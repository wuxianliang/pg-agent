"""Jev client: OpenRouter primary, TypeSafe direct as fallback.

Gates NEVER touch this module — tests inject FakeJev (v12/fake_jev.py).
The public contract is one method, identical across providers and fakes:

    ask(state, questions) -> {"answers": {qid: answer_obj}, "usage": {...}}

Provider selection (first match wins):
  1. explicit provider= argument ("openrouter" | "typesafe")
  2. OPENROUTER_API_KEY  -> openrouter   (primary per project decision)
  3. TYPESAFE_API_KEY    -> typesafe

OpenRouter wire format: jev-1.13 was onboarded 2026-09-18 with modality
text->decisions and an undocumented request mapping. We try the standard
OpenAI-compatible shapes behind a mode switch — run `v12/probe_jev.py`
once with your key to learn which mode the endpoint actually speaks,
then pin it with V12_JEV_OPENROUTER_MODE (default: wrapped).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS = ("typesafe/jev-1.13", "~typesafe/jev-latest")


class JevError(RuntimeError):
    pass


class _Backend:
    def post(self, body: dict, headers: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", **headers})
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_exc = exc
                retryable = exc.code in (408, 425, 429, 500, 502, 503, 529)
                if retryable and attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                detail = exc.read().decode("utf-8", "replace")[:400]
                raise JevError(f"{self.name}: HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise JevError(f"{self.name}: {exc}") from exc
        raise JevError(f"{self.name}: exhausted retries") from last_exc


class TypesafeBackend(_Backend):
    """Direct api.typesafe.ai — the reference shape; needs TYPESAFE_API_KEY."""

    name = "typesafe"
    endpoint = TYPESAFE_ENDPOINT

    def __init__(self, api_key: str | None = None, model: str = "jev-latest",
                 timeout: float = 15.0, retries: int = 2):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
        self.model = model
        self.timeout = timeout
        self.retries = retries

    def ask(self, state, questions: dict) -> dict:
        if not self.api_key:
            raise JevError("TYPESAFE_API_KEY not set")
        return self.post(
            {"model": self.model, "state": state, "questions": questions},
            {"Authorization": f"Bearer {self.api_key}"}, self.timeout)


class OpenRouterBackend(_Backend):
    """OpenRouter chat-completions carrier for typesafe/jev-1.13.

    Modes (the on-wire mapping is undocumented as of 2026-09-18):
      wrapped   — single user message carrying {state, questions} as JSON
      native    — the TypeSafe systemone body sent as-is (some gateways
                  pass provider-native fields through)
      system_user — questions as system message, state as user message
    """

    name = "openrouter"
    endpoint = OPENROUTER_ENDPOINT

    def __init__(self, api_key: str | None = None,
                 model: str = OPENROUTER_MODELS[0],
                 mode: str | None = None,
                 timeout: float = 20.0, retries: int = 2):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model
        self.mode = (mode or os.environ.get("V12_JEV_OPENROUTER_MODE")
                     or "wrapped")
        if self.mode not in ("wrapped", "native", "system_user"):
            raise JevError(f"unknown V12_JEV_OPENROUTER_MODE {self.mode!r}")
        self.timeout = timeout
        self.retries = retries

    def _body(self, state, questions: dict) -> dict:
        base = {"model": self.model}
        if self.mode == "native":
            return {**base, "state": state, "questions": questions}
        if self.mode == "system_user":
            return {**base, "messages": [
                {"role": "system",
                 "content": json.dumps({"questions": questions})},
                {"role": "user", "content": state if isinstance(state, str)
                 else json.dumps(state)}]}
        # wrapped (default)
        return {**base, "messages": [
            {"role": "user",
             "content": json.dumps({"state": state, "questions": questions})}]}

    def _extract(self, resp: dict) -> dict:
        """Answers may come back as message content (JSON string or object)
        or — if OpenRouter passes the native shape through — as a top-level
        'answers' key."""
        if isinstance(resp.get("answers"), dict):
            return resp
        choices = resp.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content")
            parsed = None
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except ValueError:
                    parsed = None
            elif isinstance(content, dict):
                parsed = content
            if isinstance(parsed, dict) and "answers" in parsed:
                return parsed
            if isinstance(parsed, dict) and "choice" in parsed:
                return parsed  # single-question answer without wrapper
        raise JevError(
            "openrouter: could not locate answers in response — "
            "run v12/probe_jev.py to find the right mode; raw head: "
            + json.dumps(resp)[:400])

    def ask(self, state, questions: dict) -> dict:
        if not self.api_key:
            raise JevError("OPENROUTER_API_KEY not set")
        resp = self.post(self._body(state, questions), {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/wuxianliang/pg-agent",
            "X-Title": "pg-agent v12",
        }, self.timeout)
        out = self._extract(resp)
        out.setdefault("usage", resp.get("usage", {}))
        return out


class JevClient:
    """Facade: picks the backend by explicit arg or environment.

    OpenRouter is the project's primary source (no TypeSafe access
    required); the direct backend stays available for reference runs.
    """

    def __init__(self, provider: str | None = None, **backend_kwargs):
        if provider is None:
            if os.environ.get("OPENROUTER_API_KEY"):
                provider = "openrouter"
            elif os.environ.get("TYPESAFE_API_KEY"):
                provider = "typesafe"
            else:
                raise JevError(
                    "no Jev provider: set OPENROUTER_API_KEY (primary) "
                    "or TYPESAFE_API_KEY")
        if provider == "openrouter":
            self.backend = OpenRouterBackend(**backend_kwargs)
        elif provider == "typesafe":
            self.backend = TypesafeBackend(**backend_kwargs)
        else:
            raise JevError(f"unknown provider {provider!r}")

    @property
    def provider(self) -> str:
        return self.backend.name

    def ask(self, state, questions: dict) -> dict:
        return self.backend.ask(state, questions)
