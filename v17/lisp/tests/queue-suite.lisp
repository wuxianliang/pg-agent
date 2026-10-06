;;;; queue-suite.lisp — fiveam suite for the v17 queue worker (G3).
;;;;
;;;; Pure-Lisp coverage that does not need a live queue: fake-Jev rule
;;;; matching and transient-failure accounting (the state file is the
;;;; cross-process assertion surface), fake-LLM call counting, and the
;;;; JSON alist round-trip the worker's SQL casts rely on. End-to-end
;;;; pump/batch/job behaviour is covered by the Python gate, which drives
;;;; real worker processes against agent_v17_queue.

(in-package :v17-tests)

(def-suite queue :description "v17 queue worker (fake clients, json)" :in v17)

(in-suite queue)

(defun %tmp (name)
  (format nil "/tmp/v17-queue-suite-~a-~36r" name (random (expt 36 8))))

(defun %write (path text)
  (ensure-directories-exist path)
  (with-open-file (s path :direction :output :if-exists :supersede
                          :if-does-not-exist :create)
    (write-string text s)))

(defun %slurp-json (path)
  (let ((yason:*parse-object-as* :alist)
        (yason:*parse-json-arrays-as-vectors* nil))
    (yason:parse (uiop:read-file-string path))))

(defun %get (key alist)
  (cdr (assoc key alist :test #'equal)))

(test fake-jev-first-match-wins
  "Rules are tried in order; the first whose match keys are all present
in the questions wins (v12 FakeJev.scripts order semantics)."
  (let ((script (%tmp "script" )))
    (%write script
            "{\"rules\":[{\"match\":[\"intent\"],\"answers\":{\"intent\":{\"type\":\"noul\",\"noul\":1}}},{\"match\":[\"intent\"],\"answers\":{\"intent\":{\"type\":\"noul\",\"noul\":2}}}]}")
    (let ((client (v17-jev::make-fake-jev :script-path script
                                          :state-path (%tmp "state"))))
      (multiple-value-bind (answers usage)
          (v17-jev:ask client nil '(("intent" . ("type" . "choice"))))
        (is (= 1 (%get "noul" (%get "intent" answers))))
        (is (= 1 (%get "input_tokens" usage)))))))

(test fake-jev-no-match-is-deterministic-error
  (let ((script (%tmp "script")))
    (%write script "{\"rules\":[{\"match\":[\"guard_pii_free\"],\"answers\":{}}]}")
    (let ((client (v17-jev::make-fake-jev :script-path script
                                          :state-path (%tmp "state"))))
      (handler-case
          (progn (v17-jev:ask client nil '(("intent" . nil))) (fail "no error"))
        (v17-jev:jev-error (e)
          (is (not (v17-jev:jev-error-transient-p e))))))))

(test fake-jev-transient-then-answers
  "transient_failures=N raises transiently N times, then serves answers;
the state file records every attempt (across client instances, i.e.
across worker processes)."
  (let ((script (%tmp "script"))
        (state (%tmp "state")))
    (%write script
            "{\"rules\":[{\"match\":[\"intent\"],\"transient_failures\":2,\"answers\":{\"intent\":{\"type\":\"noul\",\"noul\":7}}}]}")
    (dotimes (i 2)
      (let ((client (v17-jev::make-fake-jev :script-path script
                                            :state-path state)))
        (handler-case
            (progn (v17-jev:ask client nil '(("intent" . nil)))
                   (fail "attempt ~d should raise transiently" i))
          (v17-jev:jev-error (e)
            (is (v17-jev:jev-error-transient-p e))))))
    (let ((client (v17-jev::make-fake-jev :script-path script
                                          :state-path state)))
      (is (= 7 (%get "noul" (%get "intent"
                                  (v17-jev:ask client nil '(("intent" . nil))))))))
    (let ((saved (%slurp-json state)))
      (is (= 3 (%get "total_calls" saved)))
      (is (= 3 (%get "0" (%get "rule_calls" saved)))))))

(test fake-llm-counts-calls
  (let ((state (%tmp "state")))
    (let ((client (v17-llm::make-fake-llm :text "durable." :state-path state)))
      (is (equal "durable." (v17-llm:generate client '(("prompt" . "x")))))
      (is (equal "durable." (v17-llm:generate client '(("prompt" . "y"))))))
    (is (= 2 (%get "llm_calls" (%slurp-json state))))))

(test worker-json-round-trip-preserves-shape
  "The worker encodes alists to jsonb and decodes back; nested objects,
arrays, unicode and CJK survive (G3 canary semantics, pure-Lisp half)."
  (flet ((to (v) (let ((yason:*list-encoder* #'yason:encode-alist))
                   (yason:with-output-to-string* () (yason:encode-alist v))))
         (from (s) (let ((yason:*parse-object-as* :alist)
                         (yason:*parse-json-arrays-as-vectors* nil))
                     (yason:parse s))))
    (let* ((payload '(("params" . (("audience" . "团队") ("tags" . ("a" "b" "c"))
                                   ("nested" . (("x" . 1) ("y" . T) ("z" . NIL)))))
                      ("batch_id" . "00000000-0000-0000-0000-000000000000")))
           (back (from (to payload))))
      (is (equal "团队" (%get "audience" (%get "params" back))))
      (is (equal '("a" "b" "c") (%get "tags" (%get "params" back))))
      (is (= 1 (%get "x" (%get "nested" (%get "params" back))))))))
