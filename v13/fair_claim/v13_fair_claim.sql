-- v13 fair_claim (stage 39). Global claimed cap and multi-root fair claim.
-- No CREATE TABLE, no ALTER TABLE, no CREATE OR REPLACE of v13_claim / v13_advance.
BEGIN;

DO $probe$
DECLARE
  r record;
  v_claim text;
  v_open text;
  v_adv text;
  v_life text;
  v_vol text;
  v_definer boolean;
  v_oid regprocedure;
BEGIN
  IF to_regprocedure('public.v13_claim(text,integer)') IS NULL
     OR to_regprocedure('public.v13_advance(uuid,jsonb)') IS NULL
     OR to_regprocedure('public.v13_goal_lifecycle(uuid)') IS NULL
     OR to_regprocedure('public.v13_advisory_class(text)') IS NULL
     OR to_regprocedure('public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)') IS NULL
     OR to_regprocedure('public.v13_reject_bad_harness_request(text,text,jsonb)') IS NULL THEN
    RAISE EXCEPTION 'v13: claim fair: prefix missing';
  END IF;
  v_claim := pg_get_functiondef('public.v13_claim(text,integer)'::regprocedure);
  IF position($$status='ready'$$ IN v_claim) = 0
     AND position($$status = 'ready'$$ IN v_claim) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: live claim arms';
  END IF;
  IF position('v13_attempt_ok(kind, attempt_no)' IN v_claim) = 0
     OR position('op_seq IS NULL' IN v_claim) = 0
     OR position('v13_requires_worktree(tool_name)' IN v_claim) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: live claim arms';
  END IF;
  IF position('13001' IN pg_get_functiondef('public.v13_advisory_class(text)'::regprocedure)) = 0
     OR position('spawn_budget' IN pg_get_functiondef('public.v13_advisory_class(text)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: advisory class';
  END IF;
  SELECT p.provolatile INTO v_vol
    FROM pg_proc p
   WHERE p.oid = 'public.v13_goal_lifecycle(uuid)'::regprocedure;
  v_life := pg_get_functiondef('public.v13_goal_lifecycle(uuid)'::regprocedure);
  IF v_vol IS DISTINCT FROM 's'
     OR position('RETURNS text' IN v_life) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: lifecycle';
  END IF;
  SELECT prosecdef INTO v_definer
    FROM pg_proc
   WHERE oid = 'public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)'::regprocedure;
  IF v_definer IS DISTINCT FROM false THEN
    RAISE EXCEPTION 'v13: claim fair: opener definer';
  END IF;
  v_open := pg_get_functiondef(
    'public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)'::regprocedure);
  IF position('not_single_tree' IN v_open) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: opener token';
  END IF;
  v_adv := pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure);
  IF position('CREATE OR REPLACE FUNCTION public.v13_claim(' IN v_adv) > 0 THEN
    RAISE EXCEPTION 'v13: claim fair: advance body';
  END IF;
  FOR r IN
    SELECT p.proname AS n, pg_get_functiondef(p.oid) AS def
      FROM pg_proc p
      JOIN pg_namespace ns ON ns.oid = p.pronamespace
     WHERE ns.nspname = 'public'
       AND p.proname NOT IN (
         'v13_claim_fair', 'v13_fair_root', 'v13_fair_eligible',
         'v13_fair_snapshot', 'v13_path_conflict_locked',
         'v13_workspace_path_guard')
  LOOP
    IF position('13002' IN r.def) > 0 OR position('13003' IN r.def) > 0 THEN
      RAISE EXCEPTION 'v13: claim fair: lock class collision';
    END IF;
  END LOOP;
  v_oid := to_regprocedure('public.v13_claim_fair(text,integer)');
  IF v_oid IS NOT NULL
     AND position('v13: claim fair:' IN pg_get_functiondef(v_oid)) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: name collision';
  END IF;
  v_oid := to_regprocedure('public.v13_fair_root(uuid)');
  IF v_oid IS NOT NULL
     AND position('v13_fair_root' IN pg_get_functiondef(v_oid)) = 0 THEN
    RAISE EXCEPTION 'v13: claim fair: name collision';
  END IF;
END
$probe$;

DO $seed$
DECLARE
  v_have jsonb;
  v_active boolean;
  v_want jsonb := '{"schema_version":1,"claimed_cap":2}'::jsonb;
BEGIN
  SELECT value, active
    INTO v_have, v_active
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1;
  IF NOT FOUND THEN
    INSERT INTO public.v13_policies (name, version, value, active)
    VALUES ('global_concurrency', 1, v_want, true);
  ELSIF v_have IS DISTINCT FROM v_want OR v_active IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'v13: claim fair: policy';
  END IF;
END
$seed$;

CREATE OR REPLACE FUNCTION public.v13_fair_root(p_sid uuid)
RETURNS uuid
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_cur uuid := p_sid;
  v_parent uuid;
  v_depth int := 0;
  v_seen uuid[];
BEGIN
  IF p_sid IS NULL THEN
    RETURN NULL;
  END IF;
  v_seen := ARRAY[p_sid];
  LOOP
    SELECT parent_session_id INTO v_parent
      FROM public.sessions
     WHERE session_id = v_cur;
    IF NOT FOUND THEN
      RETURN NULL;
    END IF;
    EXIT WHEN v_parent IS NULL;
    v_depth := v_depth + 1;
    IF v_depth > 64 OR v_parent = ANY (v_seen) THEN
      RETURN NULL;
    END IF;
    v_seen := v_seen || v_parent;
    v_cur := v_parent;
  END LOOP;
  RETURN v_cur;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_fair_eligible(p_effect uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_e public.effects%ROWTYPE;
  v_st text;
  v_root uuid;
BEGIN
  SELECT * INTO v_e FROM public.effects WHERE effect_id = p_effect;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF v_e.status IS DISTINCT FROM 'ready' THEN
    RETURN false;
  END IF;
  IF NOT public.v13_attempt_ok(v_e.kind, v_e.attempt_no) THEN
    RETURN false;
  END IF;
  IF v_e.op_seq IS NOT NULL AND v_e.op_seq IS DISTINCT FROM (
       SELECT min(x.op_seq) FROM public.effects x
        WHERE x.session_id = v_e.session_id
          AND x.mutation_scope = v_e.mutation_scope
          AND x.status <> 'succeeded') THEN
    RETURN false;
  END IF;
  IF public.v13_requires_worktree(v_e.tool_name)
     AND NOT EXISTS (
       SELECT 1 FROM public.latches l
        WHERE l.session_id = v_e.session_id AND l.name = 'worktree') THEN
    RETURN false;
  END IF;
  SELECT status INTO v_st
    FROM public.sessions
   WHERE session_id = v_e.session_id;
  IF NOT FOUND OR v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN false;
  END IF;
  v_root := public.v13_fair_root(v_e.session_id);
  IF v_root IS NULL THEN
    RETURN false;
  END IF;
  IF public.v13_goal_lifecycle(v_root) = 'stopped'
     OR public.v13_goal_lifecycle(v_e.session_id) = 'stopped' THEN
    RETURN false;
  END IF;
  RETURN true;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_fair_snapshot()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_n int;
  v_val jsonb;
  v_cap int;
  v_claimed int;
  v_unresolved int;
  v_total int;
  v_omit int;
  v_roots jsonb;
BEGIN
  SELECT count(*) INTO v_n
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1
     AND active;
  IF v_n IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: fair snapshot: policy';
  END IF;
  SELECT value INTO v_val
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1
     AND active;
  IF jsonb_typeof(v_val) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_val)
        IS DISTINCT FROM ARRAY['claimed_cap', 'schema_version']
     OR NOT public.v13_json_int_ok(v_val->'schema_version', 1)
     OR (v_val->'schema_version')::text::numeric IS DISTINCT FROM 1
     OR NOT public.v13_json_int_ok(v_val->'claimed_cap', 2147483647)
     OR (v_val->>'claimed_cap')::int < 1 THEN
    RAISE EXCEPTION 'v13: fair snapshot: policy';
  END IF;
  v_cap := (v_val->>'claimed_cap')::int;
  SELECT count(*) INTO v_claimed
    FROM public.effects
   WHERE status = 'claimed';
  SELECT count(*) INTO v_unresolved
    FROM public.sessions s
   WHERE public.v13_fair_root(s.session_id) IS NULL;
  SELECT count(*) INTO v_total
    FROM public.sessions s
   WHERE s.parent_session_id IS NULL
     AND public.v13_fair_root(s.session_id) IS NOT NULL;
  IF v_total > 32 THEN
    v_omit := 1;
  ELSE
    v_omit := 0;
  END IF;
  SELECT coalesce(jsonb_agg(elem ORDER BY root_key COLLATE "C"), '[]'::jsonb)
    INTO v_roots
    FROM (
      SELECT r.root_id::text AS root_key,
             jsonb_build_object(
               'root_session_id', r.root_id,
               'inflight_claimed', (
                 SELECT count(*) FROM public.effects e
                  WHERE e.status = 'claimed'
                    AND public.v13_fair_root(e.session_id) = r.root_id),
               'claimable_ready', (
                 SELECT count(*) FROM public.effects e
                  WHERE public.v13_fair_eligible(e.effect_id)
                    AND public.v13_fair_root(e.session_id) = r.root_id),
               'oldest_ready_at', (
                 SELECT min(e.created_at) FROM public.effects e
                  WHERE public.v13_fair_eligible(e.effect_id)
                    AND public.v13_fair_root(e.session_id) = r.root_id)
             ) AS elem
        FROM (
          SELECT s.session_id AS root_id
            FROM public.sessions s
           WHERE s.parent_session_id IS NULL
             AND public.v13_fair_root(s.session_id) IS NOT NULL
           ORDER BY s.session_id::text COLLATE "C"
           LIMIT 32
        ) r
    ) q;
  RETURN jsonb_build_object(
    'schema_version', 1,
    'claimed_cap', v_cap,
    'claimed_count', v_claimed,
    'omitted_count', v_omit,
    'omitted_complete', (v_omit = 0),
    'unresolved_count', v_unresolved,
    'roots', v_roots);
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_path_conflict_locked(p_request jsonb)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root text;
  v_paths jsonb;
  v_rel text;
  v_seg text;
  v_segs text[];
  v_busy jsonb;
  v_their_root text;
  v_their text;
  v_oa text[];
  v_ob text[];
  v_na int;
  v_nb int;
  v_i int;
  v_match boolean;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  IF p_request IS NULL
     OR jsonb_typeof(p_request) IS DISTINCT FROM 'object'
     OR jsonb_typeof(p_request->'workspace_root') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_request->'paths') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  v_root := p_request->>'workspace_root';
  v_paths := p_request->'paths';
  IF v_root IS NULL
     OR v_root = ''
     OR v_root = '/'
     OR left(v_root, 1) IS DISTINCT FROM '/'
     OR position(E'\\' IN v_root) > 0
     OR position('\x00'::bytea IN convert_to(v_root, 'UTF8')) > 0 THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  v_segs := string_to_array(v_root, '/');
  IF cardinality(v_segs) >= 1 AND v_segs[1] = '' THEN
    v_segs := v_segs[2:cardinality(v_segs)];
  END IF;
  IF v_segs IS NULL OR cardinality(v_segs) < 1 THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  FOREACH v_seg IN ARRAY v_segs LOOP
    IF v_seg IS NULL OR v_seg = '' OR v_seg = '.' OR v_seg = '..' THEN
      RAISE EXCEPTION 'v13: workspace open: canonical';
    END IF;
  END LOOP;
  IF jsonb_array_length(v_paths) < 1 THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  FOR v_rel IN SELECT jsonb_array_elements_text(v_paths) LOOP
    IF v_rel IS NULL
       OR v_rel = ''
       OR left(v_rel, 1) = '/'
       OR right(v_rel, 1) = '/'
       OR position(E'\\' IN v_rel) > 0
       OR position('\x00'::bytea IN convert_to(v_rel, 'UTF8')) > 0 THEN
      RAISE EXCEPTION 'v13: workspace open: canonical';
    END IF;
    v_segs := string_to_array(v_rel, '/');
    IF v_segs IS NULL OR cardinality(v_segs) < 1 THEN
      RAISE EXCEPTION 'v13: workspace open: canonical';
    END IF;
    FOREACH v_seg IN ARRAY v_segs LOOP
      IF v_seg IS NULL OR v_seg = '' OR v_seg = '.' OR v_seg = '..' THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
    END LOOP;
  END LOOP;
  PERFORM pg_advisory_xact_lock(13003, 1);
  FOR v_busy IN
    SELECT request
      FROM public.effects
     WHERE kind = 'tool'
       AND status IN ('ready', 'claimed', 'unknown')
       AND request ? 'workspace_root'
  LOOP
    IF jsonb_typeof(v_busy->'workspace_root') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_busy->'paths') IS DISTINCT FROM 'array' THEN
      CONTINUE;
    END IF;
    v_their_root := v_busy->>'workspace_root';
    FOR v_rel IN SELECT jsonb_array_elements_text(p_request->'paths') LOOP
      FOR v_their IN SELECT jsonb_array_elements_text(v_busy->'paths') LOOP
        v_oa := string_to_array(rtrim(v_root, '/') || '/' || v_rel, '/');
        v_ob := string_to_array(rtrim(v_their_root, '/') || '/' || v_their, '/');
        v_na := cardinality(v_oa);
        v_nb := cardinality(v_ob);
        v_match := true;
        IF v_na IS NULL OR v_nb IS NULL OR v_na < 1 OR v_nb < 1 THEN
          v_match := false;
        ELSE
          FOR v_i IN 1..least(v_na, v_nb) LOOP
            IF v_oa[v_i] IS DISTINCT FROM v_ob[v_i] THEN
              v_match := false;
              EXIT;
            END IF;
          END LOOP;
        END IF;
        IF v_match THEN
          RAISE EXCEPTION 'v13: workspace open: path_busy';
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_workspace_path_guard()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
BEGIN
  PERFORM public.v13_path_conflict_locked(NEW.request);
  RETURN NEW;
