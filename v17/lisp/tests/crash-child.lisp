;;;; crash-child.lisp — G1 crash scenario child (plan §5: crash pattern).
;;;;
;;;; Opens a transaction, INSERTs a raw lisp_revisions row (bypassing
;;;; v17_publish_revision, so no pointer CAS), prints READY, then pauses.
;;;; The Python gate SIGKILLs it after READY; the uncommitted transaction
;;;; must roll back, leaving lisp_current untouched and no orphan row.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_store \
;;;;          sbcl --script THIS <world-id> <seq>

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/pgstore" :silent t)

(let ((args (uiop:command-line-arguments)))
  (destructuring-bind (world-id seq) args
    (v17-pgstore:with-store-connection ()
      (postmodern:execute "BEGIN")
      (postmodern:query
       "INSERT INTO lisp_revisions
            (world_id, seq, state_text, manifest, sbcl_version)
        VALUES ($1::uuid, $2::int, '(half-written)', '{}'::jsonb, $3)"
       world-id (parse-integer seq) (lisp-implementation-version))
      ;; Row is visible to THIS transaction only; never COMMIT.
      (format t "READY~%")
      (finish-output)
      (loop (sleep 60)))))
