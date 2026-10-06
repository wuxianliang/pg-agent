;;;; lisp-sql.lisp - G5 gate: drive a rollback through the session API.
;;;;
;;;; The kernel makes ROLLBACK worker-only (a caller submits :ROLLBACK
;;;; through SESSION-STEP), so the gate performs it in its own process:
;;;; recover the world's CURRENT revision into a fresh world, open a
;;;; session whose rollback hook publishes with a ROLLBACK-SOURCE inside
;;;; one explicit transaction (the same crash-critical composition the
;;;; world daemon uses), submit :rollback "previous", and print the new
;;;; revision.
;;;;
;;;; Usage: V17_ROLLBACK_WORLD=<name> sbcl --script THIS
;;;; Prints ROLLBACK-DONE target=<revision-id>.

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(handler-bind ((warning #'muffle-warning))
  (ql:quickload "v17/worldd" :silent t))

(defun %current-revision (world-id)
  (v17-pgstore:with-store-connection ()
    (let ((id (postmodern:query
               "SELECT revision_id::text FROM lisp_current
                  WHERE world_id = $1::uuid"
               world-id :single)))
      (when (and id (not (eq id :null))) id))))

(defun %previous-revision (world-id)
  "The revision just before CURRENT in the accepted ancestry."
  (let* ((revs (reverse (v17-pgstore:list-revisions world-id)))
         (ids (mapcar (lambda (r) (getf r :revision-id)) revs)))
    (second ids)))

(defun %rollback-hook (world world-id target)
  "Import TARGET and publish it as a revision that records its
ROLLBACK-SOURCE, all inside one explicit transaction. Returns the plist
the session-step contract expects from a rollback hook."
  (lambda (session revision)
    (declare (ignore session revision))
    (v17-pgstore:with-store-connection ()
      (v17-pgstore:with-store-transaction
        (v17-pgstore:load-world-revision world world-id :revision-id target)
        (let ((id (v17-pgstore:publish-world-revision
                   world world-id :rollback-source target)))
          (list :commit :rolled-back :revision id :source target))))))

(defun main ()
  (v17-pgstore:with-store-connection ()
    (let* ((name (or (sb-ext:posix-getenv "V17_ROLLBACK_WORLD")
                     (error "V17_ROLLBACK_WORLD is required")))
           (world-id (v17-pgstore:find-world name)))
      (unless world-id
        (error "no such world: ~a" name))
      (let ((target (%previous-revision world-id)))
        (unless target
          (error "no previous revision to roll back to"))
        (let* ((world (v17-worldd::%ensure-world-adapter name))
               (session (v17-kernel:make-session
                         world
                         :interactive t
                         :budget 8
                         :rollback-fn (%rollback-hook world world-id target)
                         :current-revision-fn
                         (lambda (s) (declare (ignore s))
                           (%current-revision world-id)))))
          (unwind-protect
               (let ((ready (v17-kernel:session-step session)))
                 (let ((view (v17-kernel:session-step
                              session
                              (list :action :rollback
                                    :revision "previous"
                                    :generation (getf ready :generation)))))
                   (let ((outcome (getf view :outcome)))
                     (format t "~&VIEW-STATUS ~s~%" (getf view :status))
                     (format t "~&VIEW-CONDITION ~s~%" (getf view :condition))
                     (unless (and outcome (getf outcome :revision))
                       (error "rollback did not publish: ~s" outcome))
                     (format t "~&ROLLBACK-DONE target=~s~%"
                             (getf outcome :revision))
                     (format t "~&ROLLBACK-COMMIT ~s~%"
                             (getf outcome :commit)))))
            (v17-kernel:close-session session)))))
    (finish-output)))

;; A --script file evaluates each top-level form; call main last.
(handler-case (main)
  (error (c)
    (format *error-output* "~&v17 rollback fatal: ~a~%" c)
    (finish-output *error-output*)
    (sb-ext:exit :code 1)))
