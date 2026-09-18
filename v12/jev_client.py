"""Real Jev (TypeSafe System One) HTTP client.

NEVER used by gates — tests inject FakeJev (v12/fake_jev.py). This module
exists so production workers have one honest caller of
POST https://api.typesafe.ai/v1/systemone with bearer auth and
backoff on 429/529, per the official API reference.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevClient:
    def __init__(self, api_key: str | None = None,
                 model: str = "jev-latest",
                 endpoint: str = DEFAULT_ENDPOINT,
                 timeout: float = 15.0,
                 retries: int = 2):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
        if not self.api_key:
            raise ValueError("TYPESAFE_API_KEY not set")
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries

    def ask(self, state, questions: dict) -> dict:
        """One request: a state plus a batch of typed questions.

        Returns the parsed response: {"model": ..., "answers": {...},
        "usage": {...}} — answers keyed exactly like the questions.
        """
        body = json.dumps({"model": self.model, "state": state,
                           "questions": questions}).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                self.endpoint, data=body, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in (429, 529) and attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
        raise last_exc  # pragma: no cover
