"""Opt-in real-provider smoke for the v24 host. Not a gate.

No flag: not_requested/0. Flag without a key: credentials_absent/2, before
constructing an adapter or opening a database. A configured attempt executes
one short start -> model -> final. Only validated metadata is printed, after
resources close and the private journal directory is successfully removed.
Failures before deletion retain the journal; partial deletion cannot be undone.
Real network I/O is allowed only from this opt-in entry (AGENTS.md).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_BUDGET = {"steps": 3, "tool_calls": 0, "tokens": 5000, "wall_ms": 60000}
_INPUT = {
    "messages": [{"role": "user", "content": "Reply with exactly: SELECT 1;"}],
    "max_output_tokens": 32,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--real-provider-smoke" not in args:
        print("not_requested")
        return 0
    return _flagged()


def _key() -> str:
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""


def _flagged() -> int:
    key = _key()
    if not key:
        print("credentials_absent")
        return 2
    return _live(key)


def _close_resources(journal, db, connections, *, best_effort=False) -> None:
    # Own the raw connections too: HostDB construction/close can fail halfway.
    error = None
    interrupt = None
    for resource in (journal, db, *connections):
        if resource is None:
            continue
        try:
            resource.close()
        except KeyboardInterrupt as exc:
            if interrupt is None:
                interrupt = exc
        except Exception as exc:
            if error is None:
                error = exc
    # An interrupt always wins after every close attempt has had a chance to
    # run. Ordinary best-effort cleanup errors are intentionally suppressed.
    if interrupt is not None:
        raise interrupt
    if error is not None and not best_effort:
        raise error


def _evidence_path(journal_path, journal_dir):
    """Return a readable evidence path without allowing probing to escape."""
    for path in (journal_path, journal_dir):
        if path is None:
            continue
        try:
            if path.exists():
                return path
        except Exception:
            continue
    return None


def _live(key: str) -> int:
    journal_dir = journal_path = None
    deleting = False
    try:
        from v24.s1.setup_db import server_helper_scope, setup_db
        from v24.host.db import HostDB
        from v24.host.deepseek import DeepSeekAdapter
        from v24.host.journal import HostJournal
        from v24.host.worker import HostWorker

        journal_dir = Path(tempfile.mkdtemp(prefix="v24-host-smoke-"))
        journal_path = journal_dir / "journal.jsonl"
        os.chmod(journal_dir, 0o700)
        with server_helper_scope(), setup_db() as fixture:
            journal = db = None
            connections = []
            try:
                scope, run_id, model_id = _bootstrap(fixture)
                for role in ("admin", "service"):
                    connections.append(fixture.connect(role))
                db = HostDB(*connections)
                adapter = DeepSeekAdapter(api_key=key, timeout_s=120)
                journal = HostJournal.open(journal_path)
                worker = HostWorker(db, journal, adapter=adapter)
                worker.run_until_idle(scope, max_rounds=8)
                summary, reply = _verify_completion(
                    db, journal, scope, run_id, model_id)
                _assert_no_leak(key, reply, summary)
                _close_resources(journal, db, connections)
                journal = db = None
                connections = []
            finally:
                _close_resources(journal, db, connections, best_effort=True)
        deleting = True
        shutil.rmtree(journal_dir)
        _require(not journal_dir.exists())
        print(summary)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # Never print exception messages, requests, replies or credentials.
        # A partially removed directory is remaining evidence, not a full copy.
        evidence = "remaining" if deleting else "retained"
        available = _evidence_path(journal_path, journal_dir)
        print(f"[failed] reason={exc.__class__.__name__} evidence={evidence if available else 'absent'} "
              f"journal={available if available is not None else 'unavailable'}")
        if isinstance(exc, KeyboardInterrupt):
            raise
        return 1


def _require(condition) -> None:
    if not condition:
        raise RuntimeError("smoke verification failed")


def _uuid(value) -> str:
    _require(isinstance(value, str))
    return str(UUID(value))


def _emitted(response, count: int) -> list[str]:
    _require(isinstance(response, dict) and "error" not in response
             and response.get("disposition") == "committed")
    emitted = response.get("emitted")
    _require(isinstance(emitted, list) and len(emitted) == count)
    return [_uuid(item) for item in emitted]


def _bootstrap(fixture) -> tuple[str, str, str]:
    from psycopg2.extras import Json

    nonce = uuid4().hex
    conn = fixture.connect("admin")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT v24.scope_control('create_root',NULL,%s,%s,%s)",
                (Json({}), "default", f"v24-smoke-scope-{nonce}"))
            response = cur.fetchone()[0]
        conn.commit()
        scope, = _emitted(response, 1)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT v24.start(%s,NULL,%s,%s,%s)",
                (scope, Json(_INPUT), Json(_BUDGET), f"v24-smoke-start-{nonce}"))
            response = cur.fetchone()[0]
        conn.commit()
        run_id, model_id = _emitted(response, 2)
        return scope, run_id, model_id
    finally:
        conn.close()


def _single_page(response) -> dict:
    _require(isinstance(response, dict) and "error" not in response
             and type(response.get("v")) is int and response["v"] == 1
             and type(response.get("limit")) is int and response["limit"] == 64
             and response.get("has_more") is False
             and "next_cursor" in response and response["next_cursor"] is None)
    items = response.get("items")
    _require(isinstance(items, list) and len(items) == 1
             and isinstance(items[0], dict))
    return items[0]


def _natural(value) -> int:
    _require(type(value) is int and value >= 0)
    return value


def _verify_completion(db, journal, scope_id, run_id, model_id) -> tuple[str, dict]:
    from v24.host.deepseek import ENDPOINT, MODEL

    scope_id, run_id, model_id = map(_uuid, (scope_id, run_id, model_id))
    run = _single_page(db.host_runs(scope_id))
    _require(run["run_id"] == run_id and run["scope_id"] == scope_id
             and run["status"] == "completed")
    effect = _single_page(db.host_run_effects(run_id))
    _require(effect["effect_id"] == model_id and effect["run_id"] == run_id
             and effect["scope_id"] == scope_id and effect["kind"] == "model_call"
             and effect["status"] == "succeeded")
    outcome = effect["outcome"]
    _require(isinstance(outcome, dict) and outcome["class"] == "success")
    result = outcome["body"]["result"]
    _require(isinstance(result, dict) and isinstance(result["final"], dict)
             and isinstance(result["final"]["text"], str))
    text = result["final"]["text"]
    _require(run["result"]["final_text"] == text)
    usage = result["usage"]
    tokens, wall_ms = _natural(usage["tokens"]), _natural(usage["wall_ms"])

    records = journal.records_for(model_id)
    starts = [r for r in records if r["event_type"] == "dispatch_started"]
    finishes = [r for r in records if r["event_type"] == "dispatch_finished"]
    _require(len(starts) == len(finishes) == 1)
    started, finished = starts[0], finishes[0]
    _require(records.index(started) < records.index(finished)
             and started["run_id"] == finished["run_id"] == run_id)
    _require(journal.last("dispatch_finished", model_id) == finished)
    payload = finished["payload"]
    mapping = payload["mapping"]
    _require(payload["outcome"] == outcome and mapping["class"] == "success"
             and mapping["result"] == result)
    mapped_usage = mapping["result"]["usage"]
    _require(_natural(mapped_usage["tokens"]) == tokens
             and _natural(mapped_usage["wall_ms"]) == wall_ms)
    reply = journal.last("dispatch_finished", model_id)["payload"]["mapping"]["reply"]
    _require(isinstance(reply, dict) and reply["finish_kind"] == "stop"
             and reply["content"] == text)
    _require(_natural(reply["prompt_tokens"]) + _natural(reply["completion_tokens"]) == tokens
             and _natural(reply["wall_ms"]) == wall_ms)
    host = urlparse(ENDPOINT).hostname
    _require(isinstance(host, str) and bool(host))
    summary = (f"[smoke] endpoint={host} model={MODEL} run={run_id} effect={model_id} "
               f"tokens={tokens} finish=stop wall_ms={wall_ms} result=completed")
    return summary, reply


def _assert_no_leak(key: str, reply, summary: str) -> None:
    text = repr((reply, summary))
    if key and key in text:
        raise RuntimeError("summary carried the API key")
    if "Authorization" in text or "Bearer " in text:
        raise RuntimeError("summary carried an Authorization header")


if __name__ == "__main__":
    raise SystemExit(main())
