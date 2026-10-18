-- v13 Stage 41: scoped, revisioned registry surface.
-- This stage adds registry objects only and does not replace earlier functions.
BEGIN;

CREATE TABLE public.v13_registrations (
  registration_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_id uuid NOT NULL REFERENCES public.sessions(session_id),
  kind text NOT NULL CHECK (kind IN ('service','tool_profile','prompt_section')),
  name text NOT NULL CHECK (btrim(name) <> '' AND octet_length(name) <= 128),
  value jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
  depends_on text[] NOT NULL DEFAULT '{}'::text[]
    CHECK (array_position(depends_on, NULL) IS NULL
       AND NOT ('' = ANY(depends_on))
       AND (kind = 'service' OR cardinality(depends_on) = 0)),
  valid_from_rev bigint NOT NULL CHECK (valid_from_rev >= 1),
  valid_to_rev bigint CHECK (valid_to_rev IS NULL OR valid_to_rev > valid_from_rev),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scope_id, kind, name, valid_from_rev)
);
CREATE UNIQUE INDEX ux_v13_registrations_one_live
  ON public.v13_registrations (scope_id, kind, name) WHERE valid_to_rev IS NULL;

CREATE TABLE public.v13_registry_clock (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
INSERT INTO public.v13_registry_clock(singleton, revision) VALUES (true, 0);

CREATE TABLE public.v13_registry_meta (
  scope_id uuid PRIMARY KEY REFERENCES public.sessions(session_id),
  revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
);

CREATE FUNCTION public.v13_registrations_frozen()
RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: registry registrations are append-only (no DELETE)';
  END IF;
  IF NEW.registration_id IS DISTINCT FROM OLD.registration_id
     OR NEW.scope_id IS DISTINCT FROM OLD.scope_id
     OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.name IS DISTINCT FROM OLD.name
     OR NEW.value IS DISTINCT FROM OLD.value
     OR NEW.depends_on IS DISTINCT FROM OLD.depends_on
     OR NEW.valid_from_rev IS DISTINCT FROM OLD.valid_from_rev
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'v13: registry registration identity and value are immutable';
  END IF;
  IF OLD.valid_to_rev IS NOT NULL OR NEW.valid_to_rev IS NULL THEN
    RAISE EXCEPTION 'v13: registry retirement is the only permitted update';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_registrations_frozen
  BEFORE UPDATE OR DELETE ON public.v13_registrations
  FOR EACH ROW EXECUTE FUNCTION public.v13_registrations_frozen();

CREATE FUNCTION public.v13_registry_caller_role()
RETURNS name
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r name := current_setting('role', true);
BEGIN
  IF r IS NULL OR r = '' OR r = 'none' THEN
    r := session_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = r) THEN
    RAISE EXCEPTION 'v13 registry: caller role';
  END IF;
  RETURN r;
END $$;

CREATE FUNCTION public.v13_registry_read_ok(p_actor uuid, p_scope uuid)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE caller name;
        parent_id uuid;
BEGIN
  IF p_actor IS NULL THEN
    caller := public.v13_registry_caller_role();
    RETURN COALESCE(EXISTS (
             SELECT 1 FROM pg_catalog.pg_roles
              WHERE rolname = caller AND rolsuper
           ), false)
        OR COALESCE(pg_catalog.pg_has_role(caller, 'v13_route', 'USAGE'), false)
        OR COALESCE(pg_catalog.pg_has_role(caller, 'v13_recall', 'USAGE'), false);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.sessions WHERE session_id = p_actor) THEN
    RETURN false;
  END IF;
  SELECT s.parent_session_id INTO parent_id
    FROM public.sessions AS s WHERE s.session_id = p_scope;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  RETURN COALESCE(p_actor = p_scope, false)
      OR COALESCE(p_actor = parent_id, false);
END $$;

