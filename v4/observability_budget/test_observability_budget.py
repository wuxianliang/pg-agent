"""W6 observability_budget gates: bounded metrics, fail-closed budget, no SQL routing."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v4.observability_budget.setup_db import DB, main as setup_db
from v4.observability_budget.worker import AgentWorker, ALLOWED_METRIC_KEYS

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
        return item

    fn.state = state  # type: ignore[attr-defined]
    return fn


def start_run(c, question: str, max_steps: int = 5, **budget) -> str:
    with c.cursor() as cur:
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
            cur.execute("UPDATE agent_runs SET " + ", ".join(sets) + " WHERE run_id=%s", args[1:] + [run_id])
        return run_id


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def test_sql_no_routing() -> None:
    print("\n[1] SQL 不按 budget 选 model/provider；无 secret 写入路径")
    sql = (ROOT / "observability_budget.sql").read_text()
    check("无 model routing", not re.search(r"IF .*budget.*THEN.*model", sql, re.I))
    check("无 provider 选择", "openai.model" not in sql and "SET model" not in sql)
    wsrc = (ROOT / "worker.py").read_text()
    check("worker 不写 api_key 进 metrics", "api_key" not in wsrc.split("normalize_metrics")[-1] or "ALLOWED_METRIC_KEYS" in wsrc)
    check("allowlist 不含 secret", "api_key" not in ALLOWED_METRIC_KEYS and "prompt" not in ALLOWED_METRIC_KEYS)


def test_metrics_and_budget(uri) -> None:
    print("\n[2] synthetic usage → budget row")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "budget ok", max_total_tokens=10_000)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="secret-key", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"raw": json.dumps({"thought": "done", "action": None, "final_answer": "ok"}),
                 "metrics": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100, "cost_usd": 0.0004,
                             "api_key": "should-strip", "prompt": "nope"}},
            ]),
        )
        result = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        check("SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        with c.cursor() as cur:
            cur.execute(
                "SELECT meta FROM agent_steps WHERE run_id=%s AND kind='llm' ORDER BY seq",
                (run_id,),
            )
            meta = as_json(cur.fetchone()[0])
            cur.execute(
                "SELECT payload FROM agent_steps WHERE run_id=%s AND kind='budget' ORDER BY seq",
                (run_id,),
            )
            budget = as_json(cur.fetchone()[0])
            cur.execute("SELECT run_budget(%s)", (run_id,))
            rb = as_json(cur.fetchone()[0])
        check("meta 无 api_key/prompt", "api_key" not in meta and "prompt" not in meta, meta)
        check("meta 含 bounded tokens", meta.get("total_tokens") == 100, meta)
        check("budget 行 cumulative=100", budget.get("cumulative_tokens") == 100, budget)
        check("run_budget 相符", rb.get("total_tokens") == 100, rb)
        check("attempts 进入 meta", meta.get("attempts") >= 1, meta)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_exceed_and_missing(uri) -> None:
    print("\n[3] exceed fail-closed；missing usage fail-closed")
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
                {"raw": json.dumps({"thought": "x", "action": None, "final_answer": "should-not"}),
                 "metrics": {"total_tokens": 1}},
            ]),
        )
        result = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            qn = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='tool'", (run_id,)
            )
            tools = cur.fetchone()[0]
            cur.execute(
                "SELECT payload->>'reason' FROM agent_steps WHERE run_id=%s AND kind='budget'",
                (run_id,),
            )
            reason = cur.fetchone()[0]
        check("token exceed → ERROR", st[0] == "ERROR", st)
        check("exceed 不执行 tool", tools == 0, tools)
        check("exceed 不留下下一条 llm 消息", qn == 0, qn)
        check("reason token_exceeded", reason == "token_exceeded", reason)
        check("drain done not ok", result.get("done") and not result.get("ok"), result)
        w.close()

        run_id2 = start_run(c, "missing usage", max_total_tokens=100)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "done", "action": None, "final_answer": "no-metrics"},
            ]),
        )
        w.drain(run_id2, timeout=20)
        st2 = run_state(c, run_id2)
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'reason' FROM agent_steps WHERE run_id=%s AND kind='budget'",
                (run_id2,),
            )
            reason2 = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            qn2 = cur.fetchone()[0]
        check("missing usage ERROR", st2[0] == "ERROR", st2)
        check("reason budget_unavailable", reason2 == "budget_unavailable", reason2)
        check("unknown 不当成 zero 继续跑", qn2 == 0 and st2[2] is None, (qn2, st2))
    finally:
        if w is not None:
            w.close()
        c.close()


def test_retries_not_duplicate(uri) -> None:
    print("\n[4] retry attempts 进 meta，不重复 llm step")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "retry", max_total_tokens=5000)
        fails = {"n": 0}

        def flaky(messages, **kwargs):
            fails["n"] += 1
            if fails["n"] <= 2:
                raise RuntimeError("transient")
            return {
                "raw": json.dumps({"thought": "ok", "action": None, "final_answer": "r"}),
                "metrics": {"total_tokens": 10},
            }

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_retries=3, llm_fn=flaky,
        )
        w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='llm'", (run_id,)
            )
            n = cur.fetchone()[0]
            cur.execute(
                "SELECT meta->>'attempts' FROM agent_steps WHERE run_id=%s AND kind='llm'",
                (run_id,),
            )
            attempts = cur.fetchone()[0]
        check("retry 后 SUCCESS", st[0] == "SUCCESS", st)
        check("只有 1 个 llm step", n == 1, n)
        check("attempts>=3", int(attempts or 0) >= 3, attempts)
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_observability_budget] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_sql_no_routing()
    test_metrics_and_budget(uri)
    test_exceed_and_missing(uri)
    test_retries_not_duplicate(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
