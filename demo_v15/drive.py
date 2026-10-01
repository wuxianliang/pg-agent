"""Headless chain, recall, fanout, and csi driver. DeepSeek is imported only on the real path."""
from __future__ import annotations

import contextlib
import io
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DEMO))

from server import get_server
from v15.protocol.render_prompt import render_system
from v15.provider.support import FLASH_SCOPE
from v15.worker import run_until_quiescent

import db
from assert_e2e import assert_e2e
from report import redact, stamp_now, write_report
from script import (
    OrderedScript,
    ScriptExhausted,
    ScriptGate,
    expected_kinds,
    gate,
    happy_chain,
    happy_csi,
    happy_fanout,
    happy_recall,
)
from task import (
    CALLS_LIMIT,
    COST_LIMIT_TEXT,
    FactsUnsized,
    HopsInvalid,
    NoteInvalid,
    PRINT_SQL,
    ScenarioInvalid,
    SealInvalid,
    SystemDrift,
    build_facts,
    ceilings,
    check_canonical_notes,
    default_hops,
    estimate_fixed,
    note_for,
    note_revision,
    nonroot_headroom,
    root_inputs,
    system_chars,
    validate_hops,
    validate_note,
    validate_scenario,
    validate_seal,
)

FAKE_LEASE = "30 seconds"
REAL_LEASE = "240 seconds"
WORKER_ID = "demo-v15"
KEEP_WARNING = (
    "下一次任何 v15 gate 的 setup 会先强制删光全部 agent_v15_* 库、"
    "然后在 DROP ROLE v15_owner 处失败——须先 --drop-only"
)
_PROTOCOL = {
    "max_invoke_input_length": 9000,
    "truncation_prefix_ratio": 0.5,
    "max_repl_output_length": 4500,
}
_HOOKS = [{"hook_key": "context_window_warning", "config": {"ratio": 0.5}}]


def drop_hint(dbname: str) -> str:
    cmd = "uv run python demo_v15/drive.py --drop-only"
    if dbname != db.DEFAULT_DB:
        cmd = f"{cmd} {dbname}"
    return f"keep database {dbname}; drop with: {cmd}"


def keep_lines(dbname: str, report_path: str | None = None) -> list[str]:
    lines = [drop_hint(dbname), KEEP_WARNING]
    if report_path:
        lines.append(report_path)
    return lines


def _emit_keep(dbname: str, report_path: str | None = None, *, stdout: bool = False) -> None:
    for line in keep_lines(dbname, report_path):
        print(line, file=sys.stderr)
        if stdout:
            print(line)


def present_key(environ: dict) -> str:
    return environ.get("DEEPSEEK_API_KEY") or environ.get("OPENAI_API_KEY") or ""


def secrets_of(environ: dict) -> list[str]:
    found = []
    for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        value = environ.get(name) or ""
        if value:
            found.append(value)
    return found


def build_real_provider():
    from v15.provider.deepseek import DeepSeekProvider

    return DeepSeekProvider(base_url="https://api.deepseek.com/v1", timeout_s=120)


