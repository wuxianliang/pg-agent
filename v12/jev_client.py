"""Jev client: OpenRouter primary, TypeSafe direct as fallback.

Gates NEVER touch this module — tests inject FakeJev (v12/fake_jev.py).
The public contract is one method, identical across providers and fakes:

    ask(state, questions) -> {"answers": {qid: answer_obj}, "usage": {...}}

Provider selection (first match wins):
  1. explicit provider= argument ("openrouter" | "typesafe")
  2. OPENROUTER_API_KEY  -> openrouter   (primary per project decision)
  3. TYPESAFE_API_KEY    -> typesafe

Wire format (verified live 2026-09-18 via v12/probe_jev.py): OpenRouter
carries decision models on POST /api/alpha/decisions with the SAME body
as TypeSafe's native systemone API — {model, state, questions} in,
{model, answers, usage, ...} out, field-for-field identical. So both
backends speak the native shape; only the endpoint and auth differ.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_DECISIONS_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_MODEL = "typesafe/jev-1.13"


class JevError(RuntimeError):
    """transient=True marks retryable transport failures (network, 429/529,
    5xx); the queue worker uses it to decide redelivery vs terminal fail."""

    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


class _Backend:
    def post(self, body: dict, headers: dict) -> dict:
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", **headers})
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_exc = exc
                detail = exc.read().decode("utf-8", "replace")[:400]
                retryable = exc.code in (408, 425, 429, 500, 502, 503, 529)
                if retryable and attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise JevError(f"{self.name}: HTTP {exc.code}: {detail}",
                               transient=retryable) from exc
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise JevError(f"{self.name}: {exc}", transient=True) from exc
        raise JevError(f"{self.name}: exhausted retries",
                               transient=True) from last_exc

    def ask(self, state, questions: dict) -> dict:
        if not self.api_key:
            raise JevError(f"{self.key_env} not set")
        resp = self.post(
            {"model": self.model, "state": state, "questions": questions},
            self._headers())
        if not isinstance(resp.get("answers"), dict):
            raise JevError(
                f"{self.name}: response has no answers object; raw head: "
                + json.dumps(resp)[:400])
        return resp

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}


class TypesafeBackend(_Backend):
    """Direct api.typesafe.ai — the reference endpoint; TYPESAFE_API_KEY."""

    name = "typesafe"
    key_env = "TYPESAFE_API_KEY"
    endpoint = TYPESAFE_ENDPOINT

    def __init__(self, api_key: str | None = None, model: str = "jev-latest",
                 timeout: float = 15.0, retries: int = 2):
        self.api_key = api_key or os.environ.get(self.key_env, "")
        self.model = model
        self.timeout = timeout
        self.retries = retries


class OpenRouterBackend(_Backend):
    """OpenRouter's dedicated decisions endpoint, native systemone body.

    Verified live: POST /api/alpha/decisions with {model, state, questions}
    returns the native {model, answers, usage} shape (plus id/provider and
    usage.cost). The chat/completions endpoint rejects decision models.
    """

    name = "openrouter"
    key_env = "OPENROUTER_API_KEY"
    endpoint = OPENROUTER_DECISIONS_ENDPOINT

    def __init__(self, api_key: str | None = None,
                 model: str = OPENROUTER_MODEL,
                 timeout: float = 20.0, retries: int = 2):
        self.api_key = api_key or os.environ.get(self.key_env, "")
        self.model = model
        self.timeout = timeout
        self.retries = retries

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/wuxianliang/pg-agent",
                "X-Title": "pg-agent v12"}


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
