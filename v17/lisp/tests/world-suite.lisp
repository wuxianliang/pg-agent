;;;; world-suite.lisp — fiveam suite for the v17 kernel and reference world
;;;; adapter (G2).
;;;;
;;;; Covers: the form policy gate, bounded printing, deterministic
;;;; managed-state capture, the reference adapter's develop/execute/preview/
;;;; error/restore semantics through the session protocol, stale-generation
;;;; rejection, unrecorded definition-change refusal, snapshot/restore,
;;;; export/import string round-trip, catalogue content, budget and goal
;;;; behaviour, and the pgstore world revision round-trip (needs
;;;; PGSOCKETDIR/PGDATABASE in the environment; the gate supplies them).

(in-package :v17-tests)

(def-suite world :description "v17 kernel + reference world (G2)" :in v17)

(in-suite world)

;;; -------------------------------------------------------------------------
;;; Helpers
;;; -------------------------------------------------------------------------

(defun fresh-ref-world (&key (prefix "V17-SUITE") initial)
  (v17-kernel:make-reference-world
   :package-name (format nil "~a-~(~36r~)" prefix (random (expt 36 10)))
   :initial initial))

(defun world-fn (world name)
  (symbol-function (find-symbol name (v17-kernel:world-package world))))

(defun state-value (world key)
  (cdr (assoc key (getf (funcall (v17-kernel:world-managed-state world)) :data)
              :test #'equal)))

(defun act (session view action &rest plist)
  "Send ACTION with VIEW's generation and return the next view."
  (v17-kernel:session-step
   session (list* :action action :generation (getf view :generation) plist)))

(defmacro with-session ((session world &rest keys) &body body)
  `(let* ((,world (fresh-ref-world :initial '(("n" . 0))))
          (,session (v17-kernel:make-session ,world ,@keys)))
     (unwind-protect (progn ,@body)
       (v17-kernel:close-session ,session))))

;;; -------------------------------------------------------------------------
;;; Policy gate
;;; -------------------------------------------------------------------------

(test parse-one-form-exactly-one
  "exactly one form, non-empty, no trailing content, length-capped,
read-eval disabled."
  (let ((pkg (v17-kernel:world-package (fresh-ref-world))))
    (is (equal '(+ 1 2) (v17-kernel:parse-one-form "(+ 1 2)" pkg)))
    (signals v17-kernel:policy-error (v17-kernel:parse-one-form "" pkg))
    (signals v17-kernel:policy-error (v17-kernel:parse-one-form "  " pkg))
    (signals v17-kernel:policy-error
      (v17-kernel:parse-one-form "(+ 1 2) (+ 3 4)" pkg))
    (signals v17-kernel:policy-error
      (v17-kernel:parse-one-form (make-string 20000 :initial-element #\a) pkg))
    ;; #. must not evaluate at read time
    (signals error (v17-kernel:parse-one-form "#.(+ 1 2)" pkg))))

(test validate-form-conservative-gate
  "protected packages and forbidden operators are rejected even when
quoted; circular forms are rejected; an ordinary defun passes."
  ;; the ordinary case: parse in the world's package (never V17-TESTS),
  ;; then validate — the real path taken by evaluate-source
  (let ((pkg (make-package "V17-SUITE-GATE-SCRATCH" :use '(:cl))))
    (unwind-protect
         (is (eq t (and (v17-kernel:validate-form
                         (v17-kernel:parse-one-form "(defun f (x) (* 2 x))" pkg))
                        t)))
      (delete-package pkg)))
  (signals v17-kernel:policy-error
    (v17-kernel:validate-form '(funcall #'v17-kernel:close-session nil)))
  (signals v17-kernel:policy-error
    (v17-kernel:validate-form '(quote v17-kernel:make-world)))
  (signals v17-kernel:policy-error
    (v17-kernel:validate-form '(invoke-restart 'abort)))
  (signals v17-kernel:policy-error
    (v17-kernel:validate-form '(sb-ext:without-package-locks nil)))
  (let ((circular (list '+ 1 2)))
    (setf (cddr circular) circular)
    (signals v17-kernel:policy-error (v17-kernel:validate-form circular))))

(test store-packages-are-protected
  "POSTMODERN/CL-POSTGRES/SB-EXT symbols are rejected even when reached
without naming them in v17 source: once a worker thread holds the world's
store connection (G3+), (postmodern:query ...) in a submitted form would
be raw SQL past the publish/journal discipline, and SB-EXT carries the
package-lock escapes."
  (let ((pq (intern "QUERY" "POSTMODERN"))
        (ce (find-symbol "DATABASE-ERROR" "CL-POSTGRES"))
        (up (find-symbol "UNLOCK-PACKAGE" "SB-EXT")))
    (signals v17-kernel:policy-error
      (v17-kernel:validate-form (list 'funcall pq)))
    (signals v17-kernel:policy-error
      (v17-kernel:validate-form (list 'quote ce)))
    (signals v17-kernel:policy-error
      (v17-kernel:validate-form (list 'funcall up)))))

(test uninterned-symbols-rejected
  "gensyms are unreadable: two distinct uninterned symbols print
identically, which would break the total ordering deterministic capture
relies on. The form gate refuses them, and so does the capture tripwire."
  (signals v17-kernel:policy-error
    (v17-kernel:validate-form (list 'quote (make-symbol "K"))))
  (let ((w (fresh-ref-world)))
    (setf (gethash "k" (v17-kernel:reference-table w)) (make-symbol "G"))
    (signals error (v17-kernel:capture-managed-state w))))

;;; -------------------------------------------------------------------------
;;; Bounded printing and capture
;;; -------------------------------------------------------------------------

(test printed-values-are-bounded
  (let* ((long (make-string 10000 :initial-element #\x))
         (record (v17-kernel:printed-value long 100)))
    (is (getf record :truncated))
    (is (<= (length (getf record :text)) 100)))
  (let ((records (v17-kernel:printed-values (loop repeat 100 collect 'x))))
    (is (<= (length records) 32))
    (is (<= (reduce #'+ (mapcar (lambda (r) (length (getf r :text))) records))
            12000))))

(test capture-is-deterministic-and-readable-only
  "two captures of the same world are byte-identical; unreadable objects
and cycles are refused."
  (let ((w (fresh-ref-world :initial '(("n" . 0) ("s" . "text")))))
    (is (equalp (v17-kernel:capture-managed-state w)
                (v17-kernel:capture-managed-state w)))
    ;; a hash table is not a readable tree
    (setf (gethash "h" (v17-kernel:reference-table w)) (make-hash-table))
    (signals error (v17-kernel:capture-managed-state w)))
  (let ((w (fresh-ref-world)))
    (let ((cycle (list 1 2)))
      (setf (cddr cycle) cycle)
      (setf (gethash "c" (v17-kernel:reference-table w)) cycle)
      (signals error (v17-kernel:capture-managed-state w)))))

(test capture-independent-of-ambient-printer
  "capture bytes must not depend on the caller's dynamic printer
environment: sorted-data prints its sort keys with pinned printer
variables, otherwise the same world captures different bytes (in a
different pair order) under a different *package* or *print-case*."
  (let ((w (fresh-ref-world)))
    (setf (gethash "sym" (v17-kernel:reference-table w))
          (intern "THING" (v17-kernel:world-package w)))
    (let ((a (let ((*package* (v17-kernel:world-package w))
                   (*print-case* :downcase))
               (v17-kernel:capture-managed-state w)))
          (b (let ((*package* (find-package :keyword))
                   (*print-case* :upcase))
               (v17-kernel:capture-managed-state w)))
          (c (let ((*package* (find-package :cl-user)))
               (v17-kernel:capture-managed-state w))))
      (is (equalp a b))
      (is (equalp a c)))))

;;; -------------------------------------------------------------------------
;;; Session protocol over the reference world
;;; -------------------------------------------------------------------------

(test develop-then-execute
  "the twice example: develop records a defun, execute sees it."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (is (eq :idle (getf view :status)))
      (setf view (act s view :develop :source "(defun twice (x) (* 2 x))"))
      (is (eq :accepted (getf (getf view :outcome) :commit)))
      (is (eq t (getf (getf view :outcome) :changed)))
      (setf view (act s view :execute :source "(twice (twice 3))"))
      (let ((outcome (getf view :outcome)))
        (is (eq :accepted (getf outcome :commit)))
        (is (equal "12" (getf (first (getf outcome :values)) :text))))
      ;; the definition is recorded and callable
      (is (= 10 (funcall (world-fn w "TWICE") 5)))
      (is (member "TWICE"
                  (mapcar (lambda (e) (getf e :name))
                          (funcall (v17-kernel:world-catalogue w)))
                  :test #'equal)))))

(test preview-restores
  "a preview execute evaluates and reports its values, then restores the
checkpoint: the mutation is visible in the outcome and gone from the state."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (act s view :execute :preview t
                      :source "(incf (gethash \"n\" *state*))"))
      (let ((outcome (getf view :outcome)))
        (is (equal "1" (getf (first (getf outcome :values)) :text)))
        (is (eq :restored (getf outcome :commit)))
        (is (eq :preview (getf outcome :reason))))
      (is (eql 0 (state-value w "n"))))))

(test error-restores-checkpoint
  "an error suspends on the live restart menu; :abort restores the
checkpoint, so a half-applied mutation is rolled back."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (act s view :execute
                      :source "(progn (setf (gethash \"n\" *state*) 99) (error \"boom\"))"))
      (is (eq :paused (getf view :status)))
      (is (search "boom" (getf view :condition)))
      (setf view (act s view :abort))
      (let ((outcome (getf view :outcome)))
        (is (eq :restored (getf outcome :commit)))
        (is (eq :aborted (getf outcome :reason))))
      (is (eql 0 (state-value w "n"))))))

(test invariant-violation-is-unsafe
  "a violated invariant refuses the attempt and restores the checkpoint;
an unmet goal would only keep the session running (jiti acceptance
contract)."
  (let* ((w (fresh-ref-world :initial '(("n" . 0))))
         (s (v17-kernel:make-session
             w :interactive t :budget 20
             :invariants (list (cons "n-nonnegative"
                                     (lambda ()
                                       (>= (gethash "n"
                                                     (v17-kernel:reference-table w))
                                           0)))))))
    (unwind-protect
         (let ((view (v17-kernel:session-step s)))
           (setf view (act s view :execute
                           :source "(setf (gethash \"n\" *state*) -1)"))
           (let ((outcome (getf view :outcome)))
             (is (eq :restored (getf outcome :commit)))
             (is (eq :unsafe (getf outcome :reason))))
           (is (eql 0 (state-value w "n"))))
      (v17-kernel:close-session s))))

(test stale-generation-rejected
  "a proposal written against an older generation is rejected with a fresh
view instead of being applied."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (v17-kernel:session-step
                  s (list :action :execute :source "(twice 1)"
                          :generation (1- (getf view :generation)))))
      (is (eq :stale-observation (getf view :rejected))))))

(test unrecorded-changes-refused
  "a direct fmakunbound or fbind that bypassed the recorder must make the
next capture fail loudly — never silently lose definitions on recovery."
  (let ((w (fresh-ref-world)))
    (let ((s (v17-kernel:make-session w :interactive t :budget 10)))
      (unwind-protect
           (let ((view (v17-kernel:session-step s)))
             (setf view (act s view :develop
                             :source "(defun twice (x) (* 2 x))"))
             (is (eq :accepted (getf (getf view :outcome) :commit))))
        (v17-kernel:close-session s)))
    ;; unrecorded removal
    (fmakunbound (find-symbol "TWICE" (v17-kernel:world-package w)))
    (signals error (v17-kernel:capture-managed-state w))
    ;; unrecorded definition
    (let ((w2 (fresh-ref-world)))
      (setf (symbol-function (intern "ROGUE" (v17-kernel:world-package w2)))
            (lambda (x) x))
      (signals error (v17-kernel:capture-managed-state w2)))))

(test package-lock-stops-runtime-intern-bypass
  "the policy gate is lexical: a form whose source mentions only CL
symbols and strings, but which interns into V17-KERNEL at runtime to
redefine validate-form, passes the text scan — and must be stopped by the
package lock (SB-EXT:PACKAGE-LOCK-VIOLATION makes the condition loop
reject the attempt immediately). jiti kernel.lisp's second layer of
defence, restored."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (act s view :execute
                      :source "(setf (symbol-function (intern \"VALIDATE-FORM\" (find-package \"V17-KERNEL\"))) (lambda (f) f))"))
      (let ((outcome (getf view :outcome)))
        (is (eq :restored (getf outcome :commit)))
        (is (eq :rejected (getf outcome :reason))))
      ;; the gate itself survived: protected references are still refused
      (signals v17-kernel:policy-error
        (v17-kernel:validate-form '(quote v17-kernel:make-world)))
      ;; and the kernel function is untouched
      (is (eq t (and (v17-kernel:validate-form '(+ 1 2)) t))))))

(test snapshot-restore-roundtrip
  "snapshot/restore directly against the adapter: data and definitions
return to the checkpoint, including removals of functions added later."
  (let ((w (fresh-ref-world :initial '(("n" . 1)))))
    (let ((snap (funcall (v17-kernel:world-snapshot w)))
          (pkg (v17-kernel:world-package w)))
      (setf (gethash "n" (v17-kernel:reference-table w)) 42)
      (setf (symbol-function (intern "EXTRA" pkg)) (lambda () :x))
      (funcall (v17-kernel:world-restore w) snap)
      (is (eql 1 (gethash "n" (v17-kernel:reference-table w))))
      (is (not (fboundp (intern "EXTRA" pkg)))))))

(test source-trees-do-not-alias-literal-vectors
  "CL's copy-tree does not copy vectors, so a naive record/snapshot shares
a defun's literal vector with the compiled closure: mutating it through
the function would rewrite the recorded source, every checkpoint and the
export text. Recording and snapshotting deep-copy with
copy-managed-value."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (act s view :develop :source "(defun v () #(1 2 3))"))
      (is (eq :accepted (getf (getf view :outcome) :commit)))
      (setf view (act s view :execute :source "(setf (aref (v) 0) 99)"))
      (is (eq :accepted (getf (getf view :outcome) :commit)))
      ;; the recorded source (and therefore the export) is untouched
      (let ((text (funcall (v17-kernel:world-export w))))
        (is (search "#(1 2 3)" text))
        (is (not (search "99" text))))
      ;; and the catalogue agrees
      (let ((entry (find "V" (funcall (v17-kernel:world-catalogue w))
                         :key (lambda (e) (getf e :name)) :test #'equal)))
        (is (search "#(1 2 3)" (getf entry :source)))))))

(test export-import-string-roundtrip
  "export produces one readable string; importing it after a recorded
removal restores data, definitions and documentation."
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (act s view :develop :source "(defun twice (x) (* 2 x))"))
      (is (eq :accepted (getf (getf view :outcome) :commit)))
      (setf view (act s view :execute
                      :source "(setf (gethash \"n\" *state*) 7)"))
      (is (eq :accepted (getf (getf view :outcome) :commit)))
      (let ((text (funcall (v17-kernel:world-export w)))
            (capture (v17-kernel:capture-managed-state w)))
        (is (stringp text))
        ;; recorded removal of twice, then import restores it
        (setf view (act s view :develop :source "(fmakunbound 'twice)"))
        (is (eq :accepted (getf (getf view :outcome) :commit)))
        (is (not (fboundp (find-symbol "TWICE" (v17-kernel:world-package w)))))
        (funcall (v17-kernel:world-import w) text)
        (is (= 8 (funcall (world-fn w "TWICE") 4)))
        (is (eql 7 (state-value w "n")))
        (is (equalp capture (v17-kernel:capture-managed-state w))))))

(test catalogue-describes-recorded-defuns
  (with-session (s w :interactive t :budget 20)
    (let ((view (v17-kernel:session-step s)))
      (setf view (act s view :develop
                      :source "(defun twice (x) \"Double X.\" (* 2 x))"))
      (let* ((catalogue (funcall (v17-kernel:world-catalogue w)))
             (entry (find "TWICE" catalogue
                          :key (lambda (e) (getf e :name)) :test #'equal)))
        (is (not (null entry)))
        (is (equal '(x) (getf entry :arguments)))
        (is (equal "Double X." (getf entry :documentation)))
        (is (search "DEFUN" (getf entry :source)))))))

;;; -------------------------------------------------------------------------
;;; Session lifecycle edges
;;; -------------------------------------------------------------------------

(test budget-zero-exhausts-immediately
  (with-session (s w :interactive t :budget 0)
    (let ((view (v17-kernel:session-step s)))
      (is (eq :exhausted (getf view :status))))))

(test goals-reached-report-success
  "a non-interactive session whose goals already hold reports :success at
the first boundary."
  (let* ((w (fresh-ref-world :initial '(("done" . t))))
         (s (v17-kernel:make-session
             w :budget 5
             :goals (list (cons "done?"
                                (lambda ()
                                  (gethash "done"
                                           (v17-kernel:reference-table w))))))))
    (unwind-protect
         (let ((view (v17-kernel:session-step s)))
           (is (eq :success (getf view :status))))
      (v17-kernel:close-session s))))

(test world-single-owner
  "a world admits exactly one owning session at a time; closing releases it."
  (let ((w (fresh-ref-world)))
    (let ((s1 (v17-kernel:make-session w :interactive t :budget 5)))
      (signals v17-kernel:configuration-error
        (v17-kernel:make-session w :interactive t :budget 5))
      (v17-kernel:close-session s1))
    (let ((s2 (v17-kernel:make-session w :interactive t :budget 5)))
      (v17-kernel:close-session s2))))

;;; -------------------------------------------------------------------------
;;; pgstore glue: world export/import ride revision rows
;;; -------------------------------------------------------------------------

(test pgstore-world-revision-roundtrip
  "publish a world's export as a revision; mutate on; loading the revision
back restores behaviour and byte-identical managed state."
  (v17-pgstore:with-store-connection ()
    (let* ((wid (v17-pgstore:create-world
                 (format nil "suite-~(~36r~)" (random (expt 36 8)))))
           (w (fresh-ref-world :prefix "V17-SUITE-DB" :initial '(("n" . 1))))
           (s (v17-kernel:make-session w :interactive t :budget 20)))
      (unwind-protect
           (let ((view (v17-kernel:session-step s)))
             (setf view (act s view :develop
                             :source "(defun twice (x) (* 2 x))"))
             (is (eq :accepted (getf (getf view :outcome) :commit)))
             (let* ((capture (v17-kernel:capture-managed-state w))
                    (rid (v17-pgstore:with-store-transaction
                           (v17-pgstore:publish-world-revision w wid))))
               (is (stringp rid))
               ;; mutate the world past the published revision
               (setf view (act s view :develop
                               :source "(defun twice (x) (* 4 x))"))
               (is (eq :accepted (getf (getf view :outcome) :commit)))
               (is (= 8 (funcall (world-fn w "TWICE") 2)))
               ;; loading the revision back restores the published behaviour
               (v17-pgstore:load-world-revision w wid :revision-id rid)
               (is (= 4 (funcall (world-fn w "TWICE") 2)))
               (is (equalp capture (v17-kernel:capture-managed-state w)))
               (is (equal rid
                          (getf (v17-pgstore:load-revision wid) :revision-id))))))
      (v17-kernel:close-session s)))))
