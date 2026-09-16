# v9 context_early 实现规格(实现组唯一契约)

日期:2026-09-15。状态:FROZEN for implementation。本文是 v9 全部文件的精确契约。
实现必须逐字遵守;与 v6 惯例冲突时以本文为准,与 v6 惯例不冲突处照抄 v6。

## 0. 定位与边界

v9 = "早起上下文"(context_early):任务创建时即投机构建 context pack;
源变更(其他任务落地)通过 commit 通知精确标脏受影响切片并增量刷新;
任务启动前由 gate 判定新鲜度(fresh / sync_refresh / drift_delta)。

- 基于 v6 代码基线(继承 v3–v6 的 21 个 SQL 文件,按路径只读加载,零修改)。
- 队列:PGMQ `ctx_heavy_requests` + `ctx_heavy_requests_dlq`,queue kind `ctx_heavy`。
- Worker:纯 Python(库外),轮询队列、按白名单快照读源表、产切片、调
  继承的 `apply_queue_result(p_queue_name, p_msg_id, p_run_id, p_result)` 分发到 `apply_ctx_result`。
- 任务锚点 = `agent_runs.run_id`(parked run:有 run 行、零 step,不 enqueue LLM)。
- 与 docs/designs/v10-raw.md(ContextPipe 装配管线构想)无关联;那是未开工的
  另一设计。本 v9 是其命名检查(v10-raw L320)通过后的独立实现。

## 1. 目录与 gate

```
v9/
  __init__.py
  README.md                    (F 负责:gate 表 + 运行命令 + 与 v10-raw.md 关系声明)
  load.py                      (A)
  kernel_freeze/  __init__.py setup_db.py test_kernel_freeze.py        (A) W1
  ctx_schema/     __init__.py setup_db.py ctx_schema.sql test_ctx_schema.py (B) W2
  ctx_queue/      __init__.py setup_db.py ctx_queue.sql test_ctx_queue.py   (C) W3
  ctx_lifecycle/  __init__.py setup_db.py ctx_lifecycle.sql
                  test_ctx_build.py test_ctx_staleness.py
                  test_ctx_refresh.py test_ctx_gate.py                 (D) W4–W7
  ctx_worker/     __init__.py worker.py test_ctx_worker.py             (E) W8
  integration/    __init__.py setup_db.py test_v9.py                   (F) W9
```

运行命令(仓库根 /Users/wxl/Projects/pg-agent,全部 `uv run python ...`,退出码 0=通过):

```
uv run python v9/kernel_freeze/test_kernel_freeze.py   # W1
uv run python v9/ctx_schema/test_ctx_schema.py         # W2
uv run python v9/ctx_queue/test_ctx_queue.py           # W3
uv run python v9/ctx_lifecycle/test_ctx_build.py       # W4
uv run python v9/ctx_lifecycle/test_ctx_staleness.py   # W5
uv run python v9/ctx_lifecycle/test_ctx_refresh.py     # W6
uv run python v9/ctx_lifecycle/test_ctx_gate.py        # W7
uv run python v9/ctx_worker/test_ctx_worker.py         # W8
uv run python v9/integration/test_v9.py                # W9
```

数据库:`agent_v9_kernel_freeze` / `agent_v9_ctx_schema` / `agent_v9_ctx_queue` /
`agent_v9_ctx_lifecycle` / `agent_v9_ctx_worker` / `agent_v9_integration`。
setup_db.py 模板照抄 v6/queue_bridge/setup_db.py:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v9.load import load_stage, run_psql

DB = 'agent_v9_<stage>'

def main() -> int:
    s = get_server()
    run_psql(s, 'postgres', f'DROP DATABASE IF EXISTS {DB} WITH (FORCE);')
    run_psql(s, 'postgres', f'CREATE DATABASE {DB};')
    run_psql(s, DB, 'CREATE EXTENSION IF NOT EXISTS vector;')
    load_stage(s, DB, '<stage>')
    print('[ready]', DB)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
