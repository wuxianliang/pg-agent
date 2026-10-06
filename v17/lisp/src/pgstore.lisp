;;;; pgstore.lisp — v17 Postgres-backed store (plan §3.1).
;;;;
;;;; The jiti file store (revision dirs + manifest.sexp + world.sexp, a
;;;; CURRENT pointer, an events.sexp journal) becomes five SQL functions in
;;;; v17_store.sql; this file wraps them one-to-one via postmodern.
;;;; Architecture and semantics are ported from jiti's store.lisp; the code
;;;; is written fresh (jiti carries no LICENSE).
;;;;
;;;; Connection discipline (plan §2.1 lesson 1): postmodern:connect does NOT
;;;; bind *database* — always wrap DB work in WITH-STORE-CONNECTION below.
;;;; NULL parameters must be passed as the keyword :null (cl-postgres
;;;; bind-message), and SQL NULL columns come back as :null.
;;;;
;;;; jsonb discipline (plan §2.1 lesson 3 / §7.2): jsonb inputs are strings
;;;; with an explicit $N::jsonb cast on the SQL side; jsonb outputs are cast
;;;; to text and parsed with yason.

(defpackage :v17-pgstore
  (:use :cl)
  (:export ;; connection
           #:with-store-connection
           ;; transactions (the crash-safety composition point)
           #:with-store-transaction
           #:encode-json #:json-text
           ;; conditions
           #:store-error #:store-error-message
           #:revision-version-mismatch
           #:mismatch-expected #:mismatch-actual
           ;; worlds
           #:create-world #:find-world
           ;; store interface (jiti store.lisp counterparts)
           #:publish-revision #:load-revision #:list-revisions
           #:append-journal #:recover-operations
           #:current-sbcl-version
           ;; world-level glue (G2): export/import ride the revision row's
           ;; state_text instead of a world.sexp file
           #:publish-world-revision #:load-world-revision))

(in-package :v17-pgstore)

;;; -------------------------------------------------------------------------
;;; Conditions
;;; -------------------------------------------------------------------------

(define-condition store-error (error)
  ((message :initarg :message :reader store-error-message))
  (:report (lambda (c s) (format s "v17 store: ~a" (store-error-message c))))
  (:documentation "Base condition for v17 store failures."))

(define-condition revision-version-mismatch (store-error)
  ((expected :initarg :expected :reader mismatch-expected)
   (actual   :initarg :actual   :reader mismatch-actual))
  (:report (lambda (c s)
             (format s "v17 store: revision was written by SBCL ~s, this image is ~s ~
                        (cross-version load refused, plan §7.4)"
                     (mismatch-actual c) (mismatch-expected c))))
  (:documentation "Signalled when a revision's sbcl_version does not match
this image's (lisp-implementation-version) — drift must fail loudly."))

;;; -------------------------------------------------------------------------
;;; Connection
;;; -------------------------------------------------------------------------

(defun current-sbcl-version ()
  (lisp-implementation-version))

(defun %env (name &optional default)
  (or (uiop:getenv name) default))

(defmacro with-store-connection ((&key (socket-dir '(%env "PGSOCKETDIR"))
                                       (database  '(%env "PGDATABASE" "postgres")))
                                 &body body)
  "Bind a postmodern connection over the pgembed unix socket.
SOCKET-DIR defaults to env PGSOCKETDIR (the pgembed data dir, whose socket
file is .s.PGSQL.5432), DATABASE to env PGDATABASE. The dynamic binding of
postmodern:*database* is per-thread, which is exactly the one-connection-
per-world-thread discipline the worker wants."
  `(let ((cl-postgres:*unix-socket-dir*
          (let ((dir ,socket-dir))
            (unless (and dir (plusp (length dir)))
              (error 'store-error
                     :message "PGSOCKETDIR is not set; cannot reach pgembed socket"))
            (if (char= #\/ (char dir (1- (length dir))))
                dir
                (concatenate 'string dir "/")))))
     (postmodern:with-connection (list ,database "postgres" "" :unix)
       ,@body)))

;;; -------------------------------------------------------------------------
;;; Transactions — the crash-safety composition point
;;; -------------------------------------------------------------------------
;;;
;;; The store's core promise (plan §1/§3.1) is that a worker's publish, its
;;; operation-finish journal entry and the queue's complete_job land in ONE
;;; commit — that is what makes jiti's uncertain publication window disappear.
;;; A bare postmodern:query is one autocommitted statement, so the natural
;;; call sequence (publish-revision alone, then the rest) would silently
;;; reopen exactly that window: publish committed, crash before complete_job,
;;; lease expires, another worker replays the job on an already-advanced
;;; world. WITH-STORE-TRANSACTION is therefore the exported composition
;;; point, and PUBLISH-REVISION refuses to run outside it.

(defmacro with-store-transaction (&body body)
  "Run BODY in one explicit transaction on the current store connection,
committing on normal exit and rolling back otherwise. Compose the worker's
crash-critical writes here: publish-revision + append-journal(operation-
finish) + the v12 queue complete_job must share this COMMIT (plan §3.1)."
  `(postmodern:with-transaction () ,@body))

(defun %assert-explicit-transaction (caller)
  "Refuse CALLER outside WITH-STORE-TRANSACTION. Detected via postmodern's
logical-transaction handle (cl-postgres no longer tracks the protocol
transaction-status byte); autocommit calls have no handle bound."
  (unless postmodern:*current-logical-transaction*
    (error 'store-error
           :message (format nil
                            "~a requires an explicit transaction: wrap it in ~
                             WITH-STORE-TRANSACTION so the publish, the ~
                             operation-finish journal and the queue ~
                             complete_job commit together (plan §3.1)"
                            caller))))

;;; -------------------------------------------------------------------------
;;; JSON helpers (objects as alists with string keys)
;;; -------------------------------------------------------------------------

;;; The encoder is hand-written because yason's *list-encoder* recursion
;;; breaks at the third nesting level: yason 20250622 emits
;;;   {"record":{"outcome":{"values":{"(text . 5)":null}}}}
;;; for a three-level alist (and errors outright on symbol keys). Journal
;;; events are routinely four levels deep, so the store cannot rely on it.
;;; Parsing is unaffected — yason reads these documents fine.

(defun %keyword-plist-p (value)
  "A symbol-keyed plist, e.g. the kernel's event and record plists."
  (and (consp value) (keywordp (car value)) (evenp (length value))))

(defun %plist-list-p (value)
  "A list OF plists (printed-value records, for instance), which an alist
test would mistake for a list of pairs."
  (and (consp value)
       (every (lambda (item) (and (consp item) (keywordp (car item))))
              value)))

(defun %pair-alist-p (value)
  "A list of (key . value) pairs."
  (and (consp value)
       (every (lambda (item)
                (and (consp item) (not (consp (car item)))))
              value)))

(defun %json-escape (text out)
  (write-char #\" out)
  (loop for ch across text
        do (case ch
             (#\" (write-string "\\\"" out))
             (#\\ (write-string "\\\\" out))
             (#\Newline (write-string "\\n" out))
             (#\Return (write-string "\\r" out))
             (#\Tab (write-string "\\t" out))
             (otherwise (if (< (char-code ch) 32)
                            (format out "\\u~4,'0x" (char-code ch))
                            (write-char ch out)))))
  (write-char #\" out))

(defun %json-key (key)
  (typecase key
    (string key)
    (symbol (string-downcase (symbol-name key)))
    (t (princ-to-string key))))

(defun encode-json (value &optional (out *standard-output*))
  "Encode any Lisp value as a JSON string to OUT. Plists become objects
with lowercased keys, lists of plists become arrays of objects, other
proper lists become arrays, symbols become their downcased names, and
UTF-8 text passes through unchanged."
  (flet ((comma-out (first)
           (unless first (write-char #\, out))))
    (cond ((null value) (write-string "null" out))
          ((eq value t) (write-string "true" out))
          ((stringp value) (%json-escape value out))
          ((numberp value) (princ value out))
          ((%keyword-plist-p value)
           (write-char #\{ out)
           (loop for (k v) on value by #'cddr
                 for first = t then nil
                 do (comma-out first)
                    (%json-escape (%json-key k) out)
                    (write-char #\: out)
                    (encode-json v out))
           (write-char #\} out))
          ((%plist-list-p value)
           (write-char #\[ out)
           (loop for item in value
                 for first = t then nil
                 do (comma-out first)
                    (encode-json item out))
           (write-char #\] out))
          ((%pair-alist-p value)
           (write-char #\{ out)
           (loop for pair in value
                 for first = t then nil
                 do (comma-out first)
                    (%json-escape (%json-key (car pair)) out)
                    (write-char #\: out)
                    (encode-json (cdr pair) out))
           (write-char #\} out))
          ((consp value)
           (write-char #\[ out)
           (loop for item in value
                 for first = t then nil
                 do (comma-out first)
                    (encode-json item out))
           (write-char #\] out))
          ((pathnamep value) (%json-escape (namestring value) out))
          ((symbolp value) (%json-escape (string-downcase (symbol-name value)) out))
          (t (%json-escape (princ-to-string value) out))))
  value)

(defun %to-json (alist)
  "Encode an alist (or any Lisp value) to a JSON object string."
  (with-output-to-string (out) (encode-json alist out)))

(defun json-text (value)
  "Public spelling of %TO-JSON. ENCODE-JSON writes to a stream and returns
the VALUE it encoded (handy when streaming), so a caller that wants the
string must wrap it — that asymmetry is exactly what once sent a raw Lisp
alist to cl-postgres as a bind parameter."
  (%to-json value))

(defun %from-json (text)
  "Parse a JSON string; objects become alists, arrays become lists."
  (when (and text (not (eq text :null)))
    (let ((yason:*parse-object-as* :alist)
          (yason:*parse-json-arrays-as-vectors* nil))
      (yason:parse text))))

(defun %unnull (value)
  (if (eq value :null) nil value))

;;; -------------------------------------------------------------------------
;;; Worlds
;;; -------------------------------------------------------------------------

(defun create-world (name &key (package-name "V17-WORLD"))
  "Register a persistent Lisp world; returns its world_id (uuid string)."
  (postmodern:query
   "INSERT INTO lisp_worlds (name, package_name) VALUES ($1, $2)
    RETURNING world_id::text"
   name package-name :single))

(defun find-world (name)
  "Look up a world by unique name; returns its world_id or NIL."
  (%unnull
   (postmodern:query
    "SELECT world_id::text FROM lisp_worlds WHERE name = $1" name :single)))

;;; -------------------------------------------------------------------------
;;; Store interface
;;; -------------------------------------------------------------------------

(defun publish-revision (world-id state-text &key manifest rollback-source)
  "Publish STATE-TEXT as the next revision of WORLD-ID; returns the new
revision_id. The revision INSERT and the CURRENT pointer CAS commit in the
caller's transaction (jiti's rename+fsync dance collapses into one COMMIT).
Must be called inside WITH-STORE-TRANSACTION — an autocommitted publish
would reopen jiti's uncertain window (publish committed, queue complete_job
never sent), so a bare call signals STORE-ERROR before touching the DB.
MANIFEST is an alist with string keys; key \"sbcl\" defaults to this image's
(lisp-implementation-version) and is pinned into the revision for the
load-time identity check. ROLLBACK-SOURCE, when given, marks the revision as
restoring that earlier revision (jiti's :rollback-source)."
  (%assert-explicit-transaction 'publish-revision)
  (let* ((manifest (if (assoc "sbcl" manifest :test #'equal)
                       manifest
                       (acons "sbcl" (current-sbcl-version) manifest)))
         (json (%to-json manifest)))
    (postmodern:query
     "SELECT v17_publish_revision($1::uuid, $2, $3::jsonb, $4::uuid)::text"
     world-id state-text json (or rollback-source :null)
     :single)))

(defun load-revision (world-id &key revision-id)
  "Load REVISION-ID (default: the CURRENT pointer) of WORLD-ID.
Returns a plist (:revision-id :seq :parent-id :state-text :manifest
:sbcl-version). Refuses loudly when the revision was written by a different
SBCL version (jiti load-revision identity check, plan §7.4)."
  (destructuring-bind (rid seq parent state manifest sbcl)
      (postmodern:query
       "SELECT revision_id::text, seq, parent_id::text, state_text,
               manifest::text, sbcl_version
          FROM v17_load_revision($1::uuid, $2::uuid)"
       world-id (or revision-id :null)
       :row)
    (unless (equal sbcl (current-sbcl-version))
      (error 'revision-version-mismatch
             :expected (current-sbcl-version) :actual sbcl))
    (list :revision-id rid
          :seq seq
          :parent-id (%unnull parent)
          :state-text state
          :manifest (%from-json manifest)
          :sbcl-version sbcl)))

(defun list-revisions (world-id)
  "Newest-first list of the accepted CURRENT ancestry of WORLD-ID as plists
(:revision-id :seq :parent-id :rollback-source :created-at). Ancestry
corruption (sequence holes, broken parent links, cycles, orphans, cross-world
links) raises on the SQL side."
  (mapcar (lambda (row)
            (destructuring-bind (rid seq parent rollback created) row
              (list :revision-id rid
                    :seq seq
                    :parent-id (%unnull parent)
                    :rollback-source (%unnull rollback)
                    :created-at created)))
          (postmodern:query
           "SELECT revision_id::text, seq, parent_id::text,
                   rollback_source::text, created_at::text
              FROM v17_list_revisions($1::uuid)"
           world-id)))

(defun append-journal (world-id event &key operation-id (generation 0))
  "Append EVENT (an alist, e.g. ((\"event\" . \"operation-start\")
 (\"record\" . ...))) to the world's journal; returns the no-hole seq.
Mirrors jiti append-journal; durability comes from the surrounding COMMIT
instead of per-write fsync. The SQL side validates operation-start /
operation-finish events loudly: the record must be an object with non-empty
string \"id\" and \"status\", OPERATION-ID must agree with that id, and the
operation_id column is backfilled from it when omitted (recover-operations
groups by record->>'id', so malformed records would silently fold or lose
recovery state). Must be called inside WITH-STORE-TRANSACTION, exactly
like publish-revision: an operation-finish committed while its publish
rolled back would be jiti's uncertain window in reverse (recover-operations
would report finished work whose effect never landed)."
  (%assert-explicit-transaction 'append-journal)
  (postmodern:query
   "SELECT v17_append_journal($1::uuid, $2::jsonb, $3, $4)"
   world-id (%to-json event) (or operation-id :null) generation
   :single))

(defun recover-operations (world-id)
  "Port of jiti recover-operations: walk the journal, fold records still
\"running\" to \"interrupted\", newest first, at most 100. Returns a list of
record alists."
  (%from-json
   (postmodern:query
    "SELECT v17_recover_operations($1::uuid)::text" world-id :single)))

;;; -------------------------------------------------------------------------
;;; World-level glue (G2)
;;; -------------------------------------------------------------------------
;;;
;;; jiti's export wrote world.sexp into the revision directory and import
;;; read it back. In v17 the revision row's state_text IS that file: the
;;; adapter's export hook returns one readable string and its import hook
;;; consumes one. These two wrappers are the only places that pair a world
;;; adapter with its durable identity.

(defun publish-world-revision (world world-id &key manifest rollback-source)
  "Export WORLD's managed state and publish it as the next revision of
WORLD-ID; returns the new revision_id. Must run inside
WITH-STORE-TRANSACTION — the publish and the queue's complete_job share
one COMMIT (plan §3.1/§4)."
  (%assert-explicit-transaction 'publish-world-revision)
  (publish-revision world-id (funcall (v17-kernel:world-export world))
                    :manifest manifest :rollback-source rollback-source))

(defun load-world-revision (world world-id &key revision-id)
  "Load REVISION-ID (default: CURRENT) of WORLD-ID and import its state
into WORLD. Returns the revision plist. The SBCL version identity check
from LOAD-REVISION applies — drift fails loudly before any import."
  (let ((revision (load-revision world-id :revision-id revision-id)))
    (funcall (v17-kernel:world-import world) (getf revision :state-text))
    revision))

;;; -------------------------------------------------------------------------
;;; Package lock (jiti parity — see the note at the bottom of
;;; reference-world.lisp)
;;; -------------------------------------------------------------------------
;;;
;;; The store is the other half of the trusted base a submitted form must
;;; not redefine (publish-revision's transaction discipline, the SBCL
;;; version identity check, recover-operations). Same residual boundary:
;;; the lock stops runtime redefinition from code running outside this
;;; package; it is cooperative, not adversarial. Must stay the last form
;;; of the last file defining into V17-PGSTORE.

(sb-ext:lock-package :v17-pgstore)
