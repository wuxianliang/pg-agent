;;;; llm.lisp — v17 LLM generation effect client + offline fake.
;;;;
;;;; LLM generation is an effect (v12: it alone owns generation; the
;;;; guardrail must pass before delivery). This is the worker-side client
;;;; the 'llm' job kind calls — the Lisp counterpart of queue_worker.py's
;;;; injected llm_fn. Backend selection:
;;;;   V17_FAKE_LLM_TEXT → deterministic fake (gates); every call returns
;;;;                       that string and bumps "llm_calls" in
;;;;                       V17_FAKE_STATE for cross-process assertions
;;;;   OPENROUTER_API_KEY → real dexador chat-completions client
;;;; The fake always succeeds; failure-path coverage comes from tool jobs
;;;; and the Jev client, not from a scripted LLM failure.

(defpackage :v17-llm
  (:use :cl)
  (:export #:llm-error #:llm-error-message
           #:make-llm-client-from-env #:generate))

(in-package :v17-llm)

(define-condition llm-error (error)
  ((message :initarg :message :reader llm-error-message))
  (:report (lambda (c s) (format s "llm: ~a" (llm-error-message c)))))

(defun %to-json (value)
  (let ((yason:*list-encoder* #'yason:encode-alist))
    (yason:with-output-to-string* () (yason:encode-alist value))))

(defun %from-json (text)
  (when (and text (not (eq text :null)))
    (let ((yason:*parse-object-as* :alist)
          (yason:*parse-json-arrays-as-vectors* nil))
      (yason:parse text))))

(defun %get (key alist &optional default)
  (let ((cell (assoc key alist :test #'equal)))
    (if cell (cdr cell) default)))

(defun %env (name &optional default)
  (or (uiop:getenv name) default))

(defgeneric generate (client payload)
  (:documentation "Generate text for the job PAYLOAD (alist). Returns a
string; signals LLM-ERROR on failure."))

;;; -------------------------------------------------------------------------
;;; Fake (gate backend)
;;; -------------------------------------------------------------------------

(defstruct fake-llm text state-path)

(defmethod generate ((client fake-llm) payload)
  (declare (ignore payload))
  (let* ((state (if (probe-file (fake-llm-state-path client))
                    (%from-json (uiop:read-file-string
                                 (fake-llm-state-path client)))
                    nil))
         (calls (or (%get "llm_calls" state) 0)))
    (setf state (acons "llm_calls" (1+ calls)
                       (remove "llm_calls" state :key #'car :test #'equal)))
    (ensure-directories-exist (fake-llm-state-path client))
    (with-open-file (s (fake-llm-state-path client)
                       :direction :output :if-exists :supersede
                       :if-does-not-exist :create)
      (write-string (%to-json state) s)))
  (fake-llm-text client))

;;; -------------------------------------------------------------------------
;;; Real client (OpenRouter chat completions; not exercised by gates)
;;; -------------------------------------------------------------------------

(defstruct openrouter-llm
  (api-key (%env "OPENROUTER_API_KEY"))
  (endpoint (%env "V17_LLM_ENDPOINT"
                  "https://openrouter.ai/api/v1/chat/completions"))
  (model (%env "V17_LLM_MODEL" "anthropic/claude-haiku-4.5")))

(defmethod generate ((client openrouter-llm) payload)
  (unless (openrouter-llm-api-key client)
    (error 'llm-error :message "OPENROUTER_API_KEY is not set"))
  (let* ((prompt (or (%get "prompt" payload)
                     (%get "text" payload)
                     (%to-json payload)))
         (body (%to-json
                (list (cons "model" (openrouter-llm-model client))
                      (cons "messages"
                            (vector (list (cons "role" "user")
                                          (cons "content" prompt)))))))
         (response
           (handler-case
               (dexador:post (openrouter-llm-endpoint client)
                             :headers `(("Authorization" . ,(format nil "Bearer ~a" (openrouter-llm-api-key client)))
                                        ("Content-Type" . "application/json"))
                             :content body
                             :connect-timeout 10 :read-timeout 120)
             (error (e)
               (error 'llm-error
                      :message (format nil "openrouter chat failed: ~a" e))))))
    (let* ((parsed (%from-json (babel:octets-to-string response :encoding :utf-8)))
           (choices (%get "choices" parsed))
           (first-choice (and choices (car choices)))
           (message (and first-choice (%get "message" first-choice)))
           (content (and message (%get "content" message))))
      (unless (stringp content)
        (error 'llm-error :message "openrouter chat response without content"))
      content)))

;;; -------------------------------------------------------------------------
;;; Selection
;;; -------------------------------------------------------------------------

(defun make-llm-client-from-env ()
  "Fake when V17_FAKE_LLM_TEXT is set (gates), else OpenRouter. NIL when
neither is configured — llm jobs then fail like queue_worker.py's missing
llm_fn."
  (let ((text (%env "V17_FAKE_LLM_TEXT")))
    (cond (text (make-fake-llm :text text
                               :state-path (%env "V17_FAKE_STATE" "/dev/null")))
          ((%env "OPENROUTER_API_KEY") (make-openrouter-llm))
          (t nil))))

;;; Package lock (jiti parity). Must stay the last form of the file.
(sb-ext:lock-package :v17-llm)
