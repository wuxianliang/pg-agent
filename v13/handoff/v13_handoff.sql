-- v13 handoff (stage 25). Immutable receipt event. No new tables.
BEGIN;

DO $handoff_base$
DECLARE
  v_rows text;
  v_hash text;
BEGIN
  SELECT string_agg(session_id::text || '/' || seq::text, ', ' ORDER BY session_id, seq)
    INTO v_rows
    FROM public.events
   WHERE type = 'control/handoff';
  IF v_rows IS NOT NULL THEN
    RAISE EXCEPTION 'v13: handoff baseline %', v_rows;
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.v13_policies WHERE name = 'handoff_policy'
  ) THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
  v_hash := pg_get_functiondef('public.v13_state_hash(uuid)'::regprocedure);
  IF position(
       'type NOT IN (''session/completed'', ''session/failed'', ''session/cancelled'')'
       IN v_hash) = 0
     OR position('control/handoff' IN v_hash) > 0 THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM pg_attribute
     WHERE attrelid = 'public.events'::regclass
       AND attname = 'payload_hash'
       AND NOT attisdropped
  ) THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM pg_trigger
     WHERE tgrelid = 'public.events'::regclass
       AND NOT tgisinternal
       AND pg_get_triggerdef(oid) LIKE '%control/handoff%'
  ) THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
  IF to_regprocedure('public.digest(text,text)') IS NULL
     OR to_regprocedure('pg_catalog.gen_random_uuid()') IS NULL
     OR to_regprocedure('public.v13_json_int_ok(jsonb,numeric)') IS NULL THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
END
$handoff_base$;

DO $handoff_role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_handoff_owner') THEN
    CREATE ROLE v13_handoff_owner
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ELSIF EXISTS (
    SELECT 1
      FROM pg_roles
     WHERE rolname = 'v13_handoff_owner'
       AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
            OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1
      FROM pg_auth_members m
      JOIN pg_roles r ON r.oid = m.roleid
     WHERE r.rolname = 'v13_handoff_owner'
  ) THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
  IF NOT pg_catalog.has_schema_privilege('v13_handoff_owner', 'public', 'CREATE') THEN
    GRANT CREATE ON SCHEMA public TO v13_handoff_owner;
  END IF;
  IF NOT pg_catalog.has_schema_privilege('v13_handoff_owner', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
  GRANT CREATE ON SCHEMA public TO v13_handoff_owner;
END
$handoff_role$;

GRANT USAGE ON SCHEMA public TO v13_handoff_owner;
GRANT SELECT, UPDATE ON public.sessions TO v13_handoff_owner;
GRANT SELECT, INSERT ON public.events TO v13_handoff_owner;
GRANT SELECT ON public.effects TO v13_handoff_owner;
GRANT SELECT ON public.v13_policies TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.v13_append_event(uuid, uuid, text, jsonb, uuid) TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.v13_assert_unknown_wall(uuid) TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.v13_json_keys(jsonb) TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.v13_json_int_ok(jsonb, numeric) TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.v13_canonical_uuid(text) TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.digest(text, text) TO v13_handoff_owner;
GRANT EXECUTE ON FUNCTION pg_catalog.gen_random_uuid() TO v13_handoff_owner;

DO $handoff_route_pol$
BEGIN
  IF NOT pg_catalog.has_table_privilege('v13_route', 'public.v13_policies', 'SELECT') THEN
    GRANT SELECT ON public.v13_policies TO v13_route;
  END IF;
  IF NOT pg_catalog.has_table_privilege('v13_route', 'public.v13_policies', 'SELECT') THEN
    RAISE EXCEPTION 'v13: handoff baseline';
  END IF;
END
$handoff_route_pol$;

INSERT INTO public.v13_policies (name, version, value, active)
VALUES ('handoff_policy', 1, '{"schema_version":1,"enabled":true}'::jsonb, true);

CREATE FUNCTION public.v13_transcript_hash(p_sid uuid, p_up_to_seq bigint)
RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $handoff_hash$
DECLARE
  v_hash text;
BEGIN
  IF p_up_to_seq IS NULL OR p_up_to_seq < 0 THEN
    RAISE EXCEPTION 'v13: handoff watermark';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid
  ) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT pg_catalog.encode(public.digest(
    pg_catalog.jsonb_build_array(
      'v1',
      p_sid::text,
      pg_catalog.to_jsonb(p_up_to_seq),
      coalesce((
        SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(
                 e.seq, e.type, e.payload_hash,
                 coalesce(e.source_effect_id::text, ''))
               ORDER BY e.seq)
          FROM public.events e
         WHERE e.session_id = p_sid
           AND e.seq <= p_up_to_seq
           AND e.type <> 'control/handoff'
      ), '[]'::jsonb)
    )::text,
    'sha256'), 'hex')
    INTO v_hash;
  RETURN v_hash;
