-- 扫描恢复 + worker 死亡回收(队列可丢;v12_requeue_stale 血统,
-- v12/queue/v12_queue.sql:62-79;评审修正 P0-5 + turn 3,#13 kind 分流 +
-- turn 8,#55 cap 共用)。
-- (a1) lease 过期且 cap 内的 judge 行(attempt_no<cap,尚可再领):CAS 回收
--     ——单条 UPDATE 谓词即比较,**只推进 fence**(turn 9,#58,第八轮双通道
--     收敛 P0:旧实现同时递增 attempt_no,claim(1)→requeue 置 2→claim(3)→
--     requeue 置 4→claim belt 4<4 假——ready-但-永不可领,两次 worker 死亡
--     即永久楔死且 (b) 每轮重发 wake;CAS 失效由 fence+1 单扛即可,「死」
--     worker 的 (attempt,fence) 立即失效,其后 complete 只得 'stale')→ready
--     重放(纯判断幂等:decisions answer-once+受限填充,重放无外部副作用)。
--     attempt_no 保持「claim 次数」单一语义,唯一递增点=claim(§3.1 claim
--     注的不变式);cap 判定与 enqueue/claim 共用 v13_attempt_ok(turn 8,
--     #55):回收无上限的旧病(turn 8 修)与 belt 击穿(turn 9 修)合并封死。
-- (a1') lease 过期且 attempt_no 已达 cap 的 judge 行(死去的 claim 是第
--     cap 次领取,belt 后不可再领):转**可结算终态 failed**(error=
--     lease_exhausted;fence 照常推进使死 worker 令牌失效——attempt_no 不动,
--     claim 次数单一语义 turn 9 #58)+唤醒
--     settle——驱动收 wake 后重 advance:① 不阻塞(failed 非未决)→③
--     enqueue 拒重挂(同 cap)→turn/end(attempts_exhausted)+sessions
--     failed(turn 7,#49 既有终结路径,事件账闭环)。选 failed 而非 unknown:
--     judge 无外部副作用、可结算(unknown 是 tool/llm 族的墙)。
-- (a2) 其余 kind(tool/llm/human/context_refresh)→unknown(外部副作用
--     可能已发生,不盲重放——对齐仓库不变量「unknown 不盲目重放」,墙,
--     ch12 显式 resolve 是唯一出口;unknown 本身即终态面,无需 cap)。
-- (b) 全部 ready 行+(a1') 新转 failed 行重发唤醒(重发无害:单活跃索引+
--     enqueue 幂等+claim 只领 ready;failed 行的 wake 是 settle 请求——驱动
--     对终态 effect 的动作=重 advance,幂等;消息仅唤醒可丢)。
-- unknown 行(含 (a2) 新增)不动:不是待办,是墙。
-- 计数语义(v12 血统:n=重发数;turn 3 拆四项+turn 8 增 lease_exhausted
-- 便于运维观测)。
-- 驱动周期调用(README 运维注记;pg_cron tick 是台账项,DP1 不引入)。
-- G-ctx8 幂等重推的地基(不依赖消息)。
CREATE FUNCTION v13_requeue_stale() RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_j int; v_u int; v_w int := 0; v_k int; v_f int; r record; v_id uuid;
  v_ids uuid[];
BEGIN
  UPDATE effects
     SET status='ready', fence=fence+1,            -- attempt_no 不动(turn 9,#58)
         lease_owner=NULL, lease_until=NULL
   WHERE status='claimed' AND kind='judge'
     AND lease_until < clock_timestamp()
     AND v13_attempt_ok('judge', attempt_no);       -- 共用 cap(turn 8,#55)
  GET DIAGNOSTICS v_j = ROW_COUNT;                   -- (a1) judge 回收重放数
  WITH capped AS (
    UPDATE effects
       SET status='failed', fence=fence+1,         -- attempt_no 不动(turn 9,#58)
           lease_owner=NULL, lease_until=NULL,
           error=jsonb_build_object('code','lease_exhausted')
     WHERE status='claimed' AND kind='judge'
       AND lease_until < clock_timestamp()
       AND NOT v13_attempt_ok('judge', attempt_no)   -- 超 cap:可结算终态
    RETURNING effect_id)
  SELECT coalesce(array_agg(effect_id), '{}'::uuid[]) INTO v_ids FROM capped;
  v_f := coalesce(array_length(v_ids, 1), 0);        -- (a1') lease 耗竭终态数
  UPDATE effects
     SET status='unknown', fence=fence+1,           -- attempt_no 不动(turn 9,#58)
         lease_owner=NULL, lease_until=NULL
   WHERE status='claimed' AND kind <> 'judge'
     AND lease_until < clock_timestamp();
  GET DIAGNOSTICS v_u = ROW_COUNT;                   -- (a2) 转墙数
  FOR r IN SELECT effect_id FROM effects WHERE status='ready' LOOP
    PERFORM v13_send_work(r.effect_id);              -- 唤醒重建(可丢消息的地基)
    v_w := v_w + 1;
  END LOOP;
  FOREACH v_id IN ARRAY v_ids LOOP
    PERFORM v13_send_work(v_id);                     -- 唤醒 settle(turn 8,#55)
  END LOOP;
  SELECT count(*) INTO v_k FROM effects WHERE status='unknown';
  RETURN jsonb_build_object('reclaimed_ready', v_j, 'walled_unknown', v_u,
                            'lease_exhausted', v_f,
                            'woken_ready', v_w, 'walls_total', v_k);
END $$;

-- worker 心跳(turn 3,#10):多批跨事务期间续租。fence 失配(被回收/重挂)
-- → false,worker 必须立即放弃本 effect(旧 fence 已失效,不得再 complete)。
CREATE FUNCTION v13_renew_lease(p_effect uuid, p_fence bigint,
                                p_ms int DEFAULT 60000) RETURNS boolean
LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_ok boolean;
BEGIN
  UPDATE effects
     SET lease_until = clock_timestamp()
                     + make_interval(secs => p_ms/1000.0)
   WHERE effect_id = p_effect AND fence = p_fence AND status = 'claimed'
  RETURNING true INTO v_ok;
  RETURN coalesce(v_ok, false);
END $$;

REVOKE EXECUTE ON FUNCTION v13_requeue_stale() FROM PUBLIC;   -- turn 3,#6:
GRANT  EXECUTE ON FUNCTION v13_requeue_stale() TO v13_route;  -- M4 stage 授权
REVOKE EXECUTE ON FUNCTION v13_renew_lease(uuid,bigint,int) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION v13_renew_lease(uuid,bigint,int) TO v13_route;
