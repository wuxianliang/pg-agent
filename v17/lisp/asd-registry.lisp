;;;; asd-registry.lisp — register v17/lisp/ in the ASDF source registry.
;;;;
;;;; Load AFTER the project-local quicklisp setup.lisp, as its own top-level
;;;; form (plan §2.1 lesson 2: quickload and references to freshly loaded
;;;; packages must not share a top-level form — READ happens before EVAL).

(require :asdf)

(let ((here (make-pathname :directory (pathname-directory *load-truename*))))
  (asdf:initialize-source-registry
   `(:source-registry (:tree ,here) :ignore-inherited-configuration)))