```

测试模板照抄 v6 惯例:模块级 `check(label, cond, detail='')`(打印 [PASS]/[FAIL],
失败 raise AssertionError);`main() -> int` 第一个 check 重跑
`from v9.<stage>.setup_db import DB, main as setup_db; check('setup', setup_db() == 0)`;
连接 `psycopg2.connect(get_server().get_uri(DB))`,`c.autocommit = True`;
结尾 `if __name__ == '__main__': raise SystemExit(main())`。

## 2. v9/load.py(A 负责)

照抄 v6/load.py 的全部机制,差异仅:

- `V9_ROOT`/`AGENT_ROOT` 命名对 v9;`SQL_LOAD_ORDER` 前 21 项 = v6 的
  SQL_LOAD_ORDER 原样(绝对路径,指向 v3/v4/v5/v6 文件,只读),后接 3 项:
  22. `v9/ctx_schema/ctx_schema.sql`
  23. `v9/ctx_queue/ctx_queue.sql`
  24. `v9/ctx_lifecycle/ctx_lifecycle.sql`
- `STAGE_THROUGH = {'kernel_freeze': 21, 'ctx_schema': 22, 'ctx_queue': 23,
  'ctx_lifecycle': 24, 'ctx_worker': 24, 'integration': 24}`
- `REFRESH_AFTER`:v6 的集合原样 + v9/ctx_queue/ctx_queue.sql 的路径
  (它注册 plugin_ctx_queue 的 COMMENT)。
- 禁止 `import v6`/`from v6`/`import v5`/`from v5`/`import v4`/`from v4`
  (W1 正则检查文件文本)。run_psql/load_stage/psql_has_row 逻辑照抄 v6。

## 3. ctx_schema.sql(B 负责;文件头注释 `-- v9 W2: context pack state`)

```sql
CREATE TABLE IF NOT EXISTS ctx_sources (
    source_id   text PRIMARY KEY,
    repo_path   text NOT NULL DEFAULT 'default',
    schema_name text NOT NULL,
    table_name  text NOT NULL,
    max_rows    integer NOT NULL DEFAULT 1000 CHECK (max_rows BETWEEN 1 AND 100000),
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repo_heads (
    repo_path   text PRIMARY KEY,
    head_commit text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS context_commits (
    repo_path  text NOT NULL,
    commit_id  text NOT NULL,
    seq        bigint GENERATED ALWAYS AS IDENTITY,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_path, commit_id)
);
CREATE INDEX IF NOT EXISTS ctx_commits_seq_idx ON context_commits (repo_path, seq);

CREATE TABLE IF NOT EXISTS context_commit_files (
    repo_path  text NOT NULL,
    commit_id  text NOT NULL,
    dep_uri    text NOT NULL,
    PRIMARY KEY (repo_path, commit_id, dep_uri)
);

CREATE TABLE IF NOT EXISTS context_packs (
    pack_id        text PRIMARY KEY,
    task_run_id    text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    repo_path      text NOT NULL,
    status         text NOT NULL DEFAULT 'BUILDING'
                   CHECK (status IN ('BUILDING','FRESH','STALE','REFRESHING','FAILED','RETIRED')),
    base_commit    text NOT NULL DEFAULT 'INIT',
    generation     integer NOT NULL DEFAULT 0 CHECK (generation >= 0),
    next_op_seq    bigint NOT NULL DEFAULT 1 CHECK (next_op_seq > 0),
    last_completed_op_seq bigint NOT NULL DEFAULT 0 CHECK (last_completed_op_seq >= 0),
    pending_refresh boolean NOT NULL DEFAULT false,
    token_count    integer,
    worker_id      text,
    last_error     jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_run_id)
);

CREATE TABLE IF NOT EXISTS context_slices (
    pack_id       text NOT NULL REFERENCES context_packs(pack_id) ON DELETE CASCADE,
    slice_id      text NOT NULL,
    seq           integer NOT NULL CHECK (seq > 0),
    kind          text NOT NULL CHECK (kind IN ('source_excerpt','summary','prompt_part')),
    dep_uri       text NOT NULL,
    title         text,
    body          text NOT NULL,
    content_hash  text NOT NULL,
    generation    integer NOT NULL DEFAULT 0,
    stale         boolean NOT NULL DEFAULT false,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_id, slice_id)
);
CREATE INDEX IF NOT EXISTS ctx_slices_stale_idx ON context_slices (pack_id) WHERE stale;

CREATE TABLE IF NOT EXISTS slice_dependencies (
    pack_id        text NOT NULL,
    slice_id       text NOT NULL,
    dep_uri        text NOT NULL,
    built_at_commit text NOT NULL,
    PRIMARY KEY (pack_id, slice_id, dep_uri)
);
CREATE INDEX IF NOT EXISTS slice_dep_uri_idx ON slice_dependencies (dep_uri);

CREATE TABLE IF NOT EXISTS context_refresh_log (
    pack_id        text NOT NULL,
    seq            bigint GENERATED ALWAYS AS IDENTITY,
    trigger_kind   text NOT NULL CHECK (trigger_kind IN ('build','run_completed','git_hook','manual','start_gate')),
    trigger_ref    text,
    dirty_slices   text[] NOT NULL DEFAULT '{}',
    rebuilt_slices text[] NOT NULL DEFAULT '{}',
    base_from      text,
    base_to        text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_id, seq)
);

