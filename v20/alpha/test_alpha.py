"""v20 alpha gate. One process, one database, no network and no real model.

Run from the repository root: uv run python v20/alpha/test_alpha.py
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
import threading
import time
import traceback
from uuid import uuid4

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, parse_dsn
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import v20.alpha.host as hostmod
import v20.alpha.setup_db as setup
from v20.alpha.control import CHANNEL, Control, ControlError
from v20.alpha.disposition import decide
from v20.alpha.host import Host
from v20.alpha.setup_db import WORKER_ROLE, local_dsn
from v20.alpha.tools import echo
from v20.alpha.worker import (
    FakeWorker,
    InTransaction,
    TurnReceipt,
    WorkerRequest,
    assert_outside_transaction,
    compute_input_digest,
    validate_receipt,
)

ACTOR = "alpha"
TABLES = {
    "v20_runtime_catalog",
    "v20_sessions",
    "v20_session_profiles",
    "v20_session_provider_handles",
    "v20_runs",
    "v20_epochs",
    "v20_operations",
    "v20_provider_handle_attempts",
    "v20_turns",
    "v20_tool_invocations",
    "v20_events",
    "v20_transcript_turns",
    "v20_transcript_activities",
}
UNKNOWN = (
    "admit_workflow_run", "handoff", "add_step", "open_workflow_run", "bind_plan",
    "export_artifact", "retire_artifact", "get_log",
)

DSN = ""
CONTROLS: list[Control] = []


def uid() -> str:
    return str(uuid4())


def open_control(kind: type[Control] = Control) -> Control:
    ctrl = kind(DSN)
    CONTROLS.append(ctrl)
    return ctrl


def close_controls() -> None:
    while CONTROLS:
        ctrl = CONTROLS.pop()
        try:
            ctrl.close()
        except Exception:
            pass


def read(ctrl: Control, statement: str, args: tuple = ()):
    with ctrl.conn.cursor() as cur:
        cur.execute(statement, args)
        found = cur.fetchall()
    ctrl.conn.commit()
    return found


def one(ctrl: Control, statement: str, args: tuple = ()):
    found = read(ctrl, statement, args)
    assert len(found) == 1, (statement, len(found))
    return found[0]


def j(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def expect(code: str, fn) -> ControlError:
    try:
        fn()
    except ControlError as exc:
        assert exc.code == code, exc.code
        return exc
    raise AssertionError(f"expected {code}")


def do_start(ctrl: Control, text: str = "hello", **extra):
    payload = {"request_id": uid(), "input_message": text}
    payload.update(extra)
    return ctrl.execute("start", ACTOR, payload)


def do_admit(ctrl: Control, started: dict, kind: str):
    return ctrl.execute("admit_turn", ACTOR, {
        "request_id": uid(),
        "run_id": started["run_id"],
        "epoch_id": started["epoch_id"],
        "owner_generation": started["owner_generation"],
        "input_kind": kind,
        "instruction": started["input_message"],
        "transcript_turn_id": started["transcript_turn_id"],
    })


def poll(ctrl: Control, run_id: str) -> dict:
    return ctrl.execute("poll", ACTOR, {"run_id": run_id})


def request_for(snap: dict, turn: dict, handle=None):
    initial = j(turn["receipt"]) or {}
    kind = initial["input_kind"]
    driving = snap["driving"]
    if kind == "parent_response":
        instruction, response, continuation = None, driving["input_message"], False
        results: list = []
    elif kind == "host_continue":
        instruction, response, continuation = driving["input_message"], None, True
        results = list(snap["tool_results"])
    else:
        instruction, response, continuation = initial.get("instruction"), None, False
        results = []
    material = {
        "base_revision": snap["revision"],
        "continuation": continuation,
        "input_kind": kind,
        "instruction": instruction,
        "provider_handle": handle,
        "response": response,
        "run_id": snap["run_id"],
        "tool_results": results,
        "turn_id": turn["turn_id"],
    }
    return WorkerRequest(
        run_id=snap["run_id"],
        turn_id=turn["turn_id"],
        base_revision=snap["revision"],
        input_kind=kind,
        input_digest=compute_input_digest(material),
        instruction=instruction,
        response=response,
        continuation=continuation,
        provider_handle=handle,
        tool_results=results,
    )


def pending_turn(ctrl: Control, run_id: str):
    snap = poll(ctrl, run_id)
    assert snap["pending_turns"], snap
    return snap, snap["pending_turns"][0]


def finish(text: str = "hello", script: str = "default", ctrl: Control | None = None):
    ctrl = ctrl or open_control()
    worker = FakeWorker(script)
    payload = {"request_id": uid(), "input_message": text}
    result = Host(ctrl, worker).drive("start", ACTOR, payload)
    return ctrl, worker, result, payload


def completed_receipt(request):
    receipt = TurnReceipt(
        schema_version=1,
        turn_id=request.turn_id,
        run_id=request.run_id,
        base_revision=request.base_revision,
        input_kind=request.input_kind,
        input_digest=request.input_digest,
        outcome="completed",
        result={"ok": True},
    )
    validate_receipt(receipt, request)
    return receipt


def park_needs_input(ctrl: Control, text: str = "ask"):
    """Leave the expects_handle row completed and still handle-pending."""
    started = do_start(ctrl, text)
    do_admit(ctrl, started, "initial")
    snap, turn = pending_turn(ctrl, started["run_id"])
    receipt = FakeWorker("needs_input")(request_for(snap, turn))
    body = receipt.as_dict()
    body["request_id"] = turn["request_id"]
    ctrl.execute("accept_turn_receipt", ACTOR, {"request_id": turn["request_id"], "receipt": body})
    published = ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"],
        "mode": "final",
        "outcome": "waiting_for_input",
        "interaction": receipt.input_request,
        "result": receipt.result,
        "preview": "waiting",
    })
    return started, published


def sql_error(ctrl: Control, statement: str, args: tuple = ()):
    try:
        with ctrl.conn.cursor() as cur:
            cur.execute(statement, args)
        ctrl.conn.commit()
    except psycopg2.Error as exc:
        ctrl.conn.rollback()
        return exc
    return None


# --- identity -----------------------------------------------------------------


def unix_socket_only():
    dsn = local_dsn()
    host = parse_dsn(dsn).get("host", "")
    assert host.startswith("/"), dsn
    ctrl = open_control()
    assert ctrl.conn.get_dsn_parameters().get("host", "").startswith("/")
    original = setup.get_server

    class Tcp:
        def get_uri(self, database):
            return "dbname=postgres host=127.0.0.1 port=1"

    setup.get_server = lambda: Tcp()
    try:
        try:
            local_dsn()
        except ValueError:
            return
        raise AssertionError("tcp dsn was accepted")
    finally:
        setup.get_server = original


def worker_role_cannot_connect():
    try:
        conn = psycopg2.connect(local_dsn(user=WORKER_ROLE))
    except psycopg2.OperationalError:
        return
    conn.close()
    raise AssertionError("worker role connected")


def control_role_sees_other_backend_pid():
    first = open_control()
    second = open_control()
    pid = second.conn.get_backend_pid()
    found = read(first, "SELECT pid FROM pg_stat_activity WHERE pid = %s", (pid,))
    assert found and found[0]["pid"] == pid


def run_id_aliases_session():
    ctrl = open_control()
    started = do_start(ctrl, "alias")
    assert started["run_id"] == started["session_id"]
    definition = one(ctrl, """
        SELECT pg_get_constraintdef(oid) AS def
        FROM pg_constraint WHERE conname = 'v20_runs_id_aliases_session'
    """)
    assert "run_id = session_id" in definition["def"]
    session_id = uid()
    assert sql_error(ctrl, """
        INSERT INTO v20_sessions (
            session_id, owning_runtime_id, owning_runtime_generation, registration_generation,
            last_epoch_ordinal, continuity_generation, state, resumable, revision, updated_at)
        VALUES (%s, 'alpha', 1, 1, 1, 1, 'active', true, 1, clock_timestamp())
    """, (session_id,)) is None
    error = sql_error(ctrl, """
        INSERT INTO v20_runs (run_id, session_id, revision, status, owner_generation, updated_at)
        VALUES (%s, %s, 1, 'running', 1, clock_timestamp())
    """, (uid(), session_id))
    assert error is not None
    assert not read(ctrl, "SELECT 1 FROM v20_runs WHERE run_id <> session_id")


def sessions_have_no_workflow_run_id():
    ctrl = open_control()
    columns = {row["column_name"] for row in read(ctrl, """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'v20_sessions'
    """)}
    assert "workflow_run_id" not in columns


def no_workflow_or_plan_or_artifact_tables():
    ctrl = open_control()
    tables = {row["table_name"] for row in read(ctrl, """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    """)}
    assert tables == TABLES
    catalog = one(ctrl, "SELECT profile_identifier, metadata_schema_version FROM v20_runtime_catalog")
    assert catalog["profile_identifier"] == "alpha"
    assert catalog["metadata_schema_version"] == 1


def child_parent_session():
    ctrl = open_control()
    parent = do_start(ctrl, "parent")
    child = do_start(ctrl, "child-text", parent_session_id=parent["session_id"])
    assert child["session_id"] != parent["session_id"]
    assert child["run_id"] == child["session_id"]
    assert child["parent_session_id"] == parent["session_id"]
    turn = do_admit(ctrl, child, "parent_instruction")
    receipt = j(one(ctrl, "SELECT receipt FROM v20_turns WHERE request_id = %s", (turn["request_id"],))["receipt"])
    assert receipt["input_kind"] == "parent_instruction"
    expect("Rejected", lambda: do_admit(ctrl, child, "initial"))


def unknown_parent_rejected():
    ctrl = open_control()
    before = one(ctrl, "SELECT count(*) AS n FROM v20_sessions")["n"]
    expect("Rejected", lambda: do_start(ctrl, "orphan", parent_session_id=uid()))
    after = one(ctrl, "SELECT count(*) AS n FROM v20_sessions")["n"]
    assert before == after


# --- vertical -----------------------------------------------------------------


def start_is_running_and_pending():
    ctrl = open_control()
    started = do_start(ctrl, "pending-text")
    assert started["status"] == "running"
    assert started["operation_status"] == "pending"
    assert started["expects_handle"] is True
    assert started["revision"] == 1
    assert one(
        ctrl, "SELECT input_retained FROM v20_operations WHERE request_id = %s", (started["request_id"],)
    )["input_retained"] is False
    assert not read(ctrl, "SELECT 1 FROM v20_turns WHERE run_id = %s", (started["run_id"],))
    snap = poll(ctrl, started["run_id"])
    assert snap["revision"] == 1
    assert snap["status"] == "running"
    before = one(ctrl, "SELECT count(*) AS n FROM v20_events")["n"]
    for verb in UNKNOWN:
        expect("UnknownVerb", lambda verb=verb: ctrl.execute(verb, ACTOR, {"request_id": uid()}))
    expect("Rejected", lambda: ctrl.execute("start", ACTOR, {
        "request_id": uid(), "input_message": "x", "input_artifact_digest": "aa",
    }))
    expect("Rejected", lambda: ctrl.execute("start", ACTOR, {"request_id": uid(), "input_message": "  "}))
    after = one(ctrl, "SELECT count(*) AS n FROM v20_events")["n"]
    assert before == after


def first_turn_accepted_before_tool():
    ctrl, _worker, result, payload = finish("order-check")
    assert result["disposition"] == "stop"
    kinds = [row["kind"] for row in read(ctrl, """
        SELECT event_id, kind FROM v20_events WHERE run_id = %s ORDER BY event_id
    """, (result["run_id"],))]
    assert kinds.index("accept_turn_receipt") < kinds.index("admit_tool")


def preview_keeps_operation_pending():
    ctrl = open_control()
    started = do_start(ctrl, "preview")
    published = ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"], "mode": "progress", "snapshot_seq": 1, "preview": "one",
    })
    assert published["revision"] == 2
    assert published["operation_status"] == "pending"
    assert published["handle_state"] == "pending"
    assert published["status"] == "running"
    snap = poll(ctrl, started["run_id"])
    assert snap["preview"] == "one"
    assert snap["driving"]["snapshot_seq"] == 1
    turn = do_admit(ctrl, started, "initial")
    expect("Rejected", lambda: ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": turn["request_id"], "mode": "final", "outcome": "completed",
        "preview": "no", "no_handle": True,
    }))
    expect("Rejected", lambda: ctrl.execute("record_provider_handle", ACTOR, {
        "request_id": turn["request_id"], "handle": {"tok": "no"},
    }))
    assert one(ctrl, "SELECT status FROM v20_operations WHERE request_id = %s", (turn["request_id"],))["status"] == "pending"
    assert one(ctrl, "SELECT status FROM v20_turns WHERE request_id = %s", (turn["request_id"],))["status"] == "admitted"
    assert poll(ctrl, started["run_id"])["status"] == "running"
    assert one(ctrl, """
        SELECT count(*) AS n FROM v20_events WHERE run_id = %s AND kind = 'archive'
    """, (started["run_id"],))["n"] == 0


def preview_retry_same_snapshot_seq():
    ctrl = open_control()
    started = do_start(ctrl, "retry")
    ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"], "mode": "progress", "snapshot_seq": 1, "preview": "one",
    })
    again = ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"], "mode": "progress", "snapshot_seq": 1, "preview": "other",
    })
    assert again["revision"] == 2
    assert poll(ctrl, started["run_id"])["preview"] == "one"
    assert one(ctrl, """
        SELECT count(*) AS n FROM v20_events WHERE run_id = %s AND kind = 'publish_snapshot'
    """, (started["run_id"],))["n"] == 1


def smaller_snapshot_seq_does_not_overwrite():
    ctrl = open_control()
    started = do_start(ctrl, "smaller")
    ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"], "mode": "progress", "snapshot_seq": 2, "preview": "two",
    })
    again = ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"], "mode": "progress", "snapshot_seq": 1, "preview": "one",
    })
    assert again["revision"] == 2
    snap = poll(ctrl, started["run_id"])
    assert snap["preview"] == "two"
    assert snap["driving"]["snapshot_seq"] == 2


def echo_result_visible_on_next_turn():
    token = "echo-token-9"
    ctrl, worker, result, _payload = finish(token)
    assert result["disposition"] == "stop"
    assert len(worker.calls) == 2
    assert worker.calls[1].input_kind == "host_continue"
    assert worker.calls[1].tool_results[0]["output"]["text"] == token
    stored = j(one(ctrl, "SELECT result FROM v20_operations WHERE request_id = %s", (result["request_id"],))["result"])
    assert stored["result"]["saw"] == token


def tool_receipt_does_not_complete_run():
    ctrl = open_control()
    payload = {"request_id": uid(), "input_message": "tool-stop"}

    def worker(request):
        assert_outside_transaction()
        if request.tool_results:
            raise RuntimeError("stop after tools")
        return FakeWorker()(request)

    try:
        Host(ctrl, worker).drive("start", ACTOR, payload)
    except RuntimeError as exc:
        assert str(exc) == "stop after tools"
    else:
        raise AssertionError("continuation ran before the assertion")
    row = one(ctrl, """
        SELECT r.run_id, r.status, r.revision, o.status AS operation_status
        FROM v20_operations o JOIN v20_epochs e ON e.epoch_id = o.epoch_id
        JOIN v20_runs r ON r.run_id = e.run_id
        WHERE o.request_id = %s
    """, (payload["request_id"],))
    assert row["status"] == "running"
    assert row["operation_status"] == "pending"
    assert row["revision"] == 2
    tool = one(ctrl, """
        SELECT o.status, i.status AS invocation_status
        FROM v20_tool_invocations i JOIN v20_operations o ON o.request_id = i.request_id
        WHERE i.run_id = %s
    """, (row["run_id"],))
    assert tool["status"] == "completed"
    assert tool["invocation_status"] == "completed"


def second_tool_does_not_block_first():
    ctrl = open_control()
    started = do_start(ctrl, "two-tools")
    turn = do_admit(ctrl, started, "initial")
    ctrl.execute("accept_turn_receipt", ACTOR, {
        "request_id": turn["request_id"],
        "receipt": {
            "schema_version": 1,
            "turn_id": turn["turn_id"],
            "run_id": started["run_id"],
            "base_revision": started["revision"],
            "input_kind": "initial",
            "input_digest": "ab" * 32,
            "outcome": "progress",
            "result": {"ok": True},
            "tool_calls": [
                {"call_id": 1, "name": "echo", "arguments": {"text": "one"}},
                {"call_id": 2, "name": "echo", "arguments": {"text": "two"}},
            ],
            "request_id": turn["request_id"],
        },
    })
    first = ctrl.execute("admit_tool", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "epoch_id": started["epoch_id"],
        "turn_id": turn["turn_id"], "tool_name": "echo", "arguments": {"text": "one"},
        "owner_generation": started["owner_generation"],
    })
    second = ctrl.execute("admit_tool", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "epoch_id": started["epoch_id"],
        "turn_id": turn["turn_id"], "tool_name": "echo", "arguments": {"text": "two"},
        "owner_generation": started["owner_generation"],
    })
    crossed = ctrl.execute("accept_tool_result", ACTOR, {
        "request_id": first["request_id"], "status": "completed", "output": {"text": "nope"},
        "receipt_request_id": uid(),
    })
    assert crossed["operation_status"] == "pending"
    assert one(ctrl, "SELECT status FROM v20_operations WHERE request_id = %s", (second["request_id"],))["status"] == "pending"
    assert one(ctrl, """
        SELECT count(*) AS n FROM v20_events WHERE run_id = %s AND kind = 'archive'
    """, (started["run_id"],))["n"] == 1
    failed = ctrl.execute("accept_tool_result", ACTOR, {
        "request_id": second["request_id"], "status": "failed", "output": {"error": "no"},
    })
    done = ctrl.execute("accept_tool_result", ACTOR, {
        "request_id": first["request_id"], "status": "completed", "output": {"text": "one"},
    })
    assert failed["operation_status"] == "completed"
    assert done["operation_status"] == "completed"
    assert poll(ctrl, started["run_id"])["status"] == "running"


def bare_progress_twice_fails():
    ctrl, worker, result, _payload = finish("bare", script="bare_progress")
    assert result["disposition"] == "failed"
    assert result["status"] == "failed"
    assert len(worker.calls) == 2
    assert one(ctrl, "SELECT failure_reason FROM v20_runs WHERE run_id = %s", (result["run_id"],))["failure_reason"]


def final_snapshot_dormant_resumable():
    ctrl, _worker, result, payload = finish("final-text")
    assert result["disposition"] == "stop"
    assert result["status"] == "completed"
    assert result["revision"] == 3
    session = one(ctrl, "SELECT state, resumable, revision FROM v20_sessions WHERE session_id = %s", (result["session_id"],))
    assert session["state"] == "dormant"
    assert session["resumable"] is True
    assert session["revision"] == 3
    operation = one(ctrl, """
        SELECT status, handle_state, input_retained FROM v20_operations WHERE request_id = %s
    """, (payload["request_id"],))
    assert operation["status"] == "completed"
    assert operation["handle_state"] == "absent"
    assert operation["input_retained"] is False


def replay_same_request_keeps_result():
    ctrl = open_control()
    payload = {"request_id": uid(), "input_message": "replay"}
    first = ctrl.execute("start", ACTOR, payload)
    second = ctrl.execute("start", ACTOR, payload)
    assert first["request_id"] == second["request_id"]
    assert second["revision"] == 1
    assert one(ctrl, "SELECT count(*) AS n FROM v20_operations WHERE request_id = %s", (payload["request_id"],))["n"] == 1
    published = ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": payload["request_id"], "mode": "final", "outcome": "completed",
        "result": {"kept": True}, "preview": "done", "no_handle": True,
    })
    stored = one(ctrl, "SELECT result, status FROM v20_operations WHERE request_id = %s", (payload["request_id"],))
    again = ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": payload["request_id"], "mode": "final", "outcome": "failed",
        "result": {"kept": False}, "failure_reason": "no", "no_handle": True,
    })
    assert again["revision"] == published["revision"]
    fresh = one(ctrl, "SELECT result, status FROM v20_operations WHERE request_id = %s", (payload["request_id"],))
    assert fresh["status"] == "completed"
    assert j(fresh["result"]) == j(stored["result"])


def replay_digest_mismatch():
    ctrl = open_control()
    request_id = uid()
    ctrl.execute("start", ACTOR, {"request_id": request_id, "input_message": "same"})
    expect("IdempotencyConflict", lambda: ctrl.execute("start", ACTOR, {
        "request_id": request_id, "input_message": "different",
    }))
    assert one(ctrl, "SELECT input_message FROM v20_operations WHERE request_id = %s", (request_id,))["input_message"] == "same"
    assert one(ctrl, "SELECT count(*) AS n FROM v20_operations WHERE request_id = %s", (request_id,))["n"] == 1


def io_outside_transaction():
    ctrl = open_control()
    seen = []
    base = FakeWorker()

    def wrapped(request):
        seen.append(ctrl.conn.get_transaction_status())
        return base(request)

    real = hostmod.run_tool

    def wrapped_tool(name, arguments):
        seen.append(ctrl.conn.get_transaction_status())
        return real(name, arguments)

    hostmod.run_tool = wrapped_tool
    try:
        result = Host(ctrl, wrapped).drive("start", ACTOR, {"request_id": uid(), "input_message": "idle"})
    finally:
        hostmod.run_tool = real
    assert result["disposition"] == "stop"
    assert seen
    assert all(status == TRANSACTION_STATUS_IDLE for status in seen)


def model_call_inside_transaction_rejected():
    ctrl = open_control()
    with ctrl.conn.cursor() as cur:
        cur.execute("SELECT 1")
    assert Control.in_transaction()
    try:
        try:
            FakeWorker()(None)
        except InTransaction:
            pass
        else:
            raise AssertionError("worker ran inside a transaction")
        try:
            echo({"text": "x"})
        except InTransaction:
            pass
        else:
            raise AssertionError("echo ran inside a transaction")
    finally:
        ctrl.conn.rollback()
    assert not Control.in_transaction()


# --- cancel and steer ----------------------------------------------------------


def cancel_then_late_t2_archives_only():
    ctrl = open_control()
    started = do_start(ctrl, "cancel-late")
    turn = do_admit(ctrl, started, "initial")
    ctrl.execute("cancel", ACTOR, {"run_id": started["run_id"]})
    expect("FenceRejected", lambda: ctrl.execute("accept_turn_receipt", ACTOR, {
        "request_id": turn["request_id"],
        "receipt": {
            "schema_version": 1, "outcome": "completed", "run_id": started["run_id"],
            "turn_id": turn["turn_id"], "input_kind": "initial", "result": {"ok": True},
            "request_id": turn["request_id"],
        },
    }))
    operation = one(ctrl, "SELECT status, input_retained FROM v20_operations WHERE request_id = %s", (turn["request_id"],))
    assert operation["status"] == "closed"
    assert operation["input_retained"] is False
    assert poll(ctrl, started["run_id"])["status"] == "cancelled"
    assert one(ctrl, "SELECT count(*) AS n FROM v20_events WHERE run_id = %s AND kind = 'archive'", (started["run_id"],))["n"] >= 1


def complete_then_cancel_stays_completed():
    ctrl, _worker, result, _payload = finish("done-cancel")
    revision = result["revision"]
    cancelled = ctrl.execute("cancel", ACTOR, {"run_id": result["run_id"]})
    assert cancelled["status"] == "completed"
    assert cancelled["revision"] == revision
    assert not read(ctrl, "SELECT 1 FROM v20_events WHERE run_id = %s AND kind = 'cancel'", (result["run_id"],))


def admit_after_cancel_rejected():
    ctrl = open_control()
    started = do_start(ctrl, "no-admit")
    ctrl.execute("cancel", ACTOR, {"run_id": started["run_id"]})
    expect("Rejected", lambda: do_admit(ctrl, started, "initial"))
    assert not read(ctrl, "SELECT 1 FROM v20_turns WHERE run_id = %s", (started["run_id"],))


def steer_from_running_publishes_new_epoch():
    ctrl = open_control()
    started = do_start(ctrl, "steer-me")
    expect("Rejected", lambda: ctrl.execute("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "no",
        "expected_revision": True,
    }))
    steered = ctrl.execute("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "next",
        "expected_revision": started["revision"],
    })
    assert steered["run_id"] == started["run_id"]
    assert steered["session_id"] == started["session_id"]
    assert steered["status"] == "running"
    assert steered["revision"] == 2
    assert steered["operation_status"] == "pending"
    assert steered["expects_handle"] is True
    epochs = read(ctrl, """
        SELECT ordinal, transition_kind, closed_at FROM v20_epochs
        WHERE session_id = %s ORDER BY ordinal
    """, (started["session_id"],))
    assert len(epochs) == 2
    assert epochs[0]["closed_at"] is not None
    assert epochs[1]["ordinal"] == 2
    assert epochs[1]["transition_kind"] == "steering"
    assert epochs[1]["closed_at"] is None
    old = one(ctrl, "SELECT status, handle_state FROM v20_operations WHERE request_id = %s", (started["request_id"],))
    assert old["status"] == "closed"
    assert old["handle_state"] == "absent"


def steer_cas_one_commits_one_conflicts():
    ctrl = open_control()
    started = do_start(ctrl, "cas")
    barrier = threading.Barrier(2)
    results = []

    def attempt(text):
        local = open_control()
        barrier.wait(5)
        try:
            local.execute("steer", ACTOR, {
                "request_id": uid(), "run_id": started["run_id"], "input_message": text,
                "expected_revision": started["revision"],
            })
            results.append("ok")
        except ControlError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=attempt, args=(label,), daemon=True) for label in ("left", "right")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(8)
        assert not thread.is_alive()
    assert sorted(results) == ["RevisionConflict", "ok"]
    assert one(ctrl, "SELECT count(*) AS n FROM v20_epochs WHERE session_id = %s", (started["session_id"],))["n"] == 2


def old_epoch_t2_does_not_overwrite_new_snapshot():
    ctrl = open_control()
    started = do_start(ctrl, "old-t2")
    turn = do_admit(ctrl, started, "initial")
    steered = ctrl.execute("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "fresh",
        "expected_revision": started["revision"],
    })
    ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": steered["request_id"], "mode": "progress", "snapshot_seq": 1, "preview": "new",
    })
    expect("FenceRejected", lambda: ctrl.execute("accept_turn_receipt", ACTOR, {
        "request_id": turn["request_id"],
        "receipt": {
            "schema_version": 1, "outcome": "completed", "run_id": started["run_id"],
            "turn_id": turn["turn_id"], "input_kind": "initial", "result": {"late": True},
            "request_id": turn["request_id"],
        },
    }))
    snap = poll(ctrl, started["run_id"])
    assert snap["preview"] == "new"
    assert snap["driving"]["request_id"] == steered["request_id"]
    assert snap["driving"]["snapshot_seq"] == 1
    assert one(ctrl, "SELECT status FROM v20_operations WHERE request_id = %s", (turn["request_id"],))["status"] == "closed"

    class SteerAfterAccept(Control):
        def execute(self, verb, actor, payload=None):
            result = super().execute(verb, actor, payload)
            if verb == "accept_turn_receipt":
                side = open_control()
                side.execute("steer", ACTOR, {
                    "request_id": uid(),
                    "run_id": result["run_id"],
                    "input_message": "intervened",
                    "expected_revision": result["revision"],
                })
            return result

    racer = open_control(SteerAfterAccept)
    race = Host(racer, FakeWorker()).drive("start", ACTOR, {
        "request_id": uid(), "input_message": "race-steer", "session_id": uid(),
    })
    assert race["disposition"] == "failed"
    raced = poll(racer, race["run_id"])
    assert raced["status"] == "running"
    assert raced["failure_reason"] is None
    assert raced["driving"]["verb"] == "steer"
    assert raced["driving"]["status"] == "pending"
    fresh = one(racer, """
        SELECT o.status, o.result FROM v20_operations o
        WHERE o.request_id = %s
    """, (raced["driving"]["request_id"],))
    assert fresh["status"] == "pending"
    assert fresh["result"] is None
    assert one(racer, """
        SELECT count(*) AS n FROM v20_tool_invocations WHERE run_id = %s
    """, (race["run_id"],))["n"] == 0


def cleanup_hides_and_rejects_resume():
    ctrl = open_control()
    visible = do_start(ctrl, "shown")
    hidden = do_start(ctrl, "hidden")
    first = ctrl.execute("cleanup", ACTOR, {"run_id": hidden["run_id"], "list_hidden": True})
    assert first["status"] == "cancelled"
    events = one(ctrl, "SELECT count(*) AS n FROM v20_events WHERE run_id = %s AND kind = 'cleanup'", (hidden["run_id"],))["n"]
    second = ctrl.execute("cleanup", ACTOR, {"run_id": hidden["run_id"], "list_hidden": True})
    assert second["revision"] == first["revision"]
    assert one(ctrl, "SELECT count(*) AS n FROM v20_events WHERE run_id = %s AND kind = 'cleanup'", (hidden["run_id"],))["n"] == events
    session = one(ctrl, "SELECT state, resumable, list_hidden FROM v20_sessions WHERE session_id = %s", (hidden["session_id"],))
    assert session["state"] == "terminal"
    assert session["resumable"] is False
    assert session["list_hidden"] is True
    listed = {row["session_id"] for row in read(ctrl, "SELECT session_id FROM v20_sessions WHERE NOT list_hidden")}
    assert visible["session_id"] in listed
    assert hidden["session_id"] not in listed
    expect("Rejected", lambda: ctrl.execute("claim_resume", ACTOR, {
        "request_id": uid(), "run_id": hidden["run_id"], "input_message": "no",
    }))
    expect("Rejected", lambda: ctrl.execute("steer", ACTOR, {
        "request_id": uid(), "run_id": hidden["run_id"], "input_message": "no",
        "expected_revision": first["revision"],
    }))


def cleanup_keeps_events_and_transcript():
    ctrl = open_control()
    started = do_start(ctrl, "keep")
    events = [row["event_id"] for row in read(ctrl, "SELECT event_id FROM v20_events WHERE run_id = %s", (started["run_id"],))]
    turns = [row["turn_id"] for row in read(ctrl, "SELECT turn_id FROM v20_transcript_turns WHERE session_id = %s", (started["session_id"],))]
    assert events and turns
    ctrl.execute("cleanup", ACTOR, {"run_id": started["run_id"]})
    left_events = {row["event_id"] for row in read(ctrl, "SELECT event_id FROM v20_events WHERE run_id = %s", (started["run_id"],))}
    left_turns = [row["turn_id"] for row in read(ctrl, "SELECT turn_id FROM v20_transcript_turns WHERE session_id = %s", (started["session_id"],))]
    assert set(events) <= left_events
    assert left_turns == turns


def wait_sees_cleanup_revision():
    owner = open_control()
    started = do_start(owner, "wait-cleanup")

    class Waiter(Control):
        def _after_listen(self, listener):
            owner.execute("cleanup", ACTOR, {"run_id": started["run_id"]})

    waiter = open_control(Waiter)
    began = time.monotonic()
    result = waiter.execute("wait", ACTOR, {
        "run_id": started["run_id"], "since_revision": started["revision"], "timeout_seconds": 1.5,
    })
    assert time.monotonic() - began < 1.0
    assert result["status"] == "cancelled"
    assert result["revision"] > started["revision"]


def steer_after_cancel_publishes():
    ctrl = open_control()
    started = do_start(ctrl, "cancelled-steer")
    cancelled = ctrl.execute("cancel", ACTOR, {"run_id": started["run_id"]})
    result = Host(ctrl, FakeWorker()).drive("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "after",
        "expected_revision": cancelled["revision"],
    })
    assert result["disposition"] == "stop"
    assert result["status"] == "completed"
    epoch = one(ctrl, """
        SELECT ordinal, transition_kind FROM v20_epochs
        WHERE session_id = %s ORDER BY ordinal DESC LIMIT 1
    """, (started["session_id"],))
    assert epoch["ordinal"] == 2
    assert epoch["transition_kind"] == "steering"


# --- recover -------------------------------------------------------------------


def _wait_until_dead(owner: Control, run_id: str) -> dict:
    owner.close()
    other = open_control()
    deadline = time.monotonic() + 2
    last = None
    while time.monotonic() < deadline:
        try:
            last = other.execute("recover_owner", ACTOR, {"run_id": run_id})
            return last
        except ControlError as exc:
            if exc.code != "AlreadyActive":
                raise
            time.sleep(0.05)
    raise AssertionError(last)


def recover_owner_expires_run():
    owner = open_control()
    started = do_start(owner, "expire")
    dead_pid = owner.conn.get_backend_pid()
    recovered = _wait_until_dead(owner, started["run_id"])
    assert recovered["status"] == "expired"
    run = one(open_control(), """
        SELECT owner_generation, owner_backend_pid, revision FROM v20_runs WHERE run_id = %s
    """, (started["run_id"],))
    assert run["owner_generation"] == 2
    assert run["owner_backend_pid"] == dead_pid
    assert run["revision"] == 2
    session = one(CONTROLS[-1], """
        SELECT state, resumable, registration_generation FROM v20_sessions WHERE session_id = %s
    """, (started["session_id"],))
    assert session["state"] == "interrupted"
    assert session["resumable"] is True
    assert session["registration_generation"] == 2
    epoch = one(CONTROLS[-1], "SELECT closed_at FROM v20_epochs WHERE session_id = %s", (started["session_id"],))
    assert epoch["closed_at"] is not None
    operation = one(CONTROLS[-1], """
        SELECT status, handle_state, input_retained FROM v20_operations WHERE request_id = %s
    """, (started["request_id"],))
    assert operation["status"] == "archived"
    assert operation["handle_state"] == "absent"
    assert operation["input_retained"] is False


def recover_owner_alive_pid_rejected():
    owner = open_control()
    started = do_start(owner, "alive")
    other = open_control()
    expect("AlreadyActive", lambda: other.execute("recover_owner", ACTOR, {"run_id": started["run_id"]}))
    run = one(other, "SELECT status, owner_generation, revision FROM v20_runs WHERE run_id = %s", (started["run_id"],))
    assert run["status"] == "running"
    assert run["owner_generation"] == 1
    assert run["revision"] == 1


def claim_resume_keeps_ids_and_advances_epoch():
    ctrl, _worker, result, _payload = finish("resume-base")
    claimed = ctrl.execute("claim_resume", ACTOR, {
        "request_id": uid(), "run_id": result["run_id"], "input_message": "again",
        "transition_kind": "related_follow_up",
    })
    assert claimed["run_id"] == result["run_id"]
    assert claimed["session_id"] == result["session_id"]
    assert claimed["status"] == "running"
    assert claimed["expects_handle"] is True
    assert claimed["operation_status"] == "pending"
    epoch = one(ctrl, """
        SELECT ordinal, transition_kind FROM v20_epochs WHERE epoch_id = %s
    """, (claimed["epoch_id"],))
    assert epoch["ordinal"] == 2
    assert epoch["transition_kind"] == "related_follow_up"
    assert one(ctrl, "SELECT continuity_generation FROM v20_sessions WHERE session_id = %s", (result["session_id"],))["continuity_generation"] == 1
    assert not read(ctrl, """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE '%%workflow%%'
    """)


def claim_resume_rejects_running_without_recover():
    owner = open_control()
    started = do_start(owner, "still-running")
    other = open_control()
    expect("AlreadyActive", lambda: other.execute("claim_resume", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "no",
    }))
    assert one(other, "SELECT count(*) AS n FROM v20_epochs WHERE session_id = %s", (started["session_id"],))["n"] == 1
    owner.close()
    deadline = time.monotonic() + 2
    seen = None
    while time.monotonic() < deadline:
        try:
            other.execute("claim_resume", ACTOR, {
                "request_id": uid(), "run_id": started["run_id"], "input_message": "still-no",
            })
        except ControlError as exc:
            seen = exc.code
            if seen != "AlreadyActive":
                break
        else:
            seen = "committed"
            break
        time.sleep(0.05)
    assert seen == "Rejected"
    assert one(other, "SELECT count(*) AS n FROM v20_epochs WHERE session_id = %s", (started["session_id"],))["n"] == 1


def related_follow_up_keeps_continuity():
    ctrl, _worker, result, _payload = finish("related")
    before = one(ctrl, "SELECT continuity_generation FROM v20_sessions WHERE session_id = %s", (result["session_id"],))["continuity_generation"]
    ctrl.execute("claim_resume", ACTOR, {
        "request_id": uid(), "run_id": result["run_id"], "input_message": "more",
        "transition_kind": "related_follow_up",
    })
    after = one(ctrl, "SELECT continuity_generation FROM v20_sessions WHERE session_id = %s", (result["session_id"],))["continuity_generation"]
    assert after == before


def unrelated_bumps_continuity():
    ctrl, _worker, result, _payload = finish("unrelated")
    before = one(ctrl, "SELECT continuity_generation FROM v20_sessions WHERE session_id = %s", (result["session_id"],))["continuity_generation"]
    claimed = ctrl.execute("claim_resume", ACTOR, {
        "request_id": uid(), "run_id": result["run_id"], "input_message": "else",
        "transition_kind": "unrelated",
    })
    after = one(ctrl, "SELECT continuity_generation FROM v20_sessions WHERE session_id = %s", (result["session_id"],))["continuity_generation"]
    assert after == before + 1
    assert one(ctrl, "SELECT continuity_generation FROM v20_epochs WHERE epoch_id = %s", (claimed["epoch_id"],))["continuity_generation"] == after


def two_claim_resume_one_wins():
    ctrl, _worker, result, _payload = finish("race-claim")
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        local = open_control()
        pid = local.conn.get_backend_pid()
        barrier.wait(5)
        try:
            local.execute("claim_resume", ACTOR, {
                "request_id": uid(), "run_id": result["run_id"], "input_message": "race",
            })
            results.append(("ok", pid))
        except ControlError as exc:
            results.append((exc.code, pid))

    threads = [threading.Thread(target=attempt, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(8)
        assert not thread.is_alive()
    codes = sorted(item[0] for item in results)
    assert codes == ["AlreadyActive", "ok"]
    winner = next(pid for code, pid in results if code == "ok")
    run = one(ctrl, "SELECT owner_backend_pid FROM v20_runs WHERE run_id = %s", (result["run_id"],))
    assert run["owner_backend_pid"] == winner
    assert one(ctrl, "SELECT count(*) AS n FROM v20_epochs WHERE session_id = %s", (result["session_id"],))["n"] == 2


def late_receipt_after_recover_archives():
    owner = open_control()
    started = do_start(owner, "late-recover")
    turn = do_admit(owner, started, "initial")
    _wait_until_dead(owner, started["run_id"])
    other = CONTROLS[-1]
    expect("FenceRejected", lambda: other.execute("accept_turn_receipt", ACTOR, {
        "request_id": turn["request_id"],
        "receipt": {
            "schema_version": 1, "outcome": "completed", "run_id": started["run_id"],
            "turn_id": turn["turn_id"], "input_kind": "initial", "result": {"late": True},
            "request_id": turn["request_id"],
        },
    }))
    operation = one(other, "SELECT status FROM v20_operations WHERE request_id = %s", (turn["request_id"],))
    assert operation["status"] == "archived"
    assert poll(other, started["run_id"])["status"] == "expired"


def cancel_during_worker_returns_failed():
    ctrl = open_control()
    other = open_control()
    session_id = uid()
    entered = threading.Event()
    release = threading.Event()
    box: dict = {}

    def blocking(request):
        assert_outside_transaction()
        entered.set()
        assert release.wait(5)
        return completed_receipt(request)

    def runner():
        try:
            box["result"] = Host(ctrl, blocking).drive("start", ACTOR, {
                "request_id": uid(), "input_message": "block", "session_id": session_id,
            })
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    try:
        assert entered.wait(5)
        expect("Rejected", lambda: Host(ctrl, blocking).drive("start", ACTOR, {
            "request_id": uid(), "input_message": "second",
        }))
        other.execute("cancel", ACTOR, {"run_id": session_id})
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert "error" not in box
    assert box["result"]["disposition"] == "failed"
    assert poll(other, session_id)["status"] == "cancelled"


# --- wait and input ------------------------------------------------------------


def needs_input_then_respond_completes():
    assert decide({"run_status": "completed", "pending_tool": True}) == "stop"
    assert decide({"run_status": "failed"}) == "failed"
    assert decide({"run_status": "cancelled"}) == "failed"
    assert decide({"run_status": "expired"}) == "failed"
    assert decide({"run_status": "running", "depended_handle_state": "pending", "pending_tool": True}) == "wait"
    assert decide({"run_status": "running", "pending_tool": True}) == "run_now"
    assert decide({"run_status": "running", "pending_turn": True}) == "run_now"
    assert decide({"run_status": "waiting_for_input"}) == "needs_input"
    assert decide({"run_status": "running"}) == "wait"
    assert decide({"run_status": "elsewhere"}) == "failed"
    ctrl = open_control()
    worker = FakeWorker("needs_input")
    host = Host(ctrl, worker)
    first = host.drive("start", ACTOR, {"request_id": uid(), "input_message": "ask"})
    assert first["disposition"] == "needs_input"
    assert first["status"] == "waiting_for_input"
    snap = poll(ctrl, first["run_id"])
    assert decide(snap) == "needs_input"
    assert snap["driving"]["handle_state"] == "absent"
    session = one(ctrl, "SELECT state, resumable FROM v20_sessions WHERE session_id = %s", (first["session_id"],))
    assert session["state"] == "active"
    assert session["resumable"] is True
    second = host.drive("respond", ACTOR, {
        "request_id": uid(), "run_id": first["run_id"], "input_message": "the answer",
        "expected_revision": snap["revision"],
    })
    assert second["disposition"] == "stop"
    assert second["status"] == "completed"
    assert any(call.input_kind == "parent_response" for call in worker.calls)
    assert one(ctrl, "SELECT state FROM v20_sessions WHERE session_id = %s", (first["session_id"],))["state"] == "dormant"

    class RoundWorker:
        def __init__(self) -> None:
            self.continues = 0

        def __call__(self, request):
            assert_outside_transaction()
            calls: tuple = ()
            input_request = None
            if request.input_kind == "initial":
                outcome = "progress"
                result = {"ok": True}
                calls = ({"call_id": 1, "name": "echo", "arguments": {"text": request.instruction}},)
            elif request.input_kind == "host_continue" and self.continues == 0:
                self.continues += 1
                outcome = "needs_input"
                result = {"ok": True}
                input_request = {"interaction_id": "round", "prompt": "again"}
            elif request.input_kind == "parent_response" and not request.tool_results:
                outcome = "progress"
                result = {"ok": True}
                calls = ({"call_id": 1, "name": "echo", "arguments": {"text": "again"}},)
            elif request.input_kind == "parent_response" and request.tool_results:
                outcome = "completed"
                result = {"ok": True}
            elif request.input_kind == "host_continue":
                self.continues += 1
                outcome = "completed"
                result = {"ok": True}
            else:
                raise AssertionError(request.input_kind)
            receipt = TurnReceipt(
                1, request.turn_id, request.run_id, request.base_revision, request.input_kind,
                request.input_digest, outcome, result, input_request, calls,
            )
            validate_receipt(receipt, request)
            return receipt

    again = open_control()
    worker = RoundWorker()
    host = Host(again, worker)
    answered = host.drive("start", ACTOR, {
        "request_id": uid(), "input_message": "ask-round",
    })
    assert answered["disposition"] == "needs_input"
    waiting = poll(again, answered["run_id"])
    responded = host.drive("respond", ACTOR, {
        "request_id": uid(), "run_id": answered["run_id"], "input_message": "the answer",
        "expected_revision": waiting["revision"],
    })
    assert responded["disposition"] == "stop", responded
    assert responded["status"] == "completed"
    assert one(again, "SELECT failure_reason FROM v20_runs WHERE run_id = %s", (answered["run_id"],))["failure_reason"] is None


def respond_rejected_unless_waiting():
    ctrl = open_control()
    started = do_start(ctrl, "not-waiting")
    expect("Rejected", lambda: ctrl.execute("respond", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "no",
        "expected_revision": started["revision"],
    }))
    assert one(ctrl, "SELECT count(*) AS n FROM v20_operations WHERE epoch_id = %s", (started["epoch_id"],))["n"] == 1
    _ctrl, _worker, result, _payload = finish("already-done", ctrl=ctrl)
    expect("Rejected", lambda: ctrl.execute("respond", ACTOR, {
        "request_id": uid(), "run_id": result["run_id"], "input_message": "no",
        "expected_revision": result["revision"],
    }))


def wait_listens_before_read():
    ctrl = open_control()
    started = do_start(ctrl, "listen-order")

    class Order(Control):
        def __init__(self, dsn: str) -> None:
            super().__init__(dsn)
            self.events = []
            self.channels = None

        def _after_listen(self, listener):
            self.events.append("listen")
            with listener.cursor() as cur:
                cur.execute("SELECT pg_listening_channels()")
                self.channels = cur.fetchone()[0]

        def _before_authoritative_read(self, listener):
            self.events.append("read")

    waiter = open_control(Order)
    waiter.execute("wait", ACTOR, {
        "run_id": started["run_id"], "since_revision": 0, "timeout_seconds": 0.2,
    })
    assert waiter.events == ["listen", "read"]
    assert CHANNEL in str(waiter.channels), waiter.channels


def wait_sees_commit_from_before_listen():
    ctrl = open_control()
    started = do_start(ctrl, "before-listen")

    class Early(Control):
        def __init__(self, dsn: str) -> None:
            super().__init__(dsn)
            self.target = started["run_id"]

        def _before_listen(self):
            side = psycopg2.connect(DSN)
            side.autocommit = True
            try:
                with side.cursor() as cur:
                    cur.execute(
                        "UPDATE v20_runs SET revision = revision + 50 WHERE run_id = %s",
                        (self.target,),
                    )
            finally:
                side.close()

    waiter = open_control(Early)
    began = time.monotonic()
    result = waiter.execute("wait", ACTOR, {
        "run_id": started["run_id"], "since_revision": started["revision"], "timeout_seconds": 1.5,
    })
    assert time.monotonic() - began < 1.0
    assert result["revision"] == started["revision"] + 50


def lost_notify_seen_on_timeout():
    ctrl = open_control()
    started = do_start(ctrl, "lost-notify")

    class Lost(Control):
        def __init__(self, dsn: str) -> None:
            super().__init__(dsn)
            self.target = started["run_id"]

        def _during_wait(self, listener):
            with listener.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "UPDATE v20_runs SET revision = revision + 7 WHERE run_id = %s",
                    (self.target,),
                )

    waiter = open_control(Lost)
    began = time.monotonic()
    result = waiter.execute("wait", ACTOR, {
        "run_id": started["run_id"], "since_revision": started["revision"], "timeout_seconds": 0.35,
    })
    elapsed = time.monotonic() - began
    assert elapsed >= 0.25, elapsed
    assert result["revision"] == started["revision"] + 7


def wait_connection_idle():
    ctrl = open_control()
    started = do_start(ctrl, "idle-wait")

    class Idle(Control):
        def __init__(self, dsn: str) -> None:
            super().__init__(dsn)
            self.main_status = None
            self.listener_status = None

        def _during_wait(self, listener):
            self.main_status = self.conn.get_transaction_status()
            self.listener_status = listener.get_transaction_status()

    waiter = open_control(Idle)
    waiter.execute("wait", ACTOR, {
        "run_id": started["run_id"], "since_revision": started["revision"], "timeout_seconds": 0.2,
    })
    assert waiter.main_status == TRANSACTION_STATUS_IDLE
    assert waiter.listener_status == TRANSACTION_STATUS_IDLE


# --- handles -------------------------------------------------------------------


def start_expects_handle_and_no_depends_on():
    ctrl = open_control()
    started = do_start(ctrl, "handle-start")
    assert started["expects_handle"] is True
    assert started["depends_on_request_id"] is None
    assert started["handle_state"] == "pending"
    assert started["operation_status"] == "pending"


def no_handle_starts_worker():
    ctrl = open_control()
    seen = []

    def worker(request):
        assert_outside_transaction()
        seen.append(request)
        return completed_receipt(request)

    began = time.monotonic()
    result = Host(ctrl, worker).drive(
        "start", ACTOR, {"request_id": uid(), "input_message": "go"}, handle_timeout=2,
    )
    assert time.monotonic() - began < 1.5
    assert result["disposition"] == "stop"
    assert len(seen) == 1
    assert seen[0].provider_handle is None


def record_handle_present_without_changing_run():
    ctrl = open_control()
    started = do_start(ctrl, "record")
    ctrl.execute("record_provider_handle", ACTOR, {
        "request_id": started["request_id"], "handle": {"tok": "a"},
    })
    snap = poll(ctrl, started["run_id"])
    assert snap["revision"] == 1
    assert snap["status"] == "running"
    operation = one(ctrl, "SELECT status, handle_state, result FROM v20_operations WHERE request_id = %s", (started["request_id"],))
    assert operation["status"] == "pending"
    assert operation["handle_state"] == "present"
    assert operation["result"] is None
    current = one(ctrl, """
        SELECT provider_cleanup_handle, attempt_seq FROM v20_session_provider_handles WHERE session_id = %s
    """, (started["session_id"],))
    assert j(current["provider_cleanup_handle"]) == {"tok": "a"}
    assert current["attempt_seq"] == started["attempt_seq"]
    assert one(ctrl, "SELECT count(*) AS n FROM v20_provider_handle_attempts WHERE request_id = %s", (started["request_id"],))["n"] == 1


def handle_before_snapshot_and_snapshot_before_handle():
    ctrl = open_control()
    first = do_start(ctrl, "handle-first")
    ctrl.execute("record_provider_handle", ACTOR, {"request_id": first["request_id"], "handle": {"k": 1}})
    ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": first["request_id"], "mode": "final", "outcome": "completed",
        "result": {"kept": 1}, "preview": "a",
    })
    operation = one(ctrl, "SELECT status, handle_state, result FROM v20_operations WHERE request_id = %s", (first["request_id"],))
    assert operation["status"] == "completed"
    assert operation["handle_state"] == "present"
    assert j(operation["result"])["result"]["kept"] == 1
    assert j(one(ctrl, "SELECT provider_cleanup_handle FROM v20_session_provider_handles WHERE session_id = %s", (first["session_id"],))["provider_cleanup_handle"]) == {"k": 1}

    second = do_start(ctrl, "snapshot-first")
    ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": second["request_id"], "mode": "final", "outcome": "completed",
        "result": {"kept": 2}, "preview": "b",
    })
    mid = one(ctrl, "SELECT status, handle_state, result FROM v20_operations WHERE request_id = %s", (second["request_id"],))
    assert mid["status"] == "completed"
    assert mid["handle_state"] == "pending"
    ctrl.execute("record_provider_handle", ACTOR, {"request_id": second["request_id"], "handle": {"k": 2}})
    done = one(ctrl, "SELECT status, handle_state, result FROM v20_operations WHERE request_id = %s", (second["request_id"],))
    assert done["status"] == "completed"
    assert done["handle_state"] == "present"
    assert j(done["result"]) == j(mid["result"])
    assert j(one(ctrl, "SELECT provider_cleanup_handle FROM v20_session_provider_handles WHERE session_id = %s", (second["session_id"],))["provider_cleanup_handle"]) == {"k": 2}


def smaller_attempt_seq_does_not_overwrite_current_handle():
    ctrl = open_control()
    started, published = park_needs_input(ctrl, "seq")
    responded = ctrl.execute("respond", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "answer",
        "expected_revision": published["revision"],
    })
    ctrl.execute("record_provider_handle", ACTOR, {"request_id": responded["request_id"], "handle": {"gen": 2}})
    ctrl.execute("record_provider_handle", ACTOR, {"request_id": started["request_id"], "handle": {"gen": 1}})
    current = one(ctrl, """
        SELECT provider_cleanup_handle, attempt_seq FROM v20_session_provider_handles WHERE session_id = %s
    """, (started["session_id"],))
    assert current["attempt_seq"] == responded["attempt_seq"]
    assert j(current["provider_cleanup_handle"]) == {"gen": 2}
    assert one(ctrl, "SELECT count(*) AS n FROM v20_provider_handle_attempts WHERE request_id IN (%s, %s)", (started["request_id"], responded["request_id"]))["n"] == 2


def old_epoch_handle_does_not_overwrite_current():
    ctrl = open_control()
    started = do_start(ctrl, "old-handle")
    steered = ctrl.execute("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "new epoch",
        "expected_revision": started["revision"],
    })
    ctrl.execute("record_provider_handle", ACTOR, {"request_id": steered["request_id"], "handle": {"side": "new"}})
    ctrl.execute("record_provider_handle", ACTOR, {"request_id": started["request_id"], "handle": {"side": "old"}})
    current = one(ctrl, """
        SELECT provider_cleanup_handle, attempt_seq FROM v20_session_provider_handles WHERE session_id = %s
    """, (started["session_id"],))
    assert current["attempt_seq"] == steered["attempt_seq"]
    assert j(current["provider_cleanup_handle"]) == {"side": "new"}
    assert one(ctrl, "SELECT count(*) AS n FROM v20_provider_handle_attempts WHERE request_id IN (%s, %s)", (started["request_id"], steered["request_id"]))["n"] == 2


def claim_resume_depends_on_earlier_handle():
    owner = open_control()
    started = do_start(owner, "archived-handle")
    owner.execute("record_provider_handle", ACTOR, {
        "request_id": started["request_id"], "handle": {"keep": "yes"},
    })
    _wait_until_dead(owner, started["run_id"])
    other = CONTROLS[-1]
    assert one(other, "SELECT status, handle_state FROM v20_operations WHERE request_id = %s", (started["request_id"],)) == {
        "status": "archived", "handle_state": "present",
    }
    claimed = other.execute("claim_resume", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "back",
    })
    assert claimed["depends_on_request_id"] == started["request_id"]
    resolved = other.resolve_handle(claimed["request_id"], timeout=2)
    assert resolved["state"] == "present"
    assert j(resolved["handle"]) == {"keep": "yes"}


def present_handle_is_in_next_worker_input():
    ctrl = open_control()
    started = do_start(ctrl, "seen-handle")
    ctrl.execute("record_provider_handle", ACTOR, {
        "request_id": started["request_id"], "handle": {"tok": "abc"},
    })
    worker = FakeWorker()
    Host(ctrl, worker).drive("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "use it",
        "expected_revision": started["revision"],
    })
    assert worker.calls
    assert j(worker.calls[0].provider_handle) == {"tok": "abc"}


def absent_does_not_wait():
    ctrl = open_control()
    started = do_start(ctrl, "absent")
    worker = FakeWorker()
    began = time.monotonic()
    Host(ctrl, worker).drive("steer", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "next",
        "expected_revision": started["revision"],
    }, handle_timeout=2)
    assert time.monotonic() - began < 1.5
    assert worker.calls
    assert worker.calls[0].provider_handle is None


def pending_handle_returns_wait_not_forever():
    ctrl = open_control()
    started, published = park_needs_input(ctrl, "pending-handle")
    calls = []

    def worker(request):
        calls.append(request)
        raise AssertionError("worker ran while the handle was pending")

    began = time.monotonic()
    result = Host(ctrl, worker).drive("respond", ACTOR, {
        "request_id": uid(), "run_id": started["run_id"], "input_message": "answer",
        "expected_revision": published["revision"],
    }, handle_timeout=0.3)
    elapsed = time.monotonic() - began
    assert result["disposition"] == "wait", result
    assert calls == []
    assert 0.25 <= elapsed < 0.7, elapsed


def completed_without_attempt_becomes_absent():
    ctrl = open_control()
    started = do_start(ctrl, "no-attempt")
    ctrl.execute("publish_snapshot", ACTOR, {
        "request_id": started["request_id"], "mode": "final", "outcome": "completed",
        "result": {"ok": True}, "preview": "done", "no_handle": True,
    })
    operation = one(ctrl, "SELECT status, handle_state FROM v20_operations WHERE request_id = %s", (started["request_id"],))
    assert operation["status"] == "completed"
    assert operation["handle_state"] == "absent"
    assert one(ctrl, "SELECT count(*) AS n FROM v20_provider_handle_attempts WHERE request_id = %s", (started["request_id"],))["n"] == 0


# --- transcript ----------------------------------------------------------------


def request_activity_on_t1():
    ctrl = open_control()
    started = do_start(ctrl, "hello there")
    rows = read(ctrl, """
        SELECT role, item_kind, text FROM v20_transcript_activities a
        JOIN v20_transcript_turns t ON t.turn_id = a.turn_id
        WHERE t.session_id = %s ORDER BY a.sequence_index
    """, (started["session_id"],))
    assert rows == [{"role": "user", "item_kind": "request", "text": "hello there"}]
    do_admit(ctrl, started, "initial")
    rows = read(ctrl, """
        SELECT role, item_kind FROM v20_transcript_activities a
        JOIN v20_transcript_turns t ON t.turn_id = a.turn_id
        WHERE t.session_id = %s ORDER BY a.sequence_index
    """, (started["session_id"],))
    assert rows == [
        {"role": "user", "item_kind": "request"},
        {"role": "user", "item_kind": "request"},
    ]


def response_activity_on_t2():
    ctrl = open_control()
    started = do_start(ctrl, "respond-activity")
    do_admit(ctrl, started, "initial")
    snap, turn = pending_turn(ctrl, started["run_id"])
    receipt = FakeWorker()(request_for(snap, turn))
    body = receipt.as_dict()
    body["request_id"] = turn["request_id"]
    assert not read(ctrl, """
        SELECT 1 FROM v20_transcript_activities a
        JOIN v20_transcript_turns t ON t.turn_id = a.turn_id
        WHERE t.session_id = %s AND a.role = 'assistant'
    """, (started["session_id"],))
    ctrl.execute("accept_turn_receipt", ACTOR, {"request_id": turn["request_id"], "receipt": body})
    activity = one(ctrl, """
        SELECT role, item_kind, text FROM v20_transcript_activities a
        JOIN v20_transcript_turns t ON t.turn_id = a.turn_id
        WHERE t.session_id = %s AND a.role = 'assistant'
    """, (started["session_id"],))
    assert activity["item_kind"] == "response"
    assert j(activity["text"]) == j(receipt.result)


def two_turns_one_transcript_turn():
    ctrl, _worker, result, _payload = finish("shared-transcript")
    turns = read(ctrl, "SELECT transcript_turn_id FROM v20_turns WHERE run_id = %s", (result["run_id"],))
    assert len(turns) == 2
    assert len({row["transcript_turn_id"] for row in turns}) == 1
    assert one(ctrl, "SELECT count(*) AS n FROM v20_transcript_turns WHERE session_id = %s", (result["session_id"],))["n"] == 1


def transcript_has_no_control_turn_id():
    ctrl = open_control()
    columns = {row["column_name"] for row in read(ctrl, """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'v20_transcript_turns'
    """)}
    assert "control_turn_id" not in columns


PROBES = (
    "unix_socket_only",
    "worker_role_cannot_connect",
    "control_role_sees_other_backend_pid",
    "run_id_aliases_session",
    "sessions_have_no_workflow_run_id",
    "no_workflow_or_plan_or_artifact_tables",
    "child_parent_session",
    "unknown_parent_rejected",
    "start_is_running_and_pending",
    "first_turn_accepted_before_tool",
    "preview_keeps_operation_pending",
    "preview_retry_same_snapshot_seq",
    "smaller_snapshot_seq_does_not_overwrite",
    "echo_result_visible_on_next_turn",
    "tool_receipt_does_not_complete_run",
    "second_tool_does_not_block_first",
    "bare_progress_twice_fails",
    "final_snapshot_dormant_resumable",
    "replay_same_request_keeps_result",
    "replay_digest_mismatch",
    "io_outside_transaction",
    "model_call_inside_transaction_rejected",
    "cancel_then_late_t2_archives_only",
    "complete_then_cancel_stays_completed",
    "admit_after_cancel_rejected",
    "steer_from_running_publishes_new_epoch",
    "steer_cas_one_commits_one_conflicts",
    "old_epoch_t2_does_not_overwrite_new_snapshot",
    "cleanup_hides_and_rejects_resume",
    "cleanup_keeps_events_and_transcript",
    "wait_sees_cleanup_revision",
    "steer_after_cancel_publishes",
    "recover_owner_expires_run",
    "recover_owner_alive_pid_rejected",
    "claim_resume_keeps_ids_and_advances_epoch",
    "claim_resume_rejects_running_without_recover",
    "related_follow_up_keeps_continuity",
    "unrelated_bumps_continuity",
    "two_claim_resume_one_wins",
    "late_receipt_after_recover_archives",
    "cancel_during_worker_returns_failed",
    "needs_input_then_respond_completes",
    "respond_rejected_unless_waiting",
    "wait_listens_before_read",
    "wait_sees_commit_from_before_listen",
    "lost_notify_seen_on_timeout",
    "wait_connection_idle",
    "start_expects_handle_and_no_depends_on",
    "no_handle_starts_worker",
    "record_handle_present_without_changing_run",
    "handle_before_snapshot_and_snapshot_before_handle",
    "smaller_attempt_seq_does_not_overwrite_current_handle",
    "old_epoch_handle_does_not_overwrite_current",
    "claim_resume_depends_on_earlier_handle",
    "present_handle_is_in_next_worker_input",
    "absent_does_not_wait",
    "pending_handle_returns_wait_not_forever",
    "completed_without_attempt_becomes_absent",
    "request_activity_on_t1",
    "response_activity_on_t2",
    "two_turns_one_transcript_turn",
    "transcript_has_no_control_turn_id",
)


def main() -> int:
    global DSN
    setup.main()
    DSN = local_dsn()
    failed = []
    for name in PROBES:
        try:
            globals()[name]()
        except Exception:
            failed.append(name)
            print("FAIL", name, flush=True)
            traceback.print_exc()
        else:
            print("ok", name, flush=True)
        finally:
            close_controls()
    print(f"{len(PROBES) - len(failed)}/{len(PROBES)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
