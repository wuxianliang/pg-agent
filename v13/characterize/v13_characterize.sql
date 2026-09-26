BEGIN;

-- =========================================================================
-- DP5 characterize: text-search extension + production index + canary
-- fixture + definition swap (recall / recall_count / extract_spans v2)
-- + verify v2 (8th check). Gate = test_characterize.py (K-R).
-- Engine facts: pgembed PG18.4 + extension 0.4.0 (installed_version 实测
-- 2026-09-25, pgembed 捆绑 pin ad4d3b7; 历史记载 0.1.0 = DP5 刻画时代、
-- 0.3.0 = mgraph_assembly 时代, 均已被 stage 库 DROP/CREATE 重建覆盖).
-- Bind operator lives in
-- pg_catalog; planner support rewrites any expr to bind_query(expr, oid);
-- Custom Scan provider = 'Stannum Text Search Scan'.
-- =========================================================================

CREATE EXTENSION IF NOT EXISTS stannum;

CREATE TABLE v13_canary_docs (
  doc_no int PRIMARY KEY,
  body   text NOT NULL
);
INSERT INTO v13_canary_docs VALUES
 (1, repeat('z', 200)),
 (2, 'plain english document about quasars and redshift surveys'),
 (3, '東京タワーは電波塔である');

CREATE INDEX ix_v13_canary ON v13_canary_docs
  USING stannum (body) WITH (long_tokens='split', max_token_bytes=64);

CREATE INDEX ix_chunks_stannum ON chunks USING stannum (body)
  WITH (tokenizer=jieba);

CREATE OR REPLACE FUNCTION v13_extract_spans(p_body text, p_terms jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_tinql text; v_open text; v_close text; v_i int;
  v_tagged text; v_from int; v_cpos int; v_epos int;
  v_tags int := 0; v_total int := 0;
  v_bstart bigint; v_bend bigint;
  v_out jsonb := '[]'::jsonb;
BEGIN
  IF p_body IS NULL THEN RETURN '[]'::jsonb; END IF;
  IF p_terms IS NULL OR jsonb_typeof(p_terms) IS DISTINCT FROM 'object'
     OR jsonb_typeof(p_terms->'tinql') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: stannum span query must be {"tinql":<string>}'
      USING ERRCODE = 'V3005';
  END IF;
  v_tinql := p_terms->>'tinql';
  v_open := NULL;
  FOR v_i IN 1 .. 4 LOOP
    IF position(chr(v_i * 2 - 1) IN p_body) = 0
       AND position(chr(v_i * 2) IN p_body) = 0 THEN
      v_open := chr(v_i * 2 - 1); v_close := chr(v_i * 2); EXIT;
    END IF;
  END LOOP;
  IF v_open IS NULL THEN
    RAISE EXCEPTION
      'v13: body contains all highlight sentinels (spans unavailable)'
      USING ERRCODE = 'V3005';
  END IF;
  v_tagged := stannum.highlight(p_body, v_open, v_close,
    stannum.bind_query(v_tinql, 'ix_chunks_stannum'::regclass));
  v_from := 1;
  LOOP
    EXIT WHEN v_total >= 256;
    v_cpos := position(v_open IN substring(v_tagged FROM v_from));
    EXIT WHEN v_cpos = 0;
    v_cpos := v_cpos + v_from - 1;
    v_epos := position(v_close IN substring(v_tagged FROM v_cpos + 1));
    EXIT WHEN v_epos = 0;
    v_epos := v_epos + v_cpos;
    v_bstart := octet_length(left(v_tagged, v_cpos)) + 1 - (v_tags + 1);
    v_bend := octet_length(left(v_tagged, v_epos - 1)) - (v_tags + 1);
    IF v_bstart >= 1 AND v_bend >= v_bstart THEN
      v_out := v_out || jsonb_build_array(jsonb_build_array(v_bstart, v_bend));
      v_total := v_total + 1;
    END IF;
    v_tags := v_tags + 2;
    v_from := v_epos + 1;
  END LOOP;
  RETURN v_out;
END $$;

CREATE OR REPLACE FUNCTION v13_recall(p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 numeric, spans jsonb)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_boosts jsonb;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_recall args out of bounds'
      USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  PERFORM v13_tinql_terms(p_tinql);
  v_boosts := v13_policy('recall_boosts');
  IF v_boosts IS NULL
     OR jsonb_typeof(v_boosts->'boosts') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: invalid recall_boosts policy shape'
      USING ERRCODE = 'V3005';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_boosts->'boosts')) THEN
    RAISE EXCEPTION
      'v13: recall_boosts must stay empty until boost landing'
      USING ERRCODE = 'V3005';
  END IF;
  RETURN QUERY EXECUTE
    'SELECT c.content_hash, '
 || 'stannum.full_score(c.ctid)::numeric AS bm25, '
 || 'v13_extract_spans(c.body, jsonb_build_object(''tinql'', $1)) '
 || 'FROM chunks c JOIN v13_sources src '
 || 'ON src.source_hash = c.source_hash AND src.superseded_by IS NULL '
 || 'WHERE c.body ==> $1 '
 || 'ORDER BY bm25 DESC, c.content_hash ASC LIMIT $2'
    USING p_tinql, p_k;
