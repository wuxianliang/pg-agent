BEGIN;

-- =========================================================================
-- DP6 memory (v13_memory.sql): transcript verbatim layer (§4.4) + watermark
-- freshness (F10) + structured layer stannum index on decisions(question).
-- Design: docs/designs/v13-context-on-pg.md §4.4/§9/§10 (p99 gate). Tutorial
-- ch13:58-59 (tick), ch13:64-79 (sweeper, not metronome). Contracts: DP4 ①③
-- (independent table/index), DP5 (post-characterize stannum library).
-- File order = load order. Owner-plane builders; zero DEFINER (DP4 OQ5 同构).
-- Engine-qualified calls: exactly stannum.full_score x1 (reader EXECUTE) +
-- stannum.verify_index x2 (verify) — gate K4 asserts the counts.
-- =========================================================================

-- === 逐字层投影表(§9 五列逐字;独立表独立索引=文档/记忆语料分区,
--     DP4 契约⑦;v1 每策展事件一行 seq_from=seq_to,OQ8)。行不可变
--     (UPDATE 拒);DELETE 留给全量重建(owner 平面——无 retention 引用面,
--     记忆行不被 manifest/decisions 引用)。自证 CHECK+FK 源事件。 ===
CREATE TABLE transcript_chunks (
  session_id   uuid NOT NULL REFERENCES sessions (session_id),
  seq_from     bigint NOT NULL CHECK (seq_from >= 0),
  seq_to       bigint NOT NULL CHECK (seq_to >= seq_from),
  body         text NOT NULL CHECK (octet_length(body) > 0),
  content_hash text NOT NULL,
  PRIMARY KEY (session_id, seq_from),
  FOREIGN KEY (session_id, seq_from) REFERENCES events (session_id, seq),
  CONSTRAINT v13_transcript_hash_selfcheck
    CHECK (content_hash = v13_body_hash(body))
);

-- 记忆语料索引(stannum 默认配置,单索引纪律;OQ9:记忆语料 CJK 为主,
-- 刻画后直接 stannum=§7 既裁路径;tsvector 对 CJK 记忆零召回=玩具)
CREATE INDEX ix_transcript_stannum ON transcript_chunks USING stannum (body);

CREATE FUNCTION v13_transcript_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION
    'v13: transcript_chunks rows are immutable (% on % %/%)',
    TG_OP, TG_TABLE_NAME, OLD.session_id, OLD.seq_to
    USING ERRCODE = 'V3006';
END $$;
CREATE TRIGGER trg_transcript_immutable
  BEFORE UPDATE ON transcript_chunks
  FOR EACH ROW EXECUTE FUNCTION v13_transcript_immutable();

-- === 水印(OQ5):投影覆盖上界(仅策展族事件计入分母——编排事件
--     (turn/route/effect_done)永不投影,计入则 lag 恒涨永降级) ===
CREATE FUNCTION v13_transcript_watermark(p_sid uuid) RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT coalesce(max(seq_to), -1) FROM transcript_chunks
   WHERE session_id = p_sid;
$$;

