"""Controller thin-cut vertical gate.

Run: UV_FROZEN=1 uv run python v13/loop_driver/test_controller_vertical.py
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import os
import secrets
import sys
import textwrap
import uuid
from pathlib import Path
from unittest.mock import Mock

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.agentctl_verbs.test_agentctl_verbs import (
    append_user,
    call_verb,
    controller_pair,
    enqueue_human,
    prepare_chain,
    q1,
    shrink_catalog,
    snapshot_window,
)
from v13.load import load_stage, run_psql
from v13.loop.test_loop import mock_from_needed, set_mock
from v13.loop_driver.controller import decide_controller_disposition
from v13.loop_driver.driver import LoopDriver

DB = f"ll_controller_vertical_{os.getpid()}_{secrets.token_hex(3)}"
CREATED = False
MODEL = "jev-mock"
N = 0


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail != "" and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def as_obj(value):
    return json.loads(value) if isinstance(value, str) else value


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET track_functions = 'all'")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', %s, false)", (MODEL,))
    conn.commit()
    return conn


def driver(server, existing=None):
    drv = LoopDriver(lambda: existing if existing is not None else connect(server))
    drv.advance = Mock(wraps=drv.advance)
    read = drv._read
    drv.observe_boundaries = []
    def committed_read(sql, params):
        drv.observe_boundaries.append(drv.conn.get_transaction_status())
        result = read(sql, params)
        drv.observe_boundaries.append(drv.conn.get_transaction_status())
        return result
    drv._read = Mock(side_effect=committed_read)
    for name in ("serve", "run_turn", "decide", "take_exit", "complete"):
        setattr(drv, name, Mock(side_effect=AssertionError("forbidden controller call: " + name)))
    return drv


def receipt(word="progressed", *, row=None, before=3, repair=False, replan=False,
            caller=None, target=None, observe=True):
    caller = caller or str(uuid.uuid4())
    target = target or str(uuid.uuid4())
    if observe is False:
        observed = None
    elif row is None:
        observed = {"schema_version": 1, "ok": True, "rows": [],
                    "hints": [], "pointers": []}
    else:
        observed = {"schema_version": 1, "ok": True, "rows": [copy.deepcopy(row)],
                    "hints": [], "pointers": []}
    return {
        "schema_version": 1,
        "caller": caller,
        "target": target,
        "advance_word": word,
        "target_seq_before": before,
        "observe": observed,
        "readback": copy.deepcopy(row) if row is not None else None,
        "repair_required": repair,
        "replan_required": replan,
    }


def pure_disposition_checks():
    caller = str(uuid.uuid4())
    target = str(uuid.uuid4())
    row = {
        "session_id": target,
        "status": "ready",
        "is_terminal": False,
        "last_event_seq": 4,
        "last_event_type": "steer/injected",
        "pending_human": False,
        "cancel_pending": False,
    }
    check("controller_disposition_run_now",
          decide_controller_disposition(receipt(caller=caller, target=target, row=row)) == "run_now")
    check("controller_disposition_wait",
          decide_controller_disposition(receipt("waiting", caller=caller, target=target,
                                                 observe=False)) == "wait")
    human = copy.deepcopy(row)
    human["pending_human"] = True
    check("controller_disposition_user_action_required",
          decide_controller_disposition(receipt(caller=caller, target=target, row=human))
          == "user_action_required")
    check("controller_disposition_repair",
          decide_controller_disposition(receipt("stale", caller=caller, target=target,
                                                 observe=False)) == "repair")
    check("controller_disposition_replan",
          decide_controller_disposition(receipt(caller=caller, target=target, row=row,
                                                 replan=True)) == "replan")
    terminal = copy.deepcopy(row)
    terminal["status"] = "completed"
    check("controller_disposition_terminal",
          decide_controller_disposition(receipt(caller=caller, target=target, row=terminal))
          == "terminal")

    bad = receipt(caller=caller, target=target, row=row)
    bad["repair_required"] = True
    bad["observe"]["rows"][0]["status"] = "completed"
    bad["readback"]["status"] = "completed"
    check("controller_priority_repair_over_terminal",
          decide_controller_disposition(bad) == "repair")
    bad = receipt(caller=caller, target=target, row=human)
    bad["replan_required"] = True
    bad["readback"]["status"] = "completed"
    bad["observe"]["rows"][0]["status"] = "completed"
    check("controller_priority_terminal_over_human",
          decide_controller_disposition(bad) == "terminal")
    bad = receipt(caller=caller, target=target, row=human)
    bad["replan_required"] = True
    check("controller_priority_human_over_replan",
          decide_controller_disposition(bad) == "user_action_required")
    bad = receipt(caller=caller, target=target, row=row, replan=True)
    check("controller_priority_replan_over_run_now",
          decide_controller_disposition(bad) == "replan")
    cancel = copy.deepcopy(row)
    cancel["cancel_pending"] = True
    check("controller_priority_cancel_pending_ignored",
          decide_controller_disposition(receipt(caller=caller, target=target, row=cancel))
          == "run_now")

    malformed = {"not": "an object"}
    try:
        decide_controller_disposition(malformed)
    except ValueError as exc:
        check("controller_disposition_unknown_shape", str(exc) == "controller receipt keys", exc)
    else:
        check("controller_disposition_unknown_shape", False, "no ValueError")
    unknown = receipt(caller=caller, target=target, row=row)
    unknown["advance_word"] = "other"
    try:
        decide_controller_disposition(unknown)
    except ValueError as exc:
        check("controller_disposition_unknown_advance_word",
              str(exc) == "controller receipt advance_word", exc)
    else:
        check("controller_disposition_unknown_advance_word", False, "no ValueError")


def expect_error(label, call, message):
    try:
        call()
    except ValueError as exc:
        check(label, str(exc) == message, str(exc))
    else:
        check(label, False, "missing ValueError")


def receipt_boundary_checks():
    target = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    row = {"session_id": target, "status": "ready", "is_terminal": False,
           "last_event_seq": 4, "last_event_type": "steer/injected",
           "pending_human": False, "cancel_pending": False}
    valid = receipt(target=target, row=row)
    for value in (None, [], 1, "object"):
        expect_error("controller_disposition_unknown_shape",
                     lambda: decide_controller_disposition(value),
                     "controller receipt must be an object")
    for field, values, message in (
        ("schema_version", (True, 1.0, 0, 2, "1", None), "schema_version must be 1"),
        ("caller", (target.upper(), "bad", uuid.UUID(target), None), "caller must be canonical uuid"),
        ("target", (target.upper(), "{" + target + "}", target.replace("-", ""), None),
         "target must be canonical uuid"),
        ("advance_word", (None, [], {}, "other"), "advance_word"),
        ("target_seq_before", (True, -2, 1.0, "1", None), "target_seq_before"),
        ("repair_required", (0, 1, None, "false"), "repair_required"),
        ("replan_required", (0, 1, None, "false"), "replan_required"),
    ):
        for value in values:
            bad = copy.deepcopy(valid)
            bad[field] = value
            expect_error("controller_receipt_invalid_" + field,
                         lambda: decide_controller_disposition(bad), "controller receipt " + message)
    for field in valid:
        bad = copy.deepcopy(valid)
        del bad[field]
        expect_error("controller_receipt_missing_key", lambda: decide_controller_disposition(bad),
                     "controller receipt keys")
    bad = dict(valid, disposition="run_now")
    expect_error("controller_receipt_disposition_not_input", lambda: decide_controller_disposition(bad),
                 "controller receipt keys")
    for field, value in (("schema_version", True), ("schema_version", 1.0), ("ok", 1),
                         ("rows", {}), ("hints", None), ("pointers", {}),
                         ("reason", "shape"), ("extra", None)):
        bad = copy.deepcopy(valid)
        bad["observe"][field] = value
        expect_error("controller_receipt_observe_shape", lambda: decide_controller_disposition(bad),
                     "controller receipt observe shape")
    for field, value in (("session_id", target.upper()), ("status", 1), ("is_terminal", 1),
                         ("last_event_seq", True), ("last_event_seq", "4"),
                         ("last_event_type", []), ("pending_human", 1),
                         ("cancel_pending", None), ("extra", False)):
        bad = copy.deepcopy(valid)
        bad["readback"][field] = value
        expect_error("controller_receipt_readback_shape", lambda: decide_controller_disposition(bad),
                     "controller receipt readback shape")
    for word in ("waiting", "terminal", "stale"):
        bad = copy.deepcopy(valid)
        bad["advance_word"] = word
        expect_error("controller_receipt_nonprogressed_readback",
                     lambda: decide_controller_disposition(bad),
                     "controller receipt observe/readback mismatch")
    for field in ("observe", "readback"):
        bad = copy.deepcopy(valid)
        bad[field] = None
        expect_error("controller_receipt_observe_readback_mismatch",
                     lambda: decide_controller_disposition(bad),
                     "controller receipt observe/readback mismatch")
    for rows in ([], [{}, {}], [None], [{"session_id": target}]):
        bad = copy.deepcopy(valid)
        bad["observe"]["rows"] = rows
        bad["readback"] = None
        check("controller_receipt_unavailable_rows", decide_controller_disposition(bad) == "repair")
    for reason in (False, True):
        bad = copy.deepcopy(valid)
        bad["observe"]["ok"] = False
        bad["readback"] = None
        if reason:
            bad["observe"]["reason"] = "shape"
        check("controller_receipt_observe_failed", decide_controller_disposition(bad) == "repair")
    for mutate in (lambda r: r["readback"].update(last_event_seq=3),
                   lambda r: r["readback"].update(session_id=str(uuid.uuid4())),
                   lambda r: r["observe"]["rows"][0].update(status="waiting")):
        bad = copy.deepcopy(valid)
        mutate(bad)
        check("controller_receipt_semantic_repair", decide_controller_disposition(bad) == "repair")
    for field, value in (("session_id", str(uuid.uuid4())),
                         ("last_event_seq", valid["target_seq_before"]),
                         ("last_event_seq", valid["target_seq_before"] - 1)):
        bad = copy.deepcopy(valid)
        bad["readback"][field] = value
        bad["observe"]["rows"][0][field] = value
        check("controller_receipt_identity_sequence_repair",
              decide_controller_disposition(bad) == "repair")
    for status in ("ready", "waiting", "blocked_unknown"):
        candidate = dict(row, status=status)
        check("controller_receipt_nonterminal_status",
              decide_controller_disposition(receipt(target=target, row=candidate)) == "run_now")
    for status in ("completed", "failed", "cancelled"):
        candidate = dict(row, status=status, pending_human=True)
        check("controller_receipt_terminal_status",
              decide_controller_disposition(receipt(target=target, row=candidate, replan=True)) == "terminal")
    check("controller_receipt_terminal_flag",
          decide_controller_disposition(receipt(target=target, row=dict(row, is_terminal=True))) == "terminal")
    check("controller_receipt_terminal_word",
          decide_controller_disposition(receipt("terminal", observe=False)) == "terminal")
    check("controller_receipt_wait_replan",
          decide_controller_disposition(receipt("waiting", observe=False, replan=True)) == "replan")
    candidate = copy.deepcopy(valid)
    candidate["observe"]["rows"][0].update(ordinal=1, parent_session_id=valid["caller"])
    unchanged = copy.deepcopy(candidate)
    check("controller_receipt_extra_row_fields", decide_controller_disposition(candidate) == "run_now")
    check("controller_receipt_pure_no_mutation", candidate == unchanged)


def driver_boundary_checks():
    sid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    target = "ffffffff-aaaa-4bbb-8ccc-dddddddddddd"
    def stub(word="waiting", observed=None):
        drv = LoopDriver(Mock(side_effect=AssertionError("no connection allowed")))
        drv.advance = Mock(return_value=word)
        drv._read = Mock(return_value=[(observed,)])
        for name in ("serve", "run_turn", "decide", "take_exit", "complete"):
            setattr(drv, name, Mock(side_effect=AssertionError("forbidden controller call: " + name)))
        return drv
    for actor, observed_target, seq in ((None, target, -1), (sid.upper(), target, -1),
                                       (sid, "bad", -1), (sid, target, True),
                                       (sid, target, -2), (sid, target, "1")):
        drv = stub()
        try:
            drv.run_controller_once(actor, observed_target, target_seq_before=seq)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid input accepted")
        check("controller_driver_invalid_zero_sql", not drv.advance.called
              and not drv._read.called and not drv._connect.called)
    for word in ("waiting", "terminal", "stale"):
        drv = stub(word)
        result = drv.run_controller_once(sid, target, target_seq_before=-1)
        check("controller_driver_nonprogressed_no_observe", drv.advance.call_count == 1
              and drv.advance.call_args.args == (sid,) and not drv._read.called
              and result["observe"] is None and result["readback"] is None)
    for word in (None, "other", 1):
        drv = stub(word)
        expect_error("controller_driver_unknown_word",
                     lambda: drv.run_controller_once(sid, target, target_seq_before=-1),
                     "controller: unsupported advance word: " + str(word))
        check("controller_driver_unknown_no_observe", drv.advance.call_count == 1 and not drv._read.called)
    for failing in ("advance", "_read"):
        drv = stub("progressed")
        failure = RuntimeError("controller test " + failing)
        getattr(drv, failing).side_effect = failure
        try:
            drv.run_controller_once(sid, target, snap={"envelope": {}}, target_seq_before=-1)
        except RuntimeError as exc:
            check("controller_driver_exception_propagates", exc is failure)
        else:
            raise AssertionError("failure swallowed")
        check("controller_driver_exception_no_retry", drv.advance.call_count == 1
              and drv._read.call_count == (1 if failing == "_read" else 0))
    observed = {"schema_version": 1, "ok": True, "rows": [], "hints": [], "pointers": []}
    drv = stub("progressed", observed)
    check("controller_driver_empty_readback_repair",
          drv.run_controller_once(sid, target, snap={}, target_seq_before=-1)["disposition"] == "repair")


def static_controller_checks():
    source = inspect.getsource(LoopDriver.run_controller_once)
    banned_calls = ("serve", "run_turn", "decide", "decide_exit", "take_exit", "complete", "tick")
    tree = ast.parse(textwrap.dedent(source))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    check("controller_static_no_legacy_calls", not called.intersection(banned_calls))
    test_tree = ast.parse(Path(__file__).read_text())
    imports = {name.name for node in ast.walk(test_tree) if isinstance(node, ast.Import) for name in node.names}
    imports |= {node.module for node in ast.walk(test_tree) if isinstance(node, ast.ImportFrom)}
    forbidden_imports = {"sock" + "et", "url" + "lib", "http" + ".client",
                         "req" + "uests", "http" + "x"}
    check("controller_static_no_network_imports",
          not any(name == banned or name.startswith(banned + ".")
                  for name in imports for banned in forbidden_imports))
    check("controller_static_no_alternate_judgment",
          "Fake" + "LLM" not in Path(__file__).read_text()
          and "tool" + "_calls" not in Path(__file__).read_text())


def happy_path(server):
    conn = connect(server)
    cur = conn.cursor()
    root, child, parsed, _ = prepare_chain(cur, "agentctl_steer", True)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s", (root,))
    before = q1(cur, "SELECT coalesce(max(seq), -1) FROM events WHERE session_id = %s", (child,))
    conn.commit()
    probe = connect(server)
    pcur = probe.cursor()
    pcur.execute("SELECT v13_control_authorized(%s::uuid, %s::uuid), "
                 "(SELECT parent_session_id FROM sessions WHERE session_id=%s)",
                 (root, child, child))
    auth, parent = pcur.fetchone()
    probe.close()
    check("controller_chain_authorized", auth is True and str(parent) == root, (auth, parent, root, child))
    drv = driver(server, conn)
    result = drv.run_controller_once(root, child, snap=parsed, target_seq_before=before)
    check("controller_chain_progressed", result["advance_word"] == "progressed", result)
    check("controller_chain_no_serve", all(name != "serve" for name, _ in drv.calls), drv.calls)
    check("controller_chain_no_complete", ("v13_complete", root) not in drv.calls, drv.calls)
    check("controller_chain_one_advance", drv.calls == [("v13_advance", root)]
          and drv.advance.call_count == 1 and drv.advance.call_args.args[1] is parsed, drv.calls)
    check("controller_chain_one_observe", drv._read.call_count == 1
          and drv._read.call_args.args[0] == "SELECT public.v13_agentctl_observe(%s::uuid, %s::jsonb)"
          and drv._read.call_args.args[1][0] == root
          and json.loads(drv._read.call_args.args[1][1]) == {"ids": [child], "hint": False})
    check("controller_chain_idle", drv.conn.get_transaction_status() == TRANSACTION_STATUS_IDLE
          and drv.observe_boundaries == [TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_IDLE])
    cur = conn.cursor()
    route = as_obj(q1(cur, "SELECT payload FROM events WHERE session_id = %s "
                      "AND type = 'turn/route' ORDER BY seq DESC LIMIT 1", (root,)))
    check("controller_chain_route_sql",
          route.get("action") == "sql" and route.get("tool") == "agentctl_steer", route)
    cur.execute("SELECT status, error, kind FROM effects WHERE session_id = %s "
                "AND tool_name = 'agentctl_steer'", (root,))
    effect_rows = cur.fetchall()
    check("controller_chain_tool_effect",
          len(effect_rows) == 1 and effect_rows[0] == ("succeeded", None, "tool"), effect_rows)
    observe = result["observe"]
    check("controller_chain_observe_ok",
          observe["schema_version"] == 1 and observe["ok"] is True
          and isinstance(observe["rows"], list)
          and isinstance(observe["hints"], list)
          and isinstance(observe["pointers"], list), observe)
    row = result["readback"]
    check("controller_chain_target_match", row["session_id"] == child, row)
    check("controller_chain_last_event_type", row["last_event_type"] == "steer/injected", row)
    check("controller_chain_last_event_seq_moved", row["last_event_seq"] > before, row)
    text = q1(cur, "SELECT payload->>'text' FROM events WHERE session_id = %s "
               "AND type = 'steer/injected' AND seq > %s ORDER BY seq DESC LIMIT 1",
               (child, before))
    check("controller_chain_steer_text", text == "steer-text", text)
    check("controller_chain_disposition",
          result["disposition"] == "run_now"
          and decide_controller_disposition({k: v for k, v in result.items()
                                             if k != "disposition"}) == "run_now", result)
    drv.close()
    conn.close()


def waiting_path(server):
    conn = connect(server)
    cur = conn.cursor()
    root, child, parsed, _ = prepare_chain(cur, "agentctl_steer", False)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s", (root,))
    target_before = q1(cur, "SELECT coalesce(max(seq), -1) FROM events WHERE session_id = %s", (child,))
    conn.commit()
    drv = driver(server, conn)
    result = drv.run_controller_once(root, child, snap=parsed, target_seq_before=target_before)
    check("controller_waiting_word", result["advance_word"] == "waiting", result)
    check("controller_waiting_disposition", result["disposition"] == "wait", result)
    cur = conn.cursor()
    reason = q1(cur, "SELECT request->>'reason' FROM effects WHERE session_id = %s "
                 "AND kind = 'human' AND status = 'ready'", (root,))
    check("controller_waiting_triage", reason == "triage_fail_closed", reason)
    check("controller_waiting_no_observe", result["observe"] is None
          and result["readback"] is None and drv._read.call_count == 0, result)
    check("controller_waiting_no_serve", all(name != "serve" for name, _ in drv.calls), drv.calls)
    check("controller_waiting_no_complete", all(name != "v13_complete" for name, _ in drv.calls), drv.calls)
    drv.close()
    conn.close()


def stale_path(server):
    conn = connect(server)
    cur = conn.cursor()
    parent, child = controller_pair(cur)
    append_user(cur, child, "watermark")
    eid = enqueue_human(cur, child, "wm-ref")
    shrink_catalog(cur, ["spawn_subsession"])
    set_mock(cur, mock_from_needed(cur, child, intent={"type": "choice", "choice": "sql_answer",
                                                        "probabilities": {"sql_answer": 0.9},
                                                        "confidence": 0.9}))
    cur.execute("SELECT v13_parse(%s)", (child,))
    parsed = as_obj(cur.fetchone()[0])
    seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    cur.execute("SELECT request::text, request_hash, attempt_no, fence, lease_owner, "
                "lease_until::text FROM effects WHERE effect_id = %s", (eid,))
    tokens = cur.fetchone()
    call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "watermark steer"})
    target_before = q1(cur, "SELECT coalesce(max(seq), -1) FROM events WHERE session_id = %s", (child,))
    before = snapshot_window(cur)
    conn.commit()
    drv = driver(server, conn)
    result = drv.run_controller_once(child, child, snap=parsed, target_seq_before=target_before)
    after = snapshot_window(cur)
    check("controller_stale_word", result["advance_word"] == "stale", result)
    check("controller_stale_disposition", result["disposition"] == "repair", result)
    check("controller_stale_supplied_snapshot",
          drv.advance.call_count == 1 and drv.advance.call_args.args[1] is parsed
          and int(parsed["snap"]["max_event_seq"]) < target_before, parsed)
    check("controller_stale_no_observe", result["observe"] is None
          and result["readback"] is None and drv._read.call_count == 0, result)
    check("controller_stale_no_serve", all(name != "serve" for name, _ in drv.calls), drv.calls)
    check("controller_stale_no_complete", all(name != "v13_complete" for name, _ in drv.calls), drv.calls)
    check("controller_stale_zero_write", after == before, (before, after))
    check("controller_stale_seq_plus_one",
          q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,)) == seq + 1, seq)
    cur.execute("SELECT request::text, request_hash, attempt_no, fence, lease_owner, "
                "lease_until::text FROM effects WHERE effect_id = %s", (eid,))
    check("controller_stale_tokens", cur.fetchone() == tokens, tokens)
    drv.close()
    conn.close()


def main() -> int:
    global CREATED, MODEL
    server = get_server()
    try:
        pure_disposition_checks()
        receipt_boundary_checks()
        driver_boundary_checks()
        static_controller_checks()
        if DB.startswith("agent_v13_"):
            raise AssertionError("illegal database name")
        admin = psycopg2.connect(server.get_uri("postgres"))
        try:
            cur = admin.cursor()
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
            if cur.fetchone() is not None:
                raise AssertionError("database exists, refusing to drop: " + DB)
        finally:
            admin.close()
        run_psql(server, "postgres", f'CREATE DATABASE "{DB}";')
        CREATED = True
        load_stage(server, DB, "agentctl_verbs")
        # The database-global judgment cache includes model in its request hash.
        # Separate mock namespaces keep UUID-bearing fixture answers isolated,
        # without deleting the immutable cache or loading the SQL a second time.
        for label, scenario in (("waiting", waiting_path),
                                ("happy", happy_path),
                                ("stale", stale_path)):
            MODEL = "jev-mock-controller-" + label
            scenario(server)
        print(f"[PASS] controller vertical checks: {N}")
        return 0
    finally:
        if CREATED:
            run_psql(server, "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
            print("[dropped]", DB)
            CREATED = False


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise
