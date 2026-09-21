BEGIN;

CREATE TABLE v13_goals (
  session_id   uuid NOT NULL,
  seq          bigint NOT NULL,
  content_hash text NOT NULL,
  payload      jsonb NOT NULL,
  PRIMARY KEY (session_id, seq),
  FOREIGN KEY (session_id, seq) REFERENCES events (session_id, seq),
  CONSTRAINT v13_goals_hash_selfcheck
    CHECK (content_hash = encode(digest(payload::text, 'sha256'), 'hex'))
);

CREATE FUNCTION v13_goals_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: v13_goals is append-only (% on % seq %)',
    TG_OP, TG_TABLE_NAME, OLD.seq;
END $$;
CREATE TRIGGER trg_v13_goals_append_only
  BEFORE UPDATE OR DELETE ON v13_goals
  FOR EACH ROW EXECUTE FUNCTION v13_goals_append_only();

CREATE FUNCTION v13_goal_project() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
  INSERT INTO public.v13_goals (session_id, seq, content_hash, payload)
  VALUES (NEW.session_id, NEW.seq,
          encode(digest(NEW.payload::text, 'sha256'), 'hex'), NEW.payload);
  RETURN NEW;
END $$;
CREATE TRIGGER trg_events_goal
  AFTER INSERT ON events FOR EACH ROW
  WHEN (NEW.type = 'user/message')
  EXECUTE FUNCTION v13_goal_project();

INSERT INTO v13_goals (session_id, seq, content_hash, payload)
SELECT e.session_id, e.seq,
       encode(digest(e.payload::text, 'sha256'), 'hex'), e.payload
  FROM events e WHERE e.type = 'user/message'
ON CONFLICT DO NOTHING;

CREATE FUNCTION v13_goal_hash(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT g.content_hash FROM v13_goals g
                    WHERE g.session_id = p_sid
                 ORDER BY g.seq DESC LIMIT 1),
                  encode(digest(''::text, 'sha256'), 'hex'));
$$;

CREATE TABLE artifacts (
  artifact_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_hash text NOT NULL,
  kind         text NOT NULL,
  inline       jsonb,
  ref          text,
  size         bigint NOT NULL,
  produced_by  uuid NOT NULL REFERENCES effects (effect_id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT v13_artifacts_selfcheck
    CHECK (inline IS NULL OR
           (content_hash = encode(digest(inline::text, 'sha256'), 'hex')
            AND size = octet_length(inline::text)))
);
CREATE INDEX ix_artifacts_content ON artifacts (content_hash);
CREATE INDEX ix_artifacts_kind ON artifacts (kind, created_at DESC);
CREATE UNIQUE INDEX uq_artifacts_context_section
  ON artifacts (content_hash) WHERE kind = 'context_section';

CREATE FUNCTION v13_artifacts_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: artifacts is append-only (% on %)',
    TG_OP, TG_TABLE_NAME;
END $$;
CREATE TRIGGER trg_artifacts_append_only
  BEFORE UPDATE OR DELETE ON artifacts
  FOR EACH ROW EXECUTE FUNCTION v13_artifacts_append_only();

CREATE FUNCTION v13_artifacts_effect_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_status text;
BEGIN
  SELECT status INTO v_status FROM effects WHERE effect_id = NEW.produced_by;
  IF v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: artifact produced_by must reference a succeeded effect (%)',
      NEW.produced_by;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_artifacts_effect_guard
  BEFORE INSERT ON artifacts FOR EACH ROW
  EXECUTE FUNCTION v13_artifacts_effect_guard();

ALTER TABLE sessions
  ADD COLUMN context_active_revision jsonb,
  ADD COLUMN context_active_artifact uuid
    REFERENCES artifacts (artifact_id);

CREATE FUNCTION v13_ctx_ptr_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_kind text;
BEGIN
  IF NEW.context_active_artifact IS NOT NULL THEN
    SELECT kind INTO v_kind FROM artifacts
     WHERE artifact_id = NEW.context_active_artifact;
    IF v_kind IS DISTINCT FROM 'context' THEN
      RAISE EXCEPTION 'v13: context_active_artifact must reference kind=''context'' (%)',
        NEW.context_active_artifact;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_sessions_ctx_ptr_guard
  BEFORE INSERT OR UPDATE OF context_active_artifact ON sessions
  FOR EACH ROW EXECUTE FUNCTION v13_ctx_ptr_guard();

ALTER TABLE decisions
  ADD COLUMN epoch text NOT NULL DEFAULT 'pre-bind'
    CHECK (epoch IN ('pre-bind','pre-finalize','post-execute'));

ALTER TABLE judgment_templates
  ADD COLUMN epoch text NOT NULL DEFAULT 'pre-bind'
    CHECK (epoch IN ('pre-bind','pre-finalize','post-execute'));

CREATE FUNCTION v13_decisions_epoch_fill() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_epoch text;
BEGIN
  IF NEW.template_name IS NOT NULL THEN
    SELECT epoch INTO v_epoch FROM judgment_templates
       WHERE template_name = NEW.template_name
         AND template_version = NEW.template_version;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'v13: decisions references missing template % v%',
        NEW.template_name, NEW.template_version
        USING ERRCODE = 'V3002';
    END IF;
    NEW.epoch := v_epoch;
  ELSE
    NEW.epoch := 'pre-bind';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decisions_epoch
  BEFORE INSERT ON decisions FOR EACH ROW
  EXECUTE FUNCTION v13_decisions_epoch_fill();

CREATE FUNCTION v13_epoch_frozen() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: decisions.epoch is frozen at insert (%)', OLD.decision_id;
END $$;
CREATE TRIGGER trg_decisions_epoch_freeze
  BEFORE UPDATE OF epoch ON decisions
  FOR EACH ROW EXECUTE FUNCTION v13_epoch_frozen();

CREATE INDEX ix_events_semantic ON events (session_id, seq)
  WHERE type IN ('user/message','llm/message','tool/result');

INSERT INTO v13_policies (name, version, value, active) VALUES
 ('assemble_manifest', 1,
  '{"budget_tokens": 8192, "est_bytes_per_token": 4, "priority_overrides": {}, "kinds_disabled": [], "inline_max_bytes": 1048576, "blob_retention": "referenced-forever"}'::jsonb, true),
 ('generation', 1,
  '{"provider": "mock", "model": "mock-1", "system_blocks_digest": "-none-"}'::jsonb, true),
 ('judgment_defaults', 1,
  '{"points": {}, "actions": ["include", "exclude", "degrade", "fail"]}'::jsonb, true);

CREATE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_tok jsonb;
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
    'gen_ver',  v_gen_ver)
  INTO v_tok;
  RETURN v_tok;
END $$;