CREATE FUNCTION public.v13_registry_chain_inner(p_scope uuid)
RETURNS TABLE(scope_id uuid, depth integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  WITH RECURSIVE chain(scope_id, parent_session_id, depth, path) AS (
    SELECT s.session_id, s.parent_session_id, 0, ARRAY[s.session_id]
      FROM public.sessions AS s WHERE s.session_id = p_scope
    UNION ALL
    SELECT parent.session_id, parent.parent_session_id, child.depth + 1,
           child.path || parent.session_id
      FROM chain AS child
      JOIN public.sessions AS parent ON parent.session_id = child.parent_session_id
     WHERE child.depth < 31
       AND NOT (parent.session_id = ANY(child.path))
  )
  SELECT chain.scope_id, chain.depth FROM chain ORDER BY chain.depth
$$;

CREATE FUNCTION public.v13_scope_chain(p_scope uuid, p_actor uuid DEFAULT NULL)
RETURNS TABLE(scope_id uuid, depth integer)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE caller name;
        parent_id uuid;
        allowed boolean := false;
BEGIN
  IF p_actor IS NULL THEN
    caller := public.v13_registry_caller_role();
    allowed := COALESCE(EXISTS (
                 SELECT 1 FROM pg_catalog.pg_roles
                  WHERE rolname = caller AND rolsuper
               ), false)
            OR COALESCE(pg_catalog.pg_has_role(caller, 'v13_route', 'USAGE'), false)
            OR COALESCE(pg_catalog.pg_has_role(caller, 'v13_recall', 'USAGE'), false);
  ELSE
    IF NOT EXISTS (SELECT 1 FROM public.sessions WHERE session_id = p_actor) THEN
      RETURN;
    END IF;
    SELECT s.parent_session_id INTO parent_id
      FROM public.sessions AS s WHERE s.session_id = p_scope;
    IF NOT FOUND THEN
      RETURN;
    END IF;
    allowed := COALESCE(p_actor = p_scope, false)
            OR COALESCE(p_actor = parent_id, false);
  END IF;
  IF NOT COALESCE(allowed, false) THEN
    RETURN;
  END IF;
  RETURN QUERY
    SELECT c.scope_id, c.depth
      FROM public.v13_registry_chain_inner(p_scope) AS c
     ORDER BY c.depth;
END $$;

CREATE FUNCTION public.v13_registry_register(
  p_scope uuid,
  p_kind text,
  p_name text,
  p_value jsonb,
  p_depends_on text[] DEFAULT '{}'::text[]
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE caller name;
        caller_super boolean;
        clock_rev bigint;
        new_rev bigint;
        registration uuid;
        live_id uuid;
        live_from bigint;
        item_count integer;
        distinct_count integer;
BEGIN
  -- Step 1: validate caller and every input before acquiring or allocating a revision.
  caller := public.v13_registry_caller_role();
  SELECT COALESCE(rolsuper, false) INTO caller_super
    FROM pg_catalog.pg_roles WHERE rolname = caller;
  IF NOT COALESCE(caller_super, false)
     AND NOT COALESCE(pg_catalog.pg_has_role(caller, 'v13_route', 'USAGE'), false) THEN
    RAISE EXCEPTION 'v13 registry: caller may not register';
  END IF;
  IF p_scope IS NULL OR NOT EXISTS (
       SELECT 1 FROM public.sessions WHERE session_id = p_scope
     ) THEN
    RAISE EXCEPTION 'v13 registry: unknown scope';
  END IF;
  IF p_kind IS NULL OR p_kind NOT IN ('service','tool_profile','prompt_section') THEN
    RAISE EXCEPTION 'v13 registry: invalid kind';
  END IF;
  IF p_name IS NULL OR btrim(p_name) = '' OR octet_length(p_name) > 128 THEN
    RAISE EXCEPTION 'v13 registry: invalid name';
  END IF;
  IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13 registry: value must be an object';
  END IF;
  IF octet_length(p_value::text) > 1048576 THEN
    RAISE EXCEPTION 'v13 registry: value exceeds 1 MiB';
  END IF;
  IF p_depends_on IS NULL THEN
    RAISE EXCEPTION 'v13 registry: depends_on must be an array';
  END IF;
  IF cardinality(p_depends_on) > 64 OR array_position(p_depends_on, NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'v13 registry: invalid depends_on array';
  END IF;
  IF EXISTS (
       SELECT 1 FROM unnest(p_depends_on) AS d(dep)
        WHERE btrim(dep) = '' OR octet_length(dep) > 128
     ) THEN
    RAISE EXCEPTION 'v13 registry: invalid depends_on name';
  END IF;
  SELECT count(*)::integer, count(DISTINCT d.dep)::integer
    INTO item_count, distinct_count FROM unnest(p_depends_on) AS d(dep);
  IF item_count <> distinct_count THEN
    RAISE EXCEPTION 'v13 registry: duplicate depends_on name';
  END IF;
  IF p_kind <> 'service' AND cardinality(p_depends_on) <> 0 THEN
    RAISE EXCEPTION 'v13 registry: only services may depend on services';
  END IF;

  IF p_kind = 'service' THEN
    IF EXISTS (
         SELECT 1 FROM jsonb_object_keys(p_value) AS k(key)
          WHERE key NOT IN ('schema_version','provides','config')
       ) THEN
      RAISE EXCEPTION 'v13 registry: unknown service value key';
    END IF;
    IF NOT (p_value ? 'provides')
       OR jsonb_typeof(p_value->'provides') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_value->'provides') NOT BETWEEN 1 AND 64 THEN
      RAISE EXCEPTION 'v13 registry: service provides must be an array of 1..64 names';
    END IF;
    IF EXISTS (
         SELECT 1 FROM jsonb_array_elements(p_value->'provides') AS e(item)
          WHERE jsonb_typeof(item) IS DISTINCT FROM 'string'
             OR length(item #>> '{}') NOT BETWEEN 1 AND 63
             OR (item #>> '{}') !~ '^[A-Za-z_][A-Za-z0-9_]*$'
       ) THEN
      RAISE EXCEPTION 'v13 registry: invalid service provides name';
    END IF;
    SELECT count(*)::integer, count(DISTINCT item)::integer
      INTO item_count, distinct_count
      FROM jsonb_array_elements(p_value->'provides') AS e(item);
    IF item_count <> distinct_count THEN
      RAISE EXCEPTION 'v13 registry: duplicate service provides name';
    END IF;
    IF p_value ? 'config'
       AND jsonb_typeof(p_value->'config') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13 registry: service config must be an object';
    END IF;
    IF p_value ? 'schema_version'
       AND p_value->'schema_version' IS DISTINCT FROM '1'::jsonb THEN
      RAISE EXCEPTION 'v13 registry: service schema_version must be 1';
    END IF;
  ELSIF p_kind = 'tool_profile' THEN
    -- v13_interruptible() 函数优先、profile 为覆盖面；本阶段 profile 无消费者。
    IF EXISTS (
         SELECT 1 FROM jsonb_object_keys(p_value) AS k(key)
          WHERE key NOT IN ('schema_version','handlers','interruptible')
       ) THEN
      RAISE EXCEPTION 'v13 registry: unknown tool_profile value key';
    END IF;
    IF NOT (p_value ? 'handlers' OR p_value ? 'interruptible') THEN
      RAISE EXCEPTION 'v13 registry: tool_profile requires handlers or interruptible';
    END IF;
    IF p_value ? 'handlers' THEN
      IF jsonb_typeof(p_value->'handlers') IS DISTINCT FROM 'array'
         OR jsonb_array_length(p_value->'handlers') NOT BETWEEN 1 AND 64 THEN
        RAISE EXCEPTION 'v13 registry: tool_profile handlers must be an array of 1..64 names';
      END IF;
      IF EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_value->'handlers') AS e(item)
            WHERE jsonb_typeof(item) IS DISTINCT FROM 'string'
               OR (item #>> '{}') = ''
               OR length(item #>> '{}') > 128
         ) THEN
        RAISE EXCEPTION 'v13 registry: invalid tool_profile handler';
      END IF;
      SELECT count(*)::integer, count(DISTINCT item)::integer
        INTO item_count, distinct_count
        FROM jsonb_array_elements(p_value->'handlers') AS e(item);
      IF item_count <> distinct_count THEN
        RAISE EXCEPTION 'v13 registry: duplicate tool_profile handler';
      END IF;
    END IF;
    IF p_value ? 'interruptible'
       AND (jsonb_typeof(p_value->'interruptible') IS DISTINCT FROM 'string'
         OR p_value->>'interruptible' NOT IN ('required','best_effort','unsupported')) THEN
      RAISE EXCEPTION 'v13 registry: invalid tool_profile interruptible value';
    END IF;
  END IF;

  -- Step 2: the singleton row is the global serialization point.
  SELECT c.revision INTO clock_rev
    FROM public.v13_registry_clock AS c
   WHERE c.singleton FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: registry clock seed missing';
  END IF;

  -- Step 3: conflicts return without writing metadata, events, rows, or clock.
  SELECT r.registration_id, r.valid_from_rev INTO live_id, live_from
    FROM public.v13_registrations AS r
   WHERE r.scope_id = p_scope AND r.kind = p_kind AND r.name = p_name
     AND r.valid_to_rev IS NULL;
  IF FOUND THEN
    RETURN jsonb_build_object('schema_version', 1, 'ok', false,
      'reason', 'already_live', 'registration_id', live_id,
      'valid_from_rev', live_from);
  END IF;

  -- Step 4: allocate exactly one revision and lazily record the scope diagnostic.
  UPDATE public.v13_registry_clock
     SET revision = revision + 1
   WHERE singleton
   RETURNING revision INTO new_rev;
  INSERT INTO public.v13_registry_meta(scope_id, revision)
  VALUES (p_scope, new_rev)
  ON CONFLICT (scope_id) DO UPDATE SET revision = EXCLUDED.revision;

  -- Step 5: append the event before inserting the registration row.
  registration := gen_random_uuid();
  PERFORM public.v13_append_event(
    p_scope, gen_random_uuid(), 'registry/registered',
    jsonb_build_object('schema_version', 1, 'registration_id', registration,
                       'kind', p_kind, 'name', p_name, 'revision', new_rev), NULL
  );
  INSERT INTO public.v13_registrations(
    registration_id, scope_id, kind, name, value, depends_on, valid_from_rev
  ) VALUES (
    registration, p_scope, p_kind, p_name, p_value, p_depends_on, new_rev
  );
  RETURN jsonb_build_object('schema_version', 1, 'ok', true,
    'registration_id', registration, 'revision', new_rev);
END $$;

CREATE FUNCTION public.v13_registry_retire(p_scope uuid, p_kind text, p_name text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE caller name;
        caller_super boolean;
        clock_rev bigint;
        new_rev bigint;
        registration uuid;
BEGIN
  -- Step 1: validate before acquiring or allocating a revision.
  caller := public.v13_registry_caller_role();
  SELECT COALESCE(rolsuper, false) INTO caller_super
    FROM pg_catalog.pg_roles WHERE rolname = caller;
  IF NOT COALESCE(caller_super, false)
     AND NOT COALESCE(pg_catalog.pg_has_role(caller, 'v13_route', 'USAGE'), false) THEN
    RAISE EXCEPTION 'v13 registry: caller may not retire';
  END IF;
  IF p_scope IS NULL OR NOT EXISTS (
       SELECT 1 FROM public.sessions WHERE session_id = p_scope
     ) THEN
    RAISE EXCEPTION 'v13 registry: unknown scope';
  END IF;
  IF p_kind IS NULL OR p_kind NOT IN ('service','tool_profile','prompt_section') THEN
    RAISE EXCEPTION 'v13 registry: invalid kind';
  END IF;
  IF p_name IS NULL OR btrim(p_name) = '' OR octet_length(p_name) > 128 THEN
    RAISE EXCEPTION 'v13 registry: invalid name';
  END IF;

  -- Step 2: lock the global clock before taking any registration row action.
  SELECT c.revision INTO clock_rev
    FROM public.v13_registry_clock AS c
   WHERE c.singleton FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: registry clock seed missing';
  END IF;

  -- Step 3: a missing live row is a structured zero-write result.
  SELECT r.registration_id INTO registration
    FROM public.v13_registrations AS r
   WHERE r.scope_id = p_scope AND r.kind = p_kind AND r.name = p_name
     AND r.valid_to_rev IS NULL;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('schema_version', 1, 'ok', false, 'reason', 'not_live');
  END IF;

  -- Step 4: allocate the revision and update the diagnostic scope mark.
  UPDATE public.v13_registry_clock
     SET revision = revision + 1
   WHERE singleton
   RETURNING revision INTO new_rev;
  INSERT INTO public.v13_registry_meta(scope_id, revision)
  VALUES (p_scope, new_rev)
  ON CONFLICT (scope_id) DO UPDATE SET revision = EXCLUDED.revision;

  -- Step 5: append the retirement event before closing the live interval.
  PERFORM public.v13_append_event(
    p_scope, gen_random_uuid(), 'registry/retired',
    jsonb_build_object('schema_version', 1, 'registration_id', registration,
                       'kind', p_kind, 'name', p_name, 'revision', new_rev), NULL
  );
  UPDATE public.v13_registrations
     SET valid_to_rev = new_rev
   WHERE registration_id = registration AND valid_to_rev IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13 registry: live row changed during retirement';
  END IF;
  RETURN jsonb_build_object('schema_version', 1, 'ok', true,
    'registration_id', registration, 'revision', new_rev);
END $$;

CREATE FUNCTION public.v13_registry_context(
  p_scope uuid,
  p_rev bigint DEFAULT NULL,
  p_actor uuid DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE clock_rev bigint;
        effective_rev bigint;
        tools_rev bigint;
        service_rows jsonb := '[]'::jsonb;
        service_item jsonb;
        service_name text;
        service_deps text[];
        resolved_names text[] := ARRAY[]::text[];
        changed boolean;
        round_no integer;
        service_count integer;
        services_out jsonb := '[]'::jsonb;
        profiles_out jsonb := '[]'::jsonb;
        sections_out jsonb := '[]'::jsonb;
        tools_out jsonb := '[]'::jsonb;
        unresolved_out jsonb := '[]'::jsonb;
        result jsonb;
BEGIN
  -- Negative revisions are rejected before authorization and disclose no scope data.
  IF p_rev IS NOT NULL AND p_rev < 0 THEN
    RAISE EXCEPTION 'v13 registry: revision must be non-negative';
  END IF;

  SELECT c.revision INTO clock_rev
    FROM public.v13_registry_clock AS c WHERE c.singleton;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: registry clock seed missing';
  END IF;
  SELECT m.revision INTO tools_rev
    FROM public.v13_tools_meta AS m WHERE m.singleton;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: tools meta seed missing';
  END IF;

  -- Unauthorized, unknown, and unknown-actor calls share the same canonical empty shape.
  IF NOT COALESCE(public.v13_registry_read_ok(p_actor, p_scope), false)
     OR NOT EXISTS (SELECT 1 FROM public.sessions WHERE session_id = p_scope) THEN
    result := jsonb_build_object(
      'schema_version', 1, 'scope_id', NULL, 'revision', 0, 'tools_revision', 0,
      'services', '[]'::jsonb, 'tool_profiles', '[]'::jsonb,
      'prompt_sections', '[]'::jsonb, 'tools', '[]'::jsonb, 'unresolved', '[]'::jsonb
    );
    RETURN result || jsonb_build_object(
      'context_hash', encode(digest((result)::text, 'sha256'), 'hex')
    );
  END IF;

  IF p_rev IS NULL OR p_rev > clock_rev THEN
    effective_rev := clock_rev;
  ELSE
    effective_rev := p_rev;
  END IF;

  WITH RECURSIVE chain AS (
    SELECT c.scope_id, c.depth FROM public.v13_registry_chain_inner(p_scope) AS c
  ), ranked AS (
    SELECT r.*, chain.depth,
           row_number() OVER (PARTITION BY r.kind, r.name ORDER BY chain.depth) AS rn
      FROM public.v13_registrations AS r
      JOIN chain ON chain.scope_id = r.scope_id
     WHERE r.valid_from_rev <= effective_rev
       AND (r.valid_to_rev IS NULL OR r.valid_to_rev > effective_rev)
  ), picked AS (
    SELECT ranked.*,
           ARRAY(SELECT DISTINCT d.dep FROM unnest(ranked.depends_on) AS d(dep) ORDER BY d.dep) AS sorted_deps
      FROM ranked WHERE rn = 1
  )
  SELECT
    COALESCE(jsonb_agg(
      p.value || jsonb_build_object('name', p.name, 'scope_id', p.scope_id,
        'registration_id', p.registration_id, 'valid_from_rev', p.valid_from_rev)
      ORDER BY p.name
    ) FILTER (WHERE p.kind = 'tool_profile'), '[]'::jsonb),
    COALESCE(jsonb_agg(
      p.value || jsonb_build_object('name', p.name, 'scope_id', p.scope_id,
        'registration_id', p.registration_id, 'valid_from_rev', p.valid_from_rev)
      ORDER BY p.name
    ) FILTER (WHERE p.kind = 'prompt_section'), '[]'::jsonb),
    COALESCE(jsonb_agg(
      jsonb_build_object(
        'name', p.name,
        'entry', p.value || jsonb_build_object('name', p.name, 'scope_id', p.scope_id,
          'registration_id', p.registration_id, 'valid_from_rev', p.valid_from_rev,
          'depends_on', to_jsonb(p.sorted_deps)),
        'depends_on', to_jsonb(p.sorted_deps)
      ) ORDER BY p.name
    ) FILTER (WHERE p.kind = 'service'), '[]'::jsonb)
    INTO profiles_out, sections_out, service_rows
    FROM picked AS p;

  service_count := jsonb_array_length(service_rows);
  IF service_count > 0 THEN
    FOR round_no IN 1..service_count + 1 LOOP
      changed := false;
      FOR service_item IN
        SELECT e.item FROM jsonb_array_elements(service_rows) AS e(item)
         ORDER BY e.item->>'name'
      LOOP
        service_name := service_item->>'name';
        IF service_name = ANY(resolved_names) THEN
          CONTINUE;
        END IF;
        SELECT array_agg(x.dep ORDER BY x.dep) INTO service_deps
          FROM jsonb_array_elements_text(service_item->'depends_on') AS x(dep);
        service_deps := COALESCE(service_deps, ARRAY[]::text[]);
        IF service_deps <@ resolved_names THEN
          resolved_names := array_append(resolved_names, service_name);
          changed := true;
        END IF;
      END LOOP;
      IF NOT changed THEN
        EXIT;
      END IF;
    END LOOP;
    -- Defensive belt: if the bounded closure did not settle, fail closed as unresolved.
    IF changed THEN
      resolved_names := ARRAY[]::text[];
    END IF;
  END IF;

  SELECT COALESCE(jsonb_agg(e.item->'entry' ORDER BY e.item->>'name'), '[]'::jsonb)
    INTO services_out
    FROM jsonb_array_elements(service_rows) AS e(item)
   WHERE (e.item->>'name') = ANY(resolved_names);

  SELECT COALESCE(jsonb_agg(
           jsonb_build_object('name', e.item->>'name', 'missing',
             COALESCE((
               SELECT jsonb_agg(x.dep ORDER BY x.dep)
                 FROM jsonb_array_elements_text(e.item->'depends_on') AS x(dep)
                WHERE NOT (x.dep = ANY(resolved_names))
             ), '[]'::jsonb)
           ) ORDER BY e.item->>'name'
         ), '[]'::jsonb)
    INTO unresolved_out
    FROM jsonb_array_elements(service_rows) AS e(item)
   WHERE NOT ((e.item->>'name') = ANY(resolved_names));

  SELECT COALESCE(jsonb_agg(jsonb_build_object(
           'name', t.name, 'description', t.description, 'kind', t.kind,
           'handler', t.handler, 'param_spec', t.param_spec, 'enabled', t.enabled
         ) ORDER BY t.name), '[]'::jsonb)
    INTO tools_out FROM public.tools AS t;

  result := jsonb_build_object(
    'schema_version', 1,
    'scope_id', p_scope,
    'revision', effective_rev,
    'tools_revision', tools_rev,
    'services', services_out,
    'tool_profiles', profiles_out,
    'prompt_sections', sections_out,
    'tools', tools_out,
    'unresolved', unresolved_out
  );
  RETURN result || jsonb_build_object(
    'context_hash', encode(digest(result::text, 'sha256'), 'hex')
  );
END $$;

-- Registry object family: no PUBLIC access; v13_resolve gets 42501 on every function.
REVOKE ALL ON TABLE public.v13_registrations, public.v13_registry_clock,
  public.v13_registry_meta FROM PUBLIC, v13_worker, v13_resolve, v13_recall, v13_route;
GRANT SELECT ON TABLE public.v13_registrations, public.v13_registry_meta
  TO v13_recall, v13_route;

REVOKE ALL ON FUNCTION public.v13_registrations_frozen(),
  public.v13_registry_caller_role(),
  public.v13_registry_read_ok(uuid,uuid),
  public.v13_registry_chain_inner(uuid),
  public.v13_registry_register(uuid,text,text,jsonb,text[]),
  public.v13_registry_retire(uuid,text,text),
  public.v13_scope_chain(uuid,uuid),
  public.v13_registry_context(uuid,bigint,uuid)
  FROM PUBLIC, v13_worker, v13_resolve, v13_recall, v13_route;
GRANT EXECUTE ON FUNCTION public.v13_registry_register(uuid,text,text,jsonb,text[]),
  public.v13_registry_retire(uuid,text,text)
  TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_scope_chain(uuid,uuid),
  public.v13_registry_context(uuid,bigint,uuid)
  TO v13_recall, v13_route;

COMMIT;
-- STAGE42_CONSUMER_OVERLAY_BEGIN
-- Consumer context pin storage and read-only projection primitives.
BEGIN;

CREATE TABLE public.v13_effect_context_pins (
  effect_id uuid NOT NULL REFERENCES public.effects(effect_id),
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  fence bigint NOT NULL CHECK (fence > 0),
  scope_id uuid NOT NULL REFERENCES public.sessions(session_id),
  context_revision bigint NOT NULL CHECK (context_revision >= 0),
  tools_revision bigint NOT NULL CHECK (tools_revision >= 0),
  claimed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (effect_id, attempt_no),
  UNIQUE (effect_id, attempt_no, fence)
);

CREATE TABLE public.v13_effect_context_event_pins (
  session_id uuid NOT NULL,
  event_seq bigint NOT NULL,
  effect_id uuid NOT NULL,
  attempt_no integer NOT NULL,
  fence bigint NOT NULL,
  PRIMARY KEY (session_id, event_seq),
  FOREIGN KEY (session_id, event_seq)
    REFERENCES public.events(session_id, seq),
  FOREIGN KEY (effect_id, attempt_no, fence)
    REFERENCES public.v13_effect_context_pins(effect_id, attempt_no, fence)
);
CREATE INDEX ix_v13_effect_context_event_pins_effect
  ON public.v13_effect_context_event_pins(effect_id, attempt_no, fence);

CREATE FUNCTION public.v13_effect_context_pin_frozen()
RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  RAISE EXCEPTION 'v13: effect context pins are immutable (%)', TG_OP;
END $$;
CREATE TRIGGER trg_v13_effect_context_pin_frozen
  BEFORE UPDATE OR DELETE ON public.v13_effect_context_pins
  FOR EACH ROW EXECUTE FUNCTION public.v13_effect_context_pin_frozen();

CREATE FUNCTION public.v13_effect_context_event_pin_frozen()
RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.events e
      JOIN public.v13_effect_context_pins p
        ON p.effect_id = NEW.effect_id AND p.attempt_no = NEW.attempt_no AND p.fence = NEW.fence
      WHERE e.session_id = NEW.session_id AND e.seq = NEW.event_seq
        AND e.source_effect_id = NEW.effect_id AND p.scope_id = NEW.session_id
    ) THEN
      RAISE EXCEPTION 'v13: effect context event pin source mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'v13: effect context event pins are immutable (%)', TG_OP;
END $$;
CREATE TRIGGER trg_v13_effect_context_event_pin_frozen
  BEFORE INSERT OR UPDATE OR DELETE ON public.v13_effect_context_event_pins
  FOR EACH ROW EXECUTE FUNCTION public.v13_effect_context_event_pin_frozen();

CREATE FUNCTION public.v13_effect_context_event_capture()
RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_attempt integer;
  v_fence bigint;
BEGIN
  IF NEW.source_effect_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT e.attempt_no, e.fence INTO v_attempt, v_fence
    FROM public.effects AS e
   WHERE e.effect_id = NEW.source_effect_id
     AND e.session_id = NEW.session_id;
  IF NOT FOUND THEN
    RETURN NEW;
  END IF;
  IF EXISTS (SELECT 1 FROM public.v13_effect_context_pins p
              WHERE p.effect_id = NEW.source_effect_id) THEN
    INSERT INTO public.v13_effect_context_event_pins
      (session_id, event_seq, effect_id, attempt_no, fence)
    SELECT NEW.session_id, NEW.seq, p.effect_id, p.attempt_no, p.fence
      FROM public.v13_effect_context_pins p
     WHERE p.effect_id = NEW.source_effect_id
       AND p.attempt_no = v_attempt AND p.fence = v_fence;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_effect_context_event_capture
  AFTER INSERT ON public.events
  FOR EACH ROW EXECUTE FUNCTION public.v13_effect_context_event_capture();

CREATE FUNCTION public.v13_registry_fences()
RETURNS TABLE(registry_revision bigint, tools_revision bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  SELECT c.revision, m.revision INTO registry_revision, tools_revision
    FROM public.v13_registry_clock c CROSS JOIN public.v13_tools_meta m
   WHERE c.singleton AND m.singleton;
  IF NOT FOUND OR registry_revision IS NULL OR tools_revision IS NULL THEN
    RAISE EXCEPTION 'v13 registry: fence seed missing';
  END IF;
  RETURN NEXT;
END $$;

CREATE FUNCTION public.v13_effect_context_pin_insert(
  p_effect uuid, p_attempt integer, p_fence bigint, p_scope uuid,
  p_context_revision bigint, p_tools_revision bigint)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE v_scope uuid; v_attempt integer; v_fence bigint;
BEGIN
  SELECT e.session_id, e.attempt_no, e.fence
    INTO v_scope, v_attempt, v_fence
    FROM public.effects e WHERE e.effect_id = p_effect AND e.status = 'claimed';
  IF NOT FOUND OR v_scope IS DISTINCT FROM p_scope
     OR v_attempt IS DISTINCT FROM p_attempt OR v_fence IS DISTINCT FROM p_fence THEN
    RAISE EXCEPTION 'v13: effect context pin token mismatch';
  END IF;
  INSERT INTO public.v13_effect_context_pins
    (effect_id, attempt_no, fence, scope_id, context_revision, tools_revision)
  VALUES (p_effect, p_attempt, p_fence, p_scope, p_context_revision, p_tools_revision);
END $$;

CREATE FUNCTION public.v13_effect_context_pin_lookup(
  p_effect uuid, p_attempt integer, p_fence bigint)
RETURNS TABLE(scope_id uuid, context_revision bigint, tools_revision bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT p.scope_id, p.context_revision, p.tools_revision
    FROM public.v13_effect_context_pins p
   WHERE p.effect_id = p_effect AND p.attempt_no = p_attempt AND p.fence = p_fence
$$;

CREATE FUNCTION public.v13_effect_context_pin_matches(
  p_effect uuid, p_attempt integer, p_fence bigint, p_context_revision bigint)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  -- NULL means missing exact pin; false means an existing pin's revision differs.
  SELECT p.context_revision = p_context_revision FROM public.v13_effect_context_pins p
    WHERE p.effect_id = p_effect AND p.attempt_no = p_attempt AND p.fence = p_fence
$$;

CREATE FUNCTION public.v13_effect_context_event_current(p_session uuid, p_seq bigint)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE v_source uuid;
BEGIN
  SELECT e.source_effect_id INTO v_source FROM public.events e
    WHERE e.session_id = p_session AND e.seq = p_seq;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.v13_effect_context_pins p WHERE p.effect_id = v_source) THEN
    RETURN true;
  END IF;
  RETURN coalesce((SELECT p.context_revision = f.registry_revision AND p.tools_revision = f.tools_revision
    FROM public.v13_effect_context_event_pins ep
    JOIN public.v13_effect_context_pins p USING (effect_id, attempt_no, fence)
    CROSS JOIN public.v13_registry_fences() f
    WHERE ep.session_id = p_session AND ep.event_seq = p_seq
      AND ep.effect_id = v_source AND p.scope_id = p_session), false);
END $$;

CREATE FUNCTION public.v13_effect_context_effect_current(p_effect uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM public.v13_effect_context_pins p
                                WHERE p.effect_id = p_effect) THEN true
              ELSE EXISTS (
                SELECT 1 FROM public.effects e
                JOIN public.v13_effect_context_pins p
                  ON p.effect_id = e.effect_id AND p.attempt_no = e.attempt_no AND p.fence = e.fence
                CROSS JOIN LATERAL public.v13_registry_fences() f
                WHERE e.effect_id = p_effect
                  AND p.scope_id = e.session_id
                  AND p.context_revision = f.registry_revision
                  AND p.tools_revision = f.tools_revision)
         END
$$;

REVOKE ALL ON TABLE public.v13_effect_context_pins,
  public.v13_effect_context_event_pins FROM PUBLIC, v13_worker, v13_resolve,
  v13_recall, v13_route, v13_spawn_owner;
REVOKE ALL ON FUNCTION public.v13_effect_context_pin_frozen(),
  public.v13_effect_context_event_pin_frozen(),
  public.v13_effect_context_event_capture(),
  public.v13_registry_fences(),
  public.v13_effect_context_pin_insert(uuid,integer,bigint,uuid,bigint,bigint),
  public.v13_effect_context_pin_lookup(uuid,integer,bigint),
  public.v13_effect_context_pin_matches(uuid,integer,bigint,bigint),
  public.v13_effect_context_event_current(uuid,bigint),
  public.v13_effect_context_effect_current(uuid)
  FROM PUBLIC, v13_worker, v13_resolve, v13_recall, v13_route, v13_spawn_owner;
GRANT EXECUTE ON FUNCTION public.v13_registry_fences()
  TO v13_route, v13_recall, v13_resolve;
GRANT EXECUTE ON FUNCTION public.v13_effect_context_pin_insert(uuid,integer,bigint,uuid,bigint,bigint)
  TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_effect_context_pin_lookup(uuid,integer,bigint)
  TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_effect_context_pin_matches(uuid,integer,bigint,bigint)
  TO v13_route, v13_spawn_owner;
GRANT EXECUTE ON FUNCTION public.v13_effect_context_event_current(uuid,bigint),
  public.v13_effect_context_effect_current(uuid)
  TO v13_route, v13_resolve;

-- W2: native claim pins and opt-in strict completion.
CREATE OR REPLACE FUNCTION public.v13_claim(p_worker text, p_lease_ms integer DEFAULT 60000)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = pg_catalog, public
AS $function$
DECLARE v_out jsonb; v_scope uuid; v_registry bigint; v_tools bigint; v_registry2 bigint; v_tools2 bigint;
BEGIN
  SELECT registry_revision, tools_revision INTO v_registry, v_tools
    FROM public.v13_registry_fences();
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
       AND NOT (
         v13_requires_worktree(tool_name)
         AND NOT EXISTS (
           SELECT 1 FROM latches l
            WHERE l.session_id = e.session_id AND l.name = 'worktree'))
     ORDER BY created_at
     FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING jsonb_build_object('effect_id', effect_id, 'attempt_no', attempt_no,
                               'fence', fence, 'kind', kind, 'request', request) INTO v_out;
  IF v_out IS NULL THEN RETURN NULL; END IF;
  SELECT session_id INTO v_scope FROM public.effects
    WHERE effect_id = (v_out->>'effect_id')::uuid;
  PERFORM public.v13_effect_context_pin_insert((v_out->>'effect_id')::uuid,
    (v_out->>'attempt_no')::integer, (v_out->>'fence')::bigint,
    v_scope, v_registry, v_tools);
  SELECT registry_revision, tools_revision INTO v_registry2, v_tools2 FROM public.v13_registry_fences();
  IF v_registry IS DISTINCT FROM v_registry2 OR v_tools IS DISTINCT FROM v_tools2 THEN
    RAISE EXCEPTION 'v13: claim registry fences changed' USING ERRCODE = '40001';
  END IF;
  RETURN v_out || jsonb_build_object('context_revision', v_registry);
END
$function$;

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
  v_registry bigint; v_tools bigint; v_registry2 bigint; v_tools2 bigint;
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
  SELECT registry_revision, tools_revision INTO v_registry, v_tools
    FROM public.v13_registry_fences();
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
  PERFORM public.v13_effect_context_pin_insert(v_eid,
    (v_out->>'attempt_no')::integer, (v_out->>'fence')::bigint,
    v_sid, v_registry, v_tools);
  SELECT registry_revision, tools_revision INTO v_registry2, v_tools2 FROM public.v13_registry_fences();
  IF v_registry IS DISTINCT FROM v_registry2 OR v_tools IS DISTINCT FROM v_tools2 THEN
    RAISE EXCEPTION 'v13: claim registry fences changed' USING ERRCODE = '40001';
  END IF;
  RETURN v_out || jsonb_build_object('context_revision', v_registry);
END
$fn$;

-- Keep completion invoker-security: v13_control_operator/authorized inspect
-- current_user. A definer wrapper would silently turn every caller into owner.
CREATE FUNCTION public.v13_complete_contextual(
  p_actor uuid,
  p_effect uuid,
  p_attempt integer,
  p_fence bigint,
  p_status text,
  p_result jsonb,
  p_context_revision bigint,
  p_require_pin boolean)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $acl_complete6$
DECLARE
  v_sid uuid; v_kind text; v_row effects; v_outcome text; v_err jsonb; v_human jsonb;
  v_resp boolean := false; v_ans boolean := false; v_skip boolean := false;
  v_pin_match boolean;
  v_n int := 0; k text; v_t text; v_calls jsonb; v_tier text;
BEGIN
  IF p_status NOT IN ('succeeded', 'failed', 'unknown', 'cancelled') THEN
    RAISE EXCEPTION 'v13: bad outcome %', p_status;
  END IF;
  IF p_attempt IS NULL OR p_fence IS NULL THEN
    RAISE EXCEPTION 'v13: complete requires non-NULL (attempt,fence) tokens (effect %)', p_effect;
  END IF;
  SELECT session_id, kind INTO v_sid, v_kind FROM effects WHERE effect_id = p_effect;
  IF p_actor IS NOT NULL THEN
    IF NOT FOUND OR v_kind IS DISTINCT FROM 'human' THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
    IF NOT public.v13_control_authorized(p_actor, v_sid) THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
  ELSIF NOT FOUND THEN
    IF public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: unknown effect %', p_effect;
    END IF;
    RAISE EXCEPTION 'v13: session not found';
  ELSIF v_kind = 'human' AND NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF NOT FOUND THEN
    IF p_actor IS NOT NULL OR NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF p_actor IS NOT NULL THEN
    IF v_row.kind IS DISTINCT FROM 'human'
       OR NOT public.v13_control_authorized(p_actor, v_row.session_id) THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
  ELSIF v_row.kind = 'human' AND NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  IF v_row.attempt_no IS DISTINCT FROM p_attempt OR v_row.fence IS DISTINCT FROM p_fence THEN
    RETURN 'stale';
  END IF;
  IF p_require_pin THEN
    IF p_context_revision IS NULL OR p_context_revision < 0 THEN
      RAISE EXCEPTION 'v13: invalid complete context revision' USING ERRCODE = '22023';
    END IF;
    v_pin_match := public.v13_effect_context_pin_matches(
      p_effect, p_attempt, p_fence, p_context_revision);
    IF v_pin_match IS NULL THEN
      RAISE EXCEPTION 'v13: complete context pin missing';
    END IF;
    IF NOT v_pin_match THEN RETURN 'stale'; END IF;
  END IF;
  IF v_row.status IN ('succeeded', 'failed', 'unknown', 'cancelled') THEN
    RETURN 'replay';
  END IF;
  IF v_row.status <> 'claimed' THEN
    RETURN 'stale';
  END IF;
  IF p_status = 'cancelled' THEN
    v_tier := v13_interruptible(v_row.tool_name);
    IF v_row.kind = 'tool' AND v_tier = 'required' THEN
      RAISE EXCEPTION 'v13: mutating interrupt settles unknown';
    END IF;
    IF v_tier = 'unsupported' THEN
      RAISE EXCEPTION 'v13: interruptible unsupported';
    END IF;
    IF NOT v13_unconsumed_cancel(v_sid) THEN
      RAISE EXCEPTION 'v13: cancel not pending';
    END IF;
    IF NOT (v_tier = 'best_effort' OR (v_tier = 'required' AND v_row.kind = 'llm')) THEN
      RAISE EXCEPTION 'v13: bad outcome cancelled';
    END IF;
    UPDATE effects
       SET status = 'cancelled', result = NULL, error = NULL
     WHERE effect_id = p_effect;
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'effect_done',
      jsonb_build_object('effect_id', p_effect, 'status', 'cancelled'), p_effect);
    RETURN 'accepted';
  END IF;
  IF v_row.kind = 'human' AND p_status = 'succeeded' AND v_row.request ? 'interaction_ref' THEN
    IF p_result IS NULL OR jsonb_typeof(p_result) <> 'object' THEN
      RAISE EXCEPTION 'v13: human channel';
    END IF;
    FOR k IN SELECT jsonb_object_keys(p_result) LOOP
      IF k NOT IN ('schema_version', 'interaction_ref', 'response', 'answers', 'skip') THEN
        RAISE EXCEPTION 'v13: human channel unknown key %', k;
      END IF;
    END LOOP;
    IF NOT v13_json_int_ok(p_result->'schema_version', 1)
       OR (p_result->'schema_version')::text::numeric <> 1 THEN
      RAISE EXCEPTION 'v13: human channel schema_version';
    END IF;
    IF jsonb_typeof(p_result->'interaction_ref') IS DISTINCT FROM 'string'
       OR p_result->>'interaction_ref' IS DISTINCT FROM v_row.request->>'interaction_ref' THEN
      RAISE EXCEPTION 'v13: human interaction_ref mismatch (submitted=%, current=%)',
        p_result->>'interaction_ref', v_row.request->>'interaction_ref';
    END IF;
    IF p_result ? 'response' THEN
      v_t := jsonb_typeof(p_result->'response');
      IF v_t IN ('array', 'object', 'null')
         OR (v_t = 'string' AND btrim(p_result->>'response') = '') THEN
        RAISE EXCEPTION 'v13: human channel illegal response';
      END IF;
    END IF;
    IF p_result ? 'answers' THEN
      IF jsonb_typeof(p_result->'answers') IS DISTINCT FROM 'object'
         OR p_result->'answers' = '{}'::jsonb THEN
        RAISE EXCEPTION 'v13: human channel illegal answers';
      END IF;
    END IF;
    IF p_result ? 'skip' AND jsonb_typeof(p_result->'skip') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: human channel illegal skip';
    END IF;
    v_resp := p_result ? 'response' AND jsonb_typeof(p_result->'response') IN ('string', 'number', 'boolean')
              AND (jsonb_typeof(p_result->'response') <> 'string' OR btrim(p_result->>'response') <> '');
    v_ans := p_result ? 'answers' AND jsonb_typeof(p_result->'answers') = 'object'
             AND p_result->'answers' <> '{}'::jsonb;
    v_skip := p_result ? 'skip' AND p_result->'skip' = 'true'::jsonb;
    v_n := v_resp::int + v_ans::int + v_skip::int;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'v13: human channel one-of';
    END IF;
    v_human := jsonb_build_object(
      'schema_version', 1,
      'interaction_ref', v_row.request->>'interaction_ref',
      'skip', CASE WHEN v_skip THEN 'true'::jsonb ELSE 'null'::jsonb END,
      'response', CASE WHEN v_resp THEN p_result->'response' ELSE 'null'::jsonb END,
      'answers', CASE WHEN v_ans THEN p_result->'answers' ELSE 'null'::jsonb END,
      'origin_user_seq', v_row.origin_user_seq);
  END IF;
  IF v_row.kind = 'tool' AND v13_is_harness_tool(v_row.tool_name, v_row.kind) THEN
    IF NOT v13_harness_request_ok(v_row.request) THEN
      RAISE EXCEPTION 'v13: logical_turn_id required';
    END IF;
    IF p_status = 'succeeded' THEN
      PERFORM v13_validate_harness_result_v1(p_result);
    END IF;
  ELSIF v_row.request ? 'logical_turn_id' OR v_row.request ? 'continuation_index'
        OR (p_status = 'succeeded' AND v_row.kind <> 'tool' AND p_result ? 'result_kind') THEN
    RAISE EXCEPTION 'v13: logical_turn_id required';
  END IF;
  IF p_status = 'succeeded'
     AND v_row.tool_name IN ('worktree_prepare', 'worktree_merge', 'worktree_release') THEN
    IF NOT v13_worktree_request_ok(v_row.tool_name, v_row.request) THEN
      RAISE EXCEPTION 'v13: worktree request';
    END IF;
    IF v_row.tool_name = 'worktree_prepare' AND NOT v13_worktree_inline_ok(p_result) THEN
      RAISE EXCEPTION 'v13: worktree inline';
    END IF;
  END IF;
  v_outcome := p_status; v_err := NULL;
  IF p_status = 'succeeded' AND v_row.kind = 'llm'
     AND (coalesce(jsonb_typeof(p_result->'text'), 'null') <> 'string'
          OR coalesce(btrim(p_result->>'text'), '') = '') THEN
    v_outcome := 'failed';
    v_err := jsonb_build_object('code', 'llm_result_shape');
  END IF;
  IF v_row.kind = 'llm' AND p_status = 'succeeded' AND p_result ? 'tool_calls' THEN
    v_calls := v13_llm_tool_calls(p_result->'tool_calls');
  END IF;
  UPDATE effects SET status = v_outcome, result = p_result, error = v_err
   WHERE effect_id = p_effect;
  PERFORM v13_append_event(v_sid, gen_random_uuid(), 'effect_done',
    jsonb_build_object('effect_id', p_effect, 'status', v_outcome), p_effect);
  IF v_outcome = 'succeeded' AND v_row.kind = 'tool' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'tool/result',
      jsonb_build_object('tool', v_row.tool_name, 'result', p_result,
                         'origin_user_seq', v_row.origin_user_seq), p_effect);
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'llm' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'llm/message',
      p_result || jsonb_build_object('origin_user_seq', v_row.origin_user_seq), p_effect);
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'llm' AND v_calls IS NOT NULL THEN
    FOR v_n IN 0..jsonb_array_length(v_calls) - 1 LOOP
      PERFORM v13_append_event(v_sid, gen_random_uuid(), 'tool/call', v_calls->v_n, p_effect);
    END LOOP;
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'tool'
     AND v13_is_harness_tool(v_row.tool_name, v_row.kind) AND p_result ? 'signals' THEN
    IF p_result->'signals' @> '["repair/required"]'::jsonb THEN
      PERFORM v13_append_event(v_sid, gen_random_uuid(), 'repair/required',
        jsonb_build_object('schema_version', 1), p_effect);
    END IF;
    IF p_result->'signals' @> '["replan/required"]'::jsonb THEN
      PERFORM v13_append_event(v_sid, gen_random_uuid(), 'replan/required',
        jsonb_build_object('schema_version', 1), p_effect);
    END IF;
  END IF;
  IF v_human IS NOT NULL AND v_outcome = 'succeeded' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'human/responded', v_human, p_effect);
  END IF;
  IF v_outcome = 'failed' AND v_row.kind = 'judge' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('effect_id', p_effect, 'path', 'worker',
                         'origin_user_seq', v_row.origin_user_seq), p_effect);
  END IF;
  IF v_outcome = 'unknown' THEN
    PERFORM v13_raise_unknown_wall(v_sid);
  END IF;
  IF v_outcome = 'succeeded'
     AND v_row.kind = 'tool'
     AND v_row.tool_name = 'worktree_release' THEN
    PERFORM v13_record_worktree_released(v_sid, p_effect);
  END IF;
  RETURN 'accepted';
END $acl_complete6$;

CREATE OR REPLACE FUNCTION public.v13_complete(
  p_actor uuid, p_effect uuid, p_attempt integer, p_fence bigint,
  p_status text, p_result jsonb DEFAULT NULL::jsonb)
RETURNS text LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $stage42$
BEGIN
  RETURN public.v13_complete_contextual(p_actor, p_effect, p_attempt, p_fence,
    p_status, p_result, NULL::bigint, false);
END
$stage42$;

CREATE FUNCTION public.v13_complete(
  p_actor uuid, p_effect uuid, p_attempt integer, p_fence bigint,
  p_status text, p_result jsonb, p_context_revision bigint)
RETURNS text LANGUAGE sql VOLATILE SET search_path = pg_catalog, public AS $stage42$
  SELECT public.v13_complete_contextual(p_actor, p_effect, p_attempt, p_fence,
    p_status, p_result, p_context_revision, true)
$stage42$;

REVOKE ALL ON FUNCTION public.v13_complete_contextual(uuid,uuid,integer,bigint,text,jsonb,bigint,boolean),
  public.v13_complete(uuid,uuid,integer,bigint,text,jsonb,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_complete_contextual(uuid,uuid,integer,bigint,text,jsonb,bigint,boolean),
  public.v13_complete(uuid,uuid,integer,bigint,text,jsonb,bigint) TO v13_route, v13_spawn_owner;


-- W3: registry revision is freshness, never effect identity.

CREATE OR REPLACE FUNCTION v13_probe(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $stage42$
  SELECT jsonb_build_object(
    'session_version', s.next_seq,
    'max_event_seq', coalesce((SELECT max(seq) FROM events
                                WHERE session_id = p_sid), -1),
    'goal_hash', v13_goal_hash(p_sid),
    'route_policy_name',     s.route_policy_name,
    'route_policy_version',  s.route_policy_version,
    'registry_revision', f.registry_revision,
    'tools_revision', f.tools_revision,
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta
        WHERE singleton))
  FROM sessions s CROSS JOIN public.v13_registry_fences() f WHERE s.session_id = p_sid;
$stage42$;

CREATE OR REPLACE FUNCTION v13_judgment_envelope(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $stage42$
  WITH fences AS MATERIALIZED (SELECT * FROM public.v13_registry_fences()),
  runtime AS MATERIALIZED (
    SELECT v13_guc_required('typesafe.provider') AS provider,
           v13_guc_required('typesafe.model') AS model),
  ctx AS MATERIALIZED (
    SELECT v13_canonical_state(p_sid) AS c),
  rc AS MATERIALIZED (                       -- 【DP6①】自 wm/pol 前移
    SELECT v13_recall_candidates(p_sid) AS r),
  tmpl AS MATERIALIZED (
    SELECT coalesce(jsonb_object_agg(t.template_name, jsonb_build_object(
             'version', t.template_version, 'kind', t.kind,
             'question', t.question, 'criteria', t.criteria,
             'projection', t.projection,
             'answer_schema_version', t.answer_schema_version)), '{}'::jsonb) AS t
      FROM v13_template_latest t),
  fg AS MATERIALIZED (                       -- 【DP6②】过滤族模板在岗守卫
    SELECT v13_require_filter_templates((SELECT t FROM tmpl)) AS g),
  frows AS MATERIALIZED (                    -- 【DP6③】过滤行(消费 rc 冻结
    SELECT coalesce(jsonb_agg(f ORDER BY f->>'signal'), '[]'::jsonb) AS f -- 候选;DISTINCT ON
      FROM ((SELECT jsonb_build_object(           -- content_hash 去重=跨源
                     'signal', 'corpus_exists',   -- 同文一行,判断缓存语义)
                     'kind', (SELECT t FROM tmpl)->'corpus_exists'->>'kind',
                     'question',
                       (SELECT t FROM tmpl)->'corpus_exists'->>'question',
                     'criteria',
                       (SELECT t FROM tmpl)->'corpus_exists'->'criteria',
                     'template_name', 'corpus_exists') AS f
              FROM fg
             WHERE jsonb_array_length(
                     coalesce((SELECT r FROM rc)->'candidates',
                              '[]'::jsonb)) > 0)
            UNION ALL
            (SELECT DISTINCT ON (cand->>'content_hash')
                    jsonb_build_object(
                     'signal', 'chunk::' || (cand->>'content_hash'),
                     'kind', (SELECT t FROM tmpl)->'chunk_score'->>'kind',
                     'question',
                       (SELECT t FROM tmpl)->'chunk_score'->>'question',
                     'criteria',
                       (SELECT t FROM tmpl)->'chunk_score'->'criteria',
                     'template_name', 'chunk_score') AS f
               FROM fg,
                    jsonb_array_elements(
                      coalesce((SELECT r FROM rc)->'candidates',
                               '[]'::jsonb)) cand
              ORDER BY cand->>'content_hash')) s),
  needed AS MATERIALIZED (                   -- 【DP6③】基族 ∪ 过滤行(signal
    SELECT coalesce(jsonb_agg(               -- 升序聚合;CASE 省 criteria 键
             CASE WHEN x.criteria IS NULL THEN   -- 形态与 DP2/DP5 同构)
               jsonb_build_object('signal', x.signal, 'kind', x.kind,
                                  'question', x.question,
                                  'template_name', x.template_name)
             ELSE
               jsonb_build_object('signal', x.signal, 'kind', x.kind,
                                  'question', x.question, 'criteria', x.criteria,
                                  'template_name', x.template_name)
             END ORDER BY x.signal), '[]'::jsonb) AS n
      FROM (SELECT signal, kind, question, criteria, template_name
              FROM v13_needed_judgments(p_sid)
             UNION ALL
            SELECT f->>'signal', f->>'kind', f->>'question',
                   NULLIF(f->'criteria', 'null'::jsonb),
                   f->>'template_name'
              FROM jsonb_array_elements((SELECT f FROM frows)) f) x),
  groups AS MATERIALIZED (                   -- 【DP6④】仅 canonical 行(过滤
    SELECT coalesce(jsonb_agg(jsonb_build_object('projection_key', s.pkey, -- 族的组态
                                                 'state', s.state)      -- 在 resolve 侧构建,
                              ORDER BY s.pkey), '[]'::jsonb) AS g        -- 信封不携体)
      FROM (SELECT DISTINCT
              v13_projection_key(
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS pkey,
              v13_project_state(
                (SELECT c FROM ctx),
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS state
              FROM jsonb_array_elements((SELECT n FROM needed)) nr
             WHERE (nr.value->>'template_name')
                   NOT IN ('chunk_score','corpus_exists')) s),
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
      encode(digest(jsonb_build_object(
        'needed', (SELECT n FROM needed),
        'recall', (SELECT r FROM rc))::text, 'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'provider', (SELECT provider FROM runtime),
    'model',    (SELECT model FROM runtime),
    'route_policy_name',     (SELECT rpn FROM pol),
    'route_policy_version',  (SELECT rpv FROM pol),
    'registry_revision', (SELECT registry_revision FROM fences),
    'tools_revision', (SELECT tools_revision FROM fences),
    'tools_catalog',  v13_tools_catalog_frozen(),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton),
    'session_version', (SELECT sv FROM wm),
    'max_event_seq',   (SELECT mes FROM wm),
    'needed_count', jsonb_array_length((SELECT n FROM needed)),
    'candidates', (SELECT r->'candidates' FROM rc));
$stage42$;

CREATE OR REPLACE FUNCTION v13_snap_of(p_env jsonb) RETURNS jsonb
LANGUAGE sql STABLE AS $stage42$
  SELECT jsonb_build_object(
    'sid', p_env->>'sid',
    'session_version', p_env->>'session_version',
    'max_event_seq', p_env->>'max_event_seq',
    'goal_hash', p_env->>'goal_hash',
    'candidate_set_hash', p_env->>'candidate_set_hash',
    'needed_count', p_env->>'needed_count',
    'route_policy_name', p_env->>'route_policy_name',
    'route_policy_version', p_env->>'route_policy_version',
    'registry_revision', p_env->>'registry_revision',
    'tools_revision', p_env->>'tools_revision',
    'candidate_generation_revision',
      p_env->>'candidate_generation_revision',   -- turn 9,#59:步 0 第七键
    'gap_count', jsonb_array_length(v13_gap(p_env)));
$stage42$;

CREATE OR REPLACE FUNCTION v13_effect_envelope(p_env jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $stage42$
  SELECT p_env - 'session_version' - 'max_event_seq'
         - 'route_policy_name' - 'route_policy_version'
         - 'tools_revision' - 'tools_catalog'
         - 'candidate_generation_revision' - 'registry_revision';
$stage42$;

CREATE OR REPLACE FUNCTION public.v13_advance(p_sid uuid, p_snap jsonb)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_now jsonb; v_route jsonb; v_cycles int; v_max int;
  v_effect uuid; v_est text; v_res jsonb; v_handler text; v_req jsonb; v_err jsonb;
  v_pred uuid; v_prow effects; v_sig text[]; v_ev text[]; v_cand boolean;
  v_cap_new boolean; v_cont boolean; v_idx bigint; v_st text;
  v_calls jsonb; v_sreq jsonb; v_triage text;
  v_plan_word text;
  -- R0_DECL_BEGIN
  v_r0_parent uuid;
  v_r0_pred uuid;
  v_r0_good boolean;
  -- R0_DECL_END
BEGIN
  IF p_snap IS NULL
     OR (p_snap->'snap'->>'sid') IS DISTINCT FROM p_sid::text
     OR (p_snap->'envelope'->>'sid') IS DISTINCT FROM p_sid::text THEN
    RAISE EXCEPTION 'v13: advance/snapshot session mismatch (p=%, snap=%, env=%)',
      p_sid, p_snap->'snap'->>'sid', p_snap->'envelope'->>'sid';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  v_now := v13_probe(p_sid);
  IF (v_now->>'session_version', v_now->>'max_event_seq', v_now->>'goal_hash',
      v_now->>'route_policy_name', v_now->>'route_policy_version',
      v_now->>'tools_revision', v_now->>'candidate_generation_revision',
      v_now->>'registry_revision')
     IS DISTINCT FROM
     (p_snap->'snap'->>'session_version', p_snap->'snap'->>'max_event_seq',
      p_snap->'snap'->>'goal_hash', p_snap->'snap'->>'route_policy_name',
      p_snap->'snap'->>'route_policy_version', p_snap->'snap'->>'tools_revision',
      p_snap->'snap'->>'candidate_generation_revision',
      p_snap->'snap'->>'registry_revision') THEN
    RETURN 'stale';
  END IF;
  PERFORM v13_bind_worktree_from_prepare(p_sid);
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN 'terminal';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'unknown')
     OR v_st = 'blocked_unknown' THEN
    IF v_st NOT IN ('blocked_unknown', 'completed', 'failed', 'cancelled') THEN
      RAISE EXCEPTION 'v13: unknown wall drift';
    END IF;
    IF v13_unconsumed_cancel(p_sid) THEN
      UPDATE effects SET status = 'cancelled', fence = fence + 1, error = NULL,
             lease_owner = NULL, lease_until = NULL
       WHERE session_id = p_sid AND status = 'ready';
    END IF;
    RETURN 'waiting';
  END IF;
  IF v13_unconsumed_cancel(p_sid) THEN
    UPDATE effects SET status = 'cancelled', fence = fence + 1, error = NULL,
           lease_owner = NULL, lease_until = NULL
     WHERE session_id = p_sid AND status = 'ready';
    IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'claimed') THEN
      UPDATE sessions SET status = 'waiting'
       WHERE session_id = p_sid AND status IN ('ready', 'waiting');
      RETURN 'waiting';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed', 'unknown')) THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'cancelled', 'cancel', false);
      RETURN 'terminal';
    END IF;
    RETURN 'waiting';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed')) THEN
    -- R0_RECEIPT_BEGIN
    -- The entry lock is on p_sid itself: never map or lock a child's root.
    SELECT parent_session_id INTO v_r0_parent FROM sessions WHERE session_id = p_sid;
    IF v_r0_parent IS NULL THEN
      v_r0_pred := (SELECT e.effect_id FROM effects e
      WHERE e.session_id = p_sid AND e.kind = 'tool'
        AND v13_is_harness_tool(e.tool_name, e.kind)
        AND e.origin_user_seq = v13_last_user_seq(p_sid)
        AND v13_harness_request_ok(e.request)
        AND public.v13_effect_context_effect_current(e.effect_id)
      ORDER BY (SELECT max(ev.seq) FROM events ev
                 WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id
                   AND public.v13_effect_context_event_current(ev.session_id, ev.seq)) DESC NULLS LAST,
               e.created_at DESC, e.effect_id DESC LIMIT 1);
      IF v_r0_pred IS NOT NULL THEN
        SELECT * INTO v_prow FROM effects WHERE effect_id = v_r0_pred FOR UPDATE;
        v_r0_good := FOUND
          AND v_prow.session_id = p_sid
          AND v_r0_pred = (SELECT e.effect_id FROM effects e
      WHERE e.session_id = p_sid AND e.kind = 'tool'
        AND v13_is_harness_tool(e.tool_name, e.kind)
        AND e.origin_user_seq = v13_last_user_seq(p_sid)
        AND v13_harness_request_ok(e.request)
        AND public.v13_effect_context_effect_current(e.effect_id)
      ORDER BY (SELECT max(ev.seq) FROM events ev
                 WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id
                   AND public.v13_effect_context_event_current(ev.session_id, ev.seq)) DESC NULLS LAST,
               e.created_at DESC, e.effect_id DESC LIMIT 1)
          AND v_prow.kind = 'tool'
          AND v13_is_harness_tool(v_prow.tool_name, v_prow.kind)
          AND v13_harness_request_ok(v_prow.request)
          AND v_prow.origin_user_seq = v13_last_user_seq(p_sid)
          AND v_prow.status = 'succeeded'
          AND jsonb_typeof(v_prow.result) = 'object';
        IF v_r0_good THEN
          -- Keep JSON expansion behind separate type checks, not SQL AND order.
          IF v_prow.result ? 'signals' THEN
            IF jsonb_typeof(v_prow.result->'signals') IS DISTINCT FROM 'array' THEN
              v_r0_good := false;
            ELSE
              SELECT NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(v_prow.result->'signals') x
                 WHERE jsonb_typeof(x) IS DISTINCT FROM 'string') INTO v_r0_good;
            END IF;
          END IF;
          IF v_r0_good THEN
            SELECT coalesce(array_agg(x ORDER BY x), '{}') INTO v_sig
              FROM jsonb_array_elements_text(
                CASE WHEN v_prow.result ? 'signals'
                     THEN v_prow.result->'signals' ELSE '[]'::jsonb END) x;
            SELECT coalesce(array_agg(type ORDER BY type), '{}') INTO v_ev
              FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_r0_pred
               AND type IN ('repair/required', 'replan/required');
            v_r0_good := v_sig IS NOT DISTINCT FROM v_ev
              AND (v_prow.result->>'result_kind' = 'finish'
                OR (v_prow.result->>'result_kind' = 'progress' AND NOT EXISTS (
                      SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_r0_pred
                       AND type IN ('repair/required', 'replan/required'))))
              AND NOT (v13_goal_lifecycle(p_sid) = 'stopped'
                       AND (v_prow.result->>'failed') IS NOT NULL)
              AND NOT EXISTS (
                SELECT 1 FROM events ev
                JOIN effects src ON src.effect_id = ev.source_effect_id
                 WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = p_sid AND ev.type = 'turn/material_spent'
                   AND src.request->>'logical_turn_id' = v_prow.request->>'logical_turn_id'
                   AND ev.source_effect_id IS DISTINCT FROM v_r0_pred)
              AND NOT EXISTS (
                SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_r0_pred
                 AND type = 'turn/material_spent');
            IF v_r0_good THEN
              PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/material_spent',
                jsonb_build_object('schema_version', 1, 'effect_id', v_r0_pred::text), v_r0_pred);
            END IF;
          END IF;
        END IF;
      END IF;
    END IF;
    -- R0_RECEIPT_END
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'tool_call_id', e.payload->>'id',
           'task', e.payload->'args'->>'task') ORDER BY e.seq), '[]'::jsonb)
    INTO v_calls
    FROM events e
   WHERE public.v13_effect_context_event_current(e.session_id, e.seq) AND e.session_id = p_sid
     AND e.type = 'tool/call'
     AND e.seq > v13_last_user_seq(p_sid)
     AND NOT EXISTS (
       SELECT 1 FROM events c
        WHERE c.session_id = p_sid AND c.type = 'child-created'
          AND c.payload->>'tool_call_id' = e.payload->>'id');
  PERFORM v13_triage_block_explore_spawn(p_sid);
  PERFORM public.v13_policy_share();
  IF jsonb_array_length(v_calls) > 0 THEN
    IF NOT public.v13_should_run(p_sid) THEN
      UPDATE public.sessions SET status = 'waiting'
       WHERE session_id = p_sid AND status IN ('ready', 'waiting');
      RETURN 'waiting';
    ELSIF NOT public.v13_spawn_batch_allowed(p_sid, jsonb_array_length(v_calls)) THEN
      UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting');
      RETURN 'waiting';
    END IF;
    v_calls := v13_spawn_children(v_calls);
    v_sreq := v13_spawn_request(v_calls);
    v_effect := v13_effect_id(p_sid, 'tool', v_sreq);
    v_res := v13_spawn_subsession(p_sid, jsonb_build_object(
      'schema_version', 1, 'children', v_calls));
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route',
      jsonb_build_object('action', 'sql', 'reason', 'spawn_fanout',
                         'tool', 'spawn_subsession', 'params', '{}'::jsonb));
    INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash,
                         idempotency_key, status, result, error, origin_user_seq)
    VALUES (v_effect, p_sid, 'tool', 'spawn_subsession', v_sreq,
            encode(digest(v_sreq::text, 'sha256'), 'hex'),
            'v13:' || v_effect::text,
            'succeeded', v_res, NULL, v13_last_user_seq(p_sid));
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'tool/result',
      jsonb_build_object('tool', 'spawn_subsession', 'result', v_res,
                         'origin_user_seq', v13_last_user_seq(p_sid)), v_effect);
    RETURN 'progressed';
  END IF;
  v_plan_word := public.v13_plan_advance_prefix(p_sid);
  IF v_plan_word IS NOT NULL THEN
    RETURN v_plan_word;
  END IF;
  v_pred := (SELECT e.effect_id FROM effects e
      WHERE e.session_id = p_sid AND e.kind = 'tool'
        AND v13_is_harness_tool(e.tool_name, e.kind)
        AND e.origin_user_seq = v13_last_user_seq(p_sid)
        AND v13_harness_request_ok(e.request)
        AND public.v13_effect_context_effect_current(e.effect_id)
      ORDER BY (SELECT max(ev.seq) FROM events ev
                 WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id
                   AND public.v13_effect_context_event_current(ev.session_id, ev.seq)) DESC NULLS LAST,
               e.created_at DESC, e.effect_id DESC LIMIT 1);
  IF v_pred IS NOT NULL THEN
    PERFORM v13_harness_tail_gap(p_sid, v_pred);
    SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
    IF v_prow.status IN ('unknown', 'ready', 'claimed') THEN
      RAISE EXCEPTION 'v13: harness predecessor active';
    END IF;
    IF v_prow.status = 'succeeded' THEN
      SELECT coalesce(array_agg(x ORDER BY x), '{}') INTO v_sig
        FROM jsonb_array_elements_text(
          CASE WHEN v_prow.result ? 'signals' THEN v_prow.result->'signals' ELSE '[]'::jsonb END) x;
      SELECT coalesce(array_agg(type ORDER BY type), '{}') INTO v_ev
        FROM events
       WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_pred AND type IN ('repair/required', 'replan/required');
      IF v_sig IS DISTINCT FROM v_ev THEN
        RAISE EXCEPTION 'v13: signals ledger';
      END IF;
      v_cand := v_prow.result->>'result_kind' = 'finish'
        OR (v_prow.result->>'result_kind' = 'progress' AND NOT EXISTS (
              SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_pred
                AND type IN ('repair/required', 'replan/required')));
      IF v_cand THEN
        IF EXISTS (
          SELECT 1 FROM events ev
          JOIN effects src ON src.effect_id = ev.source_effect_id
           WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = p_sid AND ev.type = 'turn/material_spent'
             AND src.request->>'logical_turn_id' = v_prow.request->>'logical_turn_id'
             AND ev.source_effect_id IS DISTINCT FROM v_pred) THEN
          RAISE EXCEPTION 'v13: material ledger';
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_pred AND type = 'turn/material_spent') THEN
          PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/material_spent',
            jsonb_build_object('schema_version', 1, 'effect_id', v_pred::text), v_pred);
        END IF;
      END IF;
      IF v_prow.result->>'result_kind' = 'finish' THEN
        IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'completed', 'harness_finish', false);
        RETURN 'terminal';
      ELSIF v_prow.result->>'result_kind' = 'reject' THEN
        IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'harness_reject', false);
        RETURN 'terminal';
      END IF;
      IF v_prow.result->>'result_kind' = 'wait'
         AND v_prow.result->>'wait_reason' IN ('evidence', 'quota')
         AND NOT EXISTS (
           SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_pred AND type = 'wake/satisfied') THEN
        IF NOT v13_wake_is_satisfied_v1(p_sid, v_pred, v_prow.result->'wake') THEN
          UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
          RETURN 'waiting';
        END IF;
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'wake/satisfied',
          jsonb_build_object('effect_id', v_pred::text, 'wake_kind', v_prow.result->'wake'->>'kind'),
          v_pred);
      END IF;
      IF v_prow.result->>'result_kind' = 'wait' AND v_prow.result->>'wait_reason' = 'approval'
         AND NOT EXISTS (
           SELECT 1 FROM effects h
            WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
              AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id') THEN
        IF NOT public.v13_should_run(p_sid) THEN
          UPDATE public.sessions SET status = 'waiting'
           WHERE session_id = p_sid AND status IN ('ready', 'waiting');
          RETURN 'waiting';
        END IF;
        IF EXISTS (
          SELECT 1 FROM effects h
           WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = p_sid AND h.kind = 'human'
             AND h.status IN ('ready', 'claimed', 'unknown')) THEN
          RAISE EXCEPTION 'v13: approval human exists';
        END IF;
        IF v13_cycle_no(p_sid) >= (v13_policy('turn_budget')->>'max_cycles')::int THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
          RETURN 'terminal';
        END IF;
        v_effect := v13_enqueue_effect(p_sid, 'human',
          jsonb_build_object('schema_version', 1,
                             'interaction_ref', v_prow.result->>'interaction_id'));
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'approval_exhausted', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
      v_cap_new := v13_cap_human_answered(p_sid, v_pred);
      v_cont := false;
      IF NOT v_cap_new THEN
        IF v_prow.result->>'result_kind' = 'progress' AND EXISTS (
             SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_pred
               AND type IN ('repair/required', 'replan/required')) THEN
          v_cont := true;
        ELSIF v_prow.result->>'result_kind' = 'wait' AND (
              (v_prow.result->>'wait_reason' = 'approval' AND EXISTS (
                 SELECT 1 FROM effects h
                  WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
                    AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id'))
              OR (v_prow.result->>'wait_reason' IN ('evidence', 'quota') AND EXISTS (
                 SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND source_effect_id = v_pred AND type = 'wake/satisfied'))) THEN
          v_cont := true;
        END IF;
      END IF;
      IF v_cont THEN
        IF NOT public.v13_should_run(p_sid) THEN
          UPDATE public.sessions SET status = 'waiting'
           WHERE session_id = p_sid AND status IN ('ready', 'waiting');
          RETURN 'waiting';
        END IF;
        IF v13_cycle_no(p_sid) >= (v13_policy('turn_budget')->>'max_cycles')::int THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
          RETURN 'terminal';
        END IF;
        v_idx := (v_prow.request->>'continuation_index')::bigint;
        IF v_idx >= 2147483647 THEN
          RAISE EXCEPTION 'v13: continuation_index overflow';
        END IF;
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route',
          jsonb_build_object('action', 'tool', 'reason', 'harness_continuation',
                             'tool', 'harness_turn', 'params', '{}'::jsonb));
        v_req := jsonb_build_object(
          'tool', 'harness_turn',
          'params', '{}'::jsonb,
          'handler', v_prow.request->'handler',
          'tools_revision', v_prow.request->'tools_revision',
          'logical_turn_id', v_prow.request->'logical_turn_id',
          'continuation_index', v_idx + 1);
        v_effect := v13_enqueue_effect(p_sid, 'tool', v_req, 'harness_turn');
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'harness_attempts', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
    END IF;
  END IF;
  IF public.v13_triage_duty()<>0
     AND NOT public.v13_should_run(p_sid)
     AND p_snap->>'failed' IS NOT NULL THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('remaining', p_snap->'snap'->>'gap_count',
                         'origin_user_seq', v13_last_user_seq(p_sid)));
  END IF;
  v_triage := v13_triage_prework(p_sid);
  IF v_triage IS NOT NULL THEN
    RETURN v_triage;
  END IF;
  IF coalesce((p_snap->>'failed')::boolean, false) THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('remaining', p_snap->'snap'->>'gap_count',
                         'origin_user_seq', v13_last_user_seq(p_sid)));
    RETURN 'progressed';
  END IF;
  IF coalesce((p_snap->>'abandon')::boolean, false) THEN
    v_effect := v13_enqueue_effect(p_sid, 'human', jsonb_build_object('reason', 'resolve_budget'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est = 'succeeded' THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'resolve_budget', false);
      RETURN 'terminal';
    ELSIF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'resolve_budget', true);
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  IF NOT v13_context_fresh(p_sid) THEN
    v_effect := v13_enqueue_effect(p_sid, 'context_refresh',
      jsonb_build_object('goal_hash', p_snap->'snap'->>'goal_hash'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'context_refresh', true);
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  v_cycles := v13_cycle_no(p_sid);
  v_max := (v13_policy('turn_budget')->>'max_cycles')::int;
  IF v_cycles >= v_max THEN
    v_effect := v13_enqueue_effect(p_sid, 'human', jsonb_build_object('reason', 'budget_exhausted'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est = 'succeeded' THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
      RETURN 'terminal';
    ELSIF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', true);
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  IF (p_snap->>'remaining')::int > 0 THEN
    v_effect := v13_enqueue_effect(p_sid, 'judge',
      jsonb_build_object('envelope', v13_effect_envelope(p_snap->'envelope')));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'judge_attempts', true);
      RETURN 'terminal';
    ELSIF v_est <> 'succeeded' THEN
      PERFORM v13_send_work(v_effect);
      UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
      RETURN 'waiting';
    END IF;
  END IF;
  v_triage := v13_triage_steer(p_sid);
  IF v_triage IS NOT NULL THEN
    RETURN v_triage;
  END IF;
  v_route := v13_route(p_sid, p_snap->'envelope');
  v_route := v13_triage_after_route(p_sid, v_route);
  IF v_route->>'action' = 'sql' AND v13_is_harness_tool(v_route->>'tool', 'tool') THEN
    RAISE EXCEPTION 'v13: harness_turn kind';
  END IF;
  IF v_route->>'action' = 'sql' AND v13_is_spawn_tool(v_route->>'tool', 'sql') THEN
    RAISE EXCEPTION 'v13: spawn batch-dispatched';
  END IF;
  IF v_route->>'action' = 'tool' AND v13_is_harness_tool(v_route->>'tool', 'tool') THEN
    v_pred := (SELECT e.effect_id FROM effects e
      WHERE e.session_id = p_sid AND e.kind = 'tool'
        AND v13_is_harness_tool(e.tool_name, e.kind)
        AND e.origin_user_seq = v13_last_user_seq(p_sid)
        AND v13_harness_request_ok(e.request)
        AND public.v13_effect_context_effect_current(e.effect_id)
      ORDER BY (SELECT max(ev.seq) FROM events ev
                 WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id
                   AND public.v13_effect_context_event_current(ev.session_id, ev.seq)) DESC NULLS LAST,
               e.created_at DESC, e.effect_id DESC LIMIT 1);
    IF v_pred IS NOT NULL THEN
      SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
      IF v_prow.status IN ('failed', 'cancelled') THEN
        PERFORM v13_harness_tail_gap(p_sid, v_pred);
        v_effect := v13_enqueue_effect(p_sid, 'tool', v_prow.request, v_prow.tool_name);
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'harness_attempts', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
    END IF;
  END IF;
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
  CASE v_route->>'action'
  WHEN 'sql' THEN
    IF v13_is_harness_tool(v_route->>'tool', 'tool') THEN
      RAISE EXCEPTION 'v13: harness_turn kind';
    END IF;
    IF v13_is_spawn_tool(v_route->>'tool', 'sql') THEN
      RAISE EXCEPTION 'v13: spawn batch-dispatched';
    END IF;
    SELECT t->>'handler' INTO v_handler
      FROM jsonb_array_elements(p_snap->'envelope'->'tools_catalog') t
     WHERE t->>'name' = v_route->>'tool' AND t->>'kind' = 'sql'
       AND (t->>'enabled')::boolean;
    v_req := jsonb_build_object('tool', v_route->>'tool',
                                'params', coalesce(v_route->'params', '{}'::jsonb));
    v_err := NULL;
    BEGIN
      EXECUTE format('SELECT %s($1, $2)', v_handler)
         INTO v_res USING p_sid, coalesce(v_route->'params', '{}'::jsonb);
    EXCEPTION
      WHEN query_canceled THEN
        IF coalesce(current_setting('statement_timeout', true), '0') IN ('0', '0ms') THEN
          RAISE;
        END IF;
        v_res := NULL;
        v_err := jsonb_build_object('sqlstate', SQLSTATE, 'message', SQLERRM);
      WHEN OTHERS THEN
        v_res := NULL;
        v_err := jsonb_build_object('sqlstate', SQLSTATE, 'message', SQLERRM);
    END;
    v_effect := v13_effect_id(p_sid, 'tool', v_req);
    INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash,
                         idempotency_key, status, result, error, origin_user_seq)
    VALUES (v_effect, p_sid, 'tool', v_route->>'tool', v_req,
            encode(digest(v_req::text, 'sha256'), 'hex'),
            'v13:' || v_effect::text,
            CASE WHEN v_err IS NULL THEN 'succeeded' ELSE 'failed' END,
            CASE WHEN v_err IS NULL THEN v_res END, v_err, v13_last_user_seq(p_sid));
    IF v_err IS NULL THEN
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'tool/result',
        jsonb_build_object('tool', v_route->>'tool', 'result', v_res,
                           'origin_user_seq', v13_last_user_seq(p_sid)), v_effect);
    END IF;
    RETURN 'progressed';
  WHEN 'tool' THEN
    SELECT t->>'handler' INTO v_handler
      FROM jsonb_array_elements(p_snap->'envelope'->'tools_catalog') t
     WHERE t->>'name' = v_route->>'tool' AND (t->>'enabled')::boolean;
    IF v13_is_harness_tool(v_route->>'tool', 'tool') THEN
      v_pred := (SELECT e.effect_id FROM effects e
      WHERE e.session_id = p_sid AND e.kind = 'tool'
        AND v13_is_harness_tool(e.tool_name, e.kind)
        AND e.origin_user_seq = v13_last_user_seq(p_sid)
        AND v13_harness_request_ok(e.request)
        AND public.v13_effect_context_effect_current(e.effect_id)
      ORDER BY (SELECT max(ev.seq) FROM events ev
                 WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id
                   AND public.v13_effect_context_event_current(ev.session_id, ev.seq)) DESC NULLS LAST,
               e.created_at DESC, e.effect_id DESC LIMIT 1);
      IF v_pred IS NOT NULL THEN
        SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
        IF v_prow.status = 'succeeded'
           AND v_prow.result->>'result_kind' IN ('finish', 'reject') THEN
          RAISE EXCEPTION 'v13: harness finish/reject does not continue';
        END IF;
      END IF;
      PERFORM v13_harness_tail_gap(p_sid, v_pred);
      v_req := jsonb_build_object(
        'tool', 'harness_turn',
        'params', '{}'::jsonb,
        'handler', v_handler,
        'tools_revision', p_snap->'envelope'->'tools_revision',
        'logical_turn_id', gen_random_uuid()::text,
        'continuation_index', 0);
      v_effect := v13_enqueue_effect(p_sid, 'tool', v_req, v_route->>'tool');
    ELSE
      v_effect := v13_enqueue_effect(p_sid, 'tool',
        jsonb_build_object('tool', v_route->>'tool',
                           'params', coalesce(v_route->'params', '{}'::jsonb),
                           'handler', v_handler,
                           'tools_revision', p_snap->'envelope'->'tools_revision'),
        v_route->>'tool');
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'llm' THEN
    v_effect := v13_enqueue_effect(p_sid, 'llm', jsonb_build_object('route', v_route));
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'human' THEN
    v_effect := v13_enqueue_effect(p_sid, 'human',
      jsonb_build_object('reason', v_route->>'reason'));
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'finish' THEN
    IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'completed', coalesce(v_route->>'reason', 'answered'), false);
    RETURN 'terminal';
  WHEN 'reject' THEN
    IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', coalesce(v_route->>'reason', 'injection_veto'), false);
    RETURN 'terminal';
  ELSE
    RAISE EXCEPTION 'v13: route returned no action for %', p_sid;
  END CASE;
