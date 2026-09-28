"""pg-agent v13 seam ring vs pi/PiG/PiSwift scripted agent loops - parity gate.

Turn 2 scope: the pg side walks the two-file read task (hello.txt + fib.py)
through the v13 seam ring with a fully deterministic scripted judge and drops
a normalized schema-v2 trace (canonical phases incl. an explicit llm step,
per-step persisted evidence ids asserted against the database) at
traces/pg.jsonl. The three framework sides are driven by their own driver
scripts and asserted here when their toolchains are present; absent toolchains
print honest [SKIP] lines.

Exit-code semantics: 0 = nothing failed (skips are reported as [SKIP] lines
and never fake a pass); 1 = an assertion failed. E4 in
v13/read_tools/test_read_tools.py sweeps this file serially with zero
tolerance for nonzero exits, so the skip signaling must live in printed
output only (recorded assumption: E4 executes v13 test_*.py one at a time).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

PI_SRC = Path("/Users/wxl/Projects/pi")
PIG_ROOT = Path("/Users/wxl/Projects/PiG")
PISWIFT_ROOT = Path("/Users/wxl/Projects/PiSwift")
PISWIFT_BUILD = AGENT_ROOT / ".piswift-build-parity"

FIXTURES = ROOT / "fixtures"
TRACE_DIR = ROOT / "traces"
TRACE_PATH = TRACE_DIR / "pg.jsonl"
EXPECTED_READS = ["hello.txt", "fib.py"]
RUNTIME = "pg"
TOOL_NAME = "read_file"
BASELINE_TOOLS = (
    "session_stats",
    "send_summary_email",
    "harness_turn",
    "spawn_subsession",
    "worktree_prepare",
    "worktree_merge",
    "worktree_release",
)
PARAM_SPEC = {
    "path": {
        "question": "Which fixture file should be read?",
        "stated": "Does the user name a fixture file to read?",
        "options": {
            "hello.txt": "three-line greeting fixture",
            "fib.py": "recursive fibonacci fixture",
        },
    }
}

# Golden (phase, tool) sequence for the pg side under schema v2: two tool
# cycles, one llm cycle, then the terminal beat. The llm phase is an explicit
# canonical phase (oracle P1: the model's assistant output is a step of its
# own, not merely claim kind=llm).
GOLDEN_SEQUENCE = (
    [("judge", None), ("parse", None), ("advance", None), ("claim", TOOL_NAME), ("tool", TOOL_NAME)]
    * len(EXPECTED_READS)
    + [("judge", None), ("parse", None), ("advance", None), ("claim", None), ("llm", None)]
    + [("judge", None), ("parse", None), ("advance", None), ("finish", None)]
)

FROZEN_PREFIXES = ("v13/read_tools/", "v13/pi_ports/")


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"[PASS] {label}")
        return
    print(f"[FAIL] {label}: {detail!r}")
    raise AssertionError(f"{label}: {detail!r}")


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def final_from_results(results: list[str]) -> str:
    hello, fib = results[0], results[1]
    return (
        f"hello.txt {digest(hello)} is a three-line greeting file; "
        f"fib.py {digest(fib)} defines recursive fib(n) with fib(10)=55; "
        "both files were read."
    )


def as_obj(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def choice_answer(name: str, conf: float = 0.9) -> dict:
    return {
        "type": "choice",
        "choice": name,
        "probabilities": {name: conf},
        "confidence": conf,
    }


def read_handler(params: dict) -> str:
    path = params.get("path")
    if path not in EXPECTED_READS:
        raise AssertionError(f"read out of fence: {path!r}")
    target = (FIXTURES / path).resolve()
    if FIXTURES.resolve() not in target.parents:
        raise AssertionError(f"read escaped fixture root: {path!r}")
    if not target.is_file():
        raise AssertionError(f"not a regular file: {path!r}")
    return target.read_text(encoding="utf-8")


def protected_dirty(paths: list[str]) -> list[str]:
    bad = []
    for name in paths:
        if name in {"v13/load.py", "pyproject.toml", "uv.lock"} or (
            name.startswith("v13/") and name.endswith(".sql")
        ):
            bad.append(name)
        if name.startswith(FROZEN_PREFIXES):
            bad.append(name)
    return bad


def run_guard() -> None:
    """Repo-hygiene guard (oracle P1: committed changes count too).

    Same triple as pi_ports G2: working tree vs HEAD, HEAD vs HEAD^ (the last
    commit must not have touched frozen faces either), and untracked files.
    """
    load = (AGENT_ROOT / "v13" / "load.py").read_text()
    check("P0", "pi_parity" not in load, "load.py")
    names = []
    for argv in (
        ["git", "diff", "--name-only", "HEAD", "--", "v13", "pyproject.toml", "uv.lock"],
        ["git", "diff", "--name-only", "HEAD^", "HEAD", "--", "v13", "pyproject.toml", "uv.lock"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "v13", "pyproject.toml", "uv.lock"],
    ):
        proc = subprocess.run(argv, cwd=AGENT_ROOT, capture_output=True, text=True)
        check("P0", proc.returncode == 0, (argv, proc.stderr))
        names.extend(line for line in proc.stdout.splitlines() if line.strip())
    bad = protected_dirty(names)
    check("P0", not bad, bad)


def run_pg_side() -> str:
    import psycopg2

    from server import get_server
    from v13.pi_parity.setup_db import DB, main as setup_db

    steps: list[dict] = []
    ticks = {"n": 0}

    def record(phase: str, *, tool=None, args=None, result_digest="", evidence: str) -> None:
        steps.append({
            "runtime": RUNTIME,
            "seq": len(steps),
            "phase": phase,
            "tool": tool,
            "args": args or {},
            "result_digest": result_digest,
            "persisted": "sql",
            "evidence": evidence,
        })

    def q1(cur, sql, params=None):
        cur.execute(sql, params)
        return cur.fetchone()[0]

    def begin():
        if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            conn.rollback()
        return conn.cursor()

    def event_count(cur, sid, etype) -> int:
        cur.execute(
            "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
            (sid, etype),
        )
        return cur.fetchone()[0]

    def mock_from_needed(cur, sid, **over) -> str:
        cur.execute("SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
        answers = {}
        for signal, kind, criteria in cur.fetchall():
            criteria = as_obj(criteria)
            if signal in over:
                answers[signal] = over[signal]
                continue
            if kind == "choice":
                keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
                answers[signal] = choice_answer(keys[0])
            elif kind == "score":
                answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
            else:
                answers[signal] = {"type": "noul", "noul": 0.1}
        answers.update(over)
        return json.dumps({
            "model": "jev-mock",
            "answers": answers,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    def overrides_for(cur, sid) -> dict:
        base = {
            "gate_action": {"type": "noul", "noul": 0.9},
            "gate_off_topic": {"type": "noul", "noul": 0.1},
            "risk": {"type": "score", "score": 0, "confidence": 0.9},
        }
        n_tools = event_count(cur, sid, "tool/result")
        has_llm = event_count(cur, sid, "llm/message") > 0
        if has_llm or n_tools >= len(EXPECTED_READS):
            base["intent"] = choice_answer("llm_generate")
            base["tool"] = choice_answer("none")
            return base
        base["intent"] = choice_answer("tool_action")
        base["tool"] = choice_answer(TOOL_NAME)
        base[f"stated::{TOOL_NAME}::path"] = {"type": "noul", "noul": 0.9}
        base[f"param::{TOOL_NAME}::path"] = choice_answer(EXPECTED_READS[n_tools])
        return base

    def judge_digest(over: dict) -> dict:
        condensed = {}
        for signal, answer in over.items():
            if isinstance(answer, dict) and answer.get("type") == "choice":
                condensed[signal] = answer.get("choice")
            elif isinstance(answer, dict):
                condensed[signal] = answer.get("type")
            else:
                condensed[signal] = str(answer)
        return condensed

    def persisted_results() -> list[str]:
        cur = begin()
        cur.execute(
            "SELECT payload->>'result' FROM events WHERE session_id=%s AND type='tool/result' ORDER BY seq",
            (sid,),
        )
        rows = [row[0] for row in cur.fetchall()]
        conn.rollback()
        return rows

    seen = {"calls": set(), "cache": set()}

    def judgment_evidence() -> tuple[str, str]:
        """Evidence for the judge/parse steps of the beat that just parsed.

        judge  -> the judgment_calls row recorded for the asked batch, or an
                  asserted cache-hit marker when the whole batch deduped.
        parse  -> the judgment_cache rows written by the same call, or the
                  same hit marker. Every claim is backed by a fresh SELECT.
        """
        cur = begin()
        cur.execute("SELECT call_id::text FROM judgment_calls")
        calls = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT request_hash FROM judgment_cache")
        cache = {row[0] for row in cur.fetchall()}
        conn.rollback()
        new_calls = calls - seen["calls"]
        new_cache = cache - seen["cache"]
        seen["calls"] |= new_calls
        seen["cache"] |= new_cache
        if new_calls:
            check("P-evidence", len(new_calls) == 1, sorted(new_calls))
            call_id = next(iter(new_calls))
            judge_ev = f"judgment_call:{call_id[:8]}"
            parse_ev = f"judgment_cache:+{len(new_cache)}" if new_cache else "judgment_cache:0 new"
            return judge_ev, parse_ev
        check("P-evidence", len(cache) > 0, "dedupe hit but judgment_cache is empty")
        return "judgment_cache_hit (dedupe)", "judgment_cache_hit (dedupe)"

    route_log: list[tuple] = []

    def route_evidence() -> str:
        cur = begin()
        cur.execute(
            "SELECT seq, payload->>'action' FROM events "
            "WHERE session_id=%s AND type='turn/route' ORDER BY seq",
            (sid,),
        )
        rows = cur.fetchall()
        conn.rollback()
        fresh = rows[len(route_log):]
        check("P-evidence", len(fresh) == 1, rows)
        route_log.extend(fresh)
        return f"event:{fresh[0][0]}/turn/route"

    def effect_evidence(effect_id: str, expected_status: str) -> str:
        cur = begin()
        cur.execute("SELECT status FROM effects WHERE effect_id=%s", (effect_id,))
        row = cur.fetchone()
        conn.rollback()
        check("P-evidence", row is not None and row[0] == expected_status, (effect_id, row))
        return f"effect:{str(effect_id)[:8]}"

    def result_event_evidence(claim, etype: str) -> tuple[str, str]:
        cur = begin()
        cur.execute(
            "SELECT seq FROM events WHERE session_id=%s AND type=%s AND source_effect_id=%s",
            (sid, etype, claim["effect_id"]),
        )
        rows = cur.fetchall()
        cur.execute("SELECT status FROM effects WHERE effect_id=%s", (claim["effect_id"],))
        status = cur.fetchone()[0]
        conn.rollback()
        check("P-evidence", len(rows) == 1 and status == "succeeded", (etype, rows, status))
        ev = f"event:{rows[0][0]}/{etype}+effect:{str(claim['effect_id'])[:8]}"
        return ev, f"event:{rows[0][0]}/{etype}"

    def finish_evidence() -> str:
        cur = begin()
        cur.execute(
            "SELECT seq FROM events WHERE session_id=%s AND type='turn/end' ORDER BY seq",
            (sid,),
        )
        rows = cur.fetchall()
        cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
        sess = cur.fetchone()[0]
        conn.rollback()
        check("P-evidence", len(rows) == 1 and sess == "completed", (rows, sess))
        return f"event:{rows[0][0]}/turn/end+session:{sess}"

    def parse_fresh(session_id):
        pc = psycopg2.connect(server.get_uri(DB))
        pc.autocommit = False
        pcur = pc.cursor()
        pcur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        pcur.fetchone()
        pcur.execute("SELECT set_config('typesafe.model', 'fake-judge', false)")
        pcur.fetchone()
        over = overrides_for(pcur, session_id)
        mock = mock_from_needed(pcur, session_id, **over)
        pcur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))
        pcur.fetchone()
        try:
            snap = as_obj(q1(pcur, "SELECT v13_parse(%s)", (session_id,)))
        except psycopg2.Error as exc:
            pc.rollback()
            pc.close()
            raise AssertionError(
                f"parse: {exc.pgcode} {exc.diag.message_primary if exc.diag else exc}"
            ) from exc
        pc.commit()
        pc.close()
        return snap, over

    def complete(cur, claim, status, result):
        cur.execute(
            "SELECT v13_complete(%s, %s, %s, %s, %s::jsonb)",
            (
                claim["effect_id"],
                claim["attempt_no"],
                claim["fence"],
                status,
                json.dumps(result),
            ),
        )
        return cur.fetchone()[0]

    def beat(session_id, expect_terminal=False):
        ticks["n"] += 1
        check("P-ticks", ticks["n"] <= 24, ticks["n"])
        snap, over = parse_fresh(session_id)
        judge_ev, parse_ev = judgment_evidence()
        record("judge", args=judge_digest(over), evidence=judge_ev)
        check("P-parse", int(snap["remaining"]) == 0, snap.get("remaining"))
        record("parse", args={"remaining": snap.get("remaining")}, evidence=parse_ev)
        cur = begin()
        cur.execute("SET LOCAL lock_timeout='250ms'")
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id=%s",
            (session_id,),
        )
        try:
            status = q1(cur, "SELECT v13_advance(%s, %s::jsonb)", (session_id, json.dumps(snap)))
        except psycopg2.Error as exc:
            conn.rollback()
            raise AssertionError(
                f"advance: {exc.pgcode} {exc.diag.message_primary if exc.diag else exc}"
            ) from exc
        conn.commit()
        record("advance", args={"status": status}, evidence=route_evidence())
        if status == "terminal":
            check("P-advance", expect_terminal, status)
            record("finish", args={"session": "completed"}, evidence=finish_evidence())
            return {"advance": status}
        check("P-advance", status == "waiting", status)
        cur = begin()
        cur.execute(
            "SELECT effect_id::text, session_id::text FROM effects WHERE status='ready'"
        )
        ready = cur.fetchall()
        check("P-claim", len(ready) == 1 and ready[0][1] == session_id, ready)
        claim = as_obj(q1(cur, "SELECT v13_claim(%s, %s)", ("pi-parity-hub", 120000)))
        check("P-claim", claim and str(claim["effect_id"]) == ready[0][0], claim)
        conn.commit()
        kind = claim["kind"]
        request = claim.get("request") or {}
        print(f"[beat] {kind} {request.get('handler') or request.get('reason')}")
        claim_ev = effect_evidence(claim["effect_id"], "claimed")
        if kind == "tool":
            record(
                "claim",
                tool=TOOL_NAME,
                args={
                    "kind": "tool",
                    "handler": request.get("handler"),
                    "path": (request.get("params") or {}).get("path"),
                },
                evidence=claim_ev,
            )
        else:
            record("claim", args={"kind": kind}, evidence=claim_ev)
        completed = False
        try:
            if kind == "tool":
                handler = request.get("handler")
                check(
                    "P-dispatch",
                    handler == f"worker:{TOOL_NAME}",
                    handler,
                )
                params = dict(request.get("params") or {})
                payload = read_handler(params)
                st = "succeeded"
            elif kind == "llm":
                results = persisted_results()
                check("P-llm-input", results == expected_texts, results)
                payload = {
                    "text": final_from_results(results),
                    "model": "fake",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
                st = "succeeded"
            elif kind == "human":
                payload, st = {"reason": request.get("reason")}, "succeeded"
            else:
                payload = {"error": "protocol_error", "message": f"unknown kind {kind}"}
                st = "failed"
            cur = begin()
            cur.execute("SET LOCAL lock_timeout='250ms'")
            cur.execute("SET LOCAL statement_timeout='5s'")
            got = complete(cur, claim, st, payload)
            check("P-complete", got == "accepted", got)
            conn.commit()
            completed = True
            if kind == "tool":
                _, tool_ev = result_event_evidence(claim, "tool/result")
                record(
                    "tool",
                    tool=TOOL_NAME,
                    args={"path": params.get("path")},
                    result_digest=digest(payload),
                    evidence=tool_ev,
                )
            elif kind == "llm":
                llm_ev, _ = result_event_evidence(claim, "llm/message")
                record(
                    "llm",
                    args={"kind": "llm", "model": payload["model"]},
                    result_digest=digest(payload["text"]),
                    evidence=llm_ev,
                )
            if kind not in ("tool", "llm", "human"):
                raise AssertionError(f"unexpected effect settled: {kind}")
            return {"advance": status, "claim": claim, "payload": payload, "status": st}
        finally:
            if not completed:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    cur = begin()
                    complete(cur, claim, "failed", {
                        "error": "protocol_error",
                        "message": "hub aborted",
                    })
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

    check("P-setup", setup_db() == 0, "setup_db")
    expected_texts = [read_handler({"path": name}) for name in EXPECTED_READS]
    expected_final = final_from_results(expected_texts)
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    try:
        cur = begin()
        cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        cur.fetchone()
        cur.execute("SELECT set_config('typesafe.model', 'fake-judge', false)")
        cur.fetchone()
        # Runtime toggle, not schema: same pattern as read_tools (the row is
        # restored by setup_db on the next run; recorded in README).
        cur.execute(
            "UPDATE tools SET enabled=false WHERE name='spawn_subsession' AND enabled"
        )
        conn.commit()

        cur = begin()
        cur.execute(
            "INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('default', 2)"
        )
        cur.execute(
            "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) "
            "SELECT 'default', 2, signal, band_no, lo, hi, action "
            "FROM thresholds WHERE policy_name='default' AND policy_version=1"
        )
        bands = [f"param::{TOOL_NAME}::path", f"stated::{TOOL_NAME}::path"]
        for signal in bands:
            cur.execute(
                "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) "
                "VALUES ('default', 2, %s, 1, 0.60, 'Infinity', 'pass')",
                (signal,),
            )
        cur.execute(
            "UPDATE v13_route_policies SET state='frozen' "
            "WHERE policy_name='default' AND policy_version=2"
        )
        conn.commit()

        cur = begin()
        base_count = q1(cur, "SELECT count(*) FROM tools")
        base_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
            "VALUES (%s, %s, 'tool', %s, %s::jsonb, true)",
            (
                TOOL_NAME,
                "Read a fixture file for the pi_parity task.",
                f"worker:{TOOL_NAME}",
                json.dumps(PARAM_SPEC),
            ),
        )
        after_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
        check("P-catalog", q1(cur, "SELECT count(*) FROM tools") == base_count + 1, base_count)
        conn.commit()

        cycles = len(EXPECTED_READS) + 2
        cur = begin()
        if cycles != 3:
            cur.execute("UPDATE v13_policies SET active=false WHERE name='turn_budget' AND active")
            cur.execute(
                "INSERT INTO v13_policies (name, version, value, active) "
                "VALUES ('turn_budget', 2, %s::jsonb, true)",
                (json.dumps({"max_cycles": cycles}),),
            )
        check(
            "P-budget",
            q1(cur, "SELECT v13_policy('turn_budget')->>'max_cycles'") == str(cycles),
            cycles,
        )
        conn.commit()

        cur = begin()
        sid = str(q1(
            cur,
            "SELECT v13_open_session(%s::jsonb)",
            (json.dumps({"route_policy_name": "default", "version": 2}),),
        ))
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
            (
                sid,
                str(uuid.uuid4()),
                json.dumps({"text": "Read hello.txt and fib.py, then state the key points of both files."}),
            ),
        )
        override_seq = q1(
            cur,
            "SELECT v13_submit_override(%s, %s::jsonb)",
            (sid, json.dumps({
                "schema_version": 1,
                "intent": "direct",
                "source_principal": "user",
                "reason": "pi-parity gate",
            })),
        )
        check("P-override", override_seq > 0, override_seq)
        user_seq = q1(
            cur,
            "SELECT max(seq) FROM events WHERE session_id=%s AND type='user/message'",
            (sid,),
        )
        conn.commit()

        n = len(EXPECTED_READS)
        beat_results = [beat(sid) for _ in range(n + 1)]
        end = beat(sid, expect_terminal=True)

        cur = begin()
        cur.execute(
            "SELECT payload FROM events WHERE session_id=%s AND type='turn/route' ORDER BY seq",
            (sid,),
        )
        routes = [as_obj(row[0]) for row in cur.fetchall()]
        conn.rollback()
        check(
            "P-routes",
            [row.get("action") for row in routes] == ["tool"] * n + ["llm", "finish"],
            routes,
        )
        check(
            "P-routes",
            [row.get("tool") for row in routes[:n]] == [TOOL_NAME] * n,
            routes,
        )
        for step, expected_path in zip(beat_results[:n], EXPECTED_READS):
            req = step["claim"]["request"]
            check(
                "P-args",
                step["claim"]["kind"] == "tool"
                and req.get("handler") == f"worker:{TOOL_NAME}"
                and req.get("params") == {"path": expected_path},
                req,
            )
        check("P-llm-effect", beat_results[n]["claim"]["kind"] == "llm", beat_results[n].get("claim"))
        cur = begin()
        cur.execute(
            "SELECT payload->>'result' FROM events WHERE session_id=%s AND type='tool/result' ORDER BY seq",
            (sid,),
        )
        result_events = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT status, jsonb_typeof(result), result #>> '{}', origin_user_seq "
            "FROM effects WHERE session_id=%s AND kind='tool'",
            (sid,),
        )
        effects = cur.fetchall()
        cur.execute(
            "SELECT payload->>'text', (payload->>'origin_user_seq')::bigint "
            "FROM events WHERE session_id=%s AND type='llm/message'",
            (sid,),
        )
        llm_rows = cur.fetchall()
        cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
        sess_status = cur.fetchone()[0]
        cur.execute(
            "SELECT payload FROM events WHERE session_id=%s AND type='turn/end' ORDER BY seq",
            (sid,),
        )
        ends = [as_obj(row[0]) for row in cur.fetchall()]
        conn.rollback()
        check("P-results", result_events == expected_texts, result_events)
        check(
            "P-effects",
            len(effects) == n
            and all(row[0] == "succeeded" and row[1] == "string" and row[3] == user_seq for row in effects),
            effects,
        )
        check("P-effects", sorted(row[2] for row in effects) == sorted(expected_texts), effects)
        check(
            "P-final",
            len(llm_rows) == 1 and llm_rows[0][0] == expected_final and llm_rows[0][1] == user_seq,
            llm_rows,
        )
        check("P-final", end["advance"] == "terminal" and sess_status == "completed", (end, sess_status))
        check("P-final", len(ends) == 1 and ends[0].get("delivered") is True, ends)

        final_text = llm_rows[0][0]
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        with TRACE_PATH.open("w", encoding="utf-8") as fh:
            for step in steps:
                fh.write(json.dumps(step, ensure_ascii=False) + "\n")
            fh.write(json.dumps({"runtime": RUNTIME, "final": final_text}, ensure_ascii=False) + "\n")

        cur = begin()
        cur.execute("DELETE FROM tools WHERE name=%s", (TOOL_NAME,))
        end_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
        check("P-cleanup", q1(cur, "SELECT count(*) FROM tools") == base_count, base_count)
        check("P-cleanup", end_rev == after_rev + 1, (after_rev, end_rev))
        conn.commit()
    finally:
        conn.close()
    return expected_final


def run_trace_assertions(expected_final: str) -> None:
    check("P-trace-file", TRACE_PATH.is_file(), TRACE_PATH)
    lines = TRACE_PATH.read_text(encoding="utf-8").splitlines()
    check("P-trace", bool(lines), lines)
    records = [json.loads(line) for line in lines]
    check("P-trace", all(rec.get("runtime") == RUNTIME for rec in records), records)
    steps = [rec for rec in records if "phase" in rec]
    final_rec = records[-1]
    check("P-trace", final_rec.get("final") == expected_final, final_rec)
    tool_steps = [rec for rec in steps if rec["phase"] == "tool"]
    check(
        "P-trace",
        [rec.get("args", {}).get("path") for rec in tool_steps] == EXPECTED_READS,
        tool_steps,
    )
    expected_digests = [
        digest((FIXTURES / name).read_text(encoding="utf-8")) for name in EXPECTED_READS
    ]
    check("P-trace", [rec.get("result_digest") for rec in tool_steps] == expected_digests, tool_steps)
    # Golden exact sequence (oracle P2): the full (phase, tool) list, not just
    # coverage.
    got_sequence = [(rec["phase"], rec.get("tool")) for rec in steps]
    check("P-trace-golden", got_sequence == GOLDEN_SEQUENCE, got_sequence)
    llm_steps = [rec for rec in steps if rec["phase"] == "llm"]
    check(
        "P-trace",
        len(llm_steps) == 1 and llm_steps[0].get("result_digest") == digest(final_rec["final"]),
        llm_steps,
    )
    # Persisted evidence chain (oracle P1): every step carries a non-empty
    # evidence string and persisted="sql" only alongside it.
    check(
        "P-trace",
        all(rec.get("evidence") for rec in steps),
        [rec for rec in steps if not rec.get("evidence")],
    )
    check(
        "P-trace",
        all(rec.get("persisted") == "sql" for rec in steps),
        [rec for rec in steps if rec.get("persisted") != "sql"],
    )
    seqs = [rec["seq"] for rec in steps]
    check("P-trace", seqs == list(range(len(steps))), seqs)
    print(f"[trace] {TRACE_PATH} steps={len(steps)}")


def main(argv: list[str]) -> int:
    del argv
    failed = False
    expected_final = None
    try:
        run_guard()
        expected_final = run_pg_side()
        run_trace_assertions(expected_final)
        run_framework_sides(expected_final)
    except AssertionError as exc:
        print(exc)
        failed = True
    if failed:
        return 1
    return 0


# ─── framework driver planes (pi / PiG / PiSwift) ─────────────────────────────

FRAMEWORK_TOOL_SEQUENCE = ["llm", "claim", "tool", "llm", "claim", "tool", "llm", "finish"]
ALLOWED_PHASES = {"judge", "parse", "advance", "claim", "tool", "llm", "finish", "raw"}


def command_ok(argv: list[str]) -> bool:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def node_planes_absent() -> list[str]:
    planes = []
    if not command_ok(["node", "--version"]):
        planes.append("node")
    if not (PI_SRC / "packages" / "agent" / "src" / "harness" / "agent-harness.ts").is_file():
        planes.append("pi_checkout")
    if not (ROOT / "node_modules" / "marked").is_dir():
        planes.append("node_modules")
    return planes


def go_planes_absent() -> list[str]:
    planes = []
    if not command_ok(["go", "version"]):
        planes.append("go")
    if not (PIG_ROOT / "go.mod").is_file() or not (PIG_ROOT / "ai" / "types.go").is_file():
        planes.append("pig_checkout")
    return planes


def swift_planes_absent() -> list[str]:
    planes = []
    if not command_ok(["swift", "--version"]):
        planes.append("swift")
    read_tool = PISWIFT_ROOT / "Sources" / "PiSwiftCodingAgent" / "Core" / "Tools" / "ReadTool.swift"
    if not (PISWIFT_ROOT / "Package.swift").is_file() or not read_tool.is_file():
        planes.append("piswift_checkout")
    return planes


class ToolchainMissing(Exception):
    def __init__(self, planes: list[str], detail: str = "") -> None:
        super().__init__(detail)
        self.planes = planes


def build_pig_driver() -> list[str]:
    out = ROOT / "pig_driver" / "read_pig"
    env = os.environ.copy()
    env["GOWORK"] = "off"
    env["GOTOOLCHAIN"] = "auto"
    proc = subprocess.run(
        ["go", "build", "-o", str(out), "."],
        cwd=ROOT / "pig_driver",
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        lowered = err.lower()
        if "download go" in lowered or "toolchain not available" in lowered:
            raise ToolchainMissing(["go_toolchain"], err)
        raise AssertionError(f"pi driver build (go): {err[-2000:]}")
    return [str(out), "fixtures"]


def build_piswift_driver() -> list[str]:
    port = ROOT / "piswift_driver"
    proc = subprocess.run(
        ["swift", "build", "-c", "release", "--product", "piswift_driver", "--build-path", str(PISWIFT_BUILD)],
        cwd=port,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        lowered = err.lower()
        if "unable to find" in lowered and "swift" in lowered:
            raise ToolchainMissing(["swift"], err)
        raise AssertionError(f"piswift driver build: {err[-2000:]}")
    shown = subprocess.run(
        ["swift", "build", "-c", "release", "--product", "piswift_driver", "--build-path", str(PISWIFT_BUILD), "--show-bin-path"],
        cwd=port,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if shown.returncode != 0:
        raise AssertionError(f"piswift bin path: {(shown.stderr or shown.stdout)[-1000:]}")
    bin_dir = Path(shown.stdout.strip().splitlines()[-1])
    binary = bin_dir / "piswift_driver"
    if not binary.is_file():
        raise AssertionError(f"piswift binary missing after build: {binary}")
    return [str(binary), "fixtures"]


def run_driver(tag: str, argv: list[str]) -> None:
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        raise AssertionError(f"{tag} driver exit {proc.returncode}: {detail[-2000:]}")
    lines = [line for line in (proc.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        raise AssertionError(f"{tag} driver emitted no JSON summary")
    summary = json.loads(lines[-1])
    check(f"{tag}-run", summary.get("ok") is True, summary)


def load_trace(tag: str, side: str) -> tuple[list[dict], dict]:
    path = TRACE_DIR / f"{side}.jsonl"
    check(f"{tag}-trace-file", path.is_file(), path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    check(f"{tag}-trace", bool(records), path)
    steps = [rec for rec in records if "phase" in rec]
    final_rec = records[-1]
    check(f"{tag}-trace", "final" in final_rec and "phase" not in final_rec, final_rec)
    check(f"{tag}-trace", all(rec.get("runtime") == side for rec in records), path)
    return steps, final_rec


def run_framework_assertions(tag: str, side: str, expected_final: str, pg_tool_digests: list[str]) -> None:
    steps, final_rec = load_trace(tag, side)
    seqs = [rec["seq"] for rec in steps]
    check(f"{tag}-seq", seqs == list(range(len(steps))), seqs)
    check(
        f"{tag}-phases",
        all(rec["phase"] in ALLOWED_PHASES for rec in steps),
        [rec["phase"] for rec in steps if rec["phase"] not in ALLOWED_PHASES],
    )
    # Canonical (non-raw) sequence: the frameworks have no judge/parse/
    # advance natives, so their canonical story is tool cycle x2 + final llm.
    canonical = [rec["phase"] for rec in steps if rec["phase"] != "raw"]
    check(f"{tag}-canonical", canonical == FRAMEWORK_TOOL_SEQUENCE, canonical)
    tool_steps = [rec for rec in steps if rec["phase"] == "tool"]
    check(
        f"{tag}-tools",
        [(rec.get("tool"), rec.get("args", {}).get("path")) for rec in tool_steps]
        == [("read", path) for path in EXPECTED_READS],
        tool_steps,
    )
    check(
        f"{tag}-digests",
        [rec.get("result_digest") for rec in tool_steps] == pg_tool_digests,
        tool_steps,
    )
    llm_steps = [rec for rec in steps if rec["phase"] == "llm"]
    check(f"{tag}-llm", bool(llm_steps), steps)
    check(
        f"{tag}-llm-final",
        llm_steps[-1].get("result_digest") == digest(final_rec["final"]),
        llm_steps[-1],
    )
    finish_steps = [rec for rec in steps if rec["phase"] == "finish"]
    check(
        f"{tag}-finish",
        len(finish_steps) == 1 and finish_steps[0].get("args", {}).get("status") == "completed",
        finish_steps,
    )
    # Final-answer consistency across all four runtimes.
    check(f"{tag}-final", final_rec["final"] == expected_final, final_rec)
    # Persisted evidence chain: non-empty, resolved, honestly marked memory.
    check(
        f"{tag}-evidence",
        all(rec.get("evidence") for rec in steps),
        [rec for rec in steps if not rec.get("evidence")],
    )
    unresolved = [
        rec
        for rec in steps
        if "pending" in (rec.get("evidence") or "") or "no boundary commit" in (rec.get("evidence") or "")
    ]
    check(f"{tag}-evidence-resolved", not unresolved, unresolved)
    check(
        f"{tag}-persisted",
        all(rec.get("persisted") == "memory" for rec in steps),
        [rec for rec in steps if rec.get("persisted") != "memory"],
    )
    print(f"[trace] {TRACE_DIR / (side + '.jsonl')} steps={len(steps)}")


def assert_byte_stable(tag: str, side: str, argv: list[str]) -> None:
    first = (TRACE_DIR / f"{side}.jsonl").read_bytes()
    run_driver(tag, argv)
    second = (TRACE_DIR / f"{side}.jsonl").read_bytes()
    check(f"{tag}-byte-stable", first == second, "driver output differs between runs")


def pg_tool_digests() -> list[str]:
    steps, _ = load_trace("P", "pg")
    return [rec["result_digest"] for rec in steps if rec["phase"] == "tool"]


def run_framework_sides(expected_final: str) -> None:
    digests_pg = pg_tool_digests()
    planes: list[str] = []

    node_skipped = node_planes_absent()
    if node_skipped:
        planes.extend(node_skipped)
    else:
        pi_argv = ["node", "--experimental-strip-types", "pi_driver.mjs"]
        run_driver("PI", pi_argv)
        run_framework_assertions("PI", "pi", expected_final, digests_pg)
        assert_byte_stable("PI", "pi", pi_argv)

    go_skipped = go_planes_absent()
    if go_skipped:
        planes.extend(go_skipped)
    else:
        try:
            pig_argv = build_pig_driver()
        except ToolchainMissing as exc:
            planes.extend(exc.planes)
        else:
            run_driver("PIG", pig_argv)
            run_framework_assertions("PIG", "pig", expected_final, digests_pg)
            assert_byte_stable("PIG", "pig", pig_argv)

    swift_skipped = swift_planes_absent()
    if swift_skipped:
        planes.extend(swift_skipped)
    else:
        try:
            piswift_argv = build_piswift_driver()
        except ToolchainMissing as exc:
            planes.extend(exc.planes)
        else:
            run_driver("PISWIFT", piswift_argv)
            run_framework_assertions("PISWIFT", "piswift", expected_final, digests_pg)
            assert_byte_stable("PISWIFT", "piswift", piswift_argv)

    if planes:
        print(f"[SKIP] not_run/toolchain_absent planes={','.join(sorted(set(planes)))}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
