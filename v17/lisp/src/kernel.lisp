;;;; kernel.lisp — v17 live-world kernel (plan §4).
;;;;
;;;; Ports the architecture and semantics of the jiti kernel: a world is a
;;;; bundle of adapter hooks behind a struct; a session is a worker thread
;;;; coupled to its controller by two mailboxes; actions carry a generation
;;;; counter so stale proposals are rejected; an attempt is checkpoint →
;;;; evaluate → acceptance contract (goals/invariants) → commit or restore;
;;;; an error inside an attempt suspends on a live restart menu that the
;;;; controller can repair through and resume. jiti carries no LICENSE, so
;;;; the code below is written fresh against those semantics (plan §7.1).
;;;;
;;;; The kernel is DB-agnostic. Durability enters through optional function
;;;; slots on the session — publish-fn, rollback-fn, journal-fn,
;;;; current-revision-fn — which the Postgres store (src/pgstore.lisp) or a
;;;; gate driver fills in. World state itself lives behind the adapter hooks
;;;; on the WORLD struct; the reference adapter is src/reference-world.lisp.

(eval-when (:compile-toplevel :load-toplevel :execute)
  (require :sb-concurrency)
  (require :sb-posix))

(defpackage :v17-kernel
  (:use :cl)
  (:export
   ;; conditions
   #:kernel-error
   #:configuration-error #:configuration-error-message
   #:policy-error #:policy-error-message
   #:infrastructure-error
   ;; world adapter protocol
   #:make-world #:world-p #:world-package
   #:world-observe #:world-snapshot #:world-restore
   #:world-export #:world-import #:world-managed-state #:world-catalogue
   #:world-record-form #:world-validate-form #:world-active-session
   ;; sessions
   #:make-session #:session-step #:close-session #:run-session
   #:session-world #:session-status #:session-generation #:session-budget
   #:session-goal #:session-goals #:session-invariants
   #:session-events #:session-outcome #:session-last-view #:session-thread
   ;; deterministic state capture and bounded printing
   #:capture-managed-state #:copy-managed-value
   #:printed-value #:printed-values #:bounded
   ;; form policy gate
   #:parse-one-form #:validate-form
   ;; acceptance predicates
   #:check-predicates #:all-pass-p
   ;; reference adapter (defined in reference-world.lisp)
   #:make-reference-world #:reference-table))

(in-package :v17-kernel)

;;; -------------------------------------------------------------------------
;;; Conditions
;;; -------------------------------------------------------------------------

(define-condition kernel-error (error) ()
  (:documentation "Base condition for v17 kernel failures."))

(define-condition configuration-error (kernel-error)
  ((message :initarg :message :reader configuration-error-message))
  (:report (lambda (c s) (write-string (configuration-error-message c) s)))
  (:documentation "Signalled when a session or store call is misconfigured."))

(define-condition policy-error (kernel-error)
  ((message :initarg :message :initform "form rejected by the policy gate"
            :reader policy-error-message))
  (:report (lambda (c s) (write-string (policy-error-message c) s)))
  (:documentation "Signalled when a submitted form violates the conservative
cooperative policy gate. Never pauses: it aborts the attempt immediately."))

(define-condition infrastructure-error (kernel-error) ()
  (:documentation "Signalled when persistence or observation itself failed.
Never pauses: the attempt cannot trust its own recovery machinery."))

;;; -------------------------------------------------------------------------
;;; World and session structs
;;; -------------------------------------------------------------------------

(defstruct (world (:constructor make-world
                    (&key package observe snapshot restore export import
                          managed-state catalogue
                          (record-form (constantly nil))
                          (validate-form (constantly nil)))))
  "A live world: a package plus adapter hooks. SNAPSHOT/RESTORE bracket an
attempt; MANAGED-STATE yields the deterministic readable tree; CATALOGUE
lists recorded definitions; EXPORT/IMPORT serialize the whole world as one
string (the revision row's state_text); VALIDATE-FORM and RECORD-FORM are
the adapter's edit policy and provenance recorder."
  package observe snapshot restore export import
  managed-state catalogue record-form validate-form
  active-session
  (ownership-lock (sb-thread:make-mutex :name "v17 world owner")))

(defstruct (session (:constructor %make-session))
  "One owning worker thread per world. INBOX/OUTBOX are the controller
channel; GENERATION advances on every report so stale proposals are
rejected; BUDGET bounds how many actions the session will still consume."
  world goal goals invariants (budget 100) interactive
  publish-fn rollback-fn journal-fn current-revision-fn
  recovery-history outcome last-view
  (status :starting) (events nil)
  (inbox (sb-concurrency:make-mailbox))
  (outbox (sb-concurrency:make-mailbox))
  thread (controller-lock (sb-thread:make-mutex :name "v17 session controller"))
  (generation 0) (pause-count 0) operation (operations nil) (closed nil))

(defvar *handling-error* nil
  "True while the condition loop is already handling an error; a nested
error aborts the attempt instead of recursing into the menu.")

(defvar *operation-counter* 0)
(defvar *operation-counter-lock*
  (sb-thread:make-mutex :name "v17 operation ids"))

(defun %next-operation-id ()
  (format nil "operation-~d-~d-~d" (get-universal-time) (sb-posix:getpid)
          (sb-thread:with-mutex (*operation-counter-lock*)
            (incf *operation-counter*))))

;;; -------------------------------------------------------------------------
;;; Deterministic managed-state capture
;;; -------------------------------------------------------------------------

(defun copy-managed-value (value &optional (active (make-hash-table :test 'eq)))
  "Deep-copy the mutable components of a readable tree (conses, vectors,
strings). Cycles are refused."
  (if (or (consp value) (vectorp value))
      (progn
        (when (gethash value active)
          (error "cyclic managed value"))
        (setf (gethash value active) t)
        (prog1 (cond ((consp value)
                      (cons (copy-managed-value (car value) active)
                            (copy-managed-value (cdr value) active)))
                     ((stringp value) (copy-seq value))
                     (t (let ((copy (copy-seq value)))
                          (loop for i below (length copy)
                                do (setf (aref copy i)
                                         (copy-managed-value (aref copy i) active)))
                          copy)))
          (remhash value active)))
      value))

(defun pinned-prin1-to-string (object)
  "Print OBJECT readably with every printer variable pinned (readably, no
circle, no depth/length caps, no pretty, arrays printed, base 10, upcase,
keyword package, standard readtable). The result does not depend on the
ambient dynamic environment; deterministic capture and deterministic
ordering both build on this."
  (let ((*print-readably* t) (*print-circle* nil)
        (*print-level* nil) (*print-length* nil) (*print-pretty* nil)
        (*print-array* t) (*print-base* 10) (*print-radix* nil)
        (*print-case* :upcase)
        (*package* (find-package :keyword))
        (*readtable* (copy-readtable nil)))
    (prin1-to-string object)))

(defun capture-managed-state (world)
  "Capture WORLD's managed state as a deterministic byte vector. The
adapter's managed-state hook must return a readable tree — interned
symbols, numbers, characters, strings, conses and plain vectors; anything
else (hash tables, closures, streams) or any cycle is an error. Uninterned
symbols are refused too: two distinct gensyms print identically, which
would break the total order deterministic capture relies on. Printing is
fully pinned — around the hook call itself as well as the final print — so
two images fed identical operations capture byte-identical vectors no
matter what dynamic printer environment the caller runs in (the
cross-process identity the G2 gate stores in Postgres and compares)."
  (let ((*print-readably* t) (*print-circle* nil)
        (*print-level* nil) (*print-length* nil) (*print-pretty* nil)
        (*print-array* t) (*print-base* 10) (*print-radix* nil)
        (*print-case* :upcase)
        (*package* (find-package :keyword))
        (*readtable* (copy-readtable nil)))
    (let ((tree (funcall (world-managed-state world)))
          (active (make-hash-table :test 'eq)))
      (labels ((walk (x)
                 (cond ((or (consp x) (vectorp x))
                        (when (gethash x active)
                          (error "cyclic managed state"))
                        (setf (gethash x active) t)
                        (if (consp x)
                            (progn (walk (car x)) (walk (cdr x)))
                            (loop for i below (length x) do (walk (aref x i))))
                        (remhash x active))
                       ((and (symbolp x) (not (symbol-package x)))
                        (error "managed state symbols must be interned, got ~s"
                               x))
                       ((not (or (null x) (symbolp x) (numberp x)
                                 (characterp x)))
                        (error "managed state must be a readable tree, got ~s"
                               x)))))
        (walk tree))
      (map 'vector #'char-code (prin1-to-string tree)))))

;;; -------------------------------------------------------------------------
;;; Bounded printing
;;; -------------------------------------------------------------------------

(defclass limited-output (sb-gray:fundamental-character-output-stream)
  ((buffer :initform (make-string-output-stream) :reader output-buffer)
   (count :initform 0 :accessor output-count)
   (limit :initarg :limit :reader output-limit)
   (tag :initarg :tag :reader output-tag))
  (:documentation "Character stream that throws :truncated to its TAG once
LIMIT characters have been written, so printing a huge or cyclic value
cannot blow up the outcome record."))

(defmethod sb-gray:stream-write-char ((stream limited-output) character)
  (when (>= (output-count stream) (output-limit stream))
    (throw (output-tag stream) :truncated))
  (incf (output-count stream))
  (write-char character (output-buffer stream))
  character)

(defmethod sb-gray:stream-line-column ((stream limited-output))
  (declare (ignore stream))
  nil)

(defun printed-value (value &optional (limit 4096))
  "Print VALUE readably into a bounded record (:text :truncated
:print-error). Circularity is printed via *print-circle*, not refused."
  (let* ((tag (gensym))
         (stream (make-instance 'limited-output :limit limit :tag tag))
         (status (catch tag
                   (handler-case
                       (let ((*print-level* nil) (*print-length* nil)
                             (*print-circle* t))
                         (prin1 value stream)
                         :complete)
                     (error () :unprintable)))))
    (list :text (get-output-stream-string (output-buffer stream))
          :truncated (not (eq status :complete))
          :print-error (eq status :unprintable))))

(defun printed-values (values)
  "Bounded print of a value list: at most 32 entries, at most 12000
characters in total, each entry capped at 4096."
  (loop with remaining = 12000
        for value in values
        for index below 32
        while (plusp remaining)
        for record = (printed-value value (min 4096 remaining))
        do (decf remaining (max 1 (length (getf record :text))))
        collect record))

(defun bounded (value &optional (limit 4096))
  "Print VALUE for humans, with tight depth/length limits; an unprintable
object becomes a placeholder string instead of an error."
  (handler-case
      (let* ((*print-level* 6) (*print-length* 30) (*print-circle* t)
             (text (princ-to-string value)))
        (subseq text 0 (min limit (length text))))
    (error () "<unprintable>")))

;;; -------------------------------------------------------------------------
;;; Form policy gate
;;; -------------------------------------------------------------------------

(defun parse-one-form (source package)
  "Read exactly one form from SOURCE in PACKAGE with *read-eval* disabled.
Empty input, trailing forms, or input over 16384 characters are policy
violations. Reader errors propagate as reader errors."
  (unless (and (stringp source) (plusp (length source))
               (<= (length source) 16384))
    (error 'policy-error
           :message "source must be a non-empty string of at most 16384 characters"))
  (let ((*read-eval* nil)
        (*readtable* (copy-readtable nil))
        (*package* package)
        (eof (list :eof)))
    (with-input-from-string (stream source)
      (let ((form (read stream nil eof)))
        (when (or (eq form eof) (not (eq (read stream nil eof) eof)))
          (error 'policy-error :message "source must contain exactly one form"))
        form))))

(defvar +protected-package-names+
  '("V17-KERNEL" "V17-PGSTORE" "V17-TESTS" "POSTMODERN" "CL-POSTGRES"
    "SB-EXT")
  "Packages no submitted form may reference, not even quoted. The v17
packages are the kernel/store/test internals. POSTMODERN and CL-POSTGRES
are protected ahead of need: once a worker thread holds the world's store
connection (G3+), a bare postmodern:query in a submitted form would be raw
SQL past the publish/journal discipline. SB-EXT carries the package-lock
escapes (unlock-package, without-package-locks). Later stages must add
their driver packages here too (DEXADOR once the LLM adapter lands).")

(defvar +forbidden-symbol-names+
  '("UNLOCK-PACKAGE" "WITHOUT-PACKAGE-LOCKS" "DISABLE-PACKAGE-LOCKS"
    "INVOKE-RESTART" "INVOKE-RESTART-INTERACTIVELY")
  "Symbol names no submitted form may reference: package-lock escapes and
direct restart invocation would cut around the condition loop.")

(defun validate-form (form)
  "Conservative cooperative gate: reject any reference to a protected
package or forbidden operator (even quoted), any uninterned symbol (a
gensym is unreadable and prints ambiguously), and any circular structure.
Returns FORM unchanged. The gate is deliberately stricter than the
evaluator — it rejects shapes that merely look like escapes. It is a
lexical gate: it cannot see symbols a form computes at runtime, so the
package locks at the bottom of the source files are the second layer that
turns a runtime intern attack into an immediate rejection."
  (let ((seen (make-hash-table :test 'eq)))
    (labels ((walk (x)
               (when (symbolp x)
                 (let ((home (symbol-package x)))
                   (unless home
                     (error 'policy-error
                            :message "uninterned symbols are not accepted"))
                   (when (member (package-name home)
                                 +protected-package-names+ :test #'string=)
                     (error 'policy-error
                            :message "form references a protected package"))
                   (when (member (symbol-name x) +forbidden-symbol-names+
                                 :test #'string=)
                     (error 'policy-error
                            :message "form references a forbidden operator"))))
               (when (or (consp x) (and (vectorp x) (not (stringp x))))
                 (when (gethash x seen)
                   (error 'policy-error
                          :message "circular forms are not accepted"))
                 (setf (gethash x seen) t)
                 (if (consp x)
                     (progn (walk (car x)) (walk (cdr x)))
                     (loop for i below (length x) do (walk (aref x i)))))))
      (walk form))
    form))

;;; -------------------------------------------------------------------------
;;; Acceptance predicates
;;; -------------------------------------------------------------------------

(defun check-predicates (checks)
  "Run each (name . thunk) in CHECKS, returning one result plist per check:
(:name n :status :pass/:fail) or (:name n :status :error :condition text).
A thunk returning a (:property-result ...) record is spliced through."
  (mapcar (lambda (entry)
            (handler-case
                (let ((result (funcall (cdr entry))))
                  (if (and (consp result) (eq (car result) :property-result))
                      (list* :name (car entry) result)
                      (list :name (car entry) :status (if result :pass :fail))))
              (error (c)
                (list :name (car entry) :status :error
                      :condition (bounded c)))))
          checks))

(defun all-pass-p (results)
  (every (lambda (r) (eq (getf r :status) :pass)) results))

;;; -------------------------------------------------------------------------
;;; Events, operations, reporting
;;; -------------------------------------------------------------------------

(defun emit (session kind &rest details)
  "Record an event on the session and, when a journal function is
configured, persist it. Journal failure is an infrastructure error: the
kernel never silently loses recovery state."
  (let ((event (list* :event kind
                      :operation-id (and (session-operation session)
                                         (getf (session-operation session) :id))
                      :generation (session-generation session)
                      details)))
    (push event (session-events session))
    (when (session-journal-fn session)
      (handler-case (funcall (session-journal-fn session) session event)
        (error () (error 'infrastructure-error))))
    event))

(defun begin-operation (session action)
  "Open an operation record for ACTION and emit :operation-start. The
completion fields are preallocated so later SETF GETF keeps the plist
identity shared with the operation history."
  (let ((source (getf action :source)))
    (let ((record (list :id (%next-operation-id)
                        :intent (getf action :action)
                        :target (getf action :revision)
                        :preview (not (null (getf action :preview)))
                        :source (and (stringp source)
                                     (subseq source 0 (min 16384 (length source))))
                        :status :running :outcome nil :revision nil
                        :base-revision
                        (and (session-current-revision-fn session)
                             (funcall (session-current-revision-fn session)
                                      session)))))
      (setf (session-operation session) record)
      (push record (session-operations session))
      (emit session :operation-start :record (copy-list record)))))

(defun finish-operation (session status)
  (when (session-operation session)
    (setf (getf (session-operation session) :status) status
          (getf (session-operation session) :outcome)
          (copy-tree (session-outcome session))
          (getf (session-operation session) :revision)
          (and (session-current-revision-fn session)
               (funcall (session-current-revision-fn session) session)))
    (emit session :operation-finish
          :record (copy-tree (session-operation session)))
    (setf (session-operation session) nil
          (session-operations session)
          (subseq (session-operations session)
                  0 (min 100 (length (session-operations session)))))))

(defun report-state (session status &rest details)
  "Set STATUS, advance the generation (invalidating every proposal written
against the previous view), observe the world, and publish the new view on
the outbox."
  (setf (session-status session) status)
  (incf (session-generation session))
  (let* ((*package* (world-package (session-world session)))
         (*print-level* 6) (*print-length* 30) (*print-circle* t)
         (observation
           (bounded (prin1-to-string
                     (funcall (world-observe (session-world session)))))))
    (emit session :observation :status status :world observation)
    (setf (session-last-view session)
          (list* :status status :generation (session-generation session)
                 :goal (session-goal session)
                 :observation observation
                 :recovery-history (bounded (session-recovery-history session))
                 :operation-id (or (getf (session-operation session) :id)
                                   (getf (session-outcome session) :operation-id))
                 :remaining (session-budget session)
                 :outcome (session-outcome session)
                 :revision (and (session-current-revision-fn session)
                                (funcall (session-current-revision-fn session)
                                         session))
                 :history (bounded (reverse (subseq (session-events session) 0
                                                    (min 8 (length
                                                            (session-events session)))))
                                   4096)
                 details))
    (sb-concurrency:send-message (session-outbox session)
                                 (session-last-view session))))

(defun receive-action (session)
  "Block on the inbox. :cancel aborts regardless of generation; every
received action costs one budget unit; a proposal written against an older
generation is answered with a fresh rejected view and the loop continues."
  (loop
    for action = (sb-concurrency:receive-message (session-inbox session))
    do (when (eq (getf action :action) :cancel)
         (throw 'abort-attempt :cancelled))
       (when (<= (session-budget session) 0)
         (throw 'abort-attempt :exhausted))
       (decf (session-budget session))
       (emit session :action :proposal (bounded action 17000))
       (if (= (or (getf action :generation) -1) (session-generation session))
           (return action)
           (progn
             (when (<= (session-budget session) 0)
               (throw 'abort-attempt :exhausted))
             (report-state session (session-status session)
                           :rejected :stale-observation
                           :condition (getf (session-last-view session) :condition)
                           :restarts (getf (session-last-view session) :restarts)
                           :goals (getf (session-last-view session) :goals)
                           :invariants
                           (getf (session-last-view session) :invariants))))))

;;; -------------------------------------------------------------------------
;;; Evaluation
;;; -------------------------------------------------------------------------

(defun evaluate-source (session source)
  "Parse, policy-check and evaluate one form in the world's package, then
let the adapter record it. Adapter refusal is a POLICY-ERROR; recording
failure is an INFRASTRUCTURE-ERROR — the eval already happened, so the
kernel cannot pretend nothing changed. Output streams are discarded: an
attempt's product is its values and its state change, never its printing."
  (let* ((world (session-world session))
         (*package* (world-package world))
         (form (validate-form (parse-one-form source *package*)))
         (*standard-output* (make-broadcast-stream))
         (*error-output* (make-broadcast-stream)))
    (handler-case (funcall (world-validate-form world) form)
      (error (c)
        (error 'policy-error
               :message (format nil "adapter refused the form: ~a" c))))
    (multiple-value-prog1 (eval form)
      (handler-case (funcall (world-record-form world) form)
        (error () (error 'infrastructure-error))))))

;;; -------------------------------------------------------------------------
;;; Catalogue inspection actions
;;; -------------------------------------------------------------------------

(defun catalogue-info (entry &key (include-source t))
  (flet ((text (key limit)
           (let ((value (getf entry key)))
             (and (stringp value) (subseq value 0 (min limit (length value))))))
         (truncated (key limit)
           (let ((value (getf entry key)))
             (and (stringp value) (> (length value) limit)))))
    (list :name (text :name 256)
          :arguments (printed-value (getf entry :arguments) 512)
          :documentation (text :documentation 512)
          :documentation-truncated (truncated :documentation 512)
          :source (and include-source (text :source 4096))
          :source-truncated (and include-source (truncated :source 4096)))))

(defun catalogue-summary (entry)
  (let ((copy (copy-list entry)))
    (remf copy :source)
    (when (stringp (getf copy :documentation))
      (setf (getf copy :documentation)
            (subseq (getf copy :documentation)
                    0 (min 256 (length (getf copy :documentation))))))
    (printed-value copy 512)))

(defun inspect-action (session action)
  (case (getf action :action)
    (:inspect
     (let* ((entries (funcall (world-catalogue (session-world session))))
            (offset (or (getf action :offset) 0))
            (start (min (length entries) (max 0 offset)))
            (end (min (length entries) (+ start 50))))
       (setf (session-outcome session)
             (list :catalogue (mapcar #'catalogue-summary
                                      (subseq entries start end))
                   :catalogue-infos (mapcar (lambda (entry)
                                              (catalogue-info entry
                                                              :include-source nil))
                                            (subseq entries start end))
                   :catalogue-count (length entries)
                   :catalogue-truncated (< end (length entries))
                   :next-offset (and (< end (length entries)) end)))))
    (:describe
     (let* ((name (getf action :name))
            (entry (and (stringp name)
                        (find name
                              (funcall (world-catalogue (session-world session)))
                              :key (lambda (e) (getf e :name))
                              :test #'string-equal))))
       (setf (session-outcome session)
             (list :function-info (and entry (catalogue-info entry))
                   :function (and entry (printed-value entry))
                   :found (not (null entry))))))
    (:operations
     (let ((records (remove (session-operation session)
                            (session-operations session) :test #'eq)))
       (setf (session-outcome session)
             (list :operations (mapcar (lambda (r) (printed-value r 1024))
                                       (subseq records 0
                                               (min 25 (length records))))
                   :operation-records (copy-tree (subseq records 0
                                                         (min 25 (length records))))
                   :operation-count (length records)
                   :operations-truncated (> (length records) 25)))))))

;;; -------------------------------------------------------------------------
;;; Condition loop: the live restart menu
;;; -------------------------------------------------------------------------

(defun condition-loop (session condition baseline)
  "Handle CONDITION raised during an attempt. Infrastructure and policy
failures abort immediately; anything else suspends the worker on a menu of
the restarts established since BASELINE, letting the controller repair
(evaluate a replacement form) and resume (invoke a chosen restart, with
arguments evaluated as a form). The pause itself spends budget."
  (when (typep condition 'infrastructure-error)
    (throw 'abort-attempt :infrastructure-failed))
  (when (or *handling-error*
            (typep condition 'policy-error)
            (typep condition 'sb-ext:package-lock-violation))
    (throw 'abort-attempt :rejected))
  (let ((*handling-error* t))
    (when (<= (session-budget session) 0)
      (throw 'abort-attempt :exhausted))
    (setf (session-outcome session)
          (list :commit :signaled :condition (bounded condition)))
    (emit session :condition
          :type (string (type-of condition)) :message (bounded condition))
    (loop
      for pause = (incf (session-pause-count session))
      for restarts = (remove-if (lambda (r) (member r baseline))
                                (compute-restarts condition))
      for menu = (loop for r in restarts
                       for i from 0
                       collect (list :id (format nil "~d/~d" pause i)
                                     :name (and (restart-name r)
                                                (string (restart-name r)))
                                     :report (bounded r)))
      do (when (<= (session-budget session) 0)
           (throw 'abort-attempt :exhausted))
         (report-state session :paused
                       :condition (bounded condition) :restarts menu
                       :goals (check-predicates (session-goals session))
                       :invariants (check-predicates (session-invariants session)))
         (let ((action (receive-action session)))
           (case (getf action :action)
             ((:develop :execute)
              (when (getf action :preview)
                (emit session :rejected :reason :nested-preview)
                (throw 'abort-attempt :nested-preview))
              ;; A repair form runs inside the suspended dynamic extent;
              ;; its failure faults the repair, not the paused computation.
              (handler-bind ((error (lambda (c) (declare (ignore c))
                                      (throw 'abort-attempt :repair-failed))))
                (evaluate-source session (getf action :source))))
             (:resume
              (let ((index (position (getf action :restart-id) menu
                                     :key (lambda (x) (getf x :id))
                                     :test #'equal)))
                (when index
                  (let ((arguments
                          (handler-bind ((error (lambda (c) (declare (ignore c))
                                                  (throw 'abort-attempt
                                                         :repair-failed))))
                            (evaluate-source session
                                             (or (getf action :arguments)
                                                 "nil")))))
                    (unless (listp arguments)
                      (throw 'abort-attempt :invalid-arguments))
                    (emit session :restart :id (getf action :restart-id))
                    ;; Errors raised while a restart transfers control occur
                    ;; in our handler, where the original handler cluster is
                    ;; inactive; restore the attempt rather than faulting the
                    ;; worker.
                    (handler-bind ((error (lambda (c) (declare (ignore c))
                                            (throw 'abort-attempt
                                                   :restart-failed))))
                      (apply #'invoke-restart (nth index restarts)
                             arguments))))))
             (:rollback
              (throw 'abort-attempt (list :rollback (getf action :revision))))
             ((:inspect :describe :operations) (inspect-action session action))
             (:check nil)
             (:abort (throw 'abort-attempt :aborted))
             (otherwise (emit session :rejected :reason :invalid-action)))))))

;;; -------------------------------------------------------------------------
;;; Attempt: checkpoint → eval → acceptance → commit or restore
;;; -------------------------------------------------------------------------

(defun attempt (session action)
  "Run one develop/execute action. Snapshot first; evaluate under the
condition loop; check invariants (a violation is unsafe and restores);
compare managed-state captures to detect change; a preview always restores
after reporting its values; an accepted change is published through the
session's publish-fn when one is configured. Any non-:accepted outcome
restores the checkpoint."
  (begin-operation session action)
  (let* ((world (session-world session))
         (checkpoint (funcall (world-snapshot world)))
         (baseline (compute-restarts))
         (before nil) (changed nil)
         (preview (and (eq (getf action :action) :execute)
                       (getf action :preview)))
         (outcome
           (catch 'abort-attempt
             (handler-case (setf before (capture-managed-state world))
               (error () (throw 'abort-attempt :state-capture-failed)))
             (let ((values
                     (handler-bind ((error (lambda (c)
                                             (condition-loop session c baseline))))
                       (multiple-value-list
                        (evaluate-source session (getf action :source))))))
               (let ((printed (printed-values values)))
                 (setf (session-outcome session)
                       (list :commit :evaluated
                             :operation-id (getf (session-operation session) :id)
                             :values printed
                             :value-count (length values)
                             :values-truncated (< (length printed)
                                                  (length values)))))
               (emit session :evaluated
                     :values (getf (session-outcome session) :values))
               (let ((results (check-predicates (session-invariants session))))
                 (emit session :invariants :results results)
                 (unless (all-pass-p results)
                   (throw 'abort-attempt :unsafe)))
               (handler-case
                   (setf changed (not (equalp before
                                              (capture-managed-state world))))
                 (error () (throw 'abort-attempt :state-capture-failed)))
               (setf (getf (session-outcome session) :changed) changed)
               (when preview (throw 'abort-attempt :preview))
               (when (and changed (session-publish-fn session))
                 (handler-case (funcall (session-publish-fn session) session)
                   (infrastructure-error ()
                     (throw 'abort-attempt :infrastructure-failed))
                   (error () (throw 'abort-attempt :publication-failed))))
               :accepted))))
    (if (eq outcome :accepted)
        (progn
          (setf (getf (session-outcome session) :commit) :accepted
                (getf (session-outcome session) :retained) t)
          (emit session :accepted :changed changed))
        (progn
          (funcall (world-restore world) checkpoint)
          (unless (eq outcome :preview)
            (setf (session-outcome session)
                  (list :operation-id (getf (session-operation session) :id))))
          (setf (getf (session-outcome session) :commit) :restored
                (getf (session-outcome session) :reason) outcome
                (getf (session-outcome session) :retained) nil)
          (emit session :restored :reason outcome)))
    (finish-operation session (if (eq outcome :accepted) :accepted :restored))
    (when (eq outcome :infrastructure-failed)
      (error 'infrastructure-error))
    outcome))

(defun perform-rollback (session action)
  "A rollback is its own operation: the durable mechanics live in the
session's rollback-fn (the store layer resolves the target, imports it,
checks invariants and publishes with a rollback-source)."
  (begin-operation session action)
  (setf (session-outcome session)
        (if (session-rollback-fn session)
            (handler-case
                (funcall (session-rollback-fn session) session
                         (getf action :revision))
              (error (c)
                (list :commit :restored :reason :rollback-failed
                      :condition (bounded c))))
            (list :commit :restored :reason :no-durable-store)))
  (setf (getf (session-outcome session) :operation-id)
        (getf (session-operation session) :id))
  (finish-operation session (getf (session-outcome session) :commit)))

;;; -------------------------------------------------------------------------
;;; Worker main loop
;;; -------------------------------------------------------------------------

(defun worker-main (session)
  (unwind-protect
       (handler-case
           (catch 'stop-worker
             (loop
               (let ((safety (check-predicates (session-invariants session)))
                     (goals (check-predicates (session-goals session))))
                 (emit session :checks :invariants safety :goals goals)
                 (unless (all-pass-p safety)
                   (report-state session :faulted :reason :invalid-baseline)
                   (return))
                 ;; A durable session whose store is empty publishes the
                 ;; initial state as revision 1 before serving actions.
                 (when (and (session-publish-fn session)
                            (session-current-revision-fn session)
                            (null (funcall (session-current-revision-fn session)
                                           session)))
                   (capture-managed-state (session-world session))
                   (funcall (session-publish-fn session) session))
                 (when (and (not (session-interactive session))
                            (all-pass-p goals))
                   (report-state session :success :goals goals)
                   (return))
                 (when (<= (session-budget session) 0)
                   (report-state session :exhausted)
                   (return))
                 (report-state session :idle :goals goals :invariants safety
                               :goals-achieved (and (session-goals session)
                                                    (all-pass-p goals)))
                 (let ((action (catch 'abort-attempt (receive-action session))))
                   (when (member action '(:cancelled :exhausted))
                     (report-state session
                                   (if (eq action :cancelled) :aborted :exhausted))
                     (return))
                   (case (getf action :action)
                     ((:develop :execute)
                      (let ((result (attempt session action)))
                        (when (and (consp result) (eq (first result) :rollback))
                          (perform-rollback session
                                            (list :action :rollback
                                                  :revision (second result))))
                        (when (member result '(:exhausted :cancelled))
                          (report-state session
                                        (if (eq result :exhausted)
                                            :exhausted :aborted))
                          (return))))
                     (:rollback (perform-rollback session action))
                     ((:inspect :describe :operations)
                      (inspect-action session action))
                     (:check nil)
                     (:abort (if (session-interactive session)
                                 (setf (session-outcome session)
                                       (list :commit :aborted))
                                 (progn
                                   (report-state session :aborted)
                                   (return))))
                     (otherwise
                      (emit session :rejected :reason :invalid-action)))))))
         (error (c)
           (setf (session-status session) :faulted)
           (when (session-operation session)
             (setf (getf (session-operation session) :status) :faulted))
           ;; Fault reporting must not re-enter the failing
           ;; persistence/observation path: push the event directly.
           (push (list :event :fault :condition (bounded c))
                 (session-events session))
           (sb-concurrency:send-message
            (session-outbox session)
            (list :status :faulted :condition (bounded c)))))
    (setf (session-closed session) t)
    (let ((world (session-world session)))
      (sb-thread:with-mutex ((world-ownership-lock world))
        (setf (world-active-session world) nil)))))

;;; -------------------------------------------------------------------------
;;; Session lifecycle
;;; -------------------------------------------------------------------------

(defun make-session (world &key goal goals invariants (budget 100) interactive
                                publish-fn rollback-fn journal-fn
                                current-revision-fn
                                recovery-history operation-history)
  "Claim WORLD and start its worker thread. Exactly one session may own a
world at a time (the ownership lock mirrors the single-master discipline
the store enforces across processes with an advisory lock)."
  (unless (and (or goals interactive)
               (integerp budget) (not (minusp budget))
               (world-package world) (world-observe world)
               (world-snapshot world) (world-restore world)
               (world-managed-state world) (world-catalogue world))
    (error 'configuration-error
           :message "supply world observe/snapshot/restore/managed-state/catalogue hooks, goals (unless interactive), and a nonnegative budget"))
  (when (and (or publish-fn rollback-fn journal-fn current-revision-fn)
             (not (and (world-export world) (world-import world))))
    (error 'configuration-error
           :message "durable sessions require world export and import hooks"))
  (let ((session (%make-session
                  :world world :goal goal :goals (copy-tree goals)
                  :invariants (copy-tree invariants) :budget budget
                  :interactive interactive
                  :publish-fn publish-fn :rollback-fn rollback-fn
                  :journal-fn journal-fn
                  :current-revision-fn current-revision-fn
                  :recovery-history recovery-history
                  :operations operation-history)))
    (sb-thread:with-mutex ((world-ownership-lock world))
      (when (world-active-session world)
        (error 'configuration-error :message "world already has an owner"))
      (setf (world-active-session world) session))
    (setf (session-thread session)
          (sb-thread:make-thread (lambda () (worker-main session))
                                 :name "v17 world worker"))
    session))

(defun session-step (session &optional action)
  "Deliver ACTION (when given) and wait for the next view. Serialized on
the controller lock, so a session speaks to exactly one controller thread."
  (sb-thread:with-mutex ((session-controller-lock session))
    (when action
      (when (session-closed session)
        (error "session is closed"))
      (sb-concurrency:send-message (session-inbox session) action))
    (or (sb-concurrency:receive-message (session-outbox session) :timeout 30)
        (error "worker did not reach a boundary within 30 seconds"))))

(defun close-session (session)
  "Cancel SESSION and wait for its worker thread to finish. :cancel is
only consumed at a receive boundary, so a worker stuck in a long
evaluation is first given five seconds; then it is interrupted with a
forced stop throw and given five more. A worker that still survives is a
loud error, never a silent orphan: a live worker keeps the world's
ownership, its DB connection, and the ability to publish into a session
the controller believes is closed. A forced stop unwinds without
restoring the current attempt's checkpoint — the emergency path trades
that for never stranding the world."
  (unless (session-closed session)
    (sb-concurrency:send-message
     (session-inbox session)
     (list :action :cancel :generation (session-generation session)))
    ;; join-thread returns the worker's values, and worker-main unwinds to
    ;; NIL — a NIL :default would read a successful join as a timeout.
    (flet ((joined-p (timeout)
             (let ((marker (gensym "JOIN-")))
               (not (eq marker
                        (sb-thread:join-thread (session-thread session)
                                               :timeout timeout
                                               :default marker))))))
      (unless (joined-p 5)
        (handler-case
            (sb-thread:interrupt-thread
             (session-thread session) (lambda () (throw 'stop-worker :forced)))
          ;; The worker exited between the join and the interrupt.
          (error () nil))
        (unless (joined-p 5)
          (error "v17 kernel: worker thread survived close-session; refusing ~
                  to leave an orphan that still owns the world")))))
  (session-status session))

(defun run-session (session proposer)
  "Drive SESSION with PROPOSER (a function from view to action plist) until
a terminal status. A proposer error is delivered as :proposal-failed."
  (unwind-protect
       (loop for view = (session-step session)
             then (session-step
                   session
                   (handler-case
                       (append (funcall proposer view)
                               (list :generation (getf view :generation)))
                     (error ()
                       (list :action :proposal-failed
                             :generation (getf view :generation)))))
             until (member (getf view :status)
                           '(:success :exhausted :faulted :aborted))
             finally (return view))
    (close-session session)))
