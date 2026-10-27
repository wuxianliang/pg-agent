CREATE FUNCTION v24_cordis.guard_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
  IF TG_TABLE_NAME='installs' THEN
    IF ROW(NEW.id,NEW.scope_id,NEW.owner_fiber_id,NEW.owner_episode_id,NEW.identity,
           NEW.version,NEW.manifest,NEW.artifact_digest,NEW.contracts,NEW.policy_ref,NEW.overlay)
       IS DISTINCT FROM
       ROW(OLD.id,OLD.scope_id,OLD.owner_fiber_id,OLD.owner_episode_id,OLD.identity,
           OLD.version,OLD.manifest,OLD.artifact_digest,OLD.contracts,OLD.policy_ref,OLD.overlay) THEN
      RAISE EXCEPTION 'install declaration is immutable' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='fibers' THEN
    IF ROW(NEW.id,NEW.install_id,NEW.owner_id,NEW.owner_episode_id,NEW.scope_id)
       IS DISTINCT FROM ROW(OLD.id,OLD.install_id,OLD.owner_id,OLD.owner_episode_id,OLD.scope_id) THEN
      RAISE EXCEPTION 'fiber identity is immutable' USING ERRCODE='55000';
    END IF;
    IF OLD.failure IS NOT NULL AND NEW.failure IS NULL THEN
      RAISE EXCEPTION 'failure history cannot be cleared' USING ERRCODE='55000';
    END IF;
    IF NEW.control_seq < OLD.control_seq THEN
      RAISE EXCEPTION 'fiber control sequence cannot decrease' USING ERRCODE='23514';
    END IF;
    IF (OLD.dispose_requested_at IS NOT NULL AND NEW.dispose_requested_at IS DISTINCT FROM OLD.dispose_requested_at)
       OR (OLD.disposed_at IS NOT NULL AND NEW.disposed_at IS DISTINCT FROM OLD.disposed_at) THEN
      RAISE EXCEPTION 'fiber disposal tombstone cannot change' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='episodes' THEN
    IF ROW(NEW.id,NEW.fiber_id,NEW.epoch) IS DISTINCT FROM ROW(OLD.id,OLD.fiber_id,OLD.epoch) THEN
      RAISE EXCEPTION 'episode identity is immutable' USING ERRCODE='55000';
    END IF;
    IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
      RAISE EXCEPTION 'episode close tombstone cannot change' USING ERRCODE='55000';
    END IF;
    IF (OLD.state='closing' AND (NEW.state IS DISTINCT FROM OLD.state OR NEW.outcome IS DISTINCT FROM OLD.outcome
       OR NEW.iterator IS DISTINCT FROM OLD.iterator))
       OR (OLD.state='active' AND NEW.state='reloading')
       OR (OLD.closed_at IS NOT NULL AND ROW(NEW.state,NEW.outcome,NEW.iterator)
         IS DISTINCT FROM ROW(OLD.state,OLD.outcome,OLD.iterator)) THEN
      RAISE EXCEPTION 'episode lifecycle cannot reopen or rewrite closing facts' USING ERRCODE='55000';
    END IF;
    IF NEW.committed_view IS DISTINCT FROM OLD.committed_view THEN
      RAISE EXCEPTION 'episode committed view is immutable' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='contributions' THEN
    IF ROW(NEW.id,NEW.fiber_id,NEW.episode_id,NEW.seq,NEW.kind,NEW.realm,NEW.key,
           NEW.descriptor,NEW.prev_contribution_id,NEW.inverse,NEW.contract_version)
       IS DISTINCT FROM
       ROW(OLD.id,OLD.fiber_id,OLD.episode_id,OLD.seq,OLD.kind,OLD.realm,OLD.key,
           OLD.descriptor,OLD.prev_contribution_id,OLD.inverse,OLD.contract_version) THEN
      RAISE EXCEPTION 'contribution identity and inverse are immutable' USING ERRCODE='55000';
    END IF;
    IF (OLD.withdrawn_at IS NOT NULL AND NEW.withdrawn_at IS DISTINCT FROM OLD.withdrawn_at)
       OR (OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at) THEN
      RAISE EXCEPTION 'contribution tombstone cannot change' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='runs' THEN
    IF ROW(NEW.id,NEW.owner_fiber_id,NEW.owner_episode_id,NEW.scope_id,NEW.parent_run_id,NEW.spawn_key)
       IS DISTINCT FROM ROW(OLD.id,OLD.owner_fiber_id,OLD.owner_episode_id,OLD.scope_id,OLD.parent_run_id,OLD.spawn_key) THEN
      RAISE EXCEPTION 'run identity and ownership are immutable' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='pins' THEN
    IF ROW(NEW.id,NEW.consumer_fiber_id,NEW.consumer_episode_id,NEW.consumer_run_id,NEW.key,
           NEW.contribution_id,NEW.provider_epoch,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id,OLD.consumer_fiber_id,OLD.consumer_episode_id,OLD.consumer_run_id,OLD.key,
           OLD.contribution_id,OLD.provider_epoch,OLD.created_at) THEN
      RAISE EXCEPTION 'pin identity and provider epoch are immutable' USING ERRCODE='55000';
    END IF;
    IF OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at THEN
      RAISE EXCEPTION 'pin release tombstone cannot change' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='effects' THEN
    IF ROW(NEW.id,NEW.parent_id,NEW.ordinal,NEW.fiber_id,NEW.episode_id,NEW.run_id,
           NEW.kind,NEW.input,NEW.request_actor)
       IS DISTINCT FROM
       ROW(OLD.id,OLD.parent_id,OLD.ordinal,OLD.fiber_id,OLD.episode_id,OLD.run_id,
           OLD.kind,OLD.input,OLD.request_actor) THEN
      RAISE EXCEPTION 'effect identity and input are immutable' USING ERRCODE='55000';
    END IF;
    -- A terminal receipt is durable: no reopen and no outcome/settlement replacement (plan 3.13).
    -- Check it before the non-terminal monotonic rule so every terminal attempt/fence edit is 55000.
    IF OLD.status IN ('succeeded','failed','unknown','cancelled') THEN
      IF NEW.status IS DISTINCT FROM OLD.status OR NEW.outcome IS DISTINCT FROM OLD.outcome
        OR NEW.settled_at IS DISTINCT FROM OLD.settled_at
        OR NEW.attempt IS DISTINCT FROM OLD.attempt OR NEW.fence IS DISTINCT FROM OLD.fence
        OR NEW.claim_owner IS DISTINCT FROM OLD.claim_owner
        OR NEW.lease_until IS DISTINCT FROM OLD.lease_until THEN
        RAISE EXCEPTION 'terminal effect receipt is immutable' USING ERRCODE='55000';
      END IF;
    ELSEIF NEW.attempt < OLD.attempt OR NEW.fence < OLD.fence THEN
      RAISE EXCEPTION 'effect attempt and fence cannot decrease' USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME='scopes' THEN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.parent_id IS DISTINCT FROM OLD.parent_id THEN
      RAISE EXCEPTION 'scope identity and parent are immutable' USING ERRCODE='55000';
    END IF;
    IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
      RAISE EXCEPTION 'scope close tombstone cannot change' USING ERRCODE='55000';
    END IF;
  ELSIF TG_TABLE_NAME='requests' THEN
    RAISE EXCEPTION 'request receipt is immutable' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER installs_immutable BEFORE UPDATE ON v24_cordis.installs
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER fibers_immutable BEFORE UPDATE ON v24_cordis.fibers
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER episodes_immutable BEFORE UPDATE ON v24_cordis.episodes
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER contributions_immutable BEFORE UPDATE ON v24_cordis.contributions
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER effects_immutable BEFORE UPDATE ON v24_cordis.effects
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER runs_immutable BEFORE UPDATE ON v24_cordis.runs
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER pins_immutable BEFORE UPDATE ON v24_cordis.pins
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER scopes_immutable BEFORE UPDATE ON v24_cordis.scopes
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();
CREATE TRIGGER requests_immutable BEFORE UPDATE ON v24_cordis.requests
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_immutable();

