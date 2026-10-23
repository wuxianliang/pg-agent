-- W2 guards only: no application entry point or interpreter.
-- T1: statement triggers also reject empty-table mutations.
CREATE FUNCTION v24.raise_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  RAISE EXCEPTION 'v24.events is append-only'
    USING ERRCODE = '23514', CONSTRAINT = 'c_events_append_only';
END;
$$;
CREATE TRIGGER t_events_no_mut BEFORE UPDATE OR DELETE ON v24.events
  FOR EACH STATEMENT EXECUTE FUNCTION v24.raise_append_only();
CREATE TRIGGER t_events_no_trunc BEFORE TRUNCATE ON v24.events
  FOR EACH STATEMENT EXECUTE FUNCTION v24.raise_append_only();

-- T2: compare OLD/NEW per row; permit state transitions by returning NEW.
CREATE FUNCTION v24.guard_effect_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  IF ROW(NEW.request, NEW.request_digest, NEW.kind, NEW.requester_id,
         NEW.scope_id, NEW.run_id, NEW.fiber_id, NEW.episode_id, NEW.pin_id,
         NEW.parent_effect_id, NEW.ordinal)
     IS DISTINCT FROM
     ROW(OLD.request, OLD.request_digest, OLD.kind, OLD.requester_id,
         OLD.scope_id, OLD.run_id, OLD.fiber_id, OLD.episode_id, OLD.pin_id,
         OLD.parent_effect_id, OLD.ordinal) THEN
    RAISE EXCEPTION 'effect identity is immutable'
      USING ERRCODE = '23514', CONSTRAINT = 'c_effects_immutable';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER t_effects_identity BEFORE UPDATE ON v24.effects
  FOR EACH ROW EXECUTE FUNCTION v24.guard_effect_identity();

-- T3: close intent / completion remain mutable.
CREATE FUNCTION v24.guard_scope_route() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  IF ROW(NEW.root_id, NEW.parent_id, NEW.route_path, NEW.realm_routes, NEW.default_realm)
     IS DISTINCT FROM
     ROW(OLD.root_id, OLD.parent_id, OLD.route_path, OLD.realm_routes, OLD.default_realm) THEN
    RAISE EXCEPTION 'scope route is immutable'
      USING ERRCODE = '23514', CONSTRAINT = 'c_scopes_immutable';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER t_scopes_route BEFORE UPDATE ON v24.scopes
  FOR EACH ROW EXECUTE FUNCTION v24.guard_scope_route();

-- T4: host state and disposal state remain mutable.
CREATE FUNCTION v24.guard_install_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  IF ROW(NEW.manifest, NEW.manifest_digest, NEW.requires, NEW.provides,
         NEW.artifact_digest, NEW.adapter_digest, NEW.identity, NEW.version, NEW.scope_id)
     IS DISTINCT FROM
     ROW(OLD.manifest, OLD.manifest_digest, OLD.requires, OLD.provides,
         OLD.artifact_digest, OLD.adapter_digest, OLD.identity, OLD.version, OLD.scope_id) THEN
    RAISE EXCEPTION 'install identity is immutable'
      USING ERRCODE = '23514', CONSTRAINT = 'c_installs_immutable';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER t_installs_identity BEFORE UPDATE ON v24.installs
  FOR EACH ROW EXECUTE FUNCTION v24.guard_install_identity();

-- T5: commit-time cross-row backstop. Re-read the surviving row so multiple
-- updates in one transaction validate the final state, not stale trigger data.
CREATE FUNCTION v24.check_scope_parent_route() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  child v24.scopes%ROWTYPE;
  parent v24.scopes%ROWTYPE;
BEGIN
  SELECT * INTO child FROM v24.scopes WHERE scope_id = NEW.scope_id;
  IF NOT FOUND OR child.parent_id IS NULL THEN
    RETURN NULL;
  END IF;
  SELECT * INTO parent FROM v24.scopes WHERE scope_id = child.parent_id;
  IF NOT FOUND OR child.root_id IS DISTINCT FROM parent.root_id
     OR child.route_path IS DISTINCT FROM (parent.route_path || child.scope_id) THEN
    RAISE EXCEPTION 'child scope must extend its parent route and share its root'
      USING ERRCODE = '23514', CONSTRAINT = 'c_scopes_parent_route';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER t_scopes_parent_route
  AFTER INSERT OR UPDATE ON v24.scopes
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION v24.check_scope_parent_route();
