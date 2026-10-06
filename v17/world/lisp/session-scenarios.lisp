;;;; session-scenarios.lisp — G2 gate scenarios through the session
;;;; protocol (plan §5 G2): the twice example, preview restore, error back
;;;; to checkpoint via the condition loop's pause menu, stale-generation
;;;; rejection, and refusal of unrecorded definition changes.
;;;;
;;;; Usage: sbcl --script THIS   (no DB needed)
;;;; Prints PASS/FAIL lines plus RESULT lines the Python gate asserts on;
;;;; exit 0 iff every check passed.

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/kernel" :silent t)

(defvar *failures* 0)

(defun check (label ok &optional detail)
  (format t "~a ~a~@[ ~a~]~%" (if ok "PASS" "FAIL") label detail)
  (finish-output)
  (unless ok (incf *failures*)))

(let* ((world (v17-kernel:make-reference-world
               :package-name "V17-GATE-SCEN" :initial '(("n" . 0))))
       (session (v17-kernel:make-session world :interactive t :budget 60)))
  (flet ((act (view action &rest plist)
           (v17-kernel:session-step
            session (list* :action action
                           :generation (getf view :generation) plist)))
         (data-value (key)
           (cdr (assoc key
                       (getf (funcall (v17-kernel:world-managed-state world))
                             :data)
                       :test #'equal))))
    (unwind-protect
         (let ((view (v17-kernel:session-step session)))
           (check "session starts idle" (eq (getf view :status) :idle))

           ;; 1. the twice example: develop records, execute sees it
           (setf view (funcall #'act view :develop
                               :source "(defun twice (x) (* 2 x))"))
           (check "develop accepted"
                  (eq (getf (getf view :outcome) :commit) :accepted))
           (setf view (funcall #'act view :execute
                               :source "(twice (twice 3))"))
           (let ((values (getf (getf view :outcome) :values)))
             (check "twice example evaluates to 12"
                    (and (eq (getf (getf view :outcome) :commit) :accepted)
                         (= (length values) 1)
                         (equal (getf (first values) :text) "12")))
             (format t "RESULT twice-execute ~a~%" (getf (first values) :text)))

           ;; 2. stale generation is rejected, not applied
           (setf view (v17-kernel:session-step
                       session (list :action :execute :source "(twice 1)"
                                     :generation (1- (getf view :generation)))))
           (check "stale generation rejected"
                  (eq (getf view :rejected) :stale-observation))
           (format t "RESULT stale-generation rejected~%")

           ;; 3. preview: values are reported, state is restored
           (setf view (funcall #'act view :execute :preview t
                               :source "(incf (gethash \"n\" *state*))"))
           (let ((outcome (getf view :outcome)))
             (check "preview evaluated to 1"
                    (equal "1" (getf (first (getf outcome :values)) :text)))
             (check "preview restored the checkpoint"
                    (and (eq (getf outcome :commit) :restored)
                         (eq (getf outcome :reason) :preview))))
           (check "preview left state at 0" (eql (data-value "n") 0))
           (format t "RESULT preview value=1 state=0~%")

           ;; 4. an error suspends on the live restart menu; aborting
           ;;    restores the checkpoint (the half-applied mutation is gone)
           (setf view (funcall #'act view :execute
                               :source "(progn (setf (gethash \"n\" *state*) 99) (error \"boom\"))"))
           (check "error pauses with the condition on the view"
                  (and (eq (getf view :status) :paused)
                       (search "boom" (or (getf view :condition) ""))))
           (setf view (funcall #'act view :abort))
           (let ((outcome (getf view :outcome)))
             (check "abort restored the checkpoint"
                    (and (eq (getf outcome :commit) :restored)
                         (eq (getf outcome :reason) :aborted))))
           (check "failed execution left state at 0" (eql (data-value "n") 0))
           (format t "RESULT error-restored state=0~%"))
      (v17-kernel:close-session session))

    ;; 5. unrecorded definition changes are refused loudly. These are
    ;;    checked directly against the adapter, after the session is done.
    (fmakunbound (find-symbol "TWICE" (v17-kernel:world-package world)))
    (check "unrecorded fmakunbound detected at capture"
           (handler-case (progn (v17-kernel:capture-managed-state world) nil)
             (error () t)))
    (format t "RESULT unrecorded-fmakunbound refused~%")
    (setf (symbol-function (intern "ROGUE" (v17-kernel:world-package world)))
          (lambda (x) x))
    (check "unrecorded definition detected at capture"
           (handler-case (progn (v17-kernel:capture-managed-state world) nil)
             (error () t)))
    (format t "RESULT unrecorded-defun refused~%")))

(uiop:quit (if (zerop *failures*) 0 1))
