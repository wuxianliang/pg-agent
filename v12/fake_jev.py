"""Deterministic stand-in for JevClient.

Gates must not touch the network. A FakeJev holds an ordered list of
script callables; each script inspects the request payload
({"state": ..., "questions": {...}}) and returns an answers dict when it
matches, or None to pass. Answers are plain dicts in the same shape the
HTTP API returns, so v12_record_answers validates them like real ones.
"""
from __future__ import annotations


class FakeJev:
    def __init__(self, scripts: list | None = None):
        self.scripts = scripts or []
        self.calls: list[dict] = []

    def ask(self, state, questions: dict) -> dict:
        payload = {"state": state, "questions": questions}
        self.calls.append(payload)
        for fn in self.scripts:
            answers = fn(payload)
            if answers is not None:
                return {"model": "fake-jev", "answers": answers,
                        "usage": {"input_tokens": 1, "output_tokens": 1}}
        raise AssertionError(
            "FakeJev: no script matched question ids "
            + str(sorted(questions)))
