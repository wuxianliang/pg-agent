CREATE FUNCTION v15.v15_jsonb_posint(p jsonb) RETURNS integer
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  num numeric;
BEGIN
  IF p IS NULL OR pg_catalog.jsonb_typeof(p) IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  BEGIN
    num := (p #>> '{}')::numeric;
  EXCEPTION
    WHEN invalid_text_representation OR numeric_value_out_of_range THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END;
  IF num <> trunc(num) OR num < 1 OR num > 2147483647 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  RETURN num::integer;
END;
$fn$;

CREATE FUNCTION v15.v15_check_component(p_name text, p_value jsonb) RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  key text;
  val jsonb;
  ratio numeric;
  allowed text[];
BEGIN
  IF p_value IS NULL OR pg_catalog.jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_name = 'llm' THEN
    allowed := ARRAY['model', 'temperature', 'max_output_tokens'];
  ELSIF p_name = 'repl' THEN
    allowed := ARRAY['timeout_ms'];
  ELSIF p_name = 'protocol' THEN
    allowed := ARRAY[
      'max_invoke_input_length', 'truncation_prefix_ratio', 'max_repl_output_length'
    ];
  ELSE
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  FOR key IN SELECT pg_catalog.jsonb_object_keys(p_value) LOOP
    IF NOT (key = ANY (allowed)) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END LOOP;
  IF p_name = 'llm' THEN
    IF pg_catalog.jsonb_exists(p_value, 'model') THEN
      val := p_value -> 'model';
      IF pg_catalog.jsonb_typeof(val) IS DISTINCT FROM 'string'
         OR pg_catalog.length(val #>> '{}') < 1 THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END IF;
    IF pg_catalog.jsonb_exists(p_value, 'temperature') THEN
      IF pg_catalog.jsonb_typeof(p_value -> 'temperature') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END IF;
    IF pg_catalog.jsonb_exists(p_value, 'max_output_tokens') THEN
      PERFORM v15.v15_jsonb_posint(p_value -> 'max_output_tokens');
    END IF;
  ELSIF p_name = 'repl' THEN
    IF pg_catalog.jsonb_exists(p_value, 'timeout_ms') THEN
      PERFORM v15.v15_jsonb_posint(p_value -> 'timeout_ms');
    END IF;
  ELSE
    IF pg_catalog.jsonb_exists(p_value, 'max_invoke_input_length') THEN
      PERFORM v15.v15_jsonb_posint(p_value -> 'max_invoke_input_length');
    END IF;
    IF pg_catalog.jsonb_exists(p_value, 'max_repl_output_length') THEN
      PERFORM v15.v15_jsonb_posint(p_value -> 'max_repl_output_length');
    END IF;
    IF pg_catalog.jsonb_exists(p_value, 'truncation_prefix_ratio') THEN
      val := p_value -> 'truncation_prefix_ratio';
      IF pg_catalog.jsonb_typeof(val) IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      ratio := (val #>> '{}')::numeric;
      IF ratio <= 0 OR ratio >= 1 THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END IF;
  END IF;
  RETURN p_value;
END;
$fn$;

CREATE FUNCTION v15.v15_apply_partial(
  p_llm jsonb,
  p_repl jsonb,
  p_protocol jsonb,
  p_partial jsonb,
  OUT llm jsonb,
  OUT repl jsonb,
  OUT protocol jsonb
)
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  key text;
BEGIN
  llm := p_llm;
  repl := p_repl;
  protocol := p_protocol;
  IF p_partial IS NULL OR pg_catalog.jsonb_typeof(p_partial) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF pg_catalog.jsonb_exists(p_partial, 'depth_map') THEN
    RAISE EXCEPTION 'V15_DEPTH_SELF' USING ERRCODE = 'P1530';
  END IF;
  IF pg_catalog.jsonb_exists(p_partial, 'baseline_hooks') THEN
    RAISE EXCEPTION 'V15_BASELINE_IMMUTABLE' USING ERRCODE = 'P1532';
  END IF;
  FOR key IN SELECT pg_catalog.jsonb_object_keys(p_partial) LOOP
    IF key NOT IN ('llm', 'repl', 'protocol') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END LOOP;
  IF pg_catalog.jsonb_exists(p_partial, 'llm') THEN
    llm := v15.v15_check_component('llm', p_partial -> 'llm');
  END IF;
  IF pg_catalog.jsonb_exists(p_partial, 'repl') THEN
    repl := v15.v15_check_component('repl', p_partial -> 'repl');
  END IF;
  IF pg_catalog.jsonb_exists(p_partial, 'protocol') THEN
    protocol := v15.v15_check_component('protocol', p_partial -> 'protocol');
  END IF;
  RETURN;
END;
$fn$;

CREATE FUNCTION v15.v15_require_folded(
  p_llm jsonb,
  p_repl jsonb,
  p_protocol jsonb
) RETURNS void
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_llm IS NULL OR NOT pg_catalog.jsonb_exists(p_llm, 'model') THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_protocol IS NULL
     OR NOT pg_catalog.jsonb_exists(p_protocol, 'max_invoke_input_length')
     OR NOT pg_catalog.jsonb_exists(p_protocol, 'truncation_prefix_ratio')
     OR NOT pg_catalog.jsonb_exists(p_protocol, 'max_repl_output_length') THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_repl IS NULL OR pg_catalog.jsonb_typeof(p_repl) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_check_baseline_hooks(p_hooks jsonb) RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  elem jsonb;
  key text;
  n int;
  i int;
BEGIN
  IF p_hooks IS NULL OR pg_catalog.jsonb_typeof(p_hooks) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  n := pg_catalog.jsonb_array_length(p_hooks);
  FOR i IN 0 .. n - 1 LOOP
    elem := p_hooks -> i;
    IF pg_catalog.jsonb_typeof(elem) IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    key := elem #>> '{}';
    IF key IS NULL OR pg_catalog.length(key) < 1 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM v15.hook_defs hd WHERE hd.hook_key = key
    ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF EXISTS (
      SELECT 1 FROM v15.hook_defs hd
      WHERE hd.hook_key = key AND hd.baseline_required
    ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END LOOP;
  IF (
    SELECT count(*) FROM pg_catalog.jsonb_array_elements_text(p_hooks)
  ) <> (
    SELECT count(DISTINCT x) FROM pg_catalog.jsonb_array_elements_text(p_hooks) AS t(x)
  ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_check_extra_hooks(p_hooks jsonb) RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  elem jsonb;
  key text;
  hk text;
  n int;
  i int;
BEGIN
  IF p_hooks IS NULL OR pg_catalog.jsonb_typeof(p_hooks) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  n := pg_catalog.jsonb_array_length(p_hooks);
  FOR i IN 0 .. n - 1 LOOP
    elem := p_hooks -> i;
    IF pg_catalog.jsonb_typeof(elem) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_exists(elem, 'baseline_hooks') THEN
      RAISE EXCEPTION 'V15_BASELINE_IMMUTABLE' USING ERRCODE = 'P1532';
    END IF;
    IF pg_catalog.jsonb_exists(elem, 'depth_map') THEN
      RAISE EXCEPTION 'V15_DEPTH_SELF' USING ERRCODE = 'P1530';
    END IF;
    FOR key IN SELECT pg_catalog.jsonb_object_keys(elem) LOOP
      IF key NOT IN ('hook_key', 'config') THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    IF NOT pg_catalog.jsonb_exists(elem, 'hook_key')
       OR NOT pg_catalog.jsonb_exists(elem, 'config') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_typeof(elem -> 'hook_key') IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    hk := elem ->> 'hook_key';
    IF hk IS NULL OR pg_catalog.length(hk) < 1 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_typeof(elem -> 'config') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_exists(elem -> 'config', 'baseline_hooks') THEN
      RAISE EXCEPTION 'V15_BASELINE_IMMUTABLE' USING ERRCODE = 'P1532';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM v15.hook_defs hd WHERE hd.hook_key = hk
    ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_check_depth_map(p_map jsonb) RETURNS void
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  key text;
BEGIN
  IF p_map IS NULL OR pg_catalog.jsonb_typeof(p_map) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF pg_catalog.jsonb_exists(p_map, 'depth_map') THEN
    RAISE EXCEPTION 'V15_DEPTH_SELF' USING ERRCODE = 'P1530';
  END IF;
  IF pg_catalog.jsonb_exists(p_map, 'baseline_hooks') THEN
    RAISE EXCEPTION 'V15_BASELINE_IMMUTABLE' USING ERRCODE = 'P1532';
  END IF;
  FOR key IN SELECT pg_catalog.jsonb_object_keys(p_map) LOOP
    IF key !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    PERFORM v15.v15_apply_partial(
      '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, p_map -> key
    );
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_profile_digest(
  p_llm jsonb,
  p_repl jsonb,
  p_protocol jsonb,
  p_baseline_hooks jsonb
) RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT pg_catalog.md5(pg_catalog.jsonb_build_object(
    'baseline_hooks', p_baseline_hooks,
    'llm', p_llm,
    'protocol', p_protocol,
    'repl', p_repl
  )::text)
$fn$;

CREATE FUNCTION v15.v15_layer_digest(
  p_llm jsonb,
  p_repl jsonb,
  p_protocol jsonb,
  p_depth_map jsonb,
  p_extra_hooks jsonb
) RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT pg_catalog.md5((
    CASE
      WHEN p_llm IS NULL THEN '{}'::jsonb
      ELSE pg_catalog.jsonb_build_object('llm', p_llm)
    END
    || CASE
      WHEN p_repl IS NULL THEN '{}'::jsonb
      ELSE pg_catalog.jsonb_build_object('repl', p_repl)
    END
    || CASE
      WHEN p_protocol IS NULL THEN '{}'::jsonb
      ELSE pg_catalog.jsonb_build_object('protocol', p_protocol)
    END
    || CASE
      WHEN p_depth_map IS NULL THEN '{}'::jsonb
      ELSE pg_catalog.jsonb_build_object('depth_map', p_depth_map)
    END
    || CASE
      WHEN p_extra_hooks IS NULL THEN '{}'::jsonb
      ELSE pg_catalog.jsonb_build_object('extra_hooks', p_extra_hooks)
    END
  )::text)
$fn$;

CREATE FUNCTION v15.v15_scope_digest(p_profile_id uuid) RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT pg_catalog.md5(p_profile_id::text)
$fn$;

CREATE FUNCTION v15.v15_register_profile(
  p_profile_id uuid,
  p_llm jsonb,
  p_repl jsonb,
  p_protocol jsonb,
  p_baseline_hooks jsonb
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  digest text;
BEGIN
  IF p_profile_id IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_check_component('llm', p_llm);
  PERFORM v15.v15_check_component('repl', p_repl);
  PERFORM v15.v15_check_component('protocol', p_protocol);
  PERFORM v15.v15_check_baseline_hooks(p_baseline_hooks);
  digest := v15.v15_profile_digest(p_llm, p_repl, p_protocol, p_baseline_hooks);
  INSERT INTO v15.config_profiles (
    profile_id, llm, repl, protocol, baseline_hooks, profile_digest, created_at
  ) VALUES (
    p_profile_id, p_llm, p_repl, p_protocol, p_baseline_hooks, digest,
    pg_catalog.clock_timestamp()
  );
  RETURN digest;
END;
$fn$;

CREATE FUNCTION v15.v15_update_profile(
  p_profile_id uuid,
  p_llm jsonb,
  p_repl jsonb,
  p_protocol jsonb,
  p_baseline_hooks jsonb
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  digest text;
  n int;
BEGIN
  IF p_profile_id IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_check_component('llm', p_llm);
  PERFORM v15.v15_check_component('repl', p_repl);
  PERFORM v15.v15_check_component('protocol', p_protocol);
  PERFORM v15.v15_check_baseline_hooks(p_baseline_hooks);
  digest := v15.v15_profile_digest(p_llm, p_repl, p_protocol, p_baseline_hooks);
  UPDATE v15.config_profiles
  SET llm = p_llm,
      repl = p_repl,
      protocol = p_protocol,
      baseline_hooks = p_baseline_hooks,
      profile_digest = digest
  WHERE profile_id = p_profile_id;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  RETURN digest;
END;
$fn$;

CREATE FUNCTION v15.v15_register_scope(
  p_scope_id uuid,
  p_profile_id uuid
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  digest text;
BEGIN
  IF p_scope_id IS NULL OR p_profile_id IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM v15.config_profiles WHERE profile_id = p_profile_id
  ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  digest := v15.v15_scope_digest(p_profile_id);
  INSERT INTO v15.config_scopes (scope_id, profile_id, scope_digest)
  VALUES (p_scope_id, p_profile_id, digest);
  RETURN digest;
END;
$fn$;

CREATE FUNCTION v15.v15_add_layer(
  p_layer_id uuid,
  p_scope_id uuid,
  p_ordinal integer,
  p_kind text,
  p_llm jsonb DEFAULT NULL,
  p_repl jsonb DEFAULT NULL,
  p_protocol jsonb DEFAULT NULL,
  p_depth_map jsonb DEFAULT NULL,
  p_extra_hooks jsonb DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  digest text;
BEGIN
  IF p_layer_id IS NULL OR p_ordinal IS NULL OR p_ordinal < 0 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_kind IS DISTINCT FROM 'plain' AND p_kind IS DISTINCT FROM 'depth' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_scope_id IS NULL AND p_kind IS DISTINCT FROM 'plain' THEN
    RAISE EXCEPTION 'V15_CONFIG_LOCAL' USING ERRCODE = 'P1531';
  END IF;
  IF p_scope_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM v15.config_scopes WHERE scope_id = p_scope_id
  ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_kind = 'depth' THEN
    IF p_llm IS NOT NULL OR p_repl IS NOT NULL OR p_protocol IS NOT NULL
       OR p_extra_hooks IS NOT NULL THEN
      RAISE EXCEPTION 'V15_DEPTH_SELF' USING ERRCODE = 'P1530';
    END IF;
    IF p_depth_map IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    PERFORM v15.v15_check_depth_map(p_depth_map);
  ELSE
    IF p_depth_map IS NOT NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF p_llm IS NOT NULL THEN
      PERFORM v15.v15_check_component('llm', p_llm);
    END IF;
    IF p_repl IS NOT NULL THEN
      PERFORM v15.v15_check_component('repl', p_repl);
    END IF;
    IF p_protocol IS NOT NULL THEN
      PERFORM v15.v15_check_component('protocol', p_protocol);
    END IF;
    IF p_extra_hooks IS NOT NULL THEN
      PERFORM v15.v15_check_extra_hooks(p_extra_hooks);
    END IF;
  END IF;
  digest := v15.v15_layer_digest(
    p_llm, p_repl, p_protocol, p_depth_map, p_extra_hooks
  );
  INSERT INTO v15.config_layers (
    layer_id, scope_id, ordinal, kind, llm, repl, protocol, depth_map,
    extra_hooks, layer_digest
  ) VALUES (
    p_layer_id, p_scope_id, p_ordinal, p_kind, p_llm, p_repl, p_protocol,
    p_depth_map, p_extra_hooks, digest
  );
  RETURN digest;
END;
$fn$;

CREATE FUNCTION v15.v15_resolve_config(
  p_scope_id uuid,
  p_local_layer_id uuid,
  p_depth integer,
  OUT resolved_config jsonb,
  OUT config_digest text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  prof v15.config_profiles%ROWTYPE;
  layer v15.config_layers%ROWTYPE;
  scope_profile uuid;
  acc_llm jsonb;
  acc_repl jsonb;
  acc_protocol jsonb;
  depth_key text;
  partial jsonb;
BEGIN
  IF p_scope_id IS NULL OR p_depth IS NULL OR p_depth < 1 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT s.profile_id INTO scope_profile
  FROM v15.config_scopes s
  WHERE s.scope_id = p_scope_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT * INTO prof
  FROM v15.config_profiles
  WHERE profile_id = scope_profile;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  acc_llm := v15.v15_check_component('llm', prof.llm);
  acc_repl := v15.v15_check_component('repl', prof.repl);
  acc_protocol := v15.v15_check_component('protocol', prof.protocol);
  depth_key := p_depth::text;
  FOR layer IN
    SELECT *
    FROM v15.config_layers
    WHERE scope_id = p_scope_id AND kind = 'depth'
    ORDER BY ordinal
  LOOP
    IF layer.extra_hooks IS NOT NULL
       OR layer.llm IS NOT NULL
       OR layer.repl IS NOT NULL
       OR layer.protocol IS NOT NULL THEN
      RAISE EXCEPTION 'V15_DEPTH_SELF' USING ERRCODE = 'P1530';
    END IF;
    IF layer.depth_map IS NULL
       OR pg_catalog.jsonb_typeof(layer.depth_map) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_exists(layer.depth_map, depth_key) THEN
      partial := layer.depth_map -> depth_key;
      SELECT a.llm, a.repl, a.protocol
      INTO acc_llm, acc_repl, acc_protocol
      FROM v15.v15_apply_partial(acc_llm, acc_repl, acc_protocol, partial) AS a;
    END IF;
  END LOOP;
  FOR layer IN
    SELECT *
    FROM v15.config_layers
    WHERE scope_id = p_scope_id AND kind = 'plain'
    ORDER BY ordinal
  LOOP
    IF layer.llm IS NOT NULL THEN
      acc_llm := v15.v15_check_component('llm', layer.llm);
    END IF;
    IF layer.repl IS NOT NULL THEN
      acc_repl := v15.v15_check_component('repl', layer.repl);
    END IF;
    IF layer.protocol IS NOT NULL THEN
      acc_protocol := v15.v15_check_component('protocol', layer.protocol);
    END IF;
  END LOOP;
  IF p_local_layer_id IS NOT NULL THEN
    SELECT * INTO layer
    FROM v15.config_layers
    WHERE layer_id = p_local_layer_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF layer.scope_id IS NOT NULL OR layer.kind IS DISTINCT FROM 'plain' THEN
      RAISE EXCEPTION 'V15_CONFIG_LOCAL' USING ERRCODE = 'P1531';
    END IF;
    IF layer.llm IS NOT NULL THEN
      acc_llm := v15.v15_check_component('llm', layer.llm);
    END IF;
    IF layer.repl IS NOT NULL THEN
      acc_repl := v15.v15_check_component('repl', layer.repl);
    END IF;
    IF layer.protocol IS NOT NULL THEN
      acc_protocol := v15.v15_check_component('protocol', layer.protocol);
    END IF;
  END IF;
  PERFORM v15.v15_require_folded(acc_llm, acc_repl, acc_protocol);
  resolved_config := pg_catalog.jsonb_build_object(
    'llm', acc_llm,
    'repl', acc_repl,
    'protocol', acc_protocol,
    'depth', p_depth
  );
  config_digest := pg_catalog.md5(resolved_config::text);
  RETURN;
END;
$fn$;

CREATE FUNCTION v15.v15_resolve_child_config(
  p_scope_id uuid,
  p_local_layer_id uuid,
  p_depth integer,
  OUT resolved_config jsonb,
  OUT config_digest text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_local_layer_id IS NOT NULL THEN
    RAISE EXCEPTION 'V15_CONFIG_LOCAL' USING ERRCODE = 'P1531';
  END IF;
  SELECT r.resolved_config, r.config_digest
  INTO resolved_config, config_digest
  FROM v15.v15_resolve_config(p_scope_id, NULL, p_depth) AS r;
  RETURN;
END;
$fn$;

CREATE FUNCTION v15.v15_effective_ceilings(
  p_ceilings jsonb,
  p_parent_ceilings jsonb,
  OUT ceilings jsonb,
  OUT manifest_digest text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  m_iter integer;
  m_depth integer;
  m_io integer;
  m_stmt integer;
  n_iter integer;
  n_depth integer;
  n_io integer;
  n_stmt integer;
  key text;
BEGIN
  PERFORM v15.v15_assert_manifest();
  SELECT g.max_iterations, g.max_depth, g.max_io_attempts, g.max_statement_ms
  INTO m_iter, m_depth, m_io, m_stmt
  FROM v15.governance_manifest g
  WHERE g.manifest_id = 1;
  IF p_parent_ceilings IS NULL THEN
    n_iter := m_iter;
    n_depth := m_depth;
    n_io := m_io;
    n_stmt := m_stmt;
    IF p_ceilings IS NOT NULL THEN
      IF pg_catalog.jsonb_typeof(p_ceilings) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      FOR key IN SELECT pg_catalog.jsonb_object_keys(p_ceilings) LOOP
        IF key NOT IN (
          'max_iterations', 'max_depth', 'max_io_attempts', 'max_statement_ms'
        ) THEN
          RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
        END IF;
      END LOOP;
      IF pg_catalog.jsonb_exists(p_ceilings, 'max_iterations') THEN
        n_iter := v15.v15_jsonb_posint(p_ceilings -> 'max_iterations');
        IF n_iter > m_iter THEN
          RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
        END IF;
      END IF;
      IF pg_catalog.jsonb_exists(p_ceilings, 'max_depth') THEN
        n_depth := v15.v15_jsonb_posint(p_ceilings -> 'max_depth');
        IF n_depth > m_depth THEN
          RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
        END IF;
      END IF;
      IF pg_catalog.jsonb_exists(p_ceilings, 'max_io_attempts') THEN
        n_io := v15.v15_jsonb_posint(p_ceilings -> 'max_io_attempts');
        IF n_io > m_io THEN
          RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
        END IF;
      END IF;
      IF pg_catalog.jsonb_exists(p_ceilings, 'max_statement_ms') THEN
        n_stmt := v15.v15_jsonb_posint(p_ceilings -> 'max_statement_ms');
        IF n_stmt > m_stmt THEN
          RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
        END IF;
      END IF;
    END IF;
  ELSE
    IF p_ceilings IS NOT NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_typeof(p_parent_ceilings) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    FOR key IN SELECT pg_catalog.jsonb_object_keys(p_parent_ceilings) LOOP
      IF key NOT IN (
        'max_iterations', 'max_depth', 'max_io_attempts', 'max_statement_ms'
      ) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    IF NOT pg_catalog.jsonb_exists(p_parent_ceilings, 'max_iterations')
       OR NOT pg_catalog.jsonb_exists(p_parent_ceilings, 'max_depth')
       OR NOT pg_catalog.jsonb_exists(p_parent_ceilings, 'max_io_attempts')
       OR NOT pg_catalog.jsonb_exists(p_parent_ceilings, 'max_statement_ms') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    n_iter := least(
      v15.v15_jsonb_posint(p_parent_ceilings -> 'max_iterations'), m_iter
    );
    n_depth := least(
      v15.v15_jsonb_posint(p_parent_ceilings -> 'max_depth'), m_depth
    );
    n_io := least(
      v15.v15_jsonb_posint(p_parent_ceilings -> 'max_io_attempts'), m_io
    );
    n_stmt := least(
      v15.v15_jsonb_posint(p_parent_ceilings -> 'max_statement_ms'), m_stmt
    );
  END IF;
  manifest_digest := v15.v15_manifest_digest(n_iter, n_depth, n_io, n_stmt);
  ceilings := pg_catalog.jsonb_build_object(
    'max_depth', n_depth,
    'max_io_attempts', n_io,
    'max_iterations', n_iter,
    'max_statement_ms', n_stmt
  );
  RETURN;
END;
$fn$;

ALTER FUNCTION v15.v15_jsonb_posint(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_check_component(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_apply_partial(jsonb, jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_require_folded(jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_check_baseline_hooks(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_check_extra_hooks(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_check_depth_map(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_profile_digest(jsonb, jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_layer_digest(jsonb, jsonb, jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_scope_digest(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_register_profile(uuid, jsonb, jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_update_profile(uuid, jsonb, jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_register_scope(uuid, uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_add_layer(uuid, uuid, integer, text, jsonb, jsonb, jsonb, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_resolve_config(uuid, uuid, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_resolve_child_config(uuid, uuid, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_effective_ceilings(jsonb, jsonb) OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_jsonb_posint(jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_check_component(text, jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_apply_partial(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_require_folded(jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_check_baseline_hooks(jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_check_extra_hooks(jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_check_depth_map(jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_profile_digest(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_layer_digest(jsonb, jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_scope_digest(uuid) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_register_profile(uuid, jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl;
REVOKE ALL ON FUNCTION v15.v15_update_profile(uuid, jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl;
REVOKE ALL ON FUNCTION v15.v15_register_scope(uuid, uuid) FROM PUBLIC, v15_worker, v15_repl;
REVOKE ALL ON FUNCTION v15.v15_add_layer(uuid, uuid, integer, text, jsonb, jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl;
REVOKE ALL ON FUNCTION v15.v15_resolve_config(uuid, uuid, integer) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_resolve_child_config(uuid, uuid, integer) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.v15_effective_ceilings(jsonb, jsonb) FROM PUBLIC, v15_worker, v15_repl, v15_bootstrap;

GRANT EXECUTE ON FUNCTION v15.v15_jsonb_posint(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_check_component(text, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_apply_partial(jsonb, jsonb, jsonb, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_require_folded(jsonb, jsonb, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_check_baseline_hooks(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_check_extra_hooks(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_check_depth_map(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_profile_digest(jsonb, jsonb, jsonb, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_layer_digest(jsonb, jsonb, jsonb, jsonb, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_scope_digest(uuid) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_register_profile(uuid, jsonb, jsonb, jsonb, jsonb) TO v15_owner, v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.v15_update_profile(uuid, jsonb, jsonb, jsonb, jsonb) TO v15_owner, v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.v15_register_scope(uuid, uuid) TO v15_owner, v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.v15_add_layer(uuid, uuid, integer, text, jsonb, jsonb, jsonb, jsonb, jsonb) TO v15_owner, v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.v15_resolve_config(uuid, uuid, integer) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_resolve_child_config(uuid, uuid, integer) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_effective_ceilings(jsonb, jsonb) TO v15_owner;

SELECT v15.v15_register_profile(
  '00000000-0000-4000-8000-0000000000a1'::uuid,
  '{"model":"fake"}'::jsonb,
  '{"timeout_ms":30000}'::jsonb,
  '{"max_invoke_input_length":100000,"truncation_prefix_ratio":0.7,"max_repl_output_length":4000}'::jsonb,
  '[]'::jsonb
);

SELECT v15.v15_register_scope(
  '00000000-0000-4000-8000-0000000000b1'::uuid,
  '00000000-0000-4000-8000-0000000000a1'::uuid
);
