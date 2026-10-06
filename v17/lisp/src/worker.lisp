;;;; worker.lisp — v17 queue worker: polls PGMQ, does ALL external IO.
;;;;
;;;; Drop-in Lisp replacement for v12/queue_worker.py (plan §4): same queue
;;;; ('v12_work'), same message shape ({"kind": "jev"|"job", "id": uuid}),
;;;; same constants, same per-message semantics. It never advances the turn
;;;; state machine — that is the QueueDriver's SQL-only job. Crash safety
;;;; is inherited: a message read but not archived reappears after its VT;
;;;; the state machine dedupes by status ('ready' CAS, claim fence).
;;;;
;;;; Semantics mirrored from queue_worker.py (any deviation is a bug):
;;;;   VT_SECONDS = 180, RETRY_VT = 2, MAX_READ_CT = 5, LEASE = 300.
;;;;   jev: transient failure and read_ct < MAX → set_vt(2), keep message;
;;;;        else fail batch (status 'ready' CAS) → archive.
;;;;        v12_record_answers raising → re-read status: 'answered' means a
;;;;        racing worker won the CAS → archive; else fail batch.
;;;;   job: settled statuses → archive (stale wake-up); claim error →
;;;;        set_vt(2), keep message; handler outcome → v12_complete_job in
;;;;        the SAME transaction as the claim (queue_worker.py holds one
;;;;        psycopg2 transaction across claim → execute → complete).
;;;;
;;;; Invocation (see run-worker.lisp): env selects one-shot or daemon mode.
;;;;   V17_PUMP_MODE=once    one pgmq.read cycle, print ARCHIVED=n, exit
;;;;   V17_PUMP_MODE=daemon  pump until idle for V17_IDLE_EXIT_MS, print
;;;;                         ARCHIVED-TOTAL=n, exit
;;;;   V17_PUMP_LIMIT        messages per read cycle (default 10)
;;;;   V17_WORKER_ID         claimed_by identity (default v17-lw-1)