-- 新鲜度谓词(F10 的载体):lag=max 策展非空体 seq−watermark(空体
--     不可投影,入分母则尾部空体致 watermark 永滞/lag 永不归零——dp6.1
--     P1-1,与 rebuild 策展口径对齐);超界→degraded
-- +NOTICE(运维可见);消费契约(§1.4 DP7④):degraded=true 时消费侧
-- 不得以记忆层为可靠召回面,须落审计事件并降级——recall 平面纯 SELECT
-- (DP1 角色分裂)不可写事件,附 A #9。
CREATE FUNCTION v13_transcript_freshness(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_wm bigint; v_max bigint; v_lag bigint; v_cap jsonb; v_n int;
BEGIN
  SELECT coalesce(max(seq_to), -1) INTO v_wm FROM transcript_chunks
   WHERE session_id = p_sid;
  SELECT coalesce(max(e.seq), -1) INTO v_max FROM events e
   WHERE e.session_id = p_sid
     AND e.type IN ('user/message','llm/message')
     AND coalesce(e.payload->>'text', '') <> '';
  v_lag := v_max - v_wm;
  v_cap := v13_policy('memory_stack');
  IF v_cap IS NULL
     OR jsonb_typeof(v_cap->'max_lag_events') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid memory_stack policy shape'
      USING ERRCODE = 'V3006';
  END IF;
  v_n := (v_cap->>'max_lag_events')::int;
  IF v_n < 0 THEN
    RAISE EXCEPTION 'v13: invalid memory_stack policy values'
      USING ERRCODE = 'V3006';
  END IF;
  IF v_lag > v_n THEN
    RAISE NOTICE
      'v13: transcript projection lag % exceeds max_lag_events % for session % (memory recall degraded)',
      v_lag, v_n, p_sid;
  END IF;
  RETURN jsonb_build_object('watermark', v_wm, 'max_curated_seq', v_max,
    'lag', v_lag, 'max_lag', v_n, 'degraded', v_lag > v_n);
END $$;

-- === tick 批量构建(ch13:58-59 逐字形态:每 tick 至多 100 行):增量
--     (seq>watermark 的策展事件,空体跳过)、幂等(ON CONFLICT DO
--     NOTHING)、确定性(session_id 升序逐会话;v1 会话全扫——空转成本
--     台账触发项,§7)。可重建=DELETE 后重跑(owner 平面)。 ===
CREATE FUNCTION v13_rebuild_transcript_chunks(p_limit int DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_rows int := 0; v_n int; v_wm bigint; r record;
BEGIN
  IF p_limit IS NULL OR p_limit < 1 THEN
    RAISE EXCEPTION 'v13: rebuild limit must be >= 1'
      USING ERRCODE = 'V3006';
  END IF;
  FOR r IN SELECT e.session_id, max(e.seq) AS mseq
             FROM events e
            WHERE e.type IN ('user/message','llm/message')
            GROUP BY e.session_id
            ORDER BY e.session_id
  LOOP
    EXIT WHEN v_rows >= p_limit;
    SELECT coalesce(max(t.seq_to), -1) INTO v_wm
      FROM transcript_chunks t WHERE t.session_id = r.session_id;
    IF r.mseq <= v_wm THEN
      CONTINUE;                      -- 该会话已投影到头
    END IF;
    INSERT INTO transcript_chunks (session_id, seq_from, seq_to, body,
                                   content_hash)
    SELECT e.session_id, e.seq, e.seq, e.payload->>'text',
           v13_body_hash(e.payload->>'text')
      FROM events e
     WHERE e.session_id = r.session_id
       AND e.type IN ('user/message','llm/message')
       AND e.seq > v_wm
       AND coalesce(e.payload->>'text', '') <> ''
     ORDER BY e.seq
     LIMIT least(p_limit - v_rows, 100)
    ON CONFLICT (session_id, seq_from) DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_rows := v_rows + v_n;
  END LOOP;
  RETURN jsonb_build_object('rows_projected', v_rows);
END $$;

-- === 记忆召回 reader(签名冻结 (uuid,text,int)→TABLE 三列,§1.4 DP7④):
--     只读 transcript_chunks(F10 fail-closed——零 events 回退读路径);
--     per-session 隔离(记忆是会话私有面);==>' 只在本函数族体内经
--     EXECUTE(三禁;文件 11 源码扫描计数=恰 1);入口 v13_tinql_terms
--     自产文法守卫(DP5 同款);排序 分值 DESC,content_hash ASC 终裁。 ===
CREATE FUNCTION v13_transcript_recall(p_sid uuid, p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 numeric, seq_from bigint)
LANGUAGE plpgsql STABLE AS $$
DECLARE v_cnt bigint;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_transcript_recall args out of bounds'
      USING ERRCODE = 'V3006';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  PERFORM v13_tinql_terms(p_tinql);           -- fail-closed 信封(G-ctx3 同族)
  RETURN QUERY EXECUTE
    'SELECT t.content_hash, '
 || 'stannum.full_score(t.ctid)::numeric AS bm25, t.seq_from '
 || 'FROM transcript_chunks t '
 || 'WHERE t.session_id = $1 AND t.body ==> $3 '
 || 'ORDER BY bm25 DESC, t.content_hash ASC LIMIT $2'
    USING p_sid, p_k, p_tinql;
END $$;

-- === 结构化层(§4.4:stannum 建在 decisions.question——append-only
--     不可变列=不可变段,零 fold churn 的「理想负载」;消费者=语义决策
--     缓存,§12 台账,机制不做) ===
CREATE INDEX ix_decisions_question_stannum ON decisions USING stannum (question);

-- === 记忆面校验器(v13_verify_chunks 同族;手动可调+gate;夜跑 cron 扩展
--     不做——DP4 job 保持唯一 verify 面,§7 台账) ===
CREATE FUNCTION v13_verify_memory(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_bad bigint; v_orphan bigint; v_pol boolean;
  v_ts_bad bigint; v_dq_bad bigint;
  v_checks jsonb; v_all_ok boolean;
BEGIN
  SELECT count(*) INTO v_bad FROM transcript_chunks
   WHERE content_hash IS DISTINCT FROM v13_body_hash(body);   -- ①自证
  SELECT count(*) INTO v_orphan FROM transcript_chunks t
   WHERE NOT EXISTS (SELECT 1 FROM events e
                      WHERE e.session_id = t.session_id
                        AND e.seq = t.seq_from);               -- ②源事件在
  SELECT EXISTS (SELECT 1 FROM v13_policies
                  WHERE name = 'memory_stack' AND active)
    INTO v_pol;                                               -- ③策略行在场
  SELECT count(*) INTO v_ts_bad                               -- ④transcript 索引
    FROM stannum.verify_index('ix_transcript_stannum'::regclass, true)
   WHERE severity IN ('error','warning');
  SELECT count(*) INTO v_dq_bad                               -- ⑤decisions 索引
    FROM stannum.verify_index('ix_decisions_question_stannum'::regclass, true)
   WHERE severity IN ('error','warning');
  v_checks := jsonb_build_array(
    jsonb_build_object('name','self_cert','ok', v_bad = 0,
      'detail', jsonb_build_object('violations', v_bad)),
    jsonb_build_object('name','source_events','ok', v_orphan = 0,
      'detail', jsonb_build_object('violations', v_orphan)),
    jsonb_build_object('name','policy_present','ok', v_pol,
      'detail', jsonb_build_object('name', 'memory_stack')),
    jsonb_build_object('name','transcript_verify_index','ok', v_ts_bad = 0,
      'detail', jsonb_build_object('findings', v_ts_bad)),
    jsonb_build_object('name','decisions_verify_index','ok', v_dq_bad = 0,
      'detail', jsonb_build_object('findings', v_dq_bad)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_memory failed: %', v_checks
      USING ERRCODE = 'V3006';
  END IF;
  RETURN jsonb_build_object('version', 1, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;

-- === 策略种子(滞后上界,F10) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('memory_stack', 1, '{"max_lag_events":16}'::jsonb, true);

-- === tick=扫地僧(ch13:58-59;调度是行不是节拍器——turn 推进仍靠
--     settle,DP4 §3.7 守卫降级同款;builder 恒手动可调,正确性零依赖) ===
DO $cron$
DECLARE v_ext boolean;
BEGIN
  BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
  EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'v13: pg_cron unavailable (%) — transcript sweep falls back to external scheduler; v13_rebuild_transcript_chunks() stays callable', SQLERRM;
    RETURN;
  END;
  IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'v13-sweep-transcript') THEN
    PERFORM cron.schedule('v13-sweep-transcript', '*/5 * * * *',
                          $job$SELECT v13_rebuild_transcript_chunks(100)$job$);
  END IF;
END
$cron$;
-- 本 stage 库 cron.job 恰两条(DP4 verify + 本 transcript sweep);
-- ch13 四 job 全景的 requeue/recover 仍归驱动(§12 YAGNI 触发未至,附 A #8)。

-- === ACL 全量块(文件真末尾) ===
REVOKE EXECUTE ON FUNCTION
  v13_transcript_watermark(uuid), v13_transcript_freshness(uuid),
  v13_transcript_recall(uuid,text,int),
  v13_rebuild_transcript_chunks(int), v13_verify_memory(boolean),
  v13_transcript_immutable()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_transcript_watermark(uuid), v13_transcript_freshness(uuid),
  v13_transcript_recall(uuid,text,int)
TO v13_recall, v13_resolve, v13_route;
             -- 读面三角色(未来装配/审计消费;recall=reader 主消费面)
GRANT SELECT ON transcript_chunks TO v13_recall, v13_resolve, v13_route;
-- 写/运维面(v13_rebuild_transcript_chunks/v13_verify_memory):仅 owner
-- (cron job 以 owner 身份跑;DP4 chunks 同构);transcript_chunks DML 对
-- 运行角色零授权(gate N 组负向);触发器函数 REVOKE 后仅属主可挂。

COMMIT;
