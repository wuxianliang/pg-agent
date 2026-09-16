"""Phase 1 runtime gates for the v7 DuckDB/Flock Python binding.

Run with a Python that imports the v7 wheel, not the v6 pin:
  /tmp/v7-phase1-verify/bin/python v7/tests/test_phase1_runtime.py

Does not xfail. Does not rewrite NEAREST. A second process is opened only
to prove the live-file lock rejects non-owner rw/ro connects.
"""
from __future__ import annotations

import gc
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from v7.runtime import reader_guard as reader_guard_mod
from v7.runtime.reader_guard import (
    GuardedReaderConnection,
    ReaderAdmissionError,
    ReaderGuardError,
    ReaderPool,
    _is_memory_database,
    _open_reader_raw,
    connect_reader,
    reader_execute,
    reader_sql_allowed,
)

V7_WHEEL = Path(
    "/Users/wxl/Projects/duckdb-python-pgagent/dist-v7/"
    "duckdb-1.6.0.dev366-cp312-cp312-macosx_26_0_arm64.whl"
)
V7_SHA256 = "d4e8fd28e6c6daa22dba349ed253b45b7a9f01e110126f65dc79a126308ba5ff"
V6_WHEEL = Path(
    "/Users/wxl/Projects/duckdb-python-pgagent/dist-special-g1/"
    "duckdb-1.6.0.dev366+ga1f0ab1911-cp312-cp312-macosx_26_0_arm64.whl"
)
V6_SHA256 = "fa4ba6fb193e98d9273d494d1255393a4df33b8d6890fbbcdd65b064b3c15ad9"
TARGET_COMMIT = "a1f0ab191185c0852b162adc6feb206822dc9daa"
READER_DEFAULT = 4
READER_HARD_CAP = 16
TEMP_COLUMNS = (
    "candidate_id",
    "document_id",
    "revision",
    "chunk_id",
    "document_ordinal",
    "chunk_ordinal",
    "source_query_ordinal",
    "bm25_score",
    "dense_score",
    "multi_vector_score",
    "llm_relevance_score",
    "page_start",
    "page_end",
    "line_start",
    "line_end",
    "range_origin",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_artifacts() -> None:
    assert V7_WHEEL.is_file(), f"missing v7 wheel {V7_WHEEL}"
    assert V6_WHEEL.is_file(), f"missing v6 wheel {V6_WHEEL}"
    got_v7 = _sha256(V7_WHEEL)
    got_v6 = _sha256(V6_WHEEL)
    assert got_v7 == V7_SHA256, f"v7 sha {got_v7} != {V7_SHA256}"
    assert got_v6 == V6_SHA256, f"v6 wheel mutated: {got_v6}"
    assert got_v7 != got_v6, "v7 wheel must not reuse the v6 hash"


def _import_v7():
    import duckdb

    imported = Path(duckdb.__file__).resolve()
    text = imported.as_posix()
    assert "dist-special-g1" not in text, f"imported v6 wheel path {imported}"
    # The isolated venv install lives under site-packages, not the v6 extra.
    so = Path(duckdb.__file__).resolve().parent.parent / "_duckdb.cpython-312-darwin.so"
    if so.is_file():
        assert "dist-special-g1" not in so.as_posix()
    return duckdb


def check_health(duckdb) -> None:
    con = duckdb.connect(":memory:")
    rows = {r[0]: (r[1], r[2]) for r in con.execute("SELECT component, status, detail FROM flock_rag_health()").fetchall()}
    assert rows["abi"][0] == "ok"
    assert rows["abi"][1] == TARGET_COMMIT
    assert rows["catalog"][0] == "not_initialized"
    assert rows["tachiom"] == ("blocked", "RAG_MULTI_VECTOR_UNAVAILABLE")
    assert rows["manifest"][0] == "phase_1_in_progress"
    ext = {
        r[0]: (r[1], r[2], r[3])
        for r in con.execute(
            "SELECT extension_name, loaded, installed, install_mode "
            "FROM duckdb_extensions() WHERE extension_name IN ('flock','fts','tachiom')"
        ).fetchall()
    }
    assert ext["flock"][2] == "STATICALLY_LINKED"
    assert ext["fts"][2] == "STATICALLY_LINKED"
    assert "tachiom" not in ext
    # Health fts row is compile-flag based; static link is the authority.
    assert rows["fts"][0] in {"unknown", "linked"}
    con.close()


def check_exact_nearest(duckdb) -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE products(product_id VARCHAR, name VARCHAR, price INT, country VARCHAR, embedding FLOAT[3])")
    con.execute(
        "INSERT INTO products VALUES "
        "('P1','Trail running shoes',120,'EU',[0.9,0.1,0.1]),"
        "('P2','Hiking boots',180,'EU',[0.8,0.2,0.0]),"
        "('P3','Office shoes',95,'US',[0.1,0.9,0.1]),"
        "('P4','Sandals',45,'US',[0.0,0.8,0.2]),"
        "('P5','Running shoes',110,'EU',[0.5,0.5,0.0])"
    )
    exact_sql = (
        "SELECT t.product_id FROM (SELECT [1.0,0.0,0.0]::FLOAT[3] AS embedding) q "
        "INNER JOIN products t EXACT NEAREST 3 BY DISTANCE array_distance(q.embedding, t.embedding) "
        "ORDER BY t.product_id"
    )
    approx_sql = exact_sql.replace("EXACT NEAREST 3", "APPROX NEAREST 3")
    exact = [r[0] for r in con.execute(exact_sql).fetchall()]
    assert exact == ["P1", "P2", "P5"], f"EXACT NEAREST 3 got {exact}"
    approx = [r[0] for r in con.execute(approx_sql).fetchall()]
    # Record APPROX; do not default to it. Currently informational and identical.
    assert approx == exact
    # Implicit top-1 still parses; v7 call sites must keep explicit N EXACT.
    top1 = con.execute(
        "SELECT t.product_id FROM (SELECT [1.0,0.0,0.0]::FLOAT[3] AS embedding) q "
        "INNER JOIN products t NEAREST BY DISTANCE array_distance(q.embedding, t.embedding)"
    ).fetchall()
    assert top1[0][0] == "P1"
    con.close()


def _staging_sql() -> str:
    return (
        "CREATE TEMP TABLE rag_candidates ("
        + ", ".join(
            [
                "candidate_id VARCHAR",
                "document_id VARCHAR",
                "revision VARCHAR",
                "chunk_id VARCHAR",
                "document_ordinal INTEGER",
                "chunk_ordinal INTEGER",
                "source_query_ordinal INTEGER",
                "bm25_score DOUBLE",
                "dense_score DOUBLE",
                "multi_vector_score DOUBLE",
                "llm_relevance_score DOUBLE",
                "page_start INTEGER",
                "page_end INTEGER",
                "line_start INTEGER",
                "line_end INTEGER",
                "range_origin VARCHAR",
            ]
        )
        + ")"
    )


def _assert_rejected(fn, message: str):
    try:
        fn()
    except ReaderGuardError:
        return
    except ReaderAdmissionError:
        return
    raise AssertionError(message)


def _is_raw_conn(obj) -> bool:
    if obj is None:
        return False
    import duckdb

    cls = getattr(duckdb, "DuckDBPyConnection", None)
    if cls is not None and isinstance(obj, cls):
        return True
    return type(obj).__name__ == "DuckDBPyConnection"


def _assert_guarded(obj, message: str):
    if _is_raw_conn(obj):
        raise AssertionError(f"{message}: raw DuckDBPyConnection")
    if not isinstance(obj, GuardedReaderConnection):
        raise AssertionError(f"{message}: got {type(obj)!r}")


def _assert_fetch_bound_to_wrapper(obj, message: str) -> None:
    for name in (
        "fetchone",
        "fetchall",
        "fetchmany",
        "fetchdf",
        "fetch_df",
        "fetch_df_chunk",
        "fetchnumpy",
        "fetch_arrow_table",
        "fetch_record_batch",
        "df",
        "arrow",
        "pl",
        "torch",
        "to_arrow_table",
        "to_arrow_reader",
    ):
        meth = getattr(obj, name)
        owner = getattr(meth, "__self__", None)
        if owner is not obj:
            raise AssertionError(f"{message}: {name}.__self__ is {type(owner)!r}, not wrapper")
        if _is_raw_conn(owner):
            raise AssertionError(f"{message}: {name}.__self__ is raw DuckDBPyConnection")


def _assert_no_raw_exposed(obj, message: str) -> None:
    mapping = getattr(obj, "__dict__", None)
    if isinstance(mapping, dict):
        for key, value in mapping.items():
            if _is_raw_conn(value):
                raise AssertionError(f"{message}: __dict__[{key!r}] is raw")
    try:
        vars_map = vars(obj)
    except TypeError:
        vars_map = None
    if isinstance(vars_map, dict):
        for key, value in vars_map.items():
            if _is_raw_conn(value):
                raise AssertionError(f"{message}: vars()[{key!r}] is raw")
    for name in (
        "_catalog_conn",
        "_GuardedReaderConnection__raw",
        "__raw",
        "_raw",
        "_conn",
        "connection",
        "raw",
    ):
        try:
            value = getattr(obj, name)
        except (AttributeError, ReaderGuardError):
            continue
        if callable(value) and name == "_catalog_conn":
            try:
                value = value()
            except ReaderGuardError:
                continue
        if _is_raw_conn(value):
            raise AssertionError(f"{message}: getattr({name!r}) is raw")
    for name in ("unwrap", "duplicate"):
        try:
            value = getattr(obj, name)
        except (AttributeError, ReaderGuardError):
            continue
        if callable(value):
            try:
                value = value()
            except ReaderGuardError:
                continue
        if _is_raw_conn(value):
            raise AssertionError(f"{message}: {name}() is raw")


def check_writer_readers_and_temp(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "text.rag.duckdb")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER, body VARCHAR)")
        writer.execute("INSERT INTO docs VALUES (1, 'alpha'), (2, 'beta')")
        writer.commit()

        def opener():
            return connect_reader(duckdb, db_path)

        default_pool = ReaderPool(opener)
        assert default_pool.limit == READER_DEFAULT
        default_readers = [default_pool.acquire() for _ in range(READER_DEFAULT)]
        _assert_rejected(default_pool.acquire, "default pool 5th reader must be rejected")
        for r in default_readers:
            r.close()
        default_pool.close()

        over = ReaderPool(opener, max_readers=READER_HARD_CAP + 1)
        assert over.limit == READER_HARD_CAP
        over.close()

        pool = ReaderPool(opener, max_readers=READER_HARD_CAP)
        assert pool.limit == READER_HARD_CAP
        readers = [pool.acquire() for _ in range(READER_DEFAULT)]
        extra = [pool.acquire() for _ in range(READER_HARD_CAP - READER_DEFAULT)]
        assert len(readers) + len(extra) == READER_HARD_CAP
        _assert_rejected(pool.acquire, "17th reader must be rejected")

        for i, r in enumerate(readers):
            n = r.execute("SELECT count(*) FROM docs").fetchone()[0]
            assert n == 2, f"reader {i} saw {n}"

        r0 = readers[0]
        reader_execute(r0, _staging_sql())
        cols = [row[1] for row in r0.execute("PRAGMA table_info('rag_candidates')").fetchall()]
        assert tuple(cols) == TEMP_COLUMNS, cols
        reader_execute(
            r0,
            "INSERT INTO rag_candidates (candidate_id, document_id, revision, chunk_id, "
            "document_ordinal, chunk_ordinal, source_query_ordinal, range_origin, page_start, page_end) "
            "VALUES ('c1','d1','r1','k1', 0, 0, 0, 'source_line', 1, 1)",
        )
        assert r0.execute("SELECT count(*) FROM rag_candidates").fetchone()[0] == 1

        # Connection-local: other reader must not see the TEMP table.
        # Must not catch AssertionError from a leak (that used to pass the test).
        try:
            readers[1].execute("SELECT count(*) FROM rag_candidates")
        except AssertionError:
            raise
        except Exception as exc:
            msg = str(exc).lower()
            assert "rag_candidates" in msg or "does not exist" in msg or "not found" in msg, exc
        else:
            raise AssertionError("TEMP rag_candidates leaked to another connection")

        persistent = Path(db_path)
        main_tables = [row[0] for row in writer.execute("SHOW TABLES").fetchall()]
        assert "rag_candidates" not in main_tables

        writer.execute("CREATE TABLE rag_candidates (candidate_id VARCHAR)")
        writer.execute("INSERT INTO rag_candidates VALUES ('persistent')")
        writer.commit()
        reader_execute(r0, "INSERT INTO rag_candidates (candidate_id) VALUES ('temp-only')")
        persisted = [row[0] for row in writer.execute("SELECT candidate_id FROM rag_candidates").fetchall()]
        assert persisted == ["persistent"], persisted
        other_seen = [row[0] for row in readers[1].execute("SELECT candidate_id FROM rag_candidates").fetchall()]
        assert other_seen == ["persistent"], other_seen
        temp_seen = [row[0] for row in r0.execute("SELECT candidate_id FROM rag_candidates ORDER BY 1").fetchall()]
        assert "temp-only" in temp_seen and "c1" in temp_seen, temp_seen
        assert "persistent" not in temp_seen

        _assert_rejected(lambda: r0.connection, "raw connection attribute must be rejected")
        _assert_rejected(lambda: r0.raw, "raw attribute must be rejected")
        _assert_rejected(r0.unwrap, "unwrap must be rejected")
        _assert_rejected(lambda: r0.duplicate(), "duplicate must be rejected")

        pool.close()
        writer.close()
        assert persistent.is_file()