END $function$;
-- W4 consumers: current-turn machine messages and failure budget.
CREATE OR REPLACE FUNCTION public.v13_route(p_sid uuid, p_env jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $w4$
DECLARE
  v_intent jsonb; v_tool text; v_kind text; v_params jsonb;
  v_ltype text; v_lseq bigint;
BEGIN
  v_intent := v13_env_answer(p_env, 'intent');
  v_tool := v13_env_answer(p_env, 'tool')->>'choice';
  SELECT e.type, e.seq INTO v_ltype, v_lseq
    FROM events e
   WHERE e.session_id = p_sid AND e.type IN ('llm/message','tool/result')
     AND (e.payload->>'origin_user_seq')::bigint = v13_last_user_seq(p_sid)
     AND public.v13_effect_context_event_current(e.session_id, e.seq)
   ORDER BY e.seq DESC LIMIT 1;
  IF v_ltype = 'llm/message' AND v_lseq > v13_last_user_seq(p_sid) THEN
    RETURN jsonb_build_object('action','finish','reason','answered');
  ELSIF v13_env_hit(p_env, 'gate_off_topic', 'reject') THEN
    RETURN jsonb_build_object('action','reject','reason','injection_veto');
  ELSIF v_intent IS NULL OR NOT v13_env_hit(p_env, 'intent', 'pass') THEN
    RETURN jsonb_build_object('action','human','reason','low_intent_confidence');
  ELSIF v_intent->>'choice' = 'human_escalate' THEN
    RETURN jsonb_build_object('action','human','reason','model_escalated');
  ELSIF v_intent->>'choice' IN ('sql_answer','tool_action')
        AND v13_env_hit(p_env, 'gate_action', 'pass')
        AND v13_env_hit(p_env, 'tool', 'pass') AND v_tool IS NOT NULL AND v_tool <> 'none' THEN
    SELECT t->>'kind' INTO v_kind FROM jsonb_array_elements(p_env->'tools_catalog') t
     WHERE t->>'name' = v_tool AND (t->>'enabled')::boolean;
    v_params := v13_resolve_tool_params(p_env, v_tool);
    IF v_kind IS NULL THEN
      RETURN jsonb_build_object('action','human','reason','tool_unavailable');
    ELSIF v_kind = 'sql' THEN
      RETURN jsonb_build_object('action','sql','reason','in_db_handler','tool',v_tool,'params',v_params);
    ELSIF v_kind = 'tool' AND v13_env_hit(p_env, 'risk', 'reject') THEN
      RETURN jsonb_build_object('action','human','reason','risk_veto');
    ELSE
      RETURN jsonb_build_object('action','tool','reason','side_effect_tool','tool',v_tool,'params',v_params);
    END IF;
  ELSE
    RETURN jsonb_build_object('action','llm','reason','generation_needed');
  END IF;
END $w4$;

CREATE OR REPLACE FUNCTION v13_canonical_state(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $w4$
  SELECT jsonb_build_object(
    'messages', COALESCE((SELECT jsonb_agg(jsonb_build_object('seq',e.seq,'type',e.type,'payload',e.payload) ORDER BY e.seq)
      FROM (SELECT seq,type,payload FROM events WHERE session_id=p_sid
        AND type IN ('user/message','llm/message','tool/result')
        AND (seq <= v13_last_user_seq(p_sid)
             OR ((payload->>'origin_user_seq')::bigint = v13_last_user_seq(p_sid)
                 AND public.v13_effect_context_event_current(session_id,seq)))
        ORDER BY seq DESC LIMIT 20) e),'[]'::jsonb),
    'derived', jsonb_build_object('message_count',(SELECT count(*) FROM events
      WHERE session_id=p_sid AND type IN ('user/message','llm/message','tool/result')
        AND (seq <= v13_last_user_seq(p_sid)
             OR ((payload->>'origin_user_seq')::bigint = v13_last_user_seq(p_sid)
                 AND public.v13_effect_context_event_current(session_id,seq))))),
    'tools', COALESCE((SELECT jsonb_agg(jsonb_build_object('name',name,'description',description,'kind',kind) ORDER BY name)
      FROM tools WHERE enabled),'[]'::jsonb));
$w4$;

CREATE OR REPLACE FUNCTION v13_parse(p_sid uuid) RETURNS jsonb LANGUAGE plpgsql AS $w4$
DECLARE v_env jsonb; v_snap jsonb; v_max int; v_cap int; v_failures int; v_res jsonb; v_remaining int;
BEGIN
  v_env := v13_judgment_envelope(p_sid);
  v_snap := v13_snap_of(v_env);
  SELECT count(*) INTO v_failures FROM events e
   WHERE e.session_id=p_sid AND e.type='resolve/failed'
     AND (e.payload->>'origin_user_seq')::bigint=v13_last_user_seq(p_sid)
     AND (e.source_effect_id IS NULL OR public.v13_effect_context_event_current(e.session_id,e.seq));
  v_cap := (v13_policy('resolve_retry')->>'cap')::int;
  IF v_failures >= v_cap THEN
    RETURN jsonb_build_object('snap',v_snap,'envelope',v_env,'abandon',true,'asked_batches',0,
      'asked_questions',0,'remaining',v_snap->'gap_count','failed',false);
  END IF;
  IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
    v_remaining := jsonb_array_length(v13_gap(v_env));
    RETURN jsonb_build_object('snap',v_snap,'envelope',v_env,'abandon',false,'asked_batches',0,
      'asked_questions',0,'remaining',v_remaining,'failed',false);
  END IF;
  v_max := (v13_policy('resolve_fast_path')->>'max_batches')::int;
  v_res := v13_resolve_judgments(v_env,v_max);
  RETURN jsonb_build_object('snap',v_snap,'envelope',v_env,'abandon',false,
    'asked_questions',v_res->'asked_questions','asked_batches',v_res->'asked_batches',
    'remaining',v_res->'remaining','failed',v_res->'failed');
END $w4$;
CREATE OR REPLACE FUNCTION v13_cap_answer_anchor(p_sid uuid, p_effect uuid)
RETURNS TABLE(anchor_seq bigint, cap_class text)
LANGUAGE sql
STABLE
AS $fn$
  WITH pred AS (
    SELECT e.origin_user_seq,
           (SELECT max(ev.seq) FROM events ev
             WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = e.session_id
               AND ev.source_effect_id = e.effect_id
               AND ev.type = 'effect_done') AS done_seq
      FROM effects e
     WHERE public.v13_effect_context_effect_current(e.effect_id) AND e.effect_id = p_effect
       AND e.session_id = p_sid
  ),
  hits AS (
    SELECT ev.seq AS anchor_seq,
           CASE h.request->>'interaction_kind'
             WHEN 'repair_cap' THEN 'repair'
             WHEN 'replan_cap' THEN 'replan'
             WHEN 'material_cap' THEN 'material'
           END AS cap_class
      FROM effects h
      JOIN events ev
        ON ev.session_id = h.session_id
       AND ev.source_effect_id = h.effect_id
       AND ev.type = 'human/responded'
       AND public.v13_effect_context_event_current(ev.session_id, ev.seq)
      JOIN pred p ON true
     WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = p_sid
       AND h.kind = 'human'
       AND h.status = 'succeeded'
       AND h.origin_user_seq = p.origin_user_seq
       AND h.request->>'interaction_kind' IN ('material_cap', 'repair_cap', 'replan_cap')
       AND p.done_seq IS NOT NULL
       AND ev.seq > p.done_seq
    UNION ALL
    SELECT (SELECT max(ev.seq) FROM events ev
             WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = h.session_id
               AND ev.source_effect_id = h.effect_id
               AND ev.type = 'effect_done') AS anchor_seq,
           CASE h.request->>'reason'
             WHEN 'repair_cap' THEN 'repair'
             WHEN 'replan_cap' THEN 'replan'
           END AS cap_class
      FROM effects h
      JOIN pred p ON true
     WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = p_sid
       AND h.kind = 'human'
       AND h.status = 'succeeded'
       AND h.origin_user_seq = p.origin_user_seq
       AND h.request->>'reason' IN ('repair_cap', 'replan_cap')
       AND NOT (h.request ? 'interaction_kind')
       AND p.done_seq IS NOT NULL
       AND (SELECT max(ev.seq) FROM events ev
             WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = h.session_id
               AND ev.source_effect_id = h.effect_id
               AND ev.type = 'effect_done') > p.done_seq
  ),
  ranked AS (
    SELECT cap_class, anchor_seq,
           count(*) OVER (PARTITION BY cap_class, anchor_seq) AS tie_n,
           min(anchor_seq) OVER (PARTITION BY cap_class) AS min_seq
      FROM hits
     WHERE anchor_seq IS NOT NULL
       AND cap_class IS NOT NULL
  )
  SELECT anchor_seq, cap_class
    FROM ranked
   WHERE anchor_seq = min_seq
     AND tie_n = 1;
$fn$;

CREATE OR REPLACE FUNCTION public.v13_cap_human_answered(p_sid uuid, p_pred uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE
 SET search_path TO 'pg_catalog', 'public'
AS $function$
  SELECT EXISTS (SELECT 1 FROM v13_cap_answer_anchor(p_sid, p_pred) a WHERE a.anchor_seq IS NOT NULL);
$function$;

CREATE OR REPLACE FUNCTION v13_tail_gap_cap_exempt(p_sid uuid, p_effect uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $fn$
  SELECT coalesce((
    SELECT e.result->>'result_kind' = 'progress'
       AND EXISTS (
         SELECT 1
           FROM v13_cap_answer_anchor(p_sid, p_effect) a
          WHERE a.cap_class IN ('repair', 'replan')
            AND (
              (a.cap_class = 'repair' AND EXISTS (
                 SELECT 1 FROM events sig
                  WHERE public.v13_effect_context_event_current(sig.session_id, sig.seq) AND sig.session_id = p_sid
                    AND sig.source_effect_id = e.effect_id
                    AND sig.type = 'repair/required'))
              OR (a.cap_class = 'replan' AND EXISTS (
                 SELECT 1 FROM events sig
                  WHERE public.v13_effect_context_event_current(sig.session_id, sig.seq) AND sig.session_id = p_sid
                    AND sig.source_effect_id = e.effect_id
                    AND sig.type = 'replan/required')))
            AND NOT EXISTS (
              SELECT 1 FROM effects o
               WHERE public.v13_effect_context_effect_current(o.effect_id) AND o.session_id = p_sid
                 AND o.origin_user_seq = e.origin_user_seq
                 AND o.effect_id IS DISTINCT FROM e.effect_id
                 AND o.kind = 'tool'
                 AND v13_is_harness_tool(o.tool_name, o.kind)
                 AND o.status = 'succeeded'
                 AND (SELECT max(ev.seq) FROM events ev
                       WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = o.session_id
                         AND ev.source_effect_id = o.effect_id
                         AND ev.type = 'effect_done')
                     > (SELECT max(ev.seq) FROM events ev
                         WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = e.session_id
                           AND ev.source_effect_id = e.effect_id
                           AND ev.type = 'effect_done')
                 AND (SELECT max(ev.seq) FROM events ev
                       WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = o.session_id
                         AND ev.source_effect_id = o.effect_id
                         AND ev.type = 'effect_done')
                     < a.anchor_seq)
            AND EXISTS (
              SELECT 1 FROM effects n
               WHERE public.v13_effect_context_effect_current(n.effect_id) AND n.session_id = p_sid
                 AND n.origin_user_seq = e.origin_user_seq
                 AND n.kind = 'tool'
                 AND v13_is_harness_tool(n.tool_name, n.kind)
                 AND v13_json_int_ok(n.request->'continuation_index', 2147483647)
                 AND (n.request->>'continuation_index')::int = 0
                 AND n.request->'logical_turn_id'
                     IS DISTINCT FROM e.request->'logical_turn_id'
                 AND EXISTS (
                   SELECT 1 FROM events ev
                    WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = n.session_id
                      AND ev.source_effect_id = n.effect_id
                      AND ev.seq > a.anchor_seq)))
      FROM effects e
     WHERE public.v13_effect_context_effect_current(e.effect_id) AND e.effect_id = p_effect
       AND e.session_id = p_sid
  ), false);
$fn$;

CREATE OR REPLACE FUNCTION public.v13_harness_tail_gap(p_sid uuid, p_keep uuid)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF EXISTS (
    SELECT 1 FROM effects e
     WHERE public.v13_effect_context_effect_current(e.effect_id) AND e.session_id = p_sid
       AND e.kind = 'tool'
       AND v13_is_harness_tool(e.tool_name, e.kind)
       AND e.origin_user_seq = v13_last_user_seq(p_sid)
       AND e.status = 'succeeded'
       AND e.effect_id IS DISTINCT FROM p_keep
       AND (
         (e.result->>'result_kind' = 'progress' AND EXISTS (
            SELECT 1 FROM events ev
             WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.source_effect_id = e.effect_id
               AND ev.type IN ('repair/required', 'replan/required')))
         OR e.result->>'result_kind' = 'wait')
       AND NOT EXISTS (
         SELECT 1 FROM effects n
          WHERE public.v13_effect_context_effect_current(n.effect_id) AND n.session_id = e.session_id
            AND n.kind = 'tool'
            AND v13_is_harness_tool(n.tool_name, n.kind)
            AND n.request->>'logical_turn_id' = e.request->>'logical_turn_id'
            AND v13_json_int_ok(n.request->'continuation_index', 2147483647)
            AND v13_json_int_ok(e.request->'continuation_index', 2147483647)
            AND (n.request->>'continuation_index')::int
                = (e.request->>'continuation_index')::int + 1)
       AND NOT v13_tail_gap_cap_exempt(p_sid, e.effect_id)) THEN
    RAISE EXCEPTION 'v13: harness tail gap';
  END IF;
END $function$;

CREATE OR REPLACE FUNCTION public.v13_triage_fold_reason(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
DECLARE
  v_name text; v_ver int; v_count int; v_action text;
BEGIN
  SELECT route_policy_name, route_policy_version INTO v_name, v_ver
    FROM sessions WHERE session_id = p_sid;
  IF (SELECT count(*) FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = p_sid AND type = 'repair/required') > 0
     AND NOT EXISTS (
       SELECT 1 FROM effects
        WHERE public.v13_effect_context_effect_current(effect_id) AND session_id = p_sid AND kind = 'human'
          AND origin_user_seq = v13_last_user_seq(p_sid)
          AND request = jsonb_build_object('reason', 'repair_cap')) THEN
    v_count := (SELECT count(*) FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = p_sid AND type = 'repair/required');
    v_action := v13_triage_band(v_name, v_ver, 'harness.repair_count', v_count);
    IF v_action IS NULL OR v_action = 'reject' THEN
      RETURN 'repair_cap';
    END IF;
  END IF;
  IF (SELECT count(*) FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = p_sid AND type = 'replan/required') > 0
     AND NOT EXISTS (
       SELECT 1 FROM effects
        WHERE public.v13_effect_context_effect_current(effect_id) AND session_id = p_sid AND kind = 'human'
          AND origin_user_seq = v13_last_user_seq(p_sid)
          AND request = jsonb_build_object('reason', 'replan_cap')) THEN
    v_count := (SELECT count(*) FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = p_sid AND type = 'replan/required');
    v_action := v13_triage_band(v_name, v_ver, 'harness.replan_count', v_count);
    IF v_action IS NULL OR v_action = 'reject' THEN
      RETURN 'replan_cap';
    END IF;
  END IF;
  RETURN NULL;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_triage_block_explore_spawn(p_sid uuid) RETURNS void
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF EXISTS (
    SELECT 1 FROM events tc
    JOIN effects ef ON ef.effect_id = tc.source_effect_id
     WHERE public.v13_effect_context_event_current(tc.session_id, tc.seq) AND tc.session_id = p_sid AND tc.type = 'tool/call'
       AND tc.seq > v13_last_user_seq(p_sid)
       AND ef.request->'route'->>'reason' = 'explore'
       AND NOT EXISTS (
         SELECT 1 FROM events c
          WHERE c.session_id = p_sid AND c.type = 'child-created'
            AND c.payload->>'tool_call_id' = tc.payload->>'id')) THEN
    RAISE EXCEPTION 'v13: explore spawn';
  END IF;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_closeout(p_sid uuid, p_outcome text, p_reason text, p_attempts_exhausted boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_st text; v_n int; v_seal jsonb; v_type text; v_escape boolean;
  v_end jsonb; v_hash text; v_receipt jsonb; v_ous bigint;
  v_hashes jsonb; v_repair jsonb; v_replan jsonb; v_material jsonb;
  v_children jsonb;
  v_wake jsonb; v_appr jsonb; v_owed boolean; v_pred uuid; v_prow effects;
BEGIN
  IF p_outcome NOT IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: closeout outcome %', p_outcome;
  END IF;
  IF p_reason IS NULL OR p_reason !~ '^[A-Za-z0-9_./:-]+$' OR length(p_reason) > 128 THEN
    RAISE EXCEPTION 'v13: closeout precondition reason';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  v_type := 'session/' || v_st;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    SELECT count(*) INTO v_n FROM events WHERE session_id = p_sid AND type = v_type;
    IF v_n = 0 THEN
      RAISE EXCEPTION 'v13: closeout missing seal';
    ELSIF v_n > 1 THEN
      RAISE EXCEPTION 'v13: closeout duplicate seal';
    END IF;
    IF p_outcome IS DISTINCT FROM v_st THEN
      RAISE EXCEPTION 'v13: closeout outcome conflict';
    END IF;
    SELECT payload INTO v_seal FROM events WHERE session_id = p_sid AND type = v_type;
    RETURN v_seal;
  END IF;
  IF EXISTS (
    SELECT 1 FROM sessions
     WHERE parent_session_id = p_sid
       AND status NOT IN ('completed', 'failed', 'cancelled')) THEN
    RAISE EXCEPTION 'v13: closeout precondition children_open';
  END IF;
  IF EXISTS (
    SELECT 1 FROM effects
     WHERE session_id = p_sid AND status IN ('ready', 'claimed') AND kind <> 'human') THEN
    RAISE EXCEPTION 'v13: closeout precondition active';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'unknown') THEN
    RAISE EXCEPTION 'v13: closeout precondition unknown';
  END IF;
  IF v13_pending_human(p_sid) THEN
    RAISE EXCEPTION 'v13: closeout precondition pending human';
  END IF;
  IF v_st = 'blocked_unknown' THEN
    RAISE EXCEPTION 'v13: closeout precondition blocked_unknown';
  END IF;
  v_ous := v13_last_user_seq(p_sid);
  IF p_outcome IN ('completed', 'failed') AND v_ous < 0 THEN
    RAISE EXCEPTION 'v13: closeout precondition origin_user_seq';
  END IF;
  SELECT coalesce(jsonb_agg(h ORDER BY h), '[]'::jsonb) INTO v_hashes
    FROM (
      SELECT DISTINCT a.content_hash AS h
        FROM artifacts a
        JOIN effects e ON e.effect_id = a.produced_by
       WHERE e.session_id = p_sid AND e.status = 'succeeded'
         AND a.content_hash ~ '^[0-9a-f]{64}$') q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_repair
    FROM (
      SELECT DISTINCT ev.source_effect_id::text AS id
        FROM events ev
       WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = p_sid AND ev.type = 'repair/required'
         AND ev.source_effect_id IS NOT NULL) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_replan
    FROM (
      SELECT DISTINCT ev.source_effect_id::text AS id
        FROM events ev
       WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.session_id = p_sid AND ev.type = 'replan/required'
         AND ev.source_effect_id IS NOT NULL) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_material
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE public.v13_effect_context_effect_current(e.effect_id) AND e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND v13_harness_request_ok(e.request)
         AND (e.result->>'result_kind' = 'finish'
              OR (e.result->>'result_kind' = 'progress' AND NOT EXISTS (
                    SELECT 1 FROM events ev
                     WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.source_effect_id = e.effect_id
                       AND ev.type IN ('repair/required', 'replan/required'))))
         AND NOT EXISTS (
           SELECT 1 FROM events ev
            WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.source_effect_id = e.effect_id AND ev.type = 'turn/material_spent')) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_wake
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE public.v13_effect_context_effect_current(e.effect_id) AND e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND e.result->>'result_kind' = 'wait'
         AND e.result->>'wait_reason' IN ('evidence', 'quota')
         AND NOT EXISTS (
           SELECT 1 FROM events ev
            WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.source_effect_id = e.effect_id AND ev.type = 'wake/satisfied')) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_appr
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE public.v13_effect_context_effect_current(e.effect_id) AND e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND e.result->>'result_kind' = 'wait'
         AND e.result->>'wait_reason' = 'approval'
         AND NOT EXISTS (
           SELECT 1 FROM effects h
            WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = e.session_id AND h.kind = 'human'
              AND h.status = 'succeeded'
              AND h.request->>'interaction_ref' = e.result->>'interaction_id')) q;
  v_owed := false;
  v_pred := (SELECT e.effect_id FROM effects e
      WHERE e.session_id = p_sid AND e.kind = 'tool'
        AND v13_is_harness_tool(e.tool_name, e.kind)
        AND e.origin_user_seq = v13_last_user_seq(p_sid)
        AND v13_harness_request_ok(e.request)
        AND public.v13_effect_context_effect_current(e.effect_id)
      ORDER BY (SELECT max(ev.seq) FROM events ev
                 WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id
                   AND public.v13_effect_context_event_current(ev.session_id, ev.seq)) DESC NULLS LAST,
               e.created_at DESC, e.effect_id DESC LIMIT 1);
  IF v_pred IS NOT NULL THEN
    SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
    IF v_prow.status = 'succeeded' AND (
         (v_prow.result->>'result_kind' = 'progress' AND EXISTS (
            SELECT 1 FROM events ev
             WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.source_effect_id = v_pred
               AND ev.type IN ('repair/required', 'replan/required')))
         OR (v_prow.result->>'result_kind' = 'wait'
             AND v_prow.result->>'wait_reason' = 'approval'
             AND EXISTS (
               SELECT 1 FROM effects h
                WHERE public.v13_effect_context_effect_current(h.effect_id) AND h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
                  AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id'))
         OR (v_prow.result->>'result_kind' = 'wait'
             AND v_prow.result->>'wait_reason' IN ('evidence', 'quota')
             AND EXISTS (
               SELECT 1 FROM events ev
                WHERE public.v13_effect_context_event_current(ev.session_id, ev.seq) AND ev.source_effect_id = v_pred AND ev.type = 'wake/satisfied')))
       AND NOT EXISTS (
         SELECT 1 FROM effects n
          WHERE public.v13_effect_context_effect_current(n.effect_id) AND n.session_id = p_sid AND n.kind = 'tool'
            AND v13_is_harness_tool(n.tool_name, n.kind)
            AND n.request->>'logical_turn_id' = v_prow.request->>'logical_turn_id'
            AND (n.request->>'continuation_index')::int
                = (v_prow.request->>'continuation_index')::int + 1) THEN
      v_owed := true;
    END IF;
  END IF;
  v_escape := p_outcome = 'cancelled'
    OR (p_outcome = 'failed' AND p_reason IN (
         'budget_exhausted', 'resolve_budget', 'judge_attempts', 'context_refresh',
         'harness_attempts', 'approval_exhausted'));
  IF NOT v_escape THEN
    IF v_material <> '[]'::jsonb THEN
      RAISE EXCEPTION 'v13: closeout unpaid material';
    ELSIF v_wake <> '[]'::jsonb THEN
      RAISE EXCEPTION 'v13: closeout wake pending';
    ELSIF v_appr <> '[]'::jsonb THEN
      RAISE EXCEPTION 'v13: closeout approval pending';
    ELSIF v_owed THEN
      RAISE EXCEPTION 'v13: closeout continuation owed';
    END IF;
  END IF;
  v_end := jsonb_build_object('delivered', p_outcome = 'completed', 'reason', p_reason);
  IF p_attempts_exhausted THEN
    v_end := v_end || jsonb_build_object('attempts_exhausted', true);
  END IF;
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end', v_end);
  v_hash := v13_state_hash(p_sid);
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'session_id', session_id, 'status', status) ORDER BY session_id), '[]'::jsonb)
    INTO v_children
    FROM sessions
   WHERE parent_session_id = p_sid;
  v_receipt := jsonb_build_object(
    'schema_version', 1,
    'origin_user_seq', v_ous,
    'spent', jsonb_build_object(
      'turn_no', (SELECT turn_no FROM sessions WHERE session_id = p_sid),
      'cycle_no', v13_cycle_no(p_sid),
      'max_cycles', (v13_policy('turn_budget')->>'max_cycles')::int,
      'material_count', (SELECT count(*) FROM events
                          WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = p_sid AND type = 'turn/material_spent')),
    'produced_hashes', v_hashes,
    'children', v_children,
    'unconsumed', jsonb_build_object(
      'repair_effect_ids', v_repair,
      'replan_effect_ids', v_replan,
      'material_effect_ids', v_material,
      'wake_pending_effect_ids', v_wake,
      'approval_pending_effect_ids', v_appr),
    'state_hash', v_hash,
    'turn_end_reason', p_reason);
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'session/' || p_outcome, v_receipt);
  UPDATE sessions SET status = p_outcome WHERE session_id = p_sid;
  RETURN v_receipt;
