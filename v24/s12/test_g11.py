"""G11-A..L: deterministic Fake-only fairness contracts.

Finite selection probes are paired with a real HostWorker/HostDB/PostgreSQL
fixture path for every named case. All external handlers/transports are Fake;
network entry points are denied for the complete gate lifetime.
"""
from __future__ import annotations

import argparse
import ast
import copy
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent
for path in (ROOT, ROOT.parent.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fair_support import FakeDB, FakeJournal, effect, fresh_scope
from v24.host.db import HostContractError
from v24.host.worker import HostWorker

ALL = tuple(f"G11-{letter}" for letter in "ABCDEFGHIJKL")


def worker(db, journal=None, seen=None):
    journal = journal or FakeJournal()
    seen = seen if seen is not None else []
    host = HostWorker(db, journal, resource_handler=lambda e: (seen.append(e["kind"]) or
        ("success", {"v": 1, "observed": "fake"})))
    def execute(item, token):
        seen.append(item["kind"])
        db.settle(item["effect_id"], "success", token, item["kind"],
                  {"v": 1, "observed": "fake"})
        return {"executed": True, "settled": True, "reply": None}
    host._fair_execute = execute
    return host


def run_a():
    a, b = fresh_scope(), fresh_scope()
    effects = [effect(a), effect(b)]
    db = FakeDB([a, b], effects)
    stats = worker(db).run_scopes_until_idle([a, b], max_rounds=2)
    assert stats.scope_visits == 2 and stats.new_opportunities == 2, stats
    assert all(e["status"] == "succeeded" for e in db.effects.values())


def run_b():
    scope = fresh_scope()
    effects = [effect(scope, kind="host_prepare", ordinal=i,
                      created_at=f"2026-01-01T00:00:0{i}+00:00") for i in range(4)]
    effects.append(effect(scope, kind="model_call", ordinal=4,
                          created_at="2026-01-01T00:00:04+00:00"))
    seen = []
    db = FakeDB([scope], effects)
    stats = worker(db, seen=seen).run_scopes_until_idle([scope], max_rounds=8)
    assert seen[:4] == ["host_prepare"] * 3 + ["model_call"], seen
    assert stats.new_opportunities >= 5


def run_c():
    scope = fresh_scope()
    effects = [effect(scope, ordinal=i,
                      created_at=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00")
               for i in range(65)]
    db = FakeDB([scope], effects)
    stats = worker(db).run_scopes_until_idle([scope], max_rounds=1)
    assert stats.scope_visits == 1
    assert db.rpc_log.count("host_effects") >= 2
    assert all(e["status"] in ("ready", "succeeded") for e in db.effects.values())


def run_d():
    scope = fresh_scope()
    db = FakeDB([scope], [effect(scope)])
    worker(db).run_scopes_until_idle([scope], max_rounds=1)
    assert db.rpc_log[0] == "host_effects"


def run_e():
    a, b = fresh_scope(), fresh_scope()
    started = effect(a)
    started["status"] = "claimed"
    started["attempt_no"], started["fence"], started["claim_owner"] = 1, 1, "fake"
    from datetime import datetime, timedelta, timezone
    started["lease_until"] = datetime.now(timezone.utc) + timedelta(minutes=5)
    journal = FakeJournal([{"v": 1, "seq": 1, "event_type": "dispatch_started",
        "effect_id": started["effect_id"], "request_digest": "0" * 64,
        "claim": {"attempt": 1, "fence": 1, "owner": "fake"}, "payload": {}}])
    ready = effect(b)
    db = FakeDB([a, b], [started, ready])
    stats = worker(db, journal).run_scopes_until_idle([a, b], max_rounds=2)
    assert stats.orphan_blocked == 1 and db.effects[ready["effect_id"]]["status"] == "succeeded"


def run_f():
    scope = fresh_scope()
    expired = effect(scope)
    expired["status"] = "claimed"
    expired["attempt_no"], expired["fence"], expired["claim_owner"] = 1, 1, "fake"
    from datetime import datetime, timedelta, timezone
    expired["lease_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    journal = FakeJournal([{"v": 1, "seq": 1, "event_type": "dispatch_started",
        "effect_id": expired["effect_id"], "request_digest": "0" * 64,
        "claim": {"attempt": 1, "fence": 1, "owner": "fake"}, "payload": {}}])
    db = FakeDB([scope], [expired])
    stats = worker(db, journal).run_scopes_until_idle([scope], max_rounds=1)
    assert stats.recovery_commands == 1 and stats.recovery_applied == 0


def run_g():
    scope = fresh_scope()
    item = effect(scope)
    db = FakeDB([scope], [item], deferred_once=[item["effect_id"]])
    first = worker(db).run_scopes_until_idle([scope], max_rounds=1)
    assert first.claim_conflicts == 1 and db.effects[item["effect_id"]]["status"] == "ready"
    second = worker(db).run_scopes_until_idle([scope], max_rounds=2)
    assert second.new_opportunities == 1 and db.effects[item["effect_id"]]["status"] == "succeeded"


def run_h():
    scope = fresh_scope()
    item = effect(scope)
    left = FakeDB([scope], [copy.deepcopy(item)])
    right = FakeDB([scope], [copy.deepcopy(item)])
    w1, w2 = worker(left), worker(right)
    s1 = w1.run_scopes_until_idle([scope], max_rounds=1)
    s2 = w2.run_scopes_until_idle([scope], max_rounds=1)
    assert (s1.new_opportunities, s1.claimed) == (s2.new_opportunities, s2.claimed)


def run_i():
    scope = fresh_scope()
    terminal = effect(scope)
    terminal["status"] = "unknown"
    journal = FakeJournal([{"v": 1, "seq": 1, "event_type": "dispatch_started",
        "effect_id": terminal["effect_id"], "request_digest": "0" * 64,
        "claim": {}, "payload": {}}])
    db = FakeDB([scope], [terminal])
    stats = worker(db, journal).run_scopes_until_idle([scope], max_rounds=1)
    record = journal.last("settlement_committed", terminal["effect_id"])
    assert stats.idle and record["payload"]["reason"] == "database_terminal_no_outcome"


def run_j():
    scope = fresh_scope()
    item = effect(scope)
    item["cancel_requested"] = True
    db = FakeDB([scope], [item])
    stats = worker(db).run_scopes_until_idle([scope], max_rounds=1)
    assert stats.new_opportunities == 1


