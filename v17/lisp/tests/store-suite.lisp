;;;; store-suite.lisp — fiveam suite for v17/pgstore (G1).
;;;;
;;;; Covers: publish→load round-trip, list ordering + ancestry validation,
;;;; SQL-level rollback (publish with rollback-source), journal append +
;;;; recover-operations fold, and the SBCL version identity check on load.
;;;; Requires PGSOCKETDIR / PGDATABASE in the environment (the Python gate
;;;; supplies them); every test body runs inside with-store-connection.

(in-package :v17-tests)

(def-suite store :description "v17 store (pgstore over v17_store.sql)" :in v17)

(in-suite store)

(defun fresh-world (&optional (prefix "w"))
  (v17-pgstore:create-world
   (format nil "~(~a~36r~)" prefix (random (expt 36 8)))))

(defmacro with-world ((world-id) &body body)
  `(v17-pgstore:with-store-connection ()
     (let ((,world-id (fresh-world)))
       ,@body)))

(defmacro with-tx-publish ((rid world state &rest keys) &body body)
  "Publish STATE inside an explicit transaction (the only legal way), bind
the new revision id to RID, then run BODY outside the transaction."
  `(let ((,rid (v17-pgstore:with-store-transaction
                 (v17-pgstore:publish-revision ,world ,state ,@keys))))
     ,@body))

(test publish-requires-explicit-transaction
  "autocommit publish is refused: without WITH-STORE-TRANSACTION the jiti
uncertain window would reopen (publish committed, complete_job never sent)."
  (with-world (w)
    (signals v17-pgstore:store-error
      (v17-pgstore:publish-revision w "(defparameter *t* 1)"))
    ;; nothing was published: the world still has no CURRENT ancestry
    (is (null (v17-pgstore:list-revisions w)))
    ;; inside the transaction composition point it works
    (with-tx-publish (rid w "(defparameter *t* 1)")
      (is (stringp rid))
      (is (= 1 (getf (v17-pgstore:load-revision w) :seq))))))

