;;;; run-worker.lisp — sbcl --script entry for the v17 queue worker.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_queue \
;;;;          V17_PUMP_MODE=once|daemon V17_FAKE_JEV_SCRIPT=... \
;;;;          sbcl --script v17/lisp/run-worker.lisp
;;;; Plan §2.1 lesson 2: quicklisp load, registry load, quickload, and the
;;;; package-qualified call are each their own top-level form.

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/worker" :silent t)

(handler-case
    (progn (v17-worker:main) (uiop:quit 0))
  (error (c)
    (format *error-output* "~&v17 worker fatal: ~a~%" c)
    (finish-output *error-output*)
    (uiop:quit 1)))
