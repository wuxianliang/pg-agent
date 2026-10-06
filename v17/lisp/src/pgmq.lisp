;;;; pgmq.lisp — v17 PGMQ wake-up queue protocol (plan §4).
;;;;
;;;;
;;;; Port of the pgmq slice of v12/queue_worker.py: messages on 'v12_work'
;;;; are wake-ups only — v12_requeue_stale() rebuilds them from the tables,
;;;; so losing one stalls progress but never corrupts state. All functions
;;;; run on the current postmodern connection (WITH-STORE-CONNECTION).
;;;; pgmq functions are overloaded, so every parameter carries an explicit
;;;; cast (plan §2.1 lesson 3).

(defpackage :v17-pgmq
  (:use :cl)
  (:export #:read-messages #:archive #:set-vt))

(in-package :v17-pgmq)

(defun read-messages (queue vt-seconds limit)
  "One poll cycle: up to LIMIT messages from QUEUE, each invisible for
VT-SECONDS. Returns a list of (msg-id read-ct message-alist); the message
jsonb is decoded to an alist with string keys. Autocommits (the vt bump is
a single UPDATE), which releases the row locks promptly — the same shape
as queue_worker.py's read-then-commit."
  (mapcar (lambda (row)
            (destructuring-bind (msg-id read-ct message) row
              (list msg-id read-ct
                    (let ((yason:*parse-object-as* :alist)
                          (yason:*parse-json-arrays-as-vectors* nil))
                      (yason:parse message)))))
          (postmodern:query
           "SELECT msg_id, read_ct, message::text
              FROM pgmq.read($1::text, $2::int, $3::int)"
           queue vt-seconds limit)))

(defun archive (queue msg-id)
  "Archive MSG-ID: the wake-up is fully handled. Returns true on success."
  (postmodern:query "SELECT pgmq.archive($1::text, $2::bigint)"
                    queue msg-id :single))

(defun set-vt (queue msg-id vt-seconds)
  "Hide MSG-ID for VT-SECONDS instead of archiving — the transient-failure
redelivery path (queue_worker.py RETRY_VT=2)."
  (postmodern:query "SELECT pgmq.set_vt($1::text, $2::bigint, $3::int)"
                    queue msg-id vt-seconds :single))

;;; Package lock (jiti parity): the queue protocol is trusted base a
;;; submitted form must not redefine. Must stay the last form of the file.
(sb-ext:lock-package :v17-pgmq)
