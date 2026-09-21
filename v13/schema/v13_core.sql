-- v13 core (DP1 M1): log plane (ch1) + effect ledger (ch2) + decision
-- plane (ch4) minimal slices + tools minimal slice + policy carrier.
-- Discipline transplanted from v12 (see per-object comments). Nothing
-- here loads v12 SQL; v12 is the upstream reference only.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS typesafe;
CREATE EXTENSION IF NOT EXISTS pgmq;
SELECT pgmq.create('v13_work');

-- === log plane (ch1; append-only trigger from v12_schema.sql:38-47) ===
CREATE TABLE sessions (
  session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status      text NOT NULL DEFAULT 'ready' CHECK (status IN
              ('ready','waiting','blocked_unknown','completed','failed','cancelled')),
              -- blocked_unknown 注预留(turn 4,P2):教程 ch1 词表原样保留;
              -- DP1 无生产者(unknown 墙落在 effect 级+① 阻塞),生产者归
              -- ch12 显式 resolve 面
  next_seq    bigint NOT NULL DEFAULT 0,        -- 行锁内自增的 seq 分配器(ch1.2)
  turn_no     int  NOT NULL DEFAULT 0,          -- 生命周期 turn 计数(留缝,见 §3.6 #3)
  route_policy_name    text NOT NULL DEFAULT 'default',   -- ch1 route_policy 拆两列(§3.6 #2)
  route_policy_version int NOT NULL DEFAULT 1,
  parent_session_id uuid REFERENCES sessions,   -- fork 留缝(ch14/DP8)
  parent_cutoff_seq bigint,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (
  session_id uuid NOT NULL REFERENCES sessions (session_id),
  seq        bigint NOT NULL CHECK (seq >= 0),
  event_id   uuid NOT NULL DEFAULT gen_random_uuid(),
  type       text NOT NULL,          -- 开放词表(ch1.3);本 DP 使用:
                                     -- user/message, turn/route, turn/end,
                                     -- tool/result, llm/message, judge/answered,
                                     -- resolve/failed, effect_done, cancel/*
  turn_no    int,
  payload    jsonb NOT NULL,
  payload_hash text NOT NULL,
  source_effect_id uuid,             -- 溯源锚点(ch1.3);无 FK(建序),gate 断言
  at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, seq),
  UNIQUE (event_id)
);

-- 最近 user/message 的 O(索引)定位(turn 8,#56:v13_probe 的 goal_hash 读)。
-- 无此部分索引则「type='user/message' ORDER BY seq DESC LIMIT 1」退化为反向
-- 整扫 O(N),探针的常数级承诺依赖它。
CREATE INDEX ix_events_last_user ON events (session_id, seq)
  WHERE type = 'user/message';

CREATE FUNCTION v13_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: events is append-only (% on % seq %)',
    TG_OP, TG_TABLE_NAME, OLD.seq;
END $$;

CREATE TRIGGER trg_events_append_only
  BEFORE UPDATE OR DELETE ON events
  FOR EACH ROW EXECUTE FUNCTION v13_events_append_only();

-- seq 分配 = UPDATE 控制行,行锁内互斥,天然无洞(ch1.2 原样)
CREATE FUNCTION v13_append_event(p_sid uuid, p_event_id uuid,
                                 p_type text, p_payload jsonb,
                                 p_source_effect uuid DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_seq bigint; v_turn int;
BEGIN
  UPDATE sessions
     SET next_seq = next_seq + 1,
         -- turn_no 接线(turn 3,P2 吸收):新 user/message 开新 turn,
         -- 生命周期计数唯一维护点在 append(此前无路径维护,列成死字段)
         turn_no   = turn_no + (CASE WHEN p_type = 'user/message'
                                     THEN 1 ELSE 0 END),
         -- 终态复位(turn 4,P1-11):新 user/message 同事务复位
         -- completed/failed→ready——否则 ① 恒 'terminal'、对话无法继续;
         -- cancelled 归 ch12(显式 resolve 域)不复位。与步 0 水位无交互:
         -- status 不入比对集;新 user/message 本就推 max_event_seq → 在途
         -- 旧 advance 'stale'(正常新 turn 流程)
         status    = CASE WHEN p_type = 'user/message'
                           AND status IN ('completed','failed')
                          THEN 'ready' ELSE status END
   WHERE session_id = p_sid
    RETURNING next_seq - 1, turn_no INTO v_seq, v_turn;
  IF v_seq IS NULL THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  INSERT INTO events (session_id, seq, event_id, type, turn_no,
                      payload, payload_hash, source_effect_id)
  VALUES (p_sid, v_seq, p_event_id, p_type, v_turn, p_payload,
          encode(digest(p_payload::text, 'sha256'), 'hex'), p_source_effect);
          -- p_source_effect:显式 provenance 通道(P2:此前无参无法设置)
  RETURN v_seq;
END $$;

-- === effect ledger (ch2.2 表形状;纪律 = v12/act/v12_act.sql 四件套移植) ===
CREATE TABLE effects (
  effect_id   uuid PRIMARY KEY,      -- uuid v5(命名空间, 逻辑键),SQL 生成(下文)
  session_id  uuid NOT NULL REFERENCES sessions (session_id),
  kind        text NOT NULL CHECK (kind IN
              ('judge','tool','llm','context_refresh','human')),
  tool_name   text,                  -- kind=tool 时必填(gate 断言)
  request     jsonb NOT NULL,        -- 完整出站请求,创建即冻结(ch2.3)
  request_hash text NOT NULL,
  idempotency_key text,
  origin_user_seq bigint NOT NULL,   -- 创建时 last_user_seq(turn 4,P0-2/
                                     -- 不变量 7):迟到完成锚点——完成语义
                                     -- 事件携它,消费侧(finish 判定/失败计
                                     -- 数/判断投影)按 origin=当前 turn 过滤
  attempt_no  int NOT NULL DEFAULT 0,
  fence       bigint NOT NULL DEFAULT 0,
  lease_owner text, lease_until timestamptz,
  status      text NOT NULL DEFAULT 'ready' CHECK (status IN
              ('ready','claimed','succeeded','failed','unknown','cancelled')),
  CONSTRAINT v13_effects_tool_named CHECK (kind <> 'tool'
    OR tool_name IS NOT NULL),        -- P2:tool_name 的 CHECK 承接
  op_seq      int,                   -- 并行序留缝(ch8),DP1 恒 NULL
  mutation_scope text,
  result      jsonb,
  error       jsonb,                -- 失败写者(turn 4 归并):sql 快路 handler
                                     -- 异常(§3.5/§3.6 #31,sqlstate+SQLERRM)、
                                     -- llm 结果形状降级(#26,code
                                     -- llm_result_shape)
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, idempotency_key)
);

-- 「同一时刻至多一个活跃工作单元」用 DDL 执法(v8 裁决,教程 ch5.4 引用)
CREATE UNIQUE INDEX ux_v13_effects_single_active
  ON effects (session_id) WHERE status IN ('ready','claimed');

-- uuid v5 纯 SQL(v12/queue/v12_queue.sql:36-58 逐字移植,仅前缀 v12→v13;
-- turn 3,#16:被 v13_effect_id 直接调用的函数不留占位)。RFC 4122 v5
-- (SHA-1),PG18 pgcrypto 无 uuid_generate_v5,与 Python uuid.uuid5 字节相等。
CREATE FUNCTION v13_uuid_v5(p_ns uuid, p_name text) RETURNS uuid
LANGUAGE sql IMMUTABLE AS $$
  WITH raw AS (
    SELECT substr(encode(digest(
      decode(replace(p_ns::text, '-', ''), 'hex')
      || convert_to(p_name, 'UTF8'), 'sha1'), 'hex'), 1, 32) AS h
  ), bits AS (
    SELECT h,
      lpad(to_hex((('x' || substr(h, 13, 2))::bit(8)::int & 15) | 80), 2, '0') AS b7,
      lpad(to_hex((('x' || substr(h, 17, 2))::bit(8)::int & 63) | 128), 2, '0') AS b9
    FROM raw
  )
  SELECT (substr(h2, 1, 8) || '-' || substr(h2, 9, 4) || '-' ||
          substr(h2, 13, 4) || '-' || substr(h2, 17, 4) || '-' ||
          substr(h2, 21, 12))::uuid
  FROM (SELECT substr(h, 1, 12) || b7 || substr(h, 15, 2) || b9
               || substr(h, 19, 14) AS h2 FROM bits) s
$$;

CREATE FUNCTION v13_last_user_seq(p_sid uuid) RETURNS bigint
  LANGUAGE sql STABLE AS $$
  SELECT coalesce(max(seq), -1) FROM events
   WHERE session_id = p_sid AND type = 'user/message';
$$;

-- 本 user turn 内的路由周期序数(turn/route 事件计数;预算检查与 effect
-- 身份共用同一序数源,v12_turn_cycles 血统,v12/turn/v12_turn.sql:265-271)
CREATE FUNCTION v13_cycle_no(p_sid uuid) RETURNS int
  LANGUAGE sql STABLE AS $$
  SELECT count(*)::int FROM events
   WHERE session_id = p_sid AND type = 'turn/route'
     AND seq > v13_last_user_seq(p_sid);
$$;

-- effect 身份 = (session, 本 user turn 锚, 周期序数, kind, request 哈希)
-- (评审修正 P0-3/P0-5)。v12 的三段身份(session:last_user_seq:kind,
-- v12_queue.sql:63-70)在「同一 user turn 第二个同类 effect」上碰撞:命中旧
-- succeeded 行 → 唤醒发给已完成 effect、worker 不 claim、session 停摆;SQL
-- 快路直接主键冲突。加入周期序数与 request 哈希后:**同一逻辑动作(同
-- request)重试永远同 ID;新逻辑动作必新 ID**。jsonb::text 是规范化文本
-- (键序稳定),哈希确定——与 request_hash 列同一确定性基础。
CREATE FUNCTION v13_effect_id(p_sid uuid, p_kind text, p_request jsonb) RETURNS uuid
  LANGUAGE sql STABLE AS $$
  SELECT v13_uuid_v5('00000000-0000-0000-0000-000000000000'::uuid,
                     p_sid::text || ':' ||
                     v13_last_user_seq(p_sid)::text || ':' ||
                     v13_cycle_no(p_sid)::text || ':' || p_kind || ':' ||
                     encode(digest(p_request::text, 'sha256'), 'hex'));
$$;

-- attempt cap 共用判定(turn 8,#55+turn 9,#58/#61):enqueue 重挂、requeue 回收、
-- claim 领取三处同一谓词——旧实现里过期 judge 被 requeue 直接改回 ready 后可
-- 无限 claim,持续崩溃的 worker 永不触发 kind 上限。attempt 语义=claim 次数
-- (唯一递增点=claim;requeue 回收/终态转移只推 fence,#58——belt 不变式见
-- v13_claim 注)。缺键 fail-closed(coalesce 0 → 恒拒):enqueue 顶部键存在
-- 校验使缺键在创建点即响亮 RAISE(#61,不留「ready-但-永不可领」行),本处
-- coalesce 是 claim/requeue 侧 belt(防运行期策略翻新缺键/降 cap 的存量面,
-- README 翻新纪律)。**加载序注:本函数必须先于 v13_claim 定义(claim 是
-- LANGUAGE sql,体在 CREATE 时即解析,前向引用即败);本体用 plpgsql(晚
-- 绑定)——它引用的 v13_policy 定义在更后方(§3.1 策略段),sql 语言体会在
-- 创建期就解析失败。全文件同签名定义仅此一处(turn 9 删并了策略段旧
-- LANGUAGE sql 版,#57)**。
CREATE FUNCTION v13_attempt_ok(p_kind text, p_attempt int) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN p_attempt < coalesce((v13_policy('effect_attempt_cap')->>p_kind)::int, 0);
END $$;

-- enqueue 幂等(v12_enqueue_effect 语义移植,v12/act/v12_act.sql:20-56;
-- v12 的 queued→ready、resolved_*→succeeded/cancelled 状态映射,§3.6 #7)。
-- 身份由 (kind, request) 在函数内推导——调用者不再手拼 effect_id(单一
-- 事实源,杜绝 id 与 request 错配)。failed/cancelled 重挂 = 同 ID 原子推进
-- fence(评审修正 P0-5:旧 worker 的 (attempt_no,fence) 对立即失效,不得
-- 在新 claim 前用旧 fence 结算成功);「覆盖 request」路径被结构性消灭——
-- 同 ID 必同 request(身份含其哈希),不同 request 走新行,不留
-- request/request_hash 漂移窗口。
CREATE FUNCTION v13_enqueue_effect(p_sid uuid, p_kind text, p_request jsonb,
                                   p_tool text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE v_id uuid := v13_effect_id(p_sid, p_kind, p_request); v_row effects;
BEGIN
  -- 缺键 fail-loud(turn 9,#61,第八轮 P1):effect_attempt_cap 无该 kind 键
  -- 时 v13_attempt_ok 恒 false——INSERT 路径不检查会落「ready-但-永不可领」
  -- 行(claim belt 拒、requeue 只管 claimed、advance ① 恒 waiting——永久
  -- 楔死)。创建点即响亮失败:配置错误在 enqueue 报,不留不可领取行。运行期
  -- 翻新策略缺键/降 cap(enqueue 之后)属运维事故面(claim coalesce belt
  -- 拒领,不产生错误副作用),README 记翻新纪律=新版本必含全五键、降 cap
  -- 需清场(M1-9 断言种子键集)。
  IF NOT (v13_policy('effect_attempt_cap') ? p_kind) THEN
    RAISE EXCEPTION
      'v13: effect_attempt_cap policy missing kind % (config error, fix the policy row)',
      p_kind;
  END IF;
  SELECT * INTO v_row FROM effects WHERE effect_id = v_id;
  IF v_row.effect_id IS NOT NULL THEN
    IF v_row.status IN ('succeeded','ready','claimed') THEN RETURN v_id;
    ELSIF v_row.status IN ('failed','cancelled') THEN
      -- attempt 封顶(turn 7,#49,cursor 第六轮):failed→ready 无限重挂而
      -- resolve_budget/budget_exhausted 分支不增 cycle——human worker 持续
      -- 失败时 session 永不终结。按 kind 上限(策略行 effect_attempt_cap,
      -- 复用 attempt_no 计数——每 claim +1)封顶:达上限拒重挂,行留终态、
      -- 零状态变化,交调用方按返回后行状态终结(§3.5 ②/③/abandon/⑤ 四分支
      -- 的 v_est IN ('failed','cancelled') 分流)。缺键 fail-closed:策略值
      -- 无该 kind 键 → coalesce 0 → 拒重挂(策略种子保证五 kind 全在,M1-9)。
      IF NOT v13_attempt_ok(p_kind, v_row.attempt_no) THEN
        RETURN v_id;            -- 拒重挂不报错:重挂与否由行状态表达(与
                                -- requeue/claim 同一判定,turn 8,#55)
      END IF;
      UPDATE effects SET status='ready', error=NULL,
             lease_owner=NULL, lease_until=NULL, fence=fence+1
       WHERE effect_id = v_id;
      RETURN v_id;
    ELSE  -- unknown: 墙,永不自动重放(显式 resolve 是唯一出口,ch12 缝)
      RAISE EXCEPTION 'v13: effect % is unknown — resolve explicitly', v_id;
    END IF;
  END IF;
  INSERT INTO effects (effect_id, session_id, kind, tool_name,
                       request, request_hash, idempotency_key,
                       origin_user_seq)
  VALUES (v_id, p_sid, p_kind, p_tool, p_request,
          encode(digest(p_request::text,'sha256'),'hex'),
          'v13:' || v_id::text,
          v13_last_user_seq(p_sid));
          -- origin 锚(turn 4):与 v13_effect_id 身份同源求值(同事务
          -- STABLE;enqueue 恒在 advance 会话锁下,锁内无并发
          -- user/message,两处求值必相等)
          -- 稳定 idempotency_key(turn 3,#13):同 ID 重挂(fence+1)不换键;
          -- worker 契约要求把它传出外部系统做去重(§3.5 末);UNIQUE
          -- (session_id, idempotency_key) 因 effect_id 全局唯一而恒不碰撞
  RETURN v_id;
END $$;

-- claim:SKIP LOCKED + fence 递增(ch2.2 形状 + v12_claim_job CAS 血统)
CREATE FUNCTION v13_claim(p_worker text, p_lease_ms int DEFAULT 60000)
RETURNS jsonb LANGUAGE sql AS $$
  UPDATE effects e SET status='claimed', attempt_no=attempt_no+1,
         fence=fence+1, lease_owner=p_worker,
         lease_until=clock_timestamp()
                     + make_interval(secs => p_lease_ms/1000.0)
                     -- make_interval 无 ms 命名参(turn 3,#16):毫秒换算秒
  WHERE effect_id = (
    SELECT effect_id FROM effects
     WHERE status='ready'
       AND v13_attempt_ok(kind, attempt_no)  -- cap belt(turn 8,#55+turn 9,#58):
                                             -- claim 是 attempt_no 唯一递增点
                                             -- (claim 次数单一语义;requeue
                                             -- 回收只推 fence 不动 attempt)。
                                             -- ready 行按构造恒 attempt<cap
                                             -- (enqueue 创建/重挂与 requeue
                                             -- (a1) 均已过同一判定),claim 后
                                             -- ≤cap;死在第 cap 次 claim 上的
                                             -- 行由 requeue (a1') 兜底转终态
                                             -- ——「ready-但-永不可领」结构性
                                             -- 不可达(策略翻新降 cap 的存量
                                             -- 行为=运维事故面,README 翻新纪律)
       AND (op_seq IS NULL OR op_seq = (
            SELECT min(op_seq) FROM effects
             WHERE session_id=e.session_id AND mutation_scope=e.mutation_scope
               AND status <> 'succeeded'))
     ORDER BY created_at
     FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING jsonb_build_object('effect_id', effect_id, 'attempt_no', attempt_no,
                               'fence', fence, 'kind', kind, 'request', request);
$$;

-- complete:两级锁序 + fence CAS + 多出口(ch2.2;v12_complete_job 血统)
CREATE FUNCTION v13_complete(p_effect uuid, p_attempt int, p_fence bigint,
                             p_status text, p_result jsonb DEFAULT NULL)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE v_sid uuid; v_row effects; v_outcome text; v_err jsonb;
BEGIN
  IF p_status NOT IN ('succeeded','failed','unknown') THEN
    RAISE EXCEPTION 'v13: bad outcome %', p_status;
  END IF;
  -- 令牌非 NULL(turn 5,P0-1b):NULL 经 <> 得 NULL、条件恒不成立,旧 CAS
  -- 可被 NULL 令牌整体绕过——调用面 bug,响亮失败而非协议返回。
  IF p_attempt IS NULL OR p_fence IS NULL THEN
    RAISE EXCEPTION
      'v13: complete requires non-NULL (attempt,fence) tokens (effect %)',
      p_effect;
  END IF;
  -- 锁序:session→effect(全树统一;enqueue 路径经 advance 已持 session 锁再 UPDATE
  -- effects 行,同为 session→effect。教程 ch2 草图的注释与代码序相反,以本序为准)
  SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;  -- 行存在检查(turn 5,P0-1)
  END IF;
  -- CAS 用 IS DISTINCT FROM(turn 5,P0-1b):NULL 安全的令牌比较
  IF v_row.attempt_no IS DISTINCT FROM p_attempt
     OR v_row.fence IS DISTINCT FROM p_fence THEN
    RETURN 'stale';
  END IF;
  -- 终态重入守卫(turn 3,#4):任一终态(succeeded/failed/unknown/cancelled)
  -- 的重复结算一律 'replay'——不只 succeeded。重复 failed 结算不得再落第二条
  -- resolve/failed;unknown 结算不得复活行。failed/cancelled 的重挂出口是
  -- enqueue(fence+1→ready),不是二次 complete;未重挂时旧 (attempt,fence)
  -- 仍匹配,靠本守卫拦 replay。
  IF v_row.status IN ('succeeded','failed','unknown','cancelled') THEN
    RETURN 'replay';
  END IF;
  -- claimed 前置(turn 5,P0-1a):非终态行必须处于 claimed 才可结算——ready 行
  -- 的 (attempt_no,fence)=(0,0) 可被原样传入而通过裸令牌比较,「未领取先
  -- 结算」绕过 claim 的全部租约纪律(fence CAS 的前置状态缺失)。拒收出口=
  -- 'stale'(无持有者的统一协议拒绝,行与事件零变化)。
  IF v_row.status <> 'claimed' THEN
    RETURN 'stale';
  END IF;
  -- llm 结果最低形状校验(turn 4,P0-4):text 必须是非空字符串——NULL
  -- result/{}/缺字段/非字符串/空白串一律确定性降级 failed(error 列记
  -- llm_result_shape),不落 llm/message、finish/delivered 不可达;turn
  -- 自愈=下一轮 advance 重路由(cycle 进身份必新 effect),turn_budget 封顶
  -- (与 §3.6 #31 sql 快路同一自愈模型)。校验在接受 succeeded 结算之前。
  v_outcome := p_status; v_err := NULL;
  IF p_status = 'succeeded' AND v_row.kind = 'llm'
     AND (coalesce(jsonb_typeof(p_result->'text'), 'null') <> 'string'
          OR coalesce(btrim(p_result->>'text'), '') = '') THEN
    v_outcome := 'failed';
    v_err := jsonb_build_object('code', 'llm_result_shape');
  END IF;
  UPDATE effects SET status=v_outcome, result=p_result, error=v_err
    WHERE effect_id=p_effect;  -- result 原样保留(审计 worker 送来什么)
  PERFORM v13_append_event(v_sid, gen_random_uuid(), 'effect_done',
    jsonb_build_object('effect_id', p_effect, 'status', v_outcome), p_effect);
    -- provenance:effect_done ← effect(P2 通道)
  -- 语义事件半边(turn 3,#1/#20 + turn 4 锚点):worker 慢路的语义结果在
  -- 唯一同锁落点物化——kind='tool' 成功→tool/result;kind='llm' 成功→
  -- llm/message(P0 finish 的证据源);快路 tool/result 的对称半边在
  -- advance ④ sql 分支。payload 携 origin_user_seq(不变量 7):消费侧
  -- (finish 判定/失败计数/判断投影)按锚过滤跨 turn 迟到结算。判读投影
  -- 因此看见慢路结果,turn 得以收敛(否则 tool/llm 完成后 ctx 不变、intent
  -- 缓存旧值,P4 死循环至预算耗尽)。
  IF v_outcome = 'succeeded' AND v_row.kind = 'tool' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'tool/result',
      jsonb_build_object('tool', v_row.tool_name, 'result', p_result,
                         'origin_user_seq', v_row.origin_user_seq), p_effect);
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'llm' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'llm/message',
      p_result || jsonb_build_object('origin_user_seq', v_row.origin_user_seq),
      p_effect);
      -- worker 契约:llm effect 的 result 含 'text'(生成正文),已过上方
      -- #26 形状校验(p_result 必为 object)
  END IF;
  -- worker 慢路失败审计半边(§3.6 #5/#15):parse 路径的 resolve/failed 由
  -- advance 落;worker 路径没有 advance 在环,唯一同锁落点是这里——
  -- kind='judge' 的 failed 结算追加 resolve/failed,防重试风暴计数单源
  -- (计数按 origin 锚只计当前 turn,§3.6 #25;llm 形状降级不落此事件
  -- ——那不是判断重试,自愈走重路由)。
  IF v_outcome = 'failed' AND v_row.kind = 'judge' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('effect_id', p_effect, 'path', 'worker',
                         'origin_user_seq', v_row.origin_user_seq));
  END IF;
  RETURN 'accepted';
END $$;

-- === decision plane (ch4.2;校验纪律移植自 v12 jev_questions/validate) ===
CREATE TABLE decisions (
  decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid NOT NULL REFERENCES sessions (session_id),
  signal      text NOT NULL,         -- 判断的稳定身份(路由信号名,如 'intent')
  kind        text NOT NULL CHECK (kind IN ('choice','score','noul')),
  question    text NOT NULL          -- ASCII,判断题英文(v12 调研结论的 DDL 执法)
    CHECK (question ~ '^[\x20-\x7E]+$' AND length(btrim(question)) > 0),
  criteria    jsonb,                 -- choice 选项表/score 档位表/noul 澄清
  context     jsonb NOT NULL,        -- canonical projected state(§3.2)
  answer      jsonb,                 -- NULL→非NULL 一次(ch4 硬性规定)
  provider    text, model text,
  request_hash text NOT NULL,        -- 全量哈希,安全默认(§6.5;DP2 替换 builder)
  status      text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','answered','cached','failed')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  -- 幂等缓存唯一约束=**session 作用域**(评审修正 P0-4/§3.6 #11):教程 ch4
  -- 字面是 UNIQUE(request_hash)(跨 session 规范缓存形态),但 DP1 路由
  -- 证据只读本 session(v_routes 按 d.session_id 消费)——全局唯一会让异
  -- session 同行伪命中(gap=0 而无可路由证据);命中条件同时收窄为
  -- answer 非空且 status∈answered/cached(§3.2 v13_gap),open/failed 行
  -- 不算命中。跨 session 复用的 canonical/usage 拆分归 DP6(§1.3 契约)。
  UNIQUE (session_id, request_hash), -- §4.3 ON CONFLICT 的承接(复合目标)
  CONSTRAINT v13_decisions_choice_shape CHECK (kind <> 'choice'
    OR (jsonb_typeof(criteria)='object' AND criteria <> '{}'::jsonb)),
  CONSTRAINT v13_decisions_score_shape CHECK (kind <> 'score'
    OR (jsonb_typeof(criteria)='array' AND jsonb_array_length(criteria) >= 2)),
  CONSTRAINT v13_decisions_noul_shape CHECK (kind <> 'noul'
    OR criteria IS NULL OR jsonb_typeof(criteria)='object'),
  CONSTRAINT v13_decisions_criteria_ascii CHECK (criteria IS NULL
    OR criteria::text ~ '^[\x20-\x7E]*$')          -- v12_schema.sql:129-134 移植
);

-- answer 只许 NULL→非NULL 一次(追加新行修正,不覆盖——审计链完整)
CREATE FUNCTION v13_answer_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.answer IS NOT NULL AND NEW.answer IS DISTINCT FROM OLD.answer THEN
    RAISE EXCEPTION 'v13: decision % answer is immutable; append a new decision',
      OLD.decision_id;
  END IF;
  IF OLD.answer IS NULL AND NEW.answer IS NOT NULL THEN
    NEW.answered_at := now(); NEW.status := 'answered';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decisions_answer_once BEFORE UPDATE ON decisions
  FOR EACH ROW EXECUTE FUNCTION v13_answer_once();

-- 信号抽取:v12_signal 逐字移植(choice→confidence/score→score/noul→noul)
CREATE FUNCTION v13_signal(p_kind text, p_answer jsonb) RETURNS numeric
  LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN p_kind='noul'  THEN (p_answer->>'noul')::numeric
              WHEN p_kind='score' THEN (p_answer->>'score')::numeric
              ELSE                     (p_answer->>'confidence')::numeric END;
$$;

-- === 路由策略版本父表(turn 5,P1-3/#35):thresholds 的版本必须先存在于此,
--     且带 draft/frozen 两态。draft 期可追加带行;frozen 后该版本永久封版
--     ——「向已使用版本 INSERT 新 band_no」被结构性拒绝,版本号从此真正=
--     内容地址(步 0 复核因此完备:同 (name,version) 永远同带集)。
--     sessions 只能引用 frozen 版本(触发器执法)。冻结=draft→frozen 唯一
--     许可的 UPDATE(+frozen_at 由触发器落);解冻/改键/DELETE 拒绝。 ===
CREATE TABLE v13_route_policies (
  policy_name text NOT NULL,
  policy_version int NOT NULL CHECK (policy_version >= 1),
  state text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','frozen')),
  created_at timestamptz NOT NULL DEFAULT now(),
  frozen_at timestamptz,
  PRIMARY KEY (policy_name, policy_version)
);
CREATE FUNCTION v13_route_policies_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: route policy versions are append-only (no DELETE)';
  END IF;
  IF NEW.policy_name IS DISTINCT FROM OLD.policy_name
     OR NEW.policy_version IS DISTINCT FROM OLD.policy_version THEN
    RAISE EXCEPTION 'v13: route policy version key is immutable';
  END IF;
  IF OLD.state = 'draft' AND NEW.state = 'frozen' THEN
    NEW.frozen_at := now(); RETURN NEW;    -- 冻结:唯一许可的转移
  END IF;
  RAISE EXCEPTION 'v13: route policy version only transitions draft->frozen (%)',
    OLD.state;
END $$;
CREATE TRIGGER trg_route_policies_guard
  BEFORE UPDATE OR DELETE ON v13_route_policies
  FOR EACH ROW EXECUTE FUNCTION v13_route_policies_guard();

-- === thresholds:版本化路由带(ch4.2)。**半开区间 [lo, hi)**(评审修正
--     P1-10:BETWEEN 双端闭合会让边界值同时命中相邻两带);顶带 hi=
--     'Infinity'(PG float8 支持)覆盖信号上界;带间隙允许——无带命中落
--     v13_route 兜底 human(ch4.4「低置信落 human 兜底」)。action 列=**带
--     判定词表**('pass' 清障带/'reject' 否决带);路由输出动作
--     (sql/tool/llm/human/finish/reject)由 v13_route 决策表产生,不存这里 ===
CREATE TABLE thresholds (
  policy_name text NOT NULL, policy_version int NOT NULL,
  signal text NOT NULL, band_no int NOT NULL,
  lo double precision NOT NULL CHECK (lo >= 0),
  hi double precision NOT NULL,
  action text NOT NULL CHECK (action IN ('pass','reject')),
  PRIMARY KEY (policy_name, policy_version, signal, band_no),
  CHECK (lo < hi),
  FOREIGN KEY (policy_name, policy_version)
    REFERENCES v13_route_policies (policy_name, policy_version)
);

-- 版本不可变(turn 4,P1-7/§3.6 #29 + turn 5,#35 补缺口):带行 append-only
-- ——UPDATE/DELETE 由本触发器拒绝;**INSERT 由 insert_guard 拦**:仅 draft
-- 版本可追加带行,frozen 版本拒绝(旧机制只拦 UPDATE/DELETE,同版本 INSERT
-- 追带可改语义而版本号不变,六元组复核测不到——L4 第四轮 P1)。改带=新
-- (policy_name, policy_version):父表建 draft 行→插带→freeze→sessions 指它。
-- 信封冻结 route_policy_name/version + advance 步 0 探针比对保证
-- parse/advance 对间不消费旧策略。测试 fixture 需无带场景时建空 frozen
-- 版本(如 ('default',99) 零带行)再用 sessions.route_policy_version 指向。
CREATE FUNCTION v13_thresholds_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: thresholds are append-only (new version rows, not % on %)',
    TG_OP, TG_TABLE_NAME;
END $$;
CREATE TRIGGER trg_thresholds_frozen
  BEFORE UPDATE OR DELETE ON thresholds
  FOR EACH ROW EXECUTE FUNCTION v13_thresholds_frozen();

-- INSERT 守卫(turn 5,P1-3 + turn 6,#39 并发追带封死):带行必须挂在已存在
-- 的父版本下,且父版本= draft(不存在/已 frozen 均 IS DISTINCT FROM 'draft'
-- → 拒)。**读父行 FOR UPDATE**:守卫的普通 SELECT 只看语句快照——并发
-- 事务先读 draft、他事务冻结、前者后提交即「冻结后追带」(FK 键锁是 KEY
-- SHARE 级,拦不住只 UPDATE state 的冻结路径);行锁使 insert 守卫与
-- freeze 的状态变更在父行上串行化:插带先行 → 冻结等待、提交后含该带
-- (冻结内容=冻结时点带集,合法);冻结先行 → 守卫在锁等待后重读
-- (READ COMMITTED 下 FOR UPDATE 取最新已提交版本)见 frozen → 拒。
-- 两序全序,无追带窗口。
CREATE FUNCTION v13_thresholds_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_state text;
BEGIN
  SELECT state INTO v_state FROM v13_route_policies
   WHERE policy_name = NEW.policy_name
     AND policy_version = NEW.policy_version
   FOR UPDATE;                 -- 行锁与 freeze 串行化(turn 6,#39)
  IF v_state IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION
      'v13: thresholds need a draft parent route policy version (%,%, state=%)',
      NEW.policy_name, NEW.policy_version, v_state;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_thresholds_insert_guard
  BEFORE INSERT ON thresholds
  FOR EACH ROW EXECUTE FUNCTION v13_thresholds_insert_guard();

-- sessions 只能引用 frozen 版本(turn 5,P1-3):draft 版本可被追改,引用它
-- 等于消费浮动语义。INSERT 与 route_policy 两列的 UPDATE 都拦(UPDATE OF
-- 限定列,status 等常规 UPDATE 不触发——终态复位/append 路径不受扰)。
CREATE FUNCTION v13_sessions_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_state text;
BEGIN
  SELECT state INTO v_state FROM v13_route_policies
   WHERE policy_name = NEW.route_policy_name
     AND policy_version = NEW.route_policy_version;
  IF v_state IS DISTINCT FROM 'frozen' THEN
    RAISE EXCEPTION
      'v13: session must reference a frozen route policy (%,%, state=%)',
      NEW.route_policy_name, NEW.route_policy_version, v_state;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_sessions_policy_guard
  BEFORE INSERT OR UPDATE OF route_policy_name, route_policy_version ON sessions
  FOR EACH ROW EXECUTE FUNCTION v13_sessions_policy_guard();

CREATE OR REPLACE VIEW v_routes AS     -- 路由 = answered decisions × 带的视图
SELECT d.session_id, d.decision_id, d.signal, d.answer, d.kind,
       v13_signal(d.kind, d.answer) AS value, t.action, t.band_no
  FROM decisions d
  JOIN sessions s ON s.session_id = d.session_id
  JOIN LATERAL (
    SELECT * FROM thresholds t
     WHERE t.policy_name = s.route_policy_name
       AND t.policy_version = s.route_policy_version
       AND t.signal = d.signal
       AND v13_signal(d.kind, d.answer) >= t.lo
       AND v13_signal(d.kind, d.answer) <  t.hi   -- 半开 [lo,hi):边界不双命中
     ORDER BY t.band_no LIMIT 1) t ON true
 WHERE d.status IN ('answered','cached');

-- === tools 最小切片(ch6 的 DP1 子集:kind ∈ sql/tool/llm;
--     v12 tools 形状,effect_class 改名 kind、read_only→sql,教程 ch5.4 措辞) ===
CREATE TABLE tools (
  name        text PRIMARY KEY,
  description text NOT NULL CHECK (description ~ '^[\x20-\x7E]+$'),
  kind        text NOT NULL CHECK (kind IN ('sql','tool','llm')),
  handler     text NOT NULL,        -- sql: SQL 函数名(目录即 allowlist,v1/v2 血统;
                                    -- 冻结时解析为 schema-qualified 已校验名,
                                    -- turn 7 #50;disabled 行冻结时原样透传
                                    -- 不校验,turn 8 #53);
                                    -- tool/llm: worker 处理键
  param_spec  jsonb NOT NULL DEFAULT '{}'::jsonb
              CHECK (jsonb_typeof(param_spec) = 'object'),
  enabled     boolean NOT NULL DEFAULT true
);

-- === tools 双守卫触发器(turn 7,#48/#50,cursor 第六轮两项)===
-- (1) signal 语法守卫(#48):needed 生成的 signal 是 param|stated::<tool>::<key>
--     的拼接式身份——名字含 '::' 可撞(工具 a/键 b::c ≡ 工具 a::b/键 c,
--     (session_id,request_hash) 撞行使 gap 双消、第二信号无证据,同 #43 形态)。
--     语法层禁绝:tool 名与 param_spec 键均非空且不含 '::'。单射论证:
--     name 主键唯一 × 单工具键集唯一(jsonb 对象键天然不重)× 无 '::' ⇒ 生成
--     signal 两两互异;固定五问(intent/gate_action/gate_off_topic/risk/tool)
--     不含 '::',与 param/stated 族不相交。生成端 belt(重复即 RAISE)在
--     v13_needed_judgments 末尾(§3.2),gate=M1-14(写入负向)+M2-13(端到端)。
-- (2) sql handler 写入半边校验(#50):kind='sql' 只读此前仅是标签——错误
--     配置的 VOLATILE/阻塞/外部 IO handler 会在 advance 会话锁内执行(不变量 3
--     被重引入)。写入时即校验(冻结半边=v13_tools_catalog_frozen,§3.2——捕
--     写入后 DROP/CREATE OR REPLACE 漂移):精确签名 (uuid,jsonb)→jsonb 解析
--     (0 行=缺失、跨 schema 重名=歧义)、provolatile IN ('i','s') 拒 VOLATILE、
--     v13_route 有 EXECUTE(执行权限限定)。BEFORE 守卫 RAISE → 语句失败 →
--     AFTER 的 revision bump 不执行(目录不变,gate 断言)。
--     **只校验 enabled 行(turn 8,#53,claude 第七轮)**:handler 已被 DROP 的行
--     连 UPDATE enabled=false 都被拒=最需要隔离时隔离不了;disabled 行带病可
--     入,但 enabled=false→true 的 UPDATE 必过本守卫(NEW.enabled=true → 校验)
--     ——启用时刻 fail-closed(且该 UPDATE 自身 bump revision → 在途信封弃批
--     → 重 parse 重新校验,无未校验值被消费窗口)。
--     proargtypes 比较用 oidvectortypes(p.proargtypes)='uuid, jsonb'
--     (turn 8 机械修:pg_proc.proargtypes 是 oidvector,与 oid[] 无 = 算子,
--     ARRAY[...]::oid[] 写法解析期即错 42883;oidvectortypes 版本无关、免 OID
--     硬编码;§3.2 catalog_frozen 冻结半边同改四处)。
CREATE FUNCTION v13_tools_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE k text; v_n int;
BEGIN
  IF NEW.name IS NULL OR NEW.name = '' OR NEW.name LIKE '%::%' THEN
    RAISE EXCEPTION
      'v13: tool name must be non-empty and contain no "::" (signal identity): %',
      NEW.name;
  END IF;
  IF jsonb_typeof(NEW.param_spec) = 'object' THEN
    FOR k IN SELECT jsonb_object_keys(NEW.param_spec) LOOP
      IF k = '' OR k LIKE '%::%' THEN
        RAISE EXCEPTION
          'v13: tool % param key must be non-empty and contain no "::" : %',
          NEW.name, k;
      END IF;
    END LOOP;
  END IF;
  IF NEW.kind = 'sql' AND NEW.enabled THEN   -- 只校验 enabled 行(turn 8,#53)
    SELECT count(*) INTO v_n FROM pg_proc p
     WHERE p.proname = NEW.handler
       AND oidvectortypes(p.proargtypes) = 'uuid, jsonb';
    IF v_n = 0 THEN
      RAISE EXCEPTION
        'v13: sql tool % handler % not found (signature (uuid,jsonb)->jsonb)',
        NEW.name, NEW.handler;
    ELSIF v_n > 1 THEN
      RAISE EXCEPTION
        'v13: sql tool % handler % ambiguous across schemas (%)',
        NEW.name, NEW.handler, v_n;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM pg_proc p
       WHERE p.proname = NEW.handler
         AND oidvectortypes(p.proargtypes) = 'uuid, jsonb'
         AND p.provolatile IN ('i','s')
         AND p.prorettype = 'jsonb'::regtype
         AND has_function_privilege('v13_route', p.oid, 'EXECUTE')) THEN
      RAISE EXCEPTION
        'v13: sql tool % handler % must be IMMUTABLE/STABLE, return jsonb, and be executable by v13_route',
        NEW.name, NEW.handler;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_tools_guard
  BEFORE INSERT OR UPDATE ON tools
  FOR EACH ROW EXECUTE FUNCTION v13_tools_guard();

-- === 工具目录版本(turn 5,P1-6/#38):目录任何 INSERT/UPDATE/DELETE 经
--     AFTER 触发器原子递增 revision(行级触发,多行变更多次递增——只需
--     单调,不需精确一次)。事务原子性 ⇒ 任何语句快照下 revision 与目录
--     内容一致;信封(STABLE,调用语句单快照)在同一求值内读 (revision,
--     目录全集) 并冻结为 tools_revision/tools_catalog 两键。路由/参数/
--     handler **严格读信封冻结目录**(§3.5),advance 步 0 探针含
--     tools_revision——parse/advance 间目录任何变更(含 handler/param_spec
--     这类不进判断哈希的列)→ stale 重解析。被拒替代:advance 内锁
--     v13_tools_meta 行至建账完成(可行但引入 sessions→meta 新锁序面;
--     冻结读零新增锁)。TOCTOU 边界的准确表述(turn 7,#47 修正旧注「缩到
--     零」):信封求值内部=单语句快照,目录/事件/水位/revision 同点读取
--     (结构性一致);parse→advance 间的窗口非零,但被步 0 tools_revision
--     比对检测(弃批)——窗口内不一致可检测、不静默消费)。turn 9,#59 增列 candidate_generation_revision:needed 集=f(tools 行集,**v13_needed_judgments 函数体**)——OR REPLACE 换推导体不触 tools 行、revision 不动(六键论证的破绽);由文末 DDL event trigger 第二分支命中目标名 bump(两键独立:目录行 DML 只动 revision,needed 体 DDL 只动 cgr;DP5 语料版本面必须并入本键或另立,§1.3 硬契约) ===
CREATE TABLE v13_tools_meta (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  revision  bigint NOT NULL DEFAULT 0,
  candidate_generation_revision bigint NOT NULL DEFAULT 0
);
INSERT INTO v13_tools_meta VALUES (true, 0);
CREATE FUNCTION v13_tools_bump() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE v13_tools_meta SET revision = revision + 1 WHERE singleton;
  RETURN NULL;            -- AFTER 行触发器,返回值被忽略
END $$;
CREATE TRIGGER trg_tools_bump
  AFTER INSERT OR UPDATE OR DELETE ON tools
  FOR EACH ROW EXECUTE FUNCTION v13_tools_bump();

-- === 策略行载体(§9「策略行」家族的最小起点;DP7 同表追加)。
--     **版本化=追加不覆盖**(评审修正 P1-10:name 主键下「追加新版本」无处
--     落):主键 (name,version),at-most-one active 行由部分唯一索引执法;
--     读侧单源 v13_policy() 取 active 行,无 active 行 fail-closed(种子保证
--     恒在,丢种子=配置事故应立刻炸而非静默用默认值) ===
CREATE TABLE v13_policies (
  name text NOT NULL, version int NOT NULL CHECK (version >= 1),
  value jsonb NOT NULL,
  active boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (name, version)
);
CREATE UNIQUE INDEX ux_v13_policies_one_active ON v13_policies (name)
  WHERE active;

-- 版本不可变(turn 4,P1-7/§3.6 #29):唯一许可的 UPDATE=翻 active
-- (+updated_at)——即 P1-10 的版本切换机制本身;name/version/value 改写
-- 与 DELETE 拒绝(版本行是审计轨迹)。fail-closed 语义靠「无 active 行」
-- 表达,不靠删除。
CREATE FUNCTION v13_policies_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: policy rows are append-only (no DELETE)';
  END IF;
  IF NEW.name IS DISTINCT FROM OLD.name
     OR NEW.version IS DISTINCT FROM OLD.version
     OR NEW.value IS DISTINCT FROM OLD.value THEN
    RAISE EXCEPTION 'v13: policy rows are immutable (append new version + flip active)';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_policies_frozen
  BEFORE UPDATE OR DELETE ON v13_policies
  FOR EACH ROW EXECUTE FUNCTION v13_policies_frozen();

CREATE FUNCTION v13_policy(p_name text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb;
BEGIN
  SELECT value INTO v FROM v13_policies WHERE name = p_name AND active;
  IF v IS NULL THEN
    RAISE EXCEPTION 'v13: no active policy row for % (seed lost?)', p_name;
  END IF;
  RETURN v;
END $$;

-- v13_attempt_ok 定义在上方(enqueue/claim 段,plpgsql 版=全文件唯一权威定义)。
-- 此处原有一份 LANGUAGE sql 旧定义——turn 8 上移时只增未删,同签名第二个裸
-- CREATE FUNCTION 报 42723(第八轮双通道收敛 P0);turn 9 删除(移动=增+删)。

INSERT INTO v13_policies (name, version, value, active) VALUES
-- value 列=jsonb:种子一律**单个完整 JSON 字面量+显式 ::jsonb**(turn 8 机械修,
-- cursor 第七轮 P0:两段字面量 || 拼接的产物是 text,赋 jsonb 列无赋值 cast
-- → M1 加载即败 42804;同型扫描全树——其余 jsonb 写入均为单字面量/
-- jsonb_build_object/::jsonb,无第二例字符串拼接)
 ('resolve_fast_path', 1, '{"max_batches": 1, "batch_questions": 32}'::jsonb, true),
                                                   -- §4.3 默认 ≤1 批 ≤32 问
 ('turn_budget',       1, '{"max_cycles": 3}'::jsonb, true),
                                                   -- v12 G4 血统,数据非代码
 ('resolve_retry',     1, '{"cap": 2}'::jsonb, true),  -- 防重试风暴上限,数据可调
 ('effect_attempt_cap',1,
  '{"judge":4,"tool":3,"llm":3,"human":2,"context_refresh":3}'::jsonb, true);  -- 末元组分号=turn 9 机械修:缺则与下文 CREATE TABLE 粘连(42601)
                                                   -- 按 kind 的 attempt 上限
                                                   -- (turn 7,#49 重挂+turn 8,#55
                                                   -- 扩至 requeue 回收/claim 领取
                                                   -- 共用同一判定;judge 4>
                                                   -- resolve_retry 2——常态由
                                                   -- abandon 先至,judge cap 是 belt)

-- === typesafe 远端错误码契约档案(turn 5,P1-4/#36 落表 + turn 6,#40 降位:
--     注册表=部署期契约核对与运维档案,**不是 α 吸收面**)。论证:一次坏
--     endpoint 探测只证明「该次网络错以该码浮出」,证明不了扩展内部缺陷
--     不会复用同码——若 α 按「已注册即吸收」吞 OTHERS,本地/扩展缺陷可能
--     伪装 failed=true(静默重试风暴面)。故 §3.3 的 α 对 OTHERS 零吸收,
--     本表职责=M2 setup_db.py 探针在 SAVEPOINT 内以坏 endpoint+mock NULL
--     调一次 typesafe_ask,观测 pgcode 并做**契约核对**:该码不得落在本地
--     可自产类(P0/XX/42/22/55/53/54/40/57)、'V3001'、'57014' 内(碰撞=
--     「远端传输错误与本地缺陷/取消族码空间重叠」的契约破坏,setup 退出
--     码非 0——运维必须知道码空间已不可区分);通过则记录(origin=
--     'probe_unreachable')。另设**超时可交付性前置探针(turn 7,#45,两通道
--     收敛;详见 §4 M2 产出行)**:挂起 socket+短 statement_timeout 实调一次
--     typesafe_ask 断言观测 pgcode='57014' 可交付(与坏 endpoint 探针互补:
--     后者核码空间不重叠,前者核超时族在分类门内可达);红=退出非 0 响亮
--     失败+回退预案指引。运维可人工补注(origin='manual',如现场观察到
--     typesafe 自身 timeout 的专属码)——补注同样不改变 α 行为。**SQL 面
--     零消费:不授任何角色 SELECT,owner/监控专用**(吸收面与注册解耦,
--     注册永不放大吸收)。
CREATE TABLE v13_remote_sqlstates (
  sqlstate text PRIMARY KEY,
  origin   text NOT NULL CHECK (origin IN ('probe_unreachable','manual')),
  note     text,
  registered_at timestamptz NOT NULL DEFAULT now(),
  CHECK (sqlstate ~ '^[0-9A-Z]{5}$'
         AND sqlstate <> 'V3001'
         AND substr(sqlstate,1,2) NOT IN
             ('P0','XX','42','22','55','53','54','40','57'))
);

-- === 三角色最小 ACL 矩阵(§4.3 角色分裂的 DDL 执法;评审修正 P1-7:
--     不再只落 recall——v1/v2「只读角色执法」血统升级为三角色,不建 RBAC
--     帝国(v8 六角色已裁跳过)。Postgres 函数默认 ACL 是 PUBLIC EXECUTE,
--     必须逐函数显式 REVOKE(**列举式,不用 ALL FUNCTIONS 以免误伤 pgcrypto
--     在 public 的 digest/gen_random_uuid 等扩展函数**);recall/resolve 函数
--     族的 EXECUTE 授权随 M2 的 v13_resolve.sql 落、route 族随 M3 的
--     advance.sql 落(函数在哪个 stage 创建就归哪个 stage 授权——M1-7 引用
--     M2 函数的移位问题由此消除,P1-8)。源码扫描(M1-10/K4)降为辅。
--     矩阵(闭包按函数内部调用链展开):
--       v13_recall  SELECT 七表(六表+v13_tools_meta,信封链);EXECUTE 纯读
--                   辅助(uuid_v5/last_user_seq/cycle_no/signal)
--       v13_resolve recall ∪ {INSERT/UPDATE(answer) decisions;EXECUTE
--                   parse/resolve 族;v13_policy}(v13_remote_sqlstates 零授权:
--                   契约档案无 SQL 消费者,turn 6 #40)
--       v13_route   recall ∪ {INSERT events/effects;UPDATE sessions/effects;
--                   SELECT v13_route_policies;EXECUTE append/enqueue/claim/
--                   complete/effect_id/attempt_ok/route 族/v13_policy}
--     不变量 1/2 由 ACL 直接执法:resolve 角色拿不到 v13_append_event 与
--     sessions UPDATE,route 角色拿不到 v13_resolve_judgments(typesafe_ask
--     唯一点不进 route 手) ===
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_recall') THEN
    CREATE ROLE v13_recall NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_resolve') THEN
    CREATE ROLE v13_resolve NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_route') THEN
    CREATE ROLE v13_route NOLOGIN;
  END IF;
  -- 生产登录角色(turn 5,#37 落地 + turn 6,#41 升为强制):**单成员双登录=
  --  唯一受 DB 执法的隔离形态**——v13_resolve_login 只入 v13_resolve 组、
  --  v13_route_login 只入 v13_route 组;SET ROLE 只能切到本人成员角色,
  --  route 登录在持锁事务内 SET ROLE v13_resolve 被 DB 直接拒绝(NOINHERIT
  --  双成员做不到:随时可切,「切换边界=事务边界」只是应用约定,无 DB
  --  执法)。跨平面进程(driver/worker)一律双连接池:判断面(parse/
  --  resolve_judgments)走 resolve_login 连接、建账结算面(advance/claim/
  --  complete/renew/requeue)走 route_login 连接——两相本就是两笔事务,
  --  双池零额外代价。v13_worker LOGIN NOINHERIT 双成员保留为**记录在案的
  --  退化替代**(无法开双登录的部署:隔离纯靠应用约定,README 注明无 DB
  --  执法;gate 不为其背书);角色属性由 M1-7/M2-10/M3-12 断言双登录形态。
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_route_login') THEN
    CREATE ROLE v13_route_login LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_resolve_login') THEN
    CREATE ROLE v13_resolve_login LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_worker') THEN
    CREATE ROLE v13_worker LOGIN NOINHERIT;   -- 退化替代,见上注
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO v13_recall, v13_resolve, v13_route;
GRANT v13_resolve TO v13_resolve_login;   -- 单成员:跨面 SET ROLE=permission denied
GRANT v13_route    TO v13_route_login;    -- 同上,物理隔离的判定性
GRANT v13_resolve, v13_route TO v13_worker;  -- 退化替代(无 DB 执法,README 注记)

-- 表级:recall 只读七表(六表+v13_tools_meta,信封链读);route 增读
-- v13_route_policies(sessions 建行/改指向时触发器读取);route 建账写三表;
-- v13_remote_sqlstates 零授权(契约档案,owner/监控专用,SQL 面零消费,
-- turn 6 #40)
GRANT SELECT ON sessions, events, decisions, thresholds, tools, v13_policies,
                v13_tools_meta
  TO v13_recall, v13_resolve, v13_route;
GRANT SELECT ON v13_route_policies TO v13_route;
-- decisions 列级授权(turn 3,#17 + turn 4 #28 收窄):INSERT 全列(追加新
-- 证据行),UPDATE 仅 answer。provider/model 与 question/context/request_hash/
-- signal/kind/criteria 一并不可 UPDATE——身份列冻结的 DDL 执法(旧整表
-- UPDATE 过宽;provider/model 是 request_hash 的输入,同 hash 行身份必同,
-- 冲突路径 SET 它们是死代码,§3.3);status/answered_at 由 answer-once 触发
-- 器派生(触发器内部赋值不查列权限)。
GRANT INSERT ON decisions TO v13_resolve;
GRANT UPDATE (answer) ON decisions TO v13_resolve;
GRANT INSERT ON events, effects TO v13_route;
GRANT SELECT ON v_routes TO v13_route;
  -- turn 3,#6:v_routes 是路由证据视图(v13_env_hit 消费),漏授则 route
  -- 角色读不到带命中;recall/resolve 不授(不消费)
GRANT UPDATE ON sessions, effects TO v13_route;
GRANT SELECT ON effects TO v13_route;  -- INVOKER enqueue/claim/complete read the row

-- 核心函数族:收回 PUBLIC EXECUTE,按角色发放(签名与 DDL 逐一对应)
REVOKE EXECUTE ON FUNCTION
  v13_events_append_only(), v13_append_event(uuid,uuid,text,jsonb,uuid),
  v13_uuid_v5(uuid,text), v13_last_user_seq(uuid), v13_cycle_no(uuid),
  v13_effect_id(uuid,text,jsonb),
  v13_enqueue_effect(uuid,text,jsonb,text),
  v13_claim(text,int), v13_complete(uuid,int,bigint,text,jsonb),
  v13_answer_once(), v13_signal(text,jsonb), v13_policy(text),
  v13_attempt_ok(text,int),
  v13_thresholds_frozen(), v13_policies_frozen(),
  v13_route_policies_guard(), v13_thresholds_insert_guard(),
  v13_sessions_policy_guard(), v13_tools_bump(), v13_tools_guard()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_uuid_v5(uuid,text), v13_last_user_seq(uuid), v13_cycle_no(uuid),
  v13_signal(text,jsonb)
TO v13_recall, v13_resolve, v13_route;      -- 纯读辅助,三角色共用
GRANT EXECUTE ON FUNCTION v13_policy(text)
TO v13_resolve, v13_route;                   -- 策略读取:resolve/route 各自消费
GRANT EXECUTE ON FUNCTION
  v13_append_event(uuid,uuid,text,jsonb,uuid),
  v13_enqueue_effect(uuid,text,jsonb,text),
  v13_claim(text,int), v13_complete(uuid,int,bigint,text,jsonb),
  v13_effect_id(uuid,text,jsonb), v13_attempt_ok(text,int)
TO v13_route;                                -- 建账/结算只在 route 手(cap 共用
                                             -- 判定同在 route 面,turn 8 #55)
-- v13_events_append_only/v13_answer_once/v13_thresholds_frozen/
-- v13_policies_frozen/v13_route_policies_guard/v13_thresholds_insert_guard/
-- v13_sessions_policy_guard/v13_tools_bump/v13_tools_guard 是触发器函数:REVOKE
-- 后仅属主可挂(v13_tools_ddl_bump 的 REVOKE 随其文末创建点内联——先建后引,
-- 零前向引用,turn 8 #54)
-- M3/M4 stage 函数同规(turn 3,#6):v13_send_work 随 M3 advance.sql、
-- v13_requeue_stale/v13_renew_lease 随 M4 twophase.sql,各自 REVOKE PUBLIC
-- + GRANT v13_route(claim/complete 同属 route 手),断言随 M3-12/K3。
-- typesafe_ask 的 REVOKE PUBLIC + GRANT v13_resolve 在 M2 v13_resolve.sql 落
-- (扩展函数,须属主/超级用户执行;见 §3.3 尾注)。

-- === 种子:全部落为可执行语句(评审修正 P1-11:不再省略号/纯描述) ===
-- 演示只读 handler:v12_tool_session_stats 移植(v12/turn/v12_turn.sql:49-64,
-- jobs→effects、message_count 对齐语义事件口径)
-- 统一 handler 契约 (session_id uuid, params jsonb)(turn 3,#14:种子
-- handler 原签名 (uuid) 与 SQL 快路动态调用传 (jsonb) 不匹配——统一双参,
-- EXECUTE USING 调用,见 §3.5)。
-- ACL:有意保留 PUBLIC EXECUTE(turn 3,#6 注记)——演示只读 handler,目录
-- 即 allowlist(目录行是受控面),函数只读自身三表,无写面。
CREATE FUNCTION v13_tool_session_stats(p_sid uuid, p_params jsonb) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'message_count', (SELECT count(*) FROM events
                       WHERE session_id = p_sid
                         AND type IN ('user/message','llm/message','tool/result')),
    'open_effects', (SELECT count(*) FROM effects
                      WHERE session_id = p_sid
                        AND status IN ('ready','claimed','unknown')),
    'session_status', s.status)
  FROM sessions s WHERE s.session_id = p_sid;
$$;

-- 工具目录(param_spec = v12/turn/v12_turn.sql:296-322 原样)
INSERT INTO tools (name, description, kind, handler, param_spec) VALUES
('session_stats',
 'Answer questions about this conversation itself: message counts, pending effects, session status.',
 'sql', 'v13_tool_session_stats', '{}'::jsonb),
('send_summary_email',
 'Send a summary email about this conversation to a recipient list.',
 'tool', 'worker:send_summary_email', $J${
   "tone": {
     "question": "Which tone should the summary email use?",
     "stated": "Does the user state a preferred tone for the summary email?",
     "options": {
       "formal": "Neutral, businesslike wording.",
       "friendly": "Warm, conversational wording."
     }
   },
   "audience": {
     "question": "Which audience should the summary email address?",
     "stated": "Does the user specify who receives the summary email?",
     "options": {
       "team": "The whole team mailing list.",
       "manager": "The user's direct manager only."
     }
   }
 }$J$::jsonb);

-- 默认路由带('default',v1):半开 [lo,hi),顶带 hi='Infinity';
-- 低段不插行 → 无带命中 → v13_route 兜 human(ch4.4「低置信落 human 兜底」)
-- 父版本先行(turn 5,#35):draft 建行→插带→freeze——种子顺序即部署教程
-- (任何 frozen 引用者存在前必须完成冻结;sessions 默认指向 ('default',1))
INSERT INTO v13_route_policies (policy_name, policy_version)
VALUES ('default', 1);
INSERT INTO thresholds (policy_name, policy_version, signal, band_no,
                        lo, hi, action) VALUES
-- 否决带
('default',1,'gate_off_topic',1,0.75,'Infinity','reject'),  -- 注入否决(noul 高段)
('default',1,'risk',          1,2.25,'Infinity','reject'),  -- 高风险带(score 0..3)
-- 清障带(pass = 信号达 act 档;v12 thresholds act_min 同值)
('default',1,'intent',     1,0.75,'Infinity','pass'),
('default',1,'gate_action',1,0.75,'Infinity','pass'),
('default',1,'tool',       1,0.75,'Infinity','pass'),
('default',1,'param::send_summary_email::tone',    1,0.60,'Infinity','pass'),
('default',1,'stated::send_summary_email::tone',   1,0.60,'Infinity','pass'),
('default',1,'param::send_summary_email::audience',1,0.60,'Infinity','pass'),
('default',1,'stated::send_summary_email::audience',1,0.60,'Infinity','pass'),
-- guardrail 三题通过带:预置给 guardrail 语义;DP1 的 needed 集不含
-- guardrail 题(v12_build_guardrail_questions 是 draft 后置批,非 turn 批),
-- 这些行在 DP1 inert、路由函数不消费
('default',1,'guard_pii_free',1,0.80,'Infinity','pass'),
('default',1,'guard_on_topic',1,0.80,'Infinity','pass'),
('default',1,'guard_safe',    1,0.80,'Infinity','pass');

UPDATE v13_route_policies SET state='frozen'
 WHERE policy_name='default' AND policy_version=1;
   -- 冻结 v1(turn 5,#35):触发器落 frozen_at;此后同版本 INSERT 追带被拒

-- === handler 函数体漂移也 bump revision(turn 8,#54;turn 10,#62 安全写法重写)===
-- 信封只冻函数名(schema-qualified)——两相之间 CREATE OR REPLACE 同名函数
-- 不触目录行、revision 不动 → 旧信封执行新函数体(冻结校验只证明「过去某个
-- 时刻合法」,不证明「现在还是那个函数」)。DDL event trigger 补此面。
-- **turn 10 重写(turn 9 cursor P0;两轮评审对 catalog 细节各执一词——改采
-- 「无论谁对都安全」的写法,并以本仓引擎实测为凭)**:
-- pg_event_trigger_ddl_commands() 实际列集=classid/objid/objsubid/command_tag/
-- object_type/schema_name/object_identity/in_extension/command——**有
-- command_tag、无 object_name**(旧写法 c.object_name 是幻列,触发即 42703;
-- PG18.4 实测)。分两路取证:
-- (a) ddl_command_end 面(CREATE/ALTER FUNCTION|ROUTINE 族;CREATE 的命令
--     tag 无 OR REPLACE 之分,同一 tag):c.objid JOIN pg_proc(目标行此时存活),
--     schema+名称精确匹配,签名=pg_get_function_identity_arguments(p.oid)=
--     'uuid, jsonb'(目录守卫钉死的唯一合法契约签名,与 §3.1 守卫/
--     catalog_frozen 的 oidvectortypes 比较同一常量;同名异参重载不属
--     handler 面,不 bump);handler 文本认裸名与 schema-qualified 名两种
--     形态(与目录写入形态一致——旧 object_name 匹配对 qualified handler
--     反而漏配)。
-- (b) sql_drop 面(DROP FUNCTION/ROUTINE——pg_proc 行已删,objid 不可 JOIN):
--     pg_event_trigger_dropped_objects() 的函数身份=address_names([1]=
--     schema、[2]=name;**该 SRF 的 object_name 列对函数恒为 NULL(实测,
--     表/类型才填充),不可用**);object_identity 虽含签名但文本解析脆,
--     不取。本面不做签名精确过滤(类型名拼写受可见性影响的引擎面不做
--     赌注):同名异参 overload 的 DROP 保守 bump 一次(单调计数器,后果=
--     保守弃批,无害)。
-- 两个触发器共享同一 bump 函数;tag 分工互斥(CREATE/ALTER vs DROP)——
-- 单条 DDL 恰一路触发恰一次 bump,无双计。函数体两面各以 BEGIN…EXCEPTION
-- WHEN SQLSTATE '39P03'(event trigger 上下文违约)守卫:实测矩阵=
-- ddl_commands 在 sql_drop 上下文返回空集不报错;dropped_objects 在
-- ddl_command_end 上下文报 39P03——守卫保证任一触发器激发时两面各自安全
-- 求值(只捕 39P03 上下文违约,不吞其他错误;与 α 的 OTHERS 零吸收纪律
-- 不同面——那是判断 IO 吸收面,这是目录计数器的 SRF 上下文门)。
-- ROUTINE 同义族 tag(turn 11 两通道收敛 P1;turn 12 名单同步收口):ALTER
-- ROUTINE/DROP ROUTINE 是独立 command tag 且可作用于函数(实测 PG18.4:tag
-- 序列 CREATE [OR REPLACE] FUNCTION→'CREATE FUNCTION' 无 OR REPLACE 之分、
-- ALTER ROUTINE→'ALTER ROUTINE')。**tag 名单两处必须逐 tag 同步**:trigger
-- 的 WHEN 名单(放行)与函数体内面 (a) 的 command_tag 过滤名单(消费)——
-- turn 11 只改 WHEN 侧、体内 WHERE 未随动,ALTER ROUTINE 事件被放行后在体
-- 内滤掉照样不 bump(turn 12 修:两侧同列四 tag)。'CREATE ROUTINE' 一员
-- 系 belt 预置:实测 PG18.4 无 CREATE ROUTINE 拼写(裸与 CREATE OR REPLACE
-- 均语法拒——PG 的 ROUTINE 别名只覆盖 ALTER/DROP,CREATE 无别名命令),
-- 该 tag 当前不可达;未来引擎放行此拼写则名单已含、无需改 SQL(M1-13
-- 语法拒负向断言锚住)。经 ROUTINE 删除的函数在 dropped_objects 的
-- object_type 仍报 'function',address_names 面
-- 原样兼容)。PROCEDURE 族不涉:prorettype=void 的过程过不了目录守卫(守卫
-- 钉 prorettype='jsonb'),prokind 不可经 ALTER 翻转,ROUTINE 语句作用于
-- 过程时仅 EXISTS 不命中空转(无害)。残余面:DROP SCHEMA … CASCADE/DROP
-- OWNED 的顶层 tag 不命中列表、不 bump revision——但 handler 已随级联消失,
-- 下一次 parse 的冻结校验路径 RAISE(handler 缺失→响亮失败 fail-closed),
-- 属可接受运维面(拆库级操作,非静默漂移)。
-- 双通道互斥语义(turn 9,#59)不变:分支 1 命中 handler 集(tools 行
-- kind='sql' 的 handler 文本);分支 2 只配 v13_needed_judgments(needed
-- 集的推导函数体面——OR REPLACE 换推导不触 tools 行、revision 不动,六键
-- 无漏报论证的破绽)。两分支集合不相交(M2–M4 后续 stage 的函数名均不命中
-- handler 集:canonical_state/needed/…/renew_lease/probe/attempt_ok,逐一
-- 核对;极端同管双命中则两计数器各 bump 一次——两个消费面都 stale,语义
-- 仍正确);needed 分支按名称匹配不限 schema(漏报是危险方向:异 schema
-- 同名 bump cgr 一次=保守弃批,无害)。注意:M2 加载 v13_needed_judgments
-- 自身即 bump cgr 一次(与种子 INSERT 期 revision 多行 bump 同型——计数器
-- 只在 parse 后的比对中消费,断言一律相对比较)。DP5 替换推导/引入语料
-- 版本时,语料面必须并入 cgr 或另立键(§1.3 硬契约)。过度匹配(异
-- schema 同名非 handler)只多 bump 一次(单调计数器,后果=保守弃批,
-- 无害);漏匹配仅存于引号内含点的病态标识符(write 侧守卫同 face)。
-- 置于文件末尾:本文件自身的 CREATE FUNCTION 先于触发器存在,不触发;
-- M2–M4 后续 stage 的函数在其加载时触发器已存在,但函数名均不命中
-- handler 集(见上;v13_needed_judgments 例外=设计使然的 cgr 一次 bump)。
-- SECURITY DEFINER+钉 search_path=event trigger 在任意用户 DDL
-- 期间触发,须以属主权限读 tools/meta 且免搜索路径劫持;REVOKE PUBLIC
-- (直调在事件上下文外本就报错,双保险)。**部署前置:CREATE EVENT
-- TRIGGER 需超级用户**(与 §3.1 DO 块 CREATE ROLE 的权限面同属 setup_db
-- 前提;dev setup 以超级用户连接,README 记生产前置)。
CREATE FUNCTION v13_tools_ddl_bump() RETURNS event_trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  r record;
BEGIN
  -- 面 (a):ddl_command_end——CREATE/ALTER FUNCTION|ROUTINE(objid→pg_proc 行存活)
  BEGIN
    FOR r IN
      SELECT n.nspname AS sch, p.proname AS fn,
             pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_event_trigger_ddl_commands() c
        JOIN pg_proc p ON p.oid = c.objid
        JOIN pg_namespace n ON n.oid = p.pronamespace
       WHERE c.command_tag IN ('CREATE FUNCTION','CREATE ROUTINE','ALTER FUNCTION','ALTER ROUTINE')
    LOOP
      IF r.args = 'uuid, jsonb'   -- 契约签名精确(handler 集唯一合法形态)
         AND EXISTS (SELECT 1 FROM tools t
                      WHERE t.kind = 'sql'
                        AND t.handler IN (r.fn, r.sch || '.' || r.fn)) THEN
        UPDATE v13_tools_meta SET revision = revision + 1 WHERE singleton;
      END IF;
      IF r.fn = 'v13_needed_judgments' THEN   -- 分支 2(turn 9,#59)
        UPDATE v13_tools_meta
           SET candidate_generation_revision = candidate_generation_revision + 1
         WHERE singleton;
      END IF;
    END LOOP;
  EXCEPTION WHEN SQLSTATE '39P03' THEN
    NULL;  -- sql_drop 上下文激发:面 (a) 无事可做(实测空集不报错,守卫为
           -- 对称保险),DROP 由面 (b) 处理
  END;
  -- 面 (b):sql_drop——DROP FUNCTION/ROUTINE(行已删,函数身份=address_names)
  BEGIN
    FOR r IN
      SELECT d.address_names[1] AS sch, d.address_names[2] AS fn
        FROM pg_event_trigger_dropped_objects() d
       WHERE d.object_type = 'function'
    LOOP
      IF EXISTS (SELECT 1 FROM tools t
                  WHERE t.kind = 'sql'
                    AND t.handler IN (r.fn, r.sch || '.' || r.fn)) THEN
        UPDATE v13_tools_meta SET revision = revision + 1 WHERE singleton;
      END IF;
      IF r.fn = 'v13_needed_judgments' THEN
        UPDATE v13_tools_meta
           SET candidate_generation_revision = candidate_generation_revision + 1
         WHERE singleton;
      END IF;
    END LOOP;
  EXCEPTION WHEN SQLSTATE '39P03' THEN
    NULL;  -- ddl_command_end 上下文激发:面 (b) 无事可做(实测报 39P03 被
           -- 守卫接住),CREATE/ALTER 由面 (a) 处理
  END;
END $$;
REVOKE EXECUTE ON FUNCTION v13_tools_ddl_bump() FROM PUBLIC;
CREATE EVENT TRIGGER trg_tools_ddl_bump
  ON ddl_command_end
WHEN tag IN ('CREATE FUNCTION', 'CREATE ROUTINE', 'ALTER FUNCTION', 'ALTER ROUTINE')
  EXECUTE FUNCTION v13_tools_ddl_bump();
CREATE EVENT TRIGGER trg_tools_ddl_bump_drop
  ON sql_drop
WHEN tag IN ('DROP FUNCTION', 'DROP ROUTINE')
  EXECUTE FUNCTION v13_tools_ddl_bump();
