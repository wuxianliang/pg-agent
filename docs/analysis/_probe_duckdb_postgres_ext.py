"""Live probe: DuckDB postgres core extension against pgembed PostgreSQL 18.4."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import duckdb
import pgembed
import psycopg2


def try_sql(con, name: str, sql: str) -> dict:
    out = {"name": name, "sql": sql.strip()[:500], "ok": False, "result": None, "error": None}
    try:
        out["result"] = str(con.execute(sql).fetchall())[:800]
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def libpq(socket_dir: str, dbname: str = "postgres", user: str = "postgres") -> str:
    return f"host={socket_dir} dbname={dbname} user={user}"


def main() -> int:
    report: dict = {
        "duckdb_pkg": duckdb.__version__,
        "engine": None,
        "pg_version": None,
        "socket_dir": None,
        "probes": [],
    }
    probes = report["probes"]

    with tempfile.TemporaryDirectory(prefix="duck_pg_probe_") as tmp:
        pgdata = Path(tmp) / "pgdata"
        with pgembed.get_server(pgdata) as server:
            info = server.get_postmaster_info()
            socket_dir = str(info.socket_dir)
            report["socket_dir"] = socket_dir
            uri = server.get_uri("postgres")
            report["pg_uri_kind"] = "unix-socket" if info.socket_dir else "tcp"
            report["pg_uri"] = uri.replace(socket_dir, "<socket>") if socket_dir else uri

            pg = psycopg2.connect(host=socket_dir, dbname="postgres", user="postgres")
            pg.autocommit = True
            cur = pg.cursor()
            cur.execute("SELECT version()")
            report["pg_version"] = cur.fetchone()[0]
            cur.execute(
                """
                CREATE TABLE public.probe_src (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    amount NUMERIC(10,2),
                    tags TEXT[],
                    meta JSONB,
                    created_at TIMESTAMPTZ
                );
                INSERT INTO public.probe_src VALUES
                  (1, 'a', 1.50, ARRAY['x','y'], '{"k":1}'::jsonb, '2026-08-28 12:00:00+00'),
                  (2, 'b', 2.25, ARRAY['z'], '{"k":2}'::jsonb, '2026-08-28 13:00:00+00');
                """
            )

            ddb = duckdb.connect()
            report["engine"] = ddb.execute("SELECT version()").fetchone()[0]
            connstr = libpq(socket_dir)
            connstr_sql = connstr.replace("'", "''")

            probes.append(try_sql(ddb, "INSTALL postgres", "INSTALL postgres"))
            probes.append(try_sql(ddb, "LOAD postgres", "LOAD postgres"))
            probes.append(
                try_sql(
                    ddb,
                    "ATTACH READ_ONLY",
                    f"ATTACH '{connstr_sql}' AS pg (TYPE postgres, READ_ONLY)",
                )
            )
            probes.append(try_sql(ddb, "SHOW pg tables", "SHOW TABLES FROM pg"))
            probes.append(
                try_sql(
                    ddb,
                    "SELECT attached probe_src",
                    "SELECT id, name, amount FROM pg.public.probe_src ORDER BY id",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "SELECT types from attached",
                    "SELECT id, typeof(amount), typeof(tags), typeof(meta), typeof(created_at) FROM pg.public.probe_src WHERE id = 1",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "filter on attached",
                    "SELECT id FROM pg.public.probe_src WHERE amount > 2",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "snapshot CREATE TABLE AS",
                    "CREATE TABLE snap AS SELECT * FROM pg.public.probe_src",
                )
            )
            probes.append(try_sql(ddb, "select snap", "SELECT id, name FROM snap ORDER BY id"))

            # mutate postgres, see if attached view sees it and snap does not
            cur.execute("UPDATE public.probe_src SET name = 'a-updated' WHERE id = 1")
            probes.append(
                try_sql(
                    ddb,
                    "attached after PG update",
                    "SELECT id, name FROM pg.public.probe_src WHERE id = 1",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "snap after PG update",
                    "SELECT id, name FROM snap WHERE id = 1",
                )
            )

            probes.append(
                try_sql(
                    ddb,
                    "INSERT into READ_ONLY attached",
                    "INSERT INTO pg.public.probe_src VALUES (3, 'c', 3, NULL, NULL, NULL)",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "postgres_execute INSERT",
                    "SELECT * FROM postgres_execute('pg', 'INSERT INTO public.probe_src(id, name, amount) VALUES (99, ''via-exec'', 9)')",
                )
            )
            cur.execute("SELECT id, name FROM public.probe_src WHERE id = 99")
            report["pg_row_99_after_execute"] = str(cur.fetchall())

            probes.append(
                try_sql(
                    ddb,
                    "postgres_scan",
                    f"SELECT id, name FROM postgres_scan('{connstr_sql}', 'public', 'probe_src') ORDER BY id",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "postgres_query",
                    "SELECT * FROM postgres_query('pg', 'SELECT id, name FROM public.probe_src ORDER BY id')",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "EXPLAIN attached filter",
                    "EXPLAIN SELECT id FROM pg.public.probe_src WHERE amount > 2",
                )
            )

            probes.append(try_sql(ddb, "DETACH pg", "DETACH pg"))
            probes.append(
                try_sql(
                    ddb,
                    "select snap after DETACH",
                    "SELECT count(*) FROM snap",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "lock after DETACH",
                    "SET enable_external_access = false",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "select snap after lock",
                    "SELECT id, name FROM snap ORDER BY id",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "ATTACH after lock",
                    f"ATTACH '{connstr_sql}' AS pg2 (TYPE postgres, READ_ONLY)",
                )
            )
            probes.append(
                try_sql(
                    ddb,
                    "postgres_scan after lock (already loaded)",
                    f"SELECT id FROM postgres_scan('{connstr_sql}', 'public', 'probe_src') LIMIT 1",
                )
            )

            # Second connection: lock first, cannot load
            ddb2 = duckdb.connect()
            ddb2.execute("SET autoinstall_known_extensions = false")
            ddb2.execute("SET autoload_known_extensions = false")
            ddb2.execute("SET enable_external_access = false")
            probes.append(try_sql(ddb2, "LOAD postgres after lock-first", "LOAD postgres"))

            # Third: extension as copy then lock, query-only
            ddb3 = duckdb.connect()
            ddb3.execute("INSTALL postgres")
            ddb3.execute("LOAD postgres")
            ddb3.execute(f"ATTACH '{connstr_sql}' AS pg (TYPE postgres, READ_ONLY)")
            ddb3.execute("CREATE TABLE local_src AS SELECT * FROM pg.public.probe_src")
            ddb3.execute("DETACH pg")
            ddb3.execute("SET autoinstall_known_extensions = false")
            ddb3.execute("SET autoload_known_extensions = false")
            ddb3.execute("SET enable_external_access = false")
            probes.append(
                try_sql(
                    ddb3,
                    "copy-then-lock local_src",
                    "SELECT id, name FROM local_src ORDER BY id",
                )
            )
            probes.append(
                try_sql(
                    ddb3,
                    "copy-then-lock CREATE TEMP VIEW",
                    "CREATE TEMP VIEW v1 AS SELECT id, name FROM local_src WHERE id = 1; SELECT * FROM v1",
                )
            )

            pg.close()

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
