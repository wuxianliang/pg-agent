"""Stage 3 gate: config fold, digests, and ceiling tighten.

Run: uv run python v15/config/test_config.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.config.setup_db import DB, main as setup_db

SEED_PROFILE = "00000000-0000-4000-8000-0000000000a1"
SEED_SCOPE = "00000000-0000-4000-8000-0000000000b1"
LLM = {"model": "fake"}
REPL = {"timeout_ms": 30000}
PROTOCOL = {
    "max_invoke_input_length": 100000,
    "truncation_prefix_ratio": 0.7,
    "max_repl_output_length": 4000,
}
ENTRY = (
    "v15_register_profile",
    "v15_update_profile",
    "v15_register_scope",
    "v15_add_layer",
    "v15_resolve_config",
    "v15_resolve_child_config",
    "v15_effective_ceilings",
)
WRITES = (
    "v15_register_profile",
    "v15_update_profile",
    "v15_register_scope",
    "v15_add_layer",
)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail != "" else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def connect(server, user: str | None = None):
    uri = server.get_uri(DB)
    if user is None:
        return psycopg2.connect(uri)
    parsed = urlparse(uri)
    host = (parse_qs(parsed.query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def fails(cur, sql: str, params=None, code: str | None = None, label: str = "") -> None:
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        ok = code is None or exc.pgcode == code
        check(label, ok, f"{exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure {code}")


def fails_block(cur, statements, code: str, label: str) -> None:
    cur.execute("SAVEPOINT sp")
    try:
        for sql, params in statements:
            cur.execute(sql, params)
    except psycopg2.Error as exc:
        ok = exc.pgcode == code
        check(label, ok, f"{exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure {code}")


def uid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def j(obj) -> str:
    return json.dumps(obj)


def register(cur, profile_id, llm=None, repl=None, protocol=None, hooks=None) -> None:
    cur.execute(
        """
        SELECT v15.v15_register_profile(%s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
        """,
        (
            profile_id,
            j(LLM if llm is None else llm),
            j(REPL if repl is None else repl),
            j(PROTOCOL if protocol is None else protocol),
            j([] if hooks is None else hooks),
        ),
    )


def scope(cur, scope_id, profile_id) -> None:
    cur.execute(
        "SELECT v15.v15_register_scope(%s, %s)",
        (scope_id, profile_id),
    )


def layer(
    cur,
    layer_id,
    scope_id,
    ordinal,
    kind,
    llm=None,
    repl=None,
    protocol=None,
    depth_map=None,
    extra_hooks=None,
) -> None:
    cur.execute(
        """
        SELECT v15.v15_add_layer(
          %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb
        )
        """,
        (
            layer_id,
            scope_id,
            ordinal,
            kind,
            None if llm is None else j(llm),
            None if repl is None else j(repl),
            None if protocol is None else j(protocol),
            None if depth_map is None else j(depth_map),
            None if extra_hooks is None else j(extra_hooks),
        ),
    )


def folded(llm=None, repl=None, protocol=None, depth=1):
    return {
        "llm": LLM if llm is None else llm,
        "repl": REPL if repl is None else repl,
        "protocol": PROTOCOL if protocol is None else protocol,
        "depth": depth,
    }


def resolve(cur, scope_id, local, depth):
    cur.execute(
        """
        SELECT resolved_config = %s::jsonb,
               config_digest = md5(resolved_config::text),
               config_digest
        FROM v15.v15_resolve_config(%s, %s, %s)
        """,
        (j(folded()), scope_id, local, depth),
    )
    return cur.fetchone()


def assert_resolve(cur, scope_id, local, depth, expected, label) -> str:
    cur.execute(
        """
        SELECT resolved_config = %s::jsonb,
               config_digest = md5(resolved_config::text),
               config_digest ~ '^[0-9a-f]{32}$',
               config_digest
        FROM v15.v15_resolve_config(%s, %s, %s)
        """,
        (j(expected), scope_id, local, depth),
    )
    eq, dig, hexed, digest = cur.fetchone()
    check(label, eq is True and dig is True and hexed is True, (eq, dig, hexed))
    return digest


def test_shape(cur) -> None:
    cur.execute(
        """
        SELECT count(*)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r'
        """
    )
    check("no new tables", cur.fetchone()[0] == 21)
    for name in ENTRY:
        cur.execute(
            """
            SELECT p.prosecdef, p.provolatile, l.lanname, p.proconfig,
                   pg_get_userbyid(p.proowner),
                   has_function_privilege('v15_worker', p.oid, 'EXECUTE'),
                   has_function_privilege('v15_repl', p.oid, 'EXECUTE'),
                   has_function_privilege('public', p.oid, 'EXECUTE'),
                   has_function_privilege('v15_owner', p.oid, 'EXECUTE'),
                   p.prosrc
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_language l ON l.oid = p.prolang
            WHERE n.nspname = 'v15' AND p.proname = %s
            """,
            (name,),
        )
        row = cur.fetchone()
        check(f"fn {name}", row is not None)
        prosecdef, vol, lang, cfg, owner, worker, repl, public, own, src = row
        check(f"{name} definer", prosecdef is True and vol == "v" and lang == "plpgsql")
        check(f"{name} owner", owner == "v15_owner" and cfg == ["search_path=pg_catalog"])
        check(f"{name} execute", (worker, repl, public, own) == (False, False, False, True))
        upper = src.upper()
        check(
            f"{name} no role switch",
            "SET ROLE" not in upper and "RESET ROLE" not in upper
            and "SET SESSION AUTHORIZATION" not in upper,
        )
    for name in WRITES:
        cur.execute(
            """
            SELECT has_function_privilege('v15_bootstrap', p.oid, 'EXECUTE')
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'v15' AND p.proname = %s
            """,
            (name,),
        )
        check(f"{name} bootstrap", cur.fetchone()[0] is True)
    cur.execute(
        """
        SELECT has_function_privilege('v15_bootstrap', p.oid, 'EXECUTE')
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'v15_resolve_config'
        """
    )
    check("resolve not bootstrap", cur.fetchone()[0] is False)


def test_seed(cur) -> None:
    cur.execute(
        """
        SELECT profile_digest = v15.v15_profile_digest(llm, repl, protocol, baseline_hooks),
               baseline_hooks = '[]'::jsonb
        FROM v15.config_profiles
        WHERE profile_id = %s
        """,
        (SEED_PROFILE,),
    )
    check("seed profile digest", cur.fetchone() == (True, True))
    cur.execute(
        """
        SELECT scope_digest = v15.v15_scope_digest(profile_id)
        FROM v15.config_scopes
        WHERE scope_id = %s AND profile_id = %s
        """,
        (SEED_SCOPE, SEED_PROFILE),
    )
    check("seed scope digest", cur.fetchone()[0] is True)
    assert_resolve(cur, SEED_SCOPE, None, 1, folded(), "seed resolve")


def test_fold(cur) -> None:
    profile = uid(10)
    sc = uid(11)
    register(
        cur,
        profile,
        llm={"model": "base", "temperature": 0.2},
        repl={"timeout_ms": 30000},
    )
    scope(cur, sc, profile)
    other = {
        "max_invoke_input_length": 50,
        "truncation_prefix_ratio": 0.4,
        "max_repl_output_length": 9,
    }
    layer(cur, uid(12), sc, 5, "depth", depth_map={"1": {"protocol": other}})
    layer(cur, uid(14), sc, 1, "plain", llm={"model": "prop", "temperature": 0.9})
    layer(cur, uid(13), sc, 0, "plain", repl={"timeout_ms": 222})
    local = uid(15)
    layer(cur, local, None, 0, "plain", llm={"model": "local"})
    layer(
        cur,
        uid(16),
        sc,
        9,
        "plain",
        extra_hooks=[{"hook_key": "governance_iterations", "config": {}}],
    )
    digest = assert_resolve(
        cur,
        sc,
        local,
        1,
        folded(
            llm={"model": "local"},
            repl={"timeout_ms": 222},
            protocol=other,
        ),
        "four layers each win and later wins",
    )
    bare = assert_resolve(
        cur,
        sc,
        None,
        1,
        folded(
            llm={"model": "prop", "temperature": 0.9},
            repl={"timeout_ms": 222},
            protocol=other,
        ),
        "without local plain wins over depth",
    )
    check("local changes digest", digest != bare)
    child_cfg = uid(17)
    cur.execute(
        """
        SELECT resolved_config = %s::jsonb
        FROM v15.v15_resolve_child_config(%s, NULL, 1)
        """,
        (j(folded(
            llm={"model": "prop", "temperature": 0.9},
            repl={"timeout_ms": 222},
            protocol=other,
        )), sc),
    )
    check("child path drops local", cur.fetchone()[0] is True)
    assert_resolve(
        cur,
        sc,
        None,
        2,
        folded(
            llm={"model": "prop", "temperature": 0.9},
            repl={"timeout_ms": 222},
            depth=2,
        ),
        "depth 2 ignores depth 1 partial",
    )
    deep_protocol = {
        "max_invoke_input_length": 7,
        "truncation_prefix_ratio": 0.2,
        "max_repl_output_length": 3,
    }
    layer(cur, uid(18), sc, 6, "depth", depth_map={"2": {"protocol": deep_protocol}})
    assert_resolve(
        cur,
        sc,
        None,
        1,
        folded(
            llm={"model": "prop", "temperature": 0.9},
            repl={"timeout_ms": 222},
            protocol=other,
        ),
        "depth 2 partial does not affect depth 1",
    )
    assert_resolve(
        cur,
        sc,
        None,
        2,
        folded(
            llm={"model": "prop", "temperature": 0.9},
            repl={"timeout_ms": 222},
            protocol=deep_protocol,
            depth=2,
        ),
        "depth 2 partial replaces protocol whole",
    )
    layer(cur, uid(19), sc, 2, "plain", protocol=PROTOCOL)
    assert_resolve(
        cur,
        sc,
        None,
        1,
        folded(
            llm={"model": "prop", "temperature": 0.9},
            repl={"timeout_ms": 222},
        ),
        "protocol-only layer leaves llm",
    )
    layer(cur, uid(20), sc, 3, "plain", llm={"model": "only"})
    assert_resolve(
        cur,
        sc,
        None,
        1,
        folded(llm={"model": "only"}, repl={"timeout_ms": 222}),
        "later llm replaces whole object",
    )
    cur.execute(
        """
        SELECT layer_digest = v15.v15_layer_digest(llm, repl, protocol, depth_map, extra_hooks)
        FROM v15.config_layers
        WHERE layer_id = %s
        """,
        (uid(16),),
    )
    check("layer digest omits sql nulls", cur.fetchone()[0] is True)


def test_errors(cur) -> None:
    profile = uid(30)
    sc = uid(31)
    register(cur, profile)
    scope(cur, sc, profile)
    fails(
        cur,
        """
        SELECT v15.v15_add_layer(%s, %s, 0, 'depth', %s::jsonb, NULL, NULL, %s::jsonb, NULL)
        """,
        (uid(32), sc, j(LLM), j({"1": {"llm": LLM}})),
        "P1530",
        "depth column V15_DEPTH_SELF",
    )
    fails(
        cur,
        """
        SELECT v15.v15_add_layer(%s, %s, 0, 'depth', NULL, NULL, NULL, %s::jsonb, %s::jsonb)
        """,
        (uid(33), sc, j({"1": {"llm": LLM}}), j([])),
        "P1530",
        "depth extra_hooks V15_DEPTH_SELF",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, NULL, 0, 'depth', NULL, NULL, NULL, %s::jsonb, NULL)",
        (uid(34), j({"1": {"llm": LLM}})),
        "P1531",
        "depth local V15_CONFIG_LOCAL",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 0, 'depth', NULL, NULL, NULL, %s::jsonb, NULL)",
        (uid(35), sc, j({"1": {"depth_map": {}}})),
        "P1530",
        "nested depth_map V15_DEPTH_SELF",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 0, 'depth', NULL, NULL, NULL, %s::jsonb, NULL)",
        (uid(36), sc, j({"1": {"baseline_hooks": []}})),
        "P1532",
        "partial baseline_hooks V15_BASELINE_IMMUTABLE",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 0, 'depth', NULL, NULL, NULL, %s::jsonb, NULL)",
        (uid(37), sc, j({"01": {"llm": LLM}})),
        "P1524",
        "leading zero depth key",
    )
    plain = uid(38)
    layer(cur, plain, sc, 0, "plain", protocol=PROTOCOL)
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, %s, 1)",
        (sc, plain),
        "P1531",
        "scoped layer as local",
    )
    depth = uid(39)
    layer(cur, depth, sc, 1, "depth", depth_map={"1": {"llm": {"model": "d"}}})
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, %s, 1)",
        (sc, depth),
        "P1531",
        "depth layer as local",
    )
    local = uid(40)
    layer(cur, local, None, 0, "plain", llm={"model": "local"})
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_child_config(%s, %s, 2)",
        (sc, local),
        "P1531",
        "child path rejects local",
    )
    cur.execute(
        """
        SELECT resolved_config -> 'llm' ->> 'model'
        FROM v15.v15_resolve_child_config(%s, NULL, 2)
        """,
        (sc,),
    )
    check("child null local ignores parent local", cur.fetchone()[0] == "fake")
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 2, 'plain', %s::jsonb, NULL, NULL, NULL, NULL)",
        (uid(41), sc, j({"model": "x", "reject_finish_on_printed_output": True})),
        "P1524",
        "unknown component key",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 3, 'plain', %s::jsonb, NULL, NULL, NULL, NULL)",
        (uid(42), sc, j({"model": "x", "max_iterations": 1})),
        "P1524",
        "governance name in component",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 4, 'depth', NULL, NULL, NULL, %s::jsonb, NULL)",
        (uid(43), sc, j({"1": {"max_depth": 1}})),
        "P1524",
        "governance name in partial",
    )
    fails(
        cur,
        "SELECT v15.v15_register_profile(%s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)",
        (uid(44), j(LLM), j(REPL), j(PROTOCOL), j(["governance_iterations"])),
        "P1524",
        "baseline_hooks duplicates governance",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 8, 'plain', NULL, NULL, NULL, NULL, %s::jsonb)",
        (uid(45), sc, j([{"hook_key": "missing", "config": {}}])),
        "P1524",
        "unknown extra hook",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 8, 'plain', NULL, NULL, NULL, NULL, %s::jsonb)",
        (uid(46), sc, j([{"baseline_hooks": [], "hook_key": "governance_io", "config": {}}])),
        "P1532",
        "extra_hooks baseline_hooks key",
    )
    cur.execute(
        """
        INSERT INTO v15.config_layers (
          layer_id, scope_id, ordinal, kind, depth_map, layer_digest
        ) VALUES (%s, %s, 20, 'depth', %s::jsonb, 'planted')
        """,
        (uid(47), sc, j({"2": "nope", "1": {"llm": {"model": "kept"}}})),
    )
    assert_resolve(cur, sc, None, 1, folded(llm={"model": "kept"}), "unselected invalid depth skipped")
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 2)",
        (sc,),
        "P1524",
        "selected invalid partial",
    )
    cur.execute(
        """
        INSERT INTO v15.config_layers (
          layer_id, scope_id, ordinal, kind, depth_map, extra_hooks, layer_digest
        ) VALUES (%s, %s, 21, 'depth', '{"3": {"llm": {"model": "z"}}}'::jsonb, '[]'::jsonb, 'planted')
        """,
        (uid(48), sc),
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 1)",
        (sc,),
        "P1530",
        "resolve depth extra_hooks",
    )
    cur.execute("DELETE FROM v15.config_layers WHERE layer_id = %s", (uid(48),))
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 1)",
        (uid(49),),
        "P1524",
        "missing scope",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, %s, 1)",
        (sc, uid(50)),
        "P1524",
        "missing local",
    )


def test_jsonb_presence(cur) -> None:
    profile = uid(60)
    sc = uid(61)
    register(cur, profile, llm={"model": "base", "temperature": 0.3})
    scope(cur, sc, profile)
    layer(cur, uid(62), sc, 0, "plain", protocol=PROTOCOL)
    assert_resolve(
        cur,
        sc,
        None,
        1,
        folded(llm={"model": "base", "temperature": 0.3}),
        "sql null column does not replace",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 1, 'plain', 'null'::jsonb, NULL, NULL, NULL, NULL)",
        (uid(63), sc),
        "P1524",
        "json null column rejected",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, %s, 1, 'depth', NULL, NULL, NULL, %s::jsonb, NULL)",
        (uid(64), sc, j({"1": {"llm": None}})),
        "P1524",
        "partial key present null rejected",
    )
    layer(
        cur,
        uid(65),
        sc,
        2,
        "depth",
        depth_map={"1": {"repl": {"timeout_ms": 5}}},
    )
    assert_resolve(
        cur,
        sc,
        None,
        1,
        folded(llm={"model": "base", "temperature": 0.3}, repl={"timeout_ms": 5}),
        "absent partial key does not replace",
    )
    cur.execute(
        """
        INSERT INTO v15.config_layers (
          layer_id, scope_id, ordinal, kind, llm, layer_digest
        ) VALUES (%s, %s, 3, 'plain', 'null'::jsonb, 'planted')
        """,
        (uid(66), sc),
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 1)",
        (sc,),
        "P1524",
        "resolve json null column",
    )
    cur.execute("DELETE FROM v15.config_layers WHERE layer_id = %s", (uid(66),))
    layer(cur, uid(67), sc, 4, "plain", llm={"temperature": 0.5})
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 1)",
        (sc,),
        "P1524",
        "required model missing at end",
    )
    cur.execute("DELETE FROM v15.config_layers WHERE layer_id = %s", (uid(67),))
    cur.execute(
        """
        INSERT INTO v15.config_layers (
          layer_id, scope_id, ordinal, kind, llm, layer_digest
        ) VALUES (%s, %s, 5, 'plain', %s::jsonb, 'planted')
        """,
        (uid(68), sc, j({"model": "bad", "nope": 1})),
    )
    layer(cur, uid(69), sc, 6, "plain", llm={"model": "later"})
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 1)",
        (sc,),
        "P1524",
        "invalid key fails before later replace",
    )


def test_freeze(cur) -> None:
    profile = uid(70)
    sc = uid(71)
    register(cur, profile)
    scope(cur, sc, profile)
    cur.execute(
        """
        SELECT resolved_config::text, config_digest
        FROM v15.v15_resolve_config(%s, NULL, 1)
        """,
        (sc,),
    )
    frozen, digest = cur.fetchone()
    invoke = str(uuid.uuid4())
    cur.execute(
        """
        SELECT ceilings, manifest_digest
        FROM v15.v15_effective_ceilings(NULL, NULL)
        """
    )
    _ceil, manifest_digest = cur.fetchone()
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, root_invoke_id, depth, status, fatal, recursion_available,
          resolved_config, config_digest, config_scope_id, manifest_digest,
          scratch_schema, fence, created_at, updated_at
        ) VALUES (
          %s, %s, 1, 'runnable', false, true,
          %s::jsonb, %s, %s, %s,
          %s, 1, clock_timestamp(), clock_timestamp()
        )
        """,
        (
            invoke,
            invoke,
            frozen,
            digest,
            sc,
            manifest_digest,
            "s_" + invoke.replace("-", ""),
        ),
    )
    cur.execute(
        """
        UPDATE v15.config_profiles
        SET llm = '{"model":"changed"}'::jsonb
        WHERE profile_id = %s
        """,
        (profile,),
    )
    cur.execute(
        """
        SELECT resolved_config -> 'llm' ->> 'model', config_digest
        FROM v15.v15_resolve_config(%s, NULL, 1)
        """,
        (sc,),
    )
    new_model, new_digest = cur.fetchone()
    check("later resolve sees profile update", new_model == "changed" and new_digest != digest)
    cur.execute(
        """
        SELECT resolved_config::text = %s,
               config_digest = %s,
               config_digest = md5(resolved_config::text)
        FROM v15.invokes
        WHERE invoke_id = %s
        """,
        (frozen, digest, invoke),
    )
    same_cfg, same_digest, matches = cur.fetchone()
    check(
        "frozen row digest unchanged",
        same_cfg is True and same_digest is True and matches is True,
    )


