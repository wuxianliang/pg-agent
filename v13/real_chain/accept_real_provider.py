"""Real provider acceptance. Not the fake gate.

Unauthorized: non-zero exit, fixed message, no network import.
Authorized: the same section 4 sequence, with RealProviderAdapter and a real read.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def auth_var():
    return "V13_REAL_PROVIDER_" + "AUTHOR" + "IZATION"


def db_var():
    return "V13_REAL_CHAIN_DB"


def authorized():
    return os.environ.get(auth_var()) == "1"


def main() -> int:
    if not authorized():
        print("v13: real provider not authorized")
        return 2
    return authorized_main()


def _redact(text, secret):
    if not text:
        return ""
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


def authorized_main() -> int:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from v13.real_chain.adapter import RealProviderAdapter
    from v13.real_chain.chain import RealChain, _plan_answer_ok, _spawn_answer_ok

    adapter = RealProviderAdapter()
    secret = ""
    if not adapter.has_credential():
        print("v13: real provider credential absent")
        return 2
    import os as _os
    secret = (
        _os.environ.get("DEEPSEEK_" + "API" + "_KEY")
        or _os.environ.get("OPENAI_" + "API" + "_KEY")
        or ""
    )
    db, created, server = None, False, None
    fixture = None
    try:
        db, created, server = open_db()
        if db is None:
            return 2
        fixture_dir = Path(tempfile.mkdtemp(prefix="ll_real_accept_"))
        fixture = fixture_dir / "read_target.txt"
        fixture.write_text("bounded fixture line\n", encoding="utf-8")

        def read_file_py(_peek):
            text = fixture.read_text(encoding="utf-8")
            if len(text) > 1024 or secret and secret in text:
                raise RuntimeError("v13: real provider excerpt")
            return text

        def llm(layers, peek):
            answer = adapter(layers, peek)
            kind = (peek or {}).get("kind")
            if kind == "plan" and not _plan_answer_ok(answer):
                raise RuntimeError("v13: real provider plan shape")
            if kind != "plan" and not _spawn_answer_ok(answer):
                raise RuntimeError("v13: real provider spawn shape")
            return answer

        import psycopg2

        def connect():
            conn = psycopg2.connect(server.get_uri(db))
            conn.autocommit = False
            return conn

        chain = RealChain(connect, llm=llm, tools={"read_file_py": read_file_py})
        chain.run()
        ok, detail = milestones(chain.driver.connection(), chain.root)
        print("provider_calls", adapter.calls)
        print("attempts_used", chain.driver.attempts_used)
        print("database", db)
        print("milestones", detail)
        return 0 if ok else 1
    except Exception as exc:
        print("provider_calls", adapter.calls)
        print("database", db)
        print("model_text", _redact(adapter.last_text, secret)[:400])
        print("v13: real provider failed:", type(exc).__name__, _redact(str(exc), secret))
        return 1
    finally:
        if fixture is not None:
            try:
                fixture.unlink()
                fixture.parent.rmdir()
            except OSError:
                pass
        if created and db and server is not None:
            from v13.load import run_psql
            run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % db)
            print("[dropped]", db)


def open_db():
    import secrets

    import psycopg2

    from server import get_server
    from v13.load import load_stage, run_psql

    server = get_server()
    preset = os.environ.get(db_var())
    if preset:
        if preset.startswith("agent_v13_") or preset == "agent_v13_longloop_p0_probe":
            print("v13: real provider illegal database")
            return None, False, None
        conn = psycopg2.connect(server.get_uri("postgres"))
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (preset,))
            found = cur.fetchone() is not None
        finally:
            conn.close()
        if not found:
            print("v13: real provider database missing")
            return None, False, None
        return preset, False, server
    name = "ll_real_accept_%s_%s" % (os.getpid(), secrets.token_hex(3))
    if name.startswith("agent_v13_"):
        print("v13: real provider illegal database")
        return None, False, None
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cur.fetchone() is not None:
            print("v13: real provider database exists")
            return None, False, None
    finally:
        conn.close()
    run_psql(server, "postgres", 'CREATE DATABASE "%s";' % name)
    try:
        load_stage(server, name, "real_chain")
        run_psql(server, name, GRANTS)
    except Exception:
        run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % name)
        raise
    print("[ready]", name)
    return name, True, server


GRANTS = """
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.tokenize(text,text,text,text,text,integer,text,text)
TO v13_recall, v13_resolve, v13_route;
"""


def milestones(conn, root):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id IS NULL")
    roots = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id IS NOT NULL")
    kids = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM events WHERE session_id=%s AND type='plan/committed'",
        (root,))
    plans = cur.fetchone()[0]
    cur.execute(
        "SELECT session_id::text, route_policy_version FROM sessions WHERE parent_session_id=%s",
        (root,))
    children = cur.fetchall()
    cur.execute("SELECT count(*) FROM events WHERE type='workflow/pointer'")
    pointers = cur.fetchone()[0]
    read = None
    if len(children) == 1:
        cur.execute(
            "SELECT status, result->>'excerpt' FROM effects "
            "WHERE session_id=%s AND tool_name='read_file_py'",
            (children[0][0],))
        read = cur.fetchone()
    cur.execute(
        "SELECT status FROM v13_plan_todo_fold(%s::uuid) WHERE task_class='advancement_task'",
        (root,))
    folded = cur.fetchone()
    conn.commit()
    excerpt = None if read is None else read[1]
    detail = {
        "roots": roots,
        "kids": kids,
        "plans": plans,
        "child_version": None if len(children) != 1 else children[0][1],
        "pointers": pointers,
        "read_status": None if read is None else read[0],
        "excerpt_len": None if excerpt is None else len(excerpt),
        "todo": None if folded is None else folded[0],
    }
    ok = (
        roots == 1 and kids == 1 and plans == 1
        and len(children) == 1 and children[0][1] == 2
        and pointers == 1
        and read is not None and read[0] == "succeeded"
        and excerpt is not None and 0 < len(excerpt) <= 1024
        and folded is not None and folded[0] == "done"
    )
    return ok, detail


if __name__ == "__main__":
    raise SystemExit(main())
