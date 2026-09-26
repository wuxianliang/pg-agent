BEGIN;

CREATE OR REPLACE FUNCTION public.v13_tools_catalog_frozen()
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  r record; v_handler text; v_cat jsonb := '[]'; v_entry jsonb;
  v_n int; v_oid oid; v_vol "char"; v_ret oid; v_nsp text;
  v_prosrc text; v_digest text;
  v_proname text; v_arglist text; v_qual text; v_bind text; v_exempt boolean;
BEGIN
  FOR r IN SELECT name, kind, handler, param_spec, enabled
             FROM tools ORDER BY name LOOP
    v_handler := r.handler;
    v_digest := NULL;
    IF r.kind = 'sql' AND r.enabled THEN
      SELECT count(*) INTO v_n FROM pg_proc p
       WHERE p.proname = r.handler
         AND oidvectortypes(p.proargtypes) = 'uuid, jsonb';
      IF v_n = 0 THEN
        RAISE EXCEPTION
          'v13: sql tool % handler % not found (signature (uuid,jsonb)->jsonb)',
          r.name, r.handler;
      ELSIF v_n > 1 THEN
        RAISE EXCEPTION
          'v13: sql tool % handler % ambiguous across schemas (%)',
          r.name, r.handler, v_n;
      END IF;
      SELECT p.oid, p.provolatile, p.prorettype, n.nspname, p.prosrc
        INTO v_oid, v_vol, v_ret, v_nsp, v_prosrc
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
       WHERE p.proname = r.handler
         AND oidvectortypes(p.proargtypes) = 'uuid, jsonb';
      IF v_vol NOT IN ('i','s') THEN
        v_exempt := false;
        SELECT proname INTO v_proname FROM pg_proc WHERE oid = v_oid;
        IF strpos(v_handler, '.') = 0 AND v_handler = v_proname THEN
          v_arglist := substring(v_oid::regprocedure::text FROM '\(.*\)$');
          v_qual := quote_ident(v_nsp) || '.' || quote_ident(v_proname) || v_arglist;
          v_bind := v_handler || v_arglist;
          IF to_regprocedure(v_qual) IS NOT DISTINCT FROM v_oid
             AND public.v13_named_sql_writer(v_handler) IS NOT NULL
             AND to_regprocedure(v_bind) IS NOT DISTINCT FROM v_oid
             AND public.v13_spawn_writer_ok(v_handler) IS TRUE THEN
            v_exempt := true;
          END IF;
        END IF;
        IF NOT v_exempt THEN
          RAISE EXCEPTION
            'v13: sql tool % handler % is VOLATILE (need IMMUTABLE/STABLE)',
            r.name, r.handler;
        END IF;
      END IF;
      IF v_ret <> 'jsonb'::regtype THEN
        RAISE EXCEPTION
          'v13: sql tool % handler % must return jsonb', r.name, r.handler;
      END IF;
      IF NOT has_function_privilege('v13_route', v_oid, 'EXECUTE') THEN
        RAISE EXCEPTION
          'v13: sql tool % handler % not executable by v13_route',
          r.name, r.handler;
      END IF;
      v_handler := format('%I.%I', v_nsp, r.handler);
      v_digest  := encode(digest(coalesce(v_prosrc, ''), 'sha256'), 'hex');
    END IF;
    v_entry := jsonb_build_object(
        'name', r.name, 'kind', r.kind, 'handler', v_handler,
        'param_spec', r.param_spec, 'enabled', r.enabled);
    IF v_digest IS NOT NULL THEN
      v_entry := v_entry || jsonb_build_object('handler_digest', v_digest);
    END IF;
    v_cat := v_cat || v_entry;
  END LOOP;
  RETURN v_cat;
END $function$;

REVOKE EXECUTE ON FUNCTION public.v13_named_sql_writer(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_spawn_writer_ok(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_named_sql_writer(text)
  TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION public.v13_spawn_writer_ok(text)
  TO v13_recall, v13_resolve, v13_route;

COMMIT;