END
$handoff_hash$;

GRANT EXECUTE ON FUNCTION public.v13_transcript_hash(uuid, bigint) TO v13_handoff_owner;

CREATE FUNCTION public.v13_handoff_emit(p_sid uuid, p_payload jsonb)
RETURNS bigint
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $handoff_emit$
DECLARE
  v_n int;
  v_pol jsonb;
BEGIN
  SELECT count(*)
    INTO v_n
    FROM public.v13_policies
   WHERE name = 'handoff_policy'
     AND active;
  IF v_n <> 1 THEN
    RAISE 'v13: handoff policy';
  END IF;
  SELECT value
    INTO v_pol
    FROM public.v13_policies
   WHERE name = 'handoff_policy'
     AND active;
  IF pg_catalog.jsonb_typeof(v_pol) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_pol) IS DISTINCT FROM
        ARRAY['enabled', 'schema_version']::text[]
     OR NOT public.v13_json_int_ok(v_pol -> 'schema_version', 1)
     OR (v_pol ->> 'schema_version') IS DISTINCT FROM '1'
     OR pg_catalog.jsonb_typeof(v_pol -> 'enabled') IS DISTINCT FROM 'boolean' THEN
    RAISE 'v13: handoff policy';
  END IF;
  IF (v_pol ->> 'enabled') IS DISTINCT FROM 'true' THEN
    RAISE 'v13: handoff disabled';
  END IF;
  RETURN public.v13_append_event(
    p_sid,
    pg_catalog.gen_random_uuid(),
    'control/handoff',
    p_payload,
    NULL);
END
$handoff_emit$;

ALTER FUNCTION public.v13_handoff_emit(uuid, jsonb) OWNER TO v13_handoff_owner;

CREATE FUNCTION public.v13_handoff_event_guard()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $handoff_guard$
DECLARE
  v_up jsonb;
  v_txt text;
  v_num numeric;
  v_seq bigint;
  v_hash text;
BEGIN
  IF current_user <> 'v13_handoff_owner' THEN
    RAISE EXCEPTION 'v13: handoff writer';
  END IF;
  IF NEW.source_effect_id IS NOT NULL THEN
    RAISE EXCEPTION 'v13: handoff source';
  END IF;
  IF pg_catalog.jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(NEW.payload) IS DISTINCT FROM
        ARRAY['delivery_id', 'schema_version', 'transcript_hash', 'up_to_seq']::text[] THEN
    RAISE EXCEPTION 'v13: handoff keys';
  END IF;
  IF NOT public.v13_json_int_ok(NEW.payload -> 'schema_version', 1)
     OR (NEW.payload ->> 'schema_version') IS DISTINCT FROM '1' THEN
    RAISE EXCEPTION 'v13: handoff schema';
  END IF;
  IF NOT public.v13_canonical_uuid(NEW.payload ->> 'delivery_id') THEN
    RAISE EXCEPTION 'v13: handoff delivery';
  END IF;
  IF (NEW.payload ->> 'transcript_hash') !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: handoff digest';
  END IF;
  v_up := NEW.payload -> 'up_to_seq';
  v_txt := v_up::text;
  IF pg_catalog.jsonb_typeof(v_up) IS DISTINCT FROM 'number'
     OR v_txt IS NULL
     OR pg_catalog.length(v_txt) > 40
     OR v_txt !~ '^[0-9]+(\.[0-9]+)?$' THEN
    RAISE EXCEPTION 'v13: handoff watermark';
  END IF;
  v_num := v_txt::numeric;
  IF v_num <> trunc(v_num)
     OR v_num < 0
     OR v_num > 9223372036854775807::numeric THEN
    RAISE EXCEPTION 'v13: handoff watermark';
  END IF;
  IF v_txt IS DISTINCT FROM trunc(v_num)::bigint::text THEN
    RAISE EXCEPTION 'v13: handoff watermark';
  END IF;
  v_seq := trunc(v_num)::bigint;
  IF NOT EXISTS (
    SELECT 1
      FROM public.events e
     WHERE e.session_id = NEW.session_id
       AND e.seq = v_seq
       AND e.type <> 'control/handoff'
  ) THEN
    RAISE EXCEPTION 'v13: handoff watermark';
  END IF;
  v_hash := public.v13_transcript_hash(NEW.session_id, v_seq);
  IF (NEW.payload ->> 'transcript_hash') IS DISTINCT FROM v_hash THEN
    RAISE EXCEPTION 'v13: handoff hash';
  END IF;
  RETURN NEW;
END
$handoff_guard$;

CREATE TRIGGER trg_handoff_guard
  BEFORE INSERT ON public.events
  FOR EACH ROW
  WHEN (NEW.type = 'control/handoff')
  EXECUTE FUNCTION public.v13_handoff_event_guard();

