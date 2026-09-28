# v13 长循环 Phase 0 证据（2026-09-28）

Phase 0 文档层已接受。本文不是 stage 验收，不是产品绿。裁决以 `docs/plans/v13-long-loop-plan-2026-09-28.md` 为准。复现以本文内嵌块为准，不依赖 gitignore 文件。`prompt-exports/` 副本只是执行便利，不得 `git add`。调查不提交。此前「候选」以及收尾当时尚未提交，都是历史状态。父已复跑最终证据，退出码 0；本地日志 `prompt-exports/v13-long-loop-p0-parent-verification.log` 不是必读。

## 1. 命令

规范复现：

```text
UV_FROZEN=1 uv run python prompt-exports/v13-long-loop-p0-advance-receipt-probe.py
```

本修订未改探针语义。再次用这条命令重跑，退出码 **0**。外壳回显 `EXIT:0` 不是脚本 stdout。历史裸命令 `uv run python prompt-exports/v13-long-loop-p0-advance-receipt-probe.py` 也曾退出码 0，不把那次输出改标成冻结命令。§4 摘录的 UUID 属于这次冻结重跑；合同字段不随 UUID 变。未调用真实 provider。未跑 stage runner。

清理只 DROP 本次 `created` 的 `agent_v13_longloop_p0_probe`。名字已存在则返回 2，不 DROP。`agent_v13_govern` 缺失不再拒绝：记录 `BASELINE_OBSERVATION skipped` 并继续。存在时才计 sessions/effects/events，且前后不一致则失败。

退出条件仍要求 `ok`、`PROBE_OK True`、`BASELINE_MISSING []`、`BASELINE_EXTRA []`，且没有 `FAIL baseline database set changed`。16 条具名断言谓词未改。

## 2. 角色与 GRANT

脚本在开头对库 `postgres`、连接探针库后再各 emit 一次 `current_user` 与 `rolsuper`，不打印 URI。本次输出见 §4。`v13_goal_stop` 要求 `v13_control_operator()`（`v13/acl/v13_acl.sql:74-86`）。本次两条 ROLE 都是 `postgres` / `rolsuper=True`，所以 stop 通过。生产不得假设超级用户。

GRANT 字面在脚本 `GRANTS`，与 `v13/characterize/setup_db.py:23-31` 相同。它是部署面授权：角色身份走 recall 链时，`score_bound` 的 owner-only ACL 会 42501；SQL 文件内不得写这条 GRANT。README 写加载 seam 不需要它。探针在 `load_stage(govern)` 之后执行它。超级用户三案没有单独证明它必需。产品安装把它列为未决依赖，见计划 §5。5 参 `v13_complete` 传 NULL，只为造前驱。

## 3. 可执行复现块

边界从 `BEGIN PROBE` 到 `END PROBE`。以这块为准。

<!-- BEGIN PROBE -->

