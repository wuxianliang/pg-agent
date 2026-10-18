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