CREATE UNIQUE INDEX ux_events_handoff_delivery
  ON public.events ((payload ->> 'delivery_id'))
  WHERE type = 'control/handoff';

CREATE UNIQUE INDEX ux_events_handoff_snapshot
  ON public.events (session_id, (payload ->> 'up_to_seq'), (payload ->> 'transcript_hash'))
  WHERE type = 'control/handoff';

CREATE FUNCTION public.v13_extract_handoff(
  p_actor uuid,
  p_sid uuid,
  p_up_to_seq bigint DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $handoff_extract$
DECLARE
  v_seq bigint;
  v_hash text;
  v_prev jsonb;
  v_n int;
  v_pol jsonb;
  v_delivery uuid;
  v_payload jsonb;
BEGIN
  IF NOT public.v13_control_authorized(p_actor, p_sid) THEN
    RAISE 'v13: session not found';
  END IF;
  PERFORM 1
     FROM public.sessions
    WHERE session_id = p_sid
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE 'v13: session not found';
  END IF;
  IF NOT public.v13_control_authorized(p_actor, p_sid) THEN
    RAISE 'v13: session not found';
  END IF;
  IF p_up_to_seq IS NULL THEN
    SELECT max(e.seq)
      INTO v_seq
      FROM public.events e
     WHERE e.session_id = p_sid
       AND e.type <> 'control/handoff';
    IF v_seq IS NULL THEN
      RAISE 'v13: handoff empty';
    END IF;
  ELSIF NOT EXISTS (
    SELECT 1
      FROM public.events e
     WHERE e.session_id = p_sid
       AND e.seq = p_up_to_seq
       AND e.type <> 'control/handoff'
  ) THEN
    RAISE 'v13: handoff watermark';
  ELSE
    v_seq := p_up_to_seq;
  END IF;
  v_hash := public.v13_transcript_hash(p_sid, v_seq);
  SELECT e.payload
    INTO v_prev
    FROM public.events e
   WHERE e.session_id = p_sid
     AND e.type = 'control/handoff'
     AND e.payload ->> 'up_to_seq' = v_seq::text
     AND e.payload ->> 'transcript_hash' = v_hash
   ORDER BY e.seq
   LIMIT 1;
  IF FOUND THEN
    RETURN v_prev;
  END IF;
  SELECT count(*)
    INTO v_n
    FROM public.v13_policies
   WHERE name = 'handoff_policy'
     AND active;
  IF v_n <> 1 THEN
    RAISE 'v13: handoff policy';
  END IF;
  SELECT value
    INTO v_pol
    FROM public.v13_policies
   WHERE name = 'handoff_policy'
     AND active;
  IF pg_catalog.jsonb_typeof(v_pol) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_pol) IS DISTINCT FROM
        ARRAY['enabled', 'schema_version']::text[]
     OR NOT public.v13_json_int_ok(v_pol -> 'schema_version', 1)
     OR (v_pol ->> 'schema_version') IS DISTINCT FROM '1'
     OR pg_catalog.jsonb_typeof(v_pol -> 'enabled') IS DISTINCT FROM 'boolean' THEN
    RAISE 'v13: handoff policy';
  END IF;
  IF (v_pol ->> 'enabled') IS DISTINCT FROM 'true' THEN
    RAISE 'v13: handoff disabled';
  END IF;
  v_delivery := pg_catalog.gen_random_uuid();
  v_payload := pg_catalog.jsonb_build_object(
    'schema_version', 1,
    'delivery_id', v_delivery::text,
    'transcript_hash', v_hash,
    'up_to_seq', pg_catalog.to_jsonb(v_seq));
  PERFORM public.v13_handoff_emit(p_sid, v_payload);
  RETURN v_payload;
END
$handoff_extract$;

