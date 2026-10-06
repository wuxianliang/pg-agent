;;;; worldd.lisp — v17 world daemon: lisp_eval / lisp_develop / `lisp:` tools.
;;;;
;;;; The second SBCL worker mode. The queue worker (worker.lisp) replaces
;;;; the Python QueueWorker; this one adds the effect class Python cannot
;;;; express — developing and executing code inside a persistent SBCL world
;;;; whose durability is Postgres (plan §3.2/§4).
;;;;
;;;; SCAN-DRIVEN, NOT QUEUE-DRIVEN (a deliberate design choice): the daemon
;;;; discovers work by reading the jobs table:
;;;;     status = 'queued' AND tools.handler LIKE 'lisp:%'
;;;; or kind IN ('lisp_eval', 'lisp_develop'). That keeps the plan's "no new
;;;; pgmq queue, no new message kind, no new table, no v12 change"
;;;; constraint literally true, and follows the plan's own invariant that
;;;; the tables — not the messages — are the recovery path
;;;; (v12_requeue_stale). Messages stay pure wake-ups: the queue worker
;;;; ARCHIVES (without claiming) any wake-up whose job is lisp-owned, so
;;;; mixed deployments stay race-free by construction.
;;;;
;;;; CRASH-SAFETY DESIGN:
;;;;
;;;;   1. Every job starts from the DURABLE world: the CURRENT revision is
;;;;      imported into a fresh reference world. No Lisp state carries
;;;;      between jobs (and no in-memory world survives this process), so a
;;;;      process that dies mid-job leaves behind only the durable revision
;;;;      plus an unsettled job — which the claim fence makes replayable
;;;;      after its lease expires.
;;;;
;;;;   2. The kernel's PUBLISH-FN hook fires inside the attempt, after
;;;;      evaluation and the caller's invariants pass. The daemon's hook
;;;;      performs the crash-critical writes in ONE explicit transaction on
;;;;      the worker thread's connection:
;;;;         enforce goals          (a caller contract that fails aborts)
;;;;         publish-world-revision (revision INSERT + CURRENT pointer CAS)
;;;;         append-journal          the attempt's buffered events
;;;;         v12_complete_job        queue bookkeeping, fenced
;;;;      A crash anywhere before that COMMIT means the job never settled
;;;;      and the world never advanced. jiti's uncertain publication window
;;;;      is closed by Postgres's COMMIT instead of fsync ordering.
;;;;
;;;;   3. Any non-accepted outcome restores the attempt's checkpoint in
;;;;      memory, and the daemon settles the job 'failed' in its own
;;;;      transaction with a buffered journal record. Nothing advanced, so
;;;;      a lone complete_job is safe. An explicit PREVIEW is the exception:
;;;;      it restores after reporting its values, so it settles succeeded.
;;;;
;;;; ACCEPTANCE CONTRACT (plan §3.2):
;;;;   INVARIANTS gate inside the kernel's attempt, exactly as in jiti: a
;;;;   violation restores the checkpoint.
;;;;   GOALS gate at the publish hook. jiti reports goals to an interactive
;;;;   session and gates only its own loop exit; here the caller asked for a
;;;;   specific capability, so publishing a world that lacks it would
;;;;   deliver a failed effect as a succeeded one. Refusing in the hook
;;;;   aborts the attempt, and the kernel restores the checkpoint.

