;;;; publish-world.lisp — G2 gate: publish a live world's export as a
;;;; revision row (plan §5 G2: catalogue export side).
;;;;
;;;; Builds a world through the session protocol (twice, thrice, a data
;;;; mutation), publishes its export string via pgstore inside one explicit
;;;; transaction, and stores the canonical catalogue text in the gate's
;;;; world_gate_texts table for comparison with the loading process.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_world \
;;;;          sbcl --script THIS <world-name>
;;;; Prints WORLD-ID / REVISION-ID / RESULT lines for the Python gate.

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/pgstore" :silent t)

(defun canonical-catalogue (world)
  "Print the catalogue readably with pinned printer control, so two
processes produce identical text for identical recorded definitions."
  (let ((*print-readably* t) (*print-circle* nil) (*print-case* :upcase)
        (*print-pretty* nil) (*print-level* nil) (*print-length* nil)
        (*package* (find-package :keyword)))
    (prin1-to-string (funcall (v17-kernel:world-catalogue world)))))

(let ((world-name (first (uiop:command-line-arguments))))
  (unless world-name (error "usage: publish-world.lisp <world-name>"))
  (v17-pgstore:with-store-connection ()
    (let* ((world-id (v17-pgstore:create-world world-name))
           (world (v17-kernel:make-reference-world
                   :package-name "V17-GATE-PUB" :initial '(("n" . 7))))
           (session (v17-kernel:make-session world :interactive t :budget 20)))
      (unwind-protect
           (let ((view (v17-kernel:session-step session)))
             (flet ((act (action source)
                      (setf view
                            (v17-kernel:session-step
                             session (list :action action :source source
                                           :generation
                                           (getf view :generation))))))
               (act :develop "(defun twice (x) (* 2 x))")
               (act :develop "(defun thrice (x) (* 3 x))")
               (act :execute "(setf (gethash \"n\" *state*) (twice (gethash \"n\" *state*)))")
               (unless (eq (getf (getf view :outcome) :commit) :accepted)
                 (error "operation sequence failed: ~s" (getf view :outcome))))
             (let ((revision-id
                     (v17-pgstore:with-store-transaction
                       (v17-pgstore:publish-world-revision
                        world world-id
                        :manifest '(("note" . "gate-publish"))))))
               (postmodern:execute
                "INSERT INTO world_gate_texts (label, payload)
                 VALUES ('publish-catalogue', $1)"
                (canonical-catalogue world))
               (format t "WORLD-ID ~a~%REVISION-ID ~a~%RESULT published~%"
                       world-id revision-id)))
      (v17-kernel:close-session session)))))
