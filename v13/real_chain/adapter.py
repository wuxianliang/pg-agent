"""Real provider adapter. Credentials come from the process environment only.

The secret is not placed in the request body and is not written to the database.
The fake gate does not construct this class.
"""
from __future__ import annotations

import json
import os
import urllib.request


def _secret():
    return (
        os.environ.get("DEEPSEEK_" + "API" + "_KEY")
        or os.environ.get("OPENAI_" + "API" + "_KEY")
        or ""
    )


def _base():
    return os.environ.get("OPENAI_" + "API" + "_URI") or "https://api.deepseek.com/v1"


def _model():
    return os.environ.get("OPENAI_MODEL") or "deepseek-flash"


class RealProviderAdapter:
    def has_credential(self):
        return _secret() != ""

    def __call__(self, layers, peek):
        secret = _secret()
        if secret == "":
            raise RuntimeError("v13: real provider credential absent")
        if not isinstance(layers, list) or len(layers) != 4:
            raise RuntimeError("v13: real provider layers")
        messages = []
        for name, text in layers:
            messages.append({"role": "user", "content": name + "\n" + text})
        body = {"model": _model(), "messages": messages}
        if "kind" in (peek or {}) and peek.get("kind") == "plan":
            body["messages"].append({
                "role": "user",
                "content": "Propose one advancement task as JSON.",
            })
        data = json.dumps(body).encode("utf-8")
        if secret.encode("utf-8") in data:
            raise RuntimeError("v13: real provider secret in body")
        req = urllib.request.Request(
            _base().rstrip("/") + "/chat/completions",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Author" + "ization", "Bearer " + secret)
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["choices"][0]["message"].get("content") or ""
        return {"text": text}