def open_root(conn, invoke_id: str, pool_id: str, inputs: list[dict]) -> None:
    system = render_system(recursion_available=True, bindings=[])
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(
          %s, %s, NULL, %s::jsonb, %s, %s::jsonb, %s, NULL
        )
        """,
        (
            invoke_id,
            FLASH_SCOPE,
            json.dumps(inputs),
            pool_id,
            json.dumps(ceilings()),
            system,
        ),
    )
    conn.commit()


def install_recall_layer(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM v15.hook_defs WHERE hook_key = 'context_window_warning'"
    )
    if cur.fetchone() is None:
        raise RuntimeError("hook_missing")
    cur.execute(
        """
        SELECT coalesce(max(ordinal) + 1, 0)
        FROM v15.config_layers
        WHERE scope_id = %s::uuid
        """,
        (FLASH_SCOPE,),
    )
    ordinal = int(cur.fetchone()[0])
    layer_id = str(uuid.uuid4())
    sql = """
        SELECT v15.v15_add_layer(
          %s::uuid, %s::uuid, %s, 'plain', NULL, NULL, %s::jsonb, NULL, %s::jsonb
        )
    """
    args = (
        layer_id,
        FLASH_SCOPE,
        ordinal,
        json.dumps(_PROTOCOL),
        json.dumps(_HOOKS),
    )

    try:
        cur.execute(sql, args)
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def jsonb_text_matches(conn, sample: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT to_jsonb(%s::text)::text", (sample,))
    got = cur.fetchone()[0]
    conn.rollback()
    return got == json.dumps(sample, ensure_ascii=False)


def _early(line: str, code: int) -> dict:
    return {
        "exit_code": code,
        "line": line,
        "extra_lines": [],
        "report_path": None,
        "result": None,
        "kept": False,
    }


def _minimal(root_id: str, failure_class: str, pgcode: str | None = None, scenario: str = "chain", hops: int = 0) -> dict:
    result = {
        "outcome": "fail",
        "failure_class": failure_class,
        "scenario": scenario,
        "hops": hops,
        "relay_ok": False,
        "relay_flags": [],
        "recall_ok": False,
        "recall_flags": [],
        "csi_ok": False,
        "csi_flags": [],
        "warning_ok": False,
        "warning": {},
        "root_id": root_id,
        "nodes": [],
        "transcript": {
            "assistant_messages": 0,
            "markdown_fence_messages": 0,
            "split_failures": {},
            "classified": {},
            "legal_statement_rate": "0",
            "assistant_previews": [],
            "finish_reasons": {},
        },
        "cost": {
            "sum_cost_usd": "0",
            "cost_used": "0",
            "calls_used": 0,
            "calls_charged": 0,
            "calls_limit": CALLS_LIMIT,
            "cost_limit": COST_LIMIT_TEXT,
            "pricing_revision": None,
            "any_peak": None,
            "provider_meta": "absent",
        },
        "events_ok": False,
        "scratch_clear": False,
        "running": 0,
        "leased": 0,
    }
    if pgcode:
        result["pgcode"] = pgcode
    return result


def _pgcode(exc: BaseException) -> str | None:
    return getattr(exc, "pgcode", None)


def _close_provider(provider) -> None:
    closer = getattr(provider, "close", None)
    if closer is None:
        return
    try:
        closer()
    except Exception:
        return


def summarize(mode: str, result: dict, strict: bool) -> tuple[str, int, bool]:
    scenario = result.get("scenario") or "chain"
    relay_ok = bool(result.get("relay_ok"))
    recall_ok = bool(result.get("recall_ok"))
    csi_ok = bool(result.get("csi_ok"))
    extra_ok = True
    if scenario == "recall":
        extra_ok = recall_ok
    elif scenario == "csi":
        extra_ok = csi_ok
    if result.get("outcome") == "tail_ok" and relay_ok and extra_ok:
        if scenario == "recall":
            return "tail_ok relay_ok recall_ok", 0, False
        if scenario == "csi":
            return "tail_ok relay_ok csi_ok", 0, False
        return "tail_ok relay_ok", 0, False
    if mode == "real" and result.get("outcome") == "tail_ok" and not strict:
        if scenario == "recall" and not recall_ok:
            return "tail_ok recall_soft_fail", 0, False
        if scenario == "csi" and not csi_ok:
            return "tail_ok csi_soft_fail", 0, False
        if not relay_ok:
            return "tail_ok relay_soft_fail", 0, False
    return f"fail {result.get('failure_class') or 'harness_bug'}", 1, True


def _finish(result, meta, secrets, mode, strict, environ, dbname, server) -> dict:
    line, code, keep_on_fail = summarize(mode, result, strict)
    path = None
    try:
        path = write_report(result, meta, secrets)
    except Exception:
        if not keep_on_fail:
            raise
    keep = keep_on_fail or environ.get("DEMO_KEEP_DB") == "1"
    rel = None if path is None else str(path.relative_to(ROOT))
    extra = keep_lines(dbname, rel) if keep else []
    if keep:
        _emit_keep(dbname, rel)
    elif server is not None:
        db.drop_database(server, dbname)
    calls = (result.get("cost") or {}).get("calls_used")
    if mode == "fake" and calls == 0:
        print("calls_used=0 stop", file=sys.stderr)
    return {
        "exit_code": code,
        "line": line,
        "extra_lines": extra,
        "report_path": rel,
        "result": result,
        "kept": keep,
    }


def _script(scenario: str, note: str, seal: str, hops: int, root_id: str, token: str | None, replies):
    if replies is None:
        if scenario == "recall":
            replies = happy_recall(note, seal, hops, root_id, token or "")
        elif scenario == "fanout":
            replies = happy_fanout(note, seal, hops, root_id)
        elif scenario == "csi":
            replies = happy_csi(note, seal, hops, root_id)
        else:
            replies = happy_chain(note, seal, hops, root_id)
    continued = scenario == "chain" and bool(replies) and replies[0].strip() == "SELECT 1;"
    gate(replies, expected_kinds(scenario, hops, continued=continued))
    return replies


def run(
    *,
    dbname: str = db.DEFAULT_DB,
    mode: str = "fake",
    environ: dict | None = None,
    scenario: str = "chain",
    hops: int | None = None,
    note: str | None = None,
    seal: str | None = None,
    replies: list[str] | None = None,
    reply_factory=None,
    expect_calls: int | None = None,
    expect_cost_zero: bool | None = None,
) -> dict:
    environ = os.environ if environ is None else environ
    strict = environ.get("DEMO_STRICT") == "1"
    if mode == "real" and present_key(environ) == "":
        return _early("credentials_absent", 2)
    try:
        scenario = validate_scenario(scenario)
        if hops is None:
            hops = default_hops(scenario)
        hops = validate_hops(hops, scenario)
        if note is None:
            note = note_for(scenario)
        validate_note(note, scenario)
        check_canonical_notes()
        seal = secrets.token_hex(3) if seal is None else seal
        validate_seal(seal)
        system_chars()
        if scenario == "recall" and not nonroot_headroom(note):
            return _early("note_invalid", 2)
    except ScenarioInvalid:
        return _early("scenario_invalid", 2)
    except HopsInvalid:
        return _early("hops_invalid", 2)
    except NoteInvalid:
        return _early("note_invalid", 2)
    except SealInvalid:
        return _early("seal_invalid", 2)
    except SystemDrift as exc:
        print(f"S={exc.measured}", file=sys.stderr)
        return _early("system_drift", 2)
    root_id = str(uuid.uuid4())
    token = None
    facts = None
    sized = None
    if scenario == "recall":
        try:
            fixed = estimate_fixed(note, hops)
            token, facts, padding = build_facts(note, hops)
            sized = {
                "fixed": fixed,
                "n": padding,
                "B": len(facts),
                "iter0": fixed + len(facts),
                "iter1": fixed + len(PRINT_SQL) + 2 * len(facts),
            }
        except FactsUnsized as exc:
            print(
                f"fixed={exc.fixed} S={exc.system_chars} note_len={exc.note_len}",
                file=sys.stderr,
            )
            return _early("facts_unsized", 2)
        except SystemDrift as exc:
            print(f"S={exc.measured}", file=sys.stderr)
            return _early("system_drift", 2)
    if reply_factory is not None:
        replies = reply_factory(note, seal, hops, root_id, token)
    try:
        replies = _script(scenario, note, seal, hops, root_id, token, replies)
    except ScriptGate as exc:
        print(exc, file=sys.stderr)
        return _early("fail harness_bug", 1)
    if mode == "fake" and expect_calls is None:
        expect_calls = len(replies)
    if expect_cost_zero is None:
        expect_cost_zero = mode == "fake"
    if mode == "real":
        expect_calls = None
        expect_cost_zero = False
    started_at, stamp = stamp_now()
    lease = REAL_LEASE if mode == "real" else FAKE_LEASE
    meta = {
        "started_at": started_at,
        "stamp": stamp,
        "mode": mode,
        "scenario": scenario,
        "hops": hops,
        "note_revision": note_revision(scenario),
        "dbname": dbname,
        "lease": lease,
        "ceilings": ceilings(),
        "calls_limit": CALLS_LIMIT,
        "cost_limit": COST_LIMIT_TEXT,
        "token": token,
        "facts_len": None if facts is None else len(facts),
        "facts_prefix": None if facts is None else facts[:80],
        "sizer": sized,
    }
    hidden = secrets_of(environ)
    inputs = root_inputs(seal, note, hops, root_id, facts, scenario=scenario)
    server = None
    pool_id = None
    provider = None
    started = False
    try:
        server = get_server()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                server = db.setup(dbname)
        except KeyboardInterrupt:
            result = _minimal(root_id, "interrupted", scenario=scenario, hops=hops)
            return _finish(result, meta, hidden, mode, strict, environ, dbname, server)
        except Exception as exc:
            print(type(exc).__name__, _pgcode(exc) or "", file=sys.stderr)
            result = _minimal(root_id, "open_failed", _pgcode(exc), scenario, hops)
            return _finish(result, meta, hidden, mode, strict, environ, dbname, server)
        super_conn = db.connect_super(server, dbname)
        try:
            pool_id = db.seed_and_pool(super_conn)
            if scenario == "recall":
                install_recall_layer(super_conn)
                if facts is None or not jsonb_text_matches(super_conn, facts):
                    print("jsonb_text_mismatch", file=sys.stderr)
                    result = _minimal(root_id, "harness_bug", scenario=scenario, hops=hops)
                    return _finish(result, meta, hidden, mode, strict, environ, dbname, server)
        finally:
            super_conn.close()
        if mode == "real":
            provider = build_real_provider()
        else:
            provider = OrderedScript(replies)
        try:
            if mode == "real":
                preflight = provider.preflight({"model": "deepseek-flash"})
                if preflight:
                    result = _minimal(root_id, "provider_rejected", scenario=scenario, hops=hops)
                    result["preflight_class"] = preflight.get("class")
                    return _finish(
                        result, meta, hidden, mode, strict, environ, dbname, server
                    )
            worker = db.connect_worker(server, dbname)
            try:
                db.require_worker(worker)
                open_root(worker, root_id, pool_id, inputs)
            finally:
                worker.close()
            started = True
            override = None
            try:
                run_until_quiescent(
                    server.get_uri(dbname),
                    provider,
                    WORKER_ID,
                    lease=lease,
                )
            except KeyboardInterrupt:
                override = "interrupted"
            except ScriptExhausted:
                override = "harness_bug"
            except RuntimeError as exc:
                if str(exc) == "quiescent cap":
                    override = "driver_cap"
                elif mode == "real":
                    _abort_real(
                        server, dbname, root_id, pool_id, meta, hidden, seal, note,
                        mode, strict, scenario, hops, token, exc, provider,
                    )
                else:
                    raise
            except Exception as exc:
                if mode == "real":
                    _abort_real(
                        server, dbname, root_id, pool_id, meta, hidden, seal, note,
                        mode, strict, scenario, hops, token, exc, provider,
                    )
                raise
            try:
                result = _read_result(
                    server, dbname, root_id, seal, note, mode, pool_id, strict,
                    scenario, hops, token, expect_calls, expect_cost_zero, override,
                )
            except Exception as exc:
                print(type(exc).__name__, file=sys.stderr)
                result = _minimal(root_id, override or "harness_bug", _pgcode(exc), scenario, hops)
            if mode == "fake":
                calls = (result.get("cost") or {}).get("calls_used")
                if calls != len(replies) and result.get("outcome") == "tail_ok":
                    result["outcome"] = "fail"
                    result["failure_class"] = "harness_bug"
                    result["relay_ok"] = False
                    flags = list(result.get("relay_flags") or [])
                    if "calls_mismatch" not in flags:
                        flags.append("calls_mismatch")
                    result["relay_flags"] = flags
            return _finish(result, meta, hidden, mode, strict, environ, dbname, server)
        finally:
            _close_provider(provider)
    except KeyboardInterrupt:
        if server is not None:
            result = _minimal(root_id, "interrupted", scenario=scenario, hops=hops)
            return _finish(result, meta, hidden, mode, strict, environ, dbname, server)
        return _early("fail interrupted", 1)
    except Exception as exc:
        if str(exc) == "demo real run failed":
            raise
        if server is not None and not started:
            print(type(exc).__name__, _pgcode(exc) or "", file=sys.stderr)
            result = _minimal(root_id, "open_failed", _pgcode(exc), scenario, hops)
            return _finish(result, meta, hidden, mode, strict, environ, dbname, server)
        if server is not None:
            print(type(exc).__name__, file=sys.stderr)
            _emit_keep(dbname, stdout=True)
        raise


def _abort_real(
    server, dbname, root_id, pool_id, meta, hidden, seal, note, mode, strict,
    scenario, hops, token, exc, provider,
) -> None:
    _close_provider(provider)
    print(type(exc).__name__, redact(str(exc), hidden), file=sys.stderr)
    rel = None
    try:
        result = _read_result(
            server, dbname, root_id, seal, note, mode, pool_id, strict,
            scenario, hops, token, None, False, None,
        )
        written = write_report(result, meta, hidden)
        rel = str(written.relative_to(ROOT))
    except Exception:
        rel = None
    finally:
        _emit_keep(dbname, rel, stdout=True)
    print("demo real run failed")
    raise RuntimeError("demo real run failed") from exc


def _read_result(
    server, dbname, root_id, seal, note, mode, pool_id, strict,
    scenario, hops, token, expect_calls, expect_cost_zero, override,
) -> dict:
    conn = db.connect_super(server, dbname)
    try:
        return assert_e2e(
            conn,
            root_id=root_id,
            seal=seal,
            note=note,
            mode=mode,
            pool_id=pool_id,
            scenario=scenario,
            hops=hops,
            token=token,
            strict=strict,
            expect_calls=expect_calls,
            expect_cost_zero=expect_cost_zero,
            override_class=override,
        )
    finally:
        conn.close()


def parse_args(argv: list[str]) -> dict | str:
    scenario = "chain"
    hops = None
    drop_only = False
    drop_name = None
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--drop-only":
            drop_only = True
            if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                drop_name = argv[index + 1]
                index += 1
        elif item == "--scenario":
            if index + 1 >= len(argv):
                return "scenario_invalid"
            scenario = argv[index + 1]
            index += 1
        elif item == "--hops":
            if index + 1 >= len(argv):
                return "hops_invalid"
            try:
                hops = int(argv[index + 1])
            except ValueError:
                return "hops_invalid"
            index += 1
        else:
            return "scenario_invalid"
        index += 1
    if scenario not in {"chain", "recall", "fanout", "csi"}:
        return "scenario_invalid"
    if hops is None:
        hops = default_hops(scenario)
    return {
        "scenario": scenario,
        "hops": hops,
        "drop_only": drop_only,
        "drop_name": drop_name,
    }


def main(argv: list[str] | None = None, environ: dict | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    parsed = parse_args(argv)
    if isinstance(parsed, str):
        print(parsed)
        return 2
    if parsed["drop_only"]:
        db.drop_database(get_server(), parsed["drop_name"] or db.DEFAULT_DB)
        print("dropped")
        return 0
    mode = environ.get("DEMO_MODE", "fake")
    if mode not in {"fake", "real"}:
        print("mode_invalid")
        return 2
    if mode == "real" and present_key(environ) == "":
        print("credentials_absent")
        return 2
    out = run(
        dbname=db.DEFAULT_DB,
        mode=mode,
        environ=environ,
        scenario=parsed["scenario"],
        hops=parsed["hops"],
        note=note_for(parsed["scenario"]),
    )
    print(out["line"])
    if out["exit_code"] == 0 and out["report_path"]:
        print(out["report_path"])
    for line in out["extra_lines"]:
        print(line)
    return out["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
