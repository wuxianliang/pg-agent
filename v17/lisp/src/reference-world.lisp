;;;; reference-world.lisp — v17 reference world adapter (plan §4).
;;;;
;;;; Ports the semantics of jiti's reference adapter: one EQUAL hash table
;;;; of readable values plus direct, named DEFUN/FMAKUNBOUND edits, with
;;;; unrecorded definition changes refused loudly at capture time. Written
;;;; fresh (jiti carries no LICENSE, plan §7.1).
;;;;
;;;; v17 adaptation: EXPORT/IMPORT produce and consume ONE readable string —
;;;; the revision row's state_text — instead of a world.sexp file. Durability
;;;; lives in pgstore (revision rows), never in the filesystem.
;;;;
;;;; Coverage boundary (same as jiti's reference adapter): no methods,
;;;; classes, files, threads, indirect definitions, or foreign effects.

(in-package :v17-kernel)

(defvar *reference-world-tables* (make-hash-table :test 'eq)
  "Adapter world object -> its state table (test/diagnostic handle).")

(defun reference-table (world)
  "The EQUAL hash table behind a reference world."
  (gethash world *reference-world-tables*))

(defun make-reference-world (&key (package-name
                                   (format nil "V17-REF-~(~36r~)"
                                           (random (expt 36 8))))
                                  initial)
  "A world whose managed state is one EQUAL hash table (bound to *STATE* in
its own package) plus the functions recorded through the adapter. INITIAL
is an alist of (key . value) readable entries.

For cross-process byte-identical captures, callers pass an explicit
PACKAGE-NAME and feed identical operation sequences; the default name is
random per image."
  (let* ((package (or (find-package package-name)
                      (make-package package-name :use '(:cl))))
         (table (make-hash-table :test 'equal))
         (sources nil)                        ; (name . defun-form), record order
         (recorded (make-hash-table :test 'eq)) ; name -> function at record time
         (state-symbol (intern "*STATE*" package)))
    (eval (list 'defvar state-symbol))
    (setf (symbol-value state-symbol) table)
    (dolist (pair initial)
      (setf (gethash (car pair) table) (cdr pair)))
    (labels
        ((sorted-data ()
           ;; Deterministic order: sort the copied pairs by their printed
           ;; representation so capture bytes do not depend on hash order.
           ;; The sort keys are printed with PINNED printer variables —
           ;; printing them in the ambient environment would make the
           ;; ordering (and hence snapshot/export bytes) depend on the
           ;; caller's *package* and *print-case*.
           (sort (loop for k being the hash-keys of table using (hash-value v)
                       collect (cons (copy-managed-value k)
                                     (copy-managed-value v)))
                 #'string< :key #'pinned-prin1-to-string))

         (install-data (pairs)
           (clrhash table)
           (dolist (pair pairs)
             (setf (gethash (car pair) table) (copy-managed-value (cdr pair))))
           (setf (symbol-value state-symbol) table))

         (local-name-p (name)
           (and (symbolp name) (eq (symbol-package name) package)))

         (removal-target (form)
           ;; Only (fmakunbound 'LOCAL-NAME) is a recordable removal.
           (unless (and (listp form) (= (length form) 2)
                        (let ((arg (second form)))
                          (and (consp arg) (eq (car arg) 'quote)
                               (= (length arg) 2)
                               (local-name-p (second arg)))))
             (error 'policy-error
                    :message "fmakunbound edits must name one local function directly"))
           (second (second form)))

         (check-edit-form (form)
           ;; The adapter's validate-form hook. Only direct edits have
           ;; recordable provenance: DEFUN of a local symbol, FMAKUNBOUND of
           ;; a quoted local symbol, possibly gathered under PROGN. Any other
           ;; mention of FMAKUNBOUND (funcall, apply, quoted) is refused —
           ;; an edit the recorder cannot see would be silently lost on
           ;; recovery.
           (labels ((leaf-scan (x)
                      (when (eq x 'fmakunbound)
                        (error 'policy-error
                               :message "fmakunbound is only allowed as a direct top-level edit"))
                      (cond ((consp x) (leaf-scan (car x)) (leaf-scan (cdr x)))
                            ((and (vectorp x) (not (stringp x)))
                             (loop for i below (length x)
                                   do (leaf-scan (aref x i))))))
                    (edit-scan (x)
                      (cond ((and (consp x) (eq (car x) 'progn))
                             (mapc #'edit-scan (cdr x)))
                            ((and (consp x) (eq (car x) 'fmakunbound))
                             (removal-target x))
                            ((and (consp x) (eq (car x) 'defun))
                             (unless (local-name-p (second x))
                               (error 'policy-error
                                      :message "defun must name a symbol in the world package"))
                             (leaf-scan (cddr x)))
                            (t (leaf-scan x)))))
             (edit-scan form)))

         (record-form (form)
           ;; The adapter's record-form hook, called after the form was
           ;; evaluated. Only the final edit per name matters. The source
           ;; tree is copied with copy-managed-value, not copy-tree:
           ;; copy-tree does not copy vectors, so a literal #(…) in the
           ;; defun body would stay EQ-shared with the compiled closure —
           ;; mutating it through the function would rewrite the recorded
           ;; source, the checkpoints and the export text.
           (check-edit-form form)
           (let ((edits nil))
             (labels ((collect (x)
                        (when (consp x)
                          (cond ((eq (car x) 'progn)
                                 (mapc #'collect (cdr x)))
                                ((member (car x) '(defun fmakunbound))
                                 (let ((name (if (eq (car x) 'defun)
                                                 (second x)
                                                 (removal-target x))))
                                   (setf edits
                                         (acons name x
                                                (remove name edits
                                                        :key #'car)))))))))
               (collect form))
             (dolist (edit edits)
               (let ((name (car edit)) (source (cdr edit)))
                 (if (eq (car source) 'fmakunbound)
                     (progn
                       (when (fboundp name)
                         (error "removal edit did not leave ~s unbound" name))
                       (setf sources (remove name sources :key #'car))
                       (remhash name recorded)
                       (setf (documentation name 'function) nil))
                     (progn
                       (setf (gethash name recorded) (symbol-function name))
                       (setf sources
                             (acons name (copy-managed-value source)
                                    (remove name sources :key #'car)))))))))

         (ordered-sources ()
           (sort (copy-list sources) #'string<
                 :key (lambda (pair) (symbol-name (car pair)))))

         (managed-state ()
           ;; The tripwire: any definition change that did not pass through
           ;; record-form is an error, never silently dropped on recovery.
           (unless (eq (symbol-value state-symbol) table)
             (error "unrecorded state binding change: *STATE* was re-bound"))
           (do-symbols (sym package)
             (when (and (eq (symbol-package sym) package) (fboundp sym))
               (unless (and (assoc sym sources)
                            (eq (symbol-function sym) (gethash sym recorded)))
                 (error "unrecorded function change on ~s; use a direct named DEFUN"
                        sym))))
           (dolist (pair sources)
             (unless (fboundp (car pair))
               (error "unrecorded function removal: ~s" (car pair))))
           (list :data (sorted-data)
                 :definitions (mapcar (lambda (pair)
                                        (copy-managed-value (cdr pair)))
                                      (ordered-sources))))

         (catalogue ()
           (mapcar (lambda (pair)
                     (let* ((form (cdr pair))
                            (body (cdddr form)))
                       (list :name (symbol-name (car pair))
                             :arguments (copy-managed-value (third form))
                             :documentation (and (stringp (first body))
                                                 (copy-seq (first body)))
                             :source (let ((*package* package)
                                           (*print-readably* t))
                                       (prin1-to-string form)))))
                   (ordered-sources)))

         (snapshot ()
           (list (sorted-data)
                 (copy-managed-value sources)
                 (loop for sym being the symbols of package
                       when (and (eq (symbol-package sym) package)
                                 (fboundp sym))
                       collect (cons sym (symbol-function sym)))))

         (restore (snap)
           (destructuring-bind (saved-data saved-sources saved-functions) snap
             (do-symbols (sym package)
               (when (and (eq (symbol-package sym) package)
                          (fboundp sym)
                          (not (assoc sym saved-functions)))
                 (fmakunbound sym)
                 (setf (documentation sym 'function) nil)))
             (install-data saved-data)
             (setf sources (copy-managed-value saved-sources))
             (clrhash recorded)
             (dolist (pair saved-functions)
               (setf (symbol-function (car pair)) (cdr pair)
                     (gethash (car pair) recorded) (cdr pair)))
             (dolist (pair sources)
               (let ((text (fourth (cdr pair))))
                 (setf (documentation (car pair) 'function)
                       (and (stringp text) (copy-seq text)))))))

         (export-state ()
           ;; The whole world as one readable string: data pairs plus each
           ;; definition's printed source, in name order. This string is the
           ;; revision row's state_text.
           (let ((*package* package)
                 (*print-readably* t) (*print-circle* nil)
                 (*print-level* nil) (*print-length* nil)
                 (*print-pretty* nil) (*print-array* t)
                 (*print-base* 10) (*print-radix* nil)
                 (*print-case* :upcase)
                 (*readtable* (copy-readtable nil)))
             (prin1-to-string
              (list :data (sorted-data)
                    :definitions (mapcar (lambda (pair)
                                           (let ((*print-readably* t))
                                             (prin1-to-string (cdr pair))))
                                         (ordered-sources))))))

         (import-state (text)
           ;; All-or-nothing: checkpoint before touching anything and
           ;; restore if any definition fails to parse, validate or
           ;; evaluate — a corrupt or hostile state_text must never leave
           ;; a half-imported world behind (the same checkpoint/restore
           ;; discipline the kernel's attempt uses for evaluations).
           (let ((*package* package)
                 (*read-eval* nil)
                 (*readtable* (copy-readtable nil)))
             (multiple-value-bind (state position) (read-from-string text)
               (unless (= position (length text))
                 (error 'policy-error
                        :message "trailing content after world state"))
               (let ((checkpoint (snapshot)))
                 (handler-case
                     (progn
                       (dolist (pair sources)
                         (fmakunbound (car pair))
                         (setf (documentation (car pair) 'function) nil))
                       (setf sources nil)
                       (clrhash recorded)
                       (install-data (getf state :data))
                       (dolist (definition-text (getf state :definitions))
                         (let ((form (validate-form
                                      (parse-one-form definition-text
                                                      package))))
                           (unless (and (consp form) (eq (car form) 'defun))
                             (error 'policy-error
                                    :message "exported definitions must be DEFUN forms"))
                           (check-edit-form form)
                           (eval form)
                           (record-form form))))
                   (error (c)
                     (restore checkpoint)
                     (error c)))))))

         (observe ()
           (list :bindings (list (list :name (symbol-name state-symbol)
                                       :type :hash-table :test :equal))
                 :data (sorted-data)
                 :definitions (mapcar #'cdr sources))))

      (let ((world (make-world :package package
                               :observe #'observe
                               :snapshot #'snapshot
                               :restore #'restore
                               :export #'export-state
                               :import #'import-state
                               :managed-state #'managed-state
                               :catalogue #'catalogue
                               :validate-form #'check-edit-form
                               :record-form #'record-form)))
        (setf (gethash world *reference-world-tables*) table)
        world))))

;;; -------------------------------------------------------------------------
;;; Package lock (jiti kernel.lisp parity)
;;; -------------------------------------------------------------------------
;;;
;;; The policy gate (validate-form) is lexical: it cannot see symbols a
;;; form constructs at runtime, so (setf (symbol-function
;;; (intern "VALIDATE-FORM" (find-package "V17-KERNEL"))) ...) mentions no
;;; protected symbol in its source text and passes the scan. Locking the
;;; kernel package turns that runtime redefinition into
;;; SB-EXT:PACKAGE-LOCK-VIOLATION, which the condition loop rejects
;;; immediately — jiti's second layer of defence, restored.
;;;
;;; This must stay the LAST top-level form of the last file that defines
;;; into V17-KERNEL. SBCL exempts code running with *package* bound to the
;;; locked package, so this file's own definitions above still load; the
;;; exemption is also the known residual boundary (shared with jiti): the
;;; gate is cooperative, not an adversarial sandbox — a form that rebinds
;;; *package* to a locked package before redefining escapes the lock.

(sb-ext:lock-package :v17-kernel)