```python
"""Phase 0 isolated probe: advance step-5 receipt when should_run is false.

Never drops a database that existed at start. Creates and drops only
agent_v13_longloop_p0_probe. Does not call v13/govern/setup_db.py.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import get_server
from v13.load import load_stage, run_psql

PROBE = "agent_v13_longloop_p0_probe"
BASELINE_DB = "agent_v13_govern"
LOG = Path(__file__).with_suffix(".log")
GRANTS = """
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.tokenize(text,text,text,text,text,integer,text,text)
TO v13_recall, v13_resolve, v13_route;
"""
PROGRESS = {"result_kind": "progress"}
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
CALL = [{"id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}}]


def u():
    return str(uuid.uuid4())


def emit_role(server, db):
    conn = psycopg2.connect(server.get_uri(db))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        user, is_super = cur.fetchone()
        return f"ROLE db={db} current_user={user} rolsuper={is_super}"
    finally:
        conn.close()


def as_obj(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def datnames(server):
    out = run_psql(
        server,
        "postgres",
        "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY 1;",
    )
    names = []
    for line in out.splitlines():
        name = line.strip()
        if not name or name.startswith("-") or name.startswith("(") or name == "datname":
            continue
        names.append(name)
    return names


def counts(server, db):
    sql = """
    SELECT 'sessions', count(*) FROM sessions
    UNION ALL SELECT 'effects', count(*) FROM effects
    UNION ALL SELECT 'events', count(*) FROM events
    ORDER BY 1;
    """
    return run_psql(server, db, sql)


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def open_session(cur):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps({}),)))


def fresh(cur):
    sid = open_session(cur)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": "hello goal"})),
    )
    return sid


def trev(cur, sid):
    return int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))


def harness_request(ltid, index, revision):
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": revision,
        "logical_turn_id": ltid,
        "continuation_index": index,
    }


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(q1(
            cur,
            "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name),
        ))
    return str(q1(
        cur,
        "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request)),
    ))


def settle(cur, eid, result):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence",
        (eid,),
    )
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)),
    )
    return cur.fetchone()[0]


def stop(cur, sid):
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    return cur.fetchone()[0]


def advance(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s",
        (sid,),
    )
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = as_obj(cur.fetchone()[0])
    probe["sid"] = sid
    snap = {
        "snap": probe,
        "envelope": {"sid": sid},
        "remaining": 0,
        "abandon": False,
    }
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


def effect_ids(cur, sid):
    cur.execute(
        "SELECT effect_id::text FROM effects WHERE session_id=%s ORDER BY 1",
        (sid,),
    )
    return [row[0] for row in cur.fetchall()]


def n_material(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent'",
        (sid,),
    ))


def ready_claimed(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s "
        "AND status IN ('ready','claimed','unknown')",
        (sid,),
    ))


def gate(cur, sid):
    return {
        "should_run": q1(cur, "SELECT v13_should_run(%s)", (sid,)),
        "gate": q1(cur, "SELECT v13_should_run_gate(%s)", (sid,)),
    }


def snapshot(cur, sid, pred):
    cur.execute(
        "SELECT type, source_effect_id::text, payload FROM events "
        "WHERE session_id=%s AND type='turn/material_spent' ORDER BY seq",
        (sid,),
    )
    receipts = [
        {"type": t, "source_effect_id": src, "payload": payload}
        for t, src, payload in cur.fetchall()
    ]
    return {
        "word": None,
        "status": q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,)),
        "should_run": gate(cur, sid),
        "effects": effect_ids(cur, sid),
        "ready_claimed_unknown": ready_claimed(cur, sid),
        "material": n_material(cur, sid),
        "receipts": receipts,
        "pred": pred,
    }


def run_case(cur, name, setup):
    sid, pred = setup(cur)
    before = snapshot(cur, sid, pred)
    word = advance(cur, sid)
    after = snapshot(cur, sid, pred)
    after["word"] = word
    new_effects = sorted(set(after["effects"]) - set(before["effects"]))
    return {
        "case": name,
        "before": before,
        "after": after,
        "new_effects": new_effects,
    }


def case_progress(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, PROGRESS)
    stop(cur, sid)
    return sid, eid


def case_finish(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, FINISH)
    stop(cur, sid)
    return sid, eid


def case_spawn(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s "
        "RETURNING attempt_no, fence",
        (eid,),
    )
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps({"text": "ok", "tool_calls": CALL})),
    )
    cur.fetchone()
    stop(cur, sid)
    return sid, eid


def main() -> int:
    lines = []
    ok = False

    def emit(text):
        print(text, flush=True)
        lines.append(text)

    server = get_server()
    before_names = datnames(server)
    emit("BASELINE_DB_COUNT " + str(len(before_names)))
    baseline_present = BASELINE_DB in before_names
    emit("BASELINE_HAS_GOVERN " + str(baseline_present))
    emit("BASELINE_HAS_PROBE " + str(PROBE in before_names))
    emit(emit_role(server, "postgres"))
    if PROBE in before_names:
        emit("REFUSE probe name already exists; not dropping it")
        LOG.write_text("\n".join(lines) + "\n")
        return 2
    before_counts = None
    if baseline_present:
        emit("GOVERN_COUNTS_BEFORE")
        before_counts = counts(server, BASELINE_DB).rstrip()
        emit(before_counts)
    else:
        emit("BASELINE_OBSERVATION skipped; agent_v13_govern absent; continuing")
    created = False
    try:
        run_psql(server, "postgres", f"CREATE DATABASE {PROBE};")
        created = True
        emit("CREATED " + PROBE)
        load_stage(server, PROBE, "govern")
        run_psql(server, PROBE, GRANTS)
        emit("STANNUM_GRANT_EXECUTED after_load product_necessity=unverified_by_this_probe")
        conn = psycopg2.connect(server.get_uri(PROBE))
        conn.autocommit = False
        try:
            cur = conn.cursor()
            emit(emit_role(server, PROBE))
            results = [
                run_case(cur, "progress_stopped", case_progress),
                run_case(cur, "finish_stopped", case_finish),
                run_case(cur, "spawn_calls_stopped", case_spawn),
            ]
            conn.rollback()
        finally:
            conn.close()
        emit("PROBE_JSON")
        emit(json.dumps(results, default=str, indent=2))
        ok = True
        by = {row["case"]: row for row in results}
        progress = by["progress_stopped"]
        finish = by["finish_stopped"]
        spawn = by["spawn_calls_stopped"]
        checks = {
            "progress_should_run_false": progress["before"]["should_run"]["should_run"] is False,
            "progress_gate_goal_stopped": progress["before"]["should_run"]["gate"] == "goal_stopped",
            "progress_word_waiting": progress["after"]["word"] == "waiting",
            "progress_material_plus_1": progress["after"]["material"] == progress["before"]["material"] + 1,
            "progress_zero_new_effects": progress["new_effects"] == [],
            "progress_ready_unchanged": progress["after"]["ready_claimed_unknown"] == 0,
            "progress_receipt_source": any(
                r["source_effect_id"] == progress["before"]["pred"] for r in progress["after"]["receipts"]
            ),
            "finish_should_run_false": finish["before"]["should_run"]["should_run"] is False,
            "finish_word_terminal": finish["after"]["word"] == "terminal",
            "finish_status_completed": finish["after"]["status"] == "completed",
            "finish_material_plus_1": finish["after"]["material"] == finish["before"]["material"] + 1,
            "finish_zero_new_effects": finish["new_effects"] == [],
            "spawn_should_run_false": spawn["before"]["should_run"]["should_run"] is False,
            "spawn_word_waiting": spawn["after"]["word"] == "waiting",
            "spawn_material_unchanged": spawn["after"]["material"] == spawn["before"]["material"],
            "spawn_zero_new_effects": spawn["new_effects"] == [],
        }
        for label, passed in checks.items():
            emit(("PASS " if passed else "FAIL ") + label)
            ok = ok and passed
        emit("PROBE_OK " + str(ok))
    finally:
        if created:
            run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {PROBE} WITH (FORCE);")
            emit("DROPPED_ONLY " + PROBE)
        after_names = datnames(server)
        missing = sorted(set(before_names) - set(after_names))
        extra = sorted(set(after_names) - set(before_names))
        emit("BASELINE_MISSING " + json.dumps(missing))
        emit("BASELINE_EXTRA " + json.dumps(extra))
        if baseline_present:
            emit("GOVERN_COUNTS_AFTER")
            after_counts = counts(server, BASELINE_DB).rstrip()
            emit(after_counts)
            if after_counts != before_counts:
                ok = False
                emit("FAIL govern baseline counts changed")
        else:
            emit("BASELINE_OBSERVATION skipped_after")
        if missing or extra:
            ok = False
            emit("FAIL baseline database set changed")
    LOG.write_text("\n".join(lines) + "\n")
    return 0 if (
        ok
        and "PROBE_OK True" in lines
        and "BASELINE_MISSING []" in lines
        and "BASELINE_EXTRA []" in lines
        and "FAIL baseline database set changed" not in lines
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

<!-- END PROBE -->

harness request 含 `tool`、`params`、`handler=worker:harness_turn`、`tools_revision`、`logical_turn_id`、`continuation_index=0`。claim 用 UPDATE 把 status 设为 `claimed` 并 `RETURNING attempt_no, fence`，再交给 5 参 `v13_complete`。spawn 的 result 是 `{"text":"ok","tool_calls":[{"id":"tc1","name":"spawn_subsession","args":{"task":"one"}}]}`。`text` 非空。advance 传入的 snap 没有 `failed` 键。`context_active_revision` 更新的是 `sessions` 表。`snapshot()` 的返回值不含 probe snap。

## 4. 运行输出摘录

下面不是未经删节的整份 stdout。`[loaded ]` 行和 `v13_probe` 内部字段未逐字贴入。`snapshot()` 本来就没有 `snap` 字段；它重查 gate、计数和收据。合同字段与当次输出一致。`EXIT:0` 是外壳回显。

```text
BASELINE_DB_COUNT 133
BASELINE_HAS_GOVERN True
BASELINE_HAS_PROBE False
ROLE db=postgres current_user=postgres rolsuper=True
GOVERN_COUNTS_BEFORE
 effects  |     1
 events   |    14
 sessions |     7