def check_reader_guard() -> None:
    assert reader_sql_allowed("SELECT 1")
    assert reader_sql_allowed("SELECT nextval('seq')") is False
    assert reader_sql_allowed("SELECT count(*) FROM docs") is False
    assert reader_sql_allowed("SELECT * FROM 'file.csv'") is False
    assert reader_sql_allowed("SELECT * FROM 'https://example.invalid/x.csv'") is False
    assert reader_sql_allowed("SELECT * FROM read_csv('x.csv')") is False
    assert reader_sql_allowed("EXPLAIN ANALYZE SELECT 1") is False
    assert reader_sql_allowed("CREATE TEMP TABLE rag_candidates (candidate_id VARCHAR)")
    assert reader_sql_allowed("CREATE OR REPLACE TEMP TABLE rag_candidates (candidate_id VARCHAR)")
    assert reader_sql_allowed("CREATE TABLE persistent (id INT)") is False
    assert reader_sql_allowed("CREATE TABLE TEMP (id INT)") is False
    assert reader_sql_allowed("CREATE TEMP VIEW v AS SELECT 1") is False
    assert reader_sql_allowed("ATTACH 'x.db'") is False
    assert reader_sql_allowed("DETACH other") is False
    assert reader_sql_allowed("INSTALL fts") is False
    assert reader_sql_allowed("LOAD fts") is False
    assert reader_sql_allowed("DROP TABLE docs") is False
    assert reader_sql_allowed(
        "MERGE INTO docs USING (SELECT 1 AS id) s ON docs.id = s.id WHEN MATCHED THEN DELETE"
    ) is False
    assert reader_sql_allowed("WITH x AS (SELECT 1) INSERT INTO docs SELECT * FROM x") is False
    assert reader_sql_allowed("SELECT 1; DROP TABLE docs") is False
    assert reader_sql_allowed("/* comment */ DROP TABLE docs") is False
    assert reader_sql_allowed("-- comment\nDROP TABLE docs") is False
    assert reader_sql_allowed("FOOBAR") is False
    assert reader_sql_allowed("NOT_A_STATEMENT") is False
    assert reader_sql_allowed("SET threads=1") is False
    assert reader_sql_allowed("USE main") is False
    assert reader_sql_allowed("BEGIN READ WRITE") is False
    assert reader_sql_allowed("PIVOT docs ON n USING count(*)") is False
    assert reader_sql_allowed("PIVOT docs ON n IN (1) USING count(*)") is False
    assert reader_sql_allowed("UNPIVOT docs ON n") is False
    assert reader_sql_allowed("SELECT * FROM (UNPIVOT docs ON n)") is False
    assert reader_sql_allowed("SELECT * FROM (PIVOT docs ON n IN (1) USING count(*))") is False
    assert reader_sql_allowed("DELETE FROM tgt USING vseq") is False
    assert reader_sql_allowed("WITH a AS (SELECT 1) DELETE FROM tgt USING vseq") is False
    assert reader_sql_allowed("SELECT system.main.ignored.range(1)") is False
    assert reader_sql_allowed('SELECT "memory"."adversarial"."range"(1)') is False
    assert reader_sql_allowed('SELECT "select"(1)') is False
    assert reader_sql_allowed('SELECT "filter"(1)') is False
    assert reader_sql_allowed("SELECT adversarial.range(1)") is False
    assert reader_sql_allowed("COPY docs TO 'x.csv'") is False
    assert reader_sql_allowed("EXPORT DATABASE 'x'") is False
    assert reader_sql_allowed("ALTER TABLE docs ADD COLUMN x INT") is False
    assert reader_sql_allowed("INSERT INTO \"docs\" VALUES (1)") is False
    import duckdb

    raw = duckdb.connect(":memory:")
    raw.execute("CREATE TABLE docs(id INT)")
    con = GuardedReaderConnection(raw)
    assert reader_sql_allowed("INSERT INTO docs VALUES (1)", conn=con) is False
    assert reader_sql_allowed('INSERT INTO "docs" VALUES (1)', conn=con) is False
    _assert_rejected(lambda: reader_execute(con, "ATTACH ':memory:' AS other"), "ATTACH must be guarded")
    _assert_rejected(lambda: reader_execute(con, "INSTALL httpfs"), "INSTALL must be guarded")
    _assert_rejected(lambda: reader_execute(con, "LOAD fts"), "LOAD must be guarded")
    _assert_rejected(lambda: reader_execute(con, "CREATE TABLE leaked (id INT)"), "persistent CREATE TABLE must be guarded")
    _assert_rejected(lambda: reader_execute(con, "INSERT INTO docs VALUES (9)"), "persistent INSERT must be guarded")
    _assert_rejected(lambda: con.execute("DROP TABLE docs"), "DROP must be guarded")
    _assert_rejected(
        lambda: con.execute(
            "MERGE INTO docs USING (SELECT 1 AS id) s ON docs.id = s.id WHEN MATCHED THEN DELETE"
        ),
        "MERGE must be guarded",
    )
    _assert_rejected(
        lambda: con.execute("WITH x AS (SELECT 9 AS id) INSERT INTO docs SELECT * FROM x"),
        "CTE INSERT must be guarded",
    )
    _assert_rejected(lambda: con.execute("SELECT 1; DROP TABLE docs"), "multi-statement must be guarded")
    _assert_rejected(lambda: con.execute("/* comment */ DROP TABLE docs"), "comment-wrapped DROP must be guarded")
    _assert_rejected(lambda: con.execute("FOOBAR"), "unknown SQL must be guarded")
    _assert_rejected(
        lambda: con.executemany("INSERT INTO docs VALUES (?)", [(9,)]), "executemany INSERT must be guarded"
    )
    cur = con.cursor()
    _assert_rejected(lambda: cur.execute("DROP TABLE docs"), "cursor DROP must be guarded")
    _assert_rejected(lambda: cur.execute("ATTACH ':memory:' AS other"), "cursor ATTACH must be guarded")
    con.begin()
    _assert_rejected(lambda: con.execute("UPDATE docs SET id = 0"), "transaction UPDATE must be guarded")
    con.rollback()
    reader_execute(con, "CREATE TEMP TABLE rag_candidates (candidate_id VARCHAR)")
    reader_execute(con, "INSERT INTO rag_candidates VALUES ('c1')")
    con.executemany("INSERT INTO rag_candidates VALUES (?)", [("c2",), ("c3",)])
    assert con.execute("SELECT count(*) FROM rag_candidates").fetchone()[0] == 3
    con.close()