def run_k():
    scope, foreign = fresh_scope(), fresh_scope()
    item = effect(foreign)
    journal = FakeJournal([{"v": 1, "seq": 1, "event_type": "dispatch_started",
        "effect_id": item["effect_id"], "request_digest": "0" * 64,
        "claim": {}, "payload": {}}])
    db = FakeDB([scope, foreign], [item])
    try:
        worker(db, journal).run_scopes_until_idle([scope], max_rounds=1)
    except HostContractError:
        return
    raise AssertionError("off-roster journal debt was accepted")


def run_l():
    scopes = [fresh_scope() for _ in range(3)]
    db = FakeDB(scopes, [effect(s) for s in scopes])
    stats = worker(db).run_scopes_until_idle(scopes, max_rounds=3)
    assert stats.scope_visits == 3 and stats.new_opportunities == 3
    try:
        worker(db).run_scopes_until_idle(scopes, max_rounds=0)
    except ValueError:
        pass
    else:
        raise AssertionError("max_rounds=0 accepted")


def static_guards():
    root = Path(__file__).resolve().parent
    for path in (root / "fair_support.py", root / "test_g11.py"):
        tree = ast.parse(path.read_text())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        forbidden = {"socket", "http", "urllib", "requests", "ftplib", "smtplib",
                     "telnetlib", "aiohttp", "httpx"}
        for node in imports:
            names = [node.module] if isinstance(node, ast.ImportFrom) else [x.name for x in node.names]
            assert all(not name or name.split('.')[0] not in forbidden for name in names), path
        assert ("time." + "sleep") not in path.read_text(), path
    source = (root.parent / "host" / "worker.py").read_text()
    assert "run_scopes_until_idle" in source and "attempted" in source


CASES = {"G11-A": run_a, "G11-B": run_b, "G11-C": run_c,
         "G11-D": run_d, "G11-E": run_e, "G11-F": run_f,
         "G11-G": run_g, "G11-H": run_h, "G11-I": run_i,
         "G11-J": run_j, "G11-K": run_k, "G11-L": run_l}

# ---------------------------------------------------------------------------
# Real HostWorker + HostDB + disposable PostgreSQL, scripted adapter only.
# The in-memory checks above are small seam probes, not lifecycle evidence.
# ---------------------------------------------------------------------------
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import product
from unittest.mock import patch
import hashlib
import json
import os
import tempfile

from psycopg2.extras import Json
from v24.s10 import test_g9 as g9
from v24.s9 import h_support as h
from v24.host.db import HostDB, HostDBError
from v24.host.journal import HostJournal, JournalCorrupt, request_digest
from v24.host.worker import HostCrash, HOST_KINDS
from fair_support import reference_choice


