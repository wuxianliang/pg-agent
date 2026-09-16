"""v6 DuckDB 工作台 Streamlit 演示页。

在一个页面里跑通 W9 集成链路：
    invoke_named_llm_tool (PG)  ->  duck_heavy_requests (PGMQ)
    ->  DuckDBWorkerProcessor (库外 DuckDB worker)  ->  apply_queue_result (PG)

用法：
    uv run streamlit run v6/workbench_demo/app.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import get_server  # noqa: E402
from v6.load import load_stage, run_psql  # noqa: E402
from v6.queue_bridge.duckdb_processor import DuckDBWorkerProcessor  # noqa: E402
from v6.source_ingress.duckdb_ingress import PostgresSourceResolver, SourceConfig  # noqa: E402
from v6.budget_observability.duck_budget import DuckBudget  # noqa: E402
from v6.kernel_freeze.worker import AgentWorker  # noqa: E402

DB_DEFAULT = "agent_v6_integration"
SOURCE_ID = "agent_db"
QUEUE = "duck_heavy_requests"

st.set_page_config(page_title="pg-agent v6 · DuckDB 工作台", page_icon="🦆", layout="wide")


# ---------------------------------------------------------------- 基础资源


@st.cache_resource(show_spinner=False)
def pg_uri(db: str) -> str:
    return get_server().get_uri(db)


@st.cache_resource(show_spinner=False)
def pg_conn(db: str):
    conn = psycopg2.connect(pg_uri(db))
    conn.autocommit = True
    return conn


@st.cache_resource(show_spinner=False)
def get_processor(db: str, allowed: tuple[tuple[str, str], ...], worker_id: str) -> DuckDBWorkerProcessor:
    resolver = PostgresSourceResolver([
        SourceConfig(
            source_id=SOURCE_ID,
            uri=pg_uri(db),
            allowed_tables=frozenset(allowed),
            max_rows=100000,
            max_bytes=64 * 1024 * 1024,
        ),
    ])
    return DuckDBWorkerProcessor(pg_uri(db), resolver=resolver, worker_id=worker_id)


def db_exists(db: str) -> bool:
    try:
        conn = psycopg2.connect(pg_uri("postgres"))
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def stack_loaded(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM plugin_bindings WHERE binding_name LIKE 'wb_duck_%'")
            return cur.fetchone()[0] == 7
    except Exception:
        return False


# ---------------------------------------------------------------- 初始化 / 播种


def init_database(db: str) -> None:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {db} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {db};")
    run_psql(server, db, "CREATE EXTENSION IF NOT EXISTS vector;")
    load_stage(server, db, "integration")


SEED_SQL = """
DROP TABLE IF EXISTS public.sales;
DROP TABLE IF EXISTS public.regions;
CREATE TABLE public.sales (
    month text NOT NULL, segment text NOT NULL, product text NOT NULL,
    units int NOT NULL, unit_price numeric(10,2) NOT NULL, revenue numeric(14,2) NOT NULL
);
INSERT INTO public.sales
SELECT to_char(make_date(2026, m, 1), 'YYYY-MM'), seg, prod,
       ((m * 7 + si * 13 + pi * 5) % 40) + 10, price,
       (((m * 7 + si * 13 + pi * 5) % 40) + 10) * price
FROM generate_series(1, 6) AS m
CROSS JOIN (VALUES ('North', 1), ('South', 2), ('East', 3), ('West', 4)) AS s(seg, si)
CROSS JOIN (VALUES ('Widget', 199, 1), ('Gadget', 499, 2), ('Gizmo', 899, 3)) AS p(prod, price, pi);
CREATE TABLE public.regions (segment text PRIMARY KEY, region text NOT NULL, lead text NOT NULL);
INSERT INTO public.regions VALUES
    ('North', '华北', '张伟'), ('South', '华南', '李娜'),
    ('East', '华东', '王强'), ('West', '西南', '赵敏');
