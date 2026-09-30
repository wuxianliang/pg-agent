DO $seed$
DECLARE
  v_have jsonb;
  v_active boolean;
  v_want jsonb := $policy${
    "argv_len_cap": 4,
    "bash_verbs": ["cp", "mkdir", "mv", "rm"],
    "find_depth_cap": 4,
    "labels": {
      "read_only": {"admits": ["find", "grep", "ls"]},
      "workspace_edit": {"admits": ["bash", "edit", "find", "grep", "ls", "write"]}
    },
    "paths_cap": 4,
    "result_text_cap_bytes": 51200,
    "schema_version": 1,
    "tool_open_attempts": 2
  }$policy$::jsonb;
BEGIN
  SELECT value, active
    INTO v_have, v_active
    FROM public.v13_policies
   WHERE name = 'workspace_tool_subset'
     AND version = 1;
  IF NOT FOUND THEN
    INSERT INTO public.v13_policies (name, version, value, active)
    VALUES ('workspace_tool_subset', 1, v_want, true);
  ELSIF v_have IS DISTINCT FROM v_want OR v_active IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'v13: workspace policy: drift';
  END IF;
END
$seed$;

CREATE OR REPLACE FUNCTION public.v13_workspace_policy()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_value jsonb;
  v_active boolean;
  v_ro jsonb;
  v_ed jsonb;
