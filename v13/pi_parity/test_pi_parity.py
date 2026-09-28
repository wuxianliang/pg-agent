"""pg-agent v13 seam ring vs pi/PiG/PiSwift scripted agent loops - parity gate.

Turn 1 scope: the pg side walks the two-file read task (hello.txt + fib.py)
through the v13 seam ring with a fully deterministic scripted judge and drops
a normalized trace at traces/pg.jsonl. The three framework sides land in
Turn 2 and print honest [SKIP] lines here.

Exit-code semantics: 0 = nothing failed (skips are reported as [SKIP] lines
and never fake a pass); 1 = an assertion failed. E4 in
v13/read_tools/test_read_tools.py sweeps this file with zero tolerance for
nonzero exits, so the skip signaling must live in printed output only.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

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


def run_guard() -> None:
    load = (AGENT_ROOT / "v13" / "load.py").read_text()
    check("P0", "pi_parity" not in load, "load.py")
    frozen = [
        "v13/load.py",
        "v13/read_tools/test_read_tools.py",
        "v13/pi_ports/test_pi_ports.py",
    ]
    argv = ["git", "diff", "--name-only", "HEAD", "--"] + frozen
    proc = subprocess.run(argv, cwd=AGENT_ROOT, capture_output=True, text=True)
    check("P0", proc.returncode == 0 and not proc.stdout.strip(), (argv, proc.stdout, proc.stderr))


def run_pg_side() -> str:
    import psycopg2

    from server import get_server
    from v13.pi_parity.setup_db import DB, main as setup_db

    steps: list[dict] = []
    ticks = {"n": 0}

    def record(phase: str, *, tool=None, args=None, result_digest="", persisted="sql") -> None:
        steps.append({
            "runtime": RUNTIME,
            "seq": len(steps),
            "phase": phase,
            "tool": tool,
            "args": args or {},
            "result_digest": result_digest,
            "persisted": persisted,
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
        record("judge", args=judge_digest(over))
        record("parse", args={"remaining": snap.get("remaining")})
        return snap

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
        snap = parse_fresh(session_id)
        check("P-parse", int(snap["remaining"]) == 0, snap.get("remaining"))
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
        record("advance", args={"status": status})
        if status == "terminal":
            check("P-advance", expect_terminal, status)
            record("finish", args={"session": "completed"})
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
        if kind == "tool":
            record(
                "claim",
                tool=TOOL_NAME,
                args={
                    "kind": "tool",
                    "handler": request.get("handler"),
                    "path": (request.get("params") or {}).get("path"),
                },
            )
        else:
            record("claim", args={"kind": kind})
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
                record(
                    "tool",
                    tool=TOOL_NAME,
                    args={"path": params.get("path")},
                    result_digest=digest(payload),
                )
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
    phases = [rec["phase"] for rec in steps]
    for phase in ("parse", "advance", "claim", "tool", "judge", "finish"):
        check("P-trace", phase in phases, phases)
    check(
        "P-trace",
        all(rec.get("persisted") in ("sql", "file", "memory") for rec in steps),
        steps,
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
    except AssertionError as exc:
        print(exc)
        failed = True
    if failed:
        return 1
    for side, note in (
        ("pi", "faux provider drive lands in Turn 2 (recon in README)"),
        ("PiG", "scriptedProvider drive lands in Turn 2 (recon in README)"),
        ("PiSwift", "createAgentSession + mock provider drive lands in Turn 2 (recon in README)"),
    ):
        print(f"[SKIP] {side}: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