END $function$;

CREATE OR REPLACE FUNCTION public.v13_recover_idle()
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_sid uuid; v_fp text; v_nudged int := 0; v_pending uuid[] := '{}'; v_st text;
BEGIN
  FOR v_sid IN
    SELECT s.session_id
      FROM sessions s
     WHERE s.status IN ('ready', 'waiting')
       AND NOT EXISTS (
         SELECT 1 FROM effects e
          WHERE e.session_id = s.session_id
            AND e.status IN ('ready', 'claimed', 'unknown'))
     ORDER BY s.session_id
     FOR UPDATE OF s SKIP LOCKED
  LOOP
    SELECT status INTO v_st FROM sessions WHERE session_id = v_sid;
    IF v_st NOT IN ('ready', 'waiting')
       OR EXISTS (
         SELECT 1 FROM effects e
          WHERE e.session_id = v_sid
            AND e.status IN ('ready', 'claimed', 'unknown')) THEN
      CONTINUE;
    END IF;
    IF v13_triage_hold_blocks_recover(v_sid) THEN
      CONTINUE;
    END IF;
    IF public.v13_goal_lifecycle(v_sid) = 'stopped' THEN
      CONTINUE;
    END IF;
    IF EXISTS (SELECT 1 FROM sessions c WHERE c.parent_session_id = v_sid)
       AND NOT v13_direct_children_open(v_sid) THEN
      SELECT encode(digest((
        SELECT jsonb_agg(jsonb_build_array(c.session_id::text, c.status) ORDER BY c.session_id)
          FROM sessions c WHERE c.parent_session_id = v_sid)::text, 'sha256'), 'hex')
        INTO v_fp;
      v_nudged := v_nudged + v13_insert_nudge(v_sid, 'children_terminal', v_fp);
    END IF;
    IF EXISTS (SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = v_sid AND type = 'repair/required') THEN
      SELECT jsonb_agg(seq ORDER BY seq)::text INTO v_fp
        FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = v_sid AND type = 'repair/required';
      v_nudged := v_nudged + v13_insert_nudge(v_sid, 'repair', v_fp);
    END IF;
    IF EXISTS (SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = v_sid AND type = 'replan/required') THEN
      SELECT jsonb_agg(seq ORDER BY seq)::text INTO v_fp
        FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = v_sid AND type = 'replan/required';
      v_nudged := v_nudged + v13_insert_nudge(v_sid, 'replan', v_fp);
    END IF;
    IF (EXISTS (SELECT 1 FROM sessions c WHERE c.parent_session_id = v_sid)
        AND NOT v13_direct_children_open(v_sid))
       OR EXISTS (SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = v_sid AND type = 'repair/required')
       OR EXISTS (SELECT 1 FROM events WHERE public.v13_effect_context_event_current(events.session_id, events.seq) AND session_id = v_sid AND type = 'replan/required') THEN
      v_pending := v_pending || v_sid;
    END IF;
  END LOOP;
  RETURN jsonb_build_object(
    'pending', coalesce((SELECT jsonb_agg(x ORDER BY x) FROM unnest(v_pending) x), '[]'::jsonb),
    'nudged', v_nudged);