CREATE TABLE IF NOT EXISTS ctx_operations (
    request_id     text PRIMARY KEY,
    pack_id        text NOT NULL REFERENCES context_packs(pack_id) ON DELETE CASCADE,
    op_kind        text NOT NULL CHECK (op_kind IN ('build','refresh')),
    op_seq         bigint NOT NULL CHECK (op_seq > 0),
    status         text NOT NULL DEFAULT 'QUEUED'
                   CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','DLQ')),
    built_at_commit text,
    worker_id      text,
    result_summary jsonb,
    error          jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    started_at     timestamptz,
    finished_at    timestamptz,
    UNIQUE (pack_id, op_seq)
);
CREATE INDEX IF NOT EXISTS ctx_ops_pack_idx ON ctx_operations (pack_id, op_seq);
CREATE INDEX IF NOT EXISTS ctx_ops_open_idx ON ctx_operations (pack_id, status)
    WHERE status IN ('QUEUED','RUNNING');
```

## 4. ctx_queue.sql(C 负责;文件头 `-- v9 W3 overlay: adds ctx_heavy; queue bridge + apply`)

四部分,顺序固定:

1. **refresh_plugins 覆盖**:逐字复制 v6/queue_bridge/duck_queue.sql 第 1–345 行的
   `CREATE OR REPLACE FUNCTION refresh_plugins()`,唯一功能差异:
   `v_legal_kind text[] := ARRAY['llm','embed','sql_heavy','human_inbox','duck_heavy','ctx_heavy'];`
   (追加 ctx_heavy)。其余(校验、plugin/llm_tool/queue_handler/prompt_slot 规则、
   TRUNCATE+重插)原样。文件头注释说明这是 v9 overlay,不修改 v4/v5/v6 文件。

2. **PGMQ 队列**(照抄 v6 的 DO 块模式):
```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'ctx_heavy_requests') THEN
        PERFORM pgmq.create('ctx_heavy_requests');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'ctx_heavy_requests_dlq') THEN
        PERFORM pgmq.create('ctx_heavy_requests_dlq');
    END IF;