END
$fn$;

DROP TRIGGER IF EXISTS trg_effects_workspace_path_lock ON public.effects;
CREATE TRIGGER trg_effects_workspace_path_lock
  BEFORE INSERT ON public.effects
  FOR EACH ROW
  WHEN (NEW.kind = 'tool' AND NEW.request ? 'workspace_root')
  EXECUTE FUNCTION public.v13_workspace_path_guard();

CREATE OR REPLACE FUNCTION public.v13_claim_fair(
  p_worker text,
  p_lease_ms integer DEFAULT 60000
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_n int;
  v_val jsonb;
  v_cap int;
  v_claimed int;
  v_eid uuid;
  v_sid uuid;
  v_root uuid;
  v_sess_st text;
  v_out jsonb;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: claim fair: canonical';
  END IF;
  IF p_worker IS NULL
     OR char_length(p_worker) < 1
     OR char_length(p_worker) > 128
     OR position('\x00'::bytea IN convert_to(p_worker, 'UTF8')) > 0
     OR p_worker = 'v13_workspace_opener' THEN
    RAISE EXCEPTION 'v13: claim fair: canonical';
  END IF;
  IF p_lease_ms IS NULL OR p_lease_ms < 1 OR p_lease_ms > 600000 THEN
    RAISE EXCEPTION 'v13: claim fair: canonical';
  END IF;
  SELECT count(*) INTO v_n
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1
     AND active;
  IF v_n IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: claim fair: policy';
  END IF;
  SELECT value INTO v_val
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1
     AND active;
  IF jsonb_typeof(v_val) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_val)
        IS DISTINCT FROM ARRAY['claimed_cap', 'schema_version']
     OR NOT public.v13_json_int_ok(v_val->'schema_version', 1)
     OR (v_val->'schema_version')::text::numeric IS DISTINCT FROM 1
     OR NOT public.v13_json_int_ok(v_val->'claimed_cap', 2147483647)
     OR (v_val->>'claimed_cap')::int < 1 THEN
    RAISE EXCEPTION 'v13: claim fair: policy';
  END IF;
  v_cap := (v_val->>'claimed_cap')::int;
  PERFORM pg_advisory_xact_lock(13002, 1);
  SELECT count(*) INTO v_n
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1
     AND active;
  IF v_n IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: claim fair: policy';
  END IF;
  SELECT value INTO v_val
    FROM public.v13_policies
   WHERE name = 'global_concurrency'
     AND version = 1
     AND active;
  IF jsonb_typeof(v_val) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_val)
        IS DISTINCT FROM ARRAY['claimed_cap', 'schema_version']
     OR NOT public.v13_json_int_ok(v_val->'schema_version', 1)
     OR (v_val->'schema_version')::text::numeric IS DISTINCT FROM 1
     OR NOT public.v13_json_int_ok(v_val->'claimed_cap', 2147483647)
     OR (v_val->>'claimed_cap')::int < 1 THEN
    RAISE EXCEPTION 'v13: claim fair: policy';
  END IF;
  v_cap := (v_val->>'claimed_cap')::int;
  SELECT count(*) INTO v_claimed
    FROM public.effects
   WHERE status = 'claimed';
  IF v_claimed >= v_cap THEN
    RETURN NULL;
  END IF;
  WITH claimed_roots AS (
    SELECT public.v13_fair_root(session_id) AS root_id,
           count(*)::int AS n
      FROM public.effects
     WHERE status = 'claimed'
     GROUP BY 1
  )
  SELECT e.effect_id, e.session_id, public.v13_fair_root(e.session_id)
    INTO v_eid, v_sid, v_root
    FROM public.effects e
   WHERE public.v13_fair_eligible(e.effect_id)
   ORDER BY coalesce((
              SELECT n FROM claimed_roots
               WHERE root_id = public.v13_fair_root(e.session_id)
            ), 0),
            e.created_at,
            e.effect_id
   LIMIT 1;
  IF v_eid IS NULL OR v_root IS NULL THEN
    RETURN NULL;
  END IF;
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  IF v_sid IS DISTINCT FROM v_root THEN
    PERFORM 1
       FROM public.sessions
      WHERE session_id = v_sid
        FOR UPDATE;
    IF NOT FOUND THEN
      RETURN NULL;
    END IF;
  END IF;
  SELECT status INTO v_sess_st
    FROM public.sessions
   WHERE session_id = v_sid;
  IF v_sess_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN NULL;
  END IF;
  IF public.v13_goal_lifecycle(v_root) = 'stopped'
     OR public.v13_goal_lifecycle(v_sid) = 'stopped'
     OR NOT public.v13_fair_eligible(v_eid)
     OR public.v13_fair_root(v_sid) IS DISTINCT FROM v_root THEN
    RETURN NULL;
  END IF;
  BEGIN
    PERFORM 1
       FROM public.effects
      WHERE effect_id = v_eid
        FOR UPDATE NOWAIT;
  EXCEPTION
    WHEN lock_not_available THEN
      RETURN NULL;
  END;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  SELECT count(*) INTO v_claimed
    FROM public.effects
   WHERE status = 'claimed';
  IF v_claimed >= v_cap THEN
    RETURN NULL;
  END IF;
  UPDATE public.effects
     SET status = 'claimed',
         attempt_no = attempt_no + 1,
         fence = fence + 1,
         lease_owner = p_worker,
         lease_until = clock_timestamp()
                       + make_interval(secs => p_lease_ms / 1000.0)
   WHERE effect_id = v_eid
     AND status = 'ready';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n IS DISTINCT FROM 1 THEN
    RETURN NULL;
  END IF;
  SELECT jsonb_build_object(
           'effect_id', effect_id,
           'attempt_no', attempt_no,
           'fence', fence,
           'kind', kind,
           'request', request,
           'root_session_id', v_root)
    INTO v_out
    FROM public.effects
   WHERE effect_id = v_eid;
  RETURN v_out;
END
$fn$;

REVOKE EXECUTE ON FUNCTION
  public.v13_claim_fair(text, integer),
  public.v13_fair_root(uuid),
  public.v13_fair_eligible(uuid),
  public.v13_fair_snapshot(),
  public.v13_path_conflict_locked(jsonb),
  public.v13_workspace_path_guard()
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
  public.v13_path_conflict_locked(jsonb),
  public.v13_workspace_path_guard()
TO v13_route;

COMMIT;