REVOKE EXECUTE ON FUNCTION public.v13_transcript_hash(uuid, bigint) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_handoff_emit(uuid, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_handoff_event_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_extract_handoff(uuid, uuid, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_transcript_hash(uuid, bigint) TO v13_route, v13_handoff_owner;
GRANT EXECUTE ON FUNCTION public.v13_handoff_emit(uuid, jsonb) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_extract_handoff(uuid, uuid, bigint) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_handoff_event_guard() TO v13_route, v13_handoff_owner;

DO $handoff_install$
DECLARE
  v_sig text;
  v_oid oid;
  v_ok boolean;
  v_n int;
BEGIN
  IF to_regprocedure('digest(text,text)') IS NULL
     OR to_regprocedure('pg_catalog.gen_random_uuid()') IS NULL
     OR to_regprocedure('public.digest(text,text)') IS NULL THEN
    RAISE EXCEPTION 'v13: handoff install digest';
  END IF;
  FOREACH v_sig IN ARRAY ARRAY[
    'public.v13_append_event(uuid,uuid,text,jsonb,uuid)',
    'public.v13_assert_unknown_wall(uuid)',
    'public.v13_json_keys(jsonb)',
    'public.v13_json_int_ok(jsonb,numeric)',
    'public.v13_canonical_uuid(text)',
    'public.v13_transcript_hash(uuid,bigint)',
    'public.digest(text,text)',
    'pg_catalog.gen_random_uuid()'
  ]
  LOOP
    v_oid := to_regprocedure(v_sig);
    IF v_oid IS NULL THEN
      RAISE EXCEPTION 'v13: handoff install missing %', v_sig;
    END IF;
    SELECT EXISTS (
      SELECT 1
        FROM pg_proc p,
             aclexplode(coalesce(p.proacl, pg_catalog.acldefault('f', p.proowner))) a
       WHERE p.oid = v_oid
         AND a.grantee = 'v13_handoff_owner'::regrole
         AND a.privilege_type = 'EXECUTE'
    ) INTO v_ok;
    IF NOT v_ok THEN
      RAISE EXCEPTION 'v13: handoff install execute %', v_sig;
    END IF;
  END LOOP;
  IF NOT EXISTS (
    SELECT 1
      FROM pg_namespace n, aclexplode(n.nspacl) a
     WHERE n.nspname = 'public'
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'USAGE'
  ) OR NOT EXISTS (
    SELECT 1
      FROM pg_namespace n, aclexplode(n.nspacl) a
     WHERE n.nspname = 'public'
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'CREATE'
  ) THEN
    RAISE EXCEPTION 'v13: handoff install schema';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM pg_class c,
           aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
     WHERE c.oid = 'public.sessions'::regclass
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'SELECT'
  ) OR NOT EXISTS (
    SELECT 1
      FROM pg_class c,
           aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
     WHERE c.oid = 'public.sessions'::regclass
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'UPDATE'
  ) OR NOT EXISTS (
    SELECT 1
      FROM pg_class c,
           aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
     WHERE c.oid = 'public.events'::regclass
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'SELECT'
  ) OR NOT EXISTS (
    SELECT 1
      FROM pg_class c,
           aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
     WHERE c.oid = 'public.events'::regclass
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'INSERT'
  ) OR NOT EXISTS (
    SELECT 1
      FROM pg_class c,
           aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
     WHERE c.oid = 'public.effects'::regclass
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'SELECT'
  ) OR NOT EXISTS (
    SELECT 1
      FROM pg_class c,
           aclexplode(coalesce(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
     WHERE c.oid = 'public.v13_policies'::regclass
       AND a.grantee = 'v13_handoff_owner'::regrole
       AND a.privilege_type = 'SELECT'
  ) THEN
    RAISE EXCEPTION 'v13: handoff install table';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM pg_proc
     WHERE oid = 'public.v13_handoff_emit(uuid,jsonb)'::regprocedure
       AND prosecdef
       AND proowner = 'v13_handoff_owner'::regrole
       AND proconfig::text LIKE '%search_path=pg_catalog, public%'
  ) THEN
    RAISE EXCEPTION 'v13: handoff install emit attr';
  END IF;
  SELECT count(*)
    INTO v_n
    FROM pg_proc
   WHERE oid IN (
           'public.v13_transcript_hash(uuid,bigint)'::regprocedure,
           'public.v13_handoff_event_guard()'::regprocedure,
           'public.v13_extract_handoff(uuid,uuid,bigint)'::regprocedure)
     AND NOT prosecdef
     AND proconfig::text LIKE '%search_path=pg_catalog, public%';
  IF v_n <> 3 THEN
    RAISE EXCEPTION 'v13: handoff install attr';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM pg_proc
     WHERE oid = 'public.v13_handoff_emit(uuid,jsonb)'::regprocedure
       AND proconfig::text LIKE '%search_path=pg_catalog, public%'
  ) THEN
    RAISE EXCEPTION 'v13: handoff install search_path';
  END IF;
END
$handoff_install$;

COMMENT ON FUNCTION public.v13_transcript_hash(uuid, bigint) IS
  'stage 25: prefix transcript hash; receipts excluded; negative cutoff rejected';
COMMENT ON FUNCTION public.v13_handoff_emit(uuid, jsonb) IS
  'stage 25: DEFINER single writer; policy gate before append; trusted route helper';
COMMENT ON FUNCTION public.v13_handoff_event_guard() IS
  'stage 25: INVOKER guard; writer, source, keys, schema, delivery, digest, watermark, hash';
COMMENT ON FUNCTION public.v13_extract_handoff(uuid, uuid, bigint) IS
  'stage 25: authorized extract; identity readback before policy';

COMMIT;
