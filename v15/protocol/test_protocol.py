"""Stage 4 gate: splitter, classifier, and prompt renderer.

Run: uv run python v15/protocol/test_protocol.py  (exit 0 = pass)

Does not call v15_settle_llm and does not assert attempt or iteration state.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.protocol.render_prompt import (
    HISTORY_TEXT,
    MARKER,
    REPL_TEXT,
    RESPONSE_FORMAT,
    RESPONSE_FORMAT_NO_DELEGATION,
    TAIL_DELEGATION,
    iter_message_id,
    render_base,
    render_inputs,
    render_system,
    seed_inputs_id,
    seed_system_id,
    truncate_base,
    truncate_text,
)
from v15.protocol.setup_db import DB, main as setup_db
from v15.protocol.split_sql import (
    SplitFailure,
    classify_statement,
    split_sql,
    sql_without_timeout_pragma,
    timeout_pragma_ms,
)

UTILITY = (
    "CALL",
    "EXECUTE",
    "COPY",
    "DO",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "START",
    "END",
    "ABORT",
    "RELEASE",
    "SET",
    "RESET",
    "LOCK",
    "PREPARE",
    "DEALLOCATE",
    "LISTEN",
    "NOTIFY",
    "UNLISTEN",
    "LOAD",
    "DISCARD",
    "CHECKPOINT",
    "EXPLAIN",
    "TRUNCATE",
)
DDL = (
    "CREATE FUNCTION f() RETURNS void LANGUAGE sql AS 'SELECT 1'",
    "CREATE PROCEDURE p() LANGUAGE sql AS 'SELECT 1'",
    "CREATE ROUTINE r() RETURNS void LANGUAGE sql AS 'SELECT 1'",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE ROLE nobody",
    "CREATE DATABASE other",
    "CREATE EVENT TRIGGER t ON ddl_command_end EXECUTE FUNCTION f()",
    "GRANT SELECT ON t TO u",
    "REVOKE SELECT ON t FROM u",
    "COMMENT ON TABLE t IS 'x'",
    "SECURITY LABEL ON TABLE t IS 'x'",
    "VACUUM t",
    "REINDEX TABLE t",
    "CLUSTER t USING idx",
    "ALTER TABLE t ADD COLUMN x int",
    "CREATE SCHEMA s",
    "CREATE SEQUENCE s",
    "CREATE TYPE mood AS ENUM ('ok')",
    "DROP SCHEMA s",
    "CREATE TEMP TABLE t (id int)",
    "CREATE OR REPLACE VIEW v AS SELECT 1",
    "ALTER VIEW v RENAME TO w",
)
PLAIN = (
    "SELECT 1",
    "WITH RECURSIVE t AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM t WHERE n < 3) SELECT * FROM t",
    "TABLE t",
    "VALUES (1)",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET n = 1",
    "DELETE FROM t",
    "MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE",
    "SELECT jaz.var('x')",
    "SELECT jaz.tool('lookup', '{}'::jsonb)",
    "CREATE TABLE t (id int)",
    "CREATE TABLE IF NOT EXISTS t (id int)",
    "CREATE TABLE t AS SELECT 1",
    "SELECT 1 INTO new_t",
    "CREATE INDEX idx ON t (id)",
    "CREATE UNIQUE INDEX idx ON t (id)",
    "CREATE VIEW v AS SELECT 1",
    "DROP TABLE t",
    "DROP TABLE IF EXISTS t",
    "DROP INDEX idx",
    "DROP VIEW v",
    "CREATE /*c*/ TABLE t (id int)",
)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail != "" else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def expect_split(source: str, parts: list[str], label: str) -> None:
    got = split_sql(source)
    check(label, got == parts, got)


def expect_fail(source: str, code: str, sql: str, label: str) -> None:
    got = split_sql(source)
    check(label, isinstance(got, SplitFailure), type(got).__name__)
    if not isinstance(got, SplitFailure):
        return
    check(
        label + " fields",
        got.reject_code == code
        and got.sql == sql
        and got.kind == "plain"
        and got.bind_name is None
        and got.arg_sql is None
        and not isinstance(got, list),
        got,
    )


def expect_class(sql: str, kind, bind_name, arg_sql, reject, label: str, tool_name=None) -> None:
    got = classify_statement(sql)
    check(label, got == (kind, bind_name, arg_sql, reject, tool_name), got)


def _fence(doc: str, first_line: str) -> str:
    idx = doc.index(first_line)
    start = doc.rfind("```", 0, idx)
    nl = doc.index("\n", start)
    end = doc.index("```", nl)
    return doc[nl + 1 : end].removesuffix("\n")


def test_split() -> None:
    expect_split("SELECT 1;;;  SELECT 2;", ["SELECT 1", "SELECT 2"], "empty statements")
    expect_split("  \n  SELECT 1  \n  ", ["SELECT 1"], "trim ends")
    expect_split("SELECT 1; SELECT 2", ["SELECT 1", "SELECT 2"], "no final semicolon")
    expect_split(";;;", [], "only semicolons")
    expect_split("   \n\t  ", [], "only whitespace")
    expect_split("/* only */; SELECT 1", ["SELECT 1"], "comment-only dropped")
    expect_split(
        "SELECT 1 /* outer /* inner ; */ still ; */ ; SELECT 2",
        ["SELECT 1 /* outer /* inner ; */ still ; */", "SELECT 2"],
        "nested block comment",
    )
    expect_split("SELECT 'a;b'; SELECT 2", ["SELECT 'a;b'", "SELECT 2"], "string semicolon")
    expect_split(
        "SELECT E'a;b'; SELECT 2",
        ["SELECT E'a;b'", "SELECT 2"],
        "E-string semicolon",
    )
    expect_split(
        r"SELECT E'a;b\'c'; SELECT 2",
        [r"SELECT E'a;b\'c'", "SELECT 2"],
        "E-string escaped quote",
    )
    expect_split(
        "SELECT E'it''s;ok'; SELECT 2",
        ["SELECT E'it''s;ok'", "SELECT 2"],
        "E-string doubled quote",
    )
    expect_split(
        "SELECT U&'a;b'; SELECT u&'c;d'",
        ["SELECT U&'a;b'", "SELECT u&'c;d'"],
        "U& semicolon",
    )
    expect_split(
        'SELECT "a;b"; SELECT 1',
        ['SELECT "a;b"', "SELECT 1"],
        "quoted ident semicolon",
    )
    expect_split(
        'SELECT """a;b"""; SELECT 1',
        ['SELECT """a;b"""', "SELECT 1"],
        "quoted ident escaped quote",
    )
    expect_split(
        "SELECT 1; -- semi ;\nSELECT 2",
        ["SELECT 1", "-- semi ;\nSELECT 2"],
        "line comment semicolon",
    )
    expect_split(
        "SELECT $a$ semi; $b$ still $a$; SELECT 2",
        ["SELECT $a$ semi; $b$ still $a$", "SELECT 2"],
        "dollar different tag",
    )
    expect_split("SELECT $$;$$; SELECT 2", ["SELECT $$;$$", "SELECT 2"], "empty dollar tag")
    expect_split(
        "SELECT $a1$;$a1$; SELECT 2",
        ["SELECT $a1$;$a1$", "SELECT 2"],
        "dollar tag digit",
    )
    expect_split(
        "SELECT $α$;$α$; SELECT 2",
        ["SELECT $α$;$α$", "SELECT 2"],
        "dollar tag unicode",
    )
    expect_split("SELECT $1$; SELECT 2", ["SELECT $1$", "SELECT 2"], "parameter is not dollar")
    expect_split(
        "DO $$ BEGIN PERFORM 1; END $$;",
        ["DO $$ BEGIN PERFORM 1; END $$"],
        "DO dollar is one statement",
    )
    expect_split(
        "DO $a$ BEGIN PERFORM 1; $b$ not close $a$;",
        ["DO $a$ BEGIN PERFORM 1; $b$ not close $a$"],
        "DO other tag is text",
    )
    expect_fail("SELECT /* unclosed", "V15_DIALECT", "SELECT /* unclosed", "unclosed block")
    expect_fail("SELECT /* /* */", "V15_DIALECT", "SELECT /* /* */", "unclosed nested block")
    expect_fail("SELECT 'unclosed", "V15_DIALECT", "SELECT 'unclosed", "unclosed string")
    expect_fail("SELECT E'unclosed", "V15_DIALECT", "SELECT E'unclosed", "unclosed E-string")
    expect_fail("SELECT E'foo\\", "V15_DIALECT", "SELECT E'foo\\", "unclosed E escape")
    expect_fail("SELECT U&'unclosed", "V15_DIALECT", "SELECT U&'unclosed", "unclosed U&")
    expect_fail('SELECT "unclosed', "V15_DIALECT", 'SELECT "unclosed', "unclosed ident")
    expect_fail("SELECT $$ unclosed", "V15_DIALECT", "SELECT $$ unclosed", "unclosed dollar")
    expect_fail(
        "SELECT $tag$ unclosed $other$",
        "V15_DIALECT",
        "SELECT $tag$ unclosed $other$",
        "other tag does not close",
    )
    expect_fail(
        "SELECT $a$ x $a$ y $a$",
        "V15_DIALECT",
        "SELECT $a$ x $a$ y $a$",
        "same tag closes, no stack",
    )
    expect_fail(
        "SELECT 1; SELECT 'oops",
        "V15_DIALECT",
        "SELECT 1; SELECT 'oops",
        "unclosed is not a partial list",
    )
    nul = "SELECT 1;\x00SELECT 2"
    expect_fail(
        nul,
        "V15_VALUE_INVALID",
        "SELECT 1;\\u0000SELECT 2",
        "NUL sanitized",
    )
    got = split_sql(nul)
    assert isinstance(got, SplitFailure)
    check("NUL six chars", "\\u0000" in got.sql and "\x00" not in got.sql, got.sql)
    expect_fail(
        "SELECT '\x00",
        "V15_VALUE_INVALID",
        "SELECT '\\u0000",
        "NUL beats unclosed",
    )
    multi = split_sql("a\x00b\x00")
    assert isinstance(multi, SplitFailure)
    check("NUL each", multi.sql == "a\\u0000b\\u0000", multi.sql)


def test_classify() -> None:
    plain = classify_statement("SELECT 1")
    check(
        "five-field tuple",
        plain == ("plain", None, None, None, None),
        plain,
    )
    check(
        "four-tuple is not equal",
        plain != ("plain", None, None, None),
        plain,
    )
    check(
        "as_core four-tuple",
        plain.as_core() == ("plain", None, None, None),
        plain.as_core(),
    )
    expect_class(
        'SELECT jaz."return"(1)',
        "return",
        None,
        "1",
        None,
        "quoted return",
    )
    expect_class(
        'SELECT jaz."raise"(\'x\')',
        "raise",
        None,
        "'x'",
        None,
        "quoted raise",
    )
    expect_class(
        "SELECT jaz.print('hi')",
        "print",
        None,
        "'hi'",
        None,
        "print",
    )
    expect_class(
        "SELECT jaz.assign('ab','1')",
        "assign",
        "ab",
        "'1'",
        None,
        "assign",
    )
    expect_class(
        "select JAZ.bind_invoke('Child','1')",
        "bind_invoke",
        "Child",
        "'1'",
        None,
        "bind_invoke case",
    )
    expect_class(
        'SELECT jaz."bind_invoke"(\'n\',\'1\')',
        "bind_invoke",
        "n",
        "'1'",
        None,
        "quoted lowercase bind_invoke",
    )
    expect_class(
        'SELECT jaz."return"( 1 + 2 )',
        "return",
        None,
        " 1 + 2 ",
        None,
        "arg_sql raw span",
    )
    expect_class(
        'SELECT\n  jaz\n.\n"return"\n(\n1\n)',
        "return",
        None,
        "\n1\n",
        None,
        "whitespace between tokens",
    )
    expect_class(
        "SELECT jaz.\"return\"(jsonb_build_object('a', 1))",
        "return",
        None,
        "jsonb_build_object('a', 1)",
        None,
        "comma under parens",
    )
    expect_class(
        "SELECT jaz.return('null'::jsonb)",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "unquoted return",
    )
    expect_class(
        "SELECT jaz.raise('x')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "unquoted raise",
    )
    expect_class(
        "SELECT jaz.RETURN(1)",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "unquoted RETURN",
    )
    expect_class(
        "SELECT jaz.RAISE('x')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "unquoted RAISE",
    )
    expect_class(
        'SELECT jaz."RETURN"(1)',
        "plain",
        None,
        None,
        None,
        "quoted RETURN is not the control name",
    )
    expect_class(
        'SELECT jaz."RAISE"(\'x\')',
        "plain",
        None,
        None,
        None,
        "quoted RAISE is not the control name",
    )
    expect_class(
        'SELECT jaz."BIND_INVOKE"(\'n\',\'1\')',
        "plain",
        None,
        None,
        None,
        "quoted BIND_INVOKE is a different name",
    )
    expect_class(
        "SELECT 'jaz.bind_invoke'",
        "plain",
        None,
        None,
        None,
        "control name in string",
    )
    expect_class(
        "SELECT $$ jaz.\"return\"(1) $$",
        "plain",
        None,
        None,
        None,
        "control name in dollar quote",
    )
    expect_class(
        "SELECT 1 -- jaz.raise\n",
        "plain",
        None,
        None,
        None,
        "control name in line comment",
    )
    expect_class(
        "/* jaz.bind_invoke */ SELECT 1",
        "plain",
        None,
        None,
        None,
        "control name in block comment",
    )
    expect_class(
        "SELECT jaz.bind_invoke(name, '{}')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "non-literal ident",
    )
    expect_class(
        "SELECT jaz.bind_invoke(E'name', '{}')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "E-string ident",
    )
    expect_class(
        "SELECT jaz.bind_invoke(U&'name', '{}')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "U& ident",
    )
    expect_class(
        "SELECT jaz.bind_invoke($$name$$, '{}')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "dollar ident",
    )
    expect_class(
        "SELECT jaz.bind_invoke('return', '{}')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "reserved bind name",
    )
    expect_class(
        "SELECT jaz.assign('Return','1')",
        "assign",
        "Return",
        "'1'",
        None,
        "Return is not reserved",
    )
    name63 = "a" * 63
    name64 = "a" * 64
    expect_class(
        f"SELECT jaz.assign('{name63}','1')",
        "assign",
        name63,
        "'1'",
        None,
        "name length 63",
    )
    expect_class(
        f"SELECT jaz.assign('{name64}','1')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "name length 64",
    )
    expect_class(
        'SELECT jaz."return"()',
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "empty return expr",
    )
    expect_class(
        "SELECT jaz.print('a', 'b')",
        "plain",
        None,
        None,
        "V15_INVOKE_FORM",
        "print extra comma",
    )
    expect_class(
        "SELECT jaz.print(1), 1",
        "plain",
        None,
        None,
        None,
        "print outside canonical form",
    )
    expect_class(
        "SELECT jaz.assign('n','1'), 1",
        "plain",
        None,
        None,
        None,
        "assign outside canonical form",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', (SELECT 1 INTO t))",
        "bind_invoke",
        "n",
        " (SELECT 1 INTO t)",
        "V15_INVOKE_FORM",
        "bind arg INTO",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', (SELECT nextval('s')))",
        "bind_invoke",
        "n",
        " (SELECT nextval('s'))",
        "V15_INVOKE_FORM",
        "bind arg nextval",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', (SELECT pg_catalog.setval('s', 1)))",
        "bind_invoke",
        "n",
        " (SELECT pg_catalog.setval('s', 1))",
        "V15_INVOKE_FORM",
        "bind arg pg_catalog.setval",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', (SELECT CURRVAL('s')))",
        "bind_invoke",
        "n",
        " (SELECT CURRVAL('s'))",
        "V15_INVOKE_FORM",
        "bind arg currval case",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', '{\"sql\":\"INSERT\"}'::jsonb)",
        "bind_invoke",
        "n",
        " '{\"sql\":\"INSERT\"}'::jsonb",
        None,
        "INSERT inside string is not a write token",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', $$ INSERT $$::jsonb)",
        "bind_invoke",
        "n",
        " $$ INSERT $$::jsonb",
        None,
        "INSERT inside dollar quote",
    )
    expect_class(
        "SELECT jaz.bind_invoke('n', (SELECT 1 -- nextval(\n))",
        "bind_invoke",
        "n",
        " (SELECT 1 -- nextval(\n)",
        None,
        "nextval in comment",
    )
    expect_class(
        "SELECT jaz.assign('n', (SELECT nextval('s')))",
        "assign",
        "n",
        " (SELECT nextval('s'))",
        None,
        "assign arg is not the bind_invoke write scan",
    )
    for sql in UTILITY:
        expect_class(sql, "plain", None, None, "V15_DIALECT", f"utility {sql}")
    expect_class(
        "DO $$ BEGIN PERFORM 1; END $$",
        "plain",
        None,
        None,
        "V15_DIALECT",
        "DO body rejected",
    )
    expect_class("TRUNCATE t", "plain", None, None, "V15_DIALECT", "TRUNCATE")
    expect_class("END", "plain", None, None, "V15_DIALECT", "END")
    expect_class("ABORT", "plain", None, None, "V15_DIALECT", "ABORT")
    expect_class("RELEASE s", "plain", None, None, "V15_DIALECT", "RELEASE")
    for sql in DDL:
        expect_class(sql, "plain", None, None, "V15_DDL", f"ddl {sql.split()[0]} {sql.split()[1]}")
    expect_class(
        "ALTER TABLE t ADD COLUMN x int",
        "plain",
        None,
        None,
        "V15_DDL",
        "ALTER TABLE add column",
    )
    for sql in PLAIN:
        expect_class(sql, "plain", None, None, None, f"plain {sql[:40]}")
    expect_class(
        "WITH RECURSIVE c AS (SELECT 1 AS n) SELECT n FROM c",
        "plain",
        None,
        None,
        None,
        "WITH RECURSIVE executable",
    )


def test_pragma() -> None:
    sql = "-- timeout: 1.5\nSELECT 1"
    expect_class(sql, "plain", None, None, None, "legal pragma")
    check("pragma 1500", timeout_pragma_ms(sql) == 1500, timeout_pragma_ms(sql))
    check(
        "pragma line kept",
        split_sql("-- timeout: 1\nSELECT 1\n") == ["-- timeout: 1\nSELECT 1"],
    )
    check(
        "pragma stripped for exec",
        sql_without_timeout_pragma(sql) == "SELECT 1",
        sql_without_timeout_pragma(sql),
    )
    expect_class(
        "-- timeout: 0.001\nSELECT jaz.\"return\"(1)",
        "return",
        None,
        "1",
        None,
        "pragma 1 ms on return",
    )
    check(
        "floor 1",
        timeout_pragma_ms("-- timeout: 0.001\nSELECT 1") == 1,
    )
    check(
        "floor 1900",
        timeout_pragma_ms("-- timeout: 1.9\nSELECT 1") == 1900,
    )
    check(
        "spaced pragma",
        timeout_pragma_ms("   --   timeout:   2   \nSELECT 1") == 2000,
    )
    for bad, label in (
        ("-- timeout: -1\nSELECT 1", "negative"),
        ("-- timeout: 0\nSELECT 1", "zero"),
        ("-- timeout: 0.0009\nSELECT 1", "floor zero"),
        ("-- timeout:\nSELECT 1", "missing number"),
        ("-- timeout: abc\nSELECT 1", "not decimal"),
        ("-- timeout: 1 extra\nSELECT 1", "trailing junk"),
        ("-- timeout: 1e2\nSELECT 1", "scientific"),
    ):
        expect_class(bad, "plain", None, None, "V15_VALUE_INVALID", f"bad pragma {label}")
        check(f"bad pragma ms {label}", timeout_pragma_ms(bad) is None)
    expect_class(
        "SELECT 1\n-- timeout: 9",
        "plain",
        None,
        None,
        None,
        "second line is a comment",
    )
    check(
        "second line ms",
        timeout_pragma_ms("SELECT 1\n-- timeout: 9") is None,
    )
    expect_class(
        "-- Timeout: 1\nSELECT 1",
        "plain",
        None,
        None,
        None,
        "Timeout case is not the pragma",
    )
    expect_class(
        "-- timeout: no\nSELECT jaz.\"return\"(1)",
        "return",
        None,
        "1",
        "V15_VALUE_INVALID",
        "bad pragma on canonical",
    )
    expect_class(
        "-- timeout: no\nDO $$ BEGIN END $$",
        "plain",
        None,
        None,
        "V15_DIALECT",
        "dialect wins over bad pragma",
    )


def test_render() -> None:
    doc = (AGENT_ROOT / "docs/designs/v15-jaz-dev.md").read_text()
    check(
        "spec response",
        _fence(doc, "Your entire reply is a PostgreSQL statement list.") == RESPONSE_FORMAT,
    )
    check(
        "spec repl",
        _fence(doc, "Statements run one at a time.") == REPL_TEXT,
    )
    check(
        "spec history",
        _fence(doc, "Finished iterations of this invoke are rows of jaz.history")
        == HISTORY_TEXT,
    )
    check(
        "spec tail",
        _fence(doc, "To delegate to a child invoke,") == TAIL_DELEGATION,
    )
    bindings = [
        {"name": "b", "kind": "var", "show_in_prompt": True, "value_text": "9"},
        {"name": "A", "kind": "scope", "show_in_prompt": True, "value_text": '{"z":1}'},
        {"name": "a", "kind": "input", "show_in_prompt": True, "value_text": '"hello"'},
        {
            "name": "lookup",
            "kind": "tool",
            "show_in_prompt": True,
            "description": "finds rows",
        },
        {"name": "hidden", "kind": "scope", "show_in_prompt": False, "value_text": "1"},
        {"name": "secret", "kind": "input", "show_in_prompt": False, "value_text": "nope"},
    ]
    on = render_system(recursion_available=True, bindings=bindings)
    off = render_system(recursion_available=False, bindings=bindings)
    check("history both", HISTORY_TEXT in on and HISTORY_TEXT in off)
    check("repl both", REPL_TEXT in on and REPL_TEXT in off)
    check("tail only when recursive", TAIL_DELEGATION in on and TAIL_DELEGATION not in off)
    check("bind teaching on", "jaz.bind_invoke" in on)
    check("no bind_invoke when off", "bind_invoke" not in off, off)
    check("no delegation format line", RESPONSE_FORMAT_NO_DELEGATION in off)
    check(
        "scoped order",
        "scoped names:\nA kind=scope\na kind=input\nb kind=var\nlookup kind=tool finds rows"
        not in on
        and on.endswith("scoped names:\nA kind=scope\nb kind=var\nlookup kind=tool finds rows"),
        on.split("scoped names:")[-1],
    )
    check("hidden scope omitted", "hidden" not in on)
    check("input value not in system", '"hello"' not in on)
    check("history denies __history__", "There is no __history__ object." in on)
    user = render_inputs(bindings)
    check("inputs", user == 'inputs:\na: "hello"', user)
    check("hidden input omitted", render_inputs(
        [{"name": "secret", "kind": "input", "show_in_prompt": False, "value_text": "nope"}]
    ) is None)
    check("no inputs", render_inputs([]) is None)
    check("seed ids", seed_system_id() == "seed:system" and seed_inputs_id() == "seed:inputs")
    check(
        "iter ids",
        iter_message_id(0, "assistant") == "iter:0:assistant"
        and iter_message_id(10, "observation") == "iter:10:observation",
    )
    text = "abcdefghijklmnopqrstuvwxyz0123456789"
    truncated = truncate_text(text, 28, 0.7)
    check(
        "truncate middle",
        truncated == "abcdefg" + MARKER + "6789" and len(truncated) == 28,
        truncated,
    )
    check("truncate short", truncate_text("abc", 10, 0.7) == "abc")
    check(
        "truncate keepable below 1",
        truncate_text(text, 10, 0.7) == text[:10] and MARKER not in truncate_text(text, 10, 0.7),
    )
    emoji = "🙂" * 30
    emoji_cut = truncate_text(emoji, 28, 0.7)
    check("char length", len(emoji_cut) == 28 and emoji_cut.startswith("🙂" * 7), len(emoji_cut))
    protocol = {
        "max_invoke_input_length": 40,
        "truncation_prefix_ratio": 0.5,
        "max_repl_output_length": 200,
    }
    base = [
        {"message_id": "seed:system", "role": "system", "kind": "system", "content": "S" * 10},
        {
            "message_id": "iter:0:assistant",
            "role": "assistant",
            "kind": "assistant",
            "content": "Q",
        },
        {
            "message_id": "iter:0:observation",
            "role": "user",
            "kind": "observation",
            "content": "A" * 100,
        },
    ]
    shrunk = truncate_base(base, protocol)
    check("assistant untouched", shrunk[1]["content"] == "Q")
    check("system untouched", shrunk[0]["content"] == "S" * 10)
    check("observation shrunk", len(shrunk[2]["content"]) == 29, len(shrunk[2]["content"]))
    check("ids stable", [row["message_id"] for row in shrunk] == [row["message_id"] for row in base])
    check("caller unchanged", base[2]["content"] == "A" * 100)
    floor = truncate_base(
        [
            {"message_id": "seed:system", "role": "system", "kind": "system", "content": "S" * 20},
            {
                "message_id": "iter:0:observation",
                "role": "user",
                "kind": "observation",
                "content": "A" * 80,
            },
            {
                "message_id": "iter:1:observation",
                "role": "user",
                "kind": "observation",
                "content": "B" * 80,
            },
        ],
        {
            "max_invoke_input_length": 50,
            "truncation_prefix_ratio": 0.5,
            "max_repl_output_length": 100,
        },
    )
    check(
        "oldest then next to marker",
        floor[1]["content"] == MARKER and floor[2]["content"] == MARKER and floor[0]["content"] == "S" * 20,
        [len(row["content"]) for row in floor],
    )
    inputs_cut = truncate_base(
        [
            {"message_id": "seed:system", "role": "system", "kind": "system", "content": "S" * 10},
            {
                "message_id": "iter:0:observation",
                "role": "user",
                "kind": "observation",
                "content": "A" * 5,
            },
            {"message_id": "seed:inputs", "role": "user", "kind": "input", "content": "I" * 40},
        ],
        {
            "max_invoke_input_length": 30,
            "truncation_prefix_ratio": 0.5,
            "max_repl_output_length": 100,
        },
    )
    check("short observation kept", inputs_cut[1]["content"] == "A" * 5)
    check("inputs cut to fit", inputs_cut[2]["content"] == "I" * 15, inputs_cut[2]["content"])
    over = truncate_base(
        [{"message_id": "seed:system", "role": "system", "kind": "system", "content": "S" * 100}],
        {
            "max_invoke_input_length": 10,
            "truncation_prefix_ratio": 0.7,
            "max_repl_output_length": 4000,
        },
    )
    check("system over limit still returned", over[0]["content"] == "S" * 100)
    repl_capped = truncate_base(
        [
            {
                "message_id": "iter:0:assistant",
                "role": "assistant",
                "kind": "assistant",
                "content": "Q" * 50,
            },
            {
                "message_id": "iter:0:observation",
                "role": "user",
                "kind": "observation",
                "content": "Z" * 50,
            },
        ],
        {
            "max_invoke_input_length": 100000,
            "truncation_prefix_ratio": 0.5,
            "max_repl_output_length": 20,
        },
    )
    check("assistant ignores repl cap", repl_capped[0]["content"] == "Q" * 50)
    check(
        "observation repl cap",
        len(repl_capped[1]["content"]) == 20
        and repl_capped[1]["message_id"] == "iter:0:observation",
        len(repl_capped[1]["content"]),
    )
    rendered = render_base(
        recursion_available=False,
        bindings=[{"name": "q", "kind": "input", "show_in_prompt": True, "value_text": "1"}],
        history=[
            {
                "message_id": "iter:0:observation",
                "role": "user",
                "kind": "observation",
                "content": "obs",
            }
        ],
        protocol={
            "max_invoke_input_length": 100000,
            "truncation_prefix_ratio": 0.7,
            "max_repl_output_length": 4000,
        },
    )
    check(
        "base ids",
        [row["message_id"] for row in rendered]
        == ["seed:system", "seed:inputs", "iter:0:observation"],
    )
    check("base omits bind", "bind_invoke" not in rendered[0]["content"])
    check("base inputs", rendered[1]["content"] == "inputs:\nq: 1")


def connect(server, user: str | None = None):
    uri = server.get_uri(DB)
    if user is None:
        return psycopg2.connect(uri)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def test_loaded(server) -> None:
    sql_path = ROOT / "v15_protocol.sql"
    for line in sql_path.read_text().splitlines():
        stripped = line.strip()
        check(
            "protocol sql is comments",
            stripped == "" or stripped.startswith("--"),
            stripped,
        )
    conn = connect(server)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT count(*)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname = 'v15'
        """
    )
    count = cur.fetchone()[0]
    check("no new tables", count == 21, count)
    conn.close()


def probe_unquoted(server) -> None:
    conn = connect(server)
    conn.autocommit = True
    cur = conn.cursor()
    for label, stmt in (
        ("return", "SELECT jaz.return('null'::jsonb)"),
        ("raise", "SELECT jaz.raise('x')"),
    ):
        try:
            cur.execute(stmt)
            print(f"PROBE unquoted {label}: executed {cur.fetchall()!r}")
        except Exception as exc:
            pgcode = getattr(exc, "pgcode", None)
            msg = str(exc).splitlines()[0]
            print(f"PROBE unquoted {label}: {type(exc).__name__} sqlstate={pgcode} {msg}")
    conn.close()


def main() -> int:
    test_split()
    test_classify()
    test_pragma()
    test_render()
    server = get_server()
    setup_db()
    test_loaded(server)
    probe_unquoted(server)
    print("[ready] protocol gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