CREATE FUNCTION v24_cordis.guard_failure() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE fact jsonb;
BEGIN
 SELECT failure INTO fact FROM v24_cordis.fibers WHERE id=NEW.id;
 IF fact IS NOT NULL AND NOT coalesce(v24_cordis.failure_v1_valid(fact),false) THEN
  RAISE EXCEPTION 'failure must be exact v1' USING ERRCODE='23514'; END IF;
 IF fact IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM v24_cordis.episodes e WHERE e.id=(fact->>'episode_id')::uuid AND e.fiber_id=NEW.id
   AND e.iterator->'control_seq'=fact->'control_seq') THEN
  RAISE EXCEPTION 'failure must identify its frozen episode generation' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER fibers_failure AFTER INSERT OR UPDATE OF failure
 ON v24_cordis.fibers DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_failure();

CREATE FUNCTION v24_cordis.guard_scope_tree() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE has_cycle boolean;
BEGIN
  IF NEW.parent_id IS NULL THEN RETURN NEW; END IF;
  IF NEW.parent_id=NEW.id THEN
    RAISE EXCEPTION 'scope parent cycle' USING ERRCODE='23514';
  END IF;
  WITH RECURSIVE ancestors(id,path,cycle) AS (
    SELECT s.id,ARRAY[s.id],false FROM v24_cordis.scopes s WHERE s.id=NEW.parent_id
    UNION ALL
    SELECT p.id,a.path||p.id,p.id=ANY(a.path)
      FROM ancestors a JOIN v24_cordis.scopes s ON s.id=a.id
      JOIN v24_cordis.scopes p ON p.id=s.parent_id
      WHERE NOT a.cycle
  ) SELECT coalesce(bool_or(id=NEW.id OR cycle),false) INTO has_cycle FROM ancestors;
  IF has_cycle THEN RAISE EXCEPTION 'scope parent cycle' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER scopes_acyclic AFTER INSERT OR UPDATE OF parent_id ON v24_cordis.scopes
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_scope_tree();

