"""Stage 42 consumer projection and native claim/completion gate.

Run: UV_FROZEN=1 uv run python v13/registry/test_consumer.py
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import Json
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

ROOT = Path(__file__).resolve().parent


def load_setup():
    name = "consumer_gate_setup"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "setup_db.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class Gate:
    def __init__(self):
        self.checks = 0

    def check(self, label: str, condition: bool, evidence=None):
        self.checks += 1
        if not condition:
            raise AssertionError(f"{label}: {evidence!r}")
        print(f"  ok {self.checks}: {label}", flush=True)

    @contextlib.contextmanager
    def connection(self, setup, database, role=None):
        conn = (setup.connect_owner_database(database)
                if role == "owner" else setup.connect_test_database(database, role=role))
        try:
            yield conn
        finally:
            conn.close()

    def rejected(self, conn, statement, args=(), code="42501"):
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(statement, args)
        except psycopg2.Error as exc:
            self.check("rejected at expected ACL/guard boundary", exc.pgcode == code,
                       (exc.pgcode, str(exc)))
        else:
            self.check("statement must be rejected", False, statement)


def q1(conn, statement, args=()):
    with conn.cursor() as cur:
        cur.execute(statement, args)
        row = cur.fetchone()
        return None if row is None else row[0]


def qrow(conn, statement, args=()):
    with conn.cursor() as cur:
        cur.execute(statement, args)
        return cur.fetchone()


GLOBAL_KEYS = {"effect_id", "attempt_no", "fence", "kind", "request", "context_revision"}
FRESH_KEYS = {"session_version", "max_event_seq", "goal_hash", "route_policy_name",
              "route_policy_version", "tools_revision", "candidate_generation_revision",
              "registry_revision"}
ENVELOPE_KEYS = {"sid", "ctx", "needed", "templates", "groups", "timeout_ms", "budget",
                 "candidate_set_hash", "goal_hash", "provider", "model", "route_policy_name",
                 "route_policy_version", "tools_revision", "tools_catalog",
                 "candidate_generation_revision", "session_version", "max_event_seq",
                 "needed_count", "candidates", "registry_revision"}
STRICT = "SELECT public.v13_complete(NULL::uuid,%s::uuid,%s::integer,%s::bigint,%s,%s::jsonb,%s::bigint)"


def ready(conn, sid=None):
    sid = sid or q1(conn, "SELECT public.v13_open_session('{}'::jsonb)")
    eid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("INSERT INTO effects(effect_id,session_id,kind,request,request_hash,origin_user_seq) "
                    "VALUES (%s,%s,'judge','{}',encode(digest('{}','sha256'),'hex'),0)", (eid, sid))
    conn.commit()
    return str(sid), eid


def completion_args(claim, revision=None):
    return (claim["effect_id"], claim["attempt_no"], claim["fence"], "failed", None,
            claim["context_revision"] if revision is None else revision)


def native_claim_complete(gate, setup, database):
    with gate.connection(setup, database, "owner") as owner, \
         gate.connection(setup, database, "route") as route:
        sid, eid = ready(owner)
        claim = q1(route, "SELECT public.v13_claim('consumer-global')")
        route.commit()
        gate.check("native_claim_pin: global exact six keys", set(claim) == GLOBAL_KEYS, claim)
        pin = qrow(owner, "SELECT scope_id,context_revision,tools_revision FROM "
                   "v13_effect_context_pins WHERE effect_id=%s", (eid,))
        gate.check("native_claim_pin: one exact pin", pin[:2] == (sid, claim["context_revision"]), pin)
        owner.commit()
        gate.check("native_claim_pin: empty claim returns NULL", q1(route, "SELECT v13_claim('empty')") is None)
        route.commit()
        gate.check("native_strict_complete: wrong revision is stale",
                   q1(route, STRICT, completion_args(claim, claim["context_revision"] + 1)) == "stale")
        route.commit()
        for revision in (None, -1):
            args = list(completion_args(claim)); args[-1] = revision
            gate.rejected(route, STRICT, args, "22023")
        args = list(completion_args(claim)); args[1] += 1; args[-1] = None
        gate.check("native_strict_complete: token stale precedes revision validation",
                   q1(route, STRICT, args) == "stale")
        route.commit()
        with owner.cursor() as cur:
            cur.execute("UPDATE v13_registry_clock SET revision=revision+1 WHERE singleton")
        owner.commit()
        gate.check("native_strict_complete: old exact pin can settle after clock advances",
                   q1(route, STRICT, completion_args(claim)) == "accepted")
        route.commit()
        gate.check("native_strict_complete: exact terminal token replays",
                   q1(route, STRICT, completion_args(claim)) == "replay")
        route.commit()
        mapped = qrow(owner, "SELECT e.source_effect_id,ep.attempt_no,ep.fence FROM events e "
                      "JOIN v13_effect_context_event_pins ep ON (ep.session_id,ep.event_seq)=(e.session_id,e.seq) "
                      "WHERE e.session_id=%s AND e.type='resolve/failed'", (sid,))
        gate.check("native_strict_complete: judge failure has exact event mapping",
                   mapped == (eid, claim["attempt_no"], claim["fence"]), mapped)
        gate.check("native_strict_complete: mismatch writes no extra completion events",
                   q1(owner, "SELECT count(*) FROM events WHERE source_effect_id=%s", (eid,)) == 2)
        owner.commit()

        # Missing pin is an error only for strict completion; both legacy arities survive.
        for arity in (5, 6):
            legacy_sid, legacy_eid = ready(owner)
            with owner.cursor() as cur:
                cur.execute("UPDATE effects SET status='claimed',attempt_no=1,fence=1 WHERE effect_id=%s", (legacy_eid,))
            owner.commit()
            legacy = (legacy_eid, 1, 1, "failed", None)
            gate.rejected(route, STRICT, (*legacy, 0), "P0001")
            statement = ("SELECT v13_complete(%s::uuid,%s,%s::bigint,%s,%s::jsonb)" if arity == 5
                         else "SELECT v13_complete(NULL::uuid,%s::uuid,%s,%s::bigint,%s,%s::jsonb)")
            gate.check(f"native_legacy_complete: unpinned {arity} parameters accepted",
                       q1(route, statement, legacy) == "accepted")
            route.commit()

        # The global cap is two; foundation has one claimed effect.
        fair_sid, fair_eid = ready(owner)
        fair = q1(owner, "SELECT v13_claim_fair('consumer-fair')")
        gate.check("native_claim_pin: fair exact seven keys", fair is not None and
                   set(fair) == GLOBAL_KEYS | {"root_session_id"} and fair["effect_id"] == fair_eid, fair)
        gate.check("native_claim_pin: fair pin is atomic", q1(owner,
                   "SELECT count(*) FROM v13_effect_context_pins WHERE effect_id=%s", (fair_eid,)) == 1)
        owner.commit()
        gate.rejected(route, "SELECT v13_claim_fair('denied')")
        gate.check("native_strict_complete: fair token settles", q1(route, STRICT, completion_args(fair)) == "accepted")
        route.commit()

        # Pin insertion failure must undo the effect CAS, including attempt/fence.
        rollback_sid, rollback_eid = ready(owner)
        with owner.cursor() as cur:
            cur.execute("CREATE FUNCTION consumer_reject_pin() RETURNS trigger LANGUAGE plpgsql AS $$ "
                        "BEGIN RAISE EXCEPTION 'consumer pin rollback'; END $$")
            cur.execute("CREATE TRIGGER consumer_reject_pin BEFORE INSERT ON v13_effect_context_pins "
                        "FOR EACH ROW EXECUTE FUNCTION consumer_reject_pin()")
        owner.commit()
        gate.rejected(route, "SELECT v13_claim('rollback')", code="P0001")
        gate.check("native_claim_pin: failed pin rolls back CAS", qrow(owner,
                   "SELECT status,attempt_no,fence FROM effects WHERE effect_id=%s", (rollback_eid,)) == ("ready", 0, 0))
        gate.rejected(owner, "SELECT v13_claim_fair('rollback-fair')", code="P0001")
        gate.check("native_claim_pin: fair pin failure rolls back CAS", qrow(owner,
                   "SELECT status,attempt_no,fence FROM effects WHERE effect_id=%s", (rollback_eid,)) == ("ready", 0, 0))
        with owner.cursor() as cur:
            cur.execute("DROP TRIGGER consumer_reject_pin ON v13_effect_context_pins")
            cur.execute("DROP FUNCTION consumer_reject_pin()")
        owner.commit()
        legacy_pin = q1(route, "SELECT v13_claim('pinned-legacy')")
        route.commit()
        gate.check("native_legacy_complete: pinned legacy accepted", q1(route,
                   "SELECT v13_complete(%s::uuid,%s,%s::bigint,'failed',NULL::jsonb)",
                   (legacy_pin["effect_id"], legacy_pin["attempt_no"], legacy_pin["fence"])) == "accepted")
        route.commit()
        gate.check("native_legacy_complete: pinned legacy event mapping preserved", q1(owner,
                   "SELECT count(*) FROM v13_effect_context_event_pins WHERE effect_id=%s", (rollback_eid,)) == 2)
        signature = "v13_complete(uuid,uuid,integer,bigint,text,jsonb,bigint)"
        for role in ("v13_route", "v13_spawn_owner", "v13_worker", "v13_resolve", "v13_recall"):
            gate.check("native_acl: strict completion " + role, q1(owner,
                       "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)) ==
                       (role in {"v13_route", "v13_spawn_owner"}))
        gate.check("native_acl: strict completion has zero defaults", q1(owner,
                   "SELECT pronargdefaults FROM pg_proc WHERE oid=%s::regprocedure", (signature,)) == 0)
        owner.commit()


def native_w4_projection(gate, setup, database):
    with (gate.connection(setup, database, "owner") as owner,
          gate.connection(setup, database, "route") as route):
        sid, eid = ready(owner)
        claim = q1(route, "SELECT public.v13_claim('w4-superseded')")
        route.commit()
        old_seq = q1(route, "SELECT public.v13_append_event(%s::uuid,%s::uuid,'llm/message',%s::jsonb,%s::uuid)",
                     (sid, str(uuid.uuid4()), Json({"origin_user_seq": q1(route, "SELECT v13_last_user_seq(%s)", (sid,)), "text": "old"}), eid))
        route.commit()
        with owner.cursor() as cur:
            cur.execute("UPDATE v13_registry_clock SET revision=revision+1 WHERE singleton")
        owner.commit()
        q1(route, STRICT, completion_args(claim))
        route.commit()
        gate.check("W4: superseded llm/message alone does not finish",
                   q1(route, "SELECT v13_route(%s,'{}'::jsonb)->>'action'", (sid,)) != "finish")
        route.commit()
        _, current_eid = ready(owner, sid)
        current_claim = q1(route, "SELECT public.v13_claim('w4-current')")
        route.commit()
        late_old_seq = q1(route, "SELECT public.v13_append_event(%s::uuid,%s::uuid,'tool/result',%s::jsonb,%s::uuid)",
                           (sid, str(uuid.uuid4()), Json({"origin_user_seq": q1(route, "SELECT v13_last_user_seq(%s)", (sid,)), "result": "old"}), eid))
        route.commit()
        current_seq = q1(route, "SELECT public.v13_append_event(%s::uuid,%s::uuid,'llm/message',%s::jsonb,%s::uuid)",
                         (sid, str(uuid.uuid4()), Json({"origin_user_seq": q1(route, "SELECT v13_last_user_seq(%s)", (sid,)), "text": "current"}), current_eid))
        route.commit()
        q1(route, STRICT, completion_args(current_claim))
        route.commit()
        gate.check("W4: superseded event helper false, new-pin event true",
                   q1(route, "SELECT v13_effect_context_event_current(%s,%s) IS FALSE AND v13_effect_context_event_current(%s,%s) IS TRUE",
                      (sid, late_old_seq, sid, current_seq)) is True)
        route_result = q1(route, "SELECT public.v13_route(%s,'{}'::jsonb)", (sid,))
        gate.check("W4: late superseded tool/result does not mask current llm finish",
                   route_result.get("action") == "finish", route_result)
        state = q1(route, "SELECT v13_canonical_state(%s)", (sid,))
        gate.check("W4: canonical state excludes old current-turn machine event",
                   all(message["seq"] not in {old_seq, late_old_seq} for message in state["messages"]), state)
        gate.check("W4: canonical state retains current mapped message",
                   any(message["seq"] == current_seq for message in state["messages"]), state)
        route.commit()
        legacy_seq = q1(route, "SELECT v13_append_event(%s::uuid,%s::uuid,'llm/message',%s::jsonb,NULL::uuid)",
                        (sid, str(uuid.uuid4()), Json({"origin_user_seq": q1(route, "SELECT v13_last_user_seq(%s)", (sid,)), "text": "legacy"})))
        route.commit()
        gate.check("W4: unpinned legacy machine event remains projection eligible",
                   q1(route, "SELECT v13_effect_context_event_current(%s,%s)", (sid, legacy_seq)) is True)
        gate.check("W4: legacy message still finishes route",
                   q1(route, "SELECT v13_route(%s,'{}'::jsonb)->>'action'", (sid,)) == "finish")
        user_seq = q1(route, "SELECT v13_append_event(%s::uuid,%s::uuid,'user/message','{\"text\":\"next\"}')",
                      (sid, str(uuid.uuid4())))
        state = q1(route, "SELECT v13_canonical_state(%s)", (sid,))
        gate.check("W4: superseded messages remain visible as historical audit",
                   {old_seq, late_old_seq, user_seq}.issubset({m["seq"] for m in state["messages"]}), state)
        route.commit()
    with gate.connection(setup, database, "recall") as recall:
        gate.check("W4: recall can read canonical state through narrow event helper ACL",
                   q1(recall, "SELECT v13_canonical_state(%s)->'derived'", (sid,)) is not None)
        gate.rejected(recall, "SELECT * FROM v13_effect_context_event_pins")


def w4_session(conn):
    q1(conn, "SELECT set_config('typesafe.provider','fake',false)")
    q1(conn, "SELECT set_config('typesafe.model','fake',false)")
    sid = str(q1(conn, "SELECT v13_open_session('{}')"))
    q1(conn, "SELECT v13_append_event(%s::uuid,%s::uuid,'user/message','{\"text\":\"w4\"}')",
       (sid, str(uuid.uuid4())))
    return sid


def w4_effect(conn, sid, kind, request, result=None, tool=None, pinned=True, status="succeeded"):
    eid = str(q1(conn, "SELECT v13_enqueue_effect(%s,%s,%s::jsonb,%s)", (sid, kind, Json(request), tool)))
    token = qrow(conn, "UPDATE effects SET status='claimed',attempt_no=attempt_no+1,fence=fence+1 "
                 "WHERE effect_id=%s RETURNING attempt_no,fence", (eid,))
    revision, tools_revision = qrow(conn, "SELECT * FROM v13_registry_fences()")
    if pinned:
        q1(conn, "SELECT v13_effect_context_pin_insert(%s,%s,%s,%s,%s,%s)",
           (eid, *token, sid, revision, tools_revision))
    args = (eid, *token, status, None if result is None else Json(result))
    settled = q1(conn, STRICT, (*args, revision)) if pinned else q1(
        conn, "SELECT v13_complete(%s::uuid,%s,%s::bigint,%s,%s::jsonb)", args)
    if settled != "accepted":
        raise AssertionError((eid, settled))
    return eid


def w4_harness(conn, sid, result, pinned=True, logical_turn=None, index=0):
    revision = q1(conn, "SELECT tools_revision FROM v13_registry_fences()")
    request = {"tool": "harness_turn", "params": {}, "handler": "worker:harness_turn",
               "tools_revision": revision, "logical_turn_id": logical_turn or str(uuid.uuid4()),
               "continuation_index": index}
    return w4_effect(conn, sid, "tool", request, result, "harness_turn", pinned)


def w4_bump(conn, tools=False):
    with conn.cursor() as cur:
        cur.execute("UPDATE " + ("v13_tools_meta" if tools else "v13_registry_clock") +
                    " SET revision=revision+1 WHERE singleton")


def w4_raises(gate, conn, label, statement, args=(), text=None):
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT w4_expected")
        try:
            cur.execute(statement, args)
        except psycopg2.Error as exc:
            cur.execute("ROLLBACK TO SAVEPOINT w4_expected")
            gate.check(label, exc.pgcode == "P0001" and (text is None or text in str(exc)), str(exc))
        else:
            raise AssertionError(label + ": expected failure")
        finally:
            cur.execute("RELEASE SAVEPOINT w4_expected")


def w4_batch(conn, sid, failed=False):
    env = q1(conn, "SELECT v13_judgment_envelope(%s)", (sid,))
    snap = q1(conn, "SELECT v13_snap_of(%s::jsonb)", (Json(env),))
    return Json({"snap": snap, "envelope": env, "remaining": 0, "failed": failed, "abandon": False})


def native_w4_control(gate, setup, database):
    with gate.connection(setup, database, "owner") as conn:
        # Roll back each probe group so clock/policy changes and effects cannot leak.
        for signal in ("repair/required", "replan/required"):
            sid = w4_session(conn)
            eid = w4_harness(conn, sid, {"result_kind": "progress", "signals": [signal]})
            gate.check("W4: current signal drives triage fold " + signal,
                       q1(conn, "SELECT v13_triage_fold_reason(%s)", (sid,)) == signal.split('/')[0] + "_cap")
            w4_raises(gate, conn, "W4: current signal creates tail gap", "SELECT v13_harness_tail_gap(%s,NULL)",
                      (sid,), "harness tail gap")
            pending = q1(conn, "SELECT v13_recover_idle()")
            gate.check("W4: current signal creates recover nudge", sid in pending["pending"], pending)
            w4_raises(gate, conn, "W4: current signal blocks closeout with continuation owed",
                      "SELECT v13_closeout(%s,'completed','w4',false)", (sid,), "continuation owed")
            w4_bump(conn)
            gate.check("W4: superseded signal does not fold", q1(conn, "SELECT v13_triage_fold_reason(%s)", (sid,)) is None)
            q1(conn, "SELECT v13_harness_tail_gap(%s,NULL)", (sid,))
            gate.check("W4: superseded signal makes no recover pending",
                       sid not in q1(conn, "SELECT v13_recover_idle()")["pending"])
            receipt = q1(conn, "SELECT v13_closeout(%s,'completed','w4',false)", (sid,))
            gate.check("W4: old repair/replan excluded from receipt",
                       all(not value for value in receipt["unconsumed"].values()), receipt)
            conn.rollback()

            sid = w4_session(conn)
            legacy = w4_harness(conn, sid, {"result_kind": "progress", "signals": [signal]}, pinned=False)
            w4_bump(conn)
            gate.check("W4: legacy signal still folds " + signal,
                       q1(conn, "SELECT v13_triage_fold_reason(%s)", (sid,)) == signal.split('/')[0] + "_cap")
            w4_raises(gate, conn, "W4: legacy signal still creates tail gap", "SELECT v13_harness_tail_gap(%s,NULL)",
                      (sid,), "harness tail gap")
            gate.check("W4: legacy signal still recovers", sid in q1(conn, "SELECT v13_recover_idle()")["pending"])
            w4_raises(gate, conn, "W4: legacy continuation still blocks closeout",
                      "SELECT v13_closeout(%s,'completed','w4',false)", (sid,), "continuation owed")
            receipt = q1(conn, "SELECT v13_closeout(%s,'cancelled','w4',false)", (sid,))
            gate.check("W4: legacy signal remains in closeout receipt",
                       legacy in receipt["unconsumed"][signal.split('/')[0] + "_effect_ids"], receipt)
            conn.rollback()

        # Synthetic frontier replan has a source UUID with no effects/pins history.
        sid = w4_session(conn)
        q1(conn, "SELECT v13_append_event(%s::uuid,%s::uuid,'replan/required','{\"schema_version\":1}',%s::uuid)",
           (sid, str(uuid.uuid4()), str(uuid.uuid4())))
        gate.check("W4: synthetic replan remains eligible", q1(conn, "SELECT v13_triage_fold_reason(%s)", (sid,)) == "replan_cap")
        conn.rollback()

        # Legacy predecessor survives a newer superseded predecessor: filter BEFORE latest.
        sid = w4_session(conn)
        current = w4_harness(conn, sid, {"result_kind": "finish"}, pinned=False)
        old = w4_harness(conn, sid, {"result_kind": "reject"})
        w4_bump(conn)
        word = q1(conn, "SELECT v13_advance(%s,%s::jsonb)", (sid, w4_batch(conn, sid)))
        gate.check("W4: advance selects eligible predecessor before newest old reject",
                   word == "terminal" and q1(conn, "SELECT status FROM sessions WHERE session_id=%s", (sid,)) == "completed", word)
        gate.check("W4: advance spends current material only", q1(conn,
                   "SELECT array_agg(source_effect_id::text) FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,)) == [current])
        conn.rollback()

        # A superseded finish/wait must not leave material/wake/approval debt.
        for result in ({"result_kind": "finish"},
                       {"result_kind": "wait", "wait_reason": "approval", "interaction_id": "w4-approval"},
                       {"result_kind": "wait", "wait_reason": "evidence", "wake": {"kind": "event", "event_type": "user/message"}}):
            sid = w4_session(conn)
            w4_harness(conn, sid, result)
            w4_bump(conn)
            receipt = q1(conn, "SELECT v13_closeout(%s,'completed','w4',false)", (sid,))
            gate.check("W4: superseded harness result leaves no closeout debt " + result["result_kind"],
                       all(not value for value in receipt["unconsumed"].values()), receipt)
            conn.rollback()


def native_w4_human(gate, setup, database):
    with gate.connection(setup, database, "owner") as conn:
        for legacy_shape in (False, True):
            sid = w4_session(conn)
            pred = w4_harness(conn, sid, {"result_kind": "progress", "signals": ["repair/required"]}, pinned=False)
            request = ({"reason": "repair_cap"} if legacy_shape else
                       {"interaction_kind": "repair_cap", "interaction_ref": "w4-answer"})
            result = ({"response": "ok"} if legacy_shape else
                      {"schema_version": 1, "interaction_ref": "w4-answer", "response": "ok"})
            h = w4_effect(conn, sid, "human", request, result)
            gate.check("W4: current human releases cap", q1(conn, "SELECT v13_cap_human_answered(%s,%s)", (sid, pred)) is True)
            if not legacy_shape:
                payload = q1(conn, "SELECT payload FROM events WHERE source_effect_id=%s AND type='human/responded'", (h,))
                gate.check("W4: human responded exact six-key payload unchanged",
                           set(payload) == {"schema_version","interaction_ref","skip","response","answers","origin_user_seq"}
                           and payload["schema_version"] == 1 and payload["interaction_ref"] == "w4-answer"
                           and payload["response"] == "ok" and payload["skip"] is None and payload["answers"] is None
                           and payload["origin_user_seq"] == q1(conn,"SELECT v13_last_user_seq(%s)",(sid,)), payload)
            w4_bump(conn, tools=True)
            gate.check("W4: tools-superseded human does not release cap", q1(conn,
                       "SELECT v13_cap_human_answered(%s,%s)", (sid, pred)) is False)
            gate.check("W4: tools-superseded human is not an anchor", q1(conn,
                       "SELECT count(*) FROM v13_cap_answer_anchor(%s,%s)", (sid, pred)) == 0)
            ref = str(uuid.uuid4())
            w4_effect(conn, sid, "human", {"interaction_kind": "repair_cap", "interaction_ref": ref},
                      {"schema_version": 1, "interaction_ref": ref, "response": "ok"}, pinned=False)
            gate.check("W4: unpinned legacy human still releases cap", q1(conn,
                       "SELECT v13_cap_human_answered(%s,%s)", (sid,pred)) is True)
            conn.rollback()


def native_w4_tool_parse(gate, setup, database):
    with gate.connection(setup, database, "owner") as conn:
        sid = w4_session(conn)
        calls = [{"id": "w4-call-" + str(i), "name": "spawn_subsession", "args": {"task": "w4-child"}} for i in range(2)]
        w4_policy(conn, "spawn_budget", {"max_nonterminal": 8, "max_depth": 4, "max_fanout": 1})
        w4_effect(conn, sid, "llm", {"route": {"action": "llm", "reason": "explore"}},
                  {"text": "planning", "tool_calls": calls})
        w4_raises(gate, conn, "W4: current explore call triggers spawn guard",
                  "SELECT v13_triage_block_explore_spawn(%s)", (sid,), "explore spawn")
        gate.check("W4: current tool calls make scheduler wait", q1(conn, "SELECT v13_scheduler_hint(%s)", (sid,)) == "wait")
        w4_bump(conn)
        q1(conn, "SELECT v13_triage_block_explore_spawn(%s)", (sid,))
        gate.check("W4: superseded tool calls do not force scheduler wait", q1(conn, "SELECT v13_scheduler_hint(%s)", (sid,)) == "run_now")
        word = q1(conn, "SELECT v13_advance(%s,%s::jsonb)", (sid, w4_batch(conn, sid, failed=True)))
        gate.check("W4: superseded tool/call never spawns children", q1(conn,
                   "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,)) == 0, word)
        conn.rollback()

        # The same unpinned call still trips the explore guard.
        sid = w4_session(conn)
        w4_policy(conn, "spawn_budget", {"max_nonterminal": 8, "max_depth": 4, "max_fanout": 1})
        w4_effect(conn, sid, "llm", {"route": {"action": "llm", "reason": "explore"}},
                  {"text": "planning", "tool_calls": calls}, pinned=False)
        w4_bump(conn)
        w4_raises(gate, conn, "W4: legacy explore call retains guard",
                  "SELECT v13_triage_block_explore_spawn(%s)", (sid,), "explore spawn")
        gate.check("W4: legacy tool calls retain scheduler wait", q1(conn, "SELECT v13_scheduler_hint(%s)", (sid,)) == "wait")
        conn.rollback()

        # Parse uses a no-IO resolver stub; only failure budget behavior is under test.
        with conn.cursor() as cur:
            cur.execute("CREATE OR REPLACE FUNCTION v13_resolve_judgments(p_env jsonb, p_max_batches integer DEFAULT 1) "
                        "RETURNS jsonb LANGUAGE plpgsql AS $$ BEGIN RETURN "
                        "'{\"asked_questions\":0,\"asked_batches\":0,\"remaining\":0,\"failed\":false}'::jsonb; END $$")
        sid = w4_session(conn)
        cap = q1(conn, "SELECT (v13_policy('resolve_retry')->>'cap')::int")
        for _ in range(cap):
            _, eid = ready_uncommitted(conn, sid)
            token = qrow(conn, "UPDATE effects SET status='claimed',attempt_no=1,fence=1 WHERE effect_id=%s RETURNING attempt_no,fence", (eid,))
            revision, tools_revision = qrow(conn, "SELECT * FROM v13_registry_fences()")
            q1(conn, "SELECT v13_effect_context_pin_insert(%s,%s,%s,%s,%s,%s)", (eid,*token,sid,revision,tools_revision))
            q1(conn, STRICT, (eid,*token,"failed",None,revision))
        gate.check("W4: current judge failures exhaust retry budget",
                   q1(conn, "SELECT v13_parse(%s)->'abandon'", (sid,)) is True)
        w4_bump(conn)
        gate.check("W4: superseded judge failures do not exhaust retry budget",
                   q1(conn, "SELECT v13_parse(%s)->'abandon'", (sid,)) is False)
        for _ in range(cap):
            q1(conn, "SELECT v13_append_event(%s::uuid,%s::uuid,'resolve/failed',jsonb_build_object('origin_user_seq',v13_last_user_seq(%s)))",
               (sid,str(uuid.uuid4()),sid))
        gate.check("W4: synthetic advance failures retain retry budget semantics",
                   q1(conn, "SELECT v13_parse(%s)->'abandon'", (sid,)) is True)
        sid = w4_session(conn)
        for i in range(cap):
            w4_effect(conn, sid, "judge", {"w4_legacy": i}, status="failed", pinned=False)
        w4_bump(conn)
        gate.check("W4: legacy unpinned judge failures retain retry semantics",
                   q1(conn, "SELECT v13_parse(%s)->'abandon'", (sid,)) is True)
        conn.rollback()


def w4_policy(conn, name, value):
    version = q1(conn, "SELECT max(version)+1 FROM v13_policies WHERE name=%s", (name,))
    with conn.cursor() as cur:
        cur.execute("UPDATE v13_policies SET active=false WHERE name=%s AND active", (name,))
        cur.execute("INSERT INTO v13_policies(name,version,value,active) VALUES (%s,%s,%s,true)", (name,version,Json(value)))


def ready_uncommitted(conn, sid):
    eid = str(uuid.uuid4())
    ous = q1(conn, "SELECT v13_last_user_seq(%s)", (sid,))
    with conn.cursor() as cur:
        cur.execute("INSERT INTO effects(effect_id,session_id,kind,request,request_hash,origin_user_seq) "
                    "VALUES (%s,%s,'judge','{}',encode(digest('{}','sha256'),'hex'),%s)", (eid,sid,ous))
    return sid, eid


def native_freshness(gate, setup, database):
    with gate.connection(setup, database, "owner") as owner, \
         gate.connection(setup, database, "owner") as writer:
        sid = str(q1(owner, "SELECT v13_open_session('{}'::jsonb)"))
        unrelated = str(q1(owner, "SELECT v13_open_session('{}'::jsonb)"))
        q1(owner, "SELECT set_config('typesafe.provider','fake',false)")
        q1(owner, "SELECT set_config('typesafe.model','fake',false)")
        owner.commit()
        env = q1(owner, "SELECT v13_judgment_envelope(%s)", (sid,))
        probe = q1(owner, "SELECT v13_probe(%s)", (sid,))
        snap = q1(owner, "SELECT v13_snap_of(%s::jsonb)", (Json(env),))
        gate.check("native_envelope_snapshot_consistency: exact 21-key envelope", set(env) == ENVELOPE_KEYS, set(env))
        gate.check("native_envelope_snapshot_consistency: exact eight-key probe", set(probe) == FRESH_KEYS, probe)
        gate.check("native_envelope_snapshot_consistency: snap only projects supplied revision",
                   snap["registry_revision"] == str(env["registry_revision"]))
        old_request = q1(owner, "SELECT v13_effect_envelope(%s::jsonb)", (Json(env),))
        old_id = q1(owner, "SELECT v13_effect_id(%s,'judge',jsonb_build_object('envelope',%s::jsonb))",
                    (sid, Json(old_request)))
        owner.commit()
        # Separate committed writer demonstrates global invalidation across scopes.
        q1(writer, "SELECT v13_registry_register(%s,'service','freshness','{\"provides\":[\"fake\"]}',ARRAY[]::text[])", (unrelated,))
        writer.commit()
        after = q1(owner, "SELECT v13_probe(%s)", (sid,))
        gate.check("native_global_freshness: unrelated scope changes only eighth key",
                   after["registry_revision"] > probe["registry_revision"] and
                   {k:v for k,v in after.items() if k != "registry_revision"} ==
                   {k:v for k,v in probe.items() if k != "registry_revision"}, (probe, after))
        gate.check("native_envelope_snapshot_consistency: old envelope snap never rereads clock",
                   q1(owner, "SELECT v13_snap_of(%s::jsonb)->>'registry_revision'", (Json(env),)) == str(env["registry_revision"]))
        current_env = q1(owner, "SELECT v13_judgment_envelope(%s)", (sid,))
        current_request = q1(owner, "SELECT v13_effect_envelope(%s::jsonb)", (Json(current_env),))
        gate.check("native_global_freshness: effect envelope excludes freshness",
                   "registry_revision" not in current_request and old_request == current_request)
        gate.check("native_global_freshness: logical judge effect identity remains stable",
                   q1(owner, "SELECT v13_effect_id(%s,'judge',jsonb_build_object('envelope',%s::jsonb))",
                      (sid, Json(current_request))) == old_id)
        batch = {"snap":snap, "envelope":env}
        gate.check("native_global_freshness: eighth-key stale advance",
                   q1(owner, "SELECT v13_advance(%s,%s::jsonb)", (sid, Json(batch))) == "stale")
        batch["snap"].pop("registry_revision")
        gate.check("native_global_freshness: missing eighth key is stale",
                   q1(owner, "SELECT v13_advance(%s,%s::jsonb)", (sid, Json(batch))) == "stale")
        owner.commit()
        with owner.cursor() as cur:
            cur.execute("SAVEPOINT missing_seed")
            cur.execute("DELETE FROM v13_registry_clock")
            for statement in ("SELECT v13_probe(%s)", "SELECT v13_judgment_envelope(%s)", "SELECT v13_claim(%s)"):
                cur.execute("SAVEPOINT fail_closed")
                try:
                    cur.execute(statement, (sid,))
                except psycopg2.Error as exc:
                    cur.execute("ROLLBACK TO SAVEPOINT fail_closed")
                    gate.check("native_global_freshness: missing clock fails closed", exc.pgcode == "P0001", exc.pgcode)
                else:
                    gate.check("missing clock must fail closed", False, statement)
            cur.execute("ROLLBACK TO SAVEPOINT missing_seed")
        owner.rollback()


def expected_error(gate, conn, label, statement, args=(), code="P0001"):
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT consumer_expected")
        try:
            cur.execute(statement, args)
        except psycopg2.Error as exc:
            cur.execute("ROLLBACK TO SAVEPOINT consumer_expected")
            gate.check(label, exc.pgcode == code, (exc.pgcode, str(exc)))
        else:
            raise AssertionError(label + ": expected " + code)
        finally:
            cur.execute("RELEASE SAVEPOINT consumer_expected")


class SQLCall:
    """A real backend, with bounded waits and rollback/close even on assertion failure."""
    def __init__(self, conn, statement, args=()):
        self.conn = conn
        self.pid = conn.get_backend_pid()
        self.result = None
        self.error = None
        self.finished = threading.Event()
        self.statement, self.args = statement, args
        self.thread = threading.Thread(target=self.run)

    def run(self):
        try:
            with self.conn:
                with self.conn.cursor() as cur:
                    cur.execute("SET statement_timeout='15s'")
                    cur.execute(self.statement, self.args)
                    self.result = cur.fetchone()
        except BaseException as exc:
            self.error = exc
        finally:
            self.finished.set()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        if not self.finished.is_set():
            self.conn.cancel()
        self.thread.join(timeout=20)
        self.conn.close()
        if self.thread.is_alive():
            raise RuntimeError("consumer backend did not terminate")

    def done(self, gate, label):
        gate.check(label + ": finishes within bound", self.finished.wait(10))
        gate.check(label + ": no backend error", self.error is None, repr(self.error))
        return self.result[0]


def lock_barrier(gate, observer, call, blocker, locktype="transactionid"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        blocked, waiting = qrow(observer,
            "SELECT %s=ANY(pg_blocking_pids(%s)), EXISTS (SELECT 1 FROM pg_locks "
            "WHERE pid=%s AND locktype=%s AND NOT granted)",
            (blocker, call.pid, call.pid, locktype))
        if blocked and waiting:
            gate.check("native_lock_barriers: exact PID blocker and ungranted " + locktype,
                       not call.finished.is_set(), (call.pid, blocker))
            return
        if call.finished.wait(0.01):
            raise AssertionError(("backend did not reach barrier", call.result, repr(call.error)))
    raise TimeoutError("PostgreSQL lock barrier not observed")


def native_worker_protocol(gate, setup, database):
    with (gate.connection(setup, database, "owner") as owner,
          gate.connection(setup, database, "owner") as writer,
          gate.connection(setup, database, "worker") as worker):
        other = str(q1(owner, "SELECT v13_open_session('{}')"))
        owner.commit()
        for statement in ("SELECT * FROM v13_effect_context_pin_lookup(%s,1,1)",
                          "SELECT v13_registry_context(%s)",
                          "SELECT * FROM v13_registry_fences()"):
            gate.rejected(worker, statement, () if "fences" in statement else (other,))
        for fair in (False, True):
            identity = "owner" if fair else "route"
            for change in (None, "registry", "tools"):
                sid, eid = ready(owner)
                with gate.connection(setup, database, identity) as adapter:
                    gate.check("native_worker_protocol: adapter begins IDLE", adapter.get_transaction_status() == TRANSACTION_STATUS_IDLE)
                    claim = q1(adapter, "SELECT " + ("v13_claim_fair" if fair else "v13_claim") + "('protocol')")
                    gate.check("native_worker_protocol: correct claim identity and target", claim["effect_id"] == eid, claim)
                    pin = qrow(adapter, "SELECT * FROM v13_effect_context_pin_lookup(%s,%s,%s)",
                               (eid,claim["attempt_no"],claim["fence"]))
                    context = q1(adapter, "SELECT v13_registry_context(%s,%s)", (sid,pin[1]))
                    cache_key = (pin[0],pin[1],pin[2])
                    gate.check("native_worker_protocol: pinned context and three-part cache key",
                               cache_key == (sid,claim["context_revision"],context["tools_revision"])
                               and context["revision"] == pin[1], (cache_key, context))
                    if change == "registry":
                        q1(writer, "SELECT v13_registry_register(%s,'service',%s,'{\"provides\":[\"fake\"]}',ARRAY[]::text[])",
                           (other,str(uuid.uuid4())))
                        writer.commit()
                    elif change == "tools":
                        w4_bump(writer, tools=True)
                        writer.commit()
                    fences = qrow(adapter, "SELECT * FROM v13_registry_fences()")
                    if fences != pin[1:]:
                        adapter.rollback()
                        gate.check("native_worker_protocol: precommit " + change + " change rolls back claim",
                                   qrow(owner, "SELECT status,attempt_no,fence FROM effects WHERE effect_id=%s", (eid,)) == ("ready",0,0))
                        gate.check("native_worker_protocol: rollback leaves no pin", q1(owner,
                                   "SELECT count(*) FROM v13_effect_context_pins WHERE effect_id=%s", (eid,)) == 0)
                        with owner.cursor() as cur:
                            cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
                        owner.commit()
                    else:
                        gate.check("native_worker_protocol: both fences rechecked before commit", change is None)
                        adapter.commit()
                        # This fake is the only worker-IO stand-in; no provider or socket.
                        def fake_io():
                            gate.check("native_worker_protocol: fake IO runs only after commit/IDLE",
                                       adapter.get_transaction_status() == TRANSACTION_STATUS_IDLE)
                            return {"cache_key": cache_key}
                        gate.check("native_worker_protocol: fake uses exact cached context", fake_io()["cache_key"] == cache_key)
                        gate.check("native_worker_protocol: separate strict completion transaction",
                                   q1(adapter, STRICT, completion_args(claim)) == "accepted")
                        adapter.commit()


def native_event_pin_atomicity(gate, setup, database):
    with gate.connection(setup, database, "owner") as conn:
        sid = w4_session(conn)
        _, eid = ready_uncommitted(conn, sid)
        q1(conn, "UPDATE effects SET status='claimed',attempt_no=1,fence=1 WHERE effect_id=%s RETURNING 1", (eid,))
        revision, tools = qrow(conn, "SELECT * FROM v13_registry_fences()")
        pin_args = (eid,1,1,sid,revision,tools)
        q1(conn, "SELECT v13_effect_context_pin_insert(%s,%s,%s,%s,%s,%s)", pin_args)
        expected_error(gate, conn, "native_event_pin_atomicity: duplicate pin rejected", "SELECT v13_effect_context_pin_insert(%s,%s,%s,%s,%s,%s)", pin_args, "23505")
        before = qrow(conn, "SELECT next_seq,(SELECT count(*) FROM events WHERE session_id=%s) FROM sessions WHERE session_id=%s", (sid,sid))
        with conn.cursor() as cur:
            cur.execute("CREATE FUNCTION consumer_mapping_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'mapping failure injection'; END $$")
            cur.execute("CREATE TRIGGER consumer_mapping_fail BEFORE INSERT ON v13_effect_context_event_pins FOR EACH ROW EXECUTE FUNCTION consumer_mapping_fail()")
        expected_error(gate, conn, "native_event_pin_atomicity: capture failure propagates", STRICT, (eid,1,1,"failed",None,revision))
        gate.check("native_event_pin_atomicity: failed completion restores status, events, sequence and mapping",
                   q1(conn, "SELECT status FROM effects WHERE effect_id=%s", (eid,)) == "claimed"
                   and qrow(conn, "SELECT next_seq,(SELECT count(*) FROM events WHERE session_id=%s) FROM sessions WHERE session_id=%s", (sid,sid)) == before
                   and q1(conn, "SELECT count(*) FROM v13_effect_context_event_pins WHERE effect_id=%s", (eid,)) == 0)
        with conn.cursor() as cur:
            cur.execute("DROP TRIGGER consumer_mapping_fail ON v13_effect_context_event_pins")
            cur.execute("DROP FUNCTION consumer_mapping_fail()")
        seq1 = q1(conn, "SELECT v13_append_event(%s,%s,'llm/message','{}',%s)", (sid,str(uuid.uuid4()),eid))
        expected_error(gate, conn, "native_event_pin_atomicity: duplicate mapping rejected",
                       "INSERT INTO v13_effect_context_event_pins VALUES (%s,%s,%s,1,1)", (sid,seq1,eid), "23505")
        for table, operation in (("v13_effect_context_pins","UPDATE"), ("v13_effect_context_pins","DELETE"),
                                 ("v13_effect_context_event_pins","UPDATE"), ("v13_effect_context_event_pins","DELETE")):
            statement = ("UPDATE " + table + " SET fence=fence WHERE effect_id=%s" if operation == "UPDATE"
                         else "DELETE FROM " + table + " WHERE effect_id=%s")
            expected_error(gate, conn, "native_event_pin_atomicity: immutable " + table + " " + operation, statement, (eid,))
        w4_bump(conn)
        q1(conn, "UPDATE effects SET attempt_no=2,fence=2 WHERE effect_id=%s RETURNING 1", (eid,))
        new_revision = q1(conn, "SELECT registry_revision FROM v13_registry_fences()")
        q1(conn, "SELECT v13_effect_context_pin_insert(%s,2,2,%s,%s,%s)", (eid,sid,new_revision,tools))
        seq2 = q1(conn, "SELECT v13_append_event(%s,%s,'llm/message','{}',%s)", (sid,str(uuid.uuid4()),eid))
        gate.check("native_event_pin_atomicity: reclaim keeps exact old/new attempt and fence",
                   qrow(conn, "SELECT attempt_no,fence FROM v13_effect_context_event_pins WHERE session_id=%s AND event_seq=%s", (sid,seq1)) == (1,1)
                   and qrow(conn, "SELECT attempt_no,fence FROM v13_effect_context_event_pins WHERE session_id=%s AND event_seq=%s", (sid,seq2)) == (2,2))
        gate.check("native_event_pin_atomicity: old event never guesses newest pin",
                   qrow(conn, "SELECT v13_effect_context_event_current(%s,%s),v13_effect_context_event_current(%s,%s)", (sid,seq1,sid,seq2)) == (False,True))
        # Missing capture and corrupt source are isolated fault injections, rolled back below.
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE events DISABLE TRIGGER trg_v13_effect_context_event_capture")
        missing = q1(conn, "SELECT v13_append_event(%s,%s,'llm/message','{}',%s)", (sid,str(uuid.uuid4()),eid))
        expected_error(gate, conn, "native_event_pin_atomicity: mapping source mismatch rejected",
                       "INSERT INTO v13_effect_context_event_pins VALUES (%s,%s,%s,2,2)", (sid,missing,str(uuid.uuid4())), "23514")
        gate.check("native_event_pin_atomicity: missing mapping fails closed without RAISE",
                   q1(conn, "SELECT v13_effect_context_event_current(%s,%s)", (sid,missing)) is False)
        foreign_sid = w4_session(conn)
        _, foreign_eid = ready_uncommitted(conn, foreign_sid)
        q1(conn, "UPDATE effects SET status='claimed',attempt_no=1,fence=1 WHERE effect_id=%s RETURNING 1", (foreign_eid,))
        q1(conn, "SELECT v13_effect_context_pin_insert(%s,1,1,%s,%s,%s)", (foreign_eid,foreign_sid,new_revision,tools))
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE v13_effect_context_event_pins DISABLE TRIGGER trg_v13_effect_context_event_pin_frozen")
            cur.execute("INSERT INTO v13_effect_context_event_pins VALUES (%s,%s,%s,1,1)", (sid,missing,foreign_eid))
        gate.check("native_event_pin_atomicity: malformed source/scope mapping fails closed",
                   q1(conn, "SELECT v13_effect_context_event_current(%s,%s)", (sid,missing)) is False)
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE events ENABLE TRIGGER trg_v13_effect_context_event_capture")
        q1(conn, "UPDATE effects SET attempt_no=3,fence=3 WHERE effect_id=%s RETURNING 1", (eid,))
        unmapped = q1(conn, "SELECT v13_append_event(%s,%s,'llm/message','{}',%s)", (sid,str(uuid.uuid4()),eid))
        gate.check("native_event_pin_atomicity: pin history but no exact token is ineligible",
                   q1(conn, "SELECT v13_effect_context_event_current(%s,%s)", (sid,unmapped)) is False
                   and q1(conn, "SELECT v13_effect_context_effect_current(%s)", (eid,)) is False)
        for typ, payload in (("tool/call", {"schema_version":1,"id":"x","name":"other","args":{}}),
                             ("repair/required", {"schema_version":1,"extra":True}),
                             ("human/responded", {"schema_version":1,"response":"ok"})):
            expected_error(gate, conn, "native_event_pin_atomicity: payload guard unchanged " + typ,
                           "SELECT v13_append_event(%s,%s,%s,%s::jsonb)", (sid,str(uuid.uuid4()),typ,Json(payload)))
        conn.rollback()


def native_actual_tool_spawn(gate, setup, database):
    with gate.connection(setup, database, "owner") as conn:
        for pinned, superseded in ((True,False),(True,True),(False,True)):
            sid = w4_session(conn)
            q1(conn, "UPDATE sessions SET context_active_revision=v13_context_required(session_id) WHERE session_id=%s RETURNING 1", (sid,))
            calls = [{"id":"actual-child","name":"spawn_subsession","args":{"task":"consumer-child"}}]
            w4_effect(conn,sid,"llm",{"route":{"action":"llm","reason":"answer"}},
                      {"text":"spawn","tool_calls":calls},pinned=pinned)
            if superseded:
                w4_bump(conn)
            word = q1(conn, "SELECT v13_advance(%s,%s::jsonb)", (sid,w4_batch(conn,sid,failed=True)))
            children = q1(conn, "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,))
            spawn_effects = q1(conn, "SELECT count(*) FROM effects WHERE session_id=%s AND tool_name='spawn_subsession' AND status='succeeded'", (sid,))
            expected = 0 if pinned and superseded else 1
            gate.check("native_tool_call_projection: actual child + settled spawn effect " + str((pinned,superseded)),
                       children == spawn_effects == expected, (word,children,spawn_effects))
            gate.check("native_tool_call_projection: actual spawn receipt agrees",
                       q1(conn, "SELECT count(*) FROM events WHERE session_id=%s AND type='child-created'", (sid,)) == expected)
            if expected:
                gate.check("native_tool_call_projection: eligible tool call advances before failed branch", word == "progressed", word)
            if expected:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL ROLE v13_spawn_owner")
                gate.check("native_tool_call_projection: spawn_owner canonical chain executes without broad grants",
                           q1(conn,"SELECT v13_canonical_state(%s)",(sid,)) is not None)
                with conn.cursor() as cur:
                    cur.execute("RESET ROLE")
            conn.rollback()


def native_plan_signal_evidence(gate, setup, database):
    with gate.connection(setup,database,"owner") as conn:
        for signal in ("repair/required","replan/required"):
            for old in (False,True):
                sid = w4_session(conn)
                turn = str(uuid.uuid4())
                w4_harness(conn,sid,{"result_kind":"progress","signals":[signal]},logical_turn=turn)
                if old:
                    w4_bump(conn)
                word = q1(conn,"SELECT v13_advance(%s,%s::jsonb)",(sid,w4_batch(conn,sid,failed=True)))
                continuations = q1(conn,"SELECT count(*) FROM effects WHERE session_id=%s AND request->>'logical_turn_id'=%s AND request->>'continuation_index'='1'",(sid,turn))
                gate.check("native_repair_replan_projection: actual advance continuation " + str((signal,old)),
                           continuations == (0 if old else 1), (word,continuations))
                conn.rollback()
            sid = w4_session(conn)
            pred = w4_harness(conn,sid,{"result_kind":"progress","signals":[signal]})
            ref = str(uuid.uuid4())
            w4_effect(conn,sid,"human",{"interaction_kind":signal.split('/')[0]+"_cap","interaction_ref":ref},
                      {"schema_version":1,"interaction_ref":ref,"response":"ok"},pinned=False)
            w4_harness(conn,sid,{"result_kind":"finish"},pinned=False)
            gate.check("native_repair_replan_projection: current signal makes cap exemption",
                       q1(conn,"SELECT v13_tail_gap_cap_exempt(%s,%s)",(sid,pred)) is True)
            w4_bump(conn)
            gate.check("native_repair_replan_projection: superseded signal cannot make cap exemption",
                       q1(conn,"SELECT v13_tail_gap_cap_exempt(%s,%s)",(sid,pred)) is False)
            conn.rollback()
        for event_type in ("llm/message","tool/result"):
            for origin in ("current","wrong"):
                sid = w4_session(conn)
                eid = w4_effect(conn,sid,"judge",{"projection":event_type},status="failed")
                ous = q1(conn,"SELECT v13_last_user_seq(%s)",(sid,))
                if event_type == "tool/result":
                    q1(conn,"SELECT v13_append_event(%s,%s,'llm/message',%s::jsonb)",
                       (sid,str(uuid.uuid4()),Json({"origin_user_seq":ous,"text":"legacy answer"})))
                q1(conn,"SELECT v13_append_event(%s,%s,%s,%s::jsonb,%s)",
                   (sid,str(uuid.uuid4()),event_type,Json({"origin_user_seq":ous if origin == "current" else ous+100,"text":"finish"}),eid))
                result = q1(conn,"SELECT v13_route(%s,'{}')->>'action'",(sid,))
                gate.check("native_route_projection: origin_user_seq preserved " + event_type + " " + origin,
                           (result == "finish") == ((origin == "current") if event_type == "llm/message" else (origin == "wrong")), result)
                w4_bump(conn)
                gate.check("native_route_projection: superseded " + event_type + " does not affect finish selection",
                           (q1(conn,"SELECT v13_route(%s,'{}')->>'action'",(sid,)) == "finish") == (event_type == "tool/result"))
                conn.rollback()


def native_statement_snapshot(gate, setup, database):
    with (gate.connection(setup,database,"owner") as owner,
          gate.connection(setup,database,"owner") as writer):
        sid = w4_session(owner)
        other = w4_session(owner)
        owner.commit()
        old_env = q1(owner,"SELECT v13_judgment_envelope(%s)",(sid,))
        owner.commit()
        q1(owner,"SELECT pg_advisory_lock(1342,1)")
        owner.commit()
        reader = setup.connect_owner_database(database)
        q1(reader,"SELECT set_config('typesafe.provider','fake',false)")
        q1(reader,"SELECT set_config('typesafe.model','fake',false)")
        reader.commit()
        try:
            # MATERIALIZED forces the lock wait after this statement's MVCC snapshot.
            with SQLCall(reader, "WITH barrier AS MATERIALIZED (SELECT pg_advisory_xact_lock(1342,1)) "
                         "SELECT v13_judgment_envelope(%s) FROM barrier", (sid,)) as call:
                lock_barrier(gate,writer,call,owner.get_backend_pid(),"advisory")
                reg = q1(writer,"SELECT v13_registry_register(%s,'service','snapshot','{\"provides\":[\"fake\"]}',ARRAY[]::text[])",(other,))
                w4_bump(writer,tools=True)
                writer.commit()
                q1(owner,"SELECT pg_advisory_unlock(1342,1)")
                owner.commit()
                env = call.done(gate,"native_envelope_snapshot_consistency: blocked statement")
                gate.check("native_envelope_snapshot_consistency: both fences share pre-writer statement snapshot",
                           env["registry_revision"] == old_env["registry_revision"] and env["tools_revision"] == old_env["tools_revision"], (old_env,env))
                snap = q1(owner,"SELECT v13_snap_of(%s::jsonb)",(Json(env),))
                gate.check("native_envelope_snapshot_consistency: delayed snap projects both old scalars",
                           snap["registry_revision"] == str(env["registry_revision"]) and snap["tools_revision"] == str(env["tools_revision"]))
                new = q1(owner,"SELECT v13_judgment_envelope(%s)",(sid,))
                gate.check("native_envelope_snapshot_consistency: next statement sees both committed fences",
                           new["registry_revision"] == reg["revision"] and new["tools_revision"] == env["tools_revision"]+1)
                gate.check("native_envelope_snapshot_consistency: snapshot wrapper matches new probe",
                           q1(owner,"SELECT v13_snapshot(%s)",(sid,)) == q1(owner,"SELECT v13_snap_of(v13_judgment_envelope(%s))",(sid,)))
        finally:
            owner.rollback()
            q1(owner,"SELECT pg_advisory_unlock_all()")
            owner.commit()
        q1(writer,"SELECT v13_registry_retire(%s,'service','snapshot')",(other,))
        writer.commit()
        gate.check("native_global_freshness: unrelated retire invalidates prior advance",
                   q1(owner,"SELECT v13_advance(%s,%s::jsonb)",(sid,Json({"snap":q1(owner,"SELECT v13_snap_of(%s::jsonb)",(Json(new),)),"envelope":new}))) == "stale")
        owner.rollback()
        with owner.cursor() as cur:
            cur.execute("DELETE FROM v13_tools_meta")
        for sql in ("SELECT * FROM v13_registry_fences()", "SELECT v13_probe(%s)", "SELECT v13_judgment_envelope(%s)", "SELECT v13_claim('no-tools')"):
            expected_error(gate,owner,"native_global_freshness: missing tools seed fails closed",sql,(sid,) if "%s" in sql else ())
        owner.rollback()


def native_lock_barriers(gate, setup, database):
    with (gate.connection(setup,database,"owner") as owner,
          gate.connection(setup,database,"owner") as observer,
          gate.connection(setup,database,"route") as route):
        writer_sid = w4_session(owner)
        sid, eid = ready(owner)
        q1(owner,"SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE",(writer_sid,))
        writer = setup.connect_owner_database(database)
        with SQLCall(writer,"SELECT v13_registry_register(%s,'service','locks','{\"provides\":[\"fake\"]}',ARRAY[]::text[])",(writer_sid,)) as call:
            lock_barrier(gate,observer,call,owner.get_backend_pid())
            gate.check("native_lock_barriers: writer owns clock update before session wait", q1(observer,
                       "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=%s AND relation='v13_registry_clock'::regclass AND mode='RowExclusiveLock' AND granted)",(call.pid,)))
            q1(route,"SELECT set_config('statement_timeout','3s',false)")
            claim = q1(route,"SELECT v13_claim('clock-nonlocking')")
            route.commit()
            gate.check("native_lock_barriers: claim/pin commits while writer owns clock row", claim["effect_id"] == eid)
            owner.commit()
            call.done(gate,"native_lock_barriers: clock/meta/session writer completes")
        # Completion must hold session before waiting on the effect row.
        q1(owner,"SELECT 1 FROM effects WHERE effect_id=%s FOR UPDATE",(eid,))
        completing = setup.connect_test_database(database,role="route")
        with SQLCall(completing,STRICT,completion_args(claim)) as call:
            lock_barrier(gate,observer,call,owner.get_backend_pid())
            waiter = setup.connect_owner_database(database)
            with SQLCall(waiter,"SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE",(sid,)) as session_call:
                lock_barrier(gate,observer,session_call,call.pid)
                owner.commit()
                gate.check("native_lock_barriers: strict completion accepts old exact pin",call.done(gate,"completion session/effect order") == "accepted")
                session_call.done(gate,"session waiter after completion")
        gate.check("native_lock_barriers: completion leaves full pair of mapped events",q1(observer,
                   "SELECT count(*) FROM v13_effect_context_event_pins WHERE effect_id=%s",(eid,)) == 2)
        observer.commit()
        # Fair claim: advisory -> root -> child -> effect NOWAIT, without reverse waits.
        parent = w4_session(owner)
        spawned = q1(owner,"SELECT v13_spawn_subsession(%s,%s::jsonb)",(parent,Json({"schema_version":1,"children":[{"tool_call_id":"fair-lock","task":"child"}]})))
        child = spawned["children"][0]["session_id"]
        _, child_eid = ready_uncommitted(owner,child)
        owner.commit()
        child_hold = setup.connect_owner_database(database)
        try:
            q1(owner,"SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE",(parent,))
            q1(child_hold,"SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE",(child,))
            fair = setup.connect_owner_database(database)
            with SQLCall(fair,"SELECT v13_claim_fair('fair-lock')") as call:
                lock_barrier(gate,observer,call,owner.get_backend_pid())
                gate.check("native_lock_barriers: fair holds admission advisory before root",q1(observer,
                           "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND classid=13002 AND objid=1 AND granted)",(call.pid,)))
                owner.commit()
                lock_barrier(gate,observer,call,child_hold.get_backend_pid())
                # Locking child proves root is already locked; root NOWAIT must fail.
                expected_error(gate,owner,"native_lock_barriers: fair root precedes child", "SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE NOWAIT",(parent,),"55P03")
                q1(owner,"SELECT 1 FROM effects WHERE effect_id=%s FOR UPDATE",(child_eid,))
                child_hold.commit()
                gate.check("native_lock_barriers: fair effect NOWAIT returns NULL, no deadlock",call.done(gate,"fair effect contention") is None)
                owner.rollback()
            gate.check("native_lock_barriers: failed fair claim leaves no CAS/pin",qrow(observer,
                       "SELECT status,attempt_no,fence,(SELECT count(*) FROM v13_effect_context_pins WHERE effect_id=e.effect_id) FROM effects e WHERE effect_id=%s",(child_eid,)) == ("ready",0,0,0))
            q1(owner,"UPDATE effects SET status='failed' WHERE effect_id=%s RETURNING 1",(child_eid,))
            owner.commit()
        finally:
            owner.rollback()
            child_hold.rollback()
            child_hold.close()


def native_acl_closure(gate, setup, database):
    with gate.connection(setup,database,"owner") as conn:
        roles = ("v13_route","v13_recall","v13_worker","v13_resolve","v13_spawn_owner",database.roles["plain"])
        for role in roles:
            gate.check("native_acl: zero table/column rights for " + role, q1(conn,
                "SELECT NOT EXISTS (SELECT 1 FROM (VALUES ('v13_effect_context_pins'),('v13_effect_context_event_pins')) t(n) "
                "WHERE has_table_privilege(%s,n,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
                "OR has_any_column_privilege(%s,n,'SELECT,INSERT,UPDATE,REFERENCES'))",(role,role)))
            for function, allowed in (("v13_effect_context_event_current(uuid,bigint)",{"v13_route","v13_resolve","v13_recall","v13_spawn_owner"}),
                                      ("v13_effect_context_effect_current(uuid)",{"v13_route","v13_resolve"}),
                                      ("v13_registry_context(uuid,bigint,uuid)",{"v13_route","v13_recall"}),
                                      ("v13_claim(text,integer)",{"v13_route","v13_spawn_owner"}),
                                      ("v13_claim_fair(text,integer)",set())):
                gate.check("native_acl: " + function + " " + role,
                           q1(conn,"SELECT has_function_privilege(%s,%s,'EXECUTE')",(role,function)) == (role in allowed))
        conn.rollback()
    # Both stage deltas are checked again; mutation tests prove the allowlist is closed.
    setup.validate_stage41_prefix(database.before,database.prefix)
    setup.validate_stage42_overlay(database.prefix,database.after)
    setup.validate_delta(database.before,database.after)
    for key in ("functions","relations","sequences","roles","memberships","schema_acl","db_acl"):
        altered = copy.deepcopy(database.after)
        if key in {"schema_acl","db_acl"}:
            altered[key] = "consumer_unapproved_acl"
        elif key == "functions":
            altered[key].append(("v13_unapproved()", *altered[key][0][1:]))
        elif key == "relations":
            altered[key].append((0,"public.consumer_unapproved",*altered[key][0][2:]))
        else:
            altered[key].append(("consumer_unapproved",))
        try:
            setup.validate_stage42_overlay(database.prefix,altered)
            setup.validate_delta(database.before,altered)
        except RuntimeError:
            gate.check("native_overlay_static: rejects extra " + key, True)
        else:
            raise AssertionError("overlay admitted extra " + key)
    for column, label in ((5,"columns"),(7,"triggers"),(9,"indexes"),(10,"constraints"),(8,"table ACL")):
        altered = copy.deepcopy(database.after)
        index = next(i for i,row in enumerate(altered["relations"]) if row[1] == "public.v13_effect_context_pins")
        row = list(altered["relations"][index])
        row[column] = "[]"
        if column == 8:
            row[column] = '[[0,"SELECT",false]]'
        altered["relations"][index] = tuple(row)
        try:
            setup.validate_stage42_overlay(database.prefix,altered)
            setup.validate_delta(database.before,altered)
        except RuntimeError:
            gate.check("native_overlay_static: rejects pin " + label + " mutation",True)
        else:
            raise AssertionError("admitted pin " + label + " mutation")
    altered = copy.deepcopy(database.after)
    signature = "v13_effect_context_event_current(uuid,bigint)"
    altered["function_acl"][signature] = "[]"
    try:
        setup.validate_delta(database.before,altered)
    except RuntimeError:
        gate.check("native_overlay_static: rejects helper function ACL mutation",True)
    else:
        raise AssertionError("admitted helper ACL mutation")
    # Live definitions, not obsolete source copies, must carry the projection predicates.
    with gate.connection(setup,database,"owner") as conn:
        consumers = {"v13_route(uuid,jsonb)","v13_advance(uuid,jsonb)","v13_parse(uuid)","v13_canonical_state(uuid)",
                     "v13_cap_answer_anchor(uuid,uuid)","v13_cap_human_answered(uuid,uuid)",
                     "v13_harness_tail_gap(uuid,uuid)","v13_tail_gap_cap_exempt(uuid,uuid)",
                     "v13_closeout(uuid,text,text,boolean)","v13_triage_fold_reason(uuid)",
                     "v13_triage_block_explore_spawn(uuid)","v13_recover_idle()","v13_scheduler_hint(uuid)"}
        for signature in sorted(consumers):
            definition = q1(conn,"SELECT pg_get_functiondef(%s::regprocedure)",(signature,))
            gate.check("native_overlay_static: loaded consumer predicate " + signature,
                       "v13_effect_context_event_current" in definition or "v13_effect_context_effect_current" in definition
                       or (signature == "v13_cap_human_answered(uuid,uuid)" and "v13_cap_answer_anchor" in definition))


def main() -> int:
    setup = load_setup()
    gate = Gate()
    source = (ROOT / "v13_registry.sql").read_text()
    prefix, overlay = setup._registry_sql_parts()
    gate.check("single Stage 42 sentinel overlay", source.count(setup.STAGE42_BEGIN) == 1
               and source.count(setup.STAGE42_END) == 1 and overlay.strip())
    gate.check("Stage 41 prefix hash remains pinned",
               setup.hashlib.sha256(prefix.encode()).hexdigest() == setup.STAGE41_PREFIX_SHA256)
    with setup.test_database() as database:
        with gate.connection(setup, database, "owner") as owner:
            sid = q1(owner, "SELECT public.v13_open_session('{}'::jsonb)")
            effect = str(uuid.uuid4())
            q1(owner, "SELECT public.v13_uuid_v5(%s::uuid,%s)", (sid, effect))
            with owner.cursor() as cur:
                cur.execute(
                    "INSERT INTO public.effects "
                    "(effect_id,session_id,kind,request,request_hash,origin_user_seq,"
                    "attempt_no,fence,status) "
                    "VALUES (%s,%s,'judge','{}'::jsonb,encode(digest('{}','sha256'),'hex'),0,1,7,'claimed')",
                    (effect, sid))
            owner.commit()
            fences = qrow(owner, "SELECT registry_revision,tools_revision "
                                  "FROM public.v13_registry_fences()")
            gate.check("fences expose both seeded global revisions",
                       fences is not None and all(value >= 0 for value in fences), fences)
            owner.commit()

        with gate.connection(setup, database, "route") as route:
            with route.cursor() as cur:
                cur.execute(
                    "SELECT public.v13_effect_context_pin_insert(%s::uuid,1,7,%s::uuid,%s,%s)",
                    (effect, sid, fences[0], fences[1]))
            route.commit()
            pin = qrow(route, "SELECT * FROM public.v13_effect_context_pin_lookup(%s::uuid,1,7)",
                        (effect,))
            gate.check("route can insert and exact-lookup one pin",
                       pin == (str(sid), fences[0], fences[1]), pin)
            gate.check("pin match is exact", q1(
                route,
                "SELECT public.v13_effect_context_pin_matches(%s::uuid,1,7,%s)",
                (effect, fences[0])) is True)
            gate.rejected(route, "SELECT * FROM public.v13_effect_context_pins")

        with gate.connection(setup, database, "worker") as worker:
            gate.rejected(worker, "SELECT * FROM public.v13_effect_context_pins")

        with gate.connection(setup, database, "owner") as owner:
            seq = q1(owner, "SELECT public.v13_append_event(%s::uuid,%s::uuid,'llm/message',%s::jsonb,%s::uuid)",
                     (sid, str(uuid.uuid4()), Json({"foundation": True}), effect))
            owner.commit()
            mapping = qrow(owner, "SELECT effect_id,attempt_no,fence "
                                  "FROM public.v13_effect_context_event_pins "
                                  "WHERE session_id=%s AND event_seq=%s", (sid, seq))
            gate.check("event capture records exact attempt/fence mapping",
                       mapping == (effect, 1, 7), mapping)
            gate.check("event projection helper accepts current mapping",
                       q1(owner, "SELECT public.v13_effect_context_event_current(%s::uuid,%s)",
                          (sid, seq)) is True)
            gate.check("effect projection helper accepts current pin",
                       q1(owner, "SELECT public.v13_effect_context_effect_current(%s::uuid)",
                          (effect,)) is True)
            try:
                with owner.cursor() as cur:
                    cur.execute("UPDATE public.v13_effect_context_pins SET context_revision=99 "
                                "WHERE effect_id=%s", (effect,))
            except psycopg2.Error as exc:
                owner.rollback()
                gate.check("pin update is immutable", exc.pgcode == "P0001", (exc.pgcode, str(exc)))
            else:
                owner.rollback()
                gate.check("pin update must be rejected", False)
            try:
                with owner.cursor() as cur:
                    cur.execute("DELETE FROM public.v13_effect_context_event_pins "
                                "WHERE session_id=%s AND event_seq=%s", (sid, seq))
            except psycopg2.Error as exc:
                owner.rollback()
                gate.check("event mapping delete is immutable", exc.pgcode == "P0001",
                           (exc.pgcode, str(exc)))
            else:
                owner.rollback()
                gate.check("event mapping delete must be rejected", False)

        native_claim_complete(gate, setup, database)
        native_w4_projection(gate, setup, database)
        native_w4_control(gate, setup, database)
        native_w4_human(gate, setup, database)
        native_w4_tool_parse(gate, setup, database)
        native_freshness(gate, setup, database)
        native_worker_protocol(gate, setup, database)
        native_event_pin_atomicity(gate, setup, database)
        native_actual_tool_spawn(gate, setup, database)
        native_plan_signal_evidence(gate, setup, database)
        native_statement_snapshot(gate, setup, database)
        native_lock_barriers(gate, setup, database)
        native_acl_closure(gate, setup, database)
    print(f"Consumer Phase 2 gate: {gate.checks} checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