(defpackage :v17-worker
  (:use :cl)
  (:export #:main #:pump))

(in-package :v17-worker)

(defconstant +vt-seconds+ 180)
(defconstant +retry-vt+ 2)
(defconstant +max-read-ct+ 5)
(defconstant +lease-seconds+ 300)
(defconstant +queue+ "v12_work")

;;; -------------------------------------------------------------------------
;;; JSON helpers (objects as alists)
;;; -------------------------------------------------------------------------

(defun %to-json (value)
  (let ((yason:*list-encoder* #'yason:encode-alist))
    (yason:with-output-to-string* () (yason:encode-alist value))))

(defun %from-json (text)
  (when (and text (not (eq text :null)))
    (let ((yason:*parse-object-as* :alist)
          (yason:*parse-json-arrays-as-vectors* nil))
      (yason:parse text))))

(defun %get (key alist &optional default)
  (let ((cell (assoc key alist :test #'equal)))
    (if cell (cdr cell) default)))

(defun %env (name &optional default)
  (or (uiop:getenv name) default))

(defun %truncate (text limit)
  (if (> (length text) limit) (subseq text 0 limit) text))

;;; -------------------------------------------------------------------------
;;; Tool registry — the Lisp counterpart of queue_worker.py's tool_impls.
;;; Keys are jobs.kind; values are (payload-alist) -> result-alist.
;;; -------------------------------------------------------------------------

(defvar *tool-impls* (make-hash-table :test #'equal))

(defun %tool-send-summary-email (payload)
  "Demo side-effecting tool (same contract as the v12 gate's fake): record
the call in gate_side_effects when the gate created that table (cross-
process exactly-once assertion), then return the resolved recipient."
  (handler-case
      (postmodern:query
       "INSERT INTO gate_side_effects (kind, payload) VALUES ($1, $2::jsonb)"
       "send_summary_email" (%to-json payload))
    (postmodern:database-error (c)
      (unless (equal (postmodern:database-error-code c) "42P01")
        (error c))))
  (list (cons "sent_to"
              (or (%get "audience" (%get "params" payload)) "team-default"))))

(defun %tool-echo (payload)
  "Pure round-trip tool: returns the payload unchanged. The G3 jsonb
canary drives it with nested/unicode payloads."
  (list (cons "echo" payload)))

(setf (gethash "send_summary_email" *tool-impls*) #'%tool-send-summary-email
      (gethash "echo" *tool-impls*) #'%tool-echo)

;;; -------------------------------------------------------------------------
;;; jev batches
;;; -------------------------------------------------------------------------

(defun %fetch-batch (batch-id)
  "Returns (status state-alist questions-alist), or NIL when gone."
  (let ((row (postmodern:query
              "SELECT b.status, (p -> 'state')::text, (p -> 'questions')::text
                 FROM jev_batches b, LATERAL v12_request_payload(b.batch_id) p
                WHERE b.batch_id = $1::uuid"
              batch-id :row)))
    (when row
      (list (first row) (%from-json (second row)) (%from-json (third row))))))

(defun %fail-batch (batch-id error-text)
  (postmodern:query
   "UPDATE jev_batches
       SET status = 'failed', usage = jsonb_build_object('error', $2::text)
     WHERE batch_id = $1::uuid AND status = 'ready'"
   batch-id (%truncate error-text 400)))

(defun %batch-status (batch-id)
  (postmodern:query "SELECT status FROM jev_batches WHERE batch_id = $1::uuid"
                    batch-id :single))

(defun do-batch (client msg-id read-ct batch-id)
  "Answer one ready batch. Returns true when the message is done (archive)."
  (let ((fetched (%fetch-batch batch-id)))
    (if (or (null fetched) (not (equal (first fetched) "ready")))
        t                       ; stale or already handled wake-up
        (destructuring-bind (status state questions) fetched
          (declare (ignore status))
          (handler-case
              (multiple-value-bind (answers usage)
                  (v17-jev:ask client state questions)
                (handler-case
                    (progn
                      (postmodern:query
                       "SELECT v12_record_answers($1::uuid, $2::jsonb, $3::jsonb, $4::int)"
                       batch-id (%to-json answers)
                       (%to-json (or usage nil)) :null)
                      t)
                  (postmodern:database-error ()
                    (if (equal (%batch-status batch-id) "answered")
                        t       ; a racing worker won the CAS
                        (progn
                          (%fail-batch batch-id
                                       "answer validation rejected the payload")
                          t)))))
            (v17-jev:jev-error (e)
              (if (and (v17-jev:jev-error-transient-p e)
                       (< read-ct +max-read-ct+))
                  (progn (v17-pgmq:set-vt +queue+ msg-id +retry-vt+) nil)
                  (progn
                    (%fail-batch batch-id (v17-jev:jev-error-message e))
                    t))))))))

;;; -------------------------------------------------------------------------
;;; jobs (G3 effect discipline)
;;; -------------------------------------------------------------------------

(defvar *settled-statuses*
  '("succeeded" "failed" "unknown" "resolved_ok" "resolved_abandoned"))

(defun %execute-job (llm kind payload)
  "Run the effect. Returns (values result-alist outcome error-text); every
non-DB error is caught at this boundary and becomes outcome 'failed'
(queue_worker.py's except Exception)."
  (handler-case
      (cond ((equal kind "llm")
             (unless llm (error "no llm client configured"))
             (values (list (cons "text" (v17-llm:generate llm payload)))
                     "succeeded" nil))
            (t
             (let ((impl (gethash kind *tool-impls*)))
               (unless impl (error "no tool impl for ~a" kind))
               (values (funcall impl payload) "succeeded" nil))))
    (error (e)
      (values nil "failed" (%truncate (princ-to-string e) 400)))))

(defun do-job (llm msg-id job-id worker-id)
  "Claim and execute one job through the fence/lease discipline. Returns
true when the message is done (archive)."
  (let ((row (postmodern:query
              "SELECT kind, payload::text, status FROM jobs
                WHERE job_id = $1::uuid" job-id :row)))
    (if (or (null row) (member (third row) *settled-statuses* :test #'equal))
        t                               ; gone, or settled: stale wake-up
        (destructuring-bind (kind payload-json status) row
          (declare (ignore status))
          (handler-case
              (progn
                (v17-pgstore:with-store-transaction
                  (let ((fence (postmodern:query
                                "SELECT v12_claim_job($1::uuid, $2, $3::int)"
                                job-id worker-id +lease-seconds+ :single)))
                    (multiple-value-bind (result outcome error-text)
                        (%execute-job llm kind (%from-json payload-json))
                      (postmodern:query
                       "SELECT v12_complete_job($1::uuid, $2::int, $3, $4::jsonb, $5)"
                       job-id fence outcome
                       (if result (%to-json result) :null)
                       (or error-text :null)))))
                t)
            (postmodern:database-error ()
              ;; Live lease elsewhere or mid-transition: try again after VT.
              (v17-pgmq:set-vt +queue+ msg-id +retry-vt+)
              nil))))))

;;; -------------------------------------------------------------------------
;;; pump
;;; -------------------------------------------------------------------------

(defun %handle (client llm msg-id read-ct message worker-id)
  "Dispatch one wake-up. Returns true when the message is done. Malformed
wake-ups are dropped (requeue_stale can rebuild); DB errors propagate
(queue_worker.py re-raises psycopg2.Error after rollback)."
  (let ((kind (%get "kind" message))
        (id (%get "id" message)))
    (cond ((and (equal kind "jev") (stringp id))
           (do-batch client msg-id read-ct id))
          ((and (equal kind "job") (stringp id))
           (do-job llm msg-id id worker-id))
          (t t))))

(defun pump (client llm &key (limit 10) (worker-id "v17-lw-1"))
  "One poll cycle on the current store connection. Returns the number of
archived messages."
  (let ((messages (v17-pgmq:read-messages +queue+ +vt-seconds+ limit))
        (archived 0))
    (dolist (m messages archived)
      (destructuring-bind (msg-id read-ct message) m
        (when (%handle client llm msg-id read-ct message worker-id)
          (v17-pgmq:archive +queue+ msg-id)
          (incf archived))))))

;;; -------------------------------------------------------------------------
;;; entry point
;;; -------------------------------------------------------------------------

(defun %parse-positive-int (text default)
  (let ((n (and text (ignore-errors (parse-integer text :junk-allowed t)))))
    (if (and (integerp n) (plusp n)) n default)))

(defun main ()
  "Worker entry: one process, one connection, pump per V17_PUMP_MODE."
  (let* ((mode (%env "V17_PUMP_MODE" "once"))
         (limit (%parse-positive-int (%env "V17_PUMP_LIMIT") 10))
         (worker-id (%env "V17_WORKER_ID" "v17-lw-1"))
         (idle-exit-ms (%parse-positive-int (%env "V17_IDLE_EXIT_MS") 5000))
         (idle-poll-ms (%parse-positive-int (%env "V17_IDLE_POLL_MS") 200)))
    (v17-pgstore:with-store-connection ()
      (let ((client (v17-jev:make-jev-client-from-env))
            (llm (v17-llm:make-llm-client-from-env)))
        (if (equal mode "daemon")
            (let ((total 0) (idle-ms 0))
              (loop
                (let ((n (pump client llm :limit limit :worker-id worker-id)))
                  (if (plusp n)
                      (setf idle-ms 0 total (+ total n))
                      (progn
                        (incf idle-ms idle-poll-ms)
                        (when (>= idle-ms idle-exit-ms) (return))
                        (sleep (/ idle-poll-ms 1000.0))))))
              (format t "~&ARCHIVED-TOTAL=~d~%" total))
            (let ((n (pump client llm :limit limit :worker-id worker-id)))
              (format t "~&ARCHIVED=~d~%" n))))))
  (finish-output))

;;; Package lock (jiti parity). Must stay the last form of the file.
(sb-ext:lock-package :v17-worker)
