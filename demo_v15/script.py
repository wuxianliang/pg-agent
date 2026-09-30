"""Ordered fake-provider script. No preflight, timeout_s, or close."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v15.protocol.split_sql import SplitFailure, classify_statement, split_sql

from task import BIND_NAME, PRINT_SQL, child_payload, fanout_fragments, role_for


class ScriptExhausted(Exception):
    pass


class ScriptGate(Exception):
    pass


class OrderedScript:
    def __init__(self, replies: list[str]) -> None:
        self._left = list(replies)
        self.calls: list[tuple] = []

    def complete(self, logical_digest, n, request, llm_config=None) -> dict:
        self.calls.append((logical_digest, n))
        if not self._left:
            raise ScriptExhausted("script exhausted")
        content = self._left.pop(0)
        return {"content": content, "prompt_tokens": 1, "cost_usd": 0}


def sql_jsonb(obj: object) -> str:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return "'" + text.replace("'", "''") + "'::jsonb"


def tail_reply(note: str, hops: int, role: str, seal: str, root_id: str) -> str:
    literal = sql_jsonb(child_payload(note, hops, role, seal, root_id))
    return (
        f"SELECT jaz.bind_invoke('{BIND_NAME}', {literal});\n"
        f"SELECT jaz.\"return\"(jaz.var('{BIND_NAME}'));"
    )


def leaf_chain(seal: str) -> str:
    literal = sql_jsonb({"seal": seal, "hops": 1})
    return f"SELECT jaz.\"return\"({literal});"


_LEAF_RECALL = """SELECT jaz.\"return\"(jsonb_build_object(
  'seal', '{seal}',
  'hops', 1,
  'token', (
    SELECT substring(h.repl_output from 'token=([0-9a-f]{16})')
    FROM jaz.prior_history('{root_id}'::uuid) AS h
    WHERE h.repl_output LIKE '%token=%'
    ORDER BY h.iteration
    LIMIT 1
  )
));"""


def leaf_recall(seal: str, root_id: str) -> str:
    return _LEAF_RECALL.replace("{seal}", seal).replace("{root_id}", root_id)


def happy_chain(note: str, seal: str, hops: int, root_id: str) -> list[str]:
    replies = []
    for left in range(hops, 1, -1):
        child_hops = left - 1
        replies.append(
            tail_reply(note, child_hops, role_for(child_hops, hops), seal, root_id)
        )
    replies.append(leaf_chain(seal))
    return replies


def happy_recall(note: str, seal: str, hops: int, root_id: str, token: str) -> list[str]:
    del token
    tails = []
    for left in range(hops, 1, -1):
        child_hops = left - 1
        tails.append(
            tail_reply(note, child_hops, role_for(child_hops, hops), seal, root_id)
        )
    return [PRINT_SQL, *tails, leaf_recall(seal, root_id)]


def happy_fanout(note: str, seal: str, hops: int, root_id: str) -> list[str]:
    del hops
    frag_a, frag_b = fanout_fragments(seal)
    payload_a = child_payload(note, 1, "leaf", frag_a, root_id)
    payload_b = child_payload(note, 1, "leaf", frag_b, root_id)
    root = (
        f"SELECT jaz.bind_invoke('a', {sql_jsonb(payload_a)});\n"
        f"SELECT jaz.bind_invoke('b', {sql_jsonb(payload_b)});\n"
        f"SELECT jaz.\"return\"(jsonb_build_object('a', jaz.var('a'), 'b', jaz.var('b')));"
    )
    child_a = f"SELECT jaz.\"return\"({sql_jsonb({'fragment': frag_a})});"
    child_b = f"SELECT jaz.\"return\"({sql_jsonb({'fragment': frag_b})});"
    return [root, child_a, child_b]


def continue_then_tail(note: str, seal: str, hops: int, root_id: str) -> list[str]:
    return ["SELECT 1;", *happy_chain(note, seal, hops, root_id)]


def expected_kinds(scenario: str, hops: int, *, continued: bool = False) -> list[list[str]]:
    tails = [["bind_invoke", "return"] for _ in range(hops - 1)]
    leaf = ["return"]
    if scenario == "chain" and continued:
        return [["plain"], *tails, leaf]
    if scenario == "chain":
        return [*tails, leaf]
    if scenario == "recall":
        return [["print"], *tails, leaf]
    if scenario == "fanout":
        return [["bind_invoke", "bind_invoke", "return"], ["return"], ["return"]]
    raise ScriptGate(scenario)


def gate(replies: list[str], kinds: list[list[str]]) -> None:
    if len(replies) != len(kinds):
        raise ScriptGate(("len", len(replies), len(kinds)))
    for reply, expect in zip(replies, kinds):
        pieces = split_sql(reply)
        if isinstance(pieces, SplitFailure):
            raise ScriptGate(pieces.reject_code)
        if len(pieces) != len(expect):
            raise ScriptGate(("pieces", len(pieces), expect, reply))
        for piece, kind in zip(pieces, expect):
            classified = classify_statement(piece)
            if classified.reject_code is not None or classified.kind != kind:
                raise ScriptGate((classified.kind, classified.reject_code, kind, piece))