CREATE OR REPLACE FUNCTION v13_context_fresh(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT v13_context_required(p_sid) IS NOT DISTINCT FROM
         (SELECT context_active_revision FROM sessions
           WHERE session_id = p_sid);
$$;
COMMENT ON FUNCTION v13_context_fresh(uuid) IS
  'DP3: required_revision (v13_context_required) vs sessions.context_active_revision. design §5.2/§6.1.';

CREATE FUNCTION v13_latch_digest(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT '-none-'::text $$;
COMMENT ON FUNCTION v13_latch_digest(uuid) IS
  'DP8 seam: latches join prefix identity here (design §5.1/§5.6).';

CREATE FUNCTION v13_prefix_identity(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_mat jsonb; v_gen jsonb; v_trev int;
BEGIN
  SELECT value INTO v_gen FROM v13_policies
   WHERE name = 'generation' AND active;
  IF v_gen IS NULL OR v_gen->>'provider' IS NULL
     OR v_gen->>'model' IS NULL
     OR v_gen->>'system_blocks_digest' IS NULL THEN
    RAISE EXCEPTION 'v13: no active generation policy (seed lost?)';
  END IF;
  SELECT revision INTO v_trev FROM v13_tools_meta WHERE singleton;
  IF v_trev IS NULL THEN
    RAISE EXCEPTION 'v13: v13_tools_meta singleton row missing';
  END IF;
  SELECT jsonb_build_object(
    'provider',  v_gen->>'provider',
    'model',     v_gen->>'model',
    'system_blocks_digest', v_gen->>'system_blocks_digest',
    'tools_rev', v_trev,
    'tools_digest', encode(digest(
      coalesce((v13_canonical_state(p_sid) -> 'tools')::text, ''),
      'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'latch_digest', v13_latch_digest(p_sid),
    'manifest_version', 1)
  INTO v_mat;
  RETURN encode(digest(v_mat::text, 'sha256'), 'hex');
END $$;

CREATE FUNCTION v13_manifest_validate(p_manifest jsonb) RETURNS void
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
     IS DISTINCT FROM 'asm_ver,dec,gen_ver,goal,jdef_ver,sem,tools_rev'
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
     OR (p_manifest->'required_revision'->>'gen_ver')::int < 1 THEN
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

CREATE FUNCTION v13_judgment_defaults_check(p_value jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE v_pt text; v_act jsonb;
BEGIN
  IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: judgment_defaults must be a jsonb object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_value) k)
     IS DISTINCT FROM 'actions,points' THEN
    RAISE EXCEPTION 'v13: judgment_defaults key set mismatch (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_value->'actions') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_value->'actions') <> 4
     OR NOT (p_value->'actions')
         @> '["include","exclude","degrade","fail"]'::jsonb THEN
    RAISE EXCEPTION 'v13: judgment_defaults actions vocabulary violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_value->'points') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: judgment_defaults.points must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR v_pt, v_act IN SELECT key, value FROM jsonb_each(p_value->'points') LOOP
    IF jsonb_typeof(v_act) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: judgment_defaults point % must be an object (V3003)', v_pt
      USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(v_act) k)
       IS DISTINCT FROM 'missing,review,timeout'
       OR (v_act->>'missing')
          IN ('include','exclude','degrade','fail') IS NOT TRUE
       OR (v_act->>'timeout')
          IN ('include','exclude','degrade','fail') IS NOT TRUE
       OR (v_act->>'review')
          IN ('include','exclude','degrade','fail') IS NOT TRUE THEN
      RAISE EXCEPTION 'v13: judgment_defaults point % shape violation (V3003)', v_pt
      USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
END $$;

CREATE FUNCTION v13_assemble_manifest(p_sid uuid, p_policy_version int DEFAULT NULL)
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
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'), 'hex'),
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
    'candidates', (SELECT coalesce(jsonb_agg(c ORDER BY c->>'content_hash'),
                                   '[]'::jsonb)
                     FROM (SELECT jsonb_build_object(
                             'content_hash', ga.a->>'content_hash',
                             'bm25',  NULL,
                             'spans', '[]'::jsonb,
                             'decision_id', NULL) AS c
                             FROM goal_addr ga
                            WHERE ga.a ? 'content_hash') c)
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

CREATE FUNCTION v13_artifact_land(p_effect uuid, p_kind text, p_inline jsonb)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_art uuid; v_status text;
BEGIN
  IF p_kind IS DISTINCT FROM 'context' THEN
    RAISE EXCEPTION 'v13: v13_artifact_land only lands kind=''context''';
  END IF;
  SELECT status INTO v_status FROM public.effects WHERE effect_id = p_effect;
  IF v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: artifact produced_by must reference a succeeded effect (%)',
      p_effect;
  END IF;
  v_art := gen_random_uuid();
  INSERT INTO public.artifacts (artifact_id, content_hash, kind, inline, size,
                         produced_by)
  VALUES (v_art,
          encode(digest(p_inline::text, 'sha256'), 'hex'),
          p_kind, p_inline, octet_length(p_inline::text), p_effect);
  RETURN v_art;
END $$;

CREATE FUNCTION v13_blob_land(p_effect uuid, p_inline jsonb)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_h text; v_status text;
BEGIN
  SELECT status INTO v_status FROM public.effects WHERE effect_id = p_effect;
  IF v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: artifact produced_by must reference a succeeded effect (%)',
      p_effect;
  END IF;
  v_h := encode(digest(coalesce(p_inline::text, ''), 'sha256'), 'hex');
  INSERT INTO public.artifacts (artifact_id, content_hash, kind, inline, size,
                         produced_by)
  VALUES (gen_random_uuid(), v_h, 'context_section', p_inline,
          octet_length(coalesce(p_inline::text, '')), p_effect)
  ON CONFLICT (content_hash) WHERE kind = 'context_section' DO NOTHING;
  RETURN v_h;
END $$;

CREATE FUNCTION v13_refresh_context(p_effect uuid, p_attempt int, p_fence bigint)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_row effects; v_sid uuid; v_manifest jsonb; v_art uuid; v_out text;
        v_budget int; v_div int; v_inline_max bigint;
        v_ovr jsonb; v_off jsonb;
        v_hist jsonb; v_tools jsonb; v_hh text; v_th text; v_mh text;
BEGIN
  SELECT * INTO v_row FROM public.effects WHERE effect_id = p_effect;
  IF v_row.effect_id IS NULL THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF v_row.kind IS DISTINCT FROM 'context_refresh' THEN
    RAISE EXCEPTION 'v13: refresh settle on non-context_refresh effect %', p_effect;
  END IF;
  v_sid := v_row.session_id;

  IF v_row.status IS NOT DISTINCT FROM 'claimed'
     AND (v_row.attempt_no IS DISTINCT FROM p_attempt
          OR v_row.fence IS DISTINCT FROM p_fence) THEN
    RETURN 'stale';
  END IF;

  PERFORM 1 FROM public.sessions WHERE session_id = v_sid FOR UPDATE;
  PERFORM 1 FROM public.v13_tools_meta WHERE singleton FOR UPDATE;
  PERFORM 1 FROM public.v13_policies
   WHERE name IN ('assemble_manifest','generation','judgment_defaults')
     AND active
   ORDER BY name FOR UPDATE;

  SELECT (value->>'budget_tokens')::int,
         (value->>'est_bytes_per_token')::int,
         (value->>'inline_max_bytes')::bigint,
         value->'priority_overrides',
         value->'kinds_disabled'
    INTO v_budget, v_div, v_inline_max, v_ovr, v_off
   FROM public.v13_policies WHERE name = 'assemble_manifest' AND active;
  IF v_div IS NULL OR v_div <= 0 OR v_budget IS NULL OR v_budget < 0
     OR v_inline_max IS NULL OR v_inline_max <= 0
     OR jsonb_typeof(v_ovr) IS DISTINCT FROM 'object'
     OR (SELECT bool_or((o.value #>> '{}')
             IN ('Never','First','Normal','LastResort') IS NOT TRUE)
           FROM jsonb_each(v_ovr) o) IS TRUE
     OR jsonb_typeof(v_off) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: assemble_manifest policy shape invalid'
      USING ERRCODE = 'V3003';
  END IF;
  PERFORM public.v13_judgment_defaults_check(
    (SELECT value FROM public.v13_policies
      WHERE name = 'judgment_defaults' AND active));

  v_manifest := public.v13_assemble_manifest(v_sid, NULL);
  PERFORM public.v13_manifest_validate(v_manifest);

  IF octet_length(v_manifest::text) > v_inline_max THEN
    RAISE EXCEPTION 'v13: manifest exceeds inline_max_bytes (route to ref: DP4+)'
      USING ERRCODE = 'V3003';
  END IF;

  v_out := public.v13_complete(p_effect, p_attempt, p_fence, 'succeeded',
              jsonb_build_object(
                'required_revision', v_manifest->'required_revision',
                'sections', jsonb_array_length(v_manifest->'sections')));
  IF v_out IS DISTINCT FROM 'accepted' THEN
    RETURN v_out;
  END IF;

  v_hist  := public.v13_canonical_state(v_sid) -> 'messages';
  v_tools := public.v13_canonical_state(v_sid) -> 'tools';
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'history';
  v_hh := public.v13_blob_land(p_effect, v_hist);
  IF v_hh IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: history blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'tools';
  v_th := public.v13_blob_land(p_effect, v_tools);
  IF v_th IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: tools blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;

  v_art := public.v13_artifact_land(p_effect, 'context', v_manifest);
  UPDATE public.effects SET result = coalesce(result,'{}'::jsonb) ||
           jsonb_build_object('context_artifact_id', v_art)
   WHERE effect_id = p_effect;
  UPDATE public.sessions
     SET context_active_revision = v_manifest->'required_revision',
         context_active_artifact = v_art
   WHERE session_id = v_sid;
  RETURN 'accepted';
END $$;

CREATE OR REPLACE FUNCTION v13_probe(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'session_version', s.next_seq,
    'max_event_seq', coalesce((SELECT max(seq) FROM events
                                WHERE session_id = p_sid), -1),
    'goal_hash', v13_goal_hash(p_sid),
    'route_policy_name',     s.route_policy_name,
    'route_policy_version',  s.route_policy_version,
    'tools_revision', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta
        WHERE singleton))
  FROM sessions s WHERE s.session_id = p_sid;
$$;

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
      FROM sessions WHERE session_id = p_sid)
  SELECT jsonb_build_object(
    'sid', p_sid,
    'ctx', (SELECT c FROM ctx),
    'needed', (SELECT n FROM needed),
    'templates', (SELECT t FROM tmpl),
    'groups', (SELECT g FROM groups),
    'timeout_ms', NULLIF(current_setting('typesafe.timeout_ms', true), ''),
    'budget', v13_policy('resolve_fast_path'),
    'candidate_set_hash',
      encode(digest((SELECT n FROM needed)::text, 'sha256'), 'hex'),
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
    'needed_count', jsonb_array_length((SELECT n FROM needed)));
$$;

CREATE FUNCTION v13_replay(p_artifact uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT a.inline || jsonb_build_object(
           'replay', jsonb_build_object('mode', 'exact_replay',
                                        'source_artifact', a.artifact_id))
  FROM artifacts a
  WHERE a.artifact_id = p_artifact AND a.kind = 'context';
$$;

REVOKE EXECUTE ON FUNCTION
  v13_goal_hash(uuid), v13_context_required(uuid), v13_prefix_identity(uuid),
  v13_latch_digest(uuid), v13_manifest_validate(jsonb),
  v13_judgment_defaults_check(jsonb),
  v13_assemble_manifest(uuid,int), v13_refresh_context(uuid,int,bigint),
  v13_artifact_land(uuid,text,jsonb), v13_blob_land(uuid,jsonb),
  v13_replay(uuid),
  v13_goals_append_only(), v13_goal_project(), v13_artifacts_append_only(),
  v13_artifacts_effect_guard(), v13_decisions_epoch_fill(),
  v13_epoch_frozen(), v13_ctx_ptr_guard()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_goal_hash(uuid), v13_context_required(uuid), v13_prefix_identity(uuid),
  v13_latch_digest(uuid), v13_assemble_manifest(uuid,int),
  v13_replay(uuid)
TO v13_route, v13_resolve, v13_recall;
GRANT EXECUTE ON FUNCTION
  v13_refresh_context(uuid,int,bigint), v13_manifest_validate(jsonb)
TO v13_route;
GRANT EXECUTE ON FUNCTION v13_canonical_state(uuid)
TO v13_route;
GRANT SELECT ON v13_goals, artifacts TO v13_route, v13_resolve, v13_recall;

COMMIT;