def check_reader_pool_concurrency_and_cleanup(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "pool.rag.duckdb")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()

        def opener():
            return connect_reader(duckdb, db_path)

        pool = ReaderPool(opener, max_readers=READER_HARD_CAP)
        held = [pool.acquire() for _ in range(READER_HARD_CAP)]
        _assert_rejected(pool.acquire, "17th reader must be rejected while 16 are held")
        held[0].close()
        replacement = pool.acquire()
        assert replacement.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        replacement.close()
        for r in held[1:]:
            r.close()

        errors = []

        def worker():
            for _ in range(20):
                reader = None
                try:
                    reader = pool.acquire()
                    n = reader.execute("SELECT count(*) FROM docs").fetchone()[0]
                    if n != 1:
                        errors.append(f"saw {n}")
                except ReaderAdmissionError:
                    pass
                except Exception as exc:
                    errors.append(exc)
                finally:
                    if reader is not None:
                        reader.close()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert pool.in_flight == 0
        pool.close()

        def failing_opener():
            raise RuntimeError("init fail")

        fail_pool = ReaderPool(failing_opener, max_readers=4)
        try:
            fail_pool.acquire()
            raise AssertionError("failed opener must surface")
        except RuntimeError as exc:
            assert "init fail" in str(exc)
        assert fail_pool.in_flight == 0
        fail_pool._opener = opener
        recovered = fail_pool.acquire()
        assert recovered.execute("SELECT 1").fetchone()[0] == 1
        recovered.close()

        wrap_opened = []

        def wrap_opener():
            con = duckdb.connect(db_path)
            wrap_opened.append(con)
            return con

        wrap_pool = ReaderPool(wrap_opener, max_readers=4)

        def boom(_raw, on_close=None):
            raise RuntimeError("wrap fail")

        wrap_pool._guard = boom
        try:
            wrap_pool.acquire()
            raise AssertionError("failed wrap must surface")
        except RuntimeError as exc:
            assert "wrap fail" in str(exc)
        assert wrap_pool.in_flight == 0
        for con in wrap_opened:
            try:
                con.execute("SELECT 1")
                raise AssertionError("failed-wrap connection was not closed")
            except AssertionError:
                raise
            except Exception:
                pass
        wrap_pool.close()
        fail_pool.close()
        writer.close()