(test publish-load-roundtrip
  "publish then load returns the identical state/manifest, seq 1, no parent."
  (with-world (w)
    (let* ((state "(progn (defun twice (x) (* 2 x)) (defparameter *n* 41))")
           (rid (v17-pgstore:with-store-transaction
                  (v17-pgstore:publish-revision
                   w state :manifest '(("note" . "roundtrip")))))
           (rev (v17-pgstore:load-revision w)))
      (is (stringp rid))
      (is (equal rid (getf rev :revision-id)))
      (is (= 1 (getf rev :seq)))
      (is (null (getf rev :parent-id)))
      (is (equal state (getf rev :state-text)))
      (is (equal "roundtrip" (cdr (assoc "note" (getf rev :manifest)
                                          :test #'equal))))
      (is (equal (lisp-implementation-version) (getf rev :sbcl-version)))
      ;; default manifest pins the current image version
      (is (equal (lisp-implementation-version)
                 (cdr (assoc "sbcl" (getf rev :manifest) :test #'equal))))
      ;; loading an explicit revision id round-trips too
      (is (equal state (getf (v17-pgstore:load-revision w :revision-id rid)
                             :state-text))))))

(test list-order-and-ancestry
  "three publishes chain 1→2→3; list is newest first with parent links."
  (with-world (w)
    (let ((r1 (v17-pgstore:with-store-transaction
                (v17-pgstore:publish-revision w "(defparameter *a* 1)")))
          (r2 (v17-pgstore:with-store-transaction
                (v17-pgstore:publish-revision w "(defparameter *a* 2)")))
          (r3 (v17-pgstore:with-store-transaction
                (v17-pgstore:publish-revision w "(defparameter *a* 3)"))))
      (let ((revs (v17-pgstore:list-revisions w)))
        (is (= 3 (length revs)))
        (is (equal '(3 2 1) (mapcar (lambda (r) (getf r :seq)) revs)))
        (is (equal (list r3 r2 r1)
                   (mapcar (lambda (r) (getf r :revision-id)) revs)))
        (is (equal r2 (getf (first revs) :parent-id)))
        (is (equal r1 (getf (second revs) :parent-id)))
        (is (null (getf (third revs) :parent-id))))
      ;; an empty world lists nothing (no CURRENT pointer yet)
      (is (null (v17-pgstore:list-revisions (fresh-world)))))))

(test rollback-publishes-new-revision
  "rollback = publish a revision whose state is the target's, carrying
rollback-source; history stays append-only (jiti rollback-revision)."
  (with-world (w)
    (let* ((r1 (v17-pgstore:with-store-transaction
                 (v17-pgstore:publish-revision w "(defparameter *v* 1)")))
           (r2 (v17-pgstore:with-store-transaction
                 (v17-pgstore:publish-revision w "(defparameter *v* 2)")))
           (target (v17-pgstore:load-revision w :revision-id r1))
           (r3 (v17-pgstore:with-store-transaction
                 (v17-pgstore:publish-revision
                  w (getf target :state-text) :rollback-source r1))))
      (declare (ignore r2))
      (let* ((revs (v17-pgstore:list-revisions w))
             (tip (first revs)))
        (is (= 3 (length revs)))
        (is (equal r3 (getf tip :revision-id)))
        (is (equal r1 (getf tip :rollback-source)))
        (is (equal "(defparameter *v* 1)"
                   (getf (v17-pgstore:load-revision w) :state-text)))))))

(test journal-requires-explicit-transaction
  "autocommit journal append is refused, exactly like publish: an
operation-finish committed while its publish rolled back would be the
jiti uncertain window in reverse (recover-operations would report finished
work whose effect never landed)."
  (with-world (w)
    (signals v17-pgstore:store-error
      (v17-pgstore:append-journal w '(("event" . "note"))))
    ;; the refusal happened before touching the DB: nothing journaled
    (is (null (v17-pgstore:recover-operations w)))
    ;; inside the transaction composition point it works
    (is (= 1 (v17-pgstore:with-store-transaction
               (v17-pgstore:append-journal w '(("event" . "note"))))))))

(test journal-append-and-recover
  "append allocates no-hole seqs; recover folds running→interrupted and
keeps newest first, later events superseding earlier ones per record id."
  (with-world (w)
    (is (= 1 (v17-pgstore:with-store-transaction
               (v17-pgstore:append-journal
                w '(("event" . "operation-start")
                    ("record" . (("id" . "op-1") ("status" . "running")
                                 ("form" . "(+ 1 2)"))))
                :operation-id "op-1"))))
    (is (= 2 (v17-pgstore:with-store-transaction
               (v17-pgstore:append-journal
                w '(("event" . "operation-start")
                    ("record" . (("id" . "op-2") ("status" . "running"))))
                :operation-id "op-2" :generation 1))))
    (is (= 3 (v17-pgstore:with-store-transaction
               (v17-pgstore:append-journal
                w '(("event" . "operation-finish")
                    ("record" . (("id" . "op-2") ("status" . "finished")
                                 ("value" . "3"))))
                :operation-id "op-2" :generation 1))))
    (let ((ops (v17-pgstore:recover-operations w)))
      (is (= 2 (length ops)))
      ;; newest first: op-2 (finished, seq 3) before op-1 (interrupted)
      (is (equal "op-2" (cdr (assoc "id" (first ops) :test #'equal))))
      (is (equal "finished" (cdr (assoc "status" (first ops) :test #'equal))))
      (is (equal "op-1" (cdr (assoc "id" (second ops) :test #'equal))))
      (is (equal "interrupted"
                 (cdr (assoc "status" (second ops) :test #'equal)))))))

(test journal-operation-events-validated
  "operation-start/finish events are validated on write: recover-operations
groups by record->>'id', so malformed records would silently fold or lose
recovery state. Non-operation events stay free-form. operation_id must agree
with record.id and is backfilled from it when omitted."
  (with-world (w)
    ;; missing record entirely
    (signals cl-postgres:database-error
      (v17-pgstore:with-store-transaction
        (v17-pgstore:append-journal w '(("event" . "operation-start")))))
    ;; record without id
    (signals cl-postgres:database-error
      (v17-pgstore:with-store-transaction
        (v17-pgstore:append-journal
         w '(("event" . "operation-start")
             ("record" . (("status" . "running")))))))
    ;; record without status
    (signals cl-postgres:database-error
      (v17-pgstore:with-store-transaction
        (v17-pgstore:append-journal
         w '(("event" . "operation-finish")
             ("record" . (("id" . "op-x")))))))
    ;; operation_id disagreeing with record.id
    (signals cl-postgres:database-error
      (v17-pgstore:with-store-transaction
        (v17-pgstore:append-journal
         w '(("event" . "operation-start")
             ("record" . (("id" . "op-x") ("status" . "running"))))
         :operation-id "op-y")))
    ;; the rolled-back transactions leave no hole: nothing journaled
    (is (null (v17-pgstore:recover-operations w)))
    ;; non-operation events stay free-form
    (is (= 1 (v17-pgstore:with-store-transaction
               (v17-pgstore:append-journal w '(("event" . "note"))))))
    ;; well-formed operation event accepted; operation_id backfilled
    (is (= 2 (v17-pgstore:with-store-transaction
               (v17-pgstore:append-journal
                w '(("event" . "operation-start")
                    ("record" . (("id" . "op-ok") ("status" . "running"))))))))
    (is (equal "op-ok"
               (postmodern:query
                "SELECT operation_id FROM lisp_journal
                  WHERE world_id = $1::uuid AND seq = 2" w :single)))
    (is (= 1 (length (v17-pgstore:recover-operations w))))))

(test sbcl-version-mismatch-refused
  "a revision pinned to another SBCL version must fail load loudly
(plan §7.4: drift = loud failure)."
  (with-world (w)
    (v17-pgstore:with-store-transaction
      (v17-pgstore:publish-revision
       w "(defparameter *x* 0)" :manifest '(("sbcl" . "0.0.0-not-this-sbcl"))))
    (signals v17-pgstore:revision-version-mismatch
      (v17-pgstore:load-revision w))
    ;; ...while a matching revision loads fine
    (v17-pgstore:with-store-transaction
      (v17-pgstore:publish-revision w "(defparameter *x* 1)"))
    (is (equal "(defparameter *x* 1)"
               (getf (v17-pgstore:load-revision w) :state-text)))))
