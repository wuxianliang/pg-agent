;;;; run-worldd.lisp — sbcl --script entry for the v17 world daemon.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_lisptools \
;;;;          V17_WORLDD_* ... sbcl --script v17/lisp/run-worldd.lisp
;;;; Scan-driven (see worldd.lisp): one poll of the jobs table per
;;;; V17_WORLDD_POLL_MS, exiting after V17_WORLDD_IDLE_EXIT_MS of no
;;;; lisp-owned work. Plan §2.1 lesson 2: quicklisp load, registry load,
;;;; quickload, and the package-qualified call are separate top-level
;;;; forms.

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/worldd" :silent t)

(handler-case
    (progn (v17-worldd:main) (uiop:quit 0))
  (error (c)
    (format *error-output* "~&v17 worldd fatal: ~a~%" c)
    (finish-output *error-output*)
    (uiop:quit 1)))