END $$;

CREATE OR REPLACE FUNCTION v13_recall_count(p_tinql text) RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_cnt bigint;
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: tinql must not be NULL' USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN 0; END IF;
  PERFORM v13_tinql_terms(p_tinql);
  EXECUTE 'SELECT count(*) FROM chunks c '
       || 'JOIN v13_sources src ON src.source_hash = c.source_hash '
       || 'AND src.superseded_by IS NULL '
       || 'WHERE c.body ==> $1'
    INTO v_cnt USING p_tinql;
  RETURN v_cnt;
END $$;

CREATE OR REPLACE FUNCTION v13_verify_chunks(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_bad_selfcert bigint; v_bad_orphan bigint; v_bad_source bigint;
  v_bad_ref bigint; v_plan text := ''; v_pending int; v_meta boolean;
  v_bad_backref bigint; v_orphan bigint; v_guc text;
  v_stan_bad bigint;
  v_checks jsonb := '[]'::jsonb; v_all_ok boolean;
  v_line record;
BEGIN
  SELECT count(*) INTO v_bad_selfcert FROM chunks
   WHERE content_hash IS DISTINCT FROM v13_body_hash(body);
  SELECT count(*) INTO v_bad_orphan FROM chunks c
   WHERE NOT EXISTS (SELECT 1 FROM artifacts a
                      WHERE a.content_hash = c.content_hash
                        AND a.kind = 'chunk');
  SELECT count(*) INTO v_bad_source FROM chunks c
   WHERE NOT EXISTS (SELECT 1 FROM v13_sources s
                      WHERE s.source_hash = c.source_hash);
  SELECT count(*) INTO v_bad_ref FROM artifacts a
   CROSS JOIN LATERAL jsonb_array_elements(
        coalesce(a.inline->'query_side'->'candidates', '[]'::jsonb)) cand
   WHERE a.kind = 'context'
     AND EXISTS (SELECT 1 FROM artifacts x
                  WHERE x.content_hash = cand->>'content_hash'
                    AND x.kind = 'chunk')
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = cand->>'content_hash');
  SELECT count(*) INTO v_bad_backref FROM artifacts a
   WHERE a.kind = 'chunk'
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = a.content_hash)
     AND v13_chunk_referenced(a.content_hash);
  SELECT count(*) INTO v_orphan FROM artifacts a
   WHERE a.kind = 'chunk'
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = a.content_hash);
  v_guc := current_setting('enable_seqscan');
  BEGIN
    EXECUTE 'SET enable_seqscan = off';
    FOR v_line IN EXECUTE
      'EXPLAIN (COSTS OFF) SELECT 1 FROM chunks WHERE body_tsv @@
         websearch_to_tsquery(''english''::regconfig, ''quasar'')' LOOP
      v_plan := v_plan || v_line."QUERY PLAN";
    END LOOP;
  EXCEPTION
    WHEN query_canceled THEN
      EXECUTE format('SET enable_seqscan = %s', v_guc);
      RAISE;
    WHEN OTHERS THEN
      EXECUTE format('SET enable_seqscan = %s', v_guc);
      RAISE;
  END;
  EXECUTE format('SET enable_seqscan = %s', v_guc);
  v_pending := gin_clean_pending_list('public.ix_chunks_tsv'::regclass);
  SELECT EXISTS (SELECT 1 FROM v13_chunks_meta WHERE singleton)
    INTO v_meta;
  SELECT count(*) INTO v_stan_bad
    FROM stannum.verify_index('ix_chunks_stannum'::regclass, true)
   WHERE severity IN ('error', 'warning');
  v_checks := jsonb_build_array(
    jsonb_build_object('name','self_cert','ok', v_bad_selfcert = 0,
      'detail', jsonb_build_object('violations', v_bad_selfcert)),
    jsonb_build_object('name','artifact_exists','ok', v_bad_orphan = 0,
      'detail', jsonb_build_object('violations', v_bad_orphan)),
    jsonb_build_object('name','source_ledger','ok', v_bad_source = 0,
      'detail', jsonb_build_object('violations', v_bad_source)),
    jsonb_build_object('name','reference_resolvable','ok', v_bad_ref = 0,
      'detail', jsonb_build_object('violations', v_bad_ref)),
    jsonb_build_object('name','index_usable',
      'ok', position('ix_chunks_tsv' in v_plan) > 0,
      'detail', jsonb_build_object('pending_flushed', v_pending)),
    jsonb_build_object('name','meta_present', 'ok', v_meta,
      'detail', jsonb_build_object('generation',
        (SELECT generation FROM v13_chunks_meta WHERE singleton))),
    jsonb_build_object('name','artifact_backref', 'ok', v_bad_backref = 0,
      'detail', jsonb_build_object('referenced_orphans', v_bad_backref,
                                   'orphan_artifacts_report', v_orphan)),
    jsonb_build_object('name','stannum_verify_index', 'ok', v_stan_bad = 0,
      'detail', jsonb_build_object('index', 'ix_chunks_stannum',
                                   'findings', v_stan_bad)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_chunks failed: %', v_checks
      USING ERRCODE = 'V3004';
  END IF;
  RETURN jsonb_build_object('version', 2, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;

COMMIT;
