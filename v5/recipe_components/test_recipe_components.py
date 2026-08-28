"""W3 recipe_components gates: XML compile, retrievers, run pin."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v5.recipe_components.setup_db import DB, main as setup_db

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    RESULTS.append((name, "pass" if cond else "fail", str(detail)[:240]))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  | {detail}" if detail != "" else ""))


def conn(uri: str):
    c = psycopg2.connect(uri)
    c.autocommit = True
    return c


def as_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def compile_xml(cur, name: str, version: int, xml: str, activate: bool = False):
    cur.execute(
        "SELECT compile_prompt_recipe(%s, %s, xmlparse(document %s), %s)",
        (name, version, xml, activate),
    )
    return cur.fetchone()[0]


def test_seed_and_retrievers(uri) -> None:
    print("\n[1] seeded agent_system + retrievers")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT version FROM prompt_recipes WHERE recipe_name='agent_system' AND active"
            )
            ver = cur.fetchone()[0]
            check("active agent_system v1", ver == 1, ver)
            cur.execute(
                "SELECT position, slot_key, component_type, retriever_name, required "
                "FROM prompt_slots WHERE recipe_name='agent_system' AND recipe_version=1 "
                "ORDER BY position"
            )
            slots = cur.fetchall()
            keys = [r[1] for r in slots]
            comps = [r[2] for r in slots]
            check("slot order role..history",
                  comps == ["role", "task", "example", "output_format", "tools", "question", "history"],
                  comps)
            check("positions 10*ordinal", [r[0] for r in slots] == [10, 20, 30, 40, 50, 60, 70], slots)
            check("example optional", slots[2][4] is False)
            cur.execute(
                "SELECT slot_key FROM prompt_parts WHERE recipe_name='agent_system' AND recipe_version=1 "
                "ORDER BY slot_key"
            )
            parts = [r[0] for r in cur.fetchall()]
            check("no live part rows", "tools" not in parts and "question" not in parts and "history" not in parts, parts)
            check("stored role/task/example/output",
                  set(parts) >= {"role", "task", "example_1", "output_format"}, parts)
            cur.execute(
                "SELECT binding_name FROM plugin_bindings WHERE binding_type='prompt_slot' ORDER BY 1"
            )
            binds = [r[0] for r in cur.fetchall()]
            check("four retrievers registered",
                  set(binds) >= {"prompt_stored_part", "prompt_live_tools",
                                 "prompt_live_question", "prompt_live_history"},
                  binds)
            cur.execute("SELECT agent_start(%s, %s)", ("hello pin", 3))
            run_id = cur.fetchone()[0]
            cur.execute(
                "SELECT prompt_recipe_name, prompt_recipe_version FROM agent_runs WHERE run_id=%s",
                (run_id,),
            )
            pin = cur.fetchone()
            check("agent_start pins agent_system v1", pin == ("agent_system", 1), pin)
            cur.execute(
                "SELECT prompt_stored_part(%s, %s::jsonb)",
                (run_id, json.dumps({"slot_key": "role"})),
            )
            stored = as_json(cur.fetchone()[0])
            check("stored role system message",
                  stored.get("success") and stored["messages"][0]["role"] == "system",
                  stored)
            cur.execute("SELECT prompt_live_question(%s, '{}'::jsonb)", (run_id,))
            q = as_json(cur.fetchone()[0])
            check("live question", q.get("success") and q["messages"][0]["content"] == "hello pin", q)
            cur.execute("SELECT prompt_live_history(%s, '{}'::jsonb)", (run_id,))
            h = as_json(cur.fetchone()[0])
            check("empty history", h.get("success") and h["messages"] == [], h)
            cur.execute("SELECT prompt_live_tools(%s, '{}'::jsonb)", (run_id,))
            t = as_json(cur.fetchone()[0])
            check("live tools", t.get("success") and "execute_sql" in t["messages"][0]["content"], t)
            cur.execute(
                "SELECT prompt_stored_part(%s, %s::jsonb)",
                (run_id, json.dumps({"slot_key": "missing_slot"})),
            )
            miss = as_json(cur.fetchone()[0])
            check("missing part envelope", miss.get("Type") == "PROMPT_PART_MISSING", miss)
    finally:
        c.close()


def test_compile_rejects(uri) -> None:
    print("\n[2] compile rejects")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            def raises(label, xml, needle):
                try:
                    compile_xml(cur, "probe_bad", 1, xml, False)
                    check(label, False, "compiled")
                except Exception as exc:
                    check(label, needle.lower() in str(exc).lower(), exc)
                    cur.execute("SELECT count(*) FROM prompt_recipes WHERE recipe_name='probe_bad'")
                    n = cur.fetchone()[0]
                    check(label + " 回滚", n == 0, n)

            raises("unknown tag", "<poml><role>x</role><nope/></poml>", "unknown tag")
            raises("duplicate role", "<poml><role>a</role><role>b</role><tools/><question/><history/></poml>", "duplicate")
            raises("js {{", "<poml><role>{{foo}}</role><task>t</task><output-format>o</output-format><tools/><question/><history/></poml>", "unsupported")
            raises("src=", '<poml><role>r</role><task>t</task><output-format src="x">o</output-format><tools/><question/><history/></poml>', "unsupported")
            raises("include", "<poml><include/><role>r</role><task>t</task><output-format>o</output-format><tools/><question/><history/></poml>", "unsupported")
            raises("empty required", "<poml><role></role><task>t</task><output-format>o</output-format><tools/><question/><history/></poml>", "empty required")
            raises("bad example child", "<poml><role>r</role><task>t</task><example><system>x</system></example><output-format>o</output-format><tools/><question/><history/></poml>", "invalid example")
    finally:
        c.close()


def test_version_pin(uri) -> None:
    print("\n[3] new version does not unpin old run")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT agent_start(%s, %s)", ("pin me", 3))
            run_id = cur.fetchone()[0]
            xml = """<poml>
  <role>role v2</role>
  <task>task v2</task>
  <output-format>fmt v2</output-format>
  <tools/>
  <question/>
  <history/>
