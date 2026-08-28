"""W2 prompt_taxonomy gates: prompt_slot + prompt_mutation; failed refresh atomic."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v5.prompt_taxonomy.setup_db import DB, main as setup_db

RESULTS: list[tuple[str, str, str]] = []

SLOT_OK = r'''
CREATE FUNCTION probe_slot_ok(p_run_id text, p_config jsonb) RETURNS jsonb
LANGUAGE sql STABLE AS $$ SELECT '{"success":true,"messages":[]}'::jsonb $$;
COMMENT ON FUNCTION probe_slot_ok(text, jsonb) IS $c$
{"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"probe_slot_ok","description":"ok stored part","component_types":["role","task"],"source":"stored","generation":"if_missing","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
$c$;
'''


def check(name: str, cond, detail: str = "") -> None:
    RESULTS.append((name, "pass" if cond else "fail", str(detail)[:240]))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  | {detail}" if detail != "" else ""))


def conn(uri: str):
    c = psycopg2.connect(uri)
    c.autocommit = True
    return c


def snapshot_registry(c) -> tuple:
    with c.cursor() as cur:
        cur.execute(
            "SELECT plugin_name, metadata::text FROM plugin_packages ORDER BY plugin_name"
        )
        pkgs = cur.fetchall()
        cur.execute(
            "SELECT binding_type, binding_name, plugin_name, queue_name, queue_kind, "
            "fn::text, metadata::text FROM plugin_bindings "
            "ORDER BY binding_type, binding_name"
        )
        binds = cur.fetchall()
    return pkgs, binds


def test_apply_untouched() -> None:
    print("\n[1] apply_queue_result 未改；overlay 不含 kind 分支")
    overlay = (ROOT / "prompt_taxonomy.sql").read_text()
    check(
        "overlay 不替换 apply_queue_result",
        "CREATE OR REPLACE FUNCTION apply_queue_result" not in overlay,
    )
    tax = (AGENT_ROOT / "v4" / "plugin_taxonomy" / "plugin_taxonomy.sql").read_text()
    body_m = re.search(
        r"CREATE OR REPLACE FUNCTION apply_queue_result\s*\(.*?\$\$\s*(.*?)\$\$;",
        tax,
        re.S | re.I,
    )
    body = body_m.group(1) if body_m else ""
    kind_branch = re.search(
        r"IF\s+.*kind\s*=\s*'?(llm|embed|sql_heavy|human_inbox)",
        body,
        re.I,
    )
    check("apply_queue_result 无 queue-kind 分支", kind_branch is None, kind_branch)


def test_refresh(uri) -> None:
    print("\n[2] prompt_slot / prompt_mutation 与失败原子性")
    c = conn(uri)
    probes: list[str] = []
    try:
        before = snapshot_registry(c)

        def exec_ok(sql: str) -> None:
            with c.cursor() as cur:
                cur.execute(sql)

        def refresh_raises(label: str, sql_setup: str, drop_sql: str, needle: str) -> None:
            exec_ok(sql_setup)
            probes.append(drop_sql)
            try:
                with c.cursor() as cur:
                    cur.execute("SELECT refresh_plugins()")
                check(label, False, "refresh succeeded")
            except Exception as exc:
                check(label, needle in str(exc), exc)
            after = snapshot_registry(c)
            check(label + " 后 registry 不变", after == before, (len(after[1]), len(before[1])))
            exec_ok(drop_sql)
            probes.remove(drop_sql)

        refresh_raises(
            "拒绝 live+if_missing",
            """
            CREATE FUNCTION probe_live_missing(p_run_id text, p_config jsonb) RETURNS jsonb
            LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_live_missing(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"probe_live_missing","description":"bad","component_types":["tools"],"source":"live","generation":"if_missing","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
            $c$;
            """,
            "DROP FUNCTION probe_live_missing(text, jsonb);",
            "source=live 要求 generation=never",
        )
        refresh_raises(
            "拒绝 prompt_slot 混 llm_tool",
            """
            CREATE FUNCTION probe_mixed(p_run_id text, p_config jsonb) RETURNS jsonb
            LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_mixed(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"probe_mixed","description":"x","component_types":["role"],"source":"stored","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"},"llm_tool":{"name":"probe_mixed","description":"x","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            """,
            "DROP FUNCTION probe_mixed(text, jsonb);",
            "不能同时声明",
        )
        refresh_raises(
            "拒绝非法 component_types",
            """
            CREATE FUNCTION probe_bad_comp(p_run_id text, p_config jsonb) RETURNS jsonb
            LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_bad_comp(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"probe_bad_comp","description":"x","component_types":["role","nope"],"source":"stored","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
            $c$;
            """,
            "DROP FUNCTION probe_bad_comp(text, jsonb);",
            "component_types 非法",
        )
        refresh_raises(
            "拒绝 VOLATILE retriever",
            """
            CREATE FUNCTION probe_vol(p_run_id text, p_config jsonb) RETURNS jsonb
            LANGUAGE plpgsql VOLATILE AS $$ BEGIN RETURN '{}'::jsonb; END $$;
            COMMENT ON FUNCTION probe_vol(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"probe_vol","description":"x","component_types":["role"],"source":"stored","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
            $c$;
            """,
            "DROP FUNCTION probe_vol(text, jsonb);",
            "STABLE 或 IMMUTABLE",
        )
        refresh_raises(
            "拒绝 prompt_slot 错误签名",
            """
            CREATE FUNCTION probe_sig(p_x text) RETURNS jsonb
            LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_sig(text) IS $c$
            {"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"probe_sig","description":"x","component_types":["role"],"source":"stored","generation":"never","args":{"p_x":"text"},"returns":"jsonb"}}
            $c$;
            """,
            "DROP FUNCTION probe_sig(text);",
            "(text, jsonb)",
        )

        exec_ok(SLOT_OK)
        probes.append("DROP FUNCTION probe_slot_ok(text, jsonb);")
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
            cur.execute(
                "SELECT count(*) FROM plugin_bindings "
                "WHERE binding_type='prompt_slot' AND binding_name='probe_slot_ok'"
            )
            n = cur.fetchone()[0]
        check("合法 prompt_slot 能 refresh", n == 1, n)
        exec_ok("DROP FUNCTION probe_slot_ok(text, jsonb);")
        probes.remove("DROP FUNCTION probe_slot_ok(text, jsonb);")
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
        check("DROP slot 后恢复生产 registry", snapshot_registry(c) == before)

        exec_ok("""
            CREATE FUNCTION probe_store(p_slot_key text, p_value jsonb) RETURNS jsonb
            LANGUAGE sql AS $$ SELECT '{"success":true}'::jsonb $$;
            COMMENT ON FUNCTION probe_store(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_probe"},"llm_tool":{"name":"probe_store","description":"store part","args":{"p_slot_key":"text","p_value":"jsonb"},"returns":"jsonb","session_scope":"run_connection","capability":"prompt_mutation"}}
            $c$;
        """)
        probes.append("DROP FUNCTION probe_store(text, jsonb);")
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
            cur.execute(
                "SELECT metadata->'llm_tool'->>'capability' FROM plugin_bindings "
                "WHERE binding_name='probe_store'"
            )
            cap = cur.fetchone()[0]
        check("prompt_mutation 被接受", cap == "prompt_mutation", cap)
        exec_ok("DROP FUNCTION probe_store(text, jsonb);")
        probes.remove("DROP FUNCTION probe_store(text, jsonb);")
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
        check("DROP mutation tool 后恢复", snapshot_registry(c) == before)
    finally:
        for drop in list(probes):
            try:
                with c.cursor() as cur:
                    cur.execute(drop)
            except Exception:
                pass
        try:
            with c.cursor() as cur:
                cur.execute("SELECT refresh_plugins()")
        except Exception:
            pass
        c.close()


def main() -> int:
    print("[test_prompt_taxonomy] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_apply_untouched()
    test_refresh(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