def check_reader_raw_handle_escapes(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "escape.rag.duckdb")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()

        reader = connect_reader(duckdb, db_path)
        _assert_guarded(reader, "connect_reader must return guarded wrapper")
        _assert_no_raw_exposed(reader, "connect_reader wrapper")
        _assert_fetch_bound_to_wrapper(reader, "connect_reader wrapper")
        assert reader.fetchone.__self__ is reader
        assert not _is_raw_conn(reader.fetchone.__self__)

        raw = duckdb.connect(":memory:")
        try:
            _assert_rejected(
                lambda: reader_execute(raw, "SELECT 1"),
                "reader_execute(raw) must reject",
            )
            _assert_rejected(
                lambda: reader_execute(raw, "DROP TABLE docs"),
                "reader_execute(raw) DROP must reject",
            )
        finally:
            raw.close()

        begun = reader.begin()
        _assert_guarded(begun, "begin() must return guarded wrapper")
        _assert_fetch_bound_to_wrapper(begun, "begin() wrapper")
        committed = reader.commit()
        _assert_guarded(committed, "commit() must return guarded wrapper")
        _assert_fetch_bound_to_wrapper(committed, "commit() wrapper")
        reader.begin()
        rolled = reader.rollback()
        _assert_guarded(rolled, "rollback() must return guarded wrapper")
        _assert_fetch_bound_to_wrapper(rolled, "rollback() wrapper")

        executed = reader.execute("SELECT 1")
        _assert_guarded(executed, "execute() must return guarded wrapper")
        _assert_fetch_bound_to_wrapper(executed, "execute() wrapper")
        assert executed.fetchall.__self__ is executed
        assert not _is_raw_conn(executed.fetchall.__self__)
        assert executed.fetchone()[0] == 1

        reader_execute(reader, "CREATE TEMP TABLE rag_candidates (candidate_id VARCHAR)")
        many = reader.executemany("INSERT INTO rag_candidates VALUES (?)", [("a",), ("b",)])
        _assert_guarded(many, "executemany() must return guarded wrapper")

        cur = reader.cursor()
        _assert_guarded(cur, "cursor() must return guarded wrapper")
        _assert_no_raw_exposed(cur, "cursor child")
        _assert_fetch_bound_to_wrapper(cur, "cursor child")
        _assert_rejected(lambda: cur.execute("DROP TABLE docs"), "cursor DROP must be guarded")
        _assert_rejected(lambda: cur.execute("ATTACH ':memory:' AS other"), "cursor ATTACH must be guarded")

        _assert_rejected(lambda: reader.connection, "raw connection attribute must be rejected")
        _assert_rejected(lambda: reader.raw, "raw attribute must be rejected")
        _assert_rejected(reader.unwrap, "unwrap must be rejected")
        _assert_rejected(lambda: reader.duplicate(), "duplicate must be rejected")
        _assert_no_raw_exposed(reader, "after method probes")

        _assert_rejected(lambda: reader.execute("DROP TABLE docs"), "DROP must stay guarded")
        remaining = [row[0] for row in writer.execute("SHOW TABLES").fetchall()]
        assert "docs" in remaining, remaining

        reader.close()
        with connect_reader(duckdb, db_path) as cm:
            _assert_guarded(cm, "context manager must yield guarded wrapper")
            _assert_no_raw_exposed(cm, "context manager wrapper")
            _assert_fetch_bound_to_wrapper(cm, "context manager wrapper")
            _assert_rejected(lambda: cm.execute("DROP TABLE docs"), "context-manager DROP must be guarded")
            assert cm.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        still = [row[0] for row in writer.execute("SHOW TABLES").fetchall()]
        assert "docs" in still, still
        writer.close()


