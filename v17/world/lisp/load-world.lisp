;;;; load-world.lisp — G2 gate: load a published revision into a fresh
;;;; process and prove behaviour and catalogue are identical (plan §5 G2:
;;;; catalogue export→import behaves the same).
;;;;
;;;; Creates a fresh reference adapter with the same package name (this
;;;; process has never seen the world), imports the CURRENT revision's
;;;; state_text through pgstore, then calls the imported functions and
;;;; stores the catalogue text and call results in world_gate_texts for the
;;;; Python gate to compare against the publishing process.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_world \
;;;;          sbcl --script THIS <world-id>

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/pgstore" :silent t)

(defun canonical-catalogue (world)
  (let ((*print-readably* t) (*print-circle* nil) (*print-case* :upcase)
        (*print-pretty* nil) (*print-level* nil) (*print-length* nil)
        (*package* (find-package :keyword)))
    (prin1-to-string (funcall (v17-kernel:world-catalogue world)))))

(let ((world-id (first (uiop:command-line-arguments))))
  (unless world-id (error "usage: load-world.lisp <world-id>"))
  (v17-pgstore:with-store-connection ()
    (let ((world (v17-kernel:make-reference-world
                  :package-name "V17-GATE-PUB")))
      (let ((revision (v17-pgstore:load-world-revision world world-id)))
        (let* ((package (v17-kernel:world-package world))
               (twice (symbol-function (find-symbol "TWICE" package)))
               (thrice (symbol-function (find-symbol "THRICE" package)))
               (value (funcall twice (funcall twice 3))))
          (unless (= value 12)
            (error "twice of twice of 3 is ~a, expected 12" value))
          (unless (= (funcall thrice 5) 15)
            (error "thrice of 5 is not 15"))
          (unless (eql (gethash "n" (v17-kernel:reference-table world)) 14)
            (error "imported data is wrong"))
          (postmodern:execute
           "INSERT INTO world_gate_texts (label, payload)
            VALUES ('load-catalogue', $1)"
           (canonical-catalogue world))
          (postmodern:execute
           "INSERT INTO world_gate_texts (label, payload)
            VALUES ('load-value', $1)"
           (prin1-to-string value))
          (format t "REVISION-SEQ ~a~%RESULT loaded value=~a~%"
                  (getf revision :seq) value))))))
