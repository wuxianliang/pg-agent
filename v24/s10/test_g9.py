"""G9: scripted provider extension check for the M-R host worker.

Run from the worktree root:

    uv run python v24/s10/test_g9.py
    uv run python v24/s10/test_g9.py --only G9-A

The check is an extension check, not a twelfth closeout command.  Every
transport is scripted: no real socket is opened.  The static scan runs before
the fixture, and both Python socket entry points plus the v15 opener factory
are denied for the whole run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
V24 = ROOT.parent
S1 = V24 / "s1"
S2 = V24 / "s2"
S4 = V24 / "s4"
S5 = V24 / "s5"
S6 = V24 / "s6"
S8 = V24 / "s8"
for _path in (S1, S2, S4, S5, S6, S8, V24.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

socket = __import__("socket")

import psycopg2  # noqa: E402
from psycopg2.extensions import TRANSACTION_STATUS_IDLE  # noqa: E402
from psycopg2.extras import Json  # noqa: E402

from setup_db import (  # noqa: E402
    _assert_closed_catalog,
    server_helper_scope,
    setup_db,
)
from test_g2b import loop_fixture, start  # noqa: E402

from v24.host.db import HostContractError, HostDB  # noqa: E402
from v24.host.deepseek import (  # noqa: E402
    AdapterFailure,
    DeepSeekAdapter,
    ENDPOINT,
    provider_tool_name,
)
from v24.host.journal import (  # noqa: E402
    HostJournal,
    JournalCorrupt,
    JournalLocked,
    JournalVersionError,
    canonical_json,
)
from v24.host.worker import HostCrash, HostWorker  # noqa: E402
from v15.provider.errors import ProviderUncertain, detail  # noqa: E402

ALL_CASES = ("G9-A", "G9-B", "G9-C", "G9-D", "G9-E", "G9-F", "G9-L",
             "G9-J1", "G9-J2", "G9-J3", "G9-R")

BUDGET = {"steps": 8, "tool_calls": 8, "tokens": 5000, "wall_ms": 600000}
FIXED_NOW = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
FORBIDDEN_IMPORTS = (
    "socket", "http", "urllib", "requests", "ftplib", "smtplib",
    "telnetlib", "aiohttp", "httpx",
)
_NET_SAVED = None
_OPENER_SAVED = None


def _deny(*args, **kwargs):
    raise AssertionError("v24/s10 gate attempted network I/O")


def install_no_network():
    global _NET_SAVED, _OPENER_SAVED
    urllib_request = __import__("urllib.request", fromlist=["request"])
    v15deepseek = __import__("v15.provider.deepseek", fromlist=["build_opener"])

    _NET_SAVED = (socket.socket.connect, socket.create_connection,
                  urllib_request.urlopen)
    _OPENER_SAVED = v15deepseek.build_opener
    socket.socket.connect = _deny
    socket.create_connection = _deny
    urllib_request.urlopen = _deny
    v15deepseek.build_opener = _deny


def restore_no_network():
    global _NET_SAVED, _OPENER_SAVED
    if _NET_SAVED is not None:
        socket.socket.connect, socket.create_connection, urlopen = _NET_SAVED
        __import__("urllib.request", fromlist=["request"]).urlopen = urlopen
        _NET_SAVED = None
    if _OPENER_SAVED is not None:
        v15deepseek = __import__("v15.provider.deepseek", fromlist=["build_opener"])
        v15deepseek.build_opener = _OPENER_SAVED
        _OPENER_SAVED = None


def assert_static_guards():
    for path in sorted(ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IMPORTS:
            assert re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(name)}\b",
                             source) is None, (path.name, name)
        assert ("time." + "sleep") not in source, path.name
    host = V24 / "host"
    for name in ("worker.py", "journal.py", "db.py", "process_io.py"):
        source = (host / name).read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            assert re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(forbidden)}\b",
                             source) is None, (name, forbidden)
        if name in ("worker.py", "journal.py"):
            assert "FROM V24." not in source.upper(), name
    deep = (host / "deepseek.py").read_text(encoding="utf-8")
    assert re.search(r"from v15\.provider\.deepseek import[^\n]*DeepSeekProvider",
                     deep) is None
    assert "_classify(" not in deep
    assert 'os.environ.get("OPENAI_API_URI")' not in deep
    assert "https://api.deepseek.com" in deep
    allowed = {
        "host_scopes", "host_runs", "host_effects", "host_run_effects",
        "host_effect", "host_scope_installs", "host_install_fibers",
        "host_run_pins", "host_request", "advance", "command_recover",
    }
    calls = {name for name in re.findall(r"v24\.([a-z_]+)",
                                         (host / "db.py").read_text())
             if not name.endswith("_")}
    assert calls <= allowed, calls - allowed
    deps = {name for name in re.findall(r"v24\.([a-z_]+)",
                                        (host / "worker.py").read_text())
            if not name.endswith("_")}
    assert deps <= allowed, deps - allowed


# ---------------------------------------------------------------------------
# Scripted transport
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self, value: float = 1000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, ms: int) -> None:
        self.value += ms / 1000.0


class ScriptTransport:
    def __init__(self, clock: FakeClock, script=None):
        self.clock = clock
        self.script = list(script or [])
        self.calls = []

    def post(self, url, body, headers, deadline):
        self.calls.append({"url": url, "body": body, "headers": headers,
                           "deadline": deadline})
        if self.clock() >= deadline:
            raise ProviderUncertain(detail("transport"))
        if not self.script:
            raise AssertionError("unexpected scripted HTTP call")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        self.clock.advance(item.get("advance_ms", 0))
        raw = item.get("raw", b"")
        if not isinstance(raw, (bytes, bytearray)):
            raw = canonical_json(raw).encode("utf-8")
        return item["status"], bytes(raw)


def chat_body(*, content=None, tool_calls=None, finish="stop", usage=(10, 5),
              reasoning=None, response_id="resp-1", model="deepseek-flash",
              choices=None):
    if choices is None:
        message = {"role": "assistant", "content": content}
        if reasoning is not None:
            message["reasoning_content"] = reasoning
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        choices = [{"finish_reason": finish, "message": message}]
    body = {"id": response_id, "model": model, "choices": choices}
    if usage is not None:
        body["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1]}
    return body


def call(ident, name, arguments):
    item = {"type": "function",
            "function": {"name": name, "arguments": arguments}}
    if ident is not None:
        item["id"] = ident
    return item


def reply(item, advance_ms=25):
    return {"status": 200, "raw": item, "advance_ms": advance_ms}


def status_reply(status, raw=b"{}", advance_ms=5):
    return {"status": status, "raw": raw, "advance_ms": advance_ms}


def adapter_for(script, *, timeout_s=120, key="test-key-not-real"):
    clock = FakeClock()
    transport = ScriptTransport(clock, script)
    adapter = DeepSeekAdapter(api_key=key, timeout_s=timeout_s,
                              transport=transport, clock=lambda: FIXED_NOW,
                              monotonic=clock)
    return adapter, transport, clock


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def bind_owner(fixture):
    owner = fixture.connect()
    with owner.cursor() as cur:
        cur.execute("SET ROLE v24_owner")
    owner.commit()
    return owner


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        value = cur.fetchone()[0]
    conn.commit()
    return value


def row(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        value = cur.fetchone()
    conn.commit()
    return value


def effect_row(owner, effect_id):
    return one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
               (effect_id,))


def run_row(owner, run_id):
    return one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s",
               (run_id,))


def count(owner, sql, params=()):
    return one(owner, f"SELECT count(*) FROM {sql}", params)


def new_scope(host, owner, requires=()):
    realm = f"g9-{uuid4().hex[:8]}"
    root, live, _ = loop_fixture(owner, host.service, realm=realm,
                                 requires=requires)
    # The S4 fixture uses {"k": key}; G9 needs the host v1 descriptor dialect.
    for key in requires:
        descriptor = {"v": 1, "tool": {"description": f"{key} tool",
                                       "parameters": {"type": "object"}}}
        digest = hashlib.sha256(
            canonical_json(descriptor).encode("utf-8")).digest()
        with owner.cursor() as cur:
            cur.execute(
                """UPDATE v24.slots s
                      SET descriptor=%s, descriptor_digest=%s
                     FROM v24.fibers f
                    WHERE s.fiber_id=f.fiber_id AND f.scope_id=%s AND s.key=%s""",
                (Json(descriptor), digest, root, key))
    owner.commit()
    return root, live


def start_run(host, root, live, requires=(), *, budget=None, key=None):
    value = {"messages": [{"role": "user", "content": "hello g9"}],
             "max_output_tokens": 64}
    if requires:
        value["requires"] = [{"key": key} for key in requires]
    response, _ = start(host.service, root, live["fiber"], value,
                        budget or dict(BUDGET), key or f"g9-start-{uuid4().hex}")
    host.service.commit()
    assert response.get("disposition") == "committed", response
    emitted = response["emitted"]
    assert len(emitted) == 2, emitted
    return emitted[0], emitted[1]


def fresh_run(host, owner, requires=()):
    root, live = new_scope(host, owner, requires)
    run_id, model_id = start_run(host, root, live, requires)
    return root, run_id, model_id


def make_journal(root_dir: Path, name: str):
    path = root_dir / name
    path.mkdir(mode=0o700)
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    return HostJournal.open(path / "journal.jsonl")


def journal_text(journal) -> str:
    return journal.path.read_text(encoding="utf-8")


def initial_remaining(owner, run_id):
    return run_row(owner, run_id)["remaining_tokens"]


def assert_failure(owner, run_id, model_id, *, tokens, http_calls,
                   remaining=4985, expected_http_calls=None):
    if expected_http_calls is None:
        expected_http_calls = http_calls
    effect = effect_row(owner, model_id)
    assert effect["status"] == "failed", effect
    assert effect["outcome"]["class"] == "failure", effect
    result = effect["outcome"]["body"]["result"]
    assert "tool_calls" not in result and "final" not in result, result
    assert result["usage"]["tokens"] == tokens, result
    assert run_row(owner, run_id)["status"] == "failed"
    assert run_row(owner, run_id)["remaining_tokens"] == remaining
    assert count(owner, "v24.effects WHERE run_id=%s AND kind='tool_call'",
                 (run_id,)) == 0
    assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                 (run_id,)) == 1
    assert http_calls == expected_http_calls


def assert_unknown(owner, run_id, model_id, *, tokens, remaining=904):
    effect = effect_row(owner, model_id)
    assert effect["status"] == "unknown", effect
    assert effect["outcome"]["class"] == "unknown", effect
    result = effect["outcome"]["body"]["result"]
    assert "final" not in result and "tool_calls" not in result, result
    if tokens is not None:
        assert result.get("usage", {}).get("tokens") == tokens, result
    assert run_row(owner, run_id)["status"] == "blocked_unknown"
    assert run_row(owner, run_id)["remaining_tokens"] == remaining
    assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                 (run_id,)) == 1


# ---------------------------------------------------------------------------
# G9-A: descriptor -> provider name and the tool round trip
# ---------------------------------------------------------------------------
def g9_a(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner, ["search"])
    safe = provider_tool_name("search")
    adapter, transport, _ = adapter_for([
        reply(chat_body(content=None, finish="tool_calls",
                        reasoning="plan",
                        tool_calls=[call("call_1", safe, '{"q":"x"}')])),
        reply(chat_body(content="done", finish="stop", reasoning="answer")),
    ])
    seen = []

    def tool_handler(effect):
        seen.append(effect["request"])
        return "success", {"status": "ok", "output": {"hits": []},
                           "usage": {"wall_ms": 1}}

    journal = make_journal(workdir, "g9-a")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            tool_handler=tool_handler)
        stats = worker.run_until_idle(root, max_rounds=10)
        assert stats.idle, stats
        assert len(transport.calls) == 2, len(transport.calls)
        first = json.loads(transport.calls[0]["body"])
        assert transport.calls[0]["url"] == ENDPOINT
        assert first["model"] == "deepseek-flash"
        assert first["stream"] is False
        assert "tool_choice" not in first and "parallel_tool_calls" not in first
        assert "max_tokens" in first and 1 <= first["max_tokens"] <= 64
        assert len(first["tools"]) == 1
        name = first["tools"][0]["function"]["name"]
        assert name == safe
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name)
        assert name.endswith(hashlib.sha256(b"search").hexdigest()[:8])
        assert first["tools"][0]["function"]["parameters"] == {"type": "object"}
        started = journal.last("dispatch_started", model_id)
        mapping = started["payload"]["prepared"]["tool_map"]
        assert mapping["by_provider"][name] == "search"
        assert mapping["by_key"]["search"] == name
        second = json.loads(transport.calls[1]["body"])
        assistants = [m for m in second["messages"] if m["role"] == "assistant"]
        tools = [m for m in second["messages"] if m["role"] == "tool"]
        assert len(assistants) == 1 and len(tools) == 1, second["messages"]
        assert assistants[0]["reasoning_content"] == "plan"
        assert assistants[0]["tool_calls"][0]["id"] == "call_1"
        assert assistants[0]["tool_calls"][0]["function"]["name"] == name
        assert tools[0]["tool_call_id"] == "call_1"
        assert json.loads(tools[0]["content"]) == {"hits": []}
        assert "tool_choice" not in second
        assert [item["key"] for item in seen] == ["search"]
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='tool_call'",
                     (run_id,)) == 1
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                     (run_id,)) == 2
        assert run_row(owner, run_id)["status"] == "completed"
        assert run_row(owner, run_id)["result"]["close_reason"] == "final"
        print("[G9-A] descriptor->safe name mapping (sha256 suffix), reversible "
              "journal map, two provider turns, reasoning + tool_call_id echoed, "
              "no tool_choice/parallel_tool_calls")
    finally:
        journal.close()


# ---------------------------------------------------------------------------
# G9-B: stop/final mapping and the journal-only metadata boundary
# ---------------------------------------------------------------------------
def g9_b(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="SELECT 1;", finish="stop", reasoning="why",
                        response_id="resp-B", usage=(12, 3)), advance_ms=37),
    ])
    journal = make_journal(workdir, "g9-b")
    try:
        worker = HostWorker(host, journal, adapter=adapter)
        stats = worker.run_until_idle(root, max_rounds=6)
        assert stats.idle and len(transport.calls) == 1
        effect = effect_row(owner, model_id)
        result = effect["outcome"]["body"]["result"]
        assert result["final"] == {"text": "SELECT 1;"}, result
        assert result["usage"] == {"tokens": 15, "wall_ms": 37}, result
        run = run_row(owner, run_id)
        assert run["status"] == "completed"
        assert run["result"]["final_text"] == "SELECT 1;"
        assert run["remaining_tokens"] == 4985, run["remaining_tokens"]
        db_text = canonical_json(effect["outcome"])
        assert "why" not in db_text and "resp-B" not in db_text
        assert "cost" not in db_text.lower() and "reasoning" not in db_text
        finish = journal.last("dispatch_finished", model_id)
        record = finish["payload"]["mapping"]["reply"]
        assert record["reasoning_content"] == "why"
        assert record["response_id"] == "resp-B"
        assert record["provider_metadata"]["pricing_revision"]
        assert "test-key-not-real" not in journal_text(journal)
        assert "Authorization" not in journal_text(journal)
        print("[G9-B] stop->final success, usage 12+3=15, wall 37ms, DB result "
              "excludes reasoning/id/cost; journal keeps them and no key/header")
    finally:
        journal.close()


# ---------------------------------------------------------------------------
# G9-C: provider order, duplicate ids, batch barrier
# ---------------------------------------------------------------------------
def g9_c(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner, ["alpha", "beta"])
    alpha, beta = provider_tool_name("alpha"), provider_tool_name("beta")
    adapter, transport, _ = adapter_for([
        reply(chat_body(finish="tool_calls", reasoning="both",
                        tool_calls=[call("call_a", alpha, '{"n":1}'),
                                    call("call_b", beta, '{"n":2}')])),
        reply(chat_body(content="done", finish="stop", reasoning="after")),
    ])
    seen = []

    def tool_handler(effect):
        seen.append((effect["request"]["ordinal"], effect["request"]["key"]))
        return "success", {"status": "ok",
                           "output": {"ordinal": effect["request"]["ordinal"]},
                           "usage": {"wall_ms": 1}}

    journal = make_journal(workdir, "g9-c")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            tool_handler=tool_handler)
        stats = worker.run_until_idle(root, max_rounds=10)
        assert stats.idle and len(transport.calls) == 2
        assert sorted(seen) == [(0, "alpha"), (1, "beta")], seen
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='tool_call'",
                     (run_id,)) == 2
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                     (run_id,)) == 2
        second = json.loads(transport.calls[1]["body"])
        tools = [m for m in second["messages"] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tools] == ["call_a", "call_b"]
        assert run_row(owner, run_id)["status"] == "completed"
        print("[G9-C] two tool calls mapped in provider order; tool effects "
              "settle under the batch barrier; one continuation; two HTTP calls")
    finally:
        journal.close()

    # Duplicate provider tool-call ids are a failure, not a replay.
    root, run_id, model_id = fresh_run(host, owner, ["alpha"])
    duplicate = [call("call_same", alpha, "{}"), call("call_same", beta, "{}")]
    adapter, transport, _ = adapter_for([
        reply(chat_body(finish="tool_calls", tool_calls=duplicate)),
    ])
    journal = make_journal(workdir, "g9-c-dup")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            tool_handler=lambda effect: ("success", {}))
        worker.run_once(root)
        assert_failure(owner, run_id, model_id, tokens=15, http_calls=1)
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='tool_call'",
                     (run_id,)) == 0
        print("[G9-C/dup] duplicate provider tool-call id -> failure, zero tool "
              "effects, one HTTP call")
    finally:
        journal.close()


# ---------------------------------------------------------------------------
# G9-D: mapping table classifications
# ---------------------------------------------------------------------------
def _single_model_case(host, owner, workdir, name, script, *, requires=(),
                       timeout_s=120):
    root, run_id, model_id = fresh_run(host, owner, requires)
    adapter, transport, _ = adapter_for(script, timeout_s=timeout_s)
    journal = make_journal(workdir, name)
    return root, run_id, model_id, adapter, transport, journal


def g9_d(host, owner, workdir):
    safe = provider_tool_name("search")
    failures = {
        "bad-args": [reply(chat_body(finish="tool_calls",
                                     tool_calls=[call("c1", safe, "not-json")]))],
        "unknown-tool": [reply(chat_body(finish="tool_calls",
                                         tool_calls=[call("c1", "ghost", "{}")]))],
        "missing-id": [reply(chat_body(finish="tool_calls",
                                       tool_calls=[call(None, safe, "{}")]))],
        "too-many": [reply(chat_body(finish="tool_calls", tool_calls=[
            call(f"c{i}", safe, "{}") for i in range(17)]))],
        "zero-calls": [reply(chat_body(finish="tool_calls", tool_calls=[]))],
    }
    for name, script in failures.items():
        root, run_id, model_id, adapter, transport, journal = _single_model_case(
            host, owner, workdir, f"g9-d-{name}", script, requires=["search"])
        try:
            HostWorker(host, journal, adapter=adapter).run_once(root)
            tokens = 15 if name not in ("too-many", "zero-calls") else 15
            assert_failure(owner, run_id, model_id, tokens=tokens,
                           http_calls=1)
            assert count(owner, "v24.effects WHERE run_id=%s AND kind='tool_call'",
                         (run_id,)) == 0
        finally:
            journal.close()
    print("[G9-D/failure] bad arguments, unknown tool name, missing id, >16 "
          "calls and zero calls -> failure with actual usage, zero tool effects")

    unknowns = {
        "contradictory": [reply(chat_body(content="x", finish="stop",
                                          tool_calls=[call("c1", safe, "{}")]))],
        "choices-empty": [reply(chat_body(choices=[]))],
        "not-json": [status_reply(200, b"not-json")],
        "bad-usage": [reply({"id": "r", "model": "deepseek-flash",
                             "choices": [{"finish_reason": "stop",
                                          "message": {"role": "assistant",
                                                      "content": "x"}}],
                             "usage": {"prompt_tokens": "x",
                                       "completion_tokens": 1}})],
    }
    for name, script in unknowns.items():
        root, run_id, model_id, adapter, transport, journal = _single_model_case(
            host, owner, workdir, f"g9-d-{name}", script)
        try:
            HostWorker(host, journal, adapter=adapter).run_once(root)
            assert_unknown(owner, run_id, model_id, tokens=None)
            assert len(transport.calls) == 1
        finally:
            journal.close()
    print("[G9-D/unknown] contradictory finish/message, empty choices, "
          "non-JSON and untrustworthy usage -> unknown, no successor")


# ---------------------------------------------------------------------------
# G9-E: length and over-reserve
# ---------------------------------------------------------------------------
def g9_e(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="truncated", finish="length", usage=(10, 5))),
    ])
    journal = make_journal(workdir, "g9-e-length")
    try:
        HostWorker(host, journal, adapter=adapter).run_once(root)
        assert_unknown(owner, run_id, model_id, tokens=15)
        result = effect_row(owner, model_id)["outcome"]["body"]["result"]
        assert "truncated" not in canonical_json(result)
        assert len(transport.calls) == 1
    finally:
        journal.close()
    print("[G9-E/length] length -> unknown with verifiable usage, truncated "
          "text not final, no automatic continuation")

    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="x", finish="stop", usage=(10, 5000))),
    ])
    journal = make_journal(workdir, "g9-e-reserve")
    try:
        HostWorker(host, journal, adapter=adapter).run_once(root)
        effect = effect_row(owner, model_id)
        assert effect["status"] == "unknown", effect
        assert effect["outcome"]["class"] == "success", effect
        assert effect["outcome"]["body"]["result"]["usage"]["tokens"] == 5010
        assert run_row(owner, run_id)["status"] == "blocked_unknown"
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                     (run_id,)) == 1
        assert len(transport.calls) == 1
    finally:
        journal.close()
    print("[G9-E/reserve] tokens > reserve keeps mapped success + real usage, "
          "kernel turns it semantic unknown, no truncation and no successor")


# ---------------------------------------------------------------------------
# G9-F: preflight / HTTP statuses / transport failures
# ---------------------------------------------------------------------------
def g9_f(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([], key="")
    journal = make_journal(workdir, "g9-f-nokey")
    try:
        HostWorker(host, journal, adapter=adapter).run_once(root)
        assert_failure(owner, run_id, model_id, tokens=0, http_calls=0,
                       remaining=5000)
        assert transport.calls == []
    finally:
        journal.close()
    print("[G9-F/preflight] credentials absent -> failure, zero HTTP, no reserve "
          "consumption")

    for name, item, cls in (
        ("400", status_reply(400, b'{"error":"bad"}'), "failure"),
        ("429", status_reply(429, b"{}"), "unknown"),
        ("500", status_reply(500, b"{}"), "unknown"),
        ("408", status_reply(408, b"{}"), "unknown"),
        ("302", status_reply(302, b""), "unknown"),
    ):
        root, run_id, model_id = fresh_run(host, owner)
        adapter, transport, _ = adapter_for([item])
        journal = make_journal(workdir, f"g9-f-{name}")
        try:
            HostWorker(host, journal, adapter=adapter).run_once(root)
            if cls == "failure":
                assert_failure(owner, run_id, model_id, tokens=0,
                               http_calls=1, remaining=5000)
            else:
                assert_unknown(owner, run_id, model_id, tokens=None)
            assert len(transport.calls) == 1
        finally:
            journal.close()
    print("[G9-F/http] 400 -> failure; 3xx/408/429/5xx -> unknown; exactly one "
          "HTTP attempt, never retried")

    for name, error in (
        ("timeout", ProviderUncertain(detail("transport"))),
        ("connection", OSError("connection reset")),
    ):
        root, run_id, model_id = fresh_run(host, owner)
        adapter, transport, _ = adapter_for([error])
        journal = make_journal(workdir, f"g9-f-{name}")
        try:
            HostWorker(host, journal, adapter=adapter).run_once(root)
            assert_unknown(owner, run_id, model_id, tokens=None)
            assert len(transport.calls) == 1
        finally:
            journal.close()
    print("[G9-F/transport] timeout and connection interruption -> unknown, one "
          "attempt only")


# ---------------------------------------------------------------------------
# G9-L: session profile, timeout/lease bounds and journal format
# ---------------------------------------------------------------------------
def _raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def g9_l(host, owner, workdir):
    for conn in (host.control, host.service):
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('transaction_isolation')")
            assert cur.fetchone()[0] == "read committed"
            for name, value in (("statement_timeout", "30s"),
                                ("lock_timeout", "5s"),
                                ("idle_in_transaction_session_timeout", "5s")):
                cur.execute(f"SELECT current_setting('{name}')")
                assert cur.fetchone()[0] == value, name
        conn.rollback()
        assert conn.get_transaction_status() == TRANSACTION_STATUS_IDLE

    for bad in (0, -1, 240, 239.0001, "120", True):
        _raises(ValueError, DeepSeekAdapter, api_key="x", timeout_s=bad)
    assert DeepSeekAdapter.lease_ms(1) == 61000
    assert DeepSeekAdapter.lease_ms(120) == 180000
    assert DeepSeekAdapter.lease_ms(239) == 299000

    root, run_id, model_id = fresh_run(host, owner)
    response = host.claim(model_id, 1000)
    token = response["claim"]
    assert token is not None
    adapter, transport, _ = adapter_for([])
    worker = HostWorker(host, make_journal(workdir, "g9-l-lease"),
                        adapter=adapter)
    try:
        assert worker.lease_ok(model_id, token, 120) is False
        assert transport.calls == []
        assert host.service.get_transaction_status() == TRANSACTION_STATUS_IDLE
        assert host.control.get_transaction_status() == TRANSACTION_STATUS_IDLE
    finally:
        worker.journal.close()
    print("[G9-L/lease] session read committed 30s/5s/5s; timeout bound "
          "(0<timeout<=239); lease 61/180/299s; short remaining lease -> no HTTP")

    # A transaction left open by the caller must stop the worker before I/O.
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([])
    journal = make_journal(workdir, "g9-l-idle")
    try:
        worker = HostWorker(host, journal, adapter=adapter)
        with host.service.cursor() as cur:
            cur.execute("SELECT 1")
        assert host.service.get_transaction_status() != TRANSACTION_STATUS_IDLE
        _raises(HostContractError, worker.run_once, root)
        assert transport.calls == []
    finally:
        host.service.rollback()
        journal.close()
    print("[G9-L/idle] a caller-open transaction aborts the round before any "
          "transport call")

    # Journal: private modes, POSIX lock, version, truncation, secrets.
    path_dir = workdir / "g9-l-journal"
    path_dir.mkdir(mode=0o700)
    path = path_dir / "journal.jsonl"
    journal = HostJournal.open(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)
    journal.append("effect_prepared", str(uuid4()), "a" * 64,
                   {"kind": "model_call", "request": {}})
    _raises(JournalLocked, HostJournal.open, path)
    journal.close()

    bad = path_dir / "version.jsonl"
    bad.write_text(canonical_json({"v": 2, "seq": 1,
                                   "event_type": "effect_prepared",
                                   "effect_id": "e", "request_digest": "a" * 64,
                                   "claim": None, "payload": {}}) + "\n")
    os.chmod(bad, 0o600)
    _raises(JournalVersionError, HostJournal.open, bad)

    corrupt = path_dir / "corrupt.jsonl"
    corrupt.write_text('{"v":1,"seq":1,' + "\n")
    os.chmod(corrupt, 0o600)
    _raises(JournalCorrupt, HostJournal.open, corrupt)

    partial = path_dir / "partial.jsonl"
    good = canonical_json({"v": 1, "seq": 1, "event_type": "effect_prepared",
                           "effect_id": "e", "request_digest": "b" * 64,
                           "claim": None, "payload": {}}) + "\n"
    partial.write_text(good + '{"v":1,"seq":2')
    os.chmod(partial, 0o600)
    reopened = HostJournal.open(partial)
    try:
        assert len(reopened.records) == 1
    finally:
        reopened.close()

    secret = path_dir / "secret.jsonl"
    secret_journal = HostJournal.open(secret)
    try:
        _raises(Exception, secret_journal.append, "effect_prepared", "e",
                "c" * 64, {"api_key": "sk-should-not-be-written"})
    finally:
        secret_journal.close()
    print("[G9-L/journal] 0700/0600, second writer locked, unknown version and "
          "internal corruption fail, truncated tail trimmed, secret rejected")


# ---------------------------------------------------------------------------
# G9-J1: finished without settlement -> resubmit the saved outcome, no HTTP
# ---------------------------------------------------------------------------
def g9_j1(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="done", finish="stop")),
    ])
    journal = make_journal(workdir, "g9-j1")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            crash_after="finished")
        try:
            worker.run_once(root)
        except HostCrash:
            pass
        else:
            raise AssertionError("expected scripted crash")
        assert len(transport.calls) == 1
        assert effect_row(owner, model_id)["status"] == "claimed"
        first = journal.last("dispatch_finished", model_id)["payload"]["outcome"]

        adapter2, transport2, _ = adapter_for([])
        worker2 = HostWorker(host, journal, adapter=adapter2)
        stats = worker2.run_once(root)
        assert transport2.calls == []
        assert stats.reconciled == 1
        effect = effect_row(owner, model_id)
        assert effect["status"] == "succeeded", effect
        assert effect["outcome"] == first
        assert run_row(owner, run_id)["status"] == "completed"
        assert journal.has("settlement_committed", model_id)
        print("[G9-J1] finished without settlement: restart resubmits the exact "
              "saved outcome, zero HTTP, no duplicate model effect")
    finally:
        journal.close()

    # No dispatch_started: no external I/O happened, so the original token may
    # execute after re-reading DB eligibility; the prepared record is not
    # appended twice.
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([])
    journal = make_journal(workdir, "g9-j1-prepared")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            crash_after="prepared")
        try:
            worker.run_once(root)
        except HostCrash:
            pass
        else:
            raise AssertionError("expected prepared crash")
        assert transport.calls == []
        assert effect_row(owner, model_id)["status"] == "claimed"
        assert journal.prepared_without_dispatch() == [model_id]
        assert len([r for r in journal.records_for(model_id)
                    if r["event_type"] == "effect_prepared"]) == 1

        adapter2, transport2, _ = adapter_for([
            reply(chat_body(content="resumed", finish="stop")),
        ])
        stats = HostWorker(host, journal, adapter=adapter2).run_once(root)
        assert len(transport2.calls) == 1
        assert stats.executed == 1 and stats.settled == 1, stats
        assert run_row(owner, run_id)["status"] == "completed"
        assert len([r for r in journal.records_for(model_id)
                    if r["event_type"] == "effect_prepared"]) == 1
        assert len([r for r in journal.records_for(model_id)
                    if r["event_type"] == "dispatch_started"]) == 1
        assert journal.has("settlement_committed", model_id)
        print("[G9-J1/prepared] no dispatch_started: DB eligibility re-read, "
              "one prepared record, one HTTP call, run completed")
    finally:
        journal.close()


# ---------------------------------------------------------------------------
# G9-J2: recovery to unknown wins; an old journal result cannot revive the run
# ---------------------------------------------------------------------------
def g9_j2(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="done", finish="stop")),
    ])
    journal = make_journal(workdir, "g9-j2")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            crash_after="finished")
        try:
            worker.run_once(root)
        except HostCrash:
            pass
        with owner.cursor() as cur:
            cur.execute("UPDATE v24.effects SET lease_until=now()-interval '2 seconds' "
                        "WHERE effect_id=%s", (model_id,))
        owner.commit()
        recovered = host.recover(root, f"g9-j2-recover-{uuid4().hex}")
        assert recovered.get("disposition") == "committed", recovered
        unknown = effect_row(owner, model_id)
        assert unknown["status"] == "unknown"
        assert run_row(owner, run_id)["status"] == "blocked_unknown"

        adapter2, transport2, _ = adapter_for([])
        worker2 = HostWorker(host, journal, adapter=adapter2)
        worker2.run_once(root)
        assert transport2.calls == []
        assert effect_row(owner, model_id)["outcome"] == unknown["outcome"]
        assert run_row(owner, run_id)["status"] == "blocked_unknown"
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                     (run_id,)) == 1
        settlement = journal.last("settlement_committed", model_id)
        assert settlement["payload"]["conflict"] is True, settlement
        print("[G9-J2] recovery to unknown wins; the journaled success is "
              "recorded as a conflict, never resubmitted, no revival/successor")
    finally:
        journal.close()


# ---------------------------------------------------------------------------
# G9-J3: started without finished -> isolate while live, recover after expiry
# ---------------------------------------------------------------------------
def g9_j3(host, owner, workdir):
    root, run_id, model_id = fresh_run(host, owner)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="done", finish="stop")),
    ])
    journal = make_journal(workdir, "g9-j3")
    try:
        worker = HostWorker(host, journal, adapter=adapter,
                            crash_after="started")
        try:
            worker.run_once(root)
        except HostCrash:
            pass
        else:
            raise AssertionError("expected scripted crash")
        assert transport.calls == []
        assert effect_row(owner, model_id)["status"] == "claimed"
        assert journal.unfinished_dispatches() == [model_id]

        adapter2, transport2, _ = adapter_for([])
        worker2 = HostWorker(host, journal, adapter=adapter2)
        stats = worker2.run_once(root)
        assert transport2.calls == []
        assert stats.skipped == 1
        assert effect_row(owner, model_id)["status"] == "claimed"
        assert run_row(owner, run_id)["status"] == "running"

        with owner.cursor() as cur:
            cur.execute("UPDATE v24.effects SET lease_until=now()-interval '2 seconds' "
                        "WHERE effect_id=%s", (model_id,))
        owner.commit()
        adapter3, transport3, _ = adapter_for([])
        worker3 = HostWorker(host, journal, adapter=adapter3)
        stats3 = worker3.run_once(root)
        assert transport3.calls == []
        assert stats3.recovered == 1
        assert effect_row(owner, model_id)["status"] == "unknown"
        assert run_row(owner, run_id)["status"] == "blocked_unknown"
        assert count(owner, "v24.effects WHERE run_id=%s AND kind='model_call'",
                     (run_id,)) == 1
        print("[G9-J3] started without finished: live lease isolated with no "
              "re-send/sweep; after expiry one recovery sweep -> unknown")
    finally:
        journal.close()


# ---------------------------------------------------------------------------
# G9-R: closed surface, bounded rounds, no second queue/recovery state
# ---------------------------------------------------------------------------
def g9_r(host, owner, workdir):
    snapshot = _assert_closed_catalog(host.control)
    host.control.rollback()
    names = {name for name, kind in snapshot["relations"] if kind in ("r", "p")}
    assert "queue" not in names and "journal" not in names and "claim" not in names

    root, live = new_scope(host, owner)
    run_a, model_a = start_run(host, root, live)
    run_b, model_b = start_run(host, root, live)
    adapter, transport, _ = adapter_for([
        reply(chat_body(content="a", finish="stop")),
        reply(chat_body(content="b", finish="stop")),
    ])
    journal = make_journal(workdir, "g9-r")
    try:
        worker = HostWorker(host, journal, adapter=adapter)
        stats = worker.run_until_idle(root, max_rounds=1)
        assert stats.rounds == 1, stats
        assert stats.executed == 1, stats
        statuses = {effect_row(owner, model_a)["status"],
                    effect_row(owner, model_b)["status"]}
        assert statuses == {"succeeded", "ready"}, statuses
        assert len(transport.calls) == 1
    finally:
        journal.close()
    print("[G9-R/surface] closed ten-table catalog (no queue/claim/journal "
          "table); one bounded round executes one effect, remaining work is "
          "explicitly not a fairness promise")


def run_case(case, host, owner, workdir):
    table = {"G9-A": g9_a, "G9-B": g9_b, "G9-C": g9_c, "G9-D": g9_d,
             "G9-E": g9_e, "G9-F": g9_f, "G9-L": g9_l, "G9-J1": g9_j1,
             "G9-J2": g9_j2, "G9-J3": g9_j3, "G9-R": g9_r}
    table[case](host, owner, workdir)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    selected = ALL_CASES
    if args.only:
        requested = tuple(x.strip() for x in args.only.split(",") if x.strip())
        assert requested and set(requested) <= set(ALL_CASES), requested
        selected = requested

    assert_static_guards()
    install_no_network()
    try:
        with server_helper_scope(), setup_db() as fixture:
            owner = bind_owner(fixture)
            host = HostDB(fixture.role_dsn("admin"), fixture.role_dsn("service"))
            _assert_closed_catalog(fixture.connect())
            try:
                with tempfile.TemporaryDirectory(prefix="v24-g9-") as work:
                    workdir = Path(work)
                    os.chmod(workdir, 0o700)
                    for case in selected:
                        run_case(case, host, owner, workdir)
            finally:
                host.close()
                owner.close()
    finally:
        restore_no_network()
    print(f"[passed] v24 G9 M-R: {len(selected)} case(s): {', '.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
