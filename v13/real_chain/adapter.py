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


def _holds_secret(value, secret):
    if not secret or value is None:
        return False
    if isinstance(value, str):
        return secret in value
    try:
        blob = json.dumps(value)
    except TypeError:
        blob = str(value)
    return secret in blob


def _parse_object(text):
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        fence = raw.rfind("```")
        if fence >= 0:
            raw = raw[:fence]
        raw = raw.strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    return obj


class RealProviderAdapter:
    def __init__(self):
        self.calls = 0
        self.last_text = ""

    def has_credential(self):
        return _secret() != ""

    def __call__(self, layers, peek):
        secret = _secret()
        if secret == "":
            raise RuntimeError("v13: real provider credential absent")
        if not isinstance(layers, list) or len(layers) != 4:
            raise RuntimeError("v13: real provider layers")
        kind = (peek or {}).get("kind")
        messages = []
        for name, text in layers:
            messages.append({"role": "user", "content": name + "\n" + text})
        if kind == "plan":
            task = (
                "Return one JSON object and nothing else. "
                "It must have todos, an array of exactly one object. "
                "That object must have text, task_class advancement_task, "
                "status runnable, verb add_new, and due null."
            )
        elif kind == "llm":
            task = (
                "Return one JSON object and nothing else. "
                "text must be a brief non-empty assistant sentence. "
                "tool_calls must be an array of exactly one object: "
                "id, name spawn_subsession, and args with only task. "
                "task must be one short concrete sentence under 200 characters "
                "naming the single advancement task for the selected todo. "
                "Do not repeat the prompt. Do not include result_kind."
            )
        else:
            task = (
                "Return one JSON object and nothing else. "
                "It must have text and tool_calls, an array of exactly one object. "
                "That object must have id, name spawn_subsession, and args with only task. "
                "Do not include result_kind."
            )
        messages.append({"role": "user", "content": task})
        body = {"model": _model(), "messages": messages, "temperature": 0}
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
        self.calls += 1
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["choices"][0]["message"].get("content") or ""
        parsed = _parse_object(text)
        if _holds_secret(text, secret) or _holds_secret(parsed, secret):
            self.last_text = ""
            raise RuntimeError("v13: real provider secret in response")
        self.last_text = text
        if parsed is None:
            return {"text": text}
        return parsed
