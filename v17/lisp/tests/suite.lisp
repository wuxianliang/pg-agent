;;;; suite.lisp — v17 fiveam suites (shell; real suites land per-stage).

(defpackage :v17-tests
  (:use :cl :fiveam)
  (:export :run-all))

(in-package :v17-tests)

(def-suite v17 :description "v17 top-level suite")

(defun run-all ()
  (run! 'v17))