</poml>"""
            compile_xml(cur, "agent_system", 2, xml, True)
            cur.execute(
                "SELECT prompt_recipe_version FROM agent_runs WHERE run_id=%s", (run_id,)
            )
            pinned = cur.fetchone()[0]
            check("old run stays v1", pinned == 1, pinned)
            cur.execute("SELECT agent_start(%s, %s)", ("new run", 3))
            run2 = cur.fetchone()[0]
            cur.execute(
                "SELECT prompt_recipe_version FROM agent_runs WHERE run_id=%s", (run2,)
            )
            v2 = cur.fetchone()[0]
            check("new run pins v2", v2 == 2, v2)
            cur.execute(
                "SELECT prompt_stored_part(%s, %s::jsonb)->>'success'",
                (run_id, json.dumps({"slot_key": "role"})),
            )
            check("v1 run still retrieves v1 role", cur.fetchone()[0] == "true")
            # restore active v1 for later stages sharing this DB only in this test DB
            cur.execute("UPDATE prompt_recipes SET active=false WHERE recipe_name='agent_system'")
            cur.execute(
                "UPDATE prompt_recipes SET active=true WHERE recipe_name='agent_system' AND version=1"
            )
    finally:
        c.close()


def test_retrievers_no_http() -> None:
    print("\n[4] retrievers 无网络 / 无任意 SQL")
    sql = (ROOT / "prompt_recipe.sql").read_text()
    check("无 http_call_llm", "http_call_llm" not in sql)
    check("无 pg_net", "pg_net" not in sql)
    check("stored 不调 render_plugin_tools",
          "render_plugin_tools" not in sql.split("prompt_stored_part")[1].split("prompt_live_tools")[0])


def main() -> int:
    print("[test_recipe_components] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_seed_and_retrievers(uri)
    test_compile_rejects(uri)
    test_version_pin(uri)
    test_retrievers_no_http()
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