END $$;
```

3. **apply_ctx_result(p_run_id text, p_result jsonb) RETURNS jsonb
   LANGUAGE plpgsql VOLATILE** —— 语义逐步:

   1. `v_request := p_result->>'request_id'`;空 → EXCEPTION 'ctx result missing request_id'。
   2. `SELECT * INTO v_op FROM ctx_operations WHERE request_id = v_request FOR UPDATE;`
      NOT FOUND → EXCEPTION 'unknown ctx operation: %'。
   3. 身份校验:pack 的 `task_run_id` 必须 `IS NOT DISTINCT FROM p_run_id`,且
      `COALESCE((p_result->>'op_seq')::bigint, v_op.op_seq) = v_op.op_seq`,否则
      EXCEPTION 'ctx operation identity conflict'。
   4. `IF v_op.status IN ('SUCCEEDED','FAILED','DLQ') THEN RETURN
      jsonb_build_object('done',false,'ok',true,'replayed',true,'run_id',p_run_id,
      'request_id',v_request); END IF;`
   5. 顺序门:`PERFORM 1 FROM context_packs WHERE pack_id = v_op.pack_id
      AND last_completed_op_seq = v_op.op_seq - 1 FOR UPDATE;`
      NOT FOUND → EXCEPTION 'ctx operation out of order: %'(v_op.op_seq)。
   6. `IF v_op.status NOT IN ('QUEUED','RUNNING') THEN RETURN replayed 包; END IF;`

   成功分支 `COALESCE((p_result->>'success')::boolean, false)` 为 true:
   - `v_built := p_result->>'base_commit'`;NULL/空 → EXCEPTION 'ctx result missing base_commit'。
   - 逐切片 upsert(p_result->'slices' 数组,元素含 slice_id/seq/kind/dep_uri/title/
     body/content_hash/deps 数组,deps 缺省 `[dep_uri]`):
     ```sql
     INSERT INTO context_slices(pack_id,slice_id,seq,kind,dep_uri,title,body,
                                content_hash,generation,stale,updated_at)
     VALUES(v_pack, s->>'slice_id', (s->>'seq')::int, COALESCE(s->>'kind','source_excerpt'),
            s->>'dep_uri', s->>'title', s->>'body', s->>'content_hash',
            v_gen + 1, false, now())
     ON CONFLICT (pack_id, slice_id) DO UPDATE SET
       seq=EXCLUDED.seq, kind=EXCLUDED.kind, dep_uri=EXCLUDED.dep_uri,
       title=EXCLUDED.title, body=EXCLUDED.body, content_hash=EXCLUDED.content_hash,
       generation=EXCLUDED.generation, stale=false, updated_at=now();
     ```
     并重建该切片依赖:`DELETE FROM slice_dependencies WHERE pack_id=$1 AND slice_id=$2`
     后插入每个 dep(自带 built_at_commit=v_built)。
   - `IF v_op.op_kind = 'build' THEN DELETE FROM context_slices WHERE pack_id=v_pack
     AND slice_id NOT IN (payload 切片集合); END IF`(build 为全量替换)。
   - pack 更新(一个 UPDATE):
     ```sql
     UPDATE context_packs SET
       base_commit = v_built,
       generation  = generation + 1,
       last_completed_op_seq = v_op.op_seq,
       token_count = (p_result->>'token_count')::int,
       worker_id   = p_result->>'worker_id',
       last_error  = NULL,
       updated_at  = now(),
       status      = CASE WHEN EXISTS (
             SELECT 1 FROM repo_heads h WHERE h.repo_path = context_packs.repo_path
               AND h.head_commit <> v_built)
           THEN 'STALE' ELSE 'FRESH' END
     WHERE pack_id = v_pack;
     ```
   - 尾巴消费:`SELECT pending_refresh INTO v_pending FROM context_packs WHERE pack_id=v_pack;`
     若 v_pending 且无 QUEUED/RUNNING 操作 → 复位 `pending_refresh=false` 并入队新
     refresh(调 §5 的 _ctx_enqueue_op;注意循环依赖:ctx_queue.sql 在 ctx_lifecycle.sql
     之前加载,_ctx_enqueue_op 尚不存在 → **解法**:apply 里不用动态调用,而是内联
     完整入队逻辑(与 _ctx_enqueue_op 相同的 6 步),保证 ctx_queue.sql 自包含)。
   - `INSERT INTO context_refresh_log(pack_id, trigger_kind, trigger_ref, dirty_slices,
     rebuilt_slices, base_from, base_to)` 值:trigger_kind 取
     `COALESCE(p_result->>'trigger_kind', v_op.op_kind)` 但必须命中 CHECK 集合,
     否则回退 'manual';dirty_slices = 刷新前已 stale 的切片 id 数组(更新前抓取);
     rebuilt_slices = payload 切片 id 数组;base_from = 更新前 pack.base_commit
     (更新前抓取);base_to = v_built。
   - `UPDATE ctx_operations SET status='SUCCEEDED', result_summary=p_result,
     worker_id=p_result->>'worker_id', finished_at=now() WHERE request_id=v_request;`
   - RETURN `{'done',false,'ok',true,'request_id',v_request,'pack_id',v_pack,
     'generation',v_gen+1}`。

   失败分支(success false):
   - `UPDATE ctx_operations SET status='FAILED', error=COALESCE(p_result->'error',
     p_result), finished_at=now() WHERE request_id=v_request;`
   - `UPDATE context_packs SET status='FAILED', last_completed_op_seq=v_op.op_seq,
     last_error=COALESCE(p_result->'error',p_result), updated_at=now()
     WHERE pack_id=v_pack;`
   - RETURN `{'done',true,'ok',false,'run_id',p_run_id,'request_id',v_request,'error','ctx_op_failed'}`。

4. **COMMENT 注册**(照抄 v6 格式):
```sql
COMMENT ON FUNCTION apply_ctx_result(text, jsonb) IS $v9$
{"plugin":{"name":"plugin_ctx_queue"},"queue_handler":{"queue_name":"ctx_heavy_requests","queue_kind":"ctx_heavy","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v9$;
```

## 5. ctx_lifecycle.sql(D 负责;文件头 `-- v9 W4-W7: pack lifecycle`)

辅助函数与公共函数,全部 SECURITY INVOKER:

**`ctx_current_head(p_repo text) RETURNS text LANGUAGE sql STABLE`**:
`SELECT head_commit FROM repo_heads WHERE repo_path = p_repo` 无行返回 NULL
(调用方 COALESCE 'INIT')。

**`_ctx_enqueue_op(p_pack_id text, p_op_kind text, p_trigger text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE`**(内联版供 lifecycle 用;ctx_queue.sql
apply 里的尾巴消费用相同逻辑的独立拷贝,二者可以共存):
1. `SELECT status, next_op_seq, task_run_id, repo_path INTO ... FROM context_packs
   WHERE pack_id = p_pack_id FOR UPDATE;` NOT FOUND → 错误包
   `{'success',false,'Type','CTX_PACK_ERROR','Problem',...}`(仿 _duck_tool_error
   形状:`_ctx_error(p_problem, p_solution)` 辅助函数先定义)。
2. status IN ('RETIRED','FAILED') → 错误包。
3. `v_seq := next_op_seq; UPDATE context_packs SET next_op_seq = next_op_seq + 1,
   status = CASE WHEN status='FRESH' THEN 'REFRESHING' WHEN status='BUILDING'
   THEN 'BUILDING' ELSE status END, updated_at=now() WHERE pack_id=...`
   (注意:REFRESHING 只从 FRESH 进入;STALE 保持 STALE)。
4. `v_req := gen_random_uuid()::text;`
   `INSERT INTO ctx_operations(request_id, pack_id, op_kind, op_seq, status,
   built_at_commit) VALUES(v_req, p_pack_id, p_op_kind, v_seq, 'QUEUED',
   COALESCE(ctx_current_head(repo),'INIT'));`
5. `v_msg := pgmq.send('ctx_heavy_requests', jsonb_build_object(
   'request_id',v_req,'pack_id',p_pack_id,'task_run_id',v_task_run,'op_kind',p_op_kind,
   'op_seq',v_seq,'repo_path',v_repo,'trigger',p_trigger));`
6. RETURN `{'success',true,'request_id',v_req,'op_seq',v_seq,'msg_id',v_msg}`。

**`ctx_create_task(p_question text) RETURNS text LANGUAGE plpgsql VOLATILE`**:
`INSERT INTO agent_runs(run_id, question, max_steps) VALUES(
 gen_random_uuid()::text, p_question, 10) RETURNING run_id;`(parked,不 enqueue LLM)。

**`ctx_ensure_pack(p_task_run_id text, p_repo_path text DEFAULT 'default')
RETURNS jsonb LANGUAGE plpgsql VOLATILE`**:
1. run 不存在 → 错误包。
2. 已有 pack(含 RETIRED)→ RETURN `{'success',true,'pack_id',...,'status',...,
   'replayed',true}`(不新建 op)。
3. `INSERT INTO context_packs(pack_id, task_run_id, repo_path, base_commit)
   VALUES(gen_random_uuid()::text, p_task_run_id, p_repo_path,
   COALESCE(ctx_current_head(p_repo_path),'INIT'));`
4. RETURN `_ctx_enqueue_op(v_pack,'build','ensure')` 并附 pack_id。

**`ctx_on_commit(p_repo_path text, p_new_commit text, p_changed_uris text[],
p_trigger_kind text DEFAULT 'git_hook') RETURNS jsonb LANGUAGE plpgsql VOLATILE`**:
1. `INSERT INTO context_commits(repo_path, commit_id) VALUES(...) ON CONFLICT DO NOTHING;`
   `INSERT INTO context_commit_files ... SELECT unnest(p_changed_uris) ON CONFLICT DO NOTHING;`
2. repo_heads upsert(`INSERT ... ON CONFLICT (repo_path) DO UPDATE SET
   head_commit=EXCLUDED.head_commit, updated_at=now()`)。
3. 精确标脏(更新前抓 dirty 列表):
   ```sql
   WITH marked AS (
     UPDATE context_slices s SET stale=true, updated_at=now()
     FROM slice_dependencies d
     WHERE d.pack_id=s.pack_id AND d.slice_id=s.slice_id
       AND d.dep_uri = ANY(p_changed_uris) AND s.stale=false
     RETURNING s.pack_id, s.slice_id)
   SELECT array_agg(DISTINCT pack_id), ... 
   ```
   实现:先 `SELECT DISTINCT s.pack_id, s.slice_id ... WHERE dep_uri=ANY(...) AND
   s.stale=false` 抓 dirty 明细到变量,再执行 UPDATE。
4. 对每个受影响 pack(状态非 RETIRED/FAILED):`status='STALE'`;若无
   QUEUED/RUNNING 的 op(ctx_operations 索引 ctx_ops_open_idx)→ `_ctx_enqueue_op(
   pack,'refresh', p_new_commit)`;否则 `pending_refresh=true`。
5. RETURN `{'success',true,'commit',p_new_commit,'marked_slices',dirty明细数组,
   'affected_packs',pack数组}`。
幂等:重复同 commit → ON CONFLICT DO NOTHING 后标脏条件 s.stale=false 自然空转,
head 相同,不重复入队(已有 QUEUED op 时)。

**`ctx_gate(p_task_run_id text, p_sync_threshold int DEFAULT 3)
RETURNS jsonb LANGUAGE plpgsql VOLATILE`**:
1. pack := 非 RETIRED 的 pack(UNIQUE 保证至多一行;RETIRED → `{'success',false,
   'Type','CTX_PACK_RETIRED'...}`;无 → `{'success',false,'Type','CTX_PACK_NOT_FOUND'...}`)。
2. `v_head := COALESCE(ctx_current_head(repo),'INIT');`
   base_commit = v_head → RETURN `{'success',true,'fresh',true,'action','none',
   'pack_id',...,'generation',...,'base_commit',...,'head',v_head,'drift','[]'::jsonb}`。
3. changed_uris := context_commit_files 属于 (base_seq, head_seq] 区间的 commit
   的 dep_uri 集合(base 无行[INIT]→ 全部文件):
   ```sql
   SELECT array_agg(DISTINCT f.dep_uri)
     FROM context_commit_files f
     JOIN context_commits c ON c.repo_path=f.repo_path AND c.commit_id=f.commit_id
    WHERE f.repo_path = v_repo
      AND c.seq > COALESCE((SELECT seq FROM context_commits
                            WHERE repo_path=v_repo AND commit_id=v_base), 0)
      AND c.seq <= (SELECT seq FROM context_commits
                    WHERE repo_path=v_repo AND commit_id=v_head);
   ```
4. dirty_slices := pack 中 `stale=true OR dep_uri = ANY(changed_uris)` 的
   (slice_id, dep_uri) 列表。
5. count <= p_sync_threshold → `{'success',true,'fresh',false,'action','sync_refresh',
   'dirty_slices',jsonb数组,'changed_uris',...,'base_commit','head'}`;
   否则 → `{'success',true,'fresh',false,'action','drift_delta','drift',jsonb数组
   ({commit,dep_uri} 对,来自步骤3的 join 明细),'dirty_count',n,...}`。

**`ctx_retire_pack(p_task_run_id text) RETURNS jsonb`**:pack.status='RETIRED',
updated_at=now();无 pack → 错误包。

## 6. worker.py(E 负责;文件头注释说明 v9-local,不 import v6)

```python
"""v9 ctx_heavy worker: poll PGMQ, snapshot ctx_sources, apply results."""
import argparse, hashlib, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg2
from psycopg2.extras import RealDictCursor
from server import get_server

DB = 'agent_v9_ctx_worker'
QUEUE = 'ctx_heavy_requests'
DLQ = 'ctx_heavy_requests_dlq'
VT_SECONDS = 180
MAX_READ_CT = 5
IDENT_RE = r'^[a-z_][a-z0-9_]*$'
```

类 `CtxWorker`:
- `__init__(self, uri, *, db, worker_id='v9-ctx-1', vt=VT_SECONDS,
  max_read_ct=MAX_READ_CT, poll=0.2, crash_after_read=0)`;`self.poll_conn`
  autocommit + RealDictCursor。crash_after_read:读消息后计数递减,归零时
  `os._exit(9)`(集成测试模拟崩溃)。
- `read_one()`:`SELECT msg_id, read_ct, message FROM pgmq.read(%s, %s, 1)`
  (QUEUE, vt);无行返回 None。
- `dead_letter(msg_id, payload, reason)`:`pgmq.send(DLQ, ...)` + `pgmq.archive`;
  若 payload 可取 request_id → `UPDATE ctx_operations SET status='DLQ',
  error=json, finished_at=now() WHERE request_id=%s AND status IN ('QUEUED','RUNNING')`。
- `_snapshot_source(cur, source) -> dict`:`SELECT * FROM <schema>.<table>
  LIMIT max_rows`(标识符先正则校验后 psycopg2.sql.Identifier 拼接);body =
  `json.dumps(rows, default=str, ensure_ascii=False)`;slice =
  `{slice_id: f'src_{source_id}', seq, kind:'source_excerpt',
   dep_uri: f'src:{source_id}', title: f'{schema}.{table}', body,
   content_hash: md5(body), deps:[f'src:{source_id}']}`;
  token_count := len(body)//4。
- `build_result(msg) -> dict`:payload 取 request_id/pack_id/op_kind/op_seq/
  repo_path/task_run_id;
  - `SELECT status FROM ctx_operations WHERE request_id=%s` 终态 → 返回
    `{'skip': True, 'request_id': ...}`(apply 已被别人做过,直接归档);
  - claim:`UPDATE ctx_operations SET status='RUNNING', worker_id=%s,
    started_at=now() WHERE request_id=%s AND status='QUEUED'`;rowcount=0 且
    现状态非 RUNNING → dead_letter/跳过;非 RUNNING 归档返回。
  - `v_built := SELECT COALESCE(head_commit,'INIT') FROM repo_heads WHERE
    repo_path=%s`(无行 'INIT')—— 读取在建基线。
  - build:遍历 `SELECT * FROM ctx_sources WHERE repo_path=%s AND enabled
    ORDER BY source_id`,逐源 `_snapshot_source`,切片 seq 从 1 递增。
  - refresh:`SELECT DISTINCT dep_uri FROM context_slices WHERE pack_id=%s AND
    stale`;dep_uri 形如 `src:<source_id>` → 查对应 ctx_sources 重建这些切片
    (保留原 seq:`SELECT slice_id, seq FROM context_slices WHERE pack_id AND stale`);
    无 stale 切片 → 空 slices(空刷新,仅推进 base_commit)。
  - 读源前再取一次 head 作为 base_commit(与 claim 后一致)。
  - RETURN result envelope:
    `{request_id, op_seq, success:true, run_id: task_run_id, worker_id,
      base_commit: v_built, trigger_kind: 'build'|'run_completed',
      token_count: sum, slices: [...]}`。
- `process_one()` → read_one;无消息返回 None;payload 缺关键字段(request_id/
  pack_id/op_kind/op_seq/repo_path/task_run_id 任一缺失)或 read_ct>max_read_ct
  → dead_letter 返回 dlq 摘要;否则 build_result;skip → `pgmq.archive` 返回摘要;
  正常 → **单事务 apply**(仿 v6 handle_row:新连接,autocommit off):
  `SELECT apply_queue_result(%s, %s, %s, %s::jsonb)` + `SELECT pgmq.archive(%s, %s)`
  → commit;异常 → rollback + dead_letter + 返回错误摘要。
- `pump_once()`:process_one 一次,返回其结果或 None。
- `main()`(模块级,worker 入口):argparse `--db` 默认 env `PG_AGENT_DB` 否则
  `agent_v9_integration`,`--worker-id` env `PG_AGENT_WORKER_ID` 默认 'v9-ctx-1',
  `--poll`;`CtxWorker(get_server().get_uri(args.db), db=args.db, ...)` 循环
  pump_once + sleep。`if __name__ == '__main__': raise SystemExit(main() or 0)`。

## 7. 各测试的必测断言(最小集,可加不可减)

**W1 kernel_freeze**(照抄 v6 W1 精神):
- load.py 文本不含 `import v6`/`from v6`/`import v5`/`from v5`/`import v4`/`from v4`(正则);
- SQL_LOAD_ORDER 前 21 项与硬编码期望列表逐项相等(测试内嵌 21 个路径字面量);
- 全部 24 项存在;kernel_freeze/ 下零 .sql;
- setup 后:`SELECT count(*) FROM plugin_bindings` > 0;
  pgmq.meta 含 llm_requests 与 duck_heavy_requests;`agent_runs` 可插入
  (INSERT 一行 parked run 再 DELETE)。

**W2 ctx_schema**:
- 每张表在 information_schema 有全部期望列(抽查关键列:context_packs.
  last_completed_op_seq/pending_refresh;ctx_operations.request_id/status;
  slice_dependencies.built_at_commit);
- CHECK 生效:context_packs 插非法 status 报错;context_slices 非法 kind 报错;
- UNIQUE(task_run_id) 生效(需先插 agent_runs 两行同 run → 第二个 pack 拒绝);
- slice_dep_uri_idx 存在(pg_indexes)。

**W3 ctx_queue**:
- setup(含 refresh_plugins())后 plugin_bindings 有
  `queue_name='ctx_heavy_requests'` 的 queue_handler 行,fn 指 apply_ctx_result;
- pgmq.meta 含 ctx_heavy_requests 与 _dlq;
- apply_queue_result('ctx_heavy_requests', 999999, 'nonexistent', '{}'::jsonb)
  → 在 processed_queue_messages 插入后分发到 apply_ctx_result 抛
  unknown ctx operation(psycopg2 捕获断言错误文本)——同时证明分发链通。

**W4 test_ctx_build**:
- ctx_create_task → run_id 非空,agent_runs 有行且 agent_steps 为 0;
- ctx_ensure_pack → success true;pack BUILDING、base 'INIT'、next_op_seq=2;
  ctx_operations 一行 QUEUED op_seq=1;pgmq.read 拿到 msg,核对 payload 字段;
- 幂等:再调 ctx_ensure_pack → 同 pack_id,replayed=true,ops 仍 1 条,
  队列无第二条(再 read 一次为空,注意先 archive 第一条);
- 手工构建 build 结果(2 切片,base 'INIT')→ `apply_queue_result(QUEUE, msg_id,
  run_id, result)` → pack FRESH、generation=1、last_completed_op_seq=1、
  2 切片 + 依赖行;refresh_log 一行 trigger 'build';
- 重放:同 msg_id 再 apply → replayed=true 且切片数不变;
  直接 `SELECT apply_ctx_result(run_id, result)` 再调 → replayed 包;
- 乱序:构造 op_seq=2 的伪造结果直接 apply → 异常 'out of order'。

**W5 test_ctx_staleness**:
- 建任务+pack+手工 apply build(两源切片 src:orders、src:users,base c0:
  先 ctx_on_commit('r','c0',ARRAY[]) 造头再 build,使 base_commit='c0');
- ctx_on_commit('r','c1',ARRAY['src:orders']) → 恰好 orders 切片 stale=true、
  users 仍 false;pack STALE;context_commits 有 c1;repo_heads.head='c1';
  refresh op 入队(op_seq=2);
- 再 on_commit('r','c2',ARRAY['src:orders']) → 无新 op(已有 QUEUED refresh),
  pack.pending_refresh=true,orders 仍 stale(不重复标);
- 无关变更 on_commit('r','c3',ARRAY['src:nothing']) → 两切片状态不变。

**W6 test_ctx_refresh**:
- 延续 W5 状态(测试内自己重建到该状态);手工构造 refresh 结果(重建 orders
  切片新 body/hash,users 不在 slices 里)→ apply_queue_result →
  generation=2;orders 更新且 stale=false;**users 的 content_hash 不变**;
  base_commit='c1';refresh_log 一行 rebuilt=['src_orders'];
- 尾巴消费场景:pack 处于 pending_refresh=true 且无在飞 op(测试直接 UPDATE
  构造)→ 调 apply_ctx_result(空刷新成功结果,base 取当前 head)→ apply 后
  pack 状态 FRESH 且 pending_refresh=false 且**自动入队了下一条 refresh op**
  (next_op_seq 前进、ctx_operations 多一行 QUEUED)——注意:空刷新 base=head
  时状态 FRESH,但 pending 逻辑仍要求入队;若 base<head 则 STALE + 入队。
  测试断言:apply 返回后 ctx_operations 存在 QUEUED refresh(op_seq=前+1)。

**W7 test_ctx_gate**:
- 重建"新鲜"状态(base=head)→ gate → fresh=true action=none;
- on_commit 触碰 1 个已依赖 uri → gate → fresh=false action=sync_refresh,
  dirty_slices 含该切片;
- 再触碰使 dirty 数超过 p_sync_threshold=1 调用 gate → action=drift_delta,
  drift 数组含 {commit,dep_uri} 项;
- RETIRED pack → success=false Type=CTX_PACK_RETIRED。

**W8 test_ctx_worker**:
- setup(库 agent_v9_ctx_worker)后:建 fixture 表 public.ctx_fixture_orders
  (2 行)+ ctx_sources 白名单;ctx_create_task+ensure_pack;
  `CtxWorker(uri, db=DB)` pump_once → pack FRESH,切片 body 是 fixture 行的
  JSON 且 content_hash=md5(body),deps 正确,generation=1;
- UPDATE fixture 数据 + on_commit → pump_once(refresh)→ 切片 body 反映新数据,
  generation=2(核心语义:上下文跟踪源变更);
- 投毒消息(手工 pgmq.send 缺 request_id)→ pump_once → DLQ 有消息、原队列
  归档、ctx_operations 无悬挂;
- read_ct 超限:pgmq.send 合法 payload 后反复 pgmq.read(小 vt=1, sleep 略过
  vt)累计 read_ct>5 → pump_once → DLQ。

**W9 test_v9.py**(integration,库 agent_v9_integration):
1. 全链路:fixture 表 + source → task → ensure → worker build → gate fresh;
2. 源变更 → on_commit → gate sync_refresh → worker pump → gate fresh,
   切片含新数据;
3. 多源大漂移 → gate drift_delta;
4. **崩溃重放**:crash_after_read=1 的 worker 实例 pump(读到消息后 os._exit(9),
   用 subprocess 或 try/except SystemExit… 实现:直接在本进程构造带
   crash_after_read=1 的 worker 调 pump_once,os._exit 会杀测试进程——改为
   raise RuntimeError 模拟崩溃,除非 os._exit;测试用 crash_after_read 并以
   pytest-style 子进程不现实,所以 worker 的崩溃实现为 `raise WorkerCrash`
   异常,main 循环不捕获;集成测试捕获它,然后用 vt=1 的 pgmq.read 等 vt 过期
   再读同一条消息,第二个正常 worker pump_once → apply 恰好一次
   (processed_queue_messages 计数=1,切片无重复);
5. ctx_retire_pack → ensure_pack replayed(RETIRED),gate 报 RETIRED;
6. 结束打印 [PASS] 汇总,返回 0。

WorkerCrash:worker.py 定义 `class WorkerCrash(RuntimeError)`;
crash_after_read>0 时 read_one 返回后 `self._crash_counter -= 1;
if ==0: raise WorkerCrash('simulated crash after read')`。
(os._exit 太狠,会杀测试进程——用异常模拟,语义相同:消息未归档、未 apply。)

## 8. README.md(F 负责)

包含:一句话定位(early context packs)、gate 表(W1–W9 如上)、运行命令(§1)、
边界(继承 v3–v6 只读、PGMQ ctx_heavy、任务=parked run、worker 库外)、
"与 docs/designs/v10-raw.md 的关系"一节(该文档是未实施的 ContextPipe 装配管线
设计;本 v9 按用户指令实现 context_early,命名已对照 v1–v7 检查无冲突)、
当前验证结果表(先留空,由主会话在 gate 全过后填)。

## 9. 全局纪律

- 不修改 v1–v6、pgembed、pyproject、server.py 任何文件;只新建 v9/ 与本规格。
- 所有 SQL 文件幂等可重放(CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE)。
- 所有函数 SECURITY INVOKER;错误包形状统一
  `{'success':false,'Type':..., 'Problem':..., 'Solution':...}`。
- 每个测试可独立重复运行(先 setup 重建库)。
- gate 顺序 W1→W9,前一 gate 不过不进下一个(主会话负责执行)。
