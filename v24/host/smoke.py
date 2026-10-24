"""Opt-in real-provider smoke for the v24 host.  Not a gate.

    uv run python -m v24.host.smoke                        # not_requested, 0
    uv run python -m v24.host.smoke --real-provider-smoke  # opt-in

Without a key the command prints ``credentials_absent`` and exits 2 **before**
constructing an adapter or opening a database.  With a key it builds one
disposable v24 fixture and runs exactly one short ``start -> model -> final``
through the real adapter.  It prints only the endpoint host, model, ids, usage
and finish; prompts, content, reasoning and credentials are never printed.

Real network I/O is allowed only from this opt-in entry (AGENTS.md).  The
journal is removed on success and retained, still 0600, on failure.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MODEL = "deepseek-flash"
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


def _live(key: str) -> int:
    from v24.s1.setup_db import server_helper_scope, setup_db

    journal_dir = tempfile.mkdtemp(prefix="v24-host-smoke-")
    os.chmod(journal_dir, 0o700)
    journal_path = Path(journal_dir) / "journal.jsonl"
    journal = None
    db = None
    try:
        with server_helper_scope(), setup_db() as fixture:
            scope = _bootstrap(fixture)
            from v24.host.db import HostDB
            from v24.host.deepseek import DeepSeekAdapter
            from v24.host.journal import HostJournal
            from v24.host.worker import HostWorker

            db = HostDB(fixture.role_dsn("admin"), fixture.role_dsn("service"))
            adapter = DeepSeekAdapter(api_key=key, timeout_s=120)
            journal = HostJournal.open(journal_path)
            try:
                worker = HostWorker(db, journal, adapter=adapter)
                stats = worker.run_until_idle(scope, max_rounds=8)
                model = _first_model(db, scope)
                run_id = _run_of(db, model)
                run = db.host_runs(scope)
                completed = any(
                    item["run_id"] == run_id and item["status"] == "completed"
                    for item in run.get("items", []))
                if not completed:
                    print(f"[failed] run not completed; journal={journal_path}")
                    return 1
                reply = stats.last_reply or {}
                tokens = None
                if isinstance(reply, dict):
                    prompt = reply.get("prompt_tokens")
                    completion = reply.get("completion_tokens")
                    if isinstance(prompt, int) and isinstance(completion, int):
                        tokens = prompt + completion
                finish = reply.get("finish_kind") if isinstance(reply, dict) else None
                host = urlparse(_endpoint()).hostname
                print(
                    f"[smoke] endpoint={host} model={_MODEL} run={run_id} "
                    f"effect={model} "
                    f"tokens={tokens if tokens is not None else 'unknown'} "
                    f"finish={finish if isinstance(finish, str) else 'unknown'} "
                    f"result=completed")
                _assert_no_leak(key, reply)
            finally:
                journal.close()
                journal = None
                db.close()
                db = None
        shutil.rmtree(journal_dir, ignore_errors=True)
        return 0
    except Exception as exc:
        # After the key check the run is a real attempt: never degrade to SKIP.
        print(f"[failed] real-provider smoke failed; journal={journal_path} "
              f"reason={exc.__class__.__name__}")
        return 1
    finally:
        if journal is not None:
            journal.close()
        if db is not None:
            db.close()


def _endpoint() -> str:
    from v24.host.deepseek import ENDPOINT
    return ENDPOINT


def _bootstrap(fixture) -> str:
    from psycopg2.extras import Json

    conn = fixture.connect("admin")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT v24.scope_control('create_root',NULL,%s,%s,%s)",
                (Json({}), "default", f"v24-smoke-scope-{os.getpid()}"))
            response = cur.fetchone()[0]
        conn.commit()
        if response.get("disposition") != "committed":
            raise RuntimeError(f"scope bootstrap: {response.get('error')}")
        scope = response["emitted"][0]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT v24.start(%s,NULL,%s,%s,%s)",
                (scope, Json(_INPUT), Json(_BUDGET), f"v24-smoke-start-{os.getpid()}"))
            response = cur.fetchone()[0]
        conn.commit()
        if response.get("disposition") != "committed":
            raise RuntimeError(f"start bootstrap: {response.get('error')}")
        return scope
    finally:
        conn.close()


def _first_model(db, scope):
    response = db.host_effects(scope, None, None, 64)
    for item in response.get("items", []):
        if item.get("kind") == "model_call":
            return item["effect_id"]
    return None


def _run_of(db, effect_id):
    if effect_id is None:
        return None
    response = db.host_effect(effect_id)
    if "effect" not in response:
        return None
    return response["effect"].get("run_id")


def _assert_no_leak(key: str, reply) -> None:
    text = repr(reply)
    if key and key in text:
        raise RuntimeError("summary carried the API key")
    if "Authorization" in text or "Bearer " in text:
        raise RuntimeError("summary carried an Authorization header")


if __name__ == "__main__":
    raise SystemExit(main())
