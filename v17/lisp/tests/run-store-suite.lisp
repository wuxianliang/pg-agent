;;;; run-store-suite.lisp — run the fiveam store suite; exit 0 on pass.
;;;;
;;;; Usage: PGSOCKETDIR=... PGDATABASE=agent_v17_store sbcl --script THIS
;;;; Plan §2.1 lesson 2: quicklisp load, registry load, quickload, and any
;;;; reference to freshly loaded packages are each their own top-level form
;;;; (--script reads and evaluates form by form; a shared form would READ
;;;; package prefixes before the packages exist).

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/tests" :silent t)

;; run! prints the explanation itself and returns T when nothing failed.
(uiop:quit (if (fiveam:run! 'v17-tests::store) 0 1))
