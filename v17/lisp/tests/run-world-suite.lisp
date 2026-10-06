;;;; run-world-suite.lisp — run the fiveam world suite; exit 0 on pass.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_world sbcl --script THIS
;;;; Plan §2.1 lesson 2: quicklisp load, registry load, quickload, and any
;;;; reference to freshly loaded packages are each their own top-level form.

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/tests" :silent t)

;; run! prints the explanation itself and returns T when nothing failed.
(uiop:quit (if (fiveam:run! 'v17-tests::world) 0 1))