CREATE FUNCTION v24_cordis.guard_current_episode() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE fiber uuid; target uuid; closed timestamptz;
BEGIN
  IF TG_TABLE_NAME='fibers' THEN
    fiber:=NEW.id;
    SELECT f.current_episode_id INTO target FROM v24_cordis.fibers f WHERE f.id=fiber;
    IF target IS NULL THEN RETURN NEW; END IF;
    SELECT e.closed_at INTO closed FROM v24_cordis.episodes e
      WHERE e.id=target AND e.fiber_id=fiber;
    IF NOT FOUND OR closed IS NOT NULL THEN
      RAISE EXCEPTION 'current episode must be open and belong to fiber' USING ERRCODE='23514';
    END IF;
  ELSE
    fiber:=NEW.fiber_id; target:=NEW.id;
    SELECT e.closed_at INTO closed FROM v24_cordis.episodes e WHERE e.id=target;
    IF closed IS NULL THEN RETURN NEW; END IF;
    IF EXISTS (SELECT 1 FROM v24_cordis.fibers f WHERE f.id=fiber AND f.current_episode_id=target) THEN
      RAISE EXCEPTION 'current episode must remain open' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER fibers_current_open AFTER INSERT OR UPDATE OF current_episode_id
  ON v24_cordis.fibers DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_current_episode();
CREATE CONSTRAINT TRIGGER episodes_current_open AFTER UPDATE OF closed_at
  ON v24_cordis.episodes DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_current_episode();

CREATE FUNCTION v24_cordis.guard_pin_epoch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE actual_epoch int; final_pin v24_cordis.pins%ROWTYPE; contribution_released timestamptz;
BEGIN
  SELECT * INTO final_pin FROM v24_cordis.pins WHERE id=NEW.id;
  IF NOT FOUND THEN RETURN NEW; END IF;
  SELECT e.epoch,c.released_at INTO actual_epoch,contribution_released
    FROM v24_cordis.contributions c JOIN v24_cordis.episodes e
      ON e.fiber_id=c.fiber_id AND e.id=c.episode_id
    WHERE c.id=final_pin.contribution_id;
  IF NOT FOUND OR actual_epoch IS DISTINCT FROM final_pin.provider_epoch THEN
    RAISE EXCEPTION 'pin provider epoch mismatch' USING ERRCODE='23514';
  END IF;
  IF final_pin.released_at IS NULL AND contribution_released IS NOT NULL THEN
    RAISE EXCEPTION 'live pin cannot reference released contribution' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER pins_provider_epoch AFTER INSERT OR UPDATE
  ON v24_cordis.pins DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_pin_epoch();

