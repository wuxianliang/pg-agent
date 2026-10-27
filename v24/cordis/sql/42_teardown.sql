-- Canonical teardown module, loaded after 41 and before 50.
-- W1: command barrier seam and a read-only lifecycle tag. Live, P3/P5/P6,
-- inverse, pin release and dispose bodies are later milestones and are not wired here.
CREATE FUNCTION v24_cordis.command_barrier(p_effect_id uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 -- NULL means the command may proceed. Production P6 classification is not implemented.
 -- A disposable probe may replace this function; it must not write.
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.lifecycle_step(p_effect_id uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 -- W1 does not select divert/raise/leave/P6 tags and advance does not call this function.
 RETURN jsonb_build_object('tag','idle');
END $$;
