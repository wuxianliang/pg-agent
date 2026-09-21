BEGIN;

-- =========================================================================
-- DP4 chunks (v13_chunks.sql): chunks projection & span assembly.
-- Design: docs/designs/v13-context-on-pg.md §4.2/§4.7/§7/§8/§9/§10 G-ctx2.
-- Review: stepfun F3 (chunk_offset + retention + replay gate) — legislated
-- here, design doc unchanged (plan 附 A).
-- DP contracts: DP1 §1.3 (row DP4/DP5, #59), DP3 §1.4 (row DP4:
-- v13_context_required key set + spans shape + hash-only identity).
-- File order = load order. Owner-plane writers; zero DEFINER (OQ5).
-- =========================================================================

CREATE FUNCTION v13_body_hash(p_body text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest(to_jsonb(p_body)::text, 'sha256'), 'hex')
$$;

CREATE FUNCTION v13_tsv_en(p_body text) RETURNS tsvector
LANGUAGE sql IMMUTABLE AS $$
  SELECT to_tsvector('english'::regconfig, p_body)
$$;

CREATE FUNCTION v13_chunk_referenced(p_hash text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM artifacts a
                  WHERE a.kind = 'context'
                    AND a.inline->'query_side'->'candidates'
                        @> jsonb_build_array(
                             jsonb_build_object('content_hash', p_hash)))
      OR EXISTS (SELECT 1 FROM decisions d
                  WHERE d.context->'chunk'->>'content_hash' = p_hash)
$$;

CREATE INDEX ix_artifacts_candidates ON artifacts
  USING gin (((inline->'query_side'->'candidates')) jsonb_path_ops)
  WHERE kind = 'context';

CREATE FUNCTION v13_adv_xact_locks(p_keys jsonb, p_ns bigint)
RETURNS void LANGUAGE plpgsql VOLATILE AS $$
DECLARE k text;
BEGIN
  IF jsonb_typeof(p_keys) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: lock keys must be a jsonb text array'
      USING ERRCODE = 'V3004';
  END IF;
  FOR k IN SELECT DISTINCT x FROM jsonb_array_elements_text(p_keys) AS x
            ORDER BY 1 LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended(k, p_ns));
  END LOOP;
END $$;

CREATE FUNCTION v13_artifacts_ref_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE h text;
BEGIN
  FOR h IN SELECT DISTINCT cand->>'content_hash'
             FROM jsonb_array_elements(
                  coalesce(NEW.inline->'query_side'->'candidates',
                           '[]'::jsonb)) cand
            ORDER BY 1 LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended(h, 20260920));
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_artifacts_chunk_ref_lock
  BEFORE INSERT ON artifacts FOR EACH ROW
  WHEN (NEW.kind = 'context')
  EXECUTE FUNCTION v13_artifacts_ref_lock();

CREATE FUNCTION v13_decisions_ref_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE h text;
BEGIN
  h := NEW.context->'chunk'->>'content_hash';
  IF h IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended(h, 20260920));
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decisions_chunk_ref_lock
  BEFORE INSERT OR UPDATE ON decisions FOR EACH ROW
  WHEN (NEW.context->'chunk' IS NOT NULL)
  EXECUTE FUNCTION v13_decisions_ref_lock();

CREATE TABLE v13_sources (
  source_hash   text PRIMARY KEY,
  corpus        text NOT NULL,
  artifact_id   uuid NOT NULL REFERENCES artifacts (artifact_id),
  ingested_at   timestamptz NOT NULL DEFAULT now(),
  superseded_by text DEFAULT NULL
);

CREATE FUNCTION v13_sources_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: v13_sources is append-only (DELETE on %)',
      TG_TABLE_NAME USING ERRCODE = 'V3004';
  END IF;
  IF NEW.superseded_by IS NULL
     OR OLD.superseded_by IS NOT NULL
     OR NEW.source_hash IS DISTINCT FROM OLD.source_hash
     OR NEW.corpus      IS DISTINCT FROM OLD.corpus
     OR NEW.artifact_id IS DISTINCT FROM OLD.artifact_id
     OR NEW.ingested_at IS DISTINCT FROM OLD.ingested_at THEN
    RAISE EXCEPTION
      'v13: v13_sources is append-only (only superseded_by NULL->value)'
      USING ERRCODE = 'V3004';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_sources_append_only
  BEFORE UPDATE OR DELETE ON v13_sources
  FOR EACH ROW EXECUTE FUNCTION v13_sources_append_only();

CREATE TABLE v13_chunks_meta (
  singleton   boolean PRIMARY KEY CHECK (singleton),
  generation  bigint NOT NULL DEFAULT 0 CHECK (generation >= 0)
);
INSERT INTO v13_chunks_meta (singleton, generation) VALUES (true, 0);