def check_reader_select_side_effects(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "seq.rag.duckdb")
        csv_path = str(Path(td) / "side.csv")
        Path(csv_path).write_text("id\n1\n", encoding="utf-8")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.execute("CREATE SEQUENCE seq START 1")
        writer.execute("CREATE MACRO evil() AS nextval('seq')")
        writer.execute("CREATE MACRO range(x) AS nextval('seq')")
        writer.execute("CREATE SCHEMA adversarial")
        writer.execute("CREATE MACRO adversarial.range(x) AS nextval('seq')")
        writer.execute("CREATE MACRO read_wrap(p) AS TABLE SELECT * FROM read_csv(p)")
        writer.execute("CREATE MACRO range_next(x) AS TABLE SELECT nextval('seq') AS n")
        writer.execute('CREATE MACRO "select"(x) AS nextval(\'seq\')')
        writer.execute('CREATE MACRO "filter"(x) AS nextval(\'seq\')')
        writer.execute("CREATE VIEW vseq AS SELECT nextval('seq') AS n")
        writer.commit()

        reader = connect_reader(duckdb, db_path)
        missing_csv = str(Path(td) / "missing-p0.csv")
        reader_execute(reader, "CREATE TEMP TABLE tgt (id INTEGER)")
        reader_execute(reader, "INSERT INTO tgt VALUES (1)")
        for sql, label in (
            ("SELECT nextval('seq')", "SELECT nextval"),
            ("VALUES (nextval('seq'))", "VALUES nextval"),
            ("WITH x AS (SELECT nextval('seq') AS n) SELECT * FROM x", "WITH nextval"),
            ("EXPLAIN ANALYZE SELECT nextval('seq')", "EXPLAIN ANALYZE nextval"),
            ("EXPLAIN ANALYZE SELECT 1", "EXPLAIN ANALYZE"),
            ("SELECT setval('seq', 99)", "SELECT setval"),
            ("SELECT evil()", "registered/macro side-effect function"),
            ("SELECT range(1)", "allowlist-name macro collision"),
            ("SELECT main.range(1)", "schema-qualified macro collision"),
            ("SELECT adversarial.range(1)", "schema-qualified adversarial.range"),
            ("SELECT memory.adversarial.range(1)", "catalog-qualified adversarial.range"),
            ('SELECT "memory"."adversarial"."range"(1)', "quoted catalog-qualified adversarial.range"),
            ("SELECT system.main.ignored.range(1)", "extra-qualified function identity"),
            ("SELECT * FROM system.main.ignored.range(1)", "extra-qualified table function identity"),
            ("SELECT * FROM range_next(3)", "table macro wrapping nextval"),
            (f"SELECT * FROM read_wrap('{csv_path}')", "table macro wrapping read_csv"),
            (f"SELECT * FROM read_wrap('{missing_csv}')", "table macro wrapping missing csv"),
            ('SELECT "select"(1)', "quoted select callable"),
            ('SELECT "filter"(1)', "quoted filter callable"),
            ("SELECT filter(1)", "unquoted filter callable"),
            ("SELECT * FROM vseq", "persistent view"),
            ("EXPLAIN ANALYZE SELECT * FROM vseq", "EXPLAIN ANALYZE persistent view"),
            (f"SELECT * FROM read_csv('{csv_path}')", "read_csv table function"),
            (f"SELECT * FROM read_csv_auto('{csv_path}')", "read_csv_auto table function"),
            (f"SELECT * FROM read_parquet('{csv_path}')", "read_parquet table function"),
            (f"SELECT * FROM '{csv_path}'", "string file relation"),
            (f"FROM '{csv_path}'", "FROM string file relation"),
            ("SELECT * FROM 'https://example.invalid/p0.csv'", "URL relation"),
            (f"EXPLAIN ANALYZE SELECT * FROM '{csv_path}'", "EXPLAIN ANALYZE file relation"),
            (f"SELECT * FROM '{missing_csv}'", "missing string file relation"),
            ("PIVOT vseq ON n USING count(*)", "PIVOT over side-effect view"),
            ("PIVOT vseq ON n IN (1) USING count(*)", "single-statement PIVOT over side-effect view"),
            ("SELECT * FROM (PIVOT vseq ON n IN (1) USING count(*))", "nested PIVOT over side-effect view"),
            ("UNPIVOT vseq ON n", "UNPIVOT over side-effect view"),
            ("SELECT * FROM (UNPIVOT vseq ON n)", "nested UNPIVOT over side-effect view"),
            ("DELETE FROM tgt USING vseq WHERE tgt.id = vseq.n", "DELETE TEMP USING side-effect view"),
            ("DELETE FROM tgt USING vseq AS v WHERE tgt.id = v.n", "DELETE TEMP USING aliased side-effect view"),
            ("WITH a AS (SELECT 1 AS n) DELETE FROM tgt USING vseq", "CTE then DELETE USING side-effect view"),
            (
                "WITH a AS (SELECT nextval('seq') AS n) "
                "SELECT * FROM (WITH a AS (SELECT 1 AS n) SELECT * FROM a) s",
                "inner CTE name shadowing outer",
            ),
            (
                "WITH a AS (SELECT * FROM b), b AS (SELECT nextval('seq') AS n) SELECT * FROM a",
                "forward-ref CTE",
            ),
            (
                "WITH RECURSIVE t(n) AS (SELECT nextval('seq') UNION ALL SELECT n FROM t WHERE n < 0) "
                "SELECT * FROM t",
                "recursive CTE",
            ),
            ("SELECT * FROM docs, vseq", "comma FROM side-effect view"),
        ):
            _assert_rejected(lambda sql=sql: reader.execute(sql), f"{label} must be rejected")

        assert reader_sql_allowed(
            "WITH a AS (SELECT 1 AS n), b AS (SELECT * FROM a) SELECT * FROM b", conn=reader
        )
        assert reader.execute(
            "WITH a AS (SELECT 1 AS n), b AS (SELECT * FROM a) SELECT * FROM b"
        ).fetchall() == [(1,)]
        assert reader_sql_allowed("SELECT count(*) FROM docs", conn=reader)
        assert reader_sql_allowed(
            "SELECT count(*) FILTER (WHERE id > 0) FROM docs", conn=reader
        )
        assert reader_sql_allowed("SELECT * FROM vseq", conn=reader) is False
        assert reader_sql_allowed("SELECT evil()", conn=reader) is False
        assert reader_sql_allowed("SELECT range(1)", conn=reader) is False
        assert reader_sql_allowed("SELECT adversarial.range(1)", conn=reader) is False
        assert reader_sql_allowed('SELECT "memory"."adversarial"."range"(1)', conn=reader) is False
        assert reader_sql_allowed("SELECT system.main.ignored.range(1)", conn=reader) is False
        assert reader_sql_allowed('SELECT "select"(1)', conn=reader) is False
        assert reader_sql_allowed("PIVOT vseq ON n IN (1) USING count(*)", conn=reader) is False
        assert reader_sql_allowed("DELETE FROM tgt USING vseq", conn=reader) is False
        assert reader_sql_allowed("WITH a AS (SELECT 1) DELETE FROM tgt USING vseq", conn=reader) is False
        advanced = writer.execute("SELECT nextval('seq')").fetchone()[0]
        assert advanced == 1, f"sequence advanced under reader: nextval={advanced}"
        csv_text = Path(csv_path).read_text(encoding="utf-8")
        assert csv_text == "id\n1\n", csv_text
        assert not Path(missing_csv).exists()
        reader.close()
        writer.close()

    box: list[int] = []

    def evil() -> int:
        box.append(1)
        return 1

    raw = duckdb.connect(":memory:")
    try:
        raw.create_function("evil_py", evil, return_type="INTEGER")
    except Exception:
        raw.close()
    else:
        guarded = GuardedReaderConnection(raw)
        _assert_rejected(
            lambda: guarded.execute("SELECT evil_py()"),
            "registered Python side-effect function must be rejected",
        )
        assert box == [], f"registered Python function ran: {box}"
        guarded.close()