(defpackage :v17-worldd
  (:use :cl)
  (:export #:main #:pump))

(in-package :v17-worldd)

(defconstant +max-check-bytes+ 4096)

;;; -------------------------------------------------------------------------
;;; helpers
;;; -------------------------------------------------------------------------

(defun %env (name &optional default)
  (or (uiop:getenv name) default))

(defun %parse-positive-int (text default)
  (let ((n (and text (ignore-errors (parse-integer text :junk-allowed t)))))
    (if (and (integerp n) (plusp n)) n default)))

(defun %from-json (text)
  (when (and text (not (eq text :null)))
    (let ((yason:*parse-object-as* :alist)
          (yason:*parse-json-arrays-as-vectors* nil))
      (yason:parse text))))

(defun %get (key alist &optional default)
  (let ((cell (assoc key alist :test #'equal)))
    (if cell (cdr cell) default)))

(defun %present-p (value)
  "True when a single-column SELECT found a row with a non-NULL value.
postmodern returns Lisp NIL for a zero-row result and the keyword :null for
an SQL NULL column value, so a guard that tests only :null silently passes
an absent row — that is what once made the daemon import a CURRENT revision
that did not exist yet."
  (and value (not (eq value :null))))

(defun %to-json (value)
  "Encode any Lisp value as a JSON string. Delegates to the store, where the
encoder lives in exactly one place: yason's alist encoder mis-encodes nested
alists (pgstore documents it) and journal events are four levels deep.
JSON-TEXT, not ENCODE-JSON: the latter writes to a stream and returns the
value it encoded, which once sent a raw Lisp alist to cl-postgres."
  (v17-pgstore:json-text value))

(defvar *debug* nil
  "V17_WORLDD_DEBUG=1 prints each scanned job and its outcome to stderr. Off
by default; the daemon's authoritative report is WORLDD-HANDLED.")

(defun %debug (fmt &rest args)
  (when *debug*
    (apply #'format *error-output*
           (concatenate 'string "~&[worldd] " fmt "~%") args)
    (finish-output *error-output*)))

;;; -------------------------------------------------------------------------
;;; reading the work list
;;; -------------------------------------------------------------------------

(defstruct pending-job job-id kind payload handler status)

(defun %lisp-p (handler)
  (and (stringp handler)
       (>= (length handler) 5)
       (string= "lisp:" handler :end2 (min 5 (length handler)))))

(defun %parse-lisp-handler (handler)
  "'lisp:<world>:<fn>' -> (values world fn), or NIL when unparseable."
  (let ((parts (uiop:split-string handler :separator ":")))
    (when (and (= 3 (length parts)) (string= "lisp" (first parts)))
      (values (second parts) (third parts)))))

(defun pending-jobs (&key (limit 8))
  "The daemon's work list: jobs it owns, oldest first. A job is owned when
its kind is an explicit lisp_* kind, or its tools row names a `lisp:`
handler.

A job is offered when it is queued, or when it is CLAIMED with an expired
lease — the scan is the recovery path, exactly as v12_requeue_stale is for
the queue. That mirrors v12_claim_job's own claim condition, so the scan
offers nothing the claim would refuse, and a job whose worker died is
re-offered as soon as its lease lapses. Settled jobs are never offered."
  (mapcar (lambda (row)
            (destructuring-bind (job-id kind payload handler status) row
              (make-pending-job :job-id job-id :kind kind
                                :payload (%from-json payload)
                                :handler handler :status status)))
          (postmodern:query
           "SELECT j.job_id::text, j.kind, j.payload::text, t.handler, j.status
              FROM jobs j LEFT JOIN tools t ON t.name = j.kind
             WHERE (j.status = 'queued'
                    OR (j.status = 'claimed'
                        AND (j.lease_until IS NULL
                             OR j.lease_until < clock_timestamp())))
               AND (j.kind IN ('lisp_eval', 'lisp_develop')
                    OR t.handler LIKE 'lisp:%')
             ORDER BY j.created_at
             LIMIT $1::int"
           limit)))

;;; -------------------------------------------------------------------------
;;; job payload -> one form plus its checks
;;; -------------------------------------------------------------------------

(defstruct plan source goals invariants world)

(defun %params-alist-text (params)
  "JSON params object -> READABLE Lisp alist text with keyword keys, so a
`lisp:` tool receives ONE argument: ((:TONE . \"formal\") ...). PRIN1, not
PRINC: princ drops the quotes and the keyword colons, which produces a form
like (WHO . team) that fails at evaluation instead of carrying the value."
  (if (null params)
      "NIL"
      (let ((*print-pretty* nil) (*print-readably* t) (*print-case* :upcase))
        (prin1-to-string
         (mapcar (lambda (pair)
                   (cons (intern (string-upcase (string (car pair)))
                                 (find-package :keyword))
                         (cdr pair)))
                 params)))))

(defun %safe-text (value limit what)
  "A form/check string from JSON, bounded and non-empty: JSON gives us
strings, so anything else is rejected loudly rather than coerced."
  (unless (and (stringp value) (plusp (length value))
               (<= (length value) limit))
    (error "v17 worldd: ~a must be a non-empty string <= ~d bytes" what limit))
  value)

(defun %check-predicate (source world label)
  "Compile one caller-supplied check source into the (NAME . PREDICATE) pair
the kernel's CHECK-PREDICATES expects. The form is parsed and validated
exactly like submitted code (the policy gate applies to checks too), then
closed over by a lambda evaluated in the world's package so it sees that
world's own definitions."
  (%safe-text source +max-check-bytes+ "check")
  (let* ((*package* (v17-kernel:world-package world))
         (form (v17-kernel:validate-form
                (v17-kernel:parse-one-form source *package*))))
    (cons label (eval `(lambda () ,form)))))

(defun %checks (sources world label)
  "Compile a list of check sources, numbering each so a failed check is
identifiable. Non-strings are dropped: JSON arrays of strings are the only
supported shape, and a silently dropped check would read as a passing one."
  (let ((n 0))
    (mapcar (lambda (source)
              (%check-predicate source world
                                (format nil "~a-~d" label (incf n))))
            (remove-if-not #'stringp sources))))

(defun %plan-for (job)
  "Turn a pending job into the plan the kernel executes. Returns NIL when
the job is not lisp-owned."
  (let ((payload (pending-job-payload job)))
    (cond
      ((member (pending-job-kind job) '("lisp_eval" "lisp_develop")
               :test #'string=)
       (make-plan
        :world (%get "world" payload)
        :source (%get "source" payload)
        :goals (%get "goals" payload)
        :invariants (%get "invariants" payload)))
      ((%lisp-p (pending-job-handler job))
       (multiple-value-bind (world fn)
           (%parse-lisp-handler (pending-job-handler job))
         (unless (and world fn)
           (error "v17 worldd: malformed lisp handler ~s"
                  (pending-job-handler job)))
         (make-plan
          :world world
          ;; The params alist is DATA, so it is quoted: an unquoted
          ;; ((:WHO . "team")) inside a call form would be evaluated as a
          ;; function call whose operator is the keyword :WHO, which SBCL
          ;; reports as an opaque "illegal function call".
          :source (format nil "(~a '~a)" fn
                          (%params-alist-text (%get "params" payload)))))))))

;;; -------------------------------------------------------------------------
;;; durability hooks used by the session
;;; -------------------------------------------------------------------------

(defstruct attempt-cell
  "Per-attempt state that must cross threads: EVENTS buffered for the
journal, and FAILURE carrying a goal-enforcement message out of the publish
hook. Both are needed because the kernel's journal hook and publish hook run
on the session's WORKER thread while the failure settlement runs on the
daemon thread - a global special would be rebound per thread and one side
would observe an empty buffer, and the kernel's failure report resets the
outcome without a condition, so the reason would only say
'publication-failed'."
  events
  (failure nil))

(defun %complete-job (job-id fence outcome result error)
  "Settle the queue's job row; FENCE makes a stale worker's completion a
no-op (v12_act.sql). Uses EXECUTE, not QUERY: the function returns void."
  (postmodern:execute
   "SELECT v12_complete_job($1::uuid, $2::int, $3, $4::jsonb, $5)"
   job-id fence outcome (if result (%to-json result) :null)
   (or error :null)))

(defun %flush-journal (cell world-id)
  "Append the buffered events, oldest first, inside the caller's explicit
transaction. Keeps 'journal durable but publish rolled back' impossible
(G1 review D-17-04: that would be jiti's uncertain window in reverse)."
  (dolist (event (reverse (attempt-cell-events cell)))
    (v17-pgstore:append-journal world-id event))
  (setf (attempt-cell-events cell) nil))

(defun %check-predicate-result (entry)
  "Run one caller check and report PASS/FAIL/ERROR, never signalling: a goal
predicate that errors has not shown the capability either."
  (handler-case
      (if (funcall (cdr entry)) :pass :fail)
    (error () :error)))

(defun %enforce-goals (goals cell)
  "Record and signal (a plain error the kernel turns into
:publication-failed) when any goal did not pass, naming them so the
settlement's reason is actionable."
  (let ((failed (remove-if (lambda (entry)
                             (eq (%check-predicate-result entry) :pass))
                           goals)))
    (when failed
      (let ((message (format nil "unmet goals after evaluation: ~s"
                             (mapcar (lambda (entry)
                                       (list (car entry)
                                             (%check-predicate-result entry)))
                                     failed))))
        (setf (attempt-cell-failure cell) message)
        (error "v17 worldd: ~a" message)))))

(defun %make-durable-hooks (cell world-id job-id fence goals)
  "Build the session's durability hooks for one job.

JOURNAL-FN only fills CELL: the kernel emits events on its worker thread,
and at that moment the attempt is not yet committable. PUBLISH-FN is the
crash-critical composition point: it runs on the worker thread, opens its
own connection, and commits as ONE transaction the goal enforcement, the
revision, the buffered journal, and the queue's fenced completion.

BASELINE vs ATTEMPT: the kernel also publishes an initial revision when a
durable session starts on an empty world, before any operation is open.
That baseline publish must NOT settle the job or run the goals, so the hook
does its work only while an operation record is current."
  (list :journal-fn
        (lambda (session event)
          (declare (ignore session))
          (push event (attempt-cell-events cell)))
        :current-revision-fn
        (lambda (session)
          (declare (ignore session))
          (v17-pgstore:with-store-connection ()
            (let ((id (postmodern:query
                       "SELECT revision_id::text FROM lisp_current
                         WHERE world_id = $1::uuid"
                       world-id :single)))
              (when (%present-p id) id))))
        :publish-fn
        (lambda (session)
          (let ((operation (v17-kernel::session-operation session)))
            (v17-pgstore:with-store-connection ()
              (v17-pgstore:with-store-transaction
                (let ((revision-id
                        (v17-pgstore:publish-world-revision
                         (v17-kernel:session-world session)
                         world-id
                         :manifest `(("job" . ,job-id)
                                     ("operation" . ,(getf operation :id))))))
                  (when operation
                    (%enforce-goals goals cell)
                    (%flush-journal cell world-id)
                    (%complete-job
                     job-id fence "succeeded"
                     (list (cons "revision" revision-id)
                           (cons "values"
                                 (getf (v17-kernel:session-outcome session)
                                       :values)))
                     nil))
                  revision-id)))))))

;;; -------------------------------------------------------------------------
;;; world bootstrap: one world per package, state always re-imported
;;; -------------------------------------------------------------------------

(defvar *world-serial* 0
  "Per-process counter for fresh world packages. Every job gets its own
adapter and package, so nothing in this process carries Lisp state between
jobs; the durable state is always imported from the revision row.")

(defun %world-package-name (name)
  "A fresh package for one job's world, derived from the world name so logs
stay readable. Per-process unique: the definitions in a revision are printed
without package prefixes and read back into whatever package this job uses,
so the name only has to be unique here, not across processes."
  (let* ((text (string-upcase (string (or name "ANON"))))
         (clean (remove-if-not (lambda (c)
                                 (or (alphanumericp c) (char= c #\-)))
                               text)))
    (format nil "V17-WORLD-~a-~d"
            (if (plusp (length clean)) clean "ANON")
            (incf *world-serial*))))

(defun %ensure-world-adapter (world-name)
  "A brand-new, EMPTY reference world for this job. Empty on purpose: the
durable state is imported inside the job, so an adapter never carries
managed state from one job to the next."
  (v17-kernel:make-reference-world
   :package-name (%world-package-name world-name)
   :initial nil))

;;; -------------------------------------------------------------------------
;;; the unknown wall: a modelled external effect, gate-only
;;; -------------------------------------------------------------------------

(defvar *allow-suicide* nil
  "Test hook (V17_WORLDD_ALLOW_SUICIDE=1). When a payload carries a
suicide_after_effect key, the daemon performs a modelled EXTERNAL side
effect - a row in the gate's gate_side_effects table - and then exits before
settling the job. That is the unknown-wall scenario: the effect happened,
the job never settled, and only an explicit v12_resolve_unknown may move it.
Never enabled outside gates.")

(defun %gate-effect (label)
  "Record the modelled external effect in the same observation table the
queue gate's demo tool uses, so exactly-once assertions have one surface."
  (postmodern:execute
   "INSERT INTO gate_side_effects (kind, payload) VALUES ($1, $2::jsonb)"
   "world_suicide"
   (%to-json (list (cons "job_id" label)))))

(defun %suicide (label)
  "Die before settling, after the modelled external effect."
  (format *error-output*
          "~&v17 worldd: modelled external effect for job ~a; exiting before ~
settle~%" label)
  (finish-output *error-output*)
  (sb-ext:quit :abort t))

;;; -------------------------------------------------------------------------
;;; executing one job
;;; -------------------------------------------------------------------------

(defun %settle-succeeded (cell world-id job-id fence result)
  "Settle a job whose attempt did NOT change the managed state, or which
ended in an explicit preview. Such an attempt never fires the kernel's
publish hook (the kernel publishes only when the world changed), so without
this path a read-only evaluation would leave the job claimed forever.
Nothing advanced, so journal plus the succeeded completion in one
transaction is enough."
  (v17-pgstore:with-store-connection ()
    (v17-pgstore:with-store-transaction
      (%flush-journal cell world-id)
      (%complete-job job-id fence "succeeded" result nil))))

(defun %settle-failed (cell world-id job-id fence reason)
  "The no-advance settlement: the buffered journal and the failed completion
in one transaction. Nothing advanced, so a lone complete_job is safe."
  (handler-case
      (v17-pgstore:with-store-connection ()
        (v17-pgstore:with-store-transaction
          (%flush-journal cell world-id)
          (%complete-job job-id fence "failed" nil reason)))
    (postmodern:database-error (c)
      (declare (ignore c))
      nil)))

(defun %failed-checks (view)
  "Name the checks that did not pass, for the settlement's reason string: the
view carries the last goal/invariant results the kernel reported."
  (let* ((outcome (getf view :outcome))
         (checks (append (copy-list (getf outcome :goals))
                         (copy-list (getf outcome :invariants)))))
    (let ((failed (remove-if (lambda (entry) (eq (getf entry :status) :pass))
                             checks)))
      (or failed "(none reported)"))))

(defun %run-attempt (job-id kind world-id fence plan preview)
  "Execute one job's plan under the kernel, starting from the durable world.
Returns (values status outcome)."
  (let* ((world (%ensure-world-adapter (plan-world plan)))
         (cell (make-attempt-cell)))
    ;; 1. start from the durable world
    (let ((current (postmodern:query
                    "SELECT revision_id::text FROM lisp_current
                      WHERE world_id = $1::uuid"
                    world-id :single)))
      (%debug "attempt ~a: world ~a current ~a" job-id world-id current)
      (when (%present-p current)
        (v17-pgstore:with-store-connection ()
          (v17-pgstore:load-world-revision world world-id))))
    ;; 2. a session carrying the caller's acceptance contract and the
    ;;    crash-critical durability hooks
    (let* ((goals (%checks (plan-goals plan) world "goal"))
           (invariants (%checks (plan-invariants plan) world "invariant"))
           (hooks (%make-durable-hooks cell world-id job-id fence goals))
           (session (v17-kernel:make-session
                     world
                     :interactive t
                     :budget 8
                     :goals goals
                     :invariants invariants
                     :publish-fn (getf hooks :publish-fn)
                     :journal-fn (getf hooks :journal-fn)
                     :current-revision-fn (getf hooks :current-revision-fn))))
      (unwind-protect
           (let* ((ready (v17-kernel:session-step session))
                  (view (v17-kernel:session-step
                         session
                         (list :action (if (equal kind "lisp_develop")
                                           :develop
                                           :execute)
                               :source (plan-source plan)
                               :preview preview
                               :generation (getf ready :generation)))))
             (%debug "attempt ~a: view ~s" job-id (getf view :status))
             (let ((outcome (getf view :outcome)))
               (cond
                 ((eq (getf outcome :commit) :accepted)
                  ;; The kernel's publish hook already committed goal
                  ;; enforcement, publish, journal and complete_job when the
                  ;; world changed. A no-change evaluation never calls it,
                  ;; so that case is settled here.
                  (unless (getf outcome :changed)
                    (%settle-succeeded
                     cell world-id job-id fence
                     (list (cons "values" (getf outcome :values)))))
                  (values :accepted outcome))
                 ((and (eq (getf outcome :commit) :restored)
                       (eq (getf outcome :reason) :preview))
                  ;; An explicit preview restores the checkpoint after
                  ;; reporting its values: the caller asked to LOOK and got
                  ;; what it asked for, so the job succeeds unpublished.
                  (%settle-succeeded
                   cell world-id job-id fence
                   (list (cons "values" (getf outcome :values))
                         (cons "preview" t)))
                  (values :accepted outcome))
                 ((eq (getf outcome :commit) :restored)
                  (%settle-failed
                   cell world-id job-id fence
                   (or (attempt-cell-failure cell)
                       (format nil "~a (failed checks: ~a)"
                               (getf outcome :reason)
                               (%failed-checks view))))
                  (values :failed outcome))
                 (t
                  (%settle-failed
                   cell world-id job-id fence
                   (format nil "unsettled attempt: ~s" view))
                  (values :failed outcome)))))
        (v17-kernel:close-session session)))))

(defun %handle (job worker-id lease-seconds)
  "Claim and execute one lisp-owned job. Returns :accepted, :failed, :busy
(another worker holds the lease), or :ignored (not lisp-owned)."
  (let ((plan (%plan-for job)))
    (unless plan
      (return-from %handle :ignored))
    (let ((job-id (pending-job-job-id job)))
      (handler-case
          (let ((fence (v17-pgstore:with-store-connection ()
                         (postmodern:query
                          "SELECT v12_claim_job($1::uuid, $2, $3::int)"
                          job-id worker-id lease-seconds :single))))
            (when (and *allow-suicide*
                       (%get "suicide_after_effect" (pending-job-payload job)))
              (%gate-effect job-id)
              (%suicide job-id))
            (let* ((world-name (plan-world plan))
                   (world-id (v17-pgstore:with-store-connection ()
                               (let ((found (v17-pgstore:find-world world-name)))
                                 (%debug "job ~a: world ~a -> ~a"
                                         job-id world-name found)
                                 (if found found
                                     (v17-pgstore:create-world world-name))))))
              (%debug "job ~a: claimed (fence ~a), running attempt"
                      job-id fence)
              (multiple-value-bind (status outcome)
                  (%run-attempt job-id (pending-job-kind job) world-id fence
                                plan
                                (and (%get "preview" (pending-job-payload job))
                                     t))
                (declare (ignore outcome))
                (%debug "job ~a: ~a" job-id status)
                status)))
        (postmodern:database-error (c)
          (%debug "job ~a busy: ~a" job-id c)
          :busy)
        (error (c)
          (%debug "job ~a ERROR (not busy): ~a" job-id c)
          (error c))))))

;;; -------------------------------------------------------------------------
;;; pump
;;; -------------------------------------------------------------------------

(defun pump (&key (limit 8) (worker-id "v17-wd-1") (lease-seconds 300))
  "One scan cycle. Returns (values handled owned): HANDLED counts jobs the
daemon executed to a settlement, OWNED counts lisp jobs it saw."
  (let ((handled 0) (owned 0))
    (dolist (job (v17-pgstore:with-store-connection ()
                   (pending-jobs :limit limit)))
      (incf owned)
      (%debug "scan: job ~a kind ~a world ~a"
              (pending-job-job-id job) (pending-job-kind job)
              (let ((plan (ignore-errors (%plan-for job))))
                (and plan (plan-world plan))))
      (ecase (%handle job worker-id lease-seconds)
        (:accepted (incf handled))
        (:failed (incf handled))
        (:busy nil)
        (:ignored (decf owned))))
    (values handled owned)))

;;; -------------------------------------------------------------------------
;;; entry point
;;; -------------------------------------------------------------------------

(defun main ()
  "Scan-driven loop: keep scanning until no lisp-owned job is pending for
V17_WORLDD_IDLE_EXIT_MS, then exit 0."
  (let ((idle-exit-ms (%parse-positive-int (%env "V17_WORLDD_IDLE_EXIT_MS")
                                           5000))
        (poll-ms (%parse-positive-int (%env "V17_WORLDD_POLL_MS") 150))
        (limit (%parse-positive-int (%env "V17_WORLDD_LIMIT") 8))
        (lease (%parse-positive-int (%env "V17_WORLDD_LEASE_SECONDS") 300))
        (worker-id (%env "V17_WORLDD_ID" "v17-wd-1"))
        (idle 0)
        (handled-total 0))
    (when (equal (%env "V17_WORLDD_ALLOW_SUICIDE") "1")
      (setf *allow-suicide* t))
    (when (equal (%env "V17_WORLDD_DEBUG") "1")
      (setf *debug* t))
    (v17-pgstore:with-store-connection ()
      (loop
        (multiple-value-bind (handled owned)
            (pump :limit limit :worker-id worker-id :lease-seconds lease)
          (incf handled-total handled)
          (setf idle (if (plusp owned) 0 (+ idle poll-ms)))
          (when (>= idle idle-exit-ms) (return))
          (sleep (/ poll-ms 1000.0)))))
    (format t "~&WORLDD-HANDLED=~d~%" handled-total)
    (finish-output)))

;;; Package lock (jiti parity). Must stay the last form of the file.
(sb-ext:lock-package :v17-worldd)
