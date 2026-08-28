"""W1 kernel_freeze gates: read-only v4 SQL load, HTTP guard, generic apply,
budget / wait / fan-out still work, v5 worker does not import v4.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
V5_ROOT = ROOT.parent
AGENT_ROOT = V5_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v5.kernel_freeze.setup_db import DB, main as setup_db
from v5.kernel_freeze.worker import ALLOWED_METRIC_KEYS, AgentWorker
from v5.load import SQL_LOAD_ORDER

RESULTS: list[tuple[str, str, str]] = []
QUESTION = "demo_sales 表里 South 在 2025-02 的 revenue 是多少？只给数字。"


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


def seed(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS demo_sales")
    cur.execute("""
        CREATE TABLE demo_sales (
            month text NOT NULL, segment text NOT NULL, revenue int NOT NULL)
    """)
    cur.execute("""
        INSERT INTO demo_sales (month, segment, revenue) VALUES
            ('2025-01','North',100),('2025-01','South',200),
            ('2025-02','North',150),('2025-02','South',250)
    """)


def purge(cur) -> None:
    for q in (
        "llm_requests", "llm_requests_dlq",
        "embed_requests", "embed_requests_dlq",
        "sql_heavy_requests", "sql_heavy_requests_dlq",
        "human_inbox", "human_inbox_dlq",
    ):
        cur.execute("SELECT pgmq.purge_queue(%s)", (q,))


def scripted(script: list):
    state = {"n": 0}

    def fn(messages, **kwargs):
        i = min(state["n"], len(script) - 1)
        state["n"] += 1
        item = script[i]
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)

    fn.state = state  # type: ignore[attr-defined]
    return fn


def start_run(c, question: str = QUESTION, max_steps: int = 8, **budget) -> str:
    with c.cursor() as cur:
        seed(cur)
        purge(cur)
        cur.execute("SELECT agent_start(%s, %s)", (question, max_steps))
        run_id = cur.fetchone()[0]
        if budget:
            sets = []
            args = [run_id]
            if "max_total_tokens" in budget:
                sets.append("max_total_tokens=%s")
                args.append(budget["max_total_tokens"])
            if "max_cost_usd" in budget:
                sets.append("max_cost_usd=%s")
                args.append(budget["max_cost_usd"])
            cur.execute(
                "UPDATE agent_runs SET " + ", ".join(sets) + " WHERE run_id=%s",
                args[1:] + [run_id],
            )
        return run_id


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def q_count(c, queue: str) -> int:
    with c.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM pgmq.q_{queue}")
        return cur.fetchone()[0]


def parse_v4_sql_load_order(text: str) -> list[str]:
    start = text.find("SQL_LOAD_ORDER")
    block = text[start:]
    block = block.split("=", 1)[1]
    block = block.split("REFRESH_AFTER", 1)[0]
    rows = re.findall(
        r'(AGENT_ROOT|V4_ROOT)\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"(?:\s*/\s*"([^"]+)")?',
        block,
    )
    out = []
    for root, a, b, c in rows:
        parts = [p for p in (a, b, c) if p]
        if root == "AGENT_ROOT":
            out.append("/".join(parts))
        else:
            out.append("v4/" + "/".join(parts))
    return out


def test_freeze_sources() -> None:
    print("\n[1] read-only v4 paths; no SQL copies; no import v4")
    v4_text = (AGENT_ROOT / "v4" / "load.py").read_text()
    v4_rels = parse_v4_sql_load_order(v4_text)
    v5_rels = [str(p.relative_to(AGENT_ROOT)) for p in SQL_LOAD_ORDER[:12]]
    check("v4 SQL_LOAD_ORDER 解析出 12 条", len(v4_rels) == 12, v4_rels)
    check("v5 前 12 条与 v4 相同", v5_rels == v4_rels, (v5_rels, v4_rels))
    check("kernel_freeze 无 sql 文件", list(ROOT.glob("**/*.sql")) == [])
    wsrc = (ROOT / "worker.py").read_text()
    load_src = (V5_ROOT / "load.py").read_text()
    check("worker 无 import v4", not re.search(r"^\s*(from|import)\s+v4\b", wsrc, re.M), "")
    check("load.py 无 import v4", not re.search(r"^\s*(from|import)\s+v4\b", load_src, re.M), "")
    check("worker 走 apply_queue_result", "apply_queue_result" in wsrc)
    check("worker 不调用 apply_llm_response", "apply_llm_response(" not in wsrc)
    check("allowlist 不含 secret", "api_key" not in ALLOWED_METRIC_KEYS)
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", "v1", "v2", "v3", "v4"],
        cwd=str(AGENT_ROOT),
        capture_output=True,
        text=True,
    )
    staged = [ln for ln in r.stdout.splitlines() if re.match(r"^[MAD]  v[1234]/", ln)]
    check("本测试未 git add v1–v4", staged == [], r.stdout[:200])
    py_text = "\n".join(p.read_text() for p in list(V5_ROOT.glob("**/*.py")))
    check("v5 不 import v1/v2/v3 包", not re.search(r"^\s*(from|import)\s+v[123]\b", py_text, re.M))


def test_http_guard(uri) -> None:
    print("\n[2] SQL HTTP guard + generic apply")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            try:
                cur.execute("SELECT http_call_llm('[]'::jsonb)")
                check("http_call_llm 被禁用", False, "call succeeded")
            except Exception as exc:
                check("http_call_llm 被禁用", "v4 forbids SQL-side model HTTP" in str(exc), exc)
            try:
                cur.execute("SELECT agent_run('should fail')")
                check("agent_run 被禁用", False, "call succeeded")
            except Exception as exc:
                check("agent_run 被禁用", "v4 forbids SQL-side model HTTP" in str(exc), exc)
            try:
                cur.execute(
                    "SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                    ("no_such_queue", 1, "run-x", json.dumps({"raw": "{}"})),
                )
                check("unknown queue 抛错", False, "succeeded")
            except Exception as exc:
                check("unknown queue 抛错", "unknown queue" in str(exc), exc)
    finally:
        c.close()

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


def test_happy_generic_apply(uri) -> None:
    print("\n[3] scripted LLM 经 generic dispatcher 两轮 SUCCESS")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "查表", "action": "execute_sql",
                 "action_input": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
                 "final_answer": None},
                {"thought": "有了", "action": None, "action_input": None, "final_answer": "250"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        check("happy SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("happy answer 250", st[2] == "250", st[2])
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM processed_queue_messages WHERE run_id=%s",
                (run_id,),
            )
            n_proc = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM pgmq.a_llm_requests WHERE message->>'run_id'=%s",
                (run_id,),
            )
            n_arch = cur.fetchone()[0]
        check("processed_queue_messages 记录 apply", n_proc >= 2, n_proc)
        check("archive 发生在 apply 之后", n_arch == 2, n_arch)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_budget(uri) -> None:
    print("\n[4] budget fail-closed")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "too many tokens", max_steps=5, max_total_tokens=50)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"raw": json.dumps({
                    "thought": "tool", "action": "execute_sql",
                    "action_input": "SELECT 1", "final_answer": None,
                }),
                 "metrics": {"total_tokens": 80}},
            ]),
        )
        # process_message expects llm_fn to return dict-with-raw OR a json string.
        # scripted dumps dicts to strings, so wrap:
        inner = w.llm_fn

        def with_metrics(messages, **kwargs):
            item = inner(messages, **kwargs)
            parsed = json.loads(item) if isinstance(item, str) else item
            if isinstance(parsed, dict) and "raw" in parsed:
                return parsed
            return item

        w.llm_fn = with_metrics
        result = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='tool'", (run_id,)
            )
            tools = cur.fetchone()[0]
            cur.execute(
                "SELECT payload->>'reason' FROM agent_steps WHERE run_id=%s AND kind='budget'",
                (run_id,),
            )
            brow = cur.fetchone()
            reason = brow[0] if brow else None
        check("token exceed → ERROR", st[0] == "ERROR", st)
        check("exceed 不执行 tool", tools == 0, tools)
        check("reason token_exceeded", reason == "token_exceeded", reason)
        check("drain done not ok", result.get("done") and not result.get("ok"), result)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_human_wait(uri) -> None:
    print("\n[5] human wait / answer / resume")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "ask a human")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            embed_fn=lambda *a, **k: [0.0],
            llm_fn=scripted([
                {"thought": "ask", "action": "execute_sql",
                 "action_input": "SELECT wb_request_human('what is south revenue?', 'ctx')",
                 "final_answer": None},
                {"thought": "use answer", "action": None, "action_input": None, "final_answer": "250"},
            ]),
        )
        first = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        check("human drain 停在 wait", first.get("waiting") is True, first)
        check("run_state WAITING_HUMAN", st[0] == "WAITING_HUMAN", st)
        with c.cursor() as cur:
            cur.execute("SELECT human_inbox_list()")
            listing = as_json(cur.fetchone()[0])
            reqs = listing.get("requests") or []
            check("human_inbox_list OPEN", listing.get("success") is True and len(reqs) == 1, listing)
            rid = reqs[0]["request_id"]
            cur.execute("SELECT human_answer(%s, %s, %s)", (rid, "250", "tester"))
            ans = as_json(cur.fetchone()[0])
            check("human_answer OPEN 成功", ans.get("success") is True, ans)
        result = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        check("human resume SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_fanout(uri) -> None:
    print("\n[6] parent spawn two children, resume once")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "spawn two")
        parent_fn = scripted([
            {"thought": "spawn", "action": "execute_sql",
             "action_input": (
                 "SELECT wb_spawn_agents("
                 "'[\"child question A\",\"child question B\"]'::jsonb, "
                 "'[\"alpha\",\"beta\"]'::jsonb)"
             ),
             "final_answer": None},
            {"thought": "combine", "action": None, "action_input": None, "final_answer": "A+B"},
        ])

        def routed(messages, **kwargs):
            user = messages[1]["content"] if len(messages) > 1 else ""
            if user.startswith("child question"):
                return json.dumps({
                    "thought": "child", "action": None, "action_input": None,
                    "final_answer": user[-1] + "-done",
                })
            return parent_fn(messages, **kwargs)

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_fn=routed,
        )
        first = w.pump_once()
        st = run_state(c, run_id)
        check("parent waiting after spawn", first.get("waiting") is True, first)
        check("parent WAITING_QUEUE until children done", st[0] == "WAITING_QUEUE", st)
        result = w.drain(run_id, timeout=40)
        st = run_state(c, run_id)
        check("parent SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("parent answer A+B", st[2] == "A+B", st[2])
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_kernel_freeze] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_freeze_sources()
    test_http_guard(uri)
    test_happy_generic_apply(uri)
    test_budget(uri)
    test_human_wait(uri)
    test_fanout(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