CREATE FUNCTION v13_chunks_meta_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: v13_chunks_meta row cannot be deleted'
      USING ERRCODE = 'V3004';
  END IF;
  IF NEW.singleton IS DISTINCT FROM true
     OR NEW.generation IS NULL
     OR NEW.generation < OLD.generation THEN
    RAISE EXCEPTION 'v13: chunks generation is monotonic (no reset/lowering)'
      USING ERRCODE = 'V3004';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_chunks_meta_guard
  BEFORE UPDATE OR DELETE ON v13_chunks_meta
  FOR EACH ROW EXECUTE FUNCTION v13_chunks_meta_guard();

CREATE TABLE chunks (
  source_hash      text NOT NULL,
  chunk_no         int  NOT NULL CHECK (chunk_no >= 0),
  body             text NOT NULL,
  content_hash     text NOT NULL,
  chunk_offset     bigint NOT NULL DEFAULT 0
                   CHECK (chunk_offset >= 0),
  corpus           text NOT NULL,
  chunker_version  text NOT NULL,
  analyzer_version text NOT NULL,
  body_tsv tsvector GENERATED ALWAYS AS (v13_tsv_en(body)) STORED,
  PRIMARY KEY (source_hash, chunk_no),
  FOREIGN KEY (source_hash) REFERENCES v13_sources (source_hash),
  CONSTRAINT v13_chunks_hash_selfcheck
    CHECK (content_hash = v13_body_hash(body))
);
CREATE INDEX ix_chunks_corpus ON chunks (corpus);
CREATE INDEX ix_chunks_tsv ON chunks USING gin (body_tsv);

CREATE FUNCTION v13_chunks_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: chunks rows are immutable (% on % %/%)',
    TG_OP, TG_TABLE_NAME, OLD.source_hash, OLD.chunk_no
    USING ERRCODE = 'V3004';
END $$;
CREATE TRIGGER trg_chunks_immutable
  BEFORE UPDATE ON chunks FOR EACH ROW
  EXECUTE FUNCTION v13_chunks_immutable();

CREATE FUNCTION v13_chunks_artifact_exists() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM artifacts a
                  WHERE a.content_hash = NEW.content_hash
                    AND a.kind = 'chunk') THEN
    RAISE EXCEPTION
      'v13: chunk %/% has no kind=''chunk'' artifact for %',
      NEW.source_hash, NEW.chunk_no, NEW.content_hash
      USING ERRCODE = 'V3004';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_chunks_artifact_exists
  BEFORE INSERT ON chunks FOR EACH ROW
  EXECUTE FUNCTION v13_chunks_artifact_exists();

CREATE FUNCTION v13_chunks_retention() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF v13_chunk_referenced(OLD.content_hash) THEN
    RAISE EXCEPTION
      'v13: chunk %/% is referenced (manifest/decision) and retained (F3)',
      OLD.source_hash, OLD.chunk_no
      USING ERRCODE = 'V3004';
  END IF;
  RETURN OLD;
END $$;
CREATE TRIGGER trg_chunks_retention
  BEFORE DELETE ON chunks FOR EACH ROW
  EXECUTE FUNCTION v13_chunks_retention();

CREATE FUNCTION v13_chunks_generation_bump() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE v13_chunks_meta SET generation = generation + 1 WHERE singleton;
  RETURN NULL;
END $$;
CREATE TRIGGER trg_chunks_generation_bump
  AFTER INSERT OR DELETE ON chunks FOR EACH STATEMENT
  EXECUTE FUNCTION v13_chunks_generation_bump();

CREATE FUNCTION v13_chunks_no_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: TRUNCATE chunks is forbidden; use v13_rebuild_chunks()'
    USING ERRCODE = 'V3004';
END $$;
CREATE TRIGGER trg_chunks_no_truncate
  BEFORE TRUNCATE ON chunks FOR EACH STATEMENT
  EXECUTE FUNCTION v13_chunks_no_truncate();

INSERT INTO v13_policies (name, version, value, active) VALUES
('chunks_ingest', 1, $j${"chunker_version":"para_v1","analyzer_version":"tsv_english_1","mode":"para","target_bytes":3072,"max_chunk_bytes":1048576,"max_doc_bytes":1048576}$j$::jsonb, true),
('span_assembly', 1, $j${"mode":"span","context_bytes":256,"merge_gap_bytes":64,"boundary":"sentence","fence_aware":true,"table_aware":true}$j$::jsonb, true),
('chunk_gc',      1, $j${"mode":"dry-run-only"}$j$::jsonb, true);