"""


def seed_demo_data(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(SEED_SQL)
        cur.execute("SELECT count(*) FROM public.sales")
        return cur.fetchone()[0]


@st.cache_data(ttl=5, show_spinner=False)
def discover_tables(db: str) -> list[str]:
    if not db_exists(db):
        return []
    try:
        conn = pg_conn(db)
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
            )
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


# ---------------------------------------------------------------- run / 会话


def fetch_one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row


def fetch_all(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def start_run(conn, question: str, max_steps: int, mode: str) -> str:
    # 先清空残留的 llm_requests，再建 run（否则会把刚入队的初始请求一起清掉）
    with conn.cursor() as cur:
        cur.execute("SELECT pgmq.purge_queue('llm_requests')")
        cur.execute("SELECT agent_start_session(%s,%s,%s)", (question, max_steps, mode))
        run_id = cur.fetchone()[0]
    return run_id


def run_row(conn, run_id: str):
    return fetch_one(
        conn,
        "SELECT run_id, question, max_steps, session_mode, created_at FROM agent_runs WHERE run_id=%s",
        (run_id,),
    )


def wb_session_row(conn, run_id: str):
    try:
        return fetch_one(
            conn,
            "SELECT status, session_mode, next_op_seq, last_completed_op_seq, worker_id, session_generation "
            "FROM duck_workbench_sessions WHERE run_id=%s",
            (run_id,),
        )
    except Exception:
        return None


def active_artifacts(conn, run_id: str) -> list[str]:
    try:
        rows = fetch_all(
            conn,
            "SELECT artifact_name FROM duck_artifacts WHERE run_id=%s AND artifact_status='ACTIVE' ORDER BY 1",
            (run_id,),
        )
        return [r[0] for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------- 对话（真 LLM agent 循环）


def _extract_json(raw: str) -> dict:
    """和 SQL 侧 parse_llm_output 同口径：剥代码圖栏、取花括号段。"""
    v = (raw or "").strip()
    if v.startswith("```"):
        v = v.strip("`")
        if v[:4].lower().startswith("json"):
            v = v[4:]
    if not v.lstrip().startswith("{"):
        start, end = v.find("{"), v.rfind("}")
        v = v[start:end + 1] if start >= 0 <= end else ""
    try:
        return json.loads(v) if v else {}
    except Exception:
        return {}


def _obs_table(obs: dict, max_rows: int = 8) -> str:
    """把 observation 里的有界结果渲染成 markdown 小表。"""
    cols, data = obs.get("columns"), obs.get("data")
    if not (isinstance(cols, list) and isinstance(data, list) and data):
        return ""
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "---|" * len(cols)
    rows = ["| " + " | ".join(str(x) for x in r) + " |" for r in data[:max_rows]]
    more = f"  \n（共 {len(data)} 行，仅展示前 {min(len(data), max_rows)} 行）" if len(data) > max_rows else ""
    return "\n".join([head, sep, *rows]) + more


def render_steps_md(steps) -> str:
    """把 agent_steps 渲染成一段 markdown 对话气泡内容。"""
    parts: list[str] = []
    for seq, kind, payload in steps:
        payload = payload if isinstance(payload, dict) else {}
        if kind == "llm":
            dec = _extract_json(payload.get("raw") or "")
            if dec.get("thought"):
                parts.append(f"> 🧠 {dec['thought']}")
            if dec.get("action"):
                parts.append(f"🔧 调用 `{dec['action']}`")
                ai = dec.get("action_input")
                if ai is not None:
                    if isinstance(ai, str):
                        try:
                            ai = json.loads(ai)
                        except Exception:
                            pass
                    parts.append("```json\n" + json.dumps(ai, ensure_ascii=False, indent=None) + "\n```")
        elif kind == "tool":
            tool = payload.get("tool") or "execute_sql"
            obs_txt = payload.get("observation") or ""
            try:
                obs = json.loads(obs_txt) if isinstance(obs_txt, str) else (obs_txt or {})
            except Exception:
                obs = {"raw": obs_txt}
            obs = obs if isinstance(obs, dict) else {"raw": str(obs)}
            body = _obs_table(obs)
            if not body:
                inner = obs.get("observation") if isinstance(obs.get("observation"), (dict, list)) else obs
                body = "```json\n" + json.dumps(inner, ensure_ascii=False, default=str)[:1200] + "\n```"
                ok = obs.get("success")
                body = ("✅ 观察：\n" if ok is not False else "⚠️ 观察（失败）：\n") + body
            parts.append(f"📎 `{tool}` 结果：\n{body}")
        elif kind == "wait":
            parts.append(f"⏳ 异步等待 `{payload.get('queue')}` · {payload.get('tool')}（request `{str(payload.get('request_id'))[:8]}…`）")
        elif kind == "final":
            parts.append(f"**✅ 最终回答**\n\n{payload.get('answer')}")
        elif kind == "error":
            parts.append(f"**❌ 出错：{payload.get('message')}**")
    return "\n\n".join(parts) if parts else "_（agent 还没说话）_"


def fetch_steps(conn, run_id: str):
    try:
        return fetch_all(
            conn,
            "SELECT seq, kind, payload FROM agent_steps WHERE run_id=%s ORDER BY seq",
            (run_id,),
        )
    except Exception:
        return []


def chat_drain(uri: str, db: str, proc, run_id: str, api_uri: str, api_key: str, model: str) -> None:
    """后台线程：像常驻 worker 一样持续 pump 四个队列，直到目标 run 结束。"""
    worker = AgentWorker(uri, api_uri=api_uri, api_key=api_key, model=model,
                         duck_processor=proc, db=db, poll=0.15)
    try:
        deadline = time.time() + 300
        res: dict = {}
        while time.time() < deadline:
            r = worker.pump_once()
            if r is None:
                time.sleep(0.15)
                continue
            res = r
            if r.get("run_id") == run_id and (r.get("done") or r.get("dead_lettered")):
                break
        st.session_state["chat_result"] = res or {"done": False, "ok": False, "error": "timeout：300s 内未完成"}
    except Exception as exc:  # noqa: BLE001
        st.session_state["chat_result"] = {"done": True, "ok": False, "error": str(exc)}
    finally:
        # 只关 worker 自己的 PG 连接；共享的 duck_processor / DuckDB 会话不动
        for c in list(worker._run_conns.values()):
            try:
                c.close()
            except Exception:
                pass
        try:
            worker.poll_conn.close()
        except Exception:
            pass


def tab_chat(conn, proc, db: str, llm_cfg: dict) -> None:
    st.markdown("每条提问 = 一个新 agent run。模型自主调用 `wb_duck_*` 工具，"
                "DuckDB 查询在本页内嵌 worker 执行；🧠 是模型思考，🔧 是工具调用，✅ 是最终回答。")
    if not llm_cfg["api_key"]:
        st.warning("未配置 API key（环境变量 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`，或左侧 LLM 面板）。")
    if proc is None:
        st.warning("worker 未就绪：先播种数据，保证白名单非空。")
        return

    for turn in st.session_state.get("chat", []):
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])

    question = st.chat_input("问点什么，例如：分析 South 区域的销售趋势，哪个月收入最高？")
    thread: threading.Thread | None = st.session_state.get("chat_thread")
    if thread is not None and thread.is_alive():
        if question:
            st.toast("上一个 run 还在执行，稍等它完成再发新问题")
        return
    if not question:
        return
    if not llm_cfg["api_key"]:
        st.stop()

    run_id = start_run(conn, question, 20, "temp")
    st.session_state["run_id"] = run_id
    st.session_state.setdefault("chat", []).append({"role": "user", "content": question})
    st.session_state["chat_result"] = None

    thread = threading.Thread(
        target=chat_drain,
        args=(pg_uri(db), db, proc, run_id, llm_cfg["uri"], llm_cfg["api_key"], llm_cfg["model"]),
        daemon=True,
    )
    st.session_state["chat_thread"] = thread
    thread.start()

    with st.chat_message("assistant"):
        holder = st.empty()
        deadline = time.time() + 330
        steps: list = []
        while time.time() < deadline:
            steps = fetch_steps(conn, run_id)
            holder.markdown(render_steps_md(steps))
            if not thread.is_alive():
                break
            time.sleep(1.2)
        res = st.session_state.get("chat_result") or {}
        if not any(k == "final" for _, k, _ in steps) and not any(k == "error" for _, k, _ in steps):
            holder.markdown(render_steps_md(steps) + f"\n\n**⌛ 超时或中断**（{res.get('error', 'worker 结束但没有 final')}）")
        st.session_state["chat"].append({"role": "assistant", "content": render_steps_md(steps)})
    st.rerun()


# ---------------------------------------------------------------- 工具调用全链路


def run_tool_cycle(conn, proc: DuckDBWorkerProcessor, run_id: str, action: str, args: dict[str, Any]) -> dict:
    """执行 invoke -> queue -> worker -> apply 四段，返回带 stages 的记录。"""
    stages: list[tuple[str, Any]] = []

    def record(title: str, payload: Any) -> None:
        stages.append((title, json.loads(json.dumps(payload, default=str, ensure_ascii=False))
                       if isinstance(payload, (dict, list)) else payload))

    with conn.cursor() as cur:
        cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_id,))
        cur.execute("SELECT invoke_named_llm_tool(%s, %s)", (action, json.dumps(args)))
        env = cur.fetchone()[0]
    record("① invoke_named_llm_tool —— PG 侧工具信封", env)

    nested = {}
    if isinstance(env, dict) and env.get("success") and env.get("data"):
        nested = env["data"][0].get(action) or {}
    if not nested.get("defer"):
        return {"action": action, "args": args, "ok": False, "stages": stages,
                "result": nested or env, "ts": datetime.now().strftime("%H:%M:%S")}

    with conn.cursor() as cur:
        cur.execute(f"SELECT msg_id, message FROM pgmq.read('{QUEUE}', 60, 1)")
        row = cur.fetchone()
    if row is None:
        return {"action": action, "args": args, "ok": False, "stages": stages,
                "result": {"success": False, "Type": "NO_QUEUE_MESSAGE", "Phase": "Queue",
                           "Problem": "duck_heavy_requests 中没有消息", "Solution": "重试工具调用。"},
                "ts": datetime.now().strftime("%H:%M:%S")}
    msg_id, message = row
    message = json.loads(message) if isinstance(message, str) else message
    record("② duck_heavy_requests —— PGMQ 消息", message)

    result = proc.process(message)
    record("③ DuckDBWorkerProcessor —— 库外 DuckDB 执行", result)

    with conn.cursor() as cur:
        cur.execute("SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                    (QUEUE, msg_id, run_id, json.dumps(result, default=str)))
        applied = cur.fetchone()[0]
        cur.execute(f"SELECT pgmq.archive('{QUEUE}', %s::bigint)", (msg_id,))
        cur.execute("SELECT pgmq.purge_queue('llm_requests')")
    record("④ apply_queue_result —— 结果写回 PG 元数据", applied)

    return {"action": action, "args": args, "ok": result.get("success") is True,
            "stages": stages, "result": result, "applied": applied,
            "ts": datetime.now().strftime("%H:%M:%S")}


def remember(cycle: dict) -> None:
    hist = st.session_state.setdefault("history", deque(maxlen=12))
    hist.appendleft(cycle)


def render_cycle(cycle: dict) -> None:
    ok = cycle.get("ok")
    res = cycle.get("result") or {}
    if ok:
        head = f"✅ {cycle['ts']} · {cycle['action']} 成功"
    else:
        head = (f"❌ {cycle.get('ts','')} · {cycle.get('action','')} 失败 · "
                f"{res.get('Type', res.get('error', 'ERROR'))}")
    with st.expander(head, expanded=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        c1.caption("参数")
        c1.json(cycle.get("args", {}), expanded=False)
        if res.get("row_count") is not None:
            c2.metric("row_count", res["row_count"])
        if res.get("byte_count") is not None:
            c2.metric("byte_count", res["byte_count"])
        if res.get("truncated"):
            c3.warning("结果被截断（超出预览预算）")
        if not ok and isinstance(res, dict):
            st.error(f"**{res.get('Type', 'ERROR')}** · Phase: {res.get('Phase', '-')}  \n"
                     f"Problem: {res.get('Problem', res.get('error', '-'))}  \n"
                     f"Solution: {res.get('Solution', '-')}")
        if isinstance(res, dict) and res.get("data") and res.get("columns") \
                and isinstance(res["data"], list) and isinstance(res["data"][0], (list, tuple)):
            st.dataframe(pd.DataFrame(res["data"], columns=res["columns"]), use_container_width=True)
        if isinstance(res, dict) and res.get("artifacts"):
            st.json(res["artifacts"], expanded=False)
        if isinstance(res, dict) and res.get("columns") and isinstance(res["columns"], list) \
                and res["columns"] and isinstance(res["columns"][0], dict):
            st.dataframe(pd.DataFrame(res["columns"]), use_container_width=True)
        for title, payload in cycle.get("stages", []):
            with st.expander(title, expanded=False):
                st.json(payload)


# ---------------------------------------------------------------- 页面


def sidebar(db: str) -> tuple[str, DuckDBWorkerProcessor | None, str | None]:
    with st.sidebar:
        st.title("🦆 pg-agent v6")
        st.caption("PostgreSQL-DuckDB 临时工作台 · W9 集成链路演示")

        st.subheader("数据库", divider="grey")
        db = st.text_input("数据库名", value=db, key="db_name")
        exists = db_exists(db)
        if not exists:
            st.warning(f"数据库 `{db}` 不存在")
        conn = None
        if exists:
            try:
                conn = pg_conn(db)
                if stack_loaded(conn):
                    st.success("连接正常 · 7 个 wb_duck_* 工具已注册")
                else:
                    st.warning("连接正常，但 v6 栈未加载")
            except Exception as exc:
                st.warning(f"连接失败：{exc}")

        confirm = st.checkbox("我确认要重建数据库", value=False, key="confirm_reset")
        if st.button("🗑 初始化 / 重置数据库", disabled=not confirm or not db,
                     type="primary" if confirm else "secondary"):
            with st.spinner("重建数据库并加载 21 个 SQL（W1→W9）…"):
                try:
                    init_database(db)
                except Exception as exc:
                    st.error(f"初始化失败：{exc}")
                    st.stop()
            pg_conn.clear()
            get_processor.clear()
            st.session_state.pop("run_id", None)
            discover_tables.clear()
            st.success("初始化完成")
            st.rerun()

        tables = discover_tables(db)
        if conn is not None and tables:
            if st.button(f"🌱 播种演示数据（当前 {len(tables)} 张表）"):
                n = seed_demo_data(conn)
                discover_tables.clear()
                st.toast(f"已播种：sales {n} 行 + regions 4 行")
                st.rerun()

        st.subheader("Worker（库外 DuckDB）", divider="grey")
        worker_id = st.text_input("worker_id", value="v6-ui-worker-1", key="worker_id")
        allowed_tables: tuple[tuple[str, str], ...] = ()
        if conn is not None and tables:
            picked = st.multiselect("agent_db 允许的表（白名单）", tables, default=tables,
                                    key="allowed_tables")
            allowed_tables = tuple(("public", t) for t in picked)
            st.caption("修改白名单会重建 worker；temp DuckDB 会话将按 LOST 处理（fail-closed）。")
        proc = None
        if conn is not None and allowed_tables:
            proc = get_processor(db, allowed_tables, worker_id)

        st.subheader("LLM（对话模式）", divider="grey")
        env_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        api_uri = st.text_input("api_uri", value=os.environ.get("OPENAI_API_URI", "https://api.deepseek.com/v1"), key="llm_uri")
        model = st.text_input("model", value=os.environ.get("OPENAI_MODEL", "deepseek-chat"), key="llm_model")
        api_key = st.text_input("api_key", type="password", value="", key="llm_key",
                                placeholder=("环境变量已检测到，可直接留空" if env_key else "DEEPSEEK_API_KEY 未设置"))
        llm_cfg = {"uri": api_uri, "model": model, "api_key": api_key or env_key}
        if not llm_cfg["api_key"]:
            st.caption("⚠️ 无 API key，对话页签无法调模型")

        run_id = st.session_state.get("run_id")
        st.subheader("Agent Run", divider="grey")
        if run_id and conn is not None:
            row = run_row(conn, run_id)
            if row is None:
                st.session_state.pop("run_id", None)
                st.rerun()
            else:
                _, question, max_steps, mode, created = row
                wbs = wb_session_row(conn, run_id)
                st.markdown(f"`{run_id[:8]}…` · **{mode}** · steps≤{max_steps}")
                st.caption(f"问题：{question}\n\n创建于 {created:%H:%M:%S}")
                if wbs:
                    status, _, next_seq, done_seq, w_owner, generation = wbs
                    badge = {"OPEN": "🟢", "NEW": "⚪", "DEGRADED": "🟠",
                             "LOST": "🔴", "TERMINAL": "⚫"}.get(status, "⚪")
                    st.markdown(f"{badge} workbench **{status}** · op_seq `done {done_seq} / next {next_seq}` · gen {generation}")
                    if status == "LOST":
                        st.error("temp 会话已丢失（worker 崩溃/进程重启）。v6 fail-closed：请新建 run。")
                    if w_owner:
                        st.caption(f"owner worker: {w_owner}")
                col_a, col_b = st.columns(2)
                if col_a.button("🧹 结束 run", use_container_width=True):
                    with conn.cursor() as cur:
                        cur.execute("SELECT cleanup_run_session(%s)", (run_id,))
                        cur.execute("SELECT pgmq.purge_queue('llm_requests')")
                    if proc is not None:
                        try:
                            proc.sessions.close_run(run_id)
                        except Exception:
                            pass
                    st.session_state.pop("run_id", None)
                    st.rerun()
                if col_b.button("💥 模拟 worker 崩溃", use_container_width=True,
                                help="关闭本进程 DuckDB 会话并标记 LOST，验证 fail-closed"):
                    if proc is not None:
                        try:
                            proc.sessions.close_run(run_id, lost=True)
                        except Exception as exc:
                            st.toast(f"close 失败：{exc}")
                    st.rerun()

        with st.expander("➕ 新建 run" if run_id else "➕ 创建 run"):
            with st.form("new_run", border=False):
                q = st.text_input("问题", value="分析 South 区域的销售趋势", key="run_q")
                steps = st.number_input("max_steps", 1, 100, 10, key="run_steps")
                mode = st.selectbox("session_mode", ["temp", "run_schema"], key="run_mode",
                                    help="temp：DuckDB 会话随 worker 存活；run_schema：从 PG 元数据重放")
                if st.form_submit_button("创建", type="primary", use_container_width=True):
                    st.session_state["run_id"] = start_run(conn, q, int(steps), mode)
                    st.rerun()

        if conn is not None and run_id is None:
            rows = fetch_all(conn, "SELECT run_id, question, session_mode, created_at "
                                   "FROM agent_runs ORDER BY created_at DESC LIMIT 15")
            if rows:
                with st.expander(f"切换历史 run（{len(rows)}）"):
                    for rid, q, mode, created in rows:
                        if st.button(f"{created:%m-%d %H:%M} · {mode} · {q[:24]}",
                                     key=f"pick_{rid}", use_container_width=True):
                            st.session_state["run_id"] = rid
                            st.rerun()
        return db, proc, run_id, llm_cfg



def tab_tools(conn, proc: DuckDBWorkerProcessor | None, run_id: str | None) -> None:
    if run_id is None:
        st.info("先在左侧创建一个 agent run。")
        return
    if proc is None:
        st.warning("worker 未就绪：需要数据库里有表并被加入白名单。")
        return

    st.markdown("每次调用走完整四段链路：**PG named tool → PGMQ → 库外 DuckDB worker → PG apply**。")
    artifacts = active_artifacts(conn, run_id)

    presets = st.columns(4)
    if presets[0].button("🎬 一键演示链", use_container_width=True,
                         help="register sales → query south_sales → query south_total → brief"):
        with st.status("执行演示链…", expanded=True) as status:
            steps = [
                ("wb_duck_register", {"p_brief": "读取销售表快照", "p_source_id": SOURCE_ID,
                                      "p_schema_name": "public", "p_table_name": "sales",
                                      "p_view_name": "sales_src"}),
                ("wb_duck_query", {"p_brief": "筛选 South 区域",
                                   "p_view_name": "south_sales",
                                   "p_query": "SELECT month, product, units, revenue FROM sales_src "
                                              "WHERE segment='South'"}),
                ("wb_duck_query", {"p_brief": "按月汇总 South",
                                   "p_view_name": "south_total",
                                   "p_query": "SELECT month, sum(revenue) AS total FROM south_sales GROUP BY month"}),
                ("wb_duck_brief_query", {"p_brief": "预览汇总", "p_view_name": "south_total", "p_limit": 10}),
            ]
            failed = False
            for i, (action, args) in enumerate(steps, 1):
                st.write(f"{i}/4 {action}")
                cycle = run_tool_cycle(conn, proc, run_id, action, args)
                remember(cycle)
                if not cycle["ok"]:
                    failed = True
                    st.error(f"{action} 失败：{(cycle.get('result') or {}).get('Problem')}")
                    break
            status.update(label="演示链完成 ✅" if not failed else "演示链中断 ❌",
                          state="complete" if not failed else "error")
        st.rerun()

    tool = st.selectbox("工具", [
        "wb_duck_register", "wb_duck_query", "wb_duck_brief_query",
        "wb_duck_list", "wb_duck_columns", "wb_duck_show_create", "wb_duck_drop",
    ], key="tool_pick")
    tables = discover_tables(st.session_state.get("db_name", DB_DEFAULT))

    with st.form("tool_form"):
        brief = st.text_input("p_brief（操作目的）", value="查看工作台", key="t_brief")
        args: dict[str, Any] = {"p_brief": brief}
        if tool == "wb_duck_register":
            c1, c2 = st.columns(2)
            args["p_source_id"] = c1.text_input("p_source_id", SOURCE_ID, key="t_source")
            args["p_schema_name"] = c2.text_input("p_schema_name", "public", key="t_schema")
            c3, c4 = st.columns(2)
            options = tables or ["sales"]
            args["p_table_name"] = c3.selectbox("p_table_name", options, key="t_table")
            args["p_view_name"] = c4.text_input("p_view_name", "sales_src", key="t_view")
        elif tool == "wb_duck_query":
            args["p_view_name"] = st.text_input("p_view_name（新视图名）", "my_view", key="t_newview")
            args["p_query"] = st.text_area(
                "p_query（DuckDB 只读 SELECT）", height=120, key="t_query",
                value="SELECT month, sum(revenue) AS total FROM sales_src GROUP BY month ORDER BY month",
            )
        elif tool == "wb_duck_brief_query":
            c1, c2 = st.columns([3, 1])
            opts = artifacts or ["sales_src"]
            args["p_view_name"] = c1.selectbox("p_view_name", opts, key="t_brief_view")
            args["p_limit"] = c2.number_input("p_limit", 1, 50, 20, key="t_limit")
        elif tool in ("wb_duck_list",):
            pass
        else:  # columns / show_create / drop
            opts = artifacts or ["sales_src"]
            args["p_view_name"] = st.selectbox("p_view_name", opts, key="t_meta_view")
        if st.form_submit_button(f"▶ 执行 {tool}", type="primary", use_container_width=True):
            remember(run_tool_cycle(conn, proc, run_id, tool, args))
            st.rerun()

    hist = st.session_state.get("history")
    if hist:
        st.divider()
        st.caption(f"最近 {len(hist)} 次调用（新→旧）")
        for cycle in list(hist)[:3]:
            render_cycle(cycle)


def tab_artifacts(conn, run_id: str | None) -> None:
    if run_id is None:
        st.info("先创建 run。")
        return
    show_dropped = st.toggle("显示已删除", value=False)
    sql = ("SELECT artifact_name, artifact_kind, artifact_status, generation, depends_on, "
           "columns, source_table, updated_at FROM duck_artifacts WHERE run_id=%s")
    if not show_dropped:
        sql += " AND artifact_status='ACTIVE'"
    sql += " ORDER BY created_at"
    try:
        rows = fetch_all(conn, sql, (run_id,))
    except Exception as exc:
        st.error(f"读取失败：{exc}")
        return
    if not rows:
        st.info("此 run 还没有 artifact。到「工具调用」里 register 一个源。")
        return
    data = [{
        "名称": r[0], "类型": r[1], "状态": r[2], "gen": r[3],
        "依赖": ", ".join(r[4]) if r[4] else "-",
        "列数": len(r[5]) if isinstance(r[5], list) else 0,
        "来源表": r[6] or "-", "更新于": r[7].strftime("%H:%M:%S"),
    } for r in rows]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    names = [r[0] for r in rows]
    picked = st.selectbox("查看完整定义", names)
    for r in rows:
        if r[0] == picked:
            st.subheader(f"`{picked}`")
            c1, c2 = st.columns(2)
            c1.json({"kind": r[1], "status": r[2], "generation": r[3],
                     "depends_on": r[4], "source_table": r[6]}, expanded=True)
            if isinstance(r[5], list) and r[5]:
                c2.dataframe(pd.DataFrame(r[5]), hide_index=True, use_container_width=True)


def tab_operations(conn, run_id: str | None) -> None:
    if run_id is None:
        st.info("先创建 run。")
        return
    try:
        rows = fetch_all(
            conn,
            "SELECT op_seq, op_kind, artifact_name, status, worker_id, created_at, started_at, finished_at, error "
            "FROM duck_operations WHERE run_id=%s ORDER BY op_seq DESC LIMIT 60",
            (run_id,),
        )
    except Exception as exc:
        st.error(f"读取失败：{exc}")
        return
    if not rows:
        st.info("此 run 还没有 DuckDB 操作。")
        return
    data = []
    for r in rows:
        seq, kind, name, status, worker, created, started, finished, error = r
        duration = (finished - started).total_seconds() if finished and started else None
        err_type = ""
        if isinstance(error, dict):
            err_type = error.get("Type", error.get("error", ""))
        badge = {"SUCCEEDED": "✅", "QUEUED": "🕓", "RUNNING": "⚙️",
                 "FAILED": "❌", "DLQ": "☠️", "REPLAYED": "♻️"}.get(status, "")
        data.append({"seq": seq, "操作": kind, "artifact": name or "-", "状态": f"{badge} {status}",
                     "worker": worker or "-", "耗时s": f"{duration:.3f}" if duration is not None else "-",
                     "创建于": created.strftime("%H:%M:%S"), "错误": err_type})
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)


def tab_observability(conn, run_id: str | None) -> None:
    c1, c2, c3 = st.columns(3)
    for queue, col in ((QUEUE, c1), ("llm_requests", c2), (f"{QUEUE}_dlq", c3)):
        try:
            row = fetch_one(conn, f"SELECT queue_depth FROM pgmq.metrics('{queue}')")
            col.metric(f"pgmq:{queue}", row[0] if row else 0)
        except Exception:
            col.metric(f"pgmq:{queue}", "-")
    st.divider()
    b = DuckBudget()
    st.markdown("**DuckBudget 预算（worker 硬上限）**")
    st.table(pd.DataFrame([
        {"预算": "preview_rows", "值": b.preview_rows, "说明": "query 结果预览行数"},
        {"预算": "brief_rows", "值": b.brief_rows, "说明": "brief_query 默认行数"},
        {"预算": "max_brief_rows", "值": b.max_brief_rows, "说明": "brief_query 上限"},
        {"预算": "query_chars", "值": b.query_chars, "说明": "SQL 字符上限"},
        {"预算": "timeout_ms", "值": b.timeout_ms, "说明": "单查询超时"},
        {"预算": "memory_limit", "值": b.memory_limit, "说明": "DuckDB 内存上限"},
        {"预算": "max_result_bytes", "值": b.max_result_bytes, "说明": "结果字节上限"},
        {"预算": "source_rows", "值": b.source_rows, "说明": "快照行数上限"},
        {"预算": "source_bytes", "值": b.source_bytes, "说明": "快照字节上限"},
    ], columns=["预算", "值", "说明"]).set_index("预算"))
    if run_id:
        st.divider()
        st.markdown("**操作状态分布**")
        try:
            rows = fetch_all(conn, "SELECT status, count(*) FROM duck_operations WHERE run_id=%s GROUP BY 1 ORDER BY 1", (run_id,))
            if rows:
                st.bar_chart(pd.DataFrame(rows, columns=["status", "count"]).set_index("status"))
            else:
                st.caption("此 run 暂无操作。")
        except Exception as exc:
            st.caption(f"不可用：{exc}")


def main() -> None:
    db, proc, run_id, llm_cfg = sidebar(st.session_state.get("db_name", DB_DEFAULT))
    conn = pg_conn(db) if db_exists(db) else None

    st.title("🦆 pg-agent v6 · DuckDB 工作台")
    st.caption("PostgreSQL 管状态/队列/元数据 · DuckDB 在库外 worker 里做分析 · 本页同时扮演模型与 worker")
    if conn is None:
        st.warning(f"数据库 `{db}` 尚未初始化。在左侧勾选确认后点「初始化 / 重置数据库」，然后播种演示数据、创建 run。")
        return

    tab0, tab1, tab2, tab3, tab4 = st.tabs(["💬 对话", "🛠 工具调用", "📦 Artifacts", "🧾 Operations", "📈 队列与预算"])
    with tab0:
        tab_chat(conn, proc, db, llm_cfg)
    with tab1:
        tab_tools(conn, proc, run_id)
    with tab2:
        tab_artifacts(conn, run_id)
    with tab3:
        tab_operations(conn, run_id)
    with tab4:
        tab_observability(conn, run_id)


main()
