"""W4c lifecycle, mixed batch, replay and legacy-byte gate.

G12-A…H + G12-L from design §7.3.  The tests use real Python/Node plugin
subprocesses, the local PostgreSQL test database and the existing journal
replay path.  No provider socket is opened and no real provider is constructed.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (HERE, HERE / "plugins", ROOT, ROOT / "v24" / "s11",
              ROOT / "v24" / "s1", ROOT / "v24" / "s2", ROOT / "v24" / "s4"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import server_helper_scope, setup_db  # noqa: E402

from plugin_fixtures import (  # noqa: E402
    PluginHarness,
    _chat_body,
    _owner,
    build_registry,
    build_spec,
    final_reply,
    model_adapter,
    tool_reply,
)
from fixtures import (  # noqa: E402
    DESCRIPTORS,
    V2Spec,
    install_spawn_log,
    manifest_bytes,
    node_spec,
    open_harness,
    read_spec,
    spawn_count,
    workspace,
)
from v24.host import line_json  # noqa: E402
from v24.host.db import HostDB  # noqa: E402
from v24.host.deepseek import _v2_provider_name  # noqa: E402
from v24.host.journal import HostJournal  # noqa: E402
from v24.host.plugins import PluginDispatcher  # noqa: E402
from v24.host.registry import (  # noqa: E402
    ApprovedAdapterRegistry,
    ApprovedPlugin,
    ApprovedTool,
    adapter_declaration_digest,
)
from v24.host.renderers import (  # noqa: E402
    RENDERERS, RendererError, RendererRef,
)
from v24.host.tool_pages import validate_page  # noqa: E402
from v24.host.worker import HostCrash, HostWorker  # noqa: E402

STUB = HERE / "w4_stub_plugin.py"
B0 = ROOT / "v24" / "b0" / "golden"


def node_path():
    return shutil.which("node")


class ZeroSpawn:
    def __init__(self):
        self.calls = []
        self._saved = None

    def __enter__(self):
        self._saved = line_json.run_process

        def sentinel(*args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("unexpected run_process call")

        line_json.run_process = sentinel
        return self

    def __exit__(self, exc_type, exc, tb):
        line_json.run_process = self._saved
        assert self.calls == [], self.calls
        return False


def batch_reply(calls, *, reasoning="plan", usage=(10, 5),
                response_id="resp-tool"):
    encoded = []
    for call_id, key, args in calls:
        encoded.append({
            "id": call_id,
            "type": "function",
            "function": {
                "name": _v2_provider_name(key),
                "arguments": json.dumps(args, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")),
            },
        })
    return {
        "status": 200,
        "advance_ms": 7,
        "raw": _chat_body(content=None, finish="tool_calls",
                          tool_calls=encoded, usage=usage,
                          reasoning=reasoning, response_id=response_id),
    }


def tool_effects(harness, model_id):
    found = []
    for record in harness.journal.records:
        if record.get("event_type") != "dispatch_finished":
            continue
        payload = record.get("payload") or {}
        if (payload.get("kind") == "tool_call"
                and str(payload.get("parent_effect_id")) == str(model_id)):
            found.append(harness.effect_row(record["effect_id"]))
    return found


def run_pins(harness, run_id):
    response = harness.db.host_run_pins(run_id, None, 64)
    assert not response.get("error"), response
    return {item["key"]: item for item in response.get("items", [])}


def two_install_harness(fixture, base, realm):
    portable = workspace(base / "portable", "portable")
    listing = workspace(base / "list", "list")
    read = read_spec(base / "read", portable.root, realm=realm)
    node = node_spec(base / "node", listing.root, realm=realm)
    harness = open_harness(fixture, [read, node], base / "harness", realm=realm)
    read_id = harness.admit(read)
    node_id = harness.admit(node)
    harness.prepare([read_id, node_id])
    harness.activate(read_id, "read")
    harness.activate(node_id, "list")
    return harness, read_id, node_id, read, node


def start_run(harness, owner_install, requires, text):
    fiber = harness.fiber(owner_install)
    response = harness.start(fiber["fiber_id"], requires,
                             [{"role": "user", "content": text}])
    return response["emitted"][0], response["emitted"][1]


def teardown_two_install(harness, install_ids):
    for install_id in install_ids:
        harness.off(install_id)
    for install_id in install_ids:
        harness.dispose(install_id)
    harness.run(None, max_rounds=16)
    for install_id in install_ids:
        row = harness.install_row(install_id)
        assert row["state"] == "disposed", row
        assert row["disposed_at"] is not None, row
        fiber = harness.fiber(install_id)
        assert fiber["disposed_at"] is not None, fiber
        assert harness.count(
            "v24.slots WHERE fiber_id=%s AND released_at IS NULL",
            (fiber["fiber_id"],)) == 0
    scope = harness.close_scope()
    assert scope["closed_at"] is not None, scope


def stub_spec(base, workspace_root, scenario, *, timeout_ms=5000, realm=None):
    base = Path(base)
    install = base / "install"
    install.mkdir(parents=True, exist_ok=True)
    artifact = install / "w4_stub_plugin.py"
    shutil.copyfile(STUB, artifact)
    descriptor = copy.deepcopy(DESCRIPTORS["read"])
    descriptor["tool"]["key"] = "read"
    descriptor["tool"]["description"] = "W4c stub read"
    descriptor["tool"]["limits"]["timeout_ms"] = timeout_ms
    descriptor["tool"]["parameters"]["properties"]["scenario"] = {
        "type": "string",
        "enum": ["ok", "known_error", "bad_frame", "extra_frame", "no_lf",
                 "timeout", "nonempty_meta", "bad_value", "bad_relation",
                 "huge_value", "crash", "grandchild", "kill_parent"],
    }
    realm = realm or f"w4c-stub-{uuid.uuid4().hex[:8]}"
    manifest = manifest_bytes("v24.w4c.stub", realm, [descriptor], "python")
    spawn = base / "spawn"; spawn.mkdir(exist_ok=True)
    log = spawn / f"{uuid.uuid4().hex}.log"
    tool = ApprovedTool.from_descriptor(descriptor, key="read")
    plugin = ApprovedPlugin(
        adapter_id=f"v24.w4c.stub.{realm}",
        language="python",
        identity="v24.w4c.stub",
        version="1",
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
        artifact_digest=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        adapter_digest=adapter_declaration_digest("python"),
        argv=(sys.executable, str(artifact), "serve",
              "--spawn-log", str(log)),
        cwd=str(install),
        environment_allowlist=("PATH", "HOME", "V24_WORKSPACE_ROOT"),
        tools=(tool,),
        workspace_root=os.path.realpath(workspace_root),
    )
    return V2Spec(
        language="python", identity="v24.w4c.stub", realm=realm,
        tool_keys=("read",), manifest=manifest,
        artifact_digest=plugin.artifact_digest, entry=plugin,
        spawn_log=log, workspace=os.path.realpath(workspace_root),
        env_overlay=(),
    )


def run_stub(fixture, base, scenario, args, *, timeout_ms=5000):
    empty = workspace(base / "empty", "empty")
    spec = stub_spec(base, empty.root, scenario, timeout_ms=timeout_ms)
    harness = open_harness(fixture, [spec], base / "harness", realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        run_id, model_id = start_run(harness, install_id, ["read"], scenario)
        script = [batch_reply([("call_1", "read", args)]),
                  final_reply("must-not-run")]
        harness.run(script, max_rounds=20)
        effects = tool_effects(harness, model_id)
        assert len(effects) == 1, effects
        return harness, install_id, run_id, model_id, effects[0], spec
    except Exception:
        harness.close()
        raise


# --- W7 recovery helpers ---------------------------------------------------
# The helpers below are additive: the G12 cases above and their helpers do not
# call them, so the v24 W4c gate keeps its existing behaviour and byte-exact
# legacy assertions.  W7 cases (r01_* … r16_*) use them to drive crash windows,
# fresh-process reconciliation and scope-level invariant checks.


class CountingSpawn:
    """Count plugin processes at the single ``line_json.run_process`` seam."""

    def __init__(self, artifact=None, expected=None):
        self.artifact = None if artifact is None else os.path.realpath(artifact)
        self.expected = expected
        self.calls = []
        self.ops = {}
        self._saved = None

    def __enter__(self):
        self._saved = line_json.run_process

        def counted(spec):
            argv = tuple(getattr(spec, "argv", ()))
            matched = self.artifact is None or (
                len(argv) > 1 and os.path.realpath(argv[1]) == self.artifact)
            if matched:
                operation = json.loads(spec.stdin)["operation"]
                self.calls.append(spec)
                self.ops[operation] = self.ops.get(operation, 0) + 1
            return self._saved(spec)

        line_json.run_process = counted
        return self

    def __exit__(self, exc_type, exc, tb):
        line_json.run_process = self._saved
        if self.expected is not None:
            assert len(self.calls) == self.expected, (
                self.expected, len(self.calls), self.ops)
        return False


def spawn_ops(harness, install_id):
    """Parse ``<pid> <operation>`` spawn-log lines into an operation count."""
    path = install_spawn_log(harness, install_id)
    if path is None or not path.exists():
        return {}
    ops = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        assert len(fields) == 2 and fields[0].isdigit(), (
            f"unparseable spawn log line {line!r}: {path}")
        ops[fields[1]] = ops.get(fields[1], 0) + 1
    return ops


def tool_effect_id(model_id, ordinal):
    """Same identity as ``v24.tool_effect_id`` (48_loop.sql:45-47)."""
    return uuid.UUID(hashlib.md5(
        f"{model_id}:tool_call:{ordinal}".encode()).hexdigest())


def tool_order(model_id, n=3):
    """Ordinals in execution order: ascending tool-effect UUID."""
    return sorted(range(n), key=lambda ordinal: tool_effect_id(model_id, ordinal))


def open_connections(harness):
    """Open owner → db → journal → worker, replacing the harness handles."""
    lease_ms = getattr(getattr(harness, "worker", None), "default_lease_ms", 30000)
    owner = _owner(harness.fixture.connect())
    db = None
    journal = None
    try:
        db = HostDB(harness.fixture.role_dsn("admin"),
                    harness.fixture.role_dsn("service"))
        journal = HostJournal.open(harness.workdir / "plugin-journal.jsonl")
        dispatcher = PluginDispatcher(db, harness.registry)
        worker = HostWorker(db, journal,
                            tool_handler=dispatcher.tool_handler,
                            resource_handler=dispatcher.resource_handler,
                            default_lease_ms=lease_ms)
    except BaseException:
        if journal is not None:
            journal.close()
        if db is not None:
            db.close()
        owner.close()
        raise
    harness.owner = owner
    harness.db = db
    harness.journal = journal
    harness.dispatcher = dispatcher
    harness.worker = worker
    return harness


def reopen_harness(harness):
    """Reopen every handle after the caller closed it; never closes for them."""
    return open_connections(harness)


def close_connections(harness):
    """Close journal → db → owner (PluginHarness.close order); lock stays open."""
    harness.journal.close()
    harness.db.close()
    harness.owner.close()


def assert_fork_safe(harness):
    """The parent may only fork once every mutable connection is closed."""
    assert harness.journal._fd == -1, harness.journal._fd
    assert harness.db._closed is True, harness.db._closed
    assert harness.db.control.closed == 1, harness.db.control.closed
    assert harness.db.service.closed == 1, harness.db.service.closed
    assert harness.owner.closed == 1, harness.owner.closed
    fixture = harness.fixture
    assert all(conn.closed == 1 for conn in fixture._connections), [
        conn.closed for conn in fixture._connections]
    lock = fixture._lock_conn
    assert lock is not None, "the test database lock was released before fork"
    assert lock.closed == 0, lock.closed


def inject_after(harness, event_type, *, effect_id=None, kind=None,
                 exc=HostCrash):
    """One-shot post-append crash: journal fsynced, the next line not written."""
    original = harness.journal.append
    state = {"done": False}

    def restore():
        harness.journal.append = original

    def wrapper(event_type_, effect_id_, digest, payload, **kwargs):
        result = original(event_type_, effect_id_, digest, payload, **kwargs)
        matched = (
            not state["done"]
            and event_type_ == event_type
            and (effect_id is None or str(effect_id_) == str(effect_id))
            and (kind is None or payload.get("kind") == kind))
        if matched:
            state["done"] = True
            restore()
            raise exc(f"injected after {event_type}")
        return result

    harness.journal.append = wrapper
    return restore


def inject_before(harness, event_type, *, effect_id=None, kind=None,
                  exc=HostCrash, hits=None):
    """One-shot pre-append crash: DB committed, journal line not written."""
    original = harness.journal.append
    state = {"done": False}

    def restore():
        harness.journal.append = original

    def wrapper(event_type_, effect_id_, digest, payload, **kwargs):
        outcome = payload.get("outcome") if isinstance(payload, dict) else None
        body = outcome.get("body") if isinstance(outcome, dict) else None
        body_kind = body.get("kind") if isinstance(body, dict) else None
        matched = (
            not state["done"]
            and event_type_ == event_type
            and (effect_id is None or str(effect_id_) == str(effect_id))
            and (kind is None or body_kind == kind))
        if matched and event_type_ == "settlement_committed":
            matched = (
                "outcome" in payload and "response" in payload
                and not payload.get("reconciled")
                and "reason" not in payload and "conflict" not in payload)
        if matched:
            state["done"] = True
            restore()
            if hits is not None:
                hits.append(effect_id_)
            raise exc(f"injected before {event_type}")
        return original(event_type_, effect_id_, digest, payload, **kwargs)

    harness.journal.append = wrapper
    return restore


def install_crash_after_started(worker):
    """Set ``crash_after='started'`` only while the tool branch runs."""
    original = worker._execute_tool

    def restore():
        worker.crash_after = None
        worker._execute_tool = original

    def wrapper(*args, **kwargs):
        worker.crash_after = "started"
        try:
            return original(*args, **kwargs)
        finally:
            worker.crash_after = None

    worker._execute_tool = wrapper
    return restore, original


def assert_single_receipt(harness, effect_id, *, journal_finish,
                          db_recovery=False, snapshot=None):
    """One terminal DB receipt (plus the journal receipt when it exists)."""
    effect = harness.effect_row(effect_id)
    assert effect["status"] in (
        "succeeded", "failed", "unknown", "cancelled"), effect
    assert effect["settled_at"] is not None, effect
    if snapshot is not None:
        for name in ("attempt_no", "fence", "settled_at"):
            assert effect[name] == snapshot[name], (name, snapshot, effect)
    finishes = [record for record in harness.journal.records
                if record["event_type"] == "dispatch_finished"
                and str(record["effect_id"]) == str(effect_id)]
    settlements = settlement_count(harness, effect_id)
    if journal_finish:
        assert len(finishes) == 1, (effect_id, finishes)
        assert settlements == 1, (effect_id, settlements)
    else:
        assert finishes == [], (effect_id, finishes)
        assert settlements == 0, (effect_id, settlements)
    if db_recovery:
        with harness.owner.cursor() as cur:
            cur.execute(
                "SELECT payload FROM v24.events "
                "WHERE entity_type='effect' AND entity_id=%s "
                "AND event_kind='effect_recovered_unknown' ORDER BY event_id",
                (str(effect_id),))
            events = [row[0] for row in cur.fetchall()]
        harness.owner.commit()
        assert len(events) == 1, (effect_id, events)
        assert events[0].get("action") == "settle_unknown", (effect_id, events)
        assert events[0].get("reason") == "lease_expired", (effect_id, events)
    before = settlement_count(harness)
    assert harness.worker._reconcile(harness.scope) == 0, effect_id
    assert settlement_count(harness) == before, effect_id


def capture_effect(harness, effect_id):
    """Snapshot the effect row fields that a restart must not rewrite."""
    effect = harness.effect_row(effect_id)
    return {name: effect.get(name) for name in
            ("status", "outcome", "settled_at", "attempt_no", "fence")}


def run_recover_process(harness, scope):
    """Close parent handles, reconcile in a fresh process, return (N, M)."""
    close_connections(harness)
    environment = dict(os.environ)
    environment["V24_W7_ADMIN_DSN"] = harness.fixture.role_dsn("admin")
    environment["V24_W7_SERVICE_DSN"] = harness.fixture.role_dsn("service")
    completed = subprocess.run(
        [sys.executable, str(HERE / "w7_recover.py"),
         str(harness.workdir / "plugin-journal.jsonl"), str(scope)],
        env=environment, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (
        completed.returncode, completed.stdout, completed.stderr)
    match = re.search(r"\[w7-recover\] reconciled=(\d+) settlements=(\d+)",
                      completed.stdout)
    assert match is not None, (completed.stdout, completed.stderr)
    return int(match.group(1)), int(match.group(2))


def assert_no_live(pid, timeout_s=2.0):
    """Observe only: an empty or zombie ``ps`` state means the pid is gone."""
    deadline = time.monotonic() + timeout_s
    while True:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True, text=True)
        state = completed.stdout.strip()
        if not state or state.startswith("Z"):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"pid {pid} is still live: {state!r}")
        time.sleep(0.05)


def settlement_count(harness, effect_id=None):
    return sum(1 for record in harness.journal.records
               if record["event_type"] == "settlement_committed"
               and (effect_id is None
                    or str(record["effect_id"]) == str(effect_id)))


def assert_w7_invariants(harness, *, recovered_unknown=frozenset()):
    """Scope-level I1–I5 aggregate; run-level counts stay in each case."""
    expected = {str(item) for item in recovered_unknown}

    def envelope(name, response):
        assert not (isinstance(response, dict)
                    and isinstance(response.get("error"), dict)), (name, response)
        assert isinstance(response.get("items"), list), (name, response)
        return response

    runs = []
    after_created_at = after_run_id = None
    while True:
        response = envelope("host_runs", harness.db.host_runs(
            harness.scope, after_created_at, after_run_id, 64))
        runs.extend(response["items"])
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor") or {}
        after_created_at = cursor.get("created_at")
        after_run_id = cursor.get("run_id")
        assert after_created_at is not None and after_run_id is not None, response

    tool_effects = []
    for run in runs:
        run_id = run["run_id"]
        after_created_at = after_effect_id = None
        while True:
            response = envelope("host_run_effects", harness.db.host_run_effects(
                run_id, after_created_at, after_effect_id, 64))
            tool_effects.extend(item for item in response["items"]
                                if item.get("kind") == "tool_call")
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor") or {}
            after_created_at = cursor.get("created_at")
            after_effect_id = cursor.get("effect_id")
            assert (after_created_at is not None
                    and after_effect_id is not None), response

    keys = {str(item["effect_id"]) for item in tool_effects}
    assert expected <= keys, (sorted(expected - keys), sorted(keys))

    for item in tool_effects:
        effect_id = item["effect_id"]
        key = str(effect_id)
        assert item.get("replay_policy") == "no_replay", (key, item)
        assert harness.count(
            "v24.events WHERE entity_type='effect' AND entity_id=%s "
            "AND event_kind='effect_recovered_replay'", (key,)) == 0, key
        assert item.get("status") in (
            "succeeded", "failed", "unknown", "cancelled"), (key, item)
        assert item.get("settled_at") is not None, (key, item)
        with harness.owner.cursor() as cur:
            cur.execute(
                "SELECT payload FROM v24.events "
                "WHERE entity_type='effect' AND entity_id=%s "
                "AND event_kind='effect_recovered_unknown' ORDER BY event_id",
                (key,))
            events = [row[0] for row in cur.fetchall()]
        harness.owner.commit()
        if key in expected:
            assert len(events) == 1, (key, events)
            assert events[0].get("action") == "settle_unknown", (key, events)
            assert events[0].get("reason") == "lease_expired", (key, events)
        else:
            assert events == [], (key, events)
        finishes = [record for record in harness.journal.records
                    if record["event_type"] == "dispatch_finished"
                    and str(record["effect_id"]) == key]
        settlements = settlement_count(harness, effect_id)
        if finishes:
            assert len(finishes) == 1, (key, finishes)
            assert settlements == 1, (key, settlements)
        else:
            assert settlements == 0, (key, settlements)

    leftovers = envelope("host_effects", harness.db.host_effects(harness.scope))
    assert not [item for item in leftovers["items"]
                if item.get("kind") == "tool_call"], leftovers["items"]

    before = settlement_count(harness)
    assert harness.worker._reconcile(harness.scope) == 0
    assert settlement_count(harness) == before

    after_install = None
    while True:
        response = envelope(
            "host_scope_installs",
            harness.db.host_scope_installs(harness.scope, after_install, 64))
        for install in response["items"]:
            install_id = install["install_id"]
            log_path = install_spawn_log(harness, install_id)
            if log_path is None:
                continue
            lines = (log_path.read_text(encoding="utf-8").splitlines()
                     if log_path.exists() else [])
            ops = spawn_ops(harness, install_id)
            assert sum(ops.values()) == len(lines), (install_id, ops, lines)
            assert ops.get("prepare", 0) <= 1, (install_id, ops)
            assert ops.get("release", 0) <= 1, (install_id, ops)
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor") or {}
        after_install = cursor.get("install_id")
        assert after_install is not None, response


def g12_a(fixture, base):
    harness, read_id, node_id, read, node = two_install_harness(
        fixture, base / "a", f"w4c-a-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "g12-a")
        script = [
            batch_reply([
                ("call_read", "read", {"path": "tail"}),
                ("call_list", "list", {"path": "."}),
                ("call_search", "search", {"query": "x"}),
            ]),
            final_reply("g12-a-final"),
        ]
        harness.run(script, max_rounds=30)
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        assert run["result"]["final_text"] == "g12-a-final", run
        effects = tool_effects(harness, model_id)
        assert len(effects) == 3, effects
        by_key = {item["request"]["key"]: item for item in effects}
        assert set(by_key) == {"read", "list", "search"}, by_key
        for key in by_key:
            assert by_key[key]["outcome"]["class"] == "success", by_key[key]
            value = by_key[key]["outcome"]["body"]["result"]["output"]["value"]
            assert value["path"] in ("tail", "."), value
            tool = (read.entry if key == "read" else node.entry).tool_for(key)
            assert tool is not None
            tool.output_check(value)
            validate_page(tool.render, by_key[key]["request"]["args"], value)
        pins = run_pins(harness, run_id)
        assert pins["list"]["provider_install_id"] == \
            pins["search"]["provider_install_id"]
        assert pins["read"]["provider_install_id"] != \
            pins["list"]["provider_install_id"]
        assert spawn_count(harness, read_id) == 2, spawn_count(harness, read_id)
        assert spawn_count(harness, node_id) == 3, spawn_count(harness, node_id)
        teardown_two_install(harness, [read_id, node_id])
    finally:
        harness.close()


def g12_b(fixture, base):
    harness, read_id, node_id, _read, _node = two_install_harness(
        fixture, base / "b", f"w4c-b-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "g12-b")
        script = [
            batch_reply([
                ("call_read", "read", {"path": "tail"}),
                ("call_list", "list", {"path": "."}),
                ("call_search", "search", {"query": "x"}),
            ]),
            final_reply("g12-b-final"),
        ]
        harness.run(script, max_rounds=30)
        assert len(harness._transport.calls) == 2, len(harness._transport.calls)
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'",
            (run_id,)) == 2
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,)) == 1
        pins = run_pins(harness, run_id)
        assert pins["list"]["provider_install_id"] == \
            pins["search"]["provider_install_id"]
        assert len(tool_effects(harness, model_id)) == 3
    finally:
        harness.close()


def g12_c(fixture, base):
    portable = workspace(base / "c" / "portable", "portable")
    spec = read_spec(base / "c" / "read", portable.root,
                     realm=f"w4c-c-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "c" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        baseline = spawn_count(harness, install_id)
        run_id, model_id = start_run(harness, install_id, ["read"], "g12-c")
        with ZeroSpawn():
            harness.run([
                batch_reply([("call_1", "read",
                              {"path": "tail", "offset": 0})]),
                final_reply("after-invalid"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "invalid_tool_arguments", result
        assert spawn_count(harness, install_id) == baseline
    finally:
        harness.close()


def g12_d(fixture, base):
    for scenario in ("bad_value", "bad_relation"):
        harness, install_id, _run_id, _model_id, effect, _spec = run_stub(
            fixture, base / "d" / scenario, scenario,
            {"path": "a.txt", "scenario": scenario})
        try:
            assert effect["outcome"]["class"] == "failure", effect
            result = effect["outcome"]["body"]["result"]
            assert result["output"]["error"]["code"] == "invalid_tool_output", result
            assert spawn_count(harness, install_id) == 2
        finally:
            harness.close()

    portable = workspace(base / "d" / "render", "portable")
    spec = read_spec(base / "d" / "render-read", portable.root,
                     realm=f"w4c-d-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "d" / "render-harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        _run_id, model_id = start_run(harness, install_id, ["read"], "g12-d")
        with patch.object(RENDERERS, "render",
                          side_effect=RendererError("render_failed")):
            harness.run([
                batch_reply([("call_1", "read", {"path": "tail"})]),
                final_reply("after-render"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "render_failed", result
        assert spawn_count(harness, install_id) == 2
    finally:
        harness.close()


def g12_e(fixture, base):
    harness, install_id, run_id, _model_id, effect, _spec = run_stub(
        fixture, base / "e", "timeout", {"path": "a.txt", "scenario": "timeout"},
        timeout_ms=300)
    try:
        assert effect["outcome"]["class"] == "unknown", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "timeout", result
        assert harness.run_row(run_id)["status"] == "blocked_unknown"
        assert spawn_count(harness, install_id) == 2
        assert len(harness._transport.calls) == 1
    finally:
        harness.close()


def tamper_case(fixture, base, kind):
    portable = workspace(base / "portable", "portable")
    spec = read_spec(base / "read", portable.root,
                     realm=f"w4c-f-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "harness", realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        baseline = spawn_count(harness, install_id)
        _run_id, model_id = start_run(harness, install_id, ["read"], kind)
        if kind == "artifact":
            broken = dataclasses.replace(spec.entry, artifact_digest="0" * 64)
            expected = "adapter_not_approved"
        elif kind == "adapter":
            broken = dataclasses.replace(spec.entry, adapter_digest="0" * 64)
            expected = "adapter_not_approved"
        else:
            changed = json.loads(json.dumps(spec.entry.tools[0].descriptor))
            changed["tool"]["description"] = "tampered descriptor"
            broken = dataclasses.replace(
                spec.entry, tools=(ApprovedTool.from_descriptor(
                    changed, key="read"),))
            expected = "descriptor_mismatch"
        harness.dispatcher.registry = ApprovedAdapterRegistry((broken,))
        with ZeroSpawn():
            harness.run([
                batch_reply([("call_1", "read", {"path": "tail"})]),
                final_reply("after-tamper"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        output = result["output"]
        code = (output.get("error") or {}).get("code") or output.get("code")
        assert code == expected, result
        assert spawn_count(harness, install_id) == baseline
    finally:
        harness.close()


def g12_f(fixture, base):
    for kind in ("artifact", "adapter", "descriptor"):
        tamper_case(fixture, base / "f" / kind, kind)


def g12_g(fixture, base):
    portable = workspace(base / "g" / "portable", "portable")
    spec = read_spec(base / "g" / "read", portable.root,
                     realm=f"w4c-g-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "g" / "harness",
                           realm=spec.realm)
    called = []
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        _run_id, model_id = start_run(harness, install_id, ["read"], "g12-g")
        original_execute_tool = harness.worker._execute_tool

        def crash_after_tool(*args, **kwargs):
            harness.worker.crash_after = "finished"
            return original_execute_tool(*args, **kwargs)

        harness.worker._execute_tool = crash_after_tool
        try:
            harness.run([
                batch_reply([("call_1", "read", {"path": "tail"})]),
                final_reply("after-crash"),
            ], max_rounds=20)
        except HostCrash:
            pass
        else:
            raise AssertionError("crash_after=finished did not raise")
        harness.worker.crash_after = None
        effects = tool_effects(harness, model_id)
        assert len(effects) == 1, effects
        effect = effects[0]
        record = next(item for item in harness.journal.records
                      if item["event_type"] == "dispatch_finished"
                      and item["effect_id"] == effect["effect_id"])
        original_content = record["payload"]["tool_message"]["content"]
        original_types = {item["event_type"] for item in harness.journal.records}
        original_spawn = spawn_count(harness, install_id)
        tool = spec.entry.tools[0]
        original_render = tool.render
        object.__setattr__(
            tool, "render",
            RendererRef(original_render.id, original_render.version, "0" * 64))
        assert tool.render.digest != original_render.digest
        original_settlements = len([
            item for item in harness.journal.records
            if item["event_type"] == "settlement_committed"
            and item["effect_id"] == effect["effect_id"]])
        harness.journal.close()
        journal = HostJournal.open(harness.workdir / "plugin-journal.jsonl")

        def raising(effect):
            called.append(effect["effect_id"])
            raise AssertionError("replay called the tool handler")

        worker = HostWorker(harness.db, journal, tool_handler=raising,
                            resource_handler=harness.dispatcher.resource_handler)
        harness.journal = journal
        harness.worker = worker
        settled = worker._reconcile(harness.scope)
        assert settled >= 1, settled
        assert called == [], called
        after = harness.effect_row(effect["effect_id"])
        assert after["status"] == "succeeded", after
        settlement = journal.last("settlement_committed", effect["effect_id"])
        assert settlement is not None
        assert settlement["payload"].get("reconciled") is True, settlement
        after_record = next(item for item in journal.records
                            if item["event_type"] == "dispatch_finished"
                            and item["effect_id"] == effect["effect_id"])
        assert after_record["payload"]["tool_message"]["content"] == \
            original_content
        assert spawn_count(harness, install_id) == original_spawn
        assert {item["event_type"] for item in journal.records} == original_types
        settlements = len([
            item for item in journal.records
            if item["event_type"] == "settlement_committed"
            and item["effect_id"] == effect["effect_id"]])
        assert settlements == original_settlements + 1, (
            original_settlements, settlements)
        return {
            "replay_source": "journal tool_message",
            "rerender": False,
            "second_spawn": False,
            "journal_event_types_unchanged": True,
            "model_text_source": "journal",
        }
    finally:
        harness.close()


def g12_h(fixture, base):
    listing = workspace(base / "h" / "list", "list")
    spec = node_spec(base / "h" / "node", listing.root,
                     realm=f"w4c-h-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "h" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "search")
        harness.worker.default_lease_ms = 19999
        baseline = spawn_count(harness, install_id)
        _run_id, model_id = start_run(harness, install_id, ["search"], "g12-h")
        with ZeroSpawn():
            harness.run([
                batch_reply([("call_1", "search", {"query": "x"})]),
                final_reply("after-lease"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "lease_insufficient", result
        assert spawn_count(harness, install_id) == baseline
    finally:
        harness.close()


def g12_l(fixture, base):
    requests = json.loads((B0 / "provider_requests_v1.json").read_text(
        encoding="utf-8"))["cases"]
    messages = json.loads((B0 / "tool_messages_v1.json").read_text(
        encoding="utf-8"))["cases"]
    request_by_id = {case["id"]: case for case in requests}
    message_by_id = {case["id"]: case for case in messages}
    for label, args in (("success", {"text": "snow 雪", "zero": 0}),
                        ("known_error", {"__tool_error__": True})):
        realm = f"w4c-l-{label}-{uuid.uuid4().hex[:8]}"
        spec = build_spec("python", realm=realm, tool_key="echo.python",
                          identity=f"v24.w4c.legacy.{label}")
        harness_dir = base / "l" / label / "harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(harness_dir, 0o700)
        harness = PluginHarness(fixture, build_registry(spec),
                                harness_dir, realm=realm)
        try:
            install_id = harness.admit(spec)
            harness.prepare([install_id])
            harness.activate(install_id, spec.tool_key)
            run_id, _model_id = start_run(
                harness, install_id, [spec.tool_key], "B0 fixed echo")
            call_id = f"call_b0_{label}"
            script = [
                tool_reply(call_id, spec.tool_key, args,
                           reasoning="B0 fixed", usage=(17, 9),
                           response_id=f"resp_b0_{label}"),
                final_reply("B0 final", reasoning="B0 done", usage=(22, 3),
                            response_id=f"final_b0_{label}"),
            ]
            harness.run(script, max_rounds=30)
            assert len(harness._transport.calls) == 2
            for index, case_id in enumerate(
                    (f"provider.{label}.request1",
                     f"provider.{label}.request2")):
                expected = bytes.fromhex(request_by_id[case_id]["expected_hex"])
                assert harness._transport.calls[index]["body"] == expected, (
                    label, index)
            record = next(item for item in harness.journal.records
                          if item["event_type"] == "dispatch_finished"
                          and item["payload"].get("kind") == "tool_call")
            content = record["payload"]["tool_message"]["content"]
            expected_message = bytes.fromhex(
                message_by_id[f"tool_message.{label}.content"]["expected_hex"])
            assert content.encode("utf-8") == expected_message, (label, content)
        finally:
            harness.close()


def r01_prepared_resume(fixture, base):
    """K0 tool: crash after effect_prepared, restart resumes exactly once."""
    portable = workspace(base / "r01" / "portable", "portable")
    spec = read_spec(base / "r01" / "read", portable.root,
                     realm=f"w7-r01-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r01" / "harness",
                           realm=spec.realm)
    try:
        with CountingSpawn(expected=2) as spawn:
            install_id = harness.admit(spec)
            harness.prepare([install_id])
            harness.activate(install_id, "read")
            run_id, model_id = start_run(
                harness, install_id, ["read"], "r01")
            target = tool_effect_id(model_id, 0)
            restore = inject_after(harness, "effect_prepared",
                                   effect_id=target, kind="tool_call")
            try:
                harness.run(
                    [batch_reply([("call_read", "read", {"path": "tail"})])],
                    max_rounds=20)
            except HostCrash:
                pass
            else:
                raise AssertionError("r01 did not crash after effect_prepared")
            finally:
                restore()

            effect = harness.db.host_effect(target)["effect"]
            assert effect["status"] == "claimed", effect
            assert harness.journal.last(
                "effect_prepared", str(target)) is not None
            last = harness.journal.records[-1]
            assert (last["event_type"], last["effect_id"]) == (
                "effect_prepared", str(target)), last
            assert not harness.journal.has("dispatch_started", str(target))
            ops = spawn_ops(harness, install_id)
            assert ops.get("prepare") == 1, ops
            assert ops.get("invoke", 0) == 0, ops
            crash = {
                "status": effect["status"],
                "journal_last": last["event_type"],
                "dispatch_started": harness.journal.has(
                    "dispatch_started", str(target)),
                "spawn_ops": ops,
            }

            harness.run([final_reply("r01-final")], max_rounds=20)

            effect = harness.effect_row(target)
            assert effect["status"] == "succeeded", effect
            counts = {}
            for event_type in ("dispatch_started", "dispatch_finished",
                               "settlement_committed"):
                count = sum(1 for record in harness.journal.records
                            if record["event_type"] == event_type
                            and record["effect_id"] == str(target))
                assert count == 1, (event_type, count)
                counts[event_type] = count
            run = harness.run_row(run_id)
            assert run["status"] == "completed", run
            final_ops = spawn_ops(harness, install_id)
            assert final_ops == {"prepare": 1, "invoke": 1}, final_ops
            assert_single_receipt(harness, target, journal_finish=True)
            assert_w7_invariants(harness)
            evidence = {
                "crash": crash,
                "effect_status": effect["status"],
                "run_status": run["status"],
                "journal_counts": counts,
                "spawn_ops": final_ops,
            }
        assert len(spawn.calls) == 2, spawn.calls
        assert spawn.ops == {"prepare": 1, "invoke": 1}, spawn.ops
        evidence["spawn_calls"] = len(spawn.calls)
    finally:
        harness.close()
    return evidence


def r02_started_lease_expiry(fixture, base):
    """K1 tool: crash after dispatch_started, live skip, then lease expiry."""
    portable = workspace(base / "r02" / "portable", "portable")
    spec = read_spec(base / "r02" / "read", portable.root,
                     realm=f"w7-r02-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r02" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        harness.worker.default_lease_ms = 3000
        run_id, model_id = start_run(harness, install_id, ["read"], "r02")
        target = tool_effect_id(model_id, 0)

        restore, original = install_crash_after_started(harness.worker)
        with ZeroSpawn() as zero:
            try:
                harness.run(
                    [batch_reply([("call_read", "read", {"path": "tail"})])],
                    max_rounds=20)
            except HostCrash:
                pass
            else:
                raise AssertionError("r02 did not crash after dispatch_started")
            finally:
                restore()
        assert zero.calls == [], zero.calls
        assert harness.worker.crash_after is None
        assert harness.worker._execute_tool is original

        started = [record for record in harness.journal.records
                   if record["event_type"] == "dispatch_started"
                   and record["payload"].get("kind") == "tool_call"]
        assert len(started) == 1, started
        effect_id = started[0]["effect_id"]
        assert str(effect_id) == str(target), (effect_id, target)
        effect = harness.db.host_effect(effect_id)["effect"]
        assert effect["status"] == "claimed", effect
        assert not harness.journal.has("dispatch_finished", str(effect_id))
        ops = spawn_ops(harness, install_id)
        assert ops.get("prepare") == 1, ops
        assert ops.get("invoke", 0) == 0, ops

        live = harness.run(None, max_rounds=2)
        assert live.skipped >= 1, live
        assert harness.db.host_effect(effect_id)["effect"]["status"] == \
            "claimed"

        deadline = time.monotonic() + (
            harness.worker.default_lease_ms + 2000) / 1000
        while True:
            remaining = harness.db.remaining_lease_ms(
                harness.db.host_effect(effect_id)["effect"]["lease_until"])
            if remaining <= 0:
                break
            assert time.monotonic() < deadline, remaining
            time.sleep(0.05)

        harness.run(None, max_rounds=4)
        effect = harness.db.host_effect(effect_id)["effect"]
        assert effect["status"] == "unknown", effect
        run = harness.run_row(run_id)
        assert run["status"] == "blocked_unknown", run
        assert not harness.journal.has("dispatch_finished", str(effect_id))
        assert harness.journal.records[-1]["event_type"] == "dispatch_started"
        final_ops = spawn_ops(harness, install_id)
        assert final_ops.get("invoke", 0) == 0

        before_records = len(harness.journal.records)
        before_settlements = settlement_count(harness)
        third = harness.run(None, max_rounds=2)
        assert third.recovered == 0, third
        assert len(harness.journal.records) == before_records
        assert settlement_count(harness) == before_settlements

        assert_single_receipt(harness, effect_id, journal_finish=False,
                              db_recovery=True)
        with harness.owner.cursor() as cur:
            cur.execute(
                "SELECT payload FROM v24.events "
                "WHERE entity_type='effect' AND entity_id=%s "
                "AND event_kind='effect_recovered_unknown'",
                (str(effect_id),))
            events = [row[0] for row in cur.fetchall()]
        harness.owner.commit()
        assert_w7_invariants(harness, recovered_unknown={target})
        evidence = {
            "crash": {
                "status": "claimed",
                "journal_last": "dispatch_started",
                "spawn_ops": ops,
            },
            "live_skipped": live.skipped,
            "effect_status": effect["status"],
            "run_status": run["status"],
            "db_recovery_event": {
                "count": len(events),
                "action": events[0].get("action"),
                "reason": events[0].get("reason"),
            },
            "journal_counts": {
                "dispatch_started": len(started),
                "dispatch_finished": sum(
                    1 for record in harness.journal.records
                    if record["event_type"] == "dispatch_finished"
                    and record["effect_id"] == str(effect_id)),
                "settlement_committed": settlement_count(harness, effect_id),
            },
            "spawn_ops": final_ops,
            "third_recovered": third.recovered,
        }
    finally:
        harness.close()
    return evidence


def r07_prepare_resume(fixture, base):
    """K0 host_prepare: crash after effect_prepared, restart prepares once."""
    portable = workspace(base / "r07" / "portable", "portable")
    spec = read_spec(base / "r07" / "read", portable.root,
                     realm=f"w7-r07-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r07" / "harness",
                           realm=spec.realm)
    try:
        with CountingSpawn(expected=3) as spawn:
            install_id = harness.admit(spec)
            assert harness.install_row(install_id)["state"] == "preparing"

            restore = inject_after(harness, "effect_prepared",
                                   kind="host_prepare")
            try:
                harness.run(None, max_rounds=2)
            except HostCrash:
                pass
            else:
                raise AssertionError(
                    "r07 did not crash after host_prepare effect_prepared")
            finally:
                restore()

            assert harness.install_row(install_id)["state"] == "preparing"
            pending = [item for item in
                       harness.db.host_effects(harness.scope)["items"]
                       if item["kind"] == "host_prepare"]
            assert len(pending) == 1, pending
            prepare = pending[0]
            prepare_id = prepare["effect_id"]
            assert prepare["status"] == "claimed", prepare
            prepared = harness.journal.last(
                "effect_prepared", str(prepare_id))
            assert prepared is not None, prepare_id
            assert prepared["claim"] == {
                "attempt": prepare["attempt_no"],
                "fence": prepare["fence"],
                "owner": prepare["claim_owner"]}, prepared["claim"]
            assert not harness.journal.has(
                "dispatch_started", str(prepare_id))
            assert harness.journal.records[-1]["event_type"] == \
                "effect_prepared"
            assert spawn_ops(harness, install_id).get("prepare", 0) == 0
            remaining = harness.db.remaining_lease_ms(prepare["lease_until"])
            assert remaining > 0, remaining
            crash = {
                "install_state": harness.install_row(install_id)["state"],
                "prepare_status": prepare["status"],
                "journal_last": harness.journal.records[-1]["event_type"],
                "spawn_ops": spawn_ops(harness, install_id),
                "remaining_lease_ms": remaining,
            }

            harness.run(None, max_rounds=4)
            assert harness.install_row(install_id)["state"] == "installed"
            assert spawn_ops(harness, install_id).get("prepare") == 1

            before = [item for item in
                      harness.db.host_effects(harness.scope)["items"]
                      if item["kind"] == "host_prepare"]
            harness.prepare([install_id])
            after = [item for item in
                     harness.db.host_effects(harness.scope)["items"]
                     if item["kind"] == "host_prepare"]
            assert len(after) == len(before), (before, after)
            assert before == [], before
            assert harness.install_row(install_id)["state"] == "installed"
            assert spawn_ops(harness, install_id).get("prepare") == 1

            harness.activate(install_id, "read")
            run_id, model_id = start_run(
                harness, install_id, ["read"], "r07")
            harness.run(
                [batch_reply([("call_read", "read", {"path": "tail"})]),
                 final_reply("r07-final")], max_rounds=30)
            run = harness.run_row(run_id)
            assert run["status"] == "completed", run
            read_id = tool_effect_id(model_id, 0)

            teardown_two_install(harness, [install_id])

            final_ops = spawn_ops(harness, install_id)
            assert final_ops == {
                "prepare": 1, "invoke": 1, "release": 1}, final_ops
            releases = [record for record in harness.journal.records
                        if record["event_type"] == "dispatch_finished"
                        and record["payload"].get("kind") == "host_release"]
            assert len(releases) == 1, releases
            release_id = releases[0]["effect_id"]

            assert_single_receipt(harness, prepare_id, journal_finish=True)
            assert_single_receipt(harness, read_id, journal_finish=True)
            assert_single_receipt(harness, release_id, journal_finish=True)
            journal_counts = {
                str(effect): {
                    name: sum(1 for record in harness.journal.records
                              if record["event_type"] == name
                              and record["effect_id"] == str(effect))
                    for name in ("effect_prepared", "dispatch_started",
                                 "dispatch_finished",
                                 "settlement_committed")}
                for effect in (prepare_id, read_id, release_id)}
            assert_w7_invariants(harness)
            evidence = {
                "crash": crash,
                "install_state": harness.install_row(install_id)["state"],
                "scope_closed": harness.scope_row()["closed_at"] is not None,
                "pending_prepare_effects_after_idempotent_prepare": len(after),
                "run_status": run["status"],
                "journal_counts": journal_counts,
                "spawn_ops": final_ops,
            }
        assert len(spawn.calls) == 3, spawn.calls
        assert spawn.ops == {
            "prepare": 1, "invoke": 1, "release": 1}, spawn.ops
        evidence["spawn_calls"] = len(spawn.calls)
    finally:
        harness.close()
    return evidence


def r08_release_resume(fixture, base):
    """K0 host_release: crash after effect_prepared, restart disposes once."""
    portable = workspace(base / "r08" / "portable", "portable")
    spec = read_spec(base / "r08" / "read", portable.root,
                     realm=f"w7-r08-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r08" / "harness",
                           realm=spec.realm)
    try:
        with CountingSpawn(expected=3) as spawn:
            install_id = harness.admit(spec)
            harness.prepare([install_id])
            harness.activate(install_id, "read")
            run_id, _model_id = start_run(
                harness, install_id, ["read"], "r08")
            harness.run(
                [batch_reply([("call_read", "read", {"path": "tail"})]),
                 final_reply("r08-final")], max_rounds=30)
            run = harness.run_row(run_id)
            assert run["status"] == "completed", run

            harness.off(install_id)
            harness.dispose(install_id)
            assert harness.install_row(install_id)["state"] == \
                "dispose_pending"
            pending = [item for item in
                       harness.db.host_effects(harness.scope)["items"]
                       if item["kind"] == "host_release"]
            assert len(pending) == 1, pending
            release = pending[0]
            release_id = release["effect_id"]
            assert release["status"] == "ready", release

            restore = inject_after(harness, "effect_prepared",
                                   kind="host_release")
            try:
                harness.run(None, max_rounds=2)
            except HostCrash:
                pass
            else:
                raise AssertionError(
                    "r08 did not crash after host_release effect_prepared")
            finally:
                restore()

            assert harness.install_row(install_id)["state"] == \
                "dispose_pending"
            release = harness.db.host_effect(release_id)["effect"]
            assert release["status"] == "claimed", release
            assert harness.journal.last(
                "effect_prepared", str(release_id)) is not None
            last = harness.journal.records[-1]
            assert (last["event_type"], last["effect_id"]) == (
                "effect_prepared", str(release_id)), last
            assert not harness.journal.has(
                "dispatch_started", str(release_id))
            assert spawn_ops(harness, install_id).get("release", 0) == 0
            crash = {
                "install_state": harness.install_row(install_id)["state"],
                "release_status": release["status"],
                "journal_last": last["event_type"],
                "spawn_ops": spawn_ops(harness, install_id),
            }

            harness.run(None, max_rounds=4)
            assert harness.install_row(install_id)["state"] == "disposed"
            assert spawn_ops(harness, install_id).get("release") == 1
            scope = harness.close_scope()
            assert scope["closed_at"] is not None, scope

            final_ops = spawn_ops(harness, install_id)
            assert final_ops == {
                "prepare": 1, "invoke": 1, "release": 1}, final_ops
            assert_single_receipt(harness, release_id, journal_finish=True)
            journal_counts = {
                name: sum(1 for record in harness.journal.records
                          if record["event_type"] == name
                          and record["effect_id"] == str(release_id))
                for name in ("effect_prepared", "dispatch_started",
                             "dispatch_finished", "settlement_committed")}
            assert_w7_invariants(harness)
            evidence = {
                "crash": crash,
                "install_state": harness.install_row(install_id)["state"],
                "scope_closed": harness.scope_row()["closed_at"] is not None,
                "journal_counts": journal_counts,
                "spawn_ops": final_ops,
            }
        assert len(spawn.calls) == 3, spawn.calls
        assert spawn.ops == {
            "prepare": 1, "invoke": 1, "release": 1}, spawn.ops
        evidence["spawn_calls"] = len(spawn.calls)
    finally:
        harness.close()
    return evidence


def r05_tool_finished_fresh_reconcile(fixture, base):
    """K3 tool: crash after dispatch_finished, a fresh process settles once."""
    portable = workspace(base / "r05" / "portable", "portable")
    spec = read_spec(base / "r05" / "read", portable.root,
                     realm=f"w7-r05-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r05" / "harness",
                           realm=spec.realm)
    try:
        with CountingSpawn(expected=2) as spawn:
            install_id = harness.admit(spec)
            harness.prepare([install_id])
            harness.activate(install_id, "read")
            run_id, model_id = start_run(
                harness, install_id, ["read"], "r05")
            target = tool_effect_id(model_id, 0)
            restore = inject_after(harness, "dispatch_finished",
                                   effect_id=target, kind="tool_call")
            try:
                harness.run(
                    [batch_reply([("call_read", "read", {"path": "tail"})])],
                    max_rounds=20)
            except HostCrash:
                pass
            else:
                raise AssertionError(
                    "r05 did not crash after dispatch_finished")
            finally:
                restore()

            effect = harness.effect_row(target)
            assert effect["status"] == "claimed", effect
            finishes = [record for record in harness.journal.records
                        if record["event_type"] == "dispatch_finished"
                        and str(record["effect_id"]) == str(target)]
            assert len(finishes) == 1, finishes
            assert settlement_count(harness, target) == 0
            ops = spawn_ops(harness, install_id)
            assert ops.get("invoke") == 1, ops
            assert ops == {"prepare": 1, "invoke": 1}, ops
            crash = {
                "status": effect["status"],
                "journal_counts": {
                    "dispatch_finished": len(finishes),
                    "settlement_committed": 0,
                },
                "spawn_ops": ops,
            }
            before_settlements = settlement_count(harness, target)

            reconciled, settlements = run_recover_process(
                harness, harness.scope)
            assert reconciled >= 1, reconciled
            assert settlements == 1, settlements

            reopen_harness(harness)
            harness.run([final_reply("r05-final")], max_rounds=20)

            effect = harness.effect_row(target)
            assert effect["status"] == "succeeded", effect
            delta = settlement_count(harness, target) - before_settlements
            assert delta == 1, delta
            final_ops = spawn_ops(harness, install_id)
            assert final_ops == {"prepare": 1, "invoke": 1}, final_ops
            run = harness.run_row(run_id)
            assert run["status"] == "completed", run
            assert_single_receipt(harness, target, journal_finish=True)
            assert_w7_invariants(harness)
            evidence = {
                "crash": crash,
                "reconciled": reconciled,
                "settlements": settlements,
                "settlement_delta": delta,
                "effect_status": effect["status"],
                "run_status": run["status"],
                "spawn_ops": final_ops,
            }
        assert len(spawn.calls) == 2, spawn.calls
        assert spawn.ops == {"prepare": 1, "invoke": 1}, spawn.ops
        evidence["spawn_calls"] = len(spawn.calls)
    finally:
        harness.close()
    return evidence


def r06_settled_restart_noop(fixture, base):
    """K4: a restart after every settlement changes nothing at all."""
    harness, read_id, node_id, _read, _node = two_install_harness(
        fixture, base / "r06", f"w7-r06-{uuid.uuid4().hex[:8]}")
    try:
        run_id, _model_id = start_run(
            harness, read_id, ["read", "list", "search"], "r06")
        harness.run([
            batch_reply([
                ("call_read", "read", {"path": "tail"}),
                ("call_list", "list", {"path": "."}),
                ("call_search", "search", {"query": "x"}),
            ]),
            final_reply("r06-final"),
        ], max_rounds=30)
        before_run = harness.run_row(run_id)
        assert before_run["status"] == "completed", before_run

        before_page = harness.db.host_run_effects(run_id, None, None, 64)
        assert not before_page.get("error"), before_page
        assert not before_page.get("has_more"), before_page
        before_effects = {str(item["effect_id"]): item
                          for item in before_page["items"]}
        before_tools = {effect_id: item
                        for effect_id, item in before_effects.items()
                        if item["kind"] == "tool_call"}
        assert len(before_tools) == 3, before_tools
        snapshots = {effect_id: capture_effect(harness, effect_id)
                     for effect_id in before_tools}
        before_ops = {install_id: spawn_ops(harness, install_id)
                      for install_id in (read_id, node_id)}
        assert before_ops[read_id] == {"prepare": 1, "invoke": 1}, before_ops
        assert before_ops[node_id] == {"prepare": 1, "invoke": 2}, before_ops
        before_journal = len(harness.journal.records)
        before_settlements = settlement_count(harness)

        close_connections(harness)
        reopen_harness(harness)
        stats = harness.run(None, max_rounds=4)

        after_page = harness.db.host_run_effects(run_id, None, None, 64)
        assert not after_page.get("error"), after_page
        assert not after_page.get("has_more"), after_page
        after_effects = {str(item["effect_id"]): item
                         for item in after_page["items"]}
        assert set(after_effects) == set(before_effects), (
            sorted(after_effects), sorted(before_effects))
        assert after_effects == before_effects
        for effect_id, snapshot in snapshots.items():
            assert capture_effect(harness, effect_id) == snapshot, effect_id
        after_ops = {install_id: spawn_ops(harness, install_id)
                     for install_id in (read_id, node_id)}
        assert after_ops == before_ops, after_ops
        assert len(harness.journal.records) == before_journal, (
            before_journal, len(harness.journal.records))
        assert settlement_count(harness) == before_settlements
        assert stats.reconciled == 0, stats
        assert stats.progress == 0, stats
        assert stats.idle is True, stats
        assert harness.run_row(run_id) == before_run
        assert_w7_invariants(harness)
        evidence = {
            "effects": len(before_effects),
            "tool_effects": len(before_tools),
            "journal_records": before_journal,
            "reconciled": stats.reconciled,
            "progress": stats.progress,
            "spawn_ops": after_ops,
            "snapshots_unchanged": True,
        }
    finally:
        harness.close()
    return evidence


def r15_multiple_pending_reconcile(fixture, base):
    """K3 x3: three pending tool settlements, one fresh-process reconcile."""
    harness, read_id, node_id, _read, _node = two_install_harness(
        fixture, base / "r15", f"w7-r15-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "r15")
        targets = [tool_effect_id(model_id, ordinal) for ordinal in range(3)]
        original = harness.db.settle
        calls = []

        def patched(effect_id, class_name, claim, kind, result):
            if kind == "tool_call":
                calls.append(effect_id)
                return {"error": {"code": "w7_injected_settle_error"}}
            return original(effect_id, class_name, claim, kind, result)

        harness.db.settle = patched
        try:
            stats = harness.run(
                [batch_reply([
                    ("call_read", "read", {"path": "tail"}),
                    ("call_list", "list", {"path": "."}),
                    ("call_search", "search", {"query": "x"}),
                ])], max_rounds=30)
            assert stats.idle is True, stats
            for target in targets:
                effect = harness.effect_row(target)
                assert effect["status"] == "claimed", effect
                assert harness.journal.has("dispatch_finished", str(target))
                assert settlement_count(harness, target) == 0, target
            assert spawn_ops(harness, read_id) == {
                "prepare": 1, "invoke": 1}, spawn_ops(harness, read_id)
            assert spawn_ops(harness, node_id) == {
                "prepare": 1, "invoke": 2}, spawn_ops(harness, node_id)
            run = harness.run_row(run_id)
            assert run["status"] == "running", run
            before_ops = {install_id: spawn_ops(harness, install_id)
                          for install_id in (read_id, node_id)}
            logs = {install_id: install_spawn_log(harness, install_id)
                    for install_id in (read_id, node_id)}
            before_logs = {install_id: path.read_bytes()
                           for install_id, path in logs.items()}
            settled_calls = len(calls)
        finally:
            harness.db.settle = original

        reconciled, settlements = run_recover_process(harness, harness.scope)
        assert reconciled == 3, reconciled
        assert settlements == 3, settlements
        for install_id, path in logs.items():
            assert path.read_bytes() == before_logs[install_id], install_id

        reopen_harness(harness)
        for target in targets:
            effect = harness.effect_row(target)
            assert effect["status"] in (
                "succeeded", "failed", "unknown", "cancelled"), effect
            assert settlement_count(harness, target) == 1, target
        harness.run([final_reply("r15-final")], max_rounds=30)
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'",
            (run_id,)) == 2
        continuation = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,))
        assert continuation == 1, continuation
        final_ops = {install_id: spawn_ops(harness, install_id)
                     for install_id in (read_id, node_id)}
        assert final_ops == before_ops, final_ops
        for target in targets:
            assert_single_receipt(harness, target, journal_finish=True)
        assert_w7_invariants(harness)
        evidence = {
            "pending": len(targets),
            "injected_settle_calls": settled_calls,
            "reconciled": reconciled,
            "settlements": settlements,
            "effect_statuses": [harness.effect_row(target)["status"]
                                for target in targets],
            "continuation": continuation,
            "spawn_ops": final_ops,
        }
    finally:
        harness.close()
    return evidence


def r16_settlement_backfill(fixture, base):
    """K3.5: DB settled, journal settlement missing, backfill exactly once."""
    portable = workspace(base / "r16" / "portable", "portable")
    spec = read_spec(base / "r16" / "read", portable.root,
                     realm=f"w7-r16-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r16" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        run_id, model_id = start_run(harness, install_id, ["read"], "r16")
        target = tool_effect_id(model_id, 0)
        hits = []
        restore = inject_before(harness, "settlement_committed",
                                effect_id=target, kind="tool_call", hits=hits)
        try:
            harness.run(
                [batch_reply([("call_read", "read", {"path": "tail"})]),
                 final_reply("r16-final")], max_rounds=30)
        except HostCrash:
            pass
        else:
            raise AssertionError(
                "r16 did not crash before settlement_committed")
        finally:
            restore()
        assert len(hits) == 1, hits

        effect = harness.effect_row(target)
        assert effect["status"] == "succeeded", effect
        assert effect["settled_at"] is not None, effect
        finishes = [record for record in harness.journal.records
                    if record["event_type"] == "dispatch_finished"
                    and str(record["effect_id"]) == str(target)]
        assert len(finishes) == 1, finishes
        assert settlement_count(harness, target) == 0
        ops = spawn_ops(harness, install_id)
        assert ops == {"prepare": 1, "invoke": 1}, ops
        crash = {
            "status": effect["status"],
            "settled_at_set": effect["settled_at"] is not None,
            "journal_counts": {
                "dispatch_finished": len(finishes),
                "settlement_committed": 0,
            },
            "spawn_ops": ops,
        }
        snapshot = capture_effect(harness, target)

        reconciled, settlements = run_recover_process(harness, harness.scope)
        assert reconciled == 0, reconciled
        assert settlements == 1, settlements
        reopen_harness(harness)

        backfilled = [record for record in harness.journal.records
                      if record["event_type"] == "settlement_committed"
                      and str(record["effect_id"]) == str(target)]
        assert len(backfilled) == 1, backfilled
        payload = backfilled[0]["payload"]
        assert payload.get("reason") == "database_terminal", payload
        assert payload.get("conflict") is False, payload
        assert payload.get("outcome") == finishes[0]["payload"].get("outcome"), (
            payload, finishes[0]["payload"])
        assert capture_effect(harness, target) == snapshot, snapshot
        assert spawn_ops(harness, install_id) == ops

        harness.run([final_reply("r16-final")], max_rounds=30)
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'",
            (run_id,)) == 2
        continuation = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,))
        assert continuation == 1, continuation

        before_settlements = settlement_count(harness)
        stats = harness.run(None, max_rounds=2)
        assert stats.reconciled == 0, stats
        assert settlement_count(harness) == before_settlements
        assert harness.worker._reconcile(harness.scope) == 0
        assert_single_receipt(harness, target, journal_finish=True)
        assert_w7_invariants(harness)
        evidence = {
            "crash": crash,
            "reconciled": reconciled,
            "settlements": settlements,
            "settlement_payload": {
                "reason": payload.get("reason"),
                "conflict": payload.get("conflict"),
                "reconciled": payload.get("reconciled"),
            },
            "effect_row_unchanged": True,
            "run_status": run["status"],
            "continuation": continuation,
            "second_reconcile": stats.reconciled,
        }
    finally:
        harness.close()
    return evidence


def r03_kill_parent_sigkill(fixture, base):
    """K2 tool: real spawn then SIGKILL of the host child; restart unknown."""
    child_lease_ms = 6500
    portable = workspace(base / "r03" / "portable", "portable")
    spec = stub_spec(base / "r03" / "stub", portable.root, "kill_parent",
                     timeout_ms=1000,
                     realm=f"w7-r03-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "r03" / "harness",
                           realm=spec.realm)
    child_pid = None
    plugin_pid = None
    reaped = False
    wait_status = None
    cleanup_errors = []
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        ops = spawn_ops(harness, install_id)
        assert ops == {"prepare": 1}, ops
        run_id, model_id = start_run(harness, install_id, ["read"], "r03")
        target = tool_effect_id(model_id, 0)
        batch = batch_reply(
            [("call_read", "read", {"path": "tail",
                                    "scenario": "kill_parent"})])

        def spawn_log_rows():
            path = Path(spec.spawn_log)
            if not path.exists():
                return []
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                fields = line.split()
                assert len(fields) == 2 and fields[0].isdigit(), (
                    f"unparseable spawn log line {line!r}: {path}")
                rows.append((int(fields[0]), fields[1]))
            return rows

        def ps_state(pid):
            completed = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)],
                capture_output=True, text=True)
            return completed.stdout.strip()

        try:
            close_connections(harness)
            assert_fork_safe(harness)
            child_pid = os.fork()
            if child_pid == 0:
                try:
                    child_db = HostDB(fixture.role_dsn("admin"),
                                      fixture.role_dsn("service"))
                    child_journal = HostJournal.open(
                        harness.workdir / "plugin-journal.jsonl")
                    child_dispatcher = PluginDispatcher(
                        child_db, harness.registry)
                    child_adapter, _transport = model_adapter([batch])
                    child_worker = HostWorker(
                        child_db, child_journal,
                        tool_handler=child_dispatcher.tool_handler,
                        resource_handler=child_dispatcher.resource_handler,
                        default_lease_ms=child_lease_ms,
                        adapter=child_adapter)
                    child_worker.run_until_idle(harness.scope, max_rounds=4)
                except BaseException:
                    os._exit(1)
                os._exit(0)

            deadline = time.monotonic() + 30.0
            while True:
                pid, status = os.waitpid(child_pid, os.WNOHANG)
                if pid == child_pid:
                    reaped = True
                    wait_status = status
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
            timed_out = not reaped
            if timed_out:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    cleanup_errors.append(
                        f"kill({child_pid}) errno={exc.errno}: {exc}")
                _, wait_status = os.waitpid(child_pid, 0)
                reaped = True

            rows = spawn_log_rows()
            invoke_pids = [pid for pid, operation in rows
                           if operation == "invoke"]
            if len(invoke_pids) == 1:
                plugin_pid = invoke_pids[0]
            assert not timed_out, "host child did not die within 30s"
            assert os.WIFSIGNALED(wait_status), (
                f"host child was not signalled: status={wait_status}, "
                f"WIFEXITED={os.WIFEXITED(wait_status)}, rows={rows}")
            assert os.WTERMSIG(wait_status) == signal.SIGKILL, (
                f"host child term signal {os.WTERMSIG(wait_status)}: "
                f"status={wait_status}, rows={rows}")
            assert len(invoke_pids) == 1, (rows, wait_status)
            invoke_at_crash = sum(
                1 for _, operation in rows if operation == "invoke")
            plugin_state_at_crash = ps_state(plugin_pid)
            try:
                os.killpg(plugin_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                cleanup_errors.append(
                    f"killpg({plugin_pid}) errno={exc.errno}: {exc}")
            assert_no_live(plugin_pid)
            plugin_state_after_cleanup = ps_state(plugin_pid)

            reopen_harness(harness)
            effect = harness.db.host_effect(target)["effect"]
            assert effect["status"] == "claimed", effect
            prepared = harness.journal.last("effect_prepared", str(target))
            assert prepared is not None, target
            assert prepared["claim"] == {
                "attempt": effect["attempt_no"],
                "fence": effect["fence"],
                "owner": effect["claim_owner"]}, prepared["claim"]
            assert not harness.journal.has("dispatch_finished", str(target))
            last = harness.journal.records[-1]
            assert (last["event_type"], last["effect_id"]) == (
                "dispatch_started", str(target)), last

            with harness.owner.cursor() as cur:
                cur.execute(
                    "SELECT extract(epoch FROM lease_until) "
                    "FROM v24.effects WHERE effect_id=%s", (str(target),))
                lease_epoch = float(cur.fetchone()[0])
            harness.owner.commit()
            lease_remaining_at_spawn = int(
                (lease_epoch - Path(spec.spawn_log).stat().st_mtime) * 1000)
            assert 0 < lease_remaining_at_spawn <= child_lease_ms, (
                lease_remaining_at_spawn, child_lease_ms)

            deadline = time.monotonic() + (child_lease_ms + 2000) / 1000
            while True:
                effect = harness.db.host_effect(target)["effect"]
                lease_remaining_at_recovery = harness.db.remaining_lease_ms(
                    effect["lease_until"])
                if lease_remaining_at_recovery <= 0:
                    break
                assert time.monotonic() < deadline, lease_remaining_at_recovery
                time.sleep(0.05)

            stats = harness.run(None, max_rounds=4)
            effect = harness.effect_row(target)
            assert effect["status"] == "unknown", effect
            run = harness.run_row(run_id)
            assert run["status"] == "blocked_unknown", run
            with harness.owner.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM v24.events "
                    "WHERE entity_type='effect' AND entity_id=%s "
                    "AND event_kind='effect_recovered_unknown' "
                    "ORDER BY event_id", (str(target),))
                events = [row[0] for row in cur.fetchall()]
            harness.owner.commit()
            assert len(events) == 1, (target, events)
            assert events[0].get("action") == "settle_unknown", events
            assert events[0].get("reason") == "lease_expired", events
            final_ops = spawn_ops(harness, install_id)
            assert final_ops == {"prepare": 1, "invoke": 1}, final_ops
            assert invoke_at_crash == final_ops["invoke"] == 1, (
                invoke_at_crash, final_ops)
            assert_no_live(plugin_pid)

            assert_single_receipt(harness, target, journal_finish=False,
                                  db_recovery=True)
            second_reconcile = harness.worker._reconcile(harness.scope)
            assert second_reconcile == 0, second_reconcile
            assert_w7_invariants(harness, recovered_unknown={target})
            evidence = {
                "wait_status": {
                    "WIFSIGNALED": os.WIFSIGNALED(wait_status),
                    "WTERMSIG": os.WTERMSIG(wait_status),
                    "signal_name": signal.Signals(
                        os.WTERMSIG(wait_status)).name,
                },
                "child_pid": child_pid,
                "plugin_pid": plugin_pid,
                "plugin_state_at_crash": plugin_state_at_crash,
                "plugin_state_after_cleanup": plugin_state_after_cleanup,
                "plugin_cleanup_errors": cleanup_errors,
                "crash_journal_last": {
                    "event_type": last["event_type"],
                    "effect_id": last["effect_id"],
                },
                "invoke_at_crash": invoke_at_crash,
                "invoke_after_recovery": final_ops.get("invoke"),
                "lease_ms": child_lease_ms,
                "lease_remaining_at_spawn": lease_remaining_at_spawn,
                "lease_remaining_at_recovery": lease_remaining_at_recovery,
                "effect_status": effect["status"],
                "run_status": run["status"],
                "recovered": stats.recovered,
                "db_recovery_event": {
                    "count": len(events),
                    "action": events[0].get("action"),
                    "reason": events[0].get("reason"),
                },
                "spawn_ops": final_ops,
                "second_reconcile": second_reconcile,
            }
        finally:
            if child_pid is not None and not reaped:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    cleanup_errors.append(
                        f"finally kill({child_pid}) errno={exc.errno}: {exc}")
                try:
                    os.waitpid(child_pid, 0)
                except ChildProcessError:
                    pass
                reaped = True
            if plugin_pid is not None:
                try:
                    os.killpg(plugin_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    cleanup_errors.append(
                        f"finally killpg({plugin_pid}) errno={exc.errno}: {exc}")
    finally:
        harness.close()
    return evidence


def r04_model_finished_replay(fixture, base):
    """K3(model)+K5: crash after the model dispatch_finished, replay, run tools."""
    harness, read_id, node_id, _read, _node = two_install_harness(
        fixture, base / "r04", f"w7-r04-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "r04")
        calls = [
            ("call_read", "read", {"path": "tail"}),
            ("call_list", "list", {"path": "."}),
            ("call_search", "search", {"query": "x"}),
        ]
        harness.worker.crash_after = "finished"
        try:
            harness.run([batch_reply(calls)], max_rounds=30)
        except HostCrash:
            pass
        else:
            raise AssertionError(
                "r04 did not crash after the model dispatch_finished")
        first_transport = harness._transport
        first_calls = len(first_transport.calls)
        harness.worker.crash_after = None

        assert first_calls == 1, first_calls
        effect = harness.effect_row(model_id)
        assert effect["status"] == "claimed", effect
        finishes = [record for record in harness.journal.records
                    if record["event_type"] == "dispatch_finished"
                    and str(record["effect_id"]) == str(model_id)]
        assert len(finishes) == 1, finishes
        assert finishes[0]["payload"].get("kind") == "model_call", finishes[0]
        assert settlement_count(harness, model_id) == 0
        assert tool_effects(harness, model_id) == []
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='tool_call'",
            (run_id,)) == 0
        crash = {
            "transport_calls": first_calls,
            "model_status": effect["status"],
            "journal_counts": {
                "dispatch_finished": len(finishes),
                "settlement_committed": 0,
            },
            "tool_effects": 0,
        }

        stats = harness.run([final_reply("r04-final")], max_rounds=30)
        assert stats.reconciled >= 1, stats
        assert len(first_transport.calls) == 1, first_transport.calls
        resume_calls = len(harness._transport.calls)
        assert resume_calls == 1, resume_calls
        assert first_calls + resume_calls == 2, (first_calls, resume_calls)

        effect = harness.effect_row(model_id)
        assert effect["status"] == "succeeded", effect
        model_effects = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'", (run_id,))
        assert model_effects == 2, model_effects
        continuation = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,))
        assert continuation == 1, continuation

        effects = {ordinal: harness.effect_row(tool_effect_id(model_id, ordinal))
                   for ordinal in range(3)}
        for ordinal, item in effects.items():
            assert item["status"] == "succeeded", (ordinal, item)
            assert item["outcome"]["class"] == "success", (ordinal, item)
        read_ops = spawn_ops(harness, read_id)
        node_ops = spawn_ops(harness, node_id)
        assert read_ops == {"prepare": 1, "invoke": 1}, read_ops
        assert node_ops == {"prepare": 1, "invoke": 2}, node_ops
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        for ordinal in range(3):
            assert_single_receipt(
                harness, tool_effect_id(model_id, ordinal), journal_finish=True)
        assert_w7_invariants(harness)
        evidence = {
            "crash": crash,
            "reconciled": stats.reconciled,
            "transport_calls": first_calls + resume_calls,
            "first_transport_calls": first_calls,
            "resume_transport_calls": resume_calls,
            "model_effects": model_effects,
            "continuation": continuation,
            "tool_statuses": {str(ordinal): item["status"]
                              for ordinal, item in effects.items()},
            "run_status": run["status"],
            "spawn_ops": {"read": read_ops, "node": node_ops},
        }
    finally:
        harness.close()
    return evidence


def r09_mixed_batch_timeout(fixture, base):
    """Mixed batch: two successes then one timeout; read executes last."""
    realm = f"w7-r09-{uuid.uuid4().hex[:8]}"
    portable = workspace(base / "r09" / "portable", "portable")
    listing = workspace(base / "r09" / "list", "list")
    stub = stub_spec(base / "r09" / "stub", portable.root, "timeout",
                     timeout_ms=300, realm=realm)
    node = node_spec(base / "r09" / "node", listing.root, realm=realm)
    harness = open_harness(fixture, [stub, node], base / "r09" / "harness",
                           realm=realm)
    try:
        stub_id = harness.admit(stub)
        node_id = harness.admit(node)
        harness.prepare([stub_id, node_id])
        harness.activate(stub_id, "read")
        harness.activate(node_id, "list")

        run_id, model_id = start_run(
            harness, stub_id, ["read", "list", "search"], "r09")
        order = tool_order(model_id, 3)
        read_ord = order[-1]
        calls = [None, None, None]
        calls[read_ord] = ("call_read", "read",
                           {"path": "a.txt", "scenario": "timeout"})
        others = [ordinal for ordinal in range(3) if ordinal != read_ord]
        calls[others[0]] = ("call_list", "list", {"path": "."})
        calls[others[1]] = ("call_search", "search", {"query": "x"})

        stats = harness.run([batch_reply(calls)], max_rounds=30)
        assert stats.idle is True, stats

        read = harness.effect_row(tool_effect_id(model_id, read_ord))
        assert read["status"] == "unknown", read
        assert read["outcome"]["class"] == "unknown", read["outcome"]
        assert read["outcome"]["body"]["result"]["output"]["error"]["code"] == \
            "timeout", read["outcome"]
        effects = {ordinal: harness.effect_row(tool_effect_id(model_id, ordinal))
                   for ordinal in range(3)}
        for ordinal in others:
            assert effects[ordinal]["status"] == "succeeded", (
                ordinal, effects[ordinal])
            assert effects[ordinal]["outcome"]["class"] == "success", (
                ordinal, effects[ordinal])
        run = harness.run_row(run_id)
        assert run["status"] == "blocked_unknown", run
        assert len(harness._transport.calls) == 1, harness._transport.calls
        model_effects = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'", (run_id,))
        assert model_effects == 1, model_effects
        continuation = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,))
        assert continuation == 0, continuation

        finishes = [record for record in harness.journal.records
                    if record["event_type"] == "dispatch_finished"
                    and record["payload"].get("kind") == "tool_call"]
        by_id = {str(tool_effect_id(model_id, ordinal)): ordinal
                 for ordinal in range(3)}
        journal_order = []
        for record in finishes:
            ordinal = by_id.get(str(record["effect_id"]))
            assert ordinal is not None, (record["effect_id"], sorted(by_id))
            journal_order.append(ordinal)
        assert len(journal_order) == 3, journal_order
        assert journal_order == order, (journal_order, order)

        stub_ops = spawn_ops(harness, stub_id)
        node_ops = spawn_ops(harness, node_id)
        assert stub_ops == {"prepare": 1, "invoke": 1}, stub_ops
        assert node_ops == {"prepare": 1, "invoke": 2}, node_ops
        for ordinal in range(3):
            assert_single_receipt(
                harness, tool_effect_id(model_id, ordinal), journal_finish=True)

        before_records = len(harness.journal.records)
        before_settlements = settlement_count(harness)
        restart = harness.run(None, max_rounds=2)
        assert restart.reconciled == 0, restart
        assert len(harness.journal.records) == before_records
        assert settlement_count(harness) == before_settlements
        assert spawn_ops(harness, stub_id) == stub_ops
        assert spawn_ops(harness, node_id) == node_ops
        assert harness.run_row(run_id)["status"] == "blocked_unknown"
        assert_w7_invariants(harness)
        evidence = {
            "order": order,
            "read_ordinal": read_ord,
            "journal_order": journal_order,
            "statuses": {str(ordinal): effects[ordinal]["status"]
                         for ordinal in range(3)},
            "read_error_code": read["outcome"]["body"]["result"]["output"][
                "error"]["code"],
            "transport_calls": 1,
            "model_effects": model_effects,
            "continuation": continuation,
            "run_status": run["status"],
            "spawn_ops": {"stub": stub_ops, "node": node_ops},
            "restart": {
                "reconciled": restart.reconciled,
                "journal_records": len(harness.journal.records),
                "settlements": settlement_count(harness),
            },
        }
    finally:
        harness.close()
    return evidence


def r10_first_tool_finished_crash(fixture, base):
    """Mixed batch: crash after the first tool dispatch_finished, replay it."""
    harness, read_id, node_id, _read, _node = two_install_harness(
        fixture, base / "r10", f"w7-r10-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "r10")
        target_ordinal = tool_order(model_id, 3)[0]
        target = tool_effect_id(model_id, target_ordinal)
        calls = [
            ("call_read", "read", {"path": "tail"}),
            ("call_list", "list", {"path": "."}),
            ("call_search", "search", {"query": "x"}),
        ]
        restore = inject_after(harness, "dispatch_finished",
                               effect_id=target, kind="tool_call")
        try:
            harness.run([batch_reply(calls)], max_rounds=30)
        except HostCrash:
            pass
        else:
            raise AssertionError(
                "r10 did not crash after the first tool dispatch_finished")
        finally:
            restore()
        first_calls = len(harness._transport.calls)
        assert first_calls == 1, first_calls

        finished = tool_effects(harness, model_id)
        assert len(finished) == 1, finished
        assert str(finished[0]["effect_id"]) == str(target), (finished, target)
        page = harness.db.host_effects(harness.scope)
        assert not page.get("error"), page
        tools = [item for item in page["items"]
                 if item.get("kind") == "tool_call"]
        assert len(tools) == 3, tools
        statuses = {str(item["effect_id"]): item["status"] for item in tools}
        assert statuses[str(target)] == "claimed", statuses
        ready = {key for key in statuses if key != str(target)}
        assert ready == {str(tool_effect_id(model_id, ordinal))
                         for ordinal in range(3) if ordinal != target_ordinal}
        assert {statuses[key] for key in ready} == {"ready"}, statuses
        assert all(uuid.UUID(key) > target for key in ready), (ready, target)

        target_finishes = [record for record in harness.journal.records
                           if record["event_type"] == "dispatch_finished"
                           and str(record["effect_id"]) == str(target)]
        assert len(target_finishes) == 1, target_finishes
        saved_content = target_finishes[0]["payload"]["tool_message"]["content"]
        crash = {
            "tool_effects": 1,
            "statuses": statuses,
            "transport_calls": first_calls,
        }

        stats = harness.run([final_reply("r10-final")], max_rounds=30)
        assert stats.reconciled >= 1, stats
        resume_calls = len(harness._transport.calls)
        assert resume_calls == 1, resume_calls
        assert first_calls + resume_calls == 2, (first_calls, resume_calls)

        effects = {ordinal: harness.effect_row(tool_effect_id(model_id, ordinal))
                   for ordinal in range(3)}
        for ordinal, item in effects.items():
            assert item["status"] == "succeeded", (ordinal, item)
            assert item["outcome"]["class"] == "success", (ordinal, item)
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        model_effects = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'", (run_id,))
        assert model_effects == 2, model_effects
        continuation = harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,))
        assert continuation == 1, continuation
        read_ops = spawn_ops(harness, read_id)
        node_ops = spawn_ops(harness, node_id)
        assert read_ops == {"prepare": 1, "invoke": 1}, read_ops
        assert node_ops == {"prepare": 1, "invoke": 2}, node_ops

        for ordinal in range(3):
            assert_single_receipt(
                harness, tool_effect_id(model_id, ordinal), journal_finish=True)
        after_finishes = [record for record in harness.journal.records
                          if record["event_type"] == "dispatch_finished"
                          and str(record["effect_id"]) == str(target)]
        assert len(after_finishes) == 1, after_finishes
        current_content = after_finishes[0]["payload"]["tool_message"]["content"]
        assert (current_content.encode("utf-8")
                == saved_content.encode("utf-8")), "target tool_message changed"
        for ordinal in range(3):
            if ordinal == target_ordinal:
                continue
            other = [record for record in harness.journal.records
                     if record["event_type"] == "dispatch_finished"
                     and str(record["effect_id"]) ==
                     str(tool_effect_id(model_id, ordinal))]
            assert len(other) == 1, (ordinal, other)
        assert_w7_invariants(harness)
        evidence = {
            "target_ordinal": target_ordinal,
            "target": str(target),
            "crash": crash,
            "reconciled": stats.reconciled,
            "transport_calls": first_calls + resume_calls,
            "model_effects": model_effects,
            "continuation": continuation,
            "tool_statuses": {str(ordinal): item["status"]
                              for ordinal, item in effects.items()},
            "run_status": run["status"],
            "tool_message_byte_identical": True,
            "spawn_ops": {"read": read_ops, "node": node_ops},
        }
    finally:
        harness.close()
    return evidence


def r11_artifact_tamper(fixture, base):
    """Disk artifact tamper: the four require_artifact shapes, in order."""
    portable = workspace(base / "r11" / "portable", "portable")
    spec = read_spec(base / "r11" / "read", portable.root,
                     realm=f"w7-r11-{uuid.uuid4().hex[:8]}")
    artifact = Path(spec.entry.artifact_path)
    original = artifact.read_bytes()
    original_mode = artifact.stat().st_mode
    harness = open_harness(fixture, [spec], base / "r11" / "harness",
                           realm=spec.realm)
    codes = []
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        baseline = spawn_count(harness, install_id)
        assert baseline == 1, baseline

        def restore_regular():
            if artifact.is_symlink() or artifact.is_file():
                artifact.unlink()
            elif artifact.is_dir():
                artifact.rmdir()
            artifact.write_bytes(original)
            os.chmod(artifact, original_mode & 0o7777)

        def failed_probe(label, code):
            _run_id, model_id = start_run(
                harness, install_id, ["read"], f"r11-{label}")
            target = tool_effect_id(model_id, 0)
            with ZeroSpawn():
                harness.run([
                    batch_reply([(f"call_{label}", "read",
                                  {"path": "tail"})]),
                    final_reply(f"r11-{label}-final"),
                ], max_rounds=20)
            effect = harness.effect_row(target)
            assert effect["outcome"]["class"] == "failure", (label, effect)
            result = effect["outcome"]["body"]["result"]
            actual = result["output"]["error"]["code"]
            assert actual == code, (label, code, result)
            assert_single_receipt(harness, target, journal_finish=True)
            assert spawn_count(harness, install_id) == baseline, label
            codes.append(actual)
            return {"label": label, "code": actual,
                    "status": effect["status"]}

        artifact.unlink()
        probes = [failed_probe("missing", "artifact_missing")]
        restore_regular()

        artifact.unlink()
        os.symlink("/etc/hosts", artifact)
        probes.append(failed_probe("outside", "artifact_outside_cwd"))
        restore_regular()

        artifact.unlink()
        artifact.mkdir()
        probes.append(failed_probe("not_regular", "artifact_not_regular"))
        restore_regular()

        artifact.write_bytes(original + b"\x00")
        probes.append(failed_probe("digest", "artifact_digest_mismatch"))
        restore_regular()
        assert artifact.read_bytes() == original

        _run_id, model_id = start_run(harness, install_id, ["read"],
                                      "r11-success")
        target = tool_effect_id(model_id, 0)
        harness.run([
            batch_reply([("call_success", "read", {"path": "tail"})]),
            final_reply("r11-success-final"),
        ], max_rounds=20)
        effect = harness.effect_row(target)
        assert effect["status"] == "succeeded", effect
        assert effect["outcome"]["class"] == "success", effect
        final_ops = spawn_ops(harness, install_id)
        assert final_ops == {"prepare": 1, "invoke": 1}, final_ops
        assert_single_receipt(harness, target, journal_finish=True)
        assert codes == ["artifact_missing", "artifact_outside_cwd",
                         "artifact_not_regular",
                         "artifact_digest_mismatch"], codes
        assert_w7_invariants(harness)
        evidence = {
            "order": codes,
            "probes": probes,
            "success_status": effect["status"],
            "spawn_ops": final_ops,
        }
    finally:
        harness.close()
    return evidence


def r12_workspace_unavailable(fixture, base):
    """Workspace root moved away: one pre-spawn failure, then success."""
    portable = workspace(base / "r12" / "portable", "portable")
    spec = read_spec(base / "r12" / "read", portable.root,
                     realm=f"w7-r12-{uuid.uuid4().hex[:8]}")
    root = Path(spec.workspace)
    moved = Path(str(root) + ".bak")
    harness = open_harness(fixture, [spec], base / "r12" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        baseline = spawn_count(harness, install_id)
        assert baseline == 1, baseline

        os.rename(root, moved)
        try:
            _run_id, model_id = start_run(
                harness, install_id, ["read"], "r12-unavailable")
            target = tool_effect_id(model_id, 0)
            with ZeroSpawn():
                harness.run([
                    batch_reply([("call_unavailable", "read",
                                  {"path": "tail"})]),
                    final_reply("r12-unavailable-final"),
                ], max_rounds=20)
            effect = harness.effect_row(target)
            assert effect["outcome"]["class"] == "failure", effect
            result = effect["outcome"]["body"]["result"]
            code = result["output"]["error"]["code"]
            assert code == "workspace_unavailable", result
            assert_single_receipt(harness, target, journal_finish=True)
            assert spawn_count(harness, install_id) == baseline
        finally:
            os.rename(moved, root)
        assert root.is_dir()

        _run_id, model_id = start_run(
            harness, install_id, ["read"], "r12-success")
        target = tool_effect_id(model_id, 0)
        harness.run([
            batch_reply([("call_success", "read", {"path": "tail"})]),
            final_reply("r12-success-final"),
        ], max_rounds=20)
        effect = harness.effect_row(target)
        assert effect["status"] == "succeeded", effect
        assert effect["outcome"]["class"] == "success", effect
        final_ops = spawn_ops(harness, install_id)
        assert final_ops == {"prepare": 1, "invoke": 1}, final_ops
        assert_single_receipt(harness, target, journal_finish=True)
        assert_w7_invariants(harness)
        evidence = {
            "failure_code": code,
            "success_status": effect["status"],
            "spawn_ops": final_ops,
        }
    finally:
        if moved.exists() and not root.exists():
            os.rename(moved, root)
        harness.close()
    return evidence


def r13_timeout_group_cleanup(fixture, base):
    """Timeout: plugin and grandchild are gone; restart does not replay."""
    harness = None
    plugin_pid = None
    evidence = {}
    try:
        started = time.monotonic()
        with CountingSpawn(expected=2) as spawn:
            (harness, install_id, run_id, _model_id, effect,
             spec) = run_stub(
                fixture, base / "r13", "grandchild",
                {"path": "a.txt", "scenario": "grandchild"},
                timeout_ms=1000)
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, elapsed
        assert len(spawn.calls) == 2, spawn.calls
        assert spawn.ops == {"prepare": 1, "invoke": 1}, spawn.ops

        child_path = Path(str(spec.spawn_log) + ".child")
        deadline = time.monotonic() + 2.0
        child_pid = None
        while time.monotonic() < deadline:
            try:
                text = child_path.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if text:
                try:
                    child_pid = int(text)
                    break
                except ValueError:
                    pass
            time.sleep(0.02)
        assert child_pid is not None, f"missing grandchild pid {child_path}"

        lines = spec.spawn_log.read_text(encoding="utf-8").splitlines()
        assert lines, spec.spawn_log
        fields = lines[-1].split()
        assert len(fields) == 2 and fields[1] == "invoke", lines[-1]
        plugin_pid = int(fields[0])

        assert_no_live(plugin_pid)
        plugin_state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(plugin_pid)],
            capture_output=True, text=True).stdout.strip()
        assert_no_live(child_pid)
        child_state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child_pid)],
            capture_output=True, text=True).stdout.strip()

        assert effect["outcome"]["class"] == "unknown", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "timeout", result
        assert harness.run_row(run_id)["status"] == "blocked_unknown"
        first_ops = spawn_ops(harness, install_id)
        assert first_ops == {"prepare": 1, "invoke": 1}, first_ops

        before_records = len(harness.journal.records)
        before_settlements = settlement_count(harness)
        restart = harness.run(None, max_rounds=2)
        assert restart.reconciled == 0, restart
        assert len(harness.journal.records) == before_records
        assert settlement_count(harness) == before_settlements
        assert spawn_ops(harness, install_id) == first_ops
        effect_row = harness.effect_row(effect["effect_id"])
        assert effect_row["status"] == "unknown", effect_row
        assert_single_receipt(harness, effect["effect_id"],
                              journal_finish=True)
        assert_w7_invariants(harness)
        evidence = {
            "effect_status": effect_row["status"],
            "error_code": result["output"]["error"]["code"],
            "run_status": "blocked_unknown",
            "elapsed_s": round(elapsed, 3),
            "plugin_pid": plugin_pid,
            "plugin_ps": plugin_state,
            "child_pid": child_pid,
            "child_ps": child_state,
            "spawn_ops": first_ops,
            "restart": {
                "reconciled": restart.reconciled,
                "journal_records": len(harness.journal.records),
                "settlements": settlement_count(harness),
            },
        }
    finally:
        if plugin_pid is not None:
            try:
                os.killpg(plugin_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                print(f"[w7-evidence] r13 cleanup pid={plugin_pid}: {exc}")
        if harness is not None:
            harness.close()
    return evidence


def r14_legacy_union_recovery(fixture, base):
    """v1/v2 union: v1 B0 bytes survive a fresh-process recovery."""
    requests = {case["id"]: case for case in json.loads(
        (B0 / "provider_requests_v1.json").read_text(
            encoding="utf-8"))["cases"]}
    messages = {case["id"]: case for case in json.loads(
        (B0 / "tool_messages_v1.json").read_text(
            encoding="utf-8"))["cases"]}

    realm = f"w7-r14-{uuid.uuid4().hex[:8]}"
    portable = workspace(base / "r14" / "portable", "portable")
    v1 = build_spec("python", realm=realm, tool_key="echo.python",
                    identity="v24.w7.legacy")
    v2 = read_spec(base / "r14" / "v2", portable.root, realm=realm)
    registry = ApprovedAdapterRegistry((v1.entry, v2.entry))
    workdir = base / "r14" / "harness"
    workdir.mkdir(parents=True, exist_ok=True)
    os.chmod(workdir, 0o700)
    harness = PluginHarness(fixture, registry, workdir, realm=realm)

    def request_bytes(case_id):
        return bytes.fromhex(requests[case_id]["expected_hex"])

    def message_bytes(case_id):
        return bytes.fromhex(messages[case_id]["expected_hex"])

    def v1_message(model_id):
        records = [
            record for record in harness.journal.records
            if record["event_type"] == "dispatch_finished"
            and record["payload"].get("kind") == "tool_call"
            and str(record["payload"].get("parent_effect_id"))
            == str(model_id)]
        assert len(records) == 1, (model_id, records)
        return records[0]["payload"]["tool_message"]["content"]

    try:
        with CountingSpawn(expected=3,
                           artifact=v1.entry.artifact_path) as spawn:
            v1_id = harness.admit(v1)
            v2_id = harness.admit(v2)
            harness.prepare([v1_id, v2_id])
            harness.activate(v1_id, "echo.python")
            harness.activate(v2_id, "read")

            # (a) a v2 read succeeds in the same scope; not v1-counted.
            _v2a_run, v2a_mid = start_run(
                harness, v2_id, ["read"], "r14-v2-a")
            v2a_target = tool_effect_id(v2a_mid, 0)
            harness.run([
                batch_reply([("call_r14_v2a", "read", {"path": "tail"})]),
                final_reply("r14-v2-a"),
            ], max_rounds=20)
            assert harness.effect_row(v2a_target)["status"] == "succeeded"

            # (b) v1 success: B0 request1/2 and tool message byte-exact.
            _run_id, v1_mid = start_run(
                harness, v1_id, ["echo.python"], "B0 fixed echo")
            success_target = tool_effect_id(v1_mid, 0)
            harness.run([
                tool_reply("call_b0_success", "echo.python",
                           {"text": "snow 雪", "zero": 0},
                           reasoning="B0 fixed", usage=(17, 9),
                           response_id="resp_b0_success"),
                final_reply("B0 final", reasoning="B0 done", usage=(22, 3),
                            response_id="final_b0_success"),
            ], max_rounds=30)
            assert len(harness._transport.calls) == 2
            for index, case_id in enumerate(
                    ("provider.success.request1",
                     "provider.success.request2")):
                assert (harness._transport.calls[index]["body"]
                        == request_bytes(case_id)), (case_id, index)
            success_content = v1_message(v1_mid)
            assert (success_content.encode("utf-8")
                    == message_bytes("tool_message.success.content"))
            assert harness.effect_row(success_target)["status"] == "succeeded"

            # (c) v1 known error: crash after dispatch_finished, pre settle.
            run2, v1_mid2 = start_run(
                harness, v1_id, ["echo.python"], "B0 fixed echo")
            target = tool_effect_id(v1_mid2, 0)
            restore = inject_after(harness, "dispatch_finished",
                                   effect_id=target, kind="tool_call")
            try:
                harness.run([
                    tool_reply("call_b0_known_error", "echo.python",
                               {"__tool_error__": True},
                               reasoning="B0 fixed", usage=(17, 9),
                               response_id="resp_b0_known_error"),
                ], max_rounds=20)
            except HostCrash:
                pass
            else:
                raise AssertionError(
                    "r14 did not crash after v1 dispatch_finished")
            finally:
                restore()
            assert len(harness._transport.calls) == 1
            assert (harness._transport.calls[0]["body"]
                    == request_bytes("provider.known_error.request1"))
            effect = harness.effect_row(target)
            assert effect["status"] == "claimed", effect
            finishes = [record for record in harness.journal.records
                        if record["event_type"] == "dispatch_finished"
                        and str(record["effect_id"]) == str(target)]
            assert len(finishes) == 1, finishes
            assert settlement_count(harness, target) == 0
            known_content = v1_message(v1_mid2)
            assert (known_content.encode("utf-8")
                    == message_bytes("tool_message.known_error.content"))

            # (d) fresh process settles the journal outcome exactly once.
            reconciled, settlements = run_recover_process(
                harness, harness.scope)
            assert reconciled >= 1, reconciled
            assert settlements == 1, settlements
            reopen_harness(harness)

            # (e) resume with the continuation; B0 request2 unchanged.
            harness.run([
                final_reply("B0 final", reasoning="B0 done", usage=(22, 3),
                            response_id="final_b0_known_error"),
            ], max_rounds=20)
            assert len(harness._transport.calls) == 1
            assert (harness._transport.calls[0]["body"]
                    == request_bytes("provider.known_error.request2"))
            run = harness.run_row(run2)
            assert run["status"] == "completed", run
            continuation = harness.count(
                "v24.effects WHERE run_id=%s AND kind='model_call' "
                "AND request->>'cause'='continuation'", (run2,))
            assert continuation == 1, continuation
            assert (v1_message(v1_mid2).encode("utf-8")
                    == message_bytes("tool_message.known_error.content"))
            assert settlement_count(harness, target) == 1

            # (f) v1 process count and the absent spawn log.
            assert len(spawn.calls) == 3, spawn.calls
            assert spawn.ops == {"prepare": 1, "invoke": 2}, spawn.ops
            assert "--spawn-log" not in v1.entry.argv, v1.entry.argv
            assert install_spawn_log(harness, v1_id) is None
            assert spawn_count(harness, v1_id) == 0

            # (g) v2 still works; every v1 effect stays no_replay.
            _v2b_run, v2b_mid = start_run(
                harness, v2_id, ["read"], "r14-v2-b")
            v2b_target = tool_effect_id(v2b_mid, 0)
            harness.run([
                batch_reply([("call_r14_v2b", "read", {"path": "tail"})]),
                final_reply("r14-v2-b"),
            ], max_rounds=20)
            assert harness.effect_row(v2b_target)["status"] == "succeeded"
            for effect_id in (success_target, target):
                assert harness.effect_row(effect_id)[
                    "replay_policy"] == "no_replay", effect_id
            for effect_id in (success_target, target, v2a_target,
                              v2b_target):
                assert_single_receipt(harness, effect_id,
                                      journal_finish=True)
            assert_w7_invariants(harness)
            evidence = {
                "b0_provider_requests": {
                    "success.request1": True,
                    "success.request2": True,
                    "known_error.request1": True,
                    "known_error.request2": True,
                },
                "b0_tool_messages": {
                    "success": success_content,
                    "known_error": known_content,
                    "byte_identical": True,
                },
                "reconciled": reconciled,
                "settlements": settlements,
                "run_status": run["status"],
                "continuation": continuation,
                "spawn_calls": len(spawn.calls),
                "spawn_ops": dict(spawn.ops),
                "v1_spawn_log": None,
                "v2_statuses": {
                    "a": harness.effect_row(v2a_target)["status"],
                    "b": harness.effect_row(v2b_target)["status"],
                },
                "replay_policy": "no_replay",
            }
    finally:
        harness.close()
    return evidence


def replay_vector_probe():
    document = json.loads((HERE / "vectors" / "results_v2.json").read_text(
        encoding="utf-8"))
    by_id = {case["id"]: case for case in document["cases"]}
    expected = {
        "result.replay_no_rerender": "m4_pending",
        "lifecycle.journal_replay_no_rerender": "m4_pending",
        "lifecycle.tool_message_model_text_stable": "m4_pending",
    }
    for case_id, status in expected.items():
        assert by_id[case_id]["status"] == status, case_id
    return expected


def main() -> int:
    if node_path() is None:
        print("[SKIP] W4 lifecycle; node_missing")
        return 2
    with tempfile.TemporaryDirectory(prefix="w4c-life-") as temp:
        base = Path(temp)
        with server_helper_scope(), setup_db() as fixture:
            g12_a(fixture, base)
            g12_b(fixture, base)
            g12_c(fixture, base)
            g12_d(fixture, base)
            g12_e(fixture, base)
            g12_f(fixture, base)
            replay = g12_g(fixture, base)
            assert replay["replay_source"] == "journal tool_message"
            assert replay["rerender"] is False
            assert replay["second_spawn"] is False
            assert replay["journal_event_types_unchanged"] is True
            g12_h(fixture, base)
            g12_l(fixture, base)
            r01_prepared_resume(fixture, base)
            r02_started_lease_expiry(fixture, base)
            r07_prepare_resume(fixture, base)
            r08_release_resume(fixture, base)
            r05_evidence = r05_tool_finished_fresh_reconcile(fixture, base)
            r06_evidence = r06_settled_restart_noop(fixture, base)
            r15_evidence = r15_multiple_pending_reconcile(fixture, base)
            r16_evidence = r16_settlement_backfill(fixture, base)
            r03_evidence = r03_kill_parent_sigkill(fixture, base)
            r04_evidence = r04_model_finished_replay(fixture, base)
            r09_evidence = r09_mixed_batch_timeout(fixture, base)
            r10_evidence = r10_first_tool_finished_crash(fixture, base)
            r11_evidence = r11_artifact_tamper(fixture, base)
            r12_evidence = r12_workspace_unavailable(fixture, base)
            r13_evidence = r13_timeout_group_cleanup(fixture, base)
            r14_evidence = r14_legacy_union_recovery(fixture, base)
        replay_vector_probe()
    for name, evidence in (("r03", r03_evidence), ("r04", r04_evidence),
                           ("r05", r05_evidence), ("r06", r06_evidence),
                           ("r09", r09_evidence), ("r10", r10_evidence),
                           ("r11", r11_evidence), ("r12", r12_evidence),
                           ("r13", r13_evidence), ("r14", r14_evidence),
                           ("r15", r15_evidence), ("r16", r16_evidence)):
        print(f"[w7-evidence] {name} "
              f"{json.dumps(evidence, sort_keys=True, default=str)}")
    print("[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok "
          "node=ok; second_spawn=false; rerender=false; "
          "journal_events_unchanged=true; no_replay=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
