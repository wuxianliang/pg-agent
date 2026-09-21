BEGIN;

-- =========================================================================
-- DP5 recall (v13_recall.sql): T0 tsvector recall + TINQL compiler +
-- envelope/assemble wiring + cgr corpus wiring.
-- Design: docs/designs/v13-context-on-pg.md §4.1/§4.6/§4.7/§4.8/§7/§8/§9/
-- §10 G-ctx3. Contracts: DP1 §1.3 (#59), DP2 §1.4, DP3 §1.4, DP4 §1.4 ①-⑨.
-- File order = load order. Zero dependency on the text-search extension
-- (invariant 7): this file contains no bind-operator literals and no
-- extension-qualified calls, in code or in comments (gate G asserts).
-- =========================================================================

CREATE FUNCTION v13_query_segments(p_query text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_chars text[]; v_n int; v_i int; v_ch text; v_cp int;
  v_class text; v_cur_class text := 'sep'; v_cur text := '';
  v_texts text[] := '{}'; v_cnt int := 0;
BEGIN
  IF p_query IS NULL OR p_query = '' THEN RETURN '[]'::jsonb; END IF;
  IF octet_length(p_query) > 4096 THEN
    RAISE EXCEPTION 'v13: query exceeds max bytes (4096)'
      USING ERRCODE = 'V3005';
  END IF;
  v_chars := regexp_split_to_array(p_query, '');
  v_n := coalesce(array_length(v_chars, 1), 0);
  FOR v_i IN 1 .. v_n LOOP
    v_ch := v_chars[v_i];
    IF v_ch IS NULL OR v_ch = '' THEN
      CONTINUE;
    END IF;
    v_cp := ascii(v_ch);
    IF v_ch ~ '[a-zA-Z0-9]' THEN
      v_class := 'latin';
    ELSIF (v_cp BETWEEN 12352 AND 12543)
       OR (v_cp BETWEEN 13312 AND 19903)
       OR (v_cp BETWEEN 19968 AND 40959)
       OR (v_cp BETWEEN 44032 AND 55215)
       OR (v_cp BETWEEN 63744 AND 64255)
    THEN
      v_class := 'cjk';
    ELSE
      v_class := 'sep';
    END IF;
    IF v_class = v_cur_class THEN
      v_cur := v_cur || v_ch;
    ELSE
      IF v_cur_class <> 'sep' THEN
        IF octet_length(v_cur) > 256 THEN
          RAISE EXCEPTION 'v13: query segment exceeds max bytes (256)'
            USING ERRCODE = 'V3005';
        END IF;
        v_texts := v_texts || v_cur; v_cnt := v_cnt + 1;
        IF v_cnt > 64 THEN
          RAISE EXCEPTION 'v13: query exceeds max segments (64)'
            USING ERRCODE = 'V3005';
        END IF;
      END IF;
      v_cur := v_ch; v_cur_class := v_class;
    END IF;
  END LOOP;
  IF v_cur_class <> 'sep' THEN
    IF octet_length(v_cur) > 256 THEN
      RAISE EXCEPTION 'v13: query segment exceeds max bytes (256)'
        USING ERRCODE = 'V3005';
    END IF;
    v_texts := v_texts || v_cur; v_cnt := v_cnt + 1;
    IF v_cnt > 64 THEN
      RAISE EXCEPTION 'v13: query exceeds max segments (64)'
        USING ERRCODE = 'V3005';
    END IF;
  END IF;
  RETURN (SELECT coalesce(jsonb_agg(t ORDER BY ord), '[]'::jsonb)
            FROM unnest(v_texts) WITH ORDINALITY AS u(t, ord));
END $$;

CREATE FUNCTION v13_build_tinql(p_query text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(string_agg('"' || s || '"', ' AND '), '')
    FROM jsonb_array_elements_text(v13_query_segments(p_query)) AS s
$$;

CREATE FUNCTION v13_tinql_terms(p_tinql text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_parts text[]; v_n int; v_i int; v_inner text;
  v_texts text[] := '{}';
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: tinql must not be NULL' USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN '[]'::jsonb; END IF;
  v_parts := string_to_array(p_tinql, ' AND ');
  v_n := array_length(v_parts, 1);
  FOR v_i IN 1 .. v_n LOOP
    v_inner := v_parts[v_i];
    IF length(v_inner) < 2
       OR left(v_inner, 1) <> '"'
       OR right(v_inner, 1) <> '"'
       OR position('"' in substring(v_inner FROM 2 FOR length(v_inner) - 2)) > 0
    THEN
      RAISE EXCEPTION
        'v13: tinql not in emitted grammar (quoted segments joined by AND)'
        USING ERRCODE = 'V3005';
    END IF;
    v_inner := substring(v_inner FROM 2 FOR length(v_inner) - 2);
    IF octet_length(v_inner) = 0 OR octet_length(v_inner) > 256 THEN
      RAISE EXCEPTION 'v13: tinql segment out of bounds'
        USING ERRCODE = 'V3005';
    END IF;
    v_texts := v_texts || v_inner;
  END LOOP;
  IF array_length(v_texts, 1) > 64 THEN
    RAISE EXCEPTION 'v13: tinql exceeds max segments (64)'
      USING ERRCODE = 'V3005';
  END IF;
  RETURN (SELECT coalesce(jsonb_agg(t ORDER BY ord), '[]'::jsonb)
            FROM unnest(v_texts) WITH ORDINALITY AS u(t, ord));
END $$;

CREATE FUNCTION v13_recall(p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 numeric, spans jsonb)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_segs jsonb; v_seg text; v_q tsquery;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_recall args out of bounds'
      USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  v_segs := v13_tinql_terms(p_tinql);
  v_q := NULL;
  FOR v_seg IN SELECT jsonb_array_elements_text(v_segs) LOOP
    v_q := CASE WHEN v_q IS NULL
              THEN phraseto_tsquery('english'::regconfig, v_seg)
              ELSE v_q && phraseto_tsquery('english'::regconfig, v_seg) END;
  END LOOP;
  RETURN QUERY
  SELECT c.content_hash,
         ts_rank(c.body_tsv, v_q)::numeric,
         v13_extract_spans(c.body, v_segs)
    FROM chunks c
    JOIN v13_sources src
      ON src.source_hash = c.source_hash AND src.superseded_by IS NULL
   WHERE c.body_tsv @@ v_q
   ORDER BY 2 DESC, 1 ASC
   LIMIT p_k;
END $$;

CREATE FUNCTION v13_recall_count(p_tinql text) RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_segs jsonb; v_seg text; v_q tsquery;
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: tinql must not be NULL' USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN 0; END IF;
  v_segs := v13_tinql_terms(p_tinql);
  v_q := NULL;
  FOR v_seg IN SELECT jsonb_array_elements_text(v_segs) LOOP
    v_q := CASE WHEN v_q IS NULL
              THEN phraseto_tsquery('english'::regconfig, v_seg)
              ELSE v_q && phraseto_tsquery('english'::regconfig, v_seg) END;
  END LOOP;
  RETURN (SELECT count(*) FROM chunks c
            JOIN v13_sources src
              ON src.source_hash = c.source_hash AND src.superseded_by IS NULL
           WHERE c.body_tsv @@ v_q);
END $$;

CREATE FUNCTION v13_recall_candidates(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_txt text; v_tinql text; v_pol jsonb;
  v_kb numeric; v_wr numeric; v_kmax numeric; v_tmo numeric;
  v_cnt bigint; v_k int;
BEGIN
  SELECT coalesce(g.payload->>'text', '') INTO v_txt
    FROM v13_goals g
   WHERE g.session_id = p_sid
   ORDER BY g.seq DESC LIMIT 1;
  v_tinql := CASE WHEN coalesce(v_txt, '') = '' THEN ''
                  ELSE v13_build_tinql(v_txt) END;
  IF v_tinql = '' THEN
    RETURN jsonb_build_object('k', 0, 'matched', 0, 'candidates', '[]'::jsonb);
  END IF;
  v_pol := v13_policy('recall_k');
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol->'k_base') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'widen_ratio') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'k_max') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'timeout_ms') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid recall_k policy shape'
      USING ERRCODE = 'V3005';
  END IF;
  v_kb := (v_pol->>'k_base')::numeric; v_wr := (v_pol->>'widen_ratio')::numeric;
  v_kmax := (v_pol->>'k_max')::numeric; v_tmo := (v_pol->>'timeout_ms')::numeric;
  IF v_kb < 1 OR v_wr < 0 OR v_kmax < v_kb OR v_tmo <= 0 THEN
    RAISE EXCEPTION 'v13: invalid recall_k policy values'
      USING ERRCODE = 'V3005';
  END IF;
  v_cnt := v13_recall_count(v_tinql);
  v_k := least(v_kmax::int, greatest(v_kb::int, ceil(v_cnt * v_wr)::int));
  RETURN jsonb_build_object(
    'k', v_k,
    'matched', v_cnt,
    'candidates', (SELECT coalesce(jsonb_agg(
        jsonb_build_object(
          'content_hash', r.content_hash,
          'bm25', r.bm25,
          'spans', jsonb_build_array(jsonb_build_object(
                     'doc', r.content_hash, 'offsets', r.spans)))
        ORDER BY r.bm25 DESC, r.content_hash ASC), '[]'::jsonb)
      FROM v13_recall(v_tinql, v_k) AS r));
END $$;

CREATE OR REPLACE FUNCTION v13_chunks_generation_bump() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE v13_chunks_meta SET generation = generation + 1 WHERE singleton;
  UPDATE v13_tools_meta
     SET candidate_generation_revision = candidate_generation_revision + 1
   WHERE singleton;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_corpus bigint;
        v_rk_ver int; v_tok jsonb;
BEGIN
  SELECT version INTO v_asm_ver FROM v13_policies
   WHERE name = 'assemble_manifest' AND active;
  IF v_asm_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active assemble_manifest policy (seed lost?)';
  END IF;
  SELECT version INTO v_jdef_ver FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  IF v_jdef_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active judgment_defaults policy (seed lost?)';
  END IF;
  SELECT version INTO v_gen_ver FROM v13_policies
   WHERE name = 'generation' AND active;
  IF v_gen_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active generation policy (seed lost?)';
  END IF;
  SELECT generation INTO v_corpus FROM v13_chunks_meta WHERE singleton;
  IF v_corpus IS NULL THEN
    RAISE EXCEPTION 'v13: chunks meta row lost (seed dropped?)';
  END IF;
  SELECT version INTO v_rk_ver FROM v13_policies
   WHERE name = 'recall_k' AND active;
  IF v_rk_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active recall_k policy (seed lost?)';
  END IF;
  SELECT jsonb_build_object(
    'sem',      coalesce((SELECT max(seq) FROM events
                           WHERE session_id = p_sid
                             AND type IN ('user/message','llm/message',
                                          'tool/result')), -1),
    'dec',      (SELECT count(*) FROM decisions
                  WHERE session_id = p_sid AND answer IS NOT NULL),
    'goal',     v13_goal_hash(p_sid),
    'tools_rev',(SELECT revision FROM v13_tools_meta WHERE singleton),
    'asm_ver',  v_asm_ver,
    'jdef_ver', v_jdef_ver,
    'gen_ver',  v_gen_ver,
    'corpus',   v_corpus,
    'recall_ver', v_rk_ver)
  INTO v_tok;
  RETURN v_tok;
END $$;

CREATE OR REPLACE FUNCTION v13_manifest_validate(p_manifest jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb; j jsonb; c jsonb;
BEGIN
  IF p_manifest IS NULL OR jsonb_typeof(p_manifest) IS DISTINCT FROM 'object'
  THEN
    RAISE EXCEPTION 'v13: manifest must be a jsonb object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest) k)
     IS DISTINCT FROM
     'judgments,manifest_version,policy,prefix_identity,query_side,'
     'replay,required_revision,sections,session_id,turn_no' THEN
    RAISE EXCEPTION 'v13: manifest top-level key set mismatch (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (p_manifest->>'manifest_version')::int IS DISTINCT FROM 1
     OR p_manifest->>'session_id' IS NULL
     OR p_manifest->>'session_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     OR (p_manifest->>'turn_no')::int IS NULL
     OR (p_manifest->>'turn_no')::int < 0
     OR p_manifest->>'prefix_identity' IS NULL
     OR p_manifest->>'prefix_identity' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: manifest anchor/identity shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'policy') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.policy must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest->'policy') k)
     IS DISTINCT FROM
     'assemble_version,budget_tokens,est_bytes_per_token,'
     'judgment_defaults_version'
     OR (p_manifest->'policy'->>'assemble_version')::int IS NULL
     OR (p_manifest->'policy'->>'assemble_version')::int < 1
     OR (p_manifest->'policy'->>'judgment_defaults_version')::int IS NULL
     OR (p_manifest->'policy'->>'judgment_defaults_version')::int < 1
     OR (p_manifest->'policy'->>'budget_tokens')::int IS NULL
     OR (p_manifest->'policy'->>'budget_tokens')::int < 0
     OR (p_manifest->'policy'->>'est_bytes_per_token')::int IS NULL
     OR (p_manifest->'policy'->>'est_bytes_per_token')::int <= 0 THEN
    RAISE EXCEPTION 'v13: manifest.policy shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'required_revision') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.required_revision must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'required_revision') k)
     IS DISTINCT FROM 'asm_ver,corpus,dec,gen_ver,goal,jdef_ver,recall_ver,sem,tools_rev'
     OR (p_manifest->'required_revision'->>'sem')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'sem')::bigint < -1
     OR (p_manifest->'required_revision'->>'dec')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'dec')::bigint < 0
     OR p_manifest->'required_revision'->>'goal' IS NULL
     OR p_manifest->'required_revision'->>'goal' !~ '^[0-9a-f]{64}$'
     OR (p_manifest->'required_revision'->>'tools_rev')::int IS NULL
     OR (p_manifest->'required_revision'->>'tools_rev')::int < 0
     OR (p_manifest->'required_revision'->>'asm_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'asm_ver')::int < 1
     OR (p_manifest->'required_revision'->>'jdef_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'jdef_ver')::int < 1
     OR (p_manifest->'required_revision'->>'gen_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'gen_ver')::int < 1
     OR (p_manifest->'required_revision'->>'corpus')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'corpus')::bigint < 0
     OR (p_manifest->'required_revision'->>'recall_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'recall_ver')::int < 1 THEN
    RAISE EXCEPTION 'v13: manifest.required_revision shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'replay') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.replay must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'replay') k)
     IS DISTINCT FROM 'mode,prior_artifact_id'
     OR (p_manifest->'replay'->>'mode') IN ('fresh','recompute') IS NOT TRUE
  THEN
    RAISE EXCEPTION 'v13: manifest.replay shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'sections') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_manifest->'sections') = 0 THEN
    RAISE EXCEPTION 'v13: manifest.sections must be a non-empty array (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR s IN SELECT jsonb_array_elements(p_manifest->'sections') LOOP
    IF jsonb_typeof(s) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section must be an object (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(s) k)
       IS DISTINCT FROM
       'cache_scope,churn,content_hash,est_tokens,kind,payload_ref,'
       'priority,section_id,transform' THEN
      RAISE EXCEPTION 'v13: section key set mismatch for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (s->>'cache_scope') IN ('Global','Session','None') IS NOT TRUE
       OR (s->>'priority') IN ('Never','First','Normal','LastResort') IS NOT TRUE
       OR s->>'section_id' IS NULL OR length(btrim(s->>'section_id')) = 0
       OR s->>'section_id' IS DISTINCT FROM s->>'kind'
       OR s->>'content_hash' IS NULL
       OR s->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR (s->>'churn')::int IS NULL OR (s->>'churn')::int < 0
       OR (s->>'est_tokens')::int IS NULL OR (s->>'est_tokens')::int < 0 THEN
      RAISE EXCEPTION 'v13: section vocabulary/hash violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF jsonb_typeof(s->'payload_ref') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section payload_ref must be an object for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (s->'payload_ref'->>'kind') IN ('goal','blob') IS NOT TRUE
       OR (CASE WHEN s->'payload_ref'->>'kind' = 'goal'
                THEN (s->'payload_ref'->>'seq')::int IS NULL
                     OR (s->'payload_ref'->>'seq')::int < -1
                ELSE s->'payload_ref'->>'content_hash' IS NULL
                     OR s->'payload_ref'->>'content_hash' !~ '^[0-9a-f]{64}$'
           END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section payload_ref shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF jsonb_typeof(s->'transform') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section transform must be an object for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF jsonb_typeof(s->'transform'->'applied') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: section transform.applied must be boolean for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (CASE WHEN (s->'transform'->>'applied')::boolean
             THEN (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,name'
                  OR (s->'transform'->>'name')
                     IN ('verbatim','catalog_digest') IS NOT TRUE
             ELSE (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,reason'
                  OR (s->'transform'->>'reason')
                     IN ('budget','priority_never','disabled','invalid_override')
                     IS NOT TRUE
        END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section transform shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
  IF jsonb_typeof(p_manifest->'query_side') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.query_side must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'query_side') k)
     IS DISTINCT FROM 'candidates,query_artifact_id'
     OR jsonb_typeof(p_manifest->'query_side'->'candidates')
        IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: query_side field family missing (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR c IN SELECT jsonb_array_elements(
             p_manifest->'query_side'->'candidates') LOOP
    IF jsonb_typeof(c) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: candidate must be an object (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(c) k)
       IS DISTINCT FROM 'bm25,content_hash,decision_id,spans'
       OR c->>'content_hash' IS NULL
       OR c->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(c->'spans') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION 'v13: candidate shape violation (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
  IF jsonb_typeof(p_manifest->'judgments') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: manifest.judgments must be an array (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR j IN SELECT jsonb_array_elements(p_manifest->'judgments') LOOP
    IF jsonb_typeof(j) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: judgment row must be an object (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(j) k)
       IS DISTINCT FROM
       'decision_id,epoch,final_action,raw_verdict,request_hash,'
       'template_name,template_version'
       OR j->>'decision_id' IS NULL
       OR j->>'request_hash' IS NULL
       OR j->>'request_hash' !~ '^[0-9a-f]{64}$'
       OR (j->>'epoch') IN ('pre-bind','pre-finalize','post-execute') IS NOT TRUE
       OR j->>'raw_verdict' IS NULL
       OR (j->>'final_action')
          IN ('recorded','include','exclude','degrade','fail') IS NOT TRUE
       OR NOT (  (  j->>'template_name' IS NULL
                  AND j->>'template_version' IS NULL )
              OR (  j->>'template_name' IS NOT NULL
                  AND (j->>'template_version')::int IS NOT NULL
                  AND (j->>'template_version')::int >= 1 ) ) THEN
      RAISE EXCEPTION 'v13: judgment row shape violation (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION v13_judgment_envelope(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH runtime AS MATERIALIZED (
    SELECT v13_guc_required('typesafe.provider') AS provider,
           v13_guc_required('typesafe.model') AS model),
  ctx AS MATERIALIZED (
    SELECT v13_canonical_state(p_sid) AS c),
  needed AS MATERIALIZED (
    SELECT coalesce(jsonb_agg(
             CASE WHEN n.criteria IS NULL THEN
               jsonb_build_object('signal', n.signal, 'kind', n.kind,
                                  'question', n.question,
                                  'template_name', n.template_name)
             ELSE
               jsonb_build_object('signal', n.signal, 'kind', n.kind,
                                  'question', n.question, 'criteria', n.criteria,
                                  'template_name', n.template_name)
             END ORDER BY n.signal), '[]'::jsonb) AS n
      FROM v13_needed_judgments(p_sid) n),
  tmpl AS MATERIALIZED (
    SELECT coalesce(jsonb_object_agg(t.template_name, jsonb_build_object(
             'version', t.template_version, 'kind', t.kind,
             'projection', t.projection,
             'answer_schema_version', t.answer_schema_version)), '{}'::jsonb) AS t
      FROM v13_template_latest t),
  groups AS MATERIALIZED (
    SELECT coalesce(jsonb_agg(jsonb_build_object('projection_key', s.pkey,
                                                 'state', s.state)
                              ORDER BY s.pkey), '[]'::jsonb) AS g
      FROM (SELECT DISTINCT
              v13_projection_key(
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS pkey,
              v13_project_state(
                (SELECT c FROM ctx),
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS state
              FROM jsonb_array_elements((SELECT n FROM needed)) nr) s),
  wm AS MATERIALIZED (
    SELECT (SELECT next_seq FROM sessions WHERE session_id = p_sid) AS sv,
           coalesce((SELECT max(seq) FROM events
                      WHERE session_id = p_sid), -1) AS mes),
  pol AS MATERIALIZED (
    SELECT route_policy_name AS rpn, route_policy_version AS rpv
      FROM sessions WHERE session_id = p_sid),
  rc AS MATERIALIZED (
    SELECT v13_recall_candidates(p_sid) AS r)
  SELECT jsonb_build_object(
    'sid', p_sid,
    'ctx', (SELECT c FROM ctx),
    'needed', (SELECT n FROM needed),
    'templates', (SELECT t FROM tmpl),
    'groups', (SELECT g FROM groups),
    'timeout_ms', NULLIF(current_setting('typesafe.timeout_ms', true), ''),
    'budget', v13_policy('resolve_fast_path'),
    'candidate_set_hash',
      encode(digest(jsonb_build_object(
        'needed', (SELECT n FROM needed),
        'recall', (SELECT r FROM rc))::text, 'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'provider', (SELECT provider FROM runtime),
    'model',    (SELECT model FROM runtime),
    'route_policy_name',     (SELECT rpn FROM pol),
    'route_policy_version',  (SELECT rpv FROM pol),
    'tools_revision', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'tools_catalog',  v13_tools_catalog_frozen(),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton),
    'session_version', (SELECT sv FROM wm),
    'max_event_seq',   (SELECT mes FROM wm),
    'needed_count', jsonb_array_length((SELECT n FROM needed)),
    'candidates', (SELECT r->'candidates' FROM rc));
$$;

CREATE OR REPLACE FUNCTION v13_assemble_manifest(p_sid uuid,
                                                  p_policy_version int DEFAULT NULL)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
WITH pol AS MATERIALIZED (
  SELECT p.version,
         (p.value->>'budget_tokens')::int        AS budget,
         (p.value->>'est_bytes_per_token')::int  AS divisor,
         p.value->'priority_overrides'           AS prio_ovr,
         p.value->'kinds_disabled'               AS kinds_off,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'judgment_defaults' AND q.active) AS jdef_ver
  FROM v13_policies p
  WHERE p.name = 'assemble_manifest'
    AND p.version = coalesce(p_policy_version,
        (SELECT q.version FROM v13_policies q
          WHERE q.name = 'assemble_manifest' AND q.active))
), tok AS MATERIALIZED (
  SELECT v13_context_required(p_sid) AS t
), ident AS MATERIALIZED (
  SELECT v13_prefix_identity(p_sid) AS pid
), cs AS MATERIALIZED (
  SELECT v13_canonical_state(p_sid) AS c
), pri AS MATERIALIZED (
  SELECT s.context_active_artifact AS aid, a.inline AS m
  FROM sessions s LEFT JOIN artifacts a ON a.artifact_id = s.context_active_artifact
  WHERE s.session_id = p_sid
), pri_sec AS MATERIALIZED (
  SELECT ps->>'section_id' AS section_id, ps->>'content_hash' AS content_hash,
         (ps->>'churn')::int AS churn
  FROM pri, jsonb_array_elements(
         CASE WHEN jsonb_typeof(pri.m->'sections') = 'array'
              THEN pri.m->'sections' ELSE '[]'::jsonb END) ps
), sec_src AS MATERIALIZED (
  SELECT 'goal'::text AS section_id, 'goal'::text AS kind,
         'Session'::text AS cache_scope, 'First'::text AS def_prio,
         v13_goal_hash(p_sid) AS content_hash,
         octet_length(coalesce((SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                        ORDER BY g.seq DESC LIMIT 1), '')) AS bytes,
         coalesce((SELECT max(seq) FROM v13_goals
                    WHERE session_id = p_sid), -1) AS gseq,
         NULL::jsonb AS mat
  UNION ALL
  SELECT 'history','history','Session','Normal',
         encode(digest(coalesce((cs.c -> 'messages')::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce((cs.c -> 'messages')::text, '')),
         NULL::bigint, cs.c -> 'messages'
  FROM cs
  UNION ALL
  SELECT 'tools','tools','Global','First',
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce((cs.c -> 'tools')::text, '')),
         NULL::bigint, cs.c -> 'tools'
  FROM cs
), cls AS MATERIALIZED (
  SELECT r.*,
         CASE WHEN (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS TRUE
              THEN pol.prio_ovr ->> r.kind
              ELSE r.def_prio END AS eff_priority,
         ((r.bytes + pol.divisor - 1) / pol.divisor)::int AS est_tokens,
         CASE coalesce(pol.prio_ovr ->> r.kind, r.def_prio)
           WHEN 'First'      THEN 1
           WHEN 'Normal'     THEN 2
           WHEN 'Never'      THEN 3
           WHEN 'LastResort' THEN 4
         END AS prank,
         CASE WHEN (pol.prio_ovr -> r.kind) IS NOT NULL
               AND (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS NOT TRUE
              THEN 'invalid_override'
              WHEN coalesce(pol.prio_ovr ->> r.kind, r.def_prio) = 'Never'
              THEN 'priority_never'
              WHEN pol.kinds_off @> to_jsonb(r.kind)
              THEN 'disabled'
              ELSE NULL END AS pre_skip,
         CASE WHEN r.section_id = 'goal'
              THEN jsonb_build_object('kind','goal','seq', r.gseq)
              ELSE jsonb_build_object('kind','blob','content_hash',
                encode(digest(coalesce(r.mat::text, ''), 'sha256'), 'hex'))
         END AS payload_ref
  FROM sec_src r, pol
), packed AS MATERIALIZED (
  SELECT c.section_id,
         sum(c.est_tokens) OVER (ORDER BY c.prank, c.section_id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_incl
  FROM cls c
  WHERE c.pre_skip IS NULL
), ordered AS MATERIALIZED (
  SELECT c.*,
         (p.section_id IS NULL) AS prior_missing,
         coalesce(p.content_hash, '') AS prior_hash,
         coalesce(p.churn, 0)          AS prior_churn,
         k.run_incl
  FROM cls c
       LEFT JOIN packed k ON k.section_id = c.section_id
       LEFT JOIN pri_sec p ON p.section_id = c.section_id
), final_sec AS MATERIALIZED (
  SELECT jsonb_build_object(
    'section_id',  o.section_id,
    'kind',        o.kind,
    'cache_scope', o.cache_scope,
    'priority',    o.eff_priority,
    'content_hash',o.content_hash,
    'est_tokens',  o.est_tokens,
    'payload_ref', o.payload_ref,
    'churn',       CASE WHEN o.prior_missing THEN 0
                        WHEN o.content_hash IS DISTINCT FROM o.prior_hash
                        THEN o.prior_churn + 1 ELSE 0 END,
    'transform',   CASE
                     WHEN o.pre_skip IS NOT NULL THEN
                       jsonb_build_object('applied', false,
                                          'reason', o.pre_skip)
                     WHEN o.run_incl > pol.budget THEN
                       jsonb_build_object('applied', false,
                                          'reason', 'budget')
                     ELSE
                       jsonb_build_object('applied', true, 'name',
                         CASE o.section_id WHEN 'goal'   THEN 'verbatim'
                                           WHEN 'history' THEN 'verbatim'
                                           ELSE 'catalog_digest' END)
                   END
  ) AS section, o.prank, o.section_id
  FROM ordered o, pol
), goal_addr AS MATERIALIZED (
  SELECT coalesce((SELECT jsonb_build_object('kind','goal','seq',g.seq,
                              'content_hash',g.content_hash)
                     FROM v13_goals g WHERE g.session_id = p_sid
                 ORDER BY g.seq DESC LIMIT 1),
                  'null'::jsonb) AS a
), qside AS MATERIALIZED (
  SELECT jsonb_build_object(
    'query_artifact_id', (SELECT a FROM goal_addr),
    'candidates', (SELECT coalesce(jsonb_agg(
                     c || jsonb_build_object('decision_id', NULL)
                       ORDER BY (c->>'bm25')::numeric DESC,
                                c->>'content_hash' ASC), '[]'::jsonb)
                     FROM jsonb_array_elements(
                            v13_recall_candidates(p_sid) -> 'candidates') c)
  ) AS q
), jud AS MATERIALIZED (
  SELECT coalesce(jsonb_agg(jsonb_build_object(
    'decision_id',    d.decision_id,
    'epoch',          d.epoch,
    'request_hash',   d.request_hash,
    'template_name',  d.template_name,
    'template_version', d.template_version,
    'raw_verdict',    d.answer,
    'final_action',   'recorded'
  ) ORDER BY d.decision_id), '[]'::jsonb) AS j
  FROM decisions d
  WHERE d.answer IS NOT NULL
    AND d.status IN ('answered','cached')
    AND d.decision_id::text IN (
    SELECT cand->>'decision_id'
    FROM qside, jsonb_array_elements(qside.q->'candidates') cand
    WHERE cand->>'decision_id' IS NOT NULL)
), mode AS MATERIALIZED (
  SELECT CASE
           WHEN pri.m IS NULL THEN 'fresh'
           WHEN (pri.m->>'prefix_identity')
                IS DISTINCT FROM (SELECT pid FROM ident) THEN 'fresh'
           ELSE 'recompute'
         END AS m
  FROM pri
)
SELECT jsonb_build_object(
  'manifest_version', 1,
  'session_id', p_sid,
  'turn_no',   (SELECT turn_no FROM sessions WHERE session_id = p_sid),
  'prefix_identity', (SELECT pid FROM ident),
  'policy',    jsonb_build_object(
                 'assemble_version',   (SELECT version FROM pol),
                 'budget_tokens',      (SELECT budget FROM pol),
                 'est_bytes_per_token',(SELECT divisor FROM pol),
                 'judgment_defaults_version', (SELECT jdef_ver FROM pol)),
  'required_revision', (SELECT t FROM tok),
  'sections',  (SELECT coalesce(jsonb_agg(section ORDER BY prank, section_id),
                             '[]'::jsonb)
                  FROM final_sec),
  'query_side',(SELECT q FROM qside),
  'judgments', (SELECT j FROM jud),
  'replay',    jsonb_build_object('mode', (SELECT m FROM mode),
                                  'prior_artifact_id', (SELECT aid FROM pri))
);
$$;

INSERT INTO v13_policies (name, version, value, active) VALUES
('recall_k',      1, $j${"k_base":8,"widen_ratio":0.05,"k_max":64,"timeout_ms":800}$j$::jsonb, true),
('recall_boosts', 1, $j${"boosts":[]}$j$::jsonb, true);

REVOKE EXECUTE ON FUNCTION
  v13_query_segments(text), v13_build_tinql(text), v13_tinql_terms(text),
  v13_recall(text,int), v13_recall_count(text), v13_recall_candidates(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_query_segments(text), v13_build_tinql(text), v13_tinql_terms(text),
  v13_recall(text,int), v13_recall_count(text), v13_recall_candidates(uuid)
TO v13_recall, v13_resolve, v13_route;
GRANT SELECT ON chunks, v13_sources, v13_chunks_meta TO v13_resolve, v13_route;

COMMIT;
