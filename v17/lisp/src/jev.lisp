;;;; jev.lisp — v17 Jev client: OpenRouter decisions endpoint + offline fake.
;;;;
;;;; Port of v12/jev_client.py's contract: ASK takes the request payload's
;;;; state and questions (both alists) and returns (values answers-alist
;;;; usage-alist). Errors are JEV-ERROR with TRANSIENT-P set for retryable
;;;; failures (network, 429, 5xx) — the worker's MAX_READ_CT / RETRY_VT
;;;; discipline keys off it, exactly like JevError.transient.
;;;;
;;;; Two backends, selected by environment (mirroring JevClient's
;;;; "explicit > OPENROUTER_API_KEY > fake" precedence):
;;;;   V17_FAKE_JEV_SCRIPT + V17_FAKE_STATE  → deterministic offline fake
;;;;   OPENROUTER_API_KEY                     → real dexador client
;;;; The fake is the gate backend: rules are tried in order, the first
;;;; whose "match" keys are all present in the questions wins; a rule may
;;;; declare "transient_failures": N to raise transiently on its first N
;;;; activations. Call counts persist in the state file so gate assertions
;;;; work across separate worker processes (v12's fake.calls, but on disk).

(defpackage :v17-jev
  (:use :cl)
  (:export #:jev-error #:jev-error-message #:jev-error-transient-p
           #:make-jev-client-from-env #:ask))

(in-package :v17-jev)

;;; -------------------------------------------------------------------------
;;; Conditions
;;; -------------------------------------------------------------------------

(define-condition jev-error (error)
  ((message :initarg :message :reader jev-error-message)
   (transient-p :initarg :transient-p :reader jev-error-transient-p
                :initform nil))
  (:report (lambda (c s)
             (format s "jev: ~a (~a)" (jev-error-message c)
                     (if (jev-error-transient-p c) "transient" "deterministic")))))

;;; -------------------------------------------------------------------------
;;; JSON helpers (objects as alists; duplicated from pgstore so this system
;;; stays usable without the store)
;;; -------------------------------------------------------------------------

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

;;; -------------------------------------------------------------------------
;;; Client protocol
;;; -------------------------------------------------------------------------

(defgeneric ask (client state questions)
  (:documentation "Ask Jev QUESTIONS (alist id -> question) about STATE
(alist). Returns (values answers usage). Signals JEV-ERROR on failure."))

;;; -------------------------------------------------------------------------
;;; Fake client (gate backend)
;;; -------------------------------------------------------------------------

(defstruct fake-jev script-path state-path)

(defun %read-json-file (path)
  (if (and path (probe-file path))
      (%from-json (uiop:read-file-string path))
      nil))

(defun %write-json-file (path value)
  (ensure-directories-exist path)
  (with-open-file (s path :direction :output :if-exists :supersede
                          :if-does-not-exist :create)
    (write-string (%to-json value) s)))

(defun %rule-matches-p (rule questions)
  "All of the rule's \"match\" keys are present in QUESTIONS."
  (every (lambda (key) (assoc key questions :test #'equal))
         (%get "match" rule)))

(defmethod ask ((client fake-jev) state questions)
  (declare (ignore state))
  (let* ((rules (%get "rules" (%read-json-file (fake-jev-script-path client))))
         (state-file (%read-json-file (fake-jev-state-path client)))
         (total (or (%get "total_calls" state-file) 0))
         (rule-calls (or (%get "rule_calls" state-file) nil))
         (position (position-if (lambda (rule) (%rule-matches-p rule questions))
                                rules)))
    (unless position
      (error 'jev-error
             :message (format nil "fake-jev: no rule matched question ids ~s"
                              (mapcar #'car questions))))
    (let* ((rule (nth position rules))
           (key (write-to-string position))
           (calls (or (%get key rule-calls) 0))
           (failures (or (%get "transient_failures" rule) 0)))
      ;; Persist the attempt before deciding its outcome so crash-before-
      ;; write still counts (the real client's attempt happened too).
      (setf state-file (acons "total_calls" (1+ total)
                              (remove "total_calls" state-file
                                      :key #'car :test #'equal)))
      (setf rule-calls (acons key (1+ calls)
                              (remove key rule-calls :key #'car :test #'equal)))
      (setf state-file (acons "rule_calls" rule-calls
                              (remove "rule_calls" state-file
                                      :key #'car :test #'equal)))
      (%write-json-file (fake-jev-state-path client) state-file)
      (when (< calls failures)
        (error 'jev-error
               :message "fake-jev: scripted transient failure (529)"
               :transient-p t))
      (values (%get "answers" rule)
              '(("input_tokens" . 1) ("output_tokens" . 1))))))

;;; -------------------------------------------------------------------------
;;; Real client (OpenRouter decisions endpoint; not exercised by gates —
;;;; see v12/probe_jev.py for the manual-probe pattern)
;;; -------------------------------------------------------------------------

(defstruct openrouter-jev
  (api-key (%env "OPENROUTER_API_KEY"))
  (endpoint (%env "V17_JEV_ENDPOINT" "https://openrouter.ai/api/alpha/decisions"))
  (model (%env "V17_JEV_MODEL" "typesafe/jev-1.13")))

(defmethod ask ((client openrouter-jev) state questions)
  (unless (openrouter-jev-api-key client)
    (error 'jev-error :message "OPENROUTER_API_KEY is not set"))
  (let* ((payload (%to-json
                   (list (cons "model" (openrouter-jev-model client))
                         (cons "state" state)
                         (cons "questions" questions))))
         (response
           (handler-case
               (dexador:post (openrouter-jev-endpoint client)
                             :headers `(("Authorization" . ,(format nil "Bearer ~a" (openrouter-jev-api-key client)))
                                        ("Content-Type" . "application/json"))
                             :content payload
                             :connect-timeout 10 :read-timeout 60)
             (dexador:http-request-failed (e)
               (let ((status (dexador:response-status e)))
                 (error 'jev-error
                        :message (format nil "openrouter HTTP ~a" status)
                        :transient-p (or (eql status 429) (>= status 500)))))
             (error (e)
               (error 'jev-error
                      :message (format nil "openrouter request failed: ~a" e)
                      :transient-p t)))))
    (let* ((body (%from-json (babel:octets-to-string response :encoding :utf-8)))
           (answers (%get "answers" body)))
      (unless answers
        (error 'jev-error
               :message (format nil "openrouter response without answers: ~a"
                                (subseq (babel:octets-to-string response :encoding :utf-8)
                                        0 (min 400 (length response))))))
      (values answers (or (%get "usage" body) nil)))))

;;; -------------------------------------------------------------------------
;;; Selection
;;; -------------------------------------------------------------------------

(defun make-jev-client-from-env ()
  "Fake when V17_FAKE_JEV_SCRIPT is set (gates, offline), else OpenRouter."
  (let ((script (%env "V17_FAKE_JEV_SCRIPT")))
    (if script
        (make-fake-jev :script-path script
                       :state-path (%env "V17_FAKE_STATE"
                                         (concatenate 'string script ".state")))
        (make-openrouter-jev))))

;;; Package lock (jiti parity). Must stay the last form of the file.
(sb-ext:lock-package :v17-jev)
