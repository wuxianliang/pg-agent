;;;; v17.asd — v17 SBCL worker system definitions (plan §4).
;;;;
;;;; Three serial systems mirroring the layering: the kernel (jiti kernel
;;;; semantics, DB-agnostic, plus the reference world adapter), the
;;;; Postgres-backed store (postmodern), and the fiveam test suites. Later
;;;; stages add src/pgmq.lisp, src/jev.lisp, src/llm.lisp and src/worker.lisp
;;;; to v17/kernel's successor systems.

(asdf:defsystem "v17/kernel"
  :description "v17 live-world kernel (jiti kernel semantics reimplemented)"
  :license "MIT"
  :serial t
  :depends-on ()
  :components ((:module "src"
                :serial t
                :components ((:file "kernel")
                             (:file "reference-world")))))

(asdf:defsystem "v17/pgstore"
  :description "v17 Postgres-backed revision store (postmodern)"
  :license "MIT"
  :serial t
  :depends-on ("v17/kernel" "postmodern" "yason" "babel")
  :components ((:module "src"
                :serial t
                :components ((:file "pgstore")))))

(asdf:defsystem "v17/worker"
  :description "v17 queue worker: pgmq wake-up protocol, Jev/LLM clients, pump"
  :license "MIT"
  :serial t
  :depends-on ("v17/pgstore" "dexador" "babel")
  :components ((:module "src"
                :serial t
                :components ((:file "pgmq")
                             (:file "jev")
                             (:file "llm")
                             (:file "worker")))))

(asdf:defsystem "v17/tests"
  :description "v17 fiveam suites"
  :license "MIT"
  :serial t
  :depends-on ("v17/kernel" "v17/pgstore" "v17/worker" "fiveam" "check-it")
  :components ((:module "tests"
                :serial t
                :components ((:file "suite")
                             (:file "store-suite")
                             (:file "world-suite")
                             (:file "queue-suite")))))

;; Umbrella so (ql:quickload "v17") loads the whole worker stack.
(asdf:defsystem "v17"
  :description "v17 SBCL worker (umbrella system)"
  :license "MIT"
  :depends-on ("v17/kernel" "v17/pgstore" "v17/worker"))