BEGIN
  SELECT value, active
    INTO v_value, v_active
    FROM public.v13_policies
   WHERE name = 'workspace_tool_subset'
     AND version = 1;
  IF NOT FOUND OR v_active IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'v13: workspace policy: missing';
  END IF;
  v_ro := v_value->'labels'->'read_only';
  v_ed := v_value->'labels'->'workspace_edit';
  IF jsonb_typeof(v_value) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_value) IS DISTINCT FROM
        ARRAY['argv_len_cap', 'bash_verbs', 'find_depth_cap', 'labels',
              'paths_cap', 'result_text_cap_bytes', 'schema_version',
              'tool_open_attempts']
     OR v_value->'schema_version' IS DISTINCT FROM '1'::jsonb
     OR jsonb_typeof(v_value->'argv_len_cap') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_value->'find_depth_cap') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_value->'paths_cap') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_value->'result_text_cap_bytes') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_value->'tool_open_attempts') IS DISTINCT FROM 'number'
     OR v_value->'bash_verbs' IS DISTINCT FROM '["cp","mkdir","mv","rm"]'::jsonb
     OR public.v13_json_keys(v_value->'labels') IS DISTINCT FROM
        ARRAY['read_only', 'workspace_edit']
     OR public.v13_json_keys(v_ro) IS DISTINCT FROM ARRAY['admits']
     OR public.v13_json_keys(v_ed) IS DISTINCT FROM ARRAY['admits']
     OR v_ro->'admits' IS DISTINCT FROM '["find","grep","ls"]'::jsonb
     OR v_ed->'admits' IS DISTINCT FROM
        '["bash","edit","find","grep","ls","write"]'::jsonb THEN
    RAISE EXCEPTION 'v13: workspace policy: canonical';
  END IF;
  RETURN v_value;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_tool_effect_open(
  p_actor uuid,
  p_session uuid,
  p_label text,
  p_workspace_root text,
  p_allowed_roots text[],
  p_request jsonb
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_st text;
  v_rst text;
  v_pol jsonb;
  v_tool text;
  v_paths text[];
  v_path text;
  v_seg text;
  v_acc text;
  v_parent text;
  v_i int;
  v_j int;
  v_payload jsonb;
  v_keys text[];
  v_argv text[];
  v_arg text;
  v_verb text;
  v_cap int;
  v_canonical jsonb;
  v_id uuid;
  v_row effects;
  v_busy effects;
  v_n int;
  v_our text;
  v_their text;
  v_oa text[];
  v_ob text[];
  v_na int;
  v_nb int;
  v_match boolean;
  v_lower text;
  v_seen text[];
  v_attempt text;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  IF p_actor IS NULL THEN
    IF NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: workspace open: auth';
    END IF;
  ELSIF NOT public.v13_control_authorized(p_actor, p_session) THEN
    RAISE EXCEPTION 'v13: workspace open: auth';
  END IF;
  IF (
    SELECT count(*)
      FROM public.sessions
     WHERE parent_session_id IS NULL) > 1 THEN
    RAISE EXCEPTION 'v13: workspace open: not_single_tree';
  END IF;
  v_root := public.v13_plan_map_root(p_session);
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: workspace open: terminal';
  END IF;
  PERFORM 1
     FROM public.sessions
    WHERE session_id = p_session
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: workspace open: terminal';
  END IF;
  SELECT status INTO v_rst FROM public.sessions WHERE session_id = v_root;
  SELECT status INTO v_st FROM public.sessions WHERE session_id = p_session;
  IF v_rst IN ('completed', 'failed', 'cancelled')
     OR v_st IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: workspace open: terminal';
  END IF;
  IF public.v13_goal_lifecycle(v_root) = 'stopped'
     OR public.v13_goal_lifecycle(p_session) = 'stopped' THEN
    RAISE EXCEPTION 'v13: workspace open: stopped';
  END IF;
  IF public.v13_pending_human(p_session) THEN
    RAISE EXCEPTION 'v13: workspace open: human_pending';
  END IF;
  IF public.v13_plan_current(v_root) IS NULL THEN
    RAISE EXCEPTION 'v13: workspace open: no_plan';
  END IF;
  IF NOT public.v13_should_run(v_root) THEN
    RAISE EXCEPTION 'v13: workspace open: should_run';
  END IF;
  v_pol := public.v13_workspace_policy();
  IF p_workspace_root IS NULL
     OR p_workspace_root = '/'
     OR p_workspace_root = ''
     OR p_allowed_roots IS NULL
     OR (p_workspace_root = ANY (p_allowed_roots)) IS DISTINCT FROM true
     OR EXISTS (
          SELECT 1 FROM unnest(p_allowed_roots) AS allowed_root
           WHERE allowed_root IS NULL) THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  IF p_request IS NULL
     OR jsonb_typeof(p_request) IS DISTINCT FROM 'object'
     OR p_request ? 'workspace_root'
     OR public.v13_json_keys(p_request) IS DISTINCT FROM
        ARRAY['attempt_key', 'label', 'paths', 'payload', 'schema_version', 'tool']
     OR NOT public.v13_json_int_ok(p_request->'schema_version', 1)
     OR (p_request->>'schema_version') IS DISTINCT FROM '1'
     OR jsonb_typeof(p_request->'tool') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_request->'label') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_request->'attempt_key') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_request->'paths') IS DISTINCT FROM 'array'
     OR jsonb_typeof(p_request->'payload') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  IF p_label IS DISTINCT FROM p_request->>'label' THEN
    RAISE EXCEPTION 'v13: workspace open: label_mismatch';
  END IF;
  IF p_label = 'explore' THEN
    RAISE EXCEPTION 'v13: workspace open: explore_not_a_tool_label';
  END IF;
  IF p_label NOT IN ('read_only', 'workspace_edit') THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  v_tool := p_request->>'tool';
  IF v_tool IN ('read_pi', 'read_file_swift', 'read_file_py', 'read_duck',
                'spawn_subsession') THEN
    RAISE EXCEPTION 'v13: workspace open: not_this_opener';
  END IF;
  IF v_tool NOT IN ('bash', 'edit', 'find', 'grep', 'ls', 'write') THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM jsonb_array_elements_text(v_pol->'labels'->p_label->'admits') AS admitted
     WHERE admitted = v_tool) THEN
    RAISE EXCEPTION 'v13: workspace open: subset';
  END IF;
  v_attempt := p_request->>'attempt_key';
  IF NOT public.v13_canonical_uuid(v_attempt) THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM jsonb_array_elements(p_request->'paths') AS elem
     WHERE jsonb_typeof(elem) IS DISTINCT FROM 'string') THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  SELECT coalesce(array_agg(elem ORDER BY ord), '{}')
    INTO v_paths
    FROM jsonb_array_elements_text(p_request->'paths') WITH ORDINALITY AS t(elem, ord);
  v_cap := (v_pol->>'paths_cap')::int;
  IF cardinality(v_paths) < 1
     OR cardinality(v_paths) > v_cap
     OR v_paths IS DISTINCT FROM (
          SELECT array_agg(x ORDER BY x COLLATE "C") FROM unnest(v_paths) AS x)
     OR cardinality(v_paths) IS DISTINCT FROM
        (SELECT count(DISTINCT x) FROM unnest(v_paths) AS x) THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  v_seen := '{}';
  FOREACH v_path IN ARRAY v_paths LOOP
    IF v_path IS NULL
       OR v_path = ''
       OR left(v_path, 1) = '/'
       OR right(v_path, 1) = '/'
       OR position('\' IN v_path) > 0
       OR v_path = '.' THEN
      RAISE EXCEPTION 'v13: workspace open: canonical';
    END IF;
    v_acc := '';
    FOREACH v_seg IN ARRAY string_to_array(v_path, '/') LOOP
      IF v_seg IS NULL OR v_seg = '' OR v_seg = '.' OR v_seg = '..' THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
      v_lower := public.v13_workspace_casefold(v_seg);
      IF v_seg LIKE '.v13tmp-%' THEN
        RAISE EXCEPTION 'v13: workspace open: temp_namespace';
      END IF;
      IF v_lower LIKE '.v13tmp-%' AND v_seg NOT LIKE '.v13tmp-%' THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
      IF v_lower = ANY (v_seen) AND NOT (v_seg = ANY (v_seen)) THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
      IF EXISTS (
        SELECT 1
          FROM unnest(v_seen) AS prior
         WHERE prior IS DISTINCT FROM v_seg
           AND public.v13_workspace_casefold(prior) = v_lower) THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
      v_seen := v_seen || v_seg;
      IF v_acc <> '' AND NOT (v_acc = ANY (v_paths)) THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
      IF v_acc = '' THEN
        v_acc := v_seg;
      ELSE
        v_acc := v_acc || '/' || v_seg;
      END IF;
    END LOOP;
  END LOOP;
  v_payload := p_request->'payload';
  v_keys := public.v13_json_keys(v_payload);
  IF v_tool = 'write' THEN
    IF v_keys IS DISTINCT FROM ARRAY['content', 'expected_sha256', 'path']
       OR jsonb_typeof(v_payload->'path') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_payload->'content') IS DISTINCT FROM 'string'
       OR NOT (v_payload->>'path' = ANY (v_paths)) THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF jsonb_typeof(v_payload->'expected_sha256') = 'null' THEN
      NULL;
    ELSIF jsonb_typeof(v_payload->'expected_sha256') IS DISTINCT FROM 'string'
          OR v_payload->>'expected_sha256' !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
  ELSIF v_tool = 'edit' THEN
    IF v_keys IS DISTINCT FROM ARRAY['expected_sha256', 'new', 'old', 'path']
       OR jsonb_typeof(v_payload->'path') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_payload->'old') IS DISTINCT FROM 'string'
       OR v_payload->>'old' = ''
       OR NOT (v_payload->>'path' = ANY (v_paths)) THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF jsonb_typeof(v_payload->'new') = 'null' THEN
      RAISE EXCEPTION 'v13: workspace open: canonical';
    END IF;
    IF jsonb_typeof(v_payload->'new') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_payload->'expected_sha256') IS DISTINCT FROM 'string'
       OR v_payload->>'expected_sha256' !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
  ELSIF v_tool = 'bash' THEN
    IF NOT (v_keys = ARRAY['argv']
            OR v_keys = ARRAY['argv', 'expected_sha256'])
       OR jsonb_typeof(v_payload->'argv') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF EXISTS (
      SELECT 1
        FROM jsonb_array_elements(v_payload->'argv') AS elem
       WHERE jsonb_typeof(elem) IS DISTINCT FROM 'string') THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    SELECT coalesce(array_agg(elem ORDER BY ord), '{}')
      INTO v_argv
      FROM jsonb_array_elements_text(v_payload->'argv') WITH ORDINALITY AS t(elem, ord);
    v_cap := (v_pol->>'argv_len_cap')::int;
    IF cardinality(v_argv) < 1 OR cardinality(v_argv) > v_cap THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    v_verb := v_argv[1];
    IF NOT EXISTS (
      SELECT 1
        FROM jsonb_array_elements_text(v_pol->'bash_verbs') AS verb
       WHERE verb = v_verb) THEN
      RAISE EXCEPTION 'v13: workspace open: verb_closed';
    END IF;
    v_j := 0;
    FOREACH v_arg IN ARRAY v_argv LOOP
      v_j := v_j + 1;
      IF v_arg IS NULL OR v_arg = '' THEN
        RAISE EXCEPTION 'v13: workspace open: payload';
      END IF;
      IF v_arg LIKE '.v13tmp-%' THEN
        RAISE EXCEPTION 'v13: workspace open: temp_namespace';
      END IF;
      IF lower(v_arg) LIKE '.v13tmp-%' AND v_arg NOT LIKE '.v13tmp-%' THEN
        RAISE EXCEPTION 'v13: workspace open: canonical';
      END IF;
      IF v_j > 1 AND NOT (v_arg = ANY (v_paths)) THEN
        RAISE EXCEPTION 'v13: workspace open: payload';
      END IF;
    END LOOP;
    IF v_verb IN ('rm', 'cp', 'mv') THEN
      IF NOT (v_payload ? 'expected_sha256')
         OR jsonb_typeof(v_payload->'expected_sha256') IS DISTINCT FROM 'string'
         OR v_payload->>'expected_sha256' !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'v13: workspace open: payload';
      END IF;
    ELSIF v_payload ? 'expected_sha256' THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF v_verb = 'rm' AND cardinality(v_argv) IS DISTINCT FROM 2 THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF v_verb = 'mkdir' AND cardinality(v_argv) IS DISTINCT FROM 2 THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF v_verb IN ('cp', 'mv') AND cardinality(v_argv) IS DISTINCT FROM 3 THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
  ELSIF v_tool = 'grep' THEN
    IF v_keys IS DISTINCT FROM ARRAY['path', 'pattern']
       OR jsonb_typeof(v_payload->'path') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_payload->'pattern') IS DISTINCT FROM 'string'
       OR v_payload->>'pattern' = ''
       OR NOT (v_payload->>'path' = ANY (v_paths)) THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
  ELSIF v_tool = 'find' THEN
    IF NOT (v_keys = ARRAY['path'] OR v_keys = ARRAY['name_fixed', 'path'])
       OR jsonb_typeof(v_payload->'path') IS DISTINCT FROM 'string'
       OR NOT (v_payload->>'path' = ANY (v_paths)) THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
    IF v_payload ? 'name_fixed'
       AND (jsonb_typeof(v_payload->'name_fixed') IS DISTINCT FROM 'string'
            OR v_payload->>'name_fixed' = ''
            OR position('/' IN v_payload->>'name_fixed') > 0
            OR position('*' IN v_payload->>'name_fixed') > 0
            OR position('?' IN v_payload->>'name_fixed') > 0) THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
  ELSE
    IF v_keys IS DISTINCT FROM ARRAY['path']
       OR jsonb_typeof(v_payload->'path') IS DISTINCT FROM 'string'
       OR NOT (v_payload->>'path' = ANY (v_paths)) THEN
      RAISE EXCEPTION 'v13: workspace open: payload';
    END IF;
  END IF;
  v_canonical := p_request || jsonb_build_object('workspace_root', p_workspace_root);
  v_id := public.v13_effect_id(p_session, 'tool', v_canonical);
  SELECT * INTO v_row FROM public.effects WHERE effect_id = v_id;
  IF v_row.effect_id IS NOT NULL THEN
    IF v_row.tool_name IS NOT DISTINCT FROM v_tool
       AND v_row.request IS NOT DISTINCT FROM v_canonical
       AND v_row.status = 'succeeded' THEN
      RETURN jsonb_build_object(
        'effect_id', v_row.effect_id,
        'attempt_no', v_row.attempt_no,
        'fence', v_row.fence,
        'replayed', true,
        'tool', v_row.tool_name,
        'status', v_row.status,
        'result', v_row.result);
    END IF;
    IF v_row.tool_name IS NOT DISTINCT FROM v_tool
       AND v_row.request IS NOT DISTINCT FROM v_canonical
       AND v_row.status = 'claimed' THEN
      RETURN jsonb_build_object(
        'effect_id', v_row.effect_id,
        'attempt_no', v_row.attempt_no,
        'fence', v_row.fence,
        'replayed', true,
        'tool', v_row.tool_name,
        'status', v_row.status,
        'result', 'null'::jsonb);
    END IF;
    RAISE EXCEPTION 'v13: workspace open: effect_exists';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM public.effects e
     WHERE e.request->>'attempt_key' = v_attempt) THEN
    RAISE EXCEPTION 'v13: workspace open: effect_exists';
  END IF;
  FOR v_busy IN
    SELECT *
      FROM public.effects
     WHERE kind = 'tool'
       AND status IN ('ready', 'claimed', 'unknown')
       AND request ? 'workspace_root'
     ORDER BY effect_id
       FOR UPDATE
  LOOP
    FOREACH v_our IN ARRAY v_paths LOOP
      FOR v_their IN
        SELECT elem
          FROM jsonb_array_elements_text(v_busy.request->'paths') AS elem
      LOOP
        v_oa := string_to_array(
          rtrim(p_workspace_root, '/') || '/' || v_our, '/');
        v_ob := string_to_array(
          rtrim(v_busy.request->>'workspace_root', '/') || '/' || v_their, '/');
        v_na := cardinality(v_oa);
        v_nb := cardinality(v_ob);
        v_match := true;
        FOR v_i IN 1..least(v_na, v_nb) LOOP
          IF v_oa[v_i] IS DISTINCT FROM v_ob[v_i] THEN
            v_match := false;
            EXIT;
          END IF;
        END LOOP;
        IF v_match THEN
          RAISE EXCEPTION 'v13: workspace open: path_busy';
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
  v_id := public.v13_enqueue_effect(p_session, 'tool', v_canonical, v_tool);
  UPDATE public.effects
     SET status = 'claimed',
         lease_owner = 'v13_workspace_opener',
         lease_until = 'infinity'
   WHERE effect_id = v_id
     AND status = 'ready';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: workspace open: canonical';
  END IF;
  SELECT * INTO v_row FROM public.effects WHERE effect_id = v_id;
  RETURN jsonb_build_object(
    'effect_id', v_row.effect_id,
    'attempt_no', v_row.attempt_no,
    'fence', v_row.fence,
    'replayed', false,
    'tool', v_row.tool_name,
    'status', v_row.status,
    'result', 'null'::jsonb);
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_tool_result_accept(
  p_effect_id uuid,
  p_attempt_no integer,
  p_fence bigint,
  p_status text,
  p_result jsonb
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_sid uuid;
  v_row effects;
  v_cap int;
  v_len int;
  v_byte numeric;
  v_token text;
  v_word text;
BEGIN
  SELECT session_id INTO v_sid FROM public.effects WHERE effect_id = p_effect_id;
  IF v_sid IS NULL THEN
    RAISE EXCEPTION 'v13: workspace result: lock_mismatch';
  END IF;
  PERFORM 1 FROM public.sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM public.effects WHERE effect_id = p_effect_id FOR UPDATE;
  IF NOT FOUND
     OR v_row.kind IS DISTINCT FROM 'tool'
     OR v_row.tool_name NOT IN ('bash', 'edit', 'find', 'grep', 'ls', 'write')
     OR v_row.status IS DISTINCT FROM 'claimed'
     OR v_row.lease_owner IS DISTINCT FROM 'v13_workspace_opener'
     OR v_row.attempt_no IS DISTINCT FROM p_attempt_no
     OR v_row.fence IS DISTINCT FROM p_fence THEN
    RAISE EXCEPTION 'v13: workspace result: lock_mismatch';
  END IF;
  IF public.v13_unconsumed_cancel(v_sid) THEN
    RAISE EXCEPTION 'v13: workspace result: cancel';
  END IF;
  IF p_status IS NULL
     OR p_status NOT IN ('succeeded', 'failed')
     OR p_result IS NULL
     OR jsonb_typeof(p_result) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(p_result) IS DISTINCT FROM
        ARRAY['byte_length', 'depth_limited', 'error_token', 'ok',
              'schema_version', 'text', 'tool', 'truncated']
     OR NOT public.v13_json_int_ok(p_result->'schema_version', 1)
     OR (p_result->>'schema_version') IS DISTINCT FROM '1'
     OR jsonb_typeof(p_result->'ok') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(p_result->'tool') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_result->'truncated') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(p_result->'depth_limited') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(p_result->'text') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_result->'byte_length') IS DISTINCT FROM 'number'
     OR p_result->>'byte_length' !~ '^[0-9]+$'
     OR (p_result->>'tool') IS DISTINCT FROM v_row.tool_name THEN
    RAISE EXCEPTION 'v13: workspace result: canonical';
  END IF;
  v_cap := (public.v13_workspace_policy()->>'result_text_cap_bytes')::int;
  v_len := octet_length(p_result->>'text');
  v_byte := (p_result->>'byte_length')::numeric;
  IF v_len > v_cap THEN
    RAISE EXCEPTION 'v13: workspace result: over_cap';
  END IF;
  IF (p_result->>'truncated')::boolean IS DISTINCT FROM (v_byte > v_cap::numeric)
     OR (NOT (p_result->>'truncated')::boolean AND v_byte IS DISTINCT FROM v_len::numeric)
     OR ((p_result->>'truncated')::boolean AND v_byte <= v_cap::numeric) THEN
    RAISE EXCEPTION 'v13: workspace result: flag_inconsistent';
  END IF;
  IF v_row.tool_name IS DISTINCT FROM 'find'
     AND (p_result->>'depth_limited')::boolean THEN
    RAISE EXCEPTION 'v13: workspace result: canonical';
  END IF;
  IF (p_result->>'depth_limited')::boolean
     AND (p_result->>'truncated')::boolean
     AND v_byte <= v_cap::numeric THEN
    RAISE EXCEPTION 'v13: workspace result: flag_inconsistent';
  END IF;
  v_token := CASE
    WHEN jsonb_typeof(p_result->'error_token') = 'null' THEN NULL
    WHEN jsonb_typeof(p_result->'error_token') = 'string' THEN p_result->>'error_token'
    ELSE ''
  END;
  IF v_token = 'ambiguous' THEN
    RAISE EXCEPTION 'v13: workspace result: ambiguous';
  END IF;
  IF p_status = 'succeeded' THEN
    IF (p_result->>'ok')::boolean IS DISTINCT FROM true
       OR v_token IS NOT NULL THEN
      RAISE EXCEPTION 'v13: workspace result: canonical';
    END IF;
  ELSIF (p_result->>'ok')::boolean IS DISTINCT FROM false
        OR v_token IS NULL
        OR v_token NOT IN (
          'hash_mismatch', 'exists', 'missing', 'escape', 'not_a_file',
          'not_a_dir', 'edit_not_unique', 'bad_utf8', 'io_error') THEN
    RAISE EXCEPTION 'v13: workspace result: canonical';
  END IF;
  v_word := public.v13_complete(
    p_effect_id, p_attempt_no, p_fence, p_status, p_result);
  IF v_word IS DISTINCT FROM 'accepted' THEN
    RAISE EXCEPTION 'v13: workspace result: lock_mismatch';
  END IF;
  RETURN v_word;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_workspace_casefold(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $fn$
  SELECT lower(
    replace(replace(replace(replace(replace(replace(replace(replace(
      p_text,
      U&'\00DF', 'ss'),
      U&'\1E9E', 'ss'),
      U&'\0130', U&'i\0307'),
      U&'\FB00', 'ff'),
      U&'\FB01', 'fi'),
      U&'\FB02', 'fl'),
      U&'\FB03', 'ffi'),
      U&'\FB04', 'ffl'));
$fn$;

REVOKE ALL ON FUNCTION public.v13_workspace_policy() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_workspace_casefold(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_tool_effect_open(uuid, uuid, text, text, text[], jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_tool_result_accept(uuid, integer, bigint, text, jsonb) FROM PUBLIC;
