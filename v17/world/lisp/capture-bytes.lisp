;;;; capture-bytes.lisp — G2 gate: cross-process byte identity of
;;;; managed-state capture (plan §5 G2).
;;;;
;;;; Builds the same world from the same fixed operation sequence in every
;;;; process (explicit package name, no randomness), captures the managed
;;;; state vector and stores it in the gate's world_gate_captures table.
;;;; The Python gate runs this script twice and compares the two bytea
;;;; values for byte equality.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_world \
;;;;          sbcl --script THIS <label>

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/pgstore" :silent t)

(let ((label (first (uiop:command-line-arguments))))
  (unless label (error "usage: capture-bytes.lisp <label>"))
  (let* ((world (v17-kernel:make-reference-world
                 :package-name "V17-GATE-BYTES"
                 :initial '(("n" . 0) ("tags" . ("alpha" "beta")))))
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
             (act :develop "(defun square (x) (* x x))")
             (act :execute "(setf (gethash \"n\" *state*) (twice 21))")
             (let ((outcome (getf view :outcome)))
               (unless (eq (getf outcome :commit) :accepted)
                 (error "operation sequence failed: ~s" outcome))))
           (let* ((bytes (v17-kernel:capture-managed-state world))
                  (hex (with-output-to-string (s)
                         (loop for b across bytes do (format s "~(~2,'0x~)" b)))))
             (v17-pgstore:with-store-connection ()
               (postmodern:execute
                "INSERT INTO world_gate_captures (label, bytes)
                 VALUES ($1, decode($2, 'hex'))"
                label hex))
             (format t "CAPTURED ~a bytes~%" (length bytes))))
      (v17-kernel:close-session session))))
