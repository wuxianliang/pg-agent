;;;; run-queue-suite.lisp — run the fiveam queue suite; exit 0 on pass.
;;;; Same bootstrap discipline as run-store-suite.lisp (plan §2.1 lesson 2).

(load "/Users/wxl/Projects/pg-agent/v17/lisp/quicklisp/setup.lisp")

(load "/Users/wxl/Projects/pg-agent/v17/lisp/asd-registry.lisp")

(ql:quickload "v17/tests" :silent t)

;; run! prints the explanation itself and returns T when nothing failed.
(uiop:quit (if (fiveam:run! 'v17-tests::queue) 0 1))