CREATED agent_v13_longloop_p0_probe
STANNUM_GRANT_EXECUTED after_load product_necessity=unverified_by_this_probe
ROLE db=agent_v13_longloop_p0_probe current_user=postgres rolsuper=True
PASS progress_should_run_false
PASS progress_gate_goal_stopped
PASS progress_word_waiting
PASS progress_material_plus_1
PASS progress_zero_new_effects
PASS progress_ready_unchanged
PASS progress_receipt_source
PASS finish_should_run_false
PASS finish_word_terminal
PASS finish_status_completed
PASS finish_material_plus_1
PASS finish_zero_new_effects
PASS spawn_should_run_false
PASS spawn_word_waiting
PASS spawn_material_unchanged
PASS spawn_zero_new_effects
PROBE_OK True
DROPPED_ONLY agent_v13_longloop_p0_probe
BASELINE_MISSING []
BASELINE_EXTRA []
GOVERN_COUNTS_AFTER
 effects  |     1
 events   |    14
 sessions |     7
EXIT:0
```

格式化后的合同字段，UUID 来自这次冻结命令：

```json
[
  {
    "case": "progress_stopped",
    "before": {"status": "ready", "should_run": false, "gate": "goal_stopped", "material": 0, "receipts": [], "pred": "198aa360-c00a-5a63-870e-6428c2a477ca"},
    "after": {"word": "waiting", "status": "waiting", "should_run": false, "gate": "goal_stopped", "material": 1, "source_effect_id": "198aa360-c00a-5a63-870e-6428c2a477ca"},
    "new_effects": []
  },
  {
    "case": "finish_stopped",
    "before": {"status": "ready", "should_run": false, "gate": "goal_stopped", "material": 0, "pred": "46876363-e0d5-5bd6-8f30-350d8b13a07f"},
    "after": {"word": "terminal", "status": "completed", "should_run": true, "gate": null, "material": 1, "source_effect_id": "46876363-e0d5-5bd6-8f30-350d8b13a07f"},
    "new_effects": []
  },
  {
    "case": "spawn_calls_stopped",
    "before": {"status": "ready", "should_run": false, "gate": "goal_stopped", "material": 0, "pred": "bb5f7721-9e19-58c5-95cd-9f0a3cd3bc7f"},
    "after": {"word": "waiting", "status": "waiting", "should_run": false, "gate": "goal_stopped", "material": 0, "receipts": []},
    "new_effects": []
  }
]
```

第三条 `pred` 是 setup 返回的 llm effect id，不是 `v13_harness_predecessor`。finish 调用后的 `should_run=true` 不是调用前事实。具名检查没有 `spawn_gate_goal_stopped` 或 `spawn_material_before_zero`；这两个字段在上面的 before 里。

## 5. 不证明什么

不证明 quiet、root 配额、explore RAISE 被执行、`resolve/failed`、`duty_cycle=0` 会使 should_run 为假、绑定窗已闭合、产品库已建成、stannum GRANT 对超级用户三案必需、任何 stage 测试已通过。

## 6. 写后 diff

历史基线：收尾前 `git diff --stat -- v13 v13/load.py` 为空；当时 HEAD `e915e92` 落后 origin/main 14。快进 `--ff-only` 后 HEAD 与 origin/main 同为 `9177ab5`。incoming 不含 `uv.lock` 和这两份文档，也没有改 `v13/load.py` 或 stage 1–29 既有 SQL。没有 pull、rebase、stash、reset。`uv.lock` 仍是本地修改。父最终复跑已完成。快进后提交前再次跑同一冻结命令，退出码 0，16 条 PASS；内嵌脚本与执行脚本一致。摘录 UUID 属于更早一次运行，不构成合同。