def check_reader_cursor_pool_ownership(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "cursor-cap.rag.duckdb")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()

        def opener():
            return connect_reader(duckdb, db_path)

        pool = ReaderPool(opener, max_readers=READER_HARD_CAP)
        held = [pool.acquire() for _ in range(READER_HARD_CAP)]
        cursors = []
        for i in range(100):
            parent = held[i % len(held)]
            cur = parent.cursor()
            assert cur is not parent, "cursor() must return a tracked child, not the parent"
            cursors.append(cur)
        assert len(cursors) == 100
        for cur in cursors:
            _assert_guarded(cur, "cursor() must stay guarded")
            _assert_no_raw_exposed(cur, "cursor child")
            assert cur.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        _assert_rejected(pool.acquire, "100 cursor attempts must not bypass cap")
        assert pool.in_flight == READER_HARD_CAP

        child = held[0].cursor()
        child.close()
        assert pool.in_flight == READER_HARD_CAP, "closing a cursor child must not release the parent slot"
        assert held[0].execute("SELECT 1").fetchone()[0] == 1
        _assert_rejected(lambda: child.execute("SELECT 1"), "closed cursor child must be invalid")

        grandchild = held[1].cursor().cursor()
        _assert_guarded(grandchild, "nested cursor() must stay guarded")
        assert grandchild is not held[1]
        held[1].close()
        assert pool.in_flight == READER_HARD_CAP - 1
        _assert_rejected(lambda: grandchild.execute("SELECT 1"), "parent close must invalidate nested cursors")

        close_errors = []

        def close_twice(reader):
            try:
                reader.close()
                reader.close()
            except Exception as exc:
                close_errors.append(exc)

        threads = [threading.Thread(target=close_twice, args=(held[i],)) for i in range(2, 6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert close_errors == [], close_errors
        assert pool.in_flight == READER_HARD_CAP - 1 - 4

        same = held[0]
        barrier = threading.Barrier(8)
        concurrent_errors = []

        def concurrent_close():
            barrier.wait(timeout=5)
            try:
                same.close()
            except Exception as exc:
                concurrent_errors.append(exc)

        closers = [threading.Thread(target=concurrent_close) for _ in range(8)]
        for t in closers:
            t.start()
        for t in closers:
            t.join()
        assert concurrent_errors == [], concurrent_errors
        assert pool.in_flight == READER_HARD_CAP - 1 - 4 - 1
        _assert_rejected(lambda: same.execute("SELECT 1"), "concurrent close must leave parent closed")

        pool.close()
        assert pool.in_flight == 0
        for cur in cursors:
            _assert_rejected(lambda cur=cur: cur.execute("SELECT 1"), "pool close must invalidate cursors")
        for parent in held:
            _assert_rejected(lambda parent=parent: parent.execute("SELECT 1"), "pool close must invalidate parents")

        started = threading.Event()
        release_opener = threading.Event()

        def slow_opener():
            started.set()
            if not release_opener.wait(timeout=5):
                raise TimeoutError("opener gate")
            return connect_reader(duckdb, db_path)

        race_pool = ReaderPool(slow_opener, max_readers=2)
        acquired = []
        errors = []

        def racing_acquire():
            try:
                acquired.append(race_pool.acquire())
            except Exception as exc:
                errors.append(exc)

        racer = threading.Thread(target=racing_acquire)
        racer.start()
        assert started.wait(timeout=5)
        race_pool.close()
        release_opener.set()
        racer.join(timeout=5)
        assert not racer.is_alive()
        assert acquired == [], acquired
        assert errors, "acquire must fail after concurrent pool close"
        assert all(isinstance(exc, ReaderAdmissionError) for exc in errors), errors
        assert race_pool.in_flight == 0
        _assert_rejected(race_pool.acquire, "closed pool must reject later acquire")
        race_pool.close()
        writer.close()


def check_reader_open_readonly_fallback(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        missing = Path(td) / "missing-ro.rag.duckdb"
        raised = None
        try:
            connect_reader(duckdb, str(missing))
        except Exception as exc:
            raised = exc
        assert raised is not None, "missing path must raise"
        assert not missing.exists(), f"reader created missing database: {missing}"
        wal = Path(str(missing) + ".wal")
        assert not wal.exists(), f"reader created wal for missing database: {wal}"

        writable_missing = Path(td) / "created-by-read-only-false.rag.duckdb"
        writable_raised = None
        try:
            connect_reader(duckdb, str(writable_missing), read_only=False)
        except ReaderGuardError as exc:
            writable_raised = exc
        except Exception as exc:
            raise AssertionError(f"read_only=False must fail closed, not {type(exc).__name__}: {exc}") from exc
        assert writable_raised is not None, "read_only=False must raise"
        assert not writable_missing.exists(), f"read_only=False created database: {writable_missing}"
        assert not Path(str(writable_missing) + ".wal").exists()

        mode_missing = Path(td) / "created-by-access-mode.rag.duckdb"
        mode_raised = None
        try:
            connect_reader(duckdb, str(mode_missing), config={"access_mode": "read_write"})
        except ReaderGuardError as exc:
            mode_raised = exc
        except Exception as exc:
            raise AssertionError(f"writable access_mode must fail closed, not {type(exc).__name__}: {exc}") from exc
        assert mode_raised is not None, "writable access_mode must raise"
        assert not mode_missing.exists(), f"access_mode created database: {mode_missing}"

        db_path = Path(td) / "exists-ro.rag.duckdb"
        writer = duckdb.connect(str(db_path))
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()

        class BoomModule:
            ConnectionException = duckdb.ConnectionException

            def connect(self, database, read_only=False, **kwargs):
                if read_only:
                    raise RuntimeError("unrelated boom")
                raise AssertionError("writable fallback must not run for unrelated errors")

        try:
            _open_reader_raw(BoomModule(), str(db_path))
            raise AssertionError("unrelated read_only error must re-raise")
        except RuntimeError as exc:
            assert "unrelated boom" in str(exc)

        class OtherConnExcModule:
            ConnectionException = duckdb.ConnectionException

            def connect(self, database, read_only=False, **kwargs):
                if read_only:
                    raise duckdb.ConnectionException("Connection Error: some other connection failure")
                raise AssertionError("writable fallback must not run for unrelated ConnectionException")

        try:
            _open_reader_raw(OtherConnExcModule(), str(db_path))
            raise AssertionError("unrelated ConnectionException must re-raise")
        except duckdb.ConnectionException as exc:
            assert "some other connection failure" in str(exc)

        reader = connect_reader(duckdb, str(db_path))
        assert reader.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        reader.close()
        writer.close()

        before = {p.name for p in Path(td).iterdir()}
        mem = connect_reader(duckdb, ":memory:")
        assert mem.execute("SELECT 1").fetchone()[0] == 1
        mem.close()
        after = {p.name for p in Path(td).iterdir()}
        assert after == before, f":memory: reader created files: {after - before}"


def _duckdb_shared_object(duckdb) -> Path:
    imported = Path(duckdb.__file__).resolve()
    parent = imported.parent.parent
    named = parent / "_duckdb.cpython-312-darwin.so"
    if named.is_file():
        return named
    matches = sorted(parent.glob("_duckdb*.so"))
    assert matches, f"no _duckdb shared object near {imported}"
    return matches[0]


def check_whole_archive_symbols(duckdb) -> None:
    so = _duckdb_shared_object(duckdb)
    assert "dist-special-g1" not in so.as_posix(), so
    result = subprocess.run(["nm", "-gU", str(so)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    defined = result.stdout
    assert "RagRegistry" in defined, "flock RagRegistry missing from WHOLE_ARCHIVE image"
    assert "FtsExtension" in defined, "fts FtsExtension missing from WHOLE_ARCHIVE image"
    assert "RegisterLinkedExtensions" in defined, "generated loader missing from WHOLE_ARCHIVE image"
    assert "tachiom" not in defined.lower(), "tachiom symbol leaked into Phase 1 image"


def check_non_owner_live_open(duckdb) -> None:
    child = (
        "import duckdb, sys\n"
        "path, mode = sys.argv[1], sys.argv[2]\n"
        "kwargs = {'read_only': True} if mode == 'ro' else {}\n"
        "try:\n"
        "    duckdb.connect(path, **kwargs)\n"
        "except Exception as e:\n"
        "    msg = str(e).lower()\n"
        "    if 'lock' in msg or 'conflicting' in msg:\n"
        "        print('LOCKED')\n"
        "        sys.exit(0)\n"
        "    print('OTHER', type(e).__name__, e)\n"
        "    sys.exit(3)\n"
        "print('OPENED')\n"
        "sys.exit(2)\n"
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = str(root / "live.rag.duckdb")
        child_home = root / "child-home"
        child_home.mkdir()
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()
        env = os.environ.copy()
        env["HOME"] = str(child_home)
        for mode in ("rw", "ro"):
            ran = subprocess.run(
                [sys.executable, "-c", child, db_path, mode],
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
            )
            assert ran.returncode == 0, (mode, ran.returncode, ran.stdout, ran.stderr)
            assert "LOCKED" in ran.stdout, (mode, ran.stdout, ran.stderr)
            assert "OPENED" not in ran.stdout
        writer.close()


def _files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _lock_probe_script() -> str:
    return (
        "import duckdb, sys\n"
        "path = sys.argv[1]\n"
        "try:\n"
        "    con = duckdb.connect(path)\n"
        "except Exception as e:\n"
        "    msg = str(e).lower()\n"
        "    if 'lock' in msg or 'conflicting' in msg:\n"
        "        print('LOCKED')\n"
        "        sys.exit(0)\n"
        "    print('OTHER', type(e).__name__, e)\n"
        "    sys.exit(3)\n"
        "print('OPENED')\n"
        "con.close()\n"
        "sys.exit(2)\n"
    )


def _run_lock_probe(db_path: str, home: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-c", _lock_probe_script(), db_path],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )


class _RawExecuteProxy:
    def __init__(self, inner, hook):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_hook", hook)

    def execute(self, *args, **kwargs):
        sql = args[0] if args else kwargs.get("query")
        self._hook(sql)
        result = self._inner.execute(*args, **kwargs)
        if result is self._inner:
            return self
        return result

    def __getattr__(self, name):
        return getattr(self._inner, name)


def check_reader_nested_relation_walker(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "nested.rag.duckdb")
        csv_path = str(Path(td) / "nested.csv")
        Path(csv_path).write_text("id\n1\n", encoding="utf-8")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.execute("CREATE SEQUENCE seq START 1")
        writer.execute("CREATE VIEW vseq AS SELECT nextval('seq') AS n")
        writer.commit()
        reader = connect_reader(duckdb, db_path)
        for sql, label in (
            (
                "SELECT * FROM (SELECT * FROM docs) x JOIN vseq ON TRUE",
                "JOIN continuation after subquery",
            ),
            (
                "SELECT * FROM (SELECT 1) a, vseq",
                "comma FROM after subquery",
            ),
            (
                "SELECT * FROM docs JOIN docs d2 ON d2.id IN (SELECT n FROM vseq)",
                "JOIN ON subquery",
            ),
            (
                "SELECT * FROM docs JOIN docs d2 ON EXISTS (TABLE vseq)",
                "JOIN ON nested TABLE",
            ),
            (
                "SELECT * FROM docs JOIN docs d2 ON d2.id IN (SELECT * FROM (DESCRIBE vseq))",
                "JOIN ON nested DESCRIBE",
            ),
            (
                "SELECT * FROM (TABLE vseq)",
                "subquery nested TABLE",
            ),
            (
                "SELECT * FROM (DESCRIBE vseq)",
                "subquery nested DESCRIBE",
            ),
            (
                "SELECT * FROM (SUMMARIZE vseq)",
                "subquery nested SUMMARIZE",
            ),
            (
                "TABLE (SELECT * FROM vseq)",
                "TABLE wrapping subquery",
            ),
            (
                "DESCRIBE (SELECT * FROM vseq)",
                "DESCRIBE wrapping subquery",
            ),
            (
                "SUMMARIZE (SELECT * FROM vseq)",
                "SUMMARIZE wrapping subquery",
            ),
            (
                "SELECT * FROM (SELECT * FROM vseq) x JOIN docs ON TRUE",
                "persistent view inside subquery before JOIN",
            ),
            (
                f"SELECT * FROM (SELECT * FROM '{csv_path}')",
                "string file relation inside subquery",
            ),
            (
                f"SELECT * FROM (SELECT 1) x JOIN '{csv_path}' ON TRUE",
                "string file JOIN continuation after subquery",
            ),
            (
                "SELECT * FROM (SELECT * FROM (TABLE vseq))",
                "doubly nested TABLE",
            ),
        ):
            assert reader_sql_allowed(sql, conn=reader) is False, label
            _assert_rejected(lambda sql=sql: reader.execute(sql), f"{label} must be rejected")
        assert reader_sql_allowed(
            "SELECT * FROM (SELECT * FROM docs) x JOIN docs d ON x.id = d.id",
            conn=reader,
        )
        assert reader.execute(
            "SELECT * FROM (SELECT * FROM docs) x JOIN docs d ON x.id = d.id"
        ).fetchall() == [(1, 1)]
        advanced = writer.execute("SELECT nextval('seq')").fetchone()[0]
        assert advanced == 1, f"sequence advanced under nested reader: nextval={advanced}"
        reader.close()
        writer.close()


def check_reader_active_operation_lifetime(duckdb) -> None:
    raw = duckdb.connect(":memory:")
    reader = GuardedReaderConnection(raw)
    rec = reader_guard_mod._LEASES[reader]
    inner = rec.resource.raw
    proceed = threading.Event()
    entered = threading.Event()
    close_finished = threading.Event()
    errors = []

    executed = []

    def hook(sql):
        if isinstance(sql, str) and sql.strip() == "SELECT 99":
            entered.set()
            if not proceed.wait(timeout=5):
                raise TimeoutError("in-flight execute was not released")
            executed.append(True)

    rec.resource.raw = _RawExecuteProxy(inner, hook)

    def worker():
        try:
            result = reader.execute("SELECT 99")
            if not isinstance(result, GuardedReaderConnection):
                errors.append(f"got {type(result)!r}")
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    assert entered.wait(timeout=5), "execute did not enter in-flight gate"
    assert rec.resource.in_flight >= 1

    def closer():
        try:
            reader.close()
        except Exception as exc:
            errors.append(exc)
        finally:
            close_finished.set()

    closer_t = threading.Thread(target=closer)
    closer_t.start()
    time.sleep(0.05)
    assert not close_finished.is_set(), "cross-thread close returned while execute was in flight"
    proceed.set()
    t.join(timeout=5)
    closer_t.join(timeout=5)
    assert not t.is_alive()
    assert not closer_t.is_alive()
    assert close_finished.is_set()
    assert errors == [], errors
    assert executed == [True]
    _assert_rejected(lambda: reader.execute("SELECT 1"), "new execute after drained close must reject")

    raw2 = duckdb.connect(":memory:")
    reader2 = GuardedReaderConnection(raw2)
    rec2 = reader_guard_mod._LEASES[reader2]
    inner2 = rec2.resource.raw
    saw_close = []
    ran_inner = []

    def same_thread_hook(sql):
        if isinstance(sql, str) and sql.strip() == "SELECT 2":
            reader2.close()
            saw_close.append(True)
            ran_inner.append(True)

    rec2.resource.raw = _RawExecuteProxy(inner2, same_thread_hook)
    started = time.monotonic()
    result = reader2.execute("SELECT 2")
    elapsed = time.monotonic() - started
    _assert_guarded(result, "same-thread close during execute still returns wrapper")
    assert saw_close == [True]
    assert ran_inner == [True]
    assert elapsed < 2, "same-thread close during execute deadlocked"
    _assert_rejected(lambda: reader2.execute("SELECT 3"), "new execute after same-thread close must reject")
    _assert_rejected(lambda: result.fetchone(), "fetch after drained close must reject")


def check_reader_abandoned_wrapper_cleanup(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = str(root / "abandon.rag.duckdb")
        child_home = root / "child-home"
        child_home.mkdir()
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()
        writer.close()

        reader = connect_reader(duckdb, db_path)
        cur = reader.cursor()
        nested = cur.cursor()
        parent_ref = weakref.ref(reader)
        child_ref = weakref.ref(cur)
        nested_ref = weakref.ref(nested)
        assert nested.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        del nested
        del cur
        del reader
        gc.collect()
        assert parent_ref() is None
        assert child_ref() is None
        assert nested_ref() is None
        ran = _run_lock_probe(db_path, child_home)
        assert "LOCKED" not in ran.stdout, (ran.stdout, ran.stderr)
        assert "OPENED" in ran.stdout, (ran.returncode, ran.stdout, ran.stderr)

        reader = connect_reader(duckdb, db_path)
        cur = reader.cursor()
        parent_ref = weakref.ref(reader)
        del reader
        gc.collect()
        assert parent_ref() is None
        assert cur.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        ran = _run_lock_probe(db_path, child_home)
        assert "LOCKED" in ran.stdout, "live child must keep the file lock"
        assert "OPENED" not in ran.stdout
        del cur
        gc.collect()
        ran = _run_lock_probe(db_path, child_home)
        assert "OPENED" in ran.stdout, (ran.returncode, ran.stdout, ran.stderr)
        assert "LOCKED" not in ran.stdout


def check_reader_pool_ownership_accounting(duckdb) -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "own.rag.duckdb")
        writer = duckdb.connect(db_path)
        writer.execute("CREATE TABLE docs(id INTEGER)")
        writer.execute("INSERT INTO docs VALUES (1)")
        writer.commit()

        def opener():
            return connect_reader(duckdb, db_path)

        parent = connect_reader(duckdb, db_path)
        child = parent.cursor()

        def child_opener():
            return child

        child_pool = ReaderPool(child_opener, max_readers=1)
        _assert_rejected(child_pool.acquire, "child wrapper must not consume a pool slot")
        assert child_pool.in_flight == 0
        assert parent.execute("SELECT 1").fetchone()[0] == 1
        assert child.execute("SELECT 1").fetchone()[0] == 1
        child_pool._opener = opener
        recovered = child_pool.acquire()
        assert recovered.execute("SELECT count(*) FROM docs").fetchone()[0] == 1
        recovered.close()
        assert child_pool.in_flight == 0
        child_pool.close()

        owned_pool = ReaderPool(opener, max_readers=2)
        owned = owned_pool.acquire()
        assert owned_pool.in_flight == 1

        def foreign_opener():
            return owned

        foreign_pool = ReaderPool(foreign_opener, max_readers=1)
        _assert_rejected(foreign_pool.acquire, "foreign-owned wrapper must not consume a slot")
        assert foreign_pool.in_flight == 0
        assert owned.execute("SELECT 1").fetchone()[0] == 1
        assert owned_pool.in_flight == 1
        _assert_rejected(
            lambda: foreign_pool.release(owned),
            "release must not close a foreign connection",
        )
        assert owned.execute("SELECT 1").fetchone()[0] == 1
        assert owned_pool.in_flight == 1

        _assert_rejected(lambda: owned_pool.release(None), "release(None) must raise")
        _assert_rejected(lambda: owned_pool.release(child), "release(child) must raise")
        outsider = connect_reader(duckdb, db_path)
        _assert_rejected(lambda: owned_pool.release(outsider), "release(foreign) must raise")
        assert outsider.execute("SELECT 1").fetchone()[0] == 1
        outsider.close()

        owned.close()
        owned.close()
        assert owned_pool.in_flight == 0
        _assert_rejected(lambda: owned_pool.release(owned), "release of closed reader must raise")
        assert owned_pool.in_flight == 0

        slot = owned_pool.acquire()
        assert owned_pool.in_flight == 1
        owned_pool.release(slot)
        assert owned_pool.in_flight == 0
        owned_pool.close()
        parent.close()
        writer.close()


def check_reader_memory_alias_exact(duckdb) -> None:
    assert _is_memory_database(None)
    assert _is_memory_database("")
    assert _is_memory_database(":memory:")
    assert _is_memory_database(":memory:foo") is False
    assert _is_memory_database(" :memory: ") is False
    assert _is_memory_database(":memory:/path") is False
    assert _is_memory_database(":MEMORY:") is False
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        old = os.getcwd()
        os.chdir(td)
        try:
            before = _files_under(root)
            mem = connect_reader(duckdb, ":memory:")
            assert mem.execute("SELECT 1").fetchone()[0] == 1
            mem.close()
            empty = connect_reader(duckdb, "")
            assert empty.execute("SELECT 1").fetchone()[0] == 1
            empty.close()
            for name in (
                ":memory:foo",
                " :memory: ",
                ":memory:/path",
                ":MEMORY:",
                ":memory:bar.duckdb",
                ":memory:\t",
            ):
                raised = None
                try:
                    connect_reader(duckdb, name)
                except ReaderGuardError as exc:
                    raised = exc
                except Exception as exc:
                    raise AssertionError(
                        f"lookalike {name!r} must fail closed before connect, not {type(exc).__name__}: {exc}"
                    ) from exc
                assert raised is not None, f"lookalike {name!r} must raise"
                after = _files_under(root)
                assert after == before, f"{name!r} created files: {after - before}"
                assert not list(root.glob("*.duckdb"))
                assert not list(root.glob("*.wal"))
                assert not list(root.glob("*.duckdb.wal"))
            after = _files_under(root)
            assert after == before, f"canonical :memory: created files: {after - before}"
        finally:
            os.chdir(old)


def check() -> None:
    check_artifacts()
    duckdb = _import_v7()
    check_health(duckdb)
    check_exact_nearest(duckdb)
    check_whole_archive_symbols(duckdb)
    check_writer_readers_and_temp(duckdb)
    check_reader_guard()
    check_reader_pool_concurrency_and_cleanup(duckdb)
    check_reader_raw_handle_escapes(duckdb)
    check_reader_select_side_effects(duckdb)
    check_non_owner_live_open(duckdb)
    check_reader_cursor_pool_ownership(duckdb)
    check_reader_open_readonly_fallback(duckdb)
    check_reader_nested_relation_walker(duckdb)
    check_reader_active_operation_lifetime(duckdb)
    check_reader_abandoned_wrapper_cleanup(duckdb)
    check_reader_pool_ownership_accounting(duckdb)
    check_reader_memory_alias_exact(duckdb)


def _v7_or_skip():
    try:
        import duckdb
    except ImportError:
        duckdb = None
    imported = None if duckdb is None else Path(duckdb.__file__).resolve().as_posix()
    if duckdb is None or (imported is not None and "dist-special-g1" in imported):
        try:
            import pytest
        except ImportError:
            return None
        pytest.skip("v7 duckdb is not importable")
    return duckdb


def test_reader_guard_static_and_temp_dml() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_guard()


def test_reader_function_identity_macros_and_relations() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_select_side_effects(duckdb)


def test_reader_cursor_pool_cap() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_cursor_pool_ownership(duckdb)


def test_reader_readonly_fallback_exact() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_open_readonly_fallback(duckdb)


def test_reader_nested_relation_walker() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_nested_relation_walker(duckdb)


def test_reader_active_operation_lifetime() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_active_operation_lifetime(duckdb)


def test_reader_abandoned_wrapper_cleanup() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_abandoned_wrapper_cleanup(duckdb)


def test_reader_pool_ownership_accounting() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_pool_ownership_accounting(duckdb)


def test_reader_memory_alias_exact() -> None:
    duckdb = _v7_or_skip()
    if duckdb is None:
        return
    check_reader_memory_alias_exact(duckdb)


if __name__ == "__main__":
    home = Path(os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="v7-phase1-home-")))
    (home / ".duckdb").mkdir(parents=True, exist_ok=True)
    check()
    print("phase1 runtime: all checks passed")