CREATE FUNCTION v13_chunker_slice(p_body text, p_policy jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_mode  text   := p_policy->>'mode';
  v_tgt   bigint;
  v_max   bigint;
  v_paras text[];
  v_out   jsonb := '[]'::jsonb;
  v_cur   text := '';
  v_start bigint := 0;
  v_abs   bigint := 0;
  v_no    int := 0;
  v_fence boolean := false;
  v_p text; v_fences int; v_len bigint;
BEGIN
  IF (v_mode IN ('whole','para')) IS NOT TRUE
     OR jsonb_typeof(p_policy->'target_bytes') IS DISTINCT FROM 'number'
     OR jsonb_typeof(p_policy->'max_chunk_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy shape'
      USING ERRCODE = 'V3004';
  END IF;
  v_tgt := (p_policy->>'target_bytes')::bigint;
  v_max := (p_policy->>'max_chunk_bytes')::bigint;
  IF v_tgt <= 0 OR v_max <= 0 OR v_tgt > v_max THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy shape'
      USING ERRCODE = 'V3004';
  END IF;
  IF v_mode = 'whole' THEN
    IF octet_length(p_body) > v_max THEN
      RAISE EXCEPTION 'v13: doc exceeds max_chunk_bytes (%)',
        octet_length(p_body) USING ERRCODE = 'V3004';
    END IF;
    RETURN jsonb_build_array(jsonb_build_object(
      'chunk_no', 0, 'body', p_body, 'chunk_offset', 0));
  END IF;
  IF p_body = '' THEN
    RAISE EXCEPTION 'v13: empty document rejected (para mode)'
      USING ERRCODE = 'V3004';
  END IF;
  v_paras := string_to_array(p_body, E'\n\n');
  IF coalesce(array_length(v_paras, 1), 0) > 4096 THEN
    RAISE EXCEPTION 'v13: doc exceeds paragraph cap (4096)'
      USING ERRCODE = 'V3004';
  END IF;
  FOR v_p IN SELECT unnest(v_paras) LOOP
    v_len := octet_length(v_p);
    v_fences := (length(v_p) - length(replace(v_p, '```', ''))) / 3;
    IF v_cur = '' THEN
      v_start := v_abs; v_cur := v_p;
    ELSIF NOT v_fence
          AND octet_length(v_cur) + 2 + v_len > v_tgt THEN
      IF v_len > v_max THEN
        RAISE EXCEPTION
          'v13: paragraph exceeds max_chunk_bytes — hard split is YAGNI'
          USING ERRCODE = 'V3004';
      END IF;
      IF octet_length(v_cur) > v_max THEN
        RAISE EXCEPTION
          'v13: paragraph exceeds max_chunk_bytes — hard split is YAGNI'
          USING ERRCODE = 'V3004';
      END IF;
      v_out := v_out || jsonb_build_array(jsonb_build_object(
                 'chunk_no', v_no, 'body', v_cur, 'chunk_offset', v_start));
      v_no := v_no + 1;
      v_start := v_abs; v_cur := v_p;
    ELSE
      IF octet_length(v_cur) + 2 + v_len > v_max THEN
        RAISE EXCEPTION
          'v13: paragraph cluster (fenced) exceeds max_chunk_bytes — hard split is YAGNI'
          USING ERRCODE = 'V3004';
      END IF;
      v_cur := v_cur || E'\n\n' || v_p;
    END IF;
    v_abs := v_abs + v_len + 2;
    v_fence := v_fence <> (v_fences % 2 = 1);
  END LOOP;
  IF v_cur <> '' THEN
    IF octet_length(v_cur) > v_max THEN
      RAISE EXCEPTION
        'v13: paragraph exceeds max_chunk_bytes — hard split is YAGNI'
        USING ERRCODE = 'V3004';
    END IF;
    v_out := v_out || jsonb_build_array(jsonb_build_object(
               'chunk_no', v_no, 'body', v_cur, 'chunk_offset', v_start));
  END IF;
  RETURN v_out;
END $$;

CREATE FUNCTION v13_project_source(
  p_source_hash text, p_corpus text, p_body text,
  p_produced_by uuid, p_policy jsonb)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE
  v_slices jsonb; s jsonb; v_hash text; v_n int := 0;
  v_ck text := p_policy->>'chunker_version';
  v_ak text := p_policy->>'analyzer_version';
BEGIN
  v_slices := v13_chunker_slice(p_body, p_policy);
  FOR s IN SELECT * FROM jsonb_array_elements(v_slices) LOOP
    v_hash := v13_body_hash(s->>'body');
    IF NOT EXISTS (SELECT 1 FROM artifacts
                    WHERE content_hash = v_hash AND kind = 'chunk') THEN
      INSERT INTO artifacts (content_hash, kind, inline, size, produced_by)
      VALUES (v_hash, 'chunk', to_jsonb(s->>'body'),
              octet_length(to_jsonb(s->>'body')::text), p_produced_by);
    END IF;
    INSERT INTO chunks (source_hash, chunk_no, body, content_hash,
                        chunk_offset, corpus, chunker_version, analyzer_version)
    VALUES (p_source_hash, (s->>'chunk_no')::int, s->>'body', v_hash,
            (s->>'chunk_offset')::bigint, p_corpus, v_ck, v_ak);
    v_n := v_n + 1;
  END LOOP;
  RETURN v_n;
END $$;

CREATE FUNCTION v13_ingest_document(
  p_produced_by uuid,
  p_corpus      text,
  p_body        text,
  p_supersedes  text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_policy jsonb := v13_policy('chunks_ingest');
  v_src text; v_doc jsonb; v_sz bigint; v_aid uuid;
  v_kind text; v_status text;
  v_locked boolean; v_exist jsonb; v_new jsonb := '[]'::jsonb; s jsonb;
  v_gen bigint; v_count int;
BEGIN
  IF v_policy IS NULL OR p_corpus IS NULL OR p_corpus = '' OR p_body IS NULL
     OR octet_length(p_body) = 0
     OR jsonb_typeof(v_policy->'mode') IS DISTINCT FROM 'string'
     OR (v_policy->>'mode' IN ('whole','para')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'chunker_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'chunker_version' IN ('para_v1','whole_v1')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'analyzer_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'analyzer_version' IN ('tsv_english_1')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'max_doc_bytes') IS DISTINCT FROM 'number'
     OR left(v_policy->>'chunker_version',
             length(v_policy->>'mode')) IS DISTINCT FROM v_policy->>'mode' THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy, corpus, or empty body'
      USING ERRCODE = 'V3004';
  END IF;
  SELECT kind, status INTO v_kind, v_status
    FROM effects WHERE effect_id = p_produced_by;
  IF v_kind IS DISTINCT FROM 'tool' OR v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: ingest requires a succeeded tool effect (%)',
      p_produced_by USING ERRCODE = 'V3004';
  END IF;
  v_doc := to_jsonb(p_body); v_sz := octet_length(v_doc::text);
  IF v_sz > (v_policy->>'max_doc_bytes')::bigint THEN
    RAISE EXCEPTION 'v13: doc exceeds max_doc_bytes (%)', v_sz
      USING ERRCODE = 'V3004';
  END IF;
  v_src := v13_body_hash(p_body);
  SELECT artifact_id INTO v_aid FROM artifacts
   WHERE content_hash = v_src AND kind = 'chunk' LIMIT 1;
  IF v_aid IS NULL THEN
    INSERT INTO artifacts (content_hash, kind, inline, size, produced_by)
    VALUES (v_src, 'chunk', v_doc, v_sz, p_produced_by)
    RETURNING artifact_id INTO v_aid;
  END IF;
  INSERT INTO v13_sources (source_hash, corpus, artifact_id)
  VALUES (v_src, p_corpus, v_aid)
  ON CONFLICT (source_hash) DO NOTHING;
  IF EXISTS (SELECT 1 FROM v13_sources
              WHERE source_hash = v_src AND corpus IS DISTINCT FROM p_corpus) THEN
    RAISE EXCEPTION 'v13: source % already bound to another corpus', v_src
      USING ERRCODE = 'V3004';
  END IF;
  PERFORM v13_adv_xact_locks(
    (SELECT coalesce(jsonb_agg(DISTINCT lk ORDER BY lk), '[]'::jsonb)
       FROM unnest(ARRAY[v_src, coalesce(p_supersedes, v_src)]) AS lk), 20260921);
  PERFORM v13_adv_xact_locks(
    (SELECT coalesce(jsonb_agg(DISTINCT content_hash ORDER BY content_hash),
                     '[]'::jsonb)
       FROM chunks WHERE source_hash IN (v_src, p_supersedes)), 20260920);
  v_locked := EXISTS (SELECT 1 FROM chunks
                       WHERE source_hash = v_src
                         AND v13_chunk_referenced(content_hash));
  IF v_locked THEN
    SELECT coalesce(jsonb_agg(jsonb_build_object('chunk_no', chunk_no,
                            'content_hash', content_hash)
                              ORDER BY chunk_no), '[]'::jsonb)
      INTO v_exist FROM chunks WHERE source_hash = v_src;
    FOR s IN SELECT * FROM jsonb_array_elements(v13_chunker_slice(p_body, v_policy)) LOOP
      v_new := v_new || jsonb_build_object('chunk_no', (s->>'chunk_no')::int,
                   'content_hash', v13_body_hash(s->>'body'));
    END LOOP;
    IF v_exist IS DISTINCT FROM v_new THEN
      RAISE EXCEPTION
        'v13: source % is retention-locked (F3) and new slicing differs',
        v_src USING ERRCODE = 'V3004';
    END IF;
    SELECT generation INTO v_gen FROM v13_chunks_meta WHERE singleton;
    RETURN jsonb_build_object('source_hash', v_src, 'artifact_id', v_aid,
      'chunk_count', jsonb_array_length(v_new), 'locked', true,
      'unchanged', true, 'generation', v_gen);
  END IF;
  DELETE FROM chunks WHERE source_hash = v_src;
  IF p_supersedes IS NOT NULL AND p_supersedes <> v_src THEN
    DELETE FROM chunks WHERE source_hash = p_supersedes
      AND NOT v13_chunk_referenced(content_hash);
    UPDATE v13_sources SET superseded_by = v_src
     WHERE source_hash = p_supersedes
       AND superseded_by IS NULL;
  END IF;
  v_count := v13_project_source(v_src, p_corpus, p_body, p_produced_by, v_policy);
  SELECT generation INTO v_gen FROM v13_chunks_meta WHERE singleton;
  RETURN jsonb_build_object('source_hash', v_src, 'artifact_id', v_aid,
    'chunk_count', v_count, 'locked', false, 'unchanged', false,
    'generation', v_gen);
END $$;

CREATE FUNCTION v13_rebuild_chunks(p_corpus text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_policy jsonb := v13_policy('chunks_ingest');
  r record;
  v_locked boolean;
  v_total int := 0; v_reprojected int := 0; v_locked_n int := 0;
  v_rows int := 0; v_n int;
BEGIN
  IF v_policy IS NULL
     OR jsonb_typeof(v_policy->'mode') IS DISTINCT FROM 'string'
     OR (v_policy->>'mode' IN ('whole','para')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'chunker_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'chunker_version' IN ('para_v1','whole_v1')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'analyzer_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'analyzer_version' IN ('tsv_english_1')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy shape'
      USING ERRCODE = 'V3004';
  END IF;
  FOR r IN SELECT src.source_hash, src.corpus, (a.inline #>> '{}') AS body,
                  a.produced_by
             FROM v13_sources src
             JOIN artifacts a ON a.artifact_id = src.artifact_id
            WHERE src.superseded_by IS NULL
              AND (p_corpus IS NULL OR src.corpus = p_corpus)
            ORDER BY src.source_hash
  LOOP
    v_total := v_total + 1;
    PERFORM v13_adv_xact_locks(jsonb_build_array(r.source_hash), 20260921);
    PERFORM v13_adv_xact_locks(
      (SELECT coalesce(jsonb_agg(DISTINCT content_hash ORDER BY content_hash),
                       '[]'::jsonb)
         FROM chunks WHERE source_hash = r.source_hash), 20260920);
    v_locked := EXISTS (SELECT 1 FROM chunks
                         WHERE source_hash = r.source_hash
                           AND v13_chunk_referenced(content_hash));
    IF v_locked THEN
      v_locked_n := v_locked_n + 1; CONTINUE;
    END IF;
    DELETE FROM chunks WHERE source_hash = r.source_hash;
    v_n := v13_project_source(r.source_hash, r.corpus, r.body,
                              r.produced_by, v_policy);
    v_reprojected := v_reprojected + 1; v_rows := v_rows + v_n;
  END LOOP;
  RETURN jsonb_build_object('sources', v_total, 'reprojected', v_reprojected,
    'locked', v_locked_n, 'rows_inserted', v_rows,
    'chunker_version', v_policy->>'chunker_version');
END $$;

CREATE FUNCTION v13_chunk_gc(p_dry_run boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_mode text := v13_policy('chunk_gc')->>'mode'; v_n bigint; r2 record;
        v_rc bigint;
BEGIN
  IF jsonb_typeof(v13_policy('chunk_gc')->'mode') IS DISTINCT FROM 'string'
     OR (v_mode IN ('dry-run-only','delete-unreferenced')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid chunk_gc policy mode' USING ERRCODE = 'V3004';
  END IF;
  IF p_dry_run OR v_mode = 'dry-run-only' THEN
    RETURN jsonb_build_object('mode', 'dry-run', 'deletable_by_corpus',
      (SELECT coalesce(jsonb_object_agg(corpus, n), '{}'::jsonb)
         FROM (SELECT corpus, count(*) n FROM chunks c
                WHERE NOT v13_chunk_referenced(c.content_hash)
                GROUP BY corpus) x));
  END IF;
  v_n := 0;
  FOR r2 IN SELECT DISTINCT c.source_hash FROM chunks c
             JOIN v13_sources s ON s.source_hash = c.source_hash
            WHERE s.superseded_by IS NULL
            ORDER BY c.source_hash LOOP
    PERFORM v13_adv_xact_locks(jsonb_build_array(r2.source_hash), 20260921);
    PERFORM v13_adv_xact_locks(
      (SELECT coalesce(jsonb_agg(DISTINCT content_hash ORDER BY content_hash),
                       '[]'::jsonb)
         FROM chunks WHERE source_hash = r2.source_hash), 20260920);
    DELETE FROM chunks c WHERE c.source_hash = r2.source_hash
      AND NOT v13_chunk_referenced(c.content_hash);
    GET DIAGNOSTICS v_rc = ROW_COUNT;
    v_n := v_n + v_rc;
  END LOOP;
  RETURN jsonb_build_object('mode', 'deleted', 'deleted_rows', v_n);
END $$;

CREATE FUNCTION v13_verify_chunks(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_bad_selfcert bigint; v_bad_orphan bigint; v_bad_source bigint;
  v_bad_ref bigint; v_plan text := ''; v_pending int; v_meta boolean;
  v_bad_backref bigint; v_orphan bigint; v_guc text;
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
                                   'orphan_artifacts_report', v_orphan)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_chunks failed: %', v_checks
      USING ERRCODE = 'V3004';
  END IF;
  RETURN jsonb_build_object('version', 1, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;

CREATE FUNCTION v13_extract_spans(p_body text, p_terms jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  t text; v_fold text; v_terms text[];
  v_char int; v_bstart int; v_bend int; v_hits jsonb := '[]'::jsonb;
  v_occ int; v_from int; v_total int := 0;
BEGIN
  IF p_body IS NULL THEN RETURN '[]'::jsonb; END IF;
  IF p_terms IS NULL OR jsonb_typeof(p_terms) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_terms) > 64 THEN
    RAISE EXCEPTION 'v13: span terms must be an array of <=64 items'
      USING ERRCODE = 'V3004';
  END IF;
  SELECT coalesce(array_agg(x), '{}') INTO v_terms
    FROM jsonb_array_elements_text(p_terms) AS x;
  v_fold := translate(p_body, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                           'abcdefghijklmnopqrstuvwxyz');
  FOREACH t IN ARRAY v_terms LOOP
    t := translate(t, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                      'abcdefghijklmnopqrstuvwxyz');
    IF length(t) = 0 OR length(t) > 256 THEN
      RAISE EXCEPTION 'v13: span term out of bounds' USING ERRCODE = 'V3004';
    END IF;
    v_occ := 0; v_from := 1;
    LOOP
      EXIT WHEN v_occ >= 32 OR v_total >= 256;
      v_char := position(t in substring(v_fold from v_from));
      EXIT WHEN v_char = 0;
      v_char := v_char + v_from - 1;
      v_bstart := octet_length(left(p_body, v_char - 1)) + 1;
      v_bend := v_bstart + octet_length(t) - 1;
      v_hits := v_hits || jsonb_build_array(jsonb_build_array(v_bstart, v_bend));
      v_total := v_total + 1; v_occ := v_occ + 1;
      v_from := v_char + length(t);
    END LOOP;
  END LOOP;
  RETURN (SELECT coalesce(jsonb_agg(span ORDER BY (span->>0)::int), '[]'::jsonb)
            FROM (SELECT DISTINCT span
                    FROM jsonb_array_elements(v_hits) AS span) d);
END $$;

CREATE FUNCTION v13_span_unit(p_hash text, p_body text,
                              p_s bigint, p_e bigint, p_opts jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_blen  bigint := octet_length(p_body);
  v_s bigint := p_s; v_e bigint := p_e;
  v_ctx bigint; v_boundary text; v_fence boolean; v_table boolean;
  v_lines text[]; v_n int; v_i int; v_off bigint := 0; v_le bigint;
  v_fopen boolean := false; v_fs bigint := 0;
  v_topen boolean := false; v_ts bigint := 0;
  v_blocks jsonb := '[]'::jsonb;
  v_b jsonb; v_bs bigint; v_be bigint;
  v_in_block boolean := false;
  v_chars text[]; v_cn int; v_ci int; v_cb bigint; v_ch text; v_nxt text;
  v_cend bigint; v_start bigint := 1;
  v_s_done boolean := false;
  v_e_done boolean := false;
  v_bytes bytea;
BEGIN
  IF p_s < 1 OR p_e < p_s OR p_e > v_blen THEN
    RAISE EXCEPTION 'v13: span out of bounds' USING ERRCODE = 'V3004';
  END IF;
  IF p_opts ? 'context_bytes'
     AND jsonb_typeof(p_opts->'context_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid span opts (context_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  v_ctx := coalesce((p_opts->>'context_bytes')::bigint, 0);
  IF v_ctx < 0 THEN
    RAISE EXCEPTION 'v13: invalid span opts (context_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  IF p_opts ? 'boundary'
     AND jsonb_typeof(p_opts->'boundary') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: invalid span opts (boundary)'
      USING ERRCODE = 'V3004';
  END IF;
  v_boundary := coalesce(p_opts->>'boundary', 'none');
  IF (v_boundary IN ('none','line','sentence')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid span opts (boundary)'
      USING ERRCODE = 'V3004';
  END IF;
  IF (p_opts ? 'fence_aware'
      AND jsonb_typeof(p_opts->'fence_aware') IS DISTINCT FROM 'boolean')
  OR (p_opts ? 'table_aware'
      AND jsonb_typeof(p_opts->'table_aware') IS DISTINCT FROM 'boolean') THEN
    RAISE EXCEPTION 'v13: invalid span opts (aware flags)'
      USING ERRCODE = 'V3004';
  END IF;
  v_fence := coalesce((p_opts->>'fence_aware')::boolean, false);
  v_table := coalesce((p_opts->>'table_aware')::boolean, false);

  v_lines := string_to_array(p_body, E'\n');
  v_n := coalesce(array_length(v_lines, 1), 0);
  FOR v_i IN 1 .. v_n LOOP
    v_le := least(v_off + octet_length(v_lines[v_i]) + 1, v_blen);
    IF v_fence AND (length(v_lines[v_i])
                    - length(replace(v_lines[v_i], '```', ''))) / 3 % 2 = 1 THEN
      IF NOT v_fopen THEN
        v_fopen := true; v_fs := v_off + 1;
      ELSE
        v_fopen := false;
        v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
          's', v_fs, 'e', v_le, 'kind', 'fence'));
      END IF;
    END IF;
    IF v_table AND substring(v_lines[v_i] from 1 for 1) = '|' THEN
      IF NOT v_topen THEN v_topen := true; v_ts := v_off + 1; END IF;
    ELSIF v_topen THEN
      v_topen := false;
      v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
        's', v_ts, 'e', v_off, 'kind', 'table'));
    END IF;
    v_off := v_le;
  END LOOP;
  IF v_fopen THEN
    v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
      's', v_fs, 'e', v_blen, 'kind', 'fence'));
  END IF;
  IF v_topen THEN
    v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
      's', v_ts, 'e', v_blen, 'kind', 'table'));
  END IF;

  FOR v_b IN SELECT * FROM jsonb_array_elements(v_blocks) b LOOP
    v_bs := (v_b->>'s')::bigint; v_be := (v_b->>'e')::bigint;
    IF v_b->>'kind' = 'fence' AND v_bs <= p_e AND p_s <= v_be THEN
      v_s := v_bs; v_e := v_be; v_in_block := true; EXIT;
    END IF;
  END LOOP;
  IF NOT v_in_block THEN
    FOR v_b IN SELECT * FROM jsonb_array_elements(v_blocks) b LOOP
      v_bs := (v_b->>'s')::bigint; v_be := (v_b->>'e')::bigint;
      IF v_b->>'kind' = 'table' AND v_bs <= p_e AND p_s <= v_be THEN
        v_s := v_bs; v_e := v_be; v_in_block := true; EXIT;
      END IF;
    END LOOP;
  END IF;

  IF NOT v_in_block THEN
    IF v_boundary = 'sentence' THEN
      v_chars := regexp_split_to_array(p_body, '');
      v_cn := coalesce(array_length(v_chars, 1), 0);
      v_cb := 0;
      FOR v_ci IN 1 .. v_cn LOOP
        v_ch := v_chars[v_ci];
        v_cend := v_cb + octet_length(v_ch);
        v_nxt := CASE WHEN v_ci < v_cn THEN v_chars[v_ci + 1] ELSE '' END;
        IF NOT v_s_done AND v_cend >= v_s THEN
          v_s := v_start; v_s_done := true;
        END IF;
        IF v_ch = E'\n'
           OR (v_ch IN ('.', '!', '?', '。', '！', '？')
               AND (v_nxt = '' OR v_nxt = ' '
                    OR v_nxt = E'\n' OR v_nxt = E'\t')) THEN
          IF v_cend >= v_e THEN
            v_e := v_cend; v_e_done := true; EXIT;
          END IF;
          v_start := v_cend + 1;
        END IF;
        v_cb := v_cend;
      END LOOP;
      IF NOT v_s_done THEN v_s := v_start; END IF;
      IF NOT v_e_done THEN v_e := v_blen; END IF;
    ELSIF v_boundary = 'line' THEN
      v_off := 0;
      FOR v_i IN 1 .. v_n LOOP
        v_le := least(v_off + octet_length(v_lines[v_i]) + 1, v_blen);
        IF v_off + 1 <= v_s AND v_s <= v_le THEN v_s := v_off + 1; END IF;
        IF v_off + 1 <= v_e AND v_e <= v_le THEN v_e := v_le; EXIT; END IF;
        v_off := v_le;
      END LOOP;
    END IF;
    v_s := greatest(1, v_s - v_ctx);
    v_e := least(v_blen, v_e + v_ctx);
  END IF;

  FOR v_b IN SELECT * FROM jsonb_array_elements(v_blocks) b LOOP
    v_bs := (v_b->>'s')::bigint; v_be := (v_b->>'e')::bigint;
    IF v_s < v_bs AND v_bs <= v_e AND v_e <= v_be THEN
      v_e := v_bs - 1;
    END IF;
    IF v_bs <= v_s AND v_s <= v_be AND v_be < v_e THEN
      v_s := v_be + 1;
    END IF;
  END LOOP;

  v_bytes := convert_to(p_body, 'UTF8');
  v_i := 0;
  WHILE v_i < 4 LOOP
    EXIT WHEN get_byte(v_bytes, (v_s - 1)::int) NOT BETWEEN 128 AND 191;
    v_s := v_s + 1; v_i := v_i + 1;
  END LOOP;
  v_i := 0;
  WHILE v_i < 4 LOOP
    EXIT WHEN v_e >= v_blen;
    EXIT WHEN get_byte(v_bytes, v_e::int) NOT BETWEEN 128 AND 191;
    v_e := v_e + 1; v_i := v_i + 1;
  END LOOP;

  v_s := greatest(1, v_s); v_e := least(v_blen, v_e);
  IF v_s > v_e THEN RETURN '[]'::jsonb; END IF;
  RETURN jsonb_build_array(jsonb_build_object(
           'doc', p_hash,
           'offsets', jsonb_build_array(jsonb_build_array(v_s, v_e))));
END $$;

CREATE FUNCTION v13_assemble_spans(p_units jsonb, p_opts jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  u jsonb; v_hash text; v_body text;
  v_mode text;
  v_ctx bigint; v_gap bigint;
  v_raw jsonb; sp jsonb;
  v_s bigint; v_e bigint; v_ps bigint; v_pe bigint;
  v_out jsonb := '[]'::jsonb;
BEGIN
  IF p_opts ? 'mode'
     AND jsonb_typeof(p_opts->'mode') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (mode)'
      USING ERRCODE = 'V3004';
  END IF;
  v_mode := coalesce(p_opts->>'mode', 'span');
  IF (v_mode IN ('span','whole_chunk')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (mode)'
      USING ERRCODE = 'V3004';
  END IF;
  IF p_opts ? 'context_bytes'
     AND jsonb_typeof(p_opts->'context_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (context_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  v_ctx := coalesce((p_opts->>'context_bytes')::bigint, 0);
  IF p_opts ? 'merge_gap_bytes'
     AND jsonb_typeof(p_opts->'merge_gap_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (merge_gap_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  v_gap := coalesce((p_opts->>'merge_gap_bytes')::bigint, 0);
  IF v_ctx < 0 OR v_gap < 0 THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts' USING ERRCODE = 'V3004';
  END IF;
  FOR u IN SELECT * FROM jsonb_array_elements(p_units) LOOP
    v_hash := u->>'content_hash'; v_body := u->>'body';
    IF v_hash IS NULL OR v_body IS NULL THEN
      RAISE EXCEPTION 'v13: span unit requires content_hash and body'
        USING ERRCODE = 'V3004';
    END IF;
    IF v_mode = 'whole_chunk' THEN
      IF octet_length(v_body) = 0 THEN CONTINUE; END IF;
      v_out := v_out || jsonb_build_array(jsonb_build_object(
        'doc', v_hash,
        'offsets', jsonb_build_array(
          jsonb_build_array(1, octet_length(v_body)))));
      CONTINUE;
    END IF;
    v_raw := (SELECT coalesce(jsonb_agg(x ORDER BY (x->>0)::bigint), '[]'::jsonb)
                FROM (SELECT DISTINCT x
                        FROM jsonb_array_elements(
                          coalesce(u->'spans', '[]'::jsonb)) AS x) d);
    IF jsonb_array_length(v_raw) = 0 THEN CONTINUE; END IF;
    v_s := NULL; v_e := NULL;
    FOR sp IN SELECT * FROM jsonb_array_elements(v_raw) LOOP
      v_ps := (sp->>0)::bigint; v_pe := (sp->>1)::bigint;
      IF v_s IS NULL THEN
        v_s := v_ps; v_e := v_pe;
      ELSIF v_ps <= v_e + v_gap THEN
        v_e := greatest(v_e, v_pe);
      ELSE
        v_out := v_out || v13_span_unit(v_hash, v_body, v_s, v_e, p_opts);
        v_s := v_ps; v_e := v_pe;
      END IF;
    END LOOP;
    IF v_s IS NOT NULL THEN
      v_out := v_out || v13_span_unit(v_hash, v_body, v_s, v_e, p_opts);
    END IF;
  END LOOP;
  RETURN v_out;
END $$;

CREATE OR REPLACE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_corpus bigint; v_tok jsonb;
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
    'corpus',   v_corpus)
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
     IS DISTINCT FROM 'asm_ver,corpus,dec,gen_ver,goal,jdef_ver,sem,tools_rev'
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
     OR (p_manifest->'required_revision'->>'corpus')::bigint < 0 THEN
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

DO $cron$
DECLARE v_ext boolean;
BEGIN
  BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
  EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'v13: pg_cron unavailable (%) — night verify falls back to external scheduler; v13_verify_chunks() stays callable', SQLERRM;
    RETURN;
  END;
  IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'v13-verify-chunks') THEN
    PERFORM cron.schedule('v13-verify-chunks', '17 3 * * *',
                          $job$SELECT v13_verify_chunks(true)$job$);
  END IF;
END
$cron$;

REVOKE EXECUTE ON FUNCTION
  v13_chunker_slice(text,jsonb), v13_project_source(text,text,text,uuid,jsonb),
  v13_ingest_document(uuid,text,text,text), v13_rebuild_chunks(text),
  v13_chunk_gc(boolean), v13_verify_chunks(boolean),
  v13_span_unit(text,text,bigint,bigint,jsonb),
  v13_artifacts_ref_lock(), v13_decisions_ref_lock()
FROM PUBLIC;

GRANT SELECT ON chunks, v13_sources, v13_chunks_meta TO v13_recall;
GRANT EXECUTE ON FUNCTION
  v13_body_hash(text), v13_tsv_en(text),
  v13_extract_spans(text,jsonb), v13_assemble_spans(jsonb,jsonb),
  v13_span_unit(text,text,bigint,bigint,jsonb)
TO v13_recall, v13_resolve, v13_route;

COMMIT;