CREATE FUNCTION v24_cordis.guard_contribution_release() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions c JOIN v24_cordis.pins p ON p.contribution_id=c.id
   WHERE c.id=NEW.id AND c.released_at IS NOT NULL AND p.released_at IS NULL) THEN
  RAISE EXCEPTION 'released contribution has live pin' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER contributions_pin_release AFTER UPDATE OF released_at
 ON v24_cordis.contributions DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_contribution_release();

CREATE FUNCTION v24_cordis.guard_fiber_graph() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE roots int; has_cycle boolean; too_deep boolean; elements bigint;
BEGIN
 SELECT count(*) INTO roots FROM v24_cordis.fibers WHERE owner_id IS NULL;
 IF roots>1 THEN RAISE EXCEPTION 'fiber graph multiple roots' USING ERRCODE='23514'; END IF;
 SELECT (SELECT count(*) FROM v24_cordis.fibers)
       +(SELECT count(*) FROM v24_cordis.pins)
       +(SELECT count(*) FROM v24_cordis.runs) INTO elements;
 IF elements>262144 THEN
  RAISE EXCEPTION 'fiber graph validation limit' USING ERRCODE='23514';
 END IF;
 WITH RECURSIVE edges(child,parent) AS (
   SELECT f.id,f.owner_id FROM v24_cordis.fibers f
    WHERE f.owner_id IS NOT NULL AND f.disposed_at IS NULL
   UNION
   SELECT p.consumer_fiber_id,c.fiber_id FROM v24_cordis.pins p
    JOIN v24_cordis.contributions c ON c.id=p.contribution_id
    JOIN v24_cordis.fibers cf ON cf.id=p.consumer_fiber_id AND cf.disposed_at IS NULL
    JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id AND pf.disposed_at IS NULL
    WHERE p.released_at IS NULL AND p.consumer_fiber_id IS NOT NULL
   UNION
   SELECT r.owner_fiber_id,c.fiber_id FROM v24_cordis.pins p
    JOIN v24_cordis.runs r ON r.id=p.consumer_run_id
    JOIN v24_cordis.fibers rf ON rf.id=r.owner_fiber_id AND rf.disposed_at IS NULL
    JOIN v24_cordis.contributions c ON c.id=p.contribution_id
    JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id AND pf.disposed_at IS NULL
    WHERE p.released_at IS NULL AND p.consumer_run_id IS NOT NULL
 ), reach(root,node,depth) AS (
   SELECT f.id,f.id,0 FROM v24_cordis.fibers f
   UNION
   SELECT r.root,e.parent,r.depth+1
    FROM reach r JOIN edges e ON e.child=r.node
    WHERE r.depth<512
 )
 SELECT coalesce(bool_or(root=node AND depth>0),false),
        coalesce(max(depth)>=512,false)
  INTO has_cycle,too_deep FROM reach;
 IF has_cycle THEN RAISE EXCEPTION 'fiber graph cycle' USING ERRCODE='23514'; END IF;
 IF too_deep THEN
  RAISE EXCEPTION 'fiber graph validation limit' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER fibers_graph AFTER INSERT OR UPDATE OR DELETE ON v24_cordis.fibers
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_fiber_graph();
CREATE CONSTRAINT TRIGGER pins_graph AFTER INSERT OR UPDATE OR DELETE ON v24_cordis.pins
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_fiber_graph();
CREATE CONSTRAINT TRIGGER runs_graph AFTER INSERT OR UPDATE OR DELETE ON v24_cordis.runs
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION v24_cordis.guard_fiber_graph();

CREATE FUNCTION v24_cordis.reject_append_only_change() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
  RAISE EXCEPTION '% is append-only',TG_TABLE_NAME USING ERRCODE='55000';
END $$;
CREATE TRIGGER events_no_update BEFORE UPDATE ON v24_cordis.events
  FOR EACH STATEMENT EXECUTE FUNCTION v24_cordis.reject_append_only_change();
CREATE TRIGGER events_no_delete BEFORE DELETE ON v24_cordis.events
  FOR EACH STATEMENT EXECUTE FUNCTION v24_cordis.reject_append_only_change();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON v24_cordis.events
  FOR EACH STATEMENT EXECUTE FUNCTION v24_cordis.reject_append_only_change();
CREATE TRIGGER requests_no_delete BEFORE DELETE ON v24_cordis.requests
  FOR EACH STATEMENT EXECUTE FUNCTION v24_cordis.reject_append_only_change();