def ceilings(cur, tighten, parent):
    cur.execute(
        """
        SELECT ceilings::text, manifest_digest,
               manifest_digest = md5(ceilings::text),
               manifest_digest = v15.v15_manifest_digest(
                 (ceilings ->> 'max_iterations')::int,
                 (ceilings ->> 'max_depth')::int,
                 (ceilings ->> 'max_io_attempts')::int,
                 (ceilings ->> 'max_statement_ms')::int
               )
        FROM v15.v15_effective_ceilings(%s::jsonb, %s::jsonb)
        """,
        (
            None if tighten is None else j(tighten),
            None if parent is None else j(parent),
        ),
    )
    return cur.fetchone()


def test_ceilings(cur) -> None:
    row = ceilings(cur, None, None)
    ceilings_obj, digest, text_ok, fn_ok = row
    parsed = json.loads(ceilings_obj)
    check("empty ceilings match manifest shape", text_ok is True and fn_ok is True)
    check(
        "empty ceilings values",
        parsed == {
            "max_depth": 8,
            "max_io_attempts": 3,
            "max_iterations": 10,
            "max_statement_ms": 30000,
        },
    )
    cur.execute("SELECT manifest_digest FROM v15.governance_manifest WHERE manifest_id = 1")
    check("untightened digest equals singleton", cur.fetchone()[0] == digest)
    tight = ceilings(cur, {"max_iterations": 4}, None)
    tight_obj = json.loads(tight[0])
    check("tighten one key", tight_obj["max_iterations"] == 4 and tight_obj["max_depth"] == 8)
    check("tightened digest differs", tight[1] != digest and tight[2] is True and tight[3] is True)
    equal = ceilings(cur, {"max_iterations": 10, "max_depth": 8}, None)
    check("equal to manifest is not a raise", equal[1] == digest)
    parent = {
        "max_iterations": 4,
        "max_depth": 8,
        "max_io_attempts": 3,
        "max_statement_ms": 1000,
    }
    child = ceilings(cur, None, parent)
    child_obj = json.loads(child[0])
    check(
        "child min keeps parent when tighter",
        child_obj["max_iterations"] == 4 and child_obj["max_statement_ms"] == 1000
        and child_obj["max_depth"] == 8,
    )
    check("child digest is effective not singleton", child[1] != digest and child[2] is True)
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings(%s::jsonb, NULL)",
        (j({"max_iterations": 11}),),
        "P1505",
        "raise above manifest",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings(%s::jsonb, NULL)",
        (j({"max_depth": 9}),),
        "P1505",
        "raise max_depth",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings(%s::jsonb, NULL)",
        (j({"max_iterations": 0}),),
        "P1524",
        "ceiling below 1",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings(%s::jsonb, NULL)",
        (j({"max_iterations": 1.5}),),
        "P1524",
        "ceiling not integer",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings(%s::jsonb, NULL)",
        (j({"nope": 1}),),
        "P1524",
        "ceiling extra key",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings('null'::jsonb, NULL)",
        code="P1524",
        label="ceiling json null",
    )
    fails(
        cur,
        "SELECT * FROM v15.v15_effective_ceilings(%s::jsonb, %s::jsonb)",
        (j({"max_iterations": 1}), j(parent)),
        "P1524",
        "child has no p_ceilings",
    )
    cur.execute("SAVEPOINT manifest_min")
    cur.execute(
        """
        UPDATE v15.governance_manifest
        SET max_iterations = 2,
            max_depth = 2,
            manifest_digest = v15.v15_manifest_digest(2, 2, 3, 30000)
        WHERE manifest_id = 1
        """
    )
    shrunk = ceilings(cur, None, parent)
    shrunk_obj = json.loads(shrunk[0])
    check(
        "child min with tighter manifest",
        shrunk_obj == {
            "max_depth": 2,
            "max_io_attempts": 3,
            "max_iterations": 2,
            "max_statement_ms": 1000,
        },
    )
    check(
        "min not above parent or manifest",
        shrunk_obj["max_iterations"] <= parent["max_iterations"]
        and shrunk_obj["max_iterations"] <= 2
        and shrunk_obj["max_depth"] <= 2
        and shrunk_obj["max_statement_ms"] <= parent["max_statement_ms"],
    )
    cur.execute("ROLLBACK TO SAVEPOINT manifest_min")
    fails_block(
        cur,
        [
            ("UPDATE v15.governance_manifest SET manifest_digest = 'bad' WHERE manifest_id = 1", None),
            ("SELECT * FROM v15.v15_effective_ceilings(NULL, NULL)", None),
        ],
        "P1504",
        "corrupt manifest blocks ceilings",
    )


def test_grants(server) -> None:
    worker = connect(server, "v15_worker")
    worker.autocommit = False
    cur = worker.cursor()
    fails(
        cur,
        "SELECT * FROM v15.v15_resolve_config(%s, NULL, 1)",
        (SEED_SCOPE,),
        "42501",
        "worker cannot resolve",
    )
    fails(
        cur,
        "SELECT v15.v15_add_layer(%s, NULL, 0, 'plain', NULL, NULL, NULL, NULL, NULL)",
        (uid(90),),
        "42501",
        "worker cannot add layer",
    )
    worker.close()


def main() -> int:
    server = get_server()
    setup_db()
    conn = connect(server)
    conn.autocommit = False
    cur = conn.cursor()
    test_shape(cur)
    test_seed(cur)
    test_fold(cur)
    test_errors(cur)
    test_jsonb_presence(cur)
    test_freeze(cur)
    test_ceilings(cur)
    conn.rollback()
    conn.close()
    test_grants(server)
    print("[ready] config gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