def raises(kind, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except kind:
        return
    raise AssertionError(f"expected {kind.__name__}")


def seed_resource(owner, scope, *, status="ready", replay="replay_safe", created=None):
    install = h.seed_install(owner, scope, state="preparing")
    eid = str(uuid4())
    req = {"install_id": str(install), "reservation": f"v24:host_prepare:{eid}"}
    from test_ddl import effect as insert_effect
    with owner.cursor() as cur:
        insert_effect(cur, eid, scope_id=scope, kind="host_prepare", status=status,
            request=Json(req), request_digest=bytes.fromhex(request_digest(req)), replay_policy=replay,
            attempt_no=1 if status == "claimed" else 0,
            fence=1 if status == "claimed" else 0,
            claim_owner="fixture-owner" if status == "claimed" else None,
            lease_until=datetime.now(timezone.utc) - timedelta(minutes=2) if status == "claimed" else None,
            created_at=created or datetime.now(timezone.utc))
    owner.commit()
    return eid


def make_host(host, journal, script=()):
    adapter, transport, _ = g9.adapter_for(list(script))
    def resource(item):
        host.assert_all_idle()
        return "success", {"v": 1, "observed": "known"}
    return HostWorker(host, journal, adapter=adapter, resource_handler=resource), transport


@contextmanager
def evidence(host, worker, owner, case):
    """Persist actual choices, physical claims and per-visit state in fixture DB."""
    trace = []
    original_claim, original_pick, original_visit = host.claim, worker._fair_pick, worker._fair_visit
    def claim(eid, lease):
        result = original_claim(eid, lease)
        trace.append({"op": "claim", "effect": str(eid), "result": result})
        return result
    def pick(scope, klass, candidates):
        item = original_pick(scope, klass, candidates)
        trace.append({"op": "select", "scope": scope, "class": klass,
                      "effect": str(item["effect_id"])})
        return item
    def visit(scope, attempted):
        before = len(trace)
        stats, progressed = original_visit(scope, attempted)
        payload = {"case": case, "scope": scope, "events": trace[before:],
                   "new_opportunities": stats.new_opportunities,
                   "prepared_attempts": stats.prepared_attempts,
                   "applied": stats.recovery_applied, "pending": stats.pending_work,
                   "progressed": progressed, "streak": worker._host_streak.get(scope, 0)}
        with owner.cursor() as cur:
            cur.execute("INSERT INTO v24_fake.journal "
                "(effect_id,attempt,fence,op,payload,finished_at) "
                "VALUES (%s,0,0,'fair_visit',%s,clock_timestamp())", (str(uuid4()), Json(payload)))
        owner.commit()
        trace.append({"op": "visit", "scope": scope})
        return stats, progressed
    host.claim, worker._fair_pick, worker._fair_visit = claim, pick, visit
    try:
        yield trace
    finally:
        host.claim, worker._fair_pick, worker._fair_visit = original_claim, original_pick, original_visit


def ids(trace, op="select"):
    return [x["effect"] for x in trace if x["op"] == op]


def expire(owner, eid):
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET lease_until=now()-interval '2 minutes' WHERE effect_id=%s", (eid,))
    owner.commit()


def journal_start(journal, item, *, finished=False):
    token = {"attempt": item["attempt_no"], "fence": item["fence"], "owner": item["claim_owner"]}
    digest = request_digest(item["request"])
    journal.append("dispatch_started", str(item["effect_id"]), digest, {},
                   run_id=item.get("run_id"), claim=token)
    if finished:
        journal.append("dispatch_finished", str(item["effect_id"]), digest,
                       {"outcome": {"v": 1, "class": "success", "claim": token,
                                    "body": {"kind": item["kind"], "result": {"v": 1, "observed": "known"}}}},
                       run_id=item.get("run_id"), claim=token)


def integration_a(host, owner, work, fixture):
    roots, models = [], []
    for _ in range(2):
        root, live = g9.new_scope(host, owner)
        roots.append(str(root))
        for _ in range(3):
            _, mid = g9.start_run(host, root, live)
            models.append(str(mid))
    # Save the old caller-domain gap: only driving A cannot service B.
    with g9.make_journal(work, "a-old") as journal:
        old, _ = make_host(host, journal, [g9.reply(g9.chat_body(content="old"))])
        old.run_until_idle(roots[0], max_rounds=1)
        assert all(g9.effect_row(owner, mid)["status"] == "ready" for mid in models[3:])
    with g9.make_journal(work, "a-new") as journal:
        fair, transport = make_host(host, journal, [g9.reply(g9.chat_body(content="new")) for _ in range(4)])
        with evidence(host, fair, owner, "G11-A") as trace:
            stats = fair.run_scopes_until_idle(roots, 4)
        visits = [x["scope"] for x in trace if x["op"] == "visit"]
        assert visits == sorted(roots) * 2, visits
        assert stats.new_opportunities == 4 and len(transport.calls) == 4
        assert len(ids(trace)) == 4


def integration_b(host, owner, work, fixture):
    root, live = g9.new_scope(host, owner)
    _, model = g9.start_run(host, root, live)
    resources = [seed_resource(owner, root) for _ in range(5)]
    with g9.make_journal(work, "b-old-priority") as journal:
        old, _ = make_host(host, journal)
        for _ in range(4):
            old.run_once(root)
            seed_resource(owner, root)
        assert g9.effect_row(owner, model)["status"] == "ready"
    # Fresh finite window for the new class quota.
    root, live = g9.new_scope(host, owner)
    _, model = g9.start_run(host, root, live)
    resources = [seed_resource(owner, root) for _ in range(5)]
    with g9.make_journal(work, "b-burst") as journal:
        fair, transport = make_host(host, journal, [g9.reply(g9.chat_body(content="business"))])
        with evidence(host, fair, owner, "G11-B") as trace:
            stats = fair.run_scopes_until_idle([str(root)], 4)
        choices = ids(trace)
        assert choices[:3] == sorted(resources, key=lambda x: fair._fair_key(g9.effect_row(owner,x)))[:3]
        assert choices[3] == str(model) and len(transport.calls) == 1
        assert stats.new_opportunities == 4
    # Prepared-ready consumes recovery quota, not the fresh streak/opportunity.
    root, _ = g9.new_scope(host, owner)
    prepared = seed_resource(owner, root)
    other = seed_resource(owner, root)
    with g9.make_journal(work, "b-prepared-ready") as journal:
        item = g9.effect_row(owner, prepared)
        journal.append("effect_prepared", prepared, request_digest(item["request"]), {}, claim={})
        fair, _ = make_host(host, journal)
        with evidence(host, fair, owner, "G11-B/prepared") as trace:
            stats = fair.run_scopes_until_idle([str(root)], 1)
        assert stats.prepared_attempts == 1 and stats.new_opportunities == 1
        assert ids(trace, "claim") == [prepared, other]
        assert fair._host_streak[str(root)] == 1
    # Real claimed-token recovery resumes without issuing another claim.
    root, run, model = g9.fresh_run(host, owner)
    with g9.make_journal(work, "b-prepared-claimed") as journal:
        broken, _ = make_host(host, journal)
        broken.crash_after = "prepared"
        raises(HostCrash, broken.run_scopes_until_idle, [str(root)], 1)
        fair, transport = make_host(host, journal, [g9.reply(g9.chat_body(content="resume"))])
        with evidence(host, fair, owner, "G11-B/token") as trace:
            stats = fair.run_scopes_until_idle([str(root)], 1)
        assert stats.prepared_attempts == 1 and stats.claimed == 0
        assert ids(trace, "claim") == [] and len(transport.calls) == 1


def integration_c(host, owner, work, fixture):
    roots = [g9.new_scope(host, owner)[0] for _ in range(2)]
    for number in (0, 64, 65, 128):
        root = g9.new_scope(host, owner)[0]
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = [seed_resource(owner, root, created=timestamp) for _ in range(number)]
        history_install = h.seed_install(owner, root)
        h.seed_history(owner, root, history_install, 3, prefix=f"g11-c-{number}-{uuid4().hex}")
        with g9.make_journal(work, f"c-{number}") as journal:
            fair, _ = make_host(host, journal)
            before = h.snapshot(owner)
            start_log = len(host.rpc_log)
            result = fair._fair_scan(str(root))
            assert h.snapshot(owner) == before
            assert [x["effect_id"] for x in result] == sorted(expected)
            assert host.rpc_log[start_log:].count("host_effects") == max(1, (number+63)//64)
    a_ids = [seed_resource(owner, roots[0]) for _ in range(65)]
    b_id = seed_resource(owner, roots[1])
    with g9.make_journal(work, "c-roster") as journal:
        fair, _ = make_host(host, journal)
        with evidence(host, fair, owner, "G11-C") as trace:
            stats = fair.run_scopes_until_idle(map(str, roots), 2)
        assert stats.new_opportunities == 2
        assert len(set(x["scope"] for x in trace if x["op"] == "select")) == 2


def integration_d(host, owner, work, fixture):
    root = g9.new_scope(host, owner)[0]
    original = [seed_resource(owner, root) for _ in range(65)]
    with g9.make_journal(work, "d-dynamic") as journal:
        fair, _ = make_host(host, journal)
        actual, pages, added = host.host_effects, [], []
        def scan(*args):
            response = actual(*args)
            pages.append(len(response["items"]))
            if len(pages) == 1:
                added.append(seed_resource(owner, root, created=datetime.now(timezone.utc)+timedelta(days=1)))
            return response
        with patch.object(host, "host_effects", scan):
            result = fair._fair_scan(str(root))
        assert set(original+added) == {x["effect_id"] for x in result}
        assert pages == [64, 2]
        # Roster capture is one invocation; a later scope only appears next call.
        captured = fair._fair_roster(None)
        later = str(g9.new_scope(host, owner)[0])
        assert later not in captured and later in fair._fair_roster(None)


def integration_e(host, owner, work, fixture):
    root, run, model = g9.fresh_run(host, owner)
    other, _, mid2 = g9.fresh_run(host, owner)
    with g9.make_journal(work, "e-orphan") as journal:
        broken, _ = make_host(host, journal)
        broken.crash_after = "started"
        raises(HostCrash, broken.run_scopes_until_idle, [str(root)], 1)
        fair, transport = make_host(host, journal, [g9.reply(g9.chat_body(content="other"))])
        with evidence(host, fair, owner, "G11-E"):
            stats = fair.run_scopes_until_idle([str(root), str(other)], 2)
        assert stats.orphan_blocked == 1 and len(transport.calls) == 1
        assert g9.effect_row(owner, model)["status"] == "claimed"
        assert g9.effect_row(owner, mid2)["status"] == "succeeded"


def integration_f(host, owner, work, fixture):
    root, _ = g9.new_scope(host, owner)
    expired_ids = [seed_resource(owner, root, status="claimed") for _ in range(17)]
    manual = seed_resource(owner, root, status="claimed", replay="manual")
    other, _, mid = g9.fresh_run(host, owner)
    with g9.make_journal(work, "f-recover") as journal:
        journal_start(journal, g9.effect_row(owner, expired_ids[0]))
        fair, transport = make_host(host, journal, [g9.reply(g9.chat_body(content="other"))])
        with evidence(host, fair, owner, "G11-F"):
            stats = fair.run_scopes_until_idle([str(root), str(other)], 2)
        assert stats.recovery_commands == 1 and stats.recovery_applied == 16, stats
        assert stats.recovery_has_more and stats.manual_debt_ids == {manual}, stats
        assert len(transport.calls) == 1
        # Second visit pays only remaining recover work, manual persists.
        next_stats = fair.run_scopes_until_idle([str(root), str(other)], 2)
        assert next_stats.recovery_commands == 1 and next_stats.recovery_applied == 1
    # manual-only must not issue empty recovery commands.
    root, _ = g9.new_scope(host, owner)
    manual = seed_resource(owner, root, status="claimed", replay="manual")
    with g9.make_journal(work, "f-manual") as journal:
        fair, _ = make_host(host, journal)
        stats = fair.run_scopes_until_idle([str(root)], 1)
        assert stats.recovery_commands == 0 and stats.manual_debt_ids == {manual}
        assert stats.stop_reason == "blocked_no_progress" and not stats.idle


def integration_g(host, owner, work, fixture):
    root, _ = g9.new_scope(host, owner)
    eid = seed_resource(owner, root)
    with g9.make_journal(work, "g-real-conflict") as journal:
        fair, _ = make_host(host, journal)
        rival = HostDB(fixture.role_dsn("admin"), fixture.role_dsn("service"))
        try:
            original = host.claim
            calls = []
            def compete(target, lease):
                calls.append(target)
                rival.claim(target, lease)
                return original(target, lease)
            with patch.object(host, "claim", compete), evidence(host, fair, owner, "G11-G"):
                stats = fair.run_scopes_until_idle([str(root)], 3)
            assert calls == [eid] and stats.claim_conflicts == 1
            assert not journal.has("dispatch_started", eid)
        finally:
            rival.close()
    # A real terminal-target invalid_args is a skippable observed race.
    root, _ = g9.new_scope(host, owner)
    eid = seed_resource(owner, root)
    with g9.make_journal(work, "g-terminal-race") as journal:
        fair, _ = make_host(host, journal)
        original = host.claim
        def terminal(target, lease):
            with owner.cursor() as cur:
                cur.execute("UPDATE v24.effects SET status='cancelled',settled_at=now(),outcome=NULL WHERE effect_id=%s",
                    (target,))
            owner.commit()
            return original(target, lease)
        with patch.object(host, "claim", terminal):
            stats = fair.run_scopes_until_idle([str(root)], 1)
        assert stats.claim_conflicts == 1 and not journal.has("dispatch_started", eid)


def integration_h(host, owner, work, fixture):
    root, _ = g9.new_scope(host, owner)
    items = [seed_resource(owner, root) for _ in range(3)]
    choices = []
    # Restore the same DB rows and use identical empty journal prefixes.
    before = h.snapshot(owner)
    def deferred(eid, lease):
        return {"v":1,"disposition":"deferred","effect_id":str(eid),"claim":None}
    for attempt in range(2):
        with g9.make_journal(work, f"h-{attempt}") as journal:
            fair, _ = make_host(host, journal)
            # One-scope no-progress stops after one visit. The identical claim
            # script is lease-independent and leaves every domain row untouched.
            with patch.object(host, "claim", deferred), evidence(host, fair, owner, "G11-H") as trace:
                fair.run_scopes_until_idle([str(root)], 3)
            choices.append(ids(trace))
            assert h.snapshot(owner) == before
    assert choices[0] == choices[1] and len(choices[0]) == 1


def integration_i(host, owner, work, fixture):
    root, run, model = g9.fresh_run(host, owner)
    with g9.make_journal(work, "i-orphan-unknown") as journal:
        broken, _ = make_host(host, journal)
        broken.crash_after = "started"
        raises(HostCrash, broken.run_scopes_until_idle, [str(root)], 1)
        expire(owner, model)
        fair, transport = make_host(host, journal)
        with evidence(host, fair, owner, "G11-I"):
            stats = fair.run_scopes_until_idle([str(root)], 2)
        record = journal.last("settlement_committed", model)
        assert record["payload"] == {"conflict":True,"reason":"database_terminal_no_outcome","database_status":"unknown"}
        assert stats.recovery_applied == 1 and stats.settled == 0 and stats.reconciled == 0
        assert not journal.has("dispatch_finished", model) and not transport.calls
        assert g9.run_row(owner, run)["status"] == "blocked_unknown" and stats.idle
        records = len(journal.records)
        again, _ = make_host(host, journal)
        assert again.run_scopes_until_idle([str(root)],1).idle
        assert len(journal.records) == records
    # Durable success always takes reconcile precedence over no-outcome.
    root, run, model = g9.fresh_run(host, owner)
    with g9.make_journal(work, "i-finished") as journal:
        broken, _ = make_host(host, journal, [g9.reply(g9.chat_body(content="old"))])
        broken.crash_after = "finished"
        raises(HostCrash, broken.run_scopes_until_idle, [str(root)], 1)
        saved = journal.last("dispatch_finished",model)["payload"]["outcome"]
        expire(owner, model)
        host.recover(root, f"g11-i-{uuid4().hex}",16)
        unknown = g9.effect_row(owner,model)["outcome"]
        fair, transport = make_host(host, journal)
        stats = fair.run_scopes_until_idle([str(root)],2)
        marker = journal.last("settlement_committed",model)["payload"]
        assert marker["reason"] == "database_terminal" and marker["outcome"] == saved
        assert g9.effect_row(owner,model)["outcome"] == unknown and not transport.calls


def integration_j(host, owner, work, fixture):
    from test_g2b import cancel
    root, run, model = g9.fresh_run(host, owner)
    with g9.make_journal(work, "j-cancel") as journal:
        broken, _ = make_host(host, journal)
        broken.crash_after = "started"
        raises(HostCrash, broken.run_scopes_until_idle,[str(root)],1)
        response, _ = cancel(host.service, run, 1, f"g11-cancel-{uuid4().hex}")
        host.service.commit()
        assert response["disposition"] == "committed", response
        seal = g9.run_row(owner,run)
        assert seal["status"] == "cancelled",seal
        expire(owner,model)
        fair, transport = make_host(host,journal)
        with evidence(host,fair,owner,"G11-J"):
            stats = fair.run_scopes_until_idle([str(root)],2)
        assert stats.recovery_applied == 1 and not transport.calls
        after = g9.run_row(owner,run)
        for column in ("status", "close_intent", "result", "interaction", "pending_steer",
                       "ended_at", "turn_no", "revision"):
            assert after[column] == seal[column], (column, after[column], seal[column])
        assert g9.effect_row(owner,model)["outcome"]["body"]["result"]["reason"] == "cancel_late"


def integration_k(host, owner, work, fixture):
    roots = [str(g9.new_scope(host,owner)[0]) for _ in range(3)]
    for root in roots:
        seed_resource(owner,root)
    with g9.make_journal(work,"k-visits") as journal:
        fair,_ = make_host(host,journal)
        visits=[]
        for _ in range(3):
            with evidence(host,fair,owner,"G11-K") as trace:
                stats=fair.run_scopes_until_idle(roots,1)
            assert stats.scope_visits == stats.rounds == 1
            visits.extend(x["scope"] for x in trace if x["op"]=="visit")
        assert visits==sorted(roots)
        anchor=fair._next_scope_after
        fair.run_scopes_until_idle([roots[0]],1)
        assert fair._next_scope_after==roots[0] and anchor in roots
        for bad in (0,-1,True,1.5,"2"):
            raises(ValueError,fair.run_scopes_until_idle,roots,bad)
        raises(ValueError,fair.run_scopes_until_idle,roots[0],1)
        raises(ValueError,fair.run_scopes_until_idle,["bad"],1)
        assert fair.run_scopes_until_idle([],1).idle
        empty=str(g9.new_scope(host,owner)[0])
        assert fair.run_scopes_until_idle([empty],1).stop_reason=="idle"
    # Existing settlement history is filtered BEFORE any point read, even off-roster.
    for conflict in (False,True):
        with g9.make_journal(work,f"k-history-{conflict}") as journal:
            eid=str(uuid4())
            journal.append("dispatch_started",eid,"0"*64,{},claim={})
            journal.append("settlement_committed",eid,"0"*64,{"conflict":conflict},claim={})
            fair,_=make_host(host,journal)
            with patch.object(host,"host_effect",side_effect=AssertionError("history read")):
                assert fair.run_scopes_until_idle([],1).idle
    # Verify all IDs before writing any terminal marker.
    root=str(g9.new_scope(host,owner)[0])
    eid=seed_resource(owner,root)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='cancelled',outcome=NULL,settled_at=now() WHERE effect_id=%s", (eid,))
    owner.commit()
    with g9.make_journal(work,"k-ownership") as journal:
        journal.append("dispatch_started",eid,"0"*64,{},claim={})
        missing=str(uuid4())
        journal.append("dispatch_started",missing,"0"*64,{},claim={})
        fair,_=make_host(host,journal)
        raises(HostContractError,fair.run_scopes_until_idle,[root],1)
        assert not journal.has("settlement_committed",eid)
        raises(HostContractError,fair.run_scopes_until_idle,[],1)


def integration_l(host,owner,work,fixture):
    # Dense interval, each scope has enough actual ready work for each visit.
    roots=[str(g9.new_scope(host,owner)[0]) for _ in range(3)]
    for root,n in zip(roots,(3,4,50)):
        for _ in range(n):
            seed_resource(owner,root)
    with g9.make_journal(work,"l-dense") as journal:
        fair,_=make_host(host,journal)
        with evidence(host,fair,owner,"G11-L") as trace:
            stats=fair.run_scopes_until_idle(roots,9)
        selects=[x["scope"] for x in trace if x["op"]=="select"]
        assert stats.new_opportunities==9
        counts={root:0 for root in roots}
        for root in selects:
            counts[root]+=1
            assert max(counts.values())-min(counts.values())<=1
        assert set(counts.values())=={3}


INTEGRATION={f"G11-{letter}":globals()[f"integration_{letter.lower()}"] for letter in "ABCDEFGHIJKL"}


def model_check():
    # Enumerate independent finite rules against production selection. No IO.
    count=0
    scope=str(uuid4())
    for nh,nb,streak in product(range(3),range(3),range(4)):
        hs=[str(UUID(int=i+1)) for i in range(nh)]
        bs=[str(UUID(int=i+10)) for i in range(nb)]
        for cursor in [None]+hs+bs:
            klass,target,new_streak=reference_choice(hs,bs,streak,cursor)
            if target is None:
                continue
            fair=HostWorker(FakeDB([scope],[]),FakeJournal())
            candidates=[]
            for eid in hs if klass=="host" else bs:
                item=effect(scope,kind="host_prepare" if klass=="host" else "model_call")
                item["effect_id"]=eid
                candidates.append(item)
            if cursor is not None:
                fair._fair_cursors[(scope,klass)]=fair._fair_key({"effect_id":cursor,"created_at":"2026-01-01T00:00:00+00:00"})
            actual=fair._fair_pick(scope,klass,candidates)
            assert actual["effect_id"]==target,(nh,nb,streak,cursor,target,actual)
            assert new_streak==(0 if klass=="business" else min(3,streak+1))
            count+=1
    print(f"[G11/model] {count} finite selection states; S=1..3 dense traces checked by G11-L")

def error_probes():
    """Phase-specific errors; never trade a malformed envelope for idleness."""
    scope=fresh_scope()
    for code in ("invalid_args","stale_claim","unauthorized","effect_id_conflict"):
        item=effect(scope)
        db=FakeDB([scope],[item])
        w=worker(db)
        db.claim=lambda *a,c=code: {"v":1,"error":{"code":c}}
        raises(HostDBError,w.run_scopes_until_idle,[scope],1)
        assert not w._fair_active
    for response in ({"v":1,"disposition":"mystery","claim":None},
                     {"v":1,"disposition":"committed","claim":None},
                     {"v":1,"disposition":"deferred","claim":{"attempt":1}},
                     {"v":1,"disposition":"committed","claim":{"attempt":True,"fence":1,"owner":"x"}},
                     {"v":True,"disposition":"committed","claim":{}},
                     {"v":1,"error":None},None):
        item=effect(scope)
        db=FakeDB([scope],[item])
        w=worker(db)
        result=copy.deepcopy(response)
        if isinstance(result,dict): result["effect_id"]=item["effect_id"]
        db.claim=lambda *a: copy.deepcopy(result)
        raises((HostDBError,HostContractError),w.run_scopes_until_idle,[scope],1)
    # Terminal invalid_args and observed stale/committed-token races are zero IO.
    for code in ("invalid_args","stale_claim","token_race"):
        item=effect(scope)
        db=FakeDB([scope],[item]); seen=[]; w=worker(db,seen=seen)
        def race(eid,lease):
            db.effects[eid]["status"]="unknown"
            if code=="token_race":
                return {"v":1,"effect_id":eid,"disposition":"committed",
                        "claim":{"attempt":1,"fence":1,"owner":"fake"}}
            return {"v":1,"error":{"code":code}}
        db.claim=race
        stats=w.run_scopes_until_idle([scope],1)
        assert stats.claim_conflicts==1 and not seen
    # Ready item remains after deferred; guard suppresses wrap-around on later
    # visits while other ready candidates make genuine progress.
    items=[effect(scope,created_at=f"2026-01-01T00:00:0{i}+00:00") for i in range(3)]
    other=fresh_scope()
    others=[effect(other,created_at=f"2026-01-01T00:00:0{i}+00:00") for i in range(3)]
    db=FakeDB([scope,other],items+others,deferred_once=[items[0]["effect_id"]]); w=worker(db)
    physical=[]; original=db.claim
    def record(eid,lease): physical.append(eid); return original(eid,lease)
    db.claim=record
    stats=w.run_scopes_until_idle([scope,other],10)
    assert len(physical)==len(set(physical))==6 and not stats.idle
    assert stats.stop_reason=="blocked_no_progress"
    w.run_scopes_until_idle([scope],2)
    assert physical.count(items[0]["effect_id"])==2
    # Same physical guard applies to prepared-ready before discovery.
    db=FakeDB([scope],items,deferred_once=[items[0]["effect_id"]]); journal=FakeJournal()
    journal.append("effect_prepared",items[0]["effect_id"],request_digest(items[0]["request"]),{},claim={})
    w=worker(db,journal); physical=[]; original=db.claim
    def record2(eid,lease): physical.append(eid); return original(eid,lease)
    db.claim=record2
    stats=w.run_scopes_until_idle([scope],6)
    assert len(physical)==len(set(physical))==3
    assert stats.prepared_attempts==1 and stats.new_opportunities==2
    # Read/recover/settle classifications do not reuse legacy swallow mappings.
    for response in ({"v":1,"error":{"code":"unauthorized"}}, {"v":1,"items":None}, None):
        db=FakeDB([scope],[effect(scope)]); w=worker(db)
        db.host_effects=lambda *a: response
        raises((HostDBError,HostContractError),w.run_scopes_until_idle,[scope],1)
    for code in ("receipt_conflict","stale_claim"):
        w=worker(FakeDB([],[]))
        assert not w._fair_settle_response({"v":1,"error":{"code":code}})
    for response in ({"v":1,"error":{"code":"invalid_outcome"}}, {"v":1,"disposition":"deferred"}):
        raises((HostDBError,HostContractError),w._fair_settle_response,response)
    db=FakeDB([],[]); w=worker(db)
    db.recover=lambda *a: {"v":1,"error":{"code":"unauthorized"}}
    raises(HostDBError,w._fair_recover,scope)
    db.recover=lambda *a: {"v":1,"disposition":"committed","recovery":{"applied":[],"skipped":[],"manual_debt":True,"has_more":False}}
    raises(HostContractError,w._fair_recover,scope)


def exhaustive_model(owner):
    """Compare actual entry-point decisions with an independently updated model.

    Finite state bounds: S=1..3, each class 0..2, all streaks, all cursor
    anchors, budget 1..3S, success/deferred outcomes, and empty visits. The
    trace is retained in a fixture row; this is not a proof for arbitrary N.
    """
    from uuid import UUID
    digest=hashlib.sha256(); scenarios=0; max_steps=0
    for s,nh,nb,streak,outcome in product(range(1,4),range(3),range(3),range(4),("success","deferred")):
        roots=[str(UUID(int=10000+i)) for i in range(s)]
        for anchor in range(-1,max(nh,nb)):
            for budget in range(1,3*s+1):
                items=[]
                for si,root in enumerate(roots):
                    for klass,n,offset in (("host",nh,1),("business",nb,10)):
                        for i in range(n):
                            item=effect(root,kind="host_prepare" if klass=="host" else "model_call")
                            item["effect_id"]=str(UUID(int=100*si+offset+i))
                            items.append(item)
                db=FakeDB(roots,items); w=worker(db); selected=[]; visits=[]
                for root in roots:
                    w._host_streak[root]=streak
                    for klass,offset,n in (("host",1,nh),("business",10,nb)):
                        if anchor>=0 and n:
                            a=str(UUID(int=100*roots.index(root)+offset+min(anchor,n-1)))
                            w._fair_cursors[(root,klass)]=w._fair_key({"effect_id":a,"created_at":"2026-01-01T00:00:00+00:00"})
                original_pick=w._fair_pick; original_visit=w._fair_visit
                def pick(root,klass,candidates):
                    item=original_pick(root,klass,candidates)
                    selected.append((root,klass,item["effect_id"]))
                    return item
                def visit(root,attempted):
                    visits.append(root)
                    return original_visit(root,attempted)
                w._fair_pick=pick; w._fair_visit=visit
                if outcome=="deferred":
                    db.claim=lambda eid,lease: {"v":1,"disposition":"deferred","effect_id":eid,"claim":None}
                actual_stats=w.run_scopes_until_idle(roots,budget)
                # Reference updates independent ordered ID lists and index cursors.
                expected=[]; remaining={root:{"host":[],"business":[]} for root in roots}
                cursors={}; streaks={root:streak for root in roots}
                for item in items:
                    klass="host" if item["kind"] in HOST_KINDS else "business"
                    remaining[item["scope_id"]][klass].append(item["effect_id"])
                for root in roots:
                    for klass,values in remaining[root].items():
                        values.sort()
                        cursors[(root,klass)]=values[min(anchor,len(values)-1)] if anchor>=0 and values else None
                expected_visits=[]; suppressed=set(); completed=set()
                pass_seen=set(); residual={}; pass_progress=False
                expected_stop="budget_exhausted"
                for index in range(budget):
                    root=roots[index%s]; expected_visits.append(root)
                    visible=[x for values in remaining[root].values() for x in values]
                    available={k:[x for x in v if x not in suppressed] for k,v in remaining[root].items()}
                    klass="business" if available["business"] and (not available["host"] or streaks[root]==3) else "host"
                    k,eid,next_streak=reference_choice(available["host"],available["business"],streaks[root],cursors[(root,klass)])
                    if eid is not None:
                        expected.append((root,k,eid)); cursors[(root,k)]=eid; streaks[root]=next_streak
                        suppressed.add(eid)
                        if outcome=="success":
                            remaining[root][k].remove(eid); completed.add(eid); pass_progress=True
                    residual[root]=bool(visible)
                    pass_seen.add(root)
                    if len(pass_seen)==s:
                        if not any(residual.values()):
                            expected_stop="idle"; break
                        if not pass_progress:
                            expected_stop="blocked_no_progress"; break
                        pass_seen.clear(); pass_progress=False
                assert visits==expected_visits,(s,nh,nb,streak,outcome,anchor,budget,visits,expected_visits)
                assert selected==expected,(s,nh,nb,streak,outcome,anchor,budget,selected,expected)
                assert actual_stats.stop_reason==expected_stop,(actual_stats,expected_stop)
                assert actual_stats.new_opportunities==len(expected)
                assert actual_stats.executed==len(completed)
                assert actual_stats.claim_conflicts==(len(expected) if outcome=="deferred" else 0)
                for root in roots:
                    assert w._host_streak.get(root,0)==streaks[root]
                    for klass in ("host","business"):
                        expected_cursor=cursors[(root,klass)]
                        actual_cursor=w._fair_cursors.get((root,klass))
                        assert (None if actual_cursor is None else str(actual_cursor[1]))==expected_cursor
                digest.update(json.dumps(selected).encode()); scenarios+=1; max_steps=max(max_steps,len(visits))
    with owner.cursor() as cur:
        cur.execute("INSERT INTO v24_fake.journal(effect_id,attempt,fence,op,payload) VALUES (%s,0,0,'model_enum',%s)",
                    (str(uuid4()),Json({"scenarios":scenarios,"max_visits":max_steps,"trace_sha256":digest.hexdigest()})))
    owner.commit()
    print(f"[G11/model] {scenarios} entry-point scenarios; max {max_steps} visits; trace {digest.hexdigest()[:16]}",flush=True)

def d4_probes(host,owner,work):
    root=str(g9.new_scope(host,owner)[0])
    for status in ("succeeded","failed","unknown","cancelled"):
        eid=seed_resource(owner,root)
        with owner.cursor() as cur:
            cur.execute("UPDATE v24.effects SET status=%s,settled_at=now(),outcome=%s WHERE effect_id=%s",
                (status,None if status=="cancelled" else Json({"fixture":status}),eid))
        owner.commit()
        with g9.make_journal(work,f"d4-{status}") as journal:
            journal.append("dispatch_started",eid,"0"*64,{},claim={"attempt":1,"fence":1,"owner":"original"})
            fair,_=make_host(host,journal)
            before=h.snapshot(owner)
            stats=fair.run_scopes_until_idle([root],1)
            assert stats.idle and stats.settled==stats.reconciled==stats.executed==0
            assert h.snapshot(owner)==before
            marker=journal.last("settlement_committed",eid)
            assert marker["request_digest"]=="0"*64 and marker["claim"]["owner"]=="original"
            assert marker["payload"]=={"conflict":True,"reason":"database_terminal_no_outcome","database_status":status}
            assert not journal.has("dispatch_finished",eid)
    # Journal write failure must never report idle or mutate domain state.
    eid=seed_resource(owner,root)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='cancelled',settled_at=now() WHERE effect_id=%s",(eid,))
    owner.commit()
    with g9.make_journal(work,"d4-write-failure") as journal:
        journal.append("dispatch_started",eid,"0"*64,{},claim={})
        fair,_=make_host(host,journal)
        original=journal.append
        def fail(event,*args,**kwargs):
            if event=="settlement_committed": raise OSError("scripted durable write failure")
            return original(event,*args,**kwargs)
        with patch.object(journal,"append",fail):
            raises(OSError,fair.run_scopes_until_idle,[root],1)
        assert not journal.has("settlement_committed",eid)
        assert fair.run_scopes_until_idle([root],1).idle
        path=journal.path
    # Closed journal prefix with incomplete final marker: normal loader trims
    # the partial tail and re-verifies state before adding the conflict.
    with path.open("ab") as output:
        output.write(b'{"v":1,"event_type":"settlement_committed"')
    with HostJournal.open(path) as journal:
        count=len(journal.records)
        fair,_=make_host(host,journal)
        assert fair.run_scopes_until_idle([root],1).idle
        assert len(journal.records)==count


def cursor_probes():
    scope=fresh_scope()
    db=FakeDB([scope],[]); w=worker(db)
    for cursor in ({}, {"scope_id":"bad"}, {"scope_id":scope}):
        db.host_scopes=lambda *a,c=cursor: {"v":1,"items":[],"limit":64,"has_more":True,"next_cursor":c}
        raises(HostContractError,w.run_scopes_until_idle,None,1)
    item=effect(scope)
    db=FakeDB([scope],[item]); w=worker(db)
    page={"v":1,"items":[item],"limit":64,"has_more":True,
          "next_cursor":{"created_at":item["created_at"],"effect_id":item["effect_id"]}}
    db.host_effects=lambda *a: page
    raises(HostContractError,w.run_scopes_until_idle,[scope],1)
    # No full pass may be assembled across calls with budgets below S.
    scopes=[fresh_scope(),fresh_scope()]; db=FakeDB(scopes,[]); w=worker(db)
    for _ in range(4):
        stats=w.run_scopes_until_idle(scopes,1)
        assert not stats.idle and stats.pending_work and stats.stop_reason=="budget_exhausted"
    assert w.run_scopes_until_idle(scopes,2).idle

def review_regressions(host,owner,work):
    # A retained local preflight outcome must only reconcile, never dispatch.
    scope=fresh_scope(); item=effect(scope,kind="model_call")
    item.update(status="claimed",attempt_no=1,fence=1,claim_owner="local",
                lease_until=datetime.now(timezone.utc)+timedelta(minutes=5))
    db=FakeDB([scope],[item]); journal=FakeJournal()
    token={"attempt":1,"fence":1,"owner":"local"}
    journal.append("effect_prepared",item["effect_id"],request_digest(item["request"]),{},claim=token)
    outcome={"v":1,"class":"failure","claim":token,"body":{"kind":"model_call","result":{}}}
    journal.append("dispatch_finished",item["effect_id"],request_digest(item["request"]),{"outcome":outcome,"no_io":True},claim=token)
    db.settle=lambda *a: {"v":1,"error":{"code":"receipt_conflict"}}
    w=HostWorker(db,journal)
    w._fair_execute=lambda *a: (_ for _ in ()).throw(AssertionError("reexecuted durable local outcome"))
    stats=w.run_scopes_until_idle([scope],4)
    assert stats.prepared_attempts==0 and stats.stop_reason=="blocked_no_progress"
    # A local outcome with no confirmed settle is not actual pass progress.
    item=effect(scope,kind="model_call"); db=FakeDB([scope],[item]); journal=FakeJournal()
    db.settle=lambda *a: {"v":1,"error":{"code":"receipt_conflict"}}
    w=HostWorker(db,journal) # adapter absent -> durable no-IO failure
    stats=w.run_scopes_until_idle([scope],5)
    assert stats.stop_reason=="blocked_no_progress" and stats.scope_visits==1
    assert journal.has("dispatch_finished",item["effect_id"])
    # Missing/wrong effect and incomplete success envelope cannot clear debt.
    for reply in ({"v":1,"disposition":"committed"},
                  {"v":1,"disposition":"committed","effect_id":str(uuid4()),"emitted":[],"revision":0},
                  {"v":1,"disposition":"committed","effect_id":item["effect_id"]}):
        raises(HostContractError,w._fair_settle_response,reply,item["effect_id"])
    # Pins: malformed continuing pages must fail before adapter build/IO.
    for page in ({"v":1,"items":[],"limit":64,"has_more":True,"next_cursor":{"pin_id":str(uuid4())}},
                 {"v":1,"items":[{"pin_id":str(uuid4())}],"limit":64,"has_more":True,
                  "next_cursor":{"pin_id":str(uuid4())}}):
        db.host_run_pins=lambda *a,p=page:p
        w._fair_active=True
        try: raises(HostContractError,w._run_pins,str(uuid4()))
        finally: w._fair_active=False
    # DB commit before journal marker: equal durable outcome is not conflict.
    root,run,model=g9.fresh_run(host,owner)
    with g9.make_journal(work,"review-committed-outcome") as journal:
        fair,_=make_host(host,journal,[g9.reply(g9.chat_body(content="committed"))])
        original=journal.append
        def fail_marker(event,*args,**kwargs):
            if event=="settlement_committed": raise OSError("after DB commit")
            return original(event,*args,**kwargs)
        with patch.object(journal,"append",fail_marker):
            raises(OSError,fair.run_scopes_until_idle,[str(root)],1)
        assert g9.effect_row(owner,model)["status"]=="succeeded"
        again,transport=make_host(host,journal)
        stats=again.run_scopes_until_idle([str(root)],1)
        assert journal.last("settlement_committed",model)["payload"]["conflict"] is False
        assert stats.idle and not transport.calls
    # A empty before B clears its journal outcome: one pass can establish idle.
    roots=sorted(str(g9.new_scope(host,owner)[0]) for _ in range(2))
    root_b=roots[1]
    # Resource effect provides a genuine durable outcome with terminal DB row.
    eid=seed_resource(owner,root_b)
    with g9.make_journal(work,"review-cross-scope") as journal:
        fair,_=make_host(host,journal)
        original=journal.append
        def fail(event,*args,**kwargs):
            if event=="settlement_committed": raise OSError("after commit")
            return original(event,*args,**kwargs)
        with patch.object(journal,"append",fail):
            raises(OSError,fair.run_scopes_until_idle,[root_b],1)
        again,_=make_host(host,journal)
        stats=again.run_scopes_until_idle(roots,2)
        assert stats.idle and stats.stop_reason=="idle",stats
    # Interrupted FIRST D4 marker, not an already-resolved prefix.
    root=str(g9.new_scope(host,owner)[0]); eid=seed_resource(owner,root)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='cancelled',settled_at=now() WHERE effect_id=%s",(eid,))
    owner.commit()
    with g9.make_journal(work,"review-d4-partial-first") as journal:
        journal.append("dispatch_started",eid,"0"*64,{},claim={})
        path=journal.path
    with path.open("ab") as out: out.write(b'{"v":1,"seq":2,"event_type":"settlement_committed"')
    with HostJournal.open(path) as journal:
        assert len(journal.records)==1
        fair,_=make_host(host,journal)
        original=host.host_effect; reads=[]
        def read(target): reads.append(str(target)); return original(target)
        with patch.object(host,"host_effect",read):
            assert fair.run_scopes_until_idle([root],1).idle
        assert eid in reads
        assert len([r for r in journal.records if r["event_type"]=="settlement_committed"])==1

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--only")
    args = parser.parse_args(argv)
    static_guards()
    selected = ALL if not args.only else tuple(x.strip() for x in args.only.split(","))
    assert selected and set(selected) <= set(ALL), selected
    g9.assert_static_guards()
    g9.install_no_network()
    try:
        model_check()
        with g9.server_helper_scope(), g9.setup_db() as fixture:
            owner = g9.bind_owner(fixture)
            host = HostDB(fixture.role_dsn("admin"), fixture.role_dsn("service"))
            try:
                with tempfile.TemporaryDirectory(prefix="v24-g11-") as name:
                    work = Path(name)
                    os.chmod(work, 0o700)
                    exhaustive_model(owner)
                    error_probes()
                    cursor_probes()
                    d4_probes(host,owner,work)
                    review_regressions(host,owner,work)
                    for case in selected:
                        CASES[case]()
                        INTEGRATION[case](host, owner, work, fixture)
                        print(f"[{case}] seam + real PostgreSQL passed", flush=True)
                g9._assert_closed_catalog(host.control)
                host.control.rollback()
            finally:
                host.close()
                owner.close()
    finally:
        g9.restore_no_network()
    print(f"[passed] v24 G11 Fake-only: {len(selected)} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