END
$function$;

CREATE OR REPLACE FUNCTION public.v13_scheduler_hint(p_sid uuid) RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_st text;
  v_requested integer;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT status INTO v_st
    FROM public.sessions
   WHERE session_id = p_sid;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN 'dont_notify';
  END IF;
  IF public.v13_unconsumed_cancel(p_sid) THEN
    IF EXISTS (
      SELECT 1 FROM public.effects
       WHERE session_id = p_sid
         AND status IN ('claimed', 'unknown')) THEN
      RETURN 'wait';
    END IF;
    RETURN 'run_now';
  END IF;
  IF public.v13_goal_lifecycle(p_sid) = 'stopped' THEN
    RETURN 'dont_notify';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.effects
     WHERE session_id = p_sid
       AND status IN ('ready', 'claimed', 'unknown')) THEN
    RETURN 'wait';
  ELSIF public.v13_pending_human(p_sid) THEN
    RETURN 'wait';
  ELSIF public.v13_triage_duty() = 0 THEN
    RETURN 'wait';
  ELSIF NOT public.v13_should_run(p_sid) THEN
    RETURN 'wait';
  END IF;
  SELECT count(*)::integer INTO v_requested
    FROM public.events AS e
   WHERE public.v13_effect_context_event_current(e.session_id, e.seq) AND e.session_id = p_sid
     AND e.type = 'tool/call'
     AND e.seq > public.v13_last_user_seq(p_sid)
     AND NOT EXISTS (
         SELECT 1 FROM public.events AS c
        WHERE c.session_id = p_sid
          AND c.type = 'child-created'
          AND c.payload->>'tool_call_id' = e.payload->>'id');
  IF v_requested > 0
     AND NOT public.v13_spawn_budget_snapshot(p_sid, v_requested) THEN
    RETURN 'wait';
  END IF;
  RETURN 'run_now';
END
$function$;

-- Canonical state is reached by recall reads and spawn_owner's fork prefix.
GRANT EXECUTE ON FUNCTION public.v13_effect_context_event_current(uuid,bigint)
  TO v13_recall, v13_spawn_owner;
COMMIT;
-- STAGE42_CONSUMER_OVERLAY_END
