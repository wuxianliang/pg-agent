-- v13 control plane stage 17. Self-contained transaction. Prefix files untouched.
BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_jsonschema;

DO $probe$
DECLARE
  sch json := '{"$schema":"http://json-schema.org/draft-07/schema#","type":"string","format":"date-time"}'::json;
  ok boolean;
BEGIN
  IF NOT jsonb_matches_schema(sch, '"2026-09-26T00:00:00Z"'::jsonb) THEN
    RAISE EXCEPTION 'v13: pg_jsonschema draft-07 date-time not enforced';
  END IF;
  IF NOT jsonb_matches_schema(sch, '"2026-09-26T00:00:00+00:00"'::jsonb) THEN
    RAISE EXCEPTION 'v13: pg_jsonschema draft-07 date-time not enforced';
  END IF;
  IF jsonb_matches_schema(sch, '"2026-09-26T00:00:00"'::jsonb) THEN
    RAISE EXCEPTION 'v13: pg_jsonschema draft-07 date-time not enforced';
  END IF;
  BEGIN
    ok := jsonb_matches_schema(sch, '1710000000'::jsonb);
    IF ok THEN
      RAISE EXCEPTION 'v13: pg_jsonschema draft-07 date-time not enforced';
    END IF;
  EXCEPTION
    WHEN raise_exception THEN RAISE;
    WHEN OTHERS THEN NULL;
  END;
END
$probe$;

INSERT INTO v13_policies (name, version, value, active) VALUES (
  'harness_result_schema', 1,
  jsonb_build_object('dialect', 'draft-07', 'schema', $harness$
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "required": ["result_kind"],
  "properties": {
    "result_kind": {"enum": ["progress", "finish", "wait", "reject"]},
    "wait_reason": {"enum": ["approval", "evidence", "quota"]},
    "delivery_kind": {"type": "string", "minLength": 1, "maxLength": 64},
    "harness_session_ref": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": "^[A-Za-z0-9_./:-]+$"},
    "resume_token": {"type": "string", "minLength": 1, "maxLength": 512},
    "interaction_id": {"type": "string", "minLength": 1, "maxLength": 256},
    "partial": {"type": "boolean"},
    "content_hash": {
      "type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": true,
      "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    },
    "signals": {
      "type": "array", "minItems": 1, "maxItems": 2, "uniqueItems": true,
      "items": {"enum": ["repair/required", "replan/required"]}
    },
    "wake": {"oneOf": [
      {"type": "object", "additionalProperties": false, "required": ["kind", "event_type"],
       "properties": {"kind": {"enum": ["event"]},
                      "event_type": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9_./:-]+$"}}},
      {"type": "object", "additionalProperties": false, "required": ["kind", "at"],
       "properties": {"kind": {"enum": ["not_before"]},
                      "at": {"type": "string", "format": "date-time", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"}}},
      {"type": "object", "additionalProperties": false, "required": ["kind", "content_hash"],
       "properties": {"kind": {"enum": ["artifact"]},
                      "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}},
      {"type": "object", "additionalProperties": false, "required": ["kind", "child_session_ids"],
       "properties": {"kind": {"enum": ["children_terminal"]},
                      "child_session_ids": {"type": "array", "minItems": 1, "uniqueItems": true,
                        "items": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}}}
    ]}
  },
  "allOf": [
    {"if": {"properties": {"result_kind": {"enum": ["progress"]}}, "required": ["result_kind"]},
     "then": {"allOf": [{"not": {"required": ["wait_reason"]}}, {"not": {"required": ["wake"]}}, {"not": {"required": ["interaction_id"]}}]}},
    {"if": {"properties": {"result_kind": {"enum": ["finish", "reject"]}}, "required": ["result_kind"]},
     "then": {"allOf": [{"not": {"required": ["wait_reason"]}}, {"not": {"required": ["wake"]}}, {"not": {"required": ["interaction_id"]}}, {"not": {"required": ["signals"]}}]}},
    {"if": {"properties": {"result_kind": {"enum": ["wait"]}}, "required": ["result_kind"]},
     "then": {"required": ["wait_reason"]}},
    {"if": {"properties": {"wait_reason": {"enum": ["approval"]}}, "required": ["wait_reason"]},
     "then": {"required": ["interaction_id"], "allOf": [{"not": {"required": ["wake"]}}]}},
    {"if": {"properties": {"wait_reason": {"enum": ["evidence", "quota"]}}, "required": ["wait_reason"]},
     "then": {"required": ["wake"], "allOf": [{"not": {"required": ["interaction_id"]}}]}},
    {"if": {"properties": {"delivery_kind": {"enum": ["USER_ACTION_REQUIRED"]}}, "required": ["delivery_kind"]},
     "then": {"properties": {"result_kind": {"enum": ["wait"]}, "wait_reason": {"enum": ["approval"]}},
              "required": ["result_kind", "wait_reason", "interaction_id"],
              "allOf": [{"not": {"required": ["wake"]}}]}}
  ]
}
$harness$::jsonb),
  true);

INSERT INTO tools (name, description, kind, handler, param_spec, enabled) VALUES (
  'harness_turn',
  'Run one harness turn and return a harness_result/v1 object.',
  'tool', 'worker:harness_turn', '{}'::jsonb, true);

CREATE FUNCTION v13_is_harness_tool(p_name text, p_kind text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT p_name = 'harness_turn' AND p_kind = 'tool'
$$;

CREATE FUNCTION v13_json_keys(p jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(array_agg(k ORDER BY k), '{}'::text[])
    FROM jsonb_object_keys(coalesce(p, '{}'::jsonb)) AS k
$$;

CREATE FUNCTION v13_json_int_ok(p jsonb, p_max numeric) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT p IS NOT NULL
     AND jsonb_typeof(p) = 'number'
     AND p::text ~ '^[0-9]+$'
     AND p::text::numeric BETWEEN 0 AND p_max
$$;

CREATE FUNCTION v13_canonical_uuid(p text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT p ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
$$;

CREATE FUNCTION v13_pending_human(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM effects
     WHERE session_id = p_sid AND kind = 'human'
       AND status IN ('ready', 'claimed'))
$$;

CREATE FUNCTION v13_unconsumed_cancel(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM sessions s
     WHERE s.session_id = p_sid
       AND s.status NOT IN ('completed', 'failed', 'cancelled')
       AND EXISTS (
         SELECT 1 FROM events c
          WHERE c.session_id = p_sid AND c.type = 'cancel/requested'
            AND c.seq > coalesce((
                  SELECT max(seq) FROM events
                   WHERE session_id = p_sid AND type = 'session/cancelled'), -1)))
$$;

CREATE FUNCTION v13_harness_request_ok(p_request jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT v13_json_keys(p_request) = ARRAY['continuation_index','handler','logical_turn_id','params','tool','tools_revision']
     AND p_request->>'tool' = 'harness_turn'
     AND jsonb_typeof(p_request->'params') = 'object'
     AND p_request->'params' = '{}'::jsonb
     AND NOT (p_request->'params' ? 'logical_turn_id')
     AND NOT (p_request->'params' ? 'continuation_index')
     AND jsonb_typeof(p_request->'handler') = 'string'
     AND length(p_request->>'handler') > 0
     AND v13_json_int_ok(p_request->'tools_revision', 9223372036854775807)
     AND jsonb_typeof(p_request->'logical_turn_id') = 'string'
     AND v13_canonical_uuid(p_request->>'logical_turn_id')
     AND v13_json_int_ok(p_request->'continuation_index', 2147483647)
$$;

CREATE FUNCTION v13_reject_bad_harness_request(p_kind text, p_tool text, p_request jsonb)
RETURNS void LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_req jsonb := coalesce(p_request, '{}'::jsonb);
  v_name text := coalesce(v_req->>'tool', p_tool, '');
  v_pair boolean := coalesce(v_req ? 'logical_turn_id', false)
                    OR coalesce(v_req ? 'continuation_index', false)
                    OR coalesce(coalesce(v_req->'params', '{}'::jsonb) ? 'logical_turn_id', false)
                    OR coalesce(coalesce(v_req->'params', '{}'::jsonb) ? 'continuation_index', false);
  v_harness boolean := v_name = 'harness_turn' OR coalesce(p_tool, '') = 'harness_turn';
BEGIN
  IF NOT v_pair AND NOT v_harness THEN
    RETURN;
  END IF;
  IF p_kind IS DISTINCT FROM 'tool'
     OR NOT v13_is_harness_tool(v_name, 'tool')
     OR NOT v13_harness_request_ok(p_request) THEN
    RAISE EXCEPTION 'v13: logical_turn_id required';
  END IF;
END $$;

CREATE FUNCTION v13_harness_predecessor(p_sid uuid) RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT e.effect_id
    FROM effects e
   WHERE e.session_id = p_sid
     AND e.kind = 'tool'
     AND v13_is_harness_tool(e.tool_name, e.kind)
     AND e.origin_user_seq = v13_last_user_seq(p_sid)
     AND v13_harness_request_ok(e.request)
   ORDER BY (SELECT max(ev.seq) FROM events ev
              WHERE ev.session_id = e.session_id AND ev.source_effect_id = e.effect_id) DESC NULLS LAST,
            e.created_at DESC,
            e.effect_id DESC
   LIMIT 1
$$;

CREATE FUNCTION v13_harness_tail_gap(p_sid uuid, p_keep uuid) RETURNS void
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM effects e
     WHERE e.session_id = p_sid
       AND e.kind = 'tool'
       AND v13_is_harness_tool(e.tool_name, e.kind)
       AND e.origin_user_seq = v13_last_user_seq(p_sid)
       AND e.status = 'succeeded'
       AND e.effect_id IS DISTINCT FROM p_keep
       AND (
         (e.result->>'result_kind' = 'progress' AND EXISTS (
            SELECT 1 FROM events ev
             WHERE ev.source_effect_id = e.effect_id
               AND ev.type IN ('repair/required', 'replan/required')))
         OR e.result->>'result_kind' = 'wait')
       AND NOT EXISTS (
         SELECT 1 FROM effects n
          WHERE n.session_id = e.session_id
            AND n.kind = 'tool'
            AND v13_is_harness_tool(n.tool_name, n.kind)
            AND n.request->>'logical_turn_id' = e.request->>'logical_turn_id'
            AND v13_json_int_ok(n.request->'continuation_index', 2147483647)
            AND v13_json_int_ok(e.request->'continuation_index', 2147483647)
            AND (n.request->>'continuation_index')::int
                = (e.request->>'continuation_index')::int + 1)) THEN
    RAISE EXCEPTION 'v13: harness tail gap';
  END IF;
END $$;

CREATE FUNCTION v13_raise_unknown_wall(p_sid uuid) RETURNS void
LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public
AS $wall$
DECLARE v_st text; v_unk boolean;
BEGIN
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  IF v_st IN ('blocked_unknown', 'completed', 'failed', 'cancelled') THEN
    RETURN;
  END IF;
  SELECT EXISTS (
    SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'unknown')
    INTO v_unk;
  IF v_st IN ('ready', 'waiting') AND v_unk THEN
    UPDATE sessions SET status = 'blocked_unknown' WHERE session_id = p_sid;
  END IF;
END
$wall$;

CREATE FUNCTION v13_validate_harness_result_v1(p_result jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb; v_err text;
BEGIN
  v_pol := v13_policy('harness_result_schema');
  IF v13_json_keys(v_pol) IS DISTINCT FROM ARRAY['dialect', 'schema']
     OR v_pol->>'dialect' IS DISTINCT FROM 'draft-07'
     OR v_pol->'schema'->>'$schema' IS DISTINCT FROM 'http://json-schema.org/draft-07/schema#' THEN
    RAISE EXCEPTION 'v13: harness_result schema dialect';
  END IF;
  IF NOT jsonb_matches_schema((v_pol->'schema')::json, p_result) THEN
    SELECT array_to_string(jsonschema_validation_errors((v_pol->'schema')::json, p_result::json), '; ')
      INTO v_err;
    RAISE EXCEPTION 'v13: harness_result schema %', coalesce(v_err, '');
  END IF;
END $$;

DO $self$
DECLARE v_msg text;
BEGIN
  PERFORM v13_validate_harness_result_v1('{"result_kind":"progress"}'::jsonb);
  PERFORM v13_validate_harness_result_v1(
    '{"result_kind":"wait","wait_reason":"approval","interaction_id":"ix-1"}'::jsonb);
  PERFORM v13_validate_harness_result_v1(
    '{"result_kind":"wait","wait_reason":"evidence","wake":{"kind":"not_before","at":"2026-09-26T00:00:00Z"}}'::jsonb);
  PERFORM v13_validate_harness_result_v1(
    '{"result_kind":"wait","wait_reason":"approval","interaction_id":"ix-1","delivery_kind":"USER_ACTION_REQUIRED"}'::jsonb);
  PERFORM v13_validate_harness_result_v1(
    '{"result_kind":"wait","wait_reason":"evidence","wake":{"kind":"children_terminal","child_session_ids":["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]}}'::jsonb);
  BEGIN
    PERFORM v13_validate_harness_result_v1('{"result_kind":"progress","wait_reason":"approval"}'::jsonb);
    RAISE EXCEPTION 'self-check progress+wait';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
    IF v_msg NOT LIKE '%harness_result schema%' THEN RAISE; END IF;
  END;
  BEGIN
    PERFORM v13_validate_harness_result_v1('{"result_kind":"finish","signals":["repair/required"]}'::jsonb);
    RAISE EXCEPTION 'self-check finish+signals';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
    IF v_msg NOT LIKE '%harness_result schema%' THEN RAISE; END IF;
  END;
  BEGIN
    PERFORM v13_validate_harness_result_v1('{"result_kind":"wait","wait_reason":"approval","interaction_id":"ix-1","wake":{"kind":"event","event_type":"ping"}}'::jsonb);
    RAISE EXCEPTION 'self-check approval+wake';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
    IF v_msg NOT LIKE '%harness_result schema%' THEN RAISE; END IF;
  END;
  BEGIN
    PERFORM v13_validate_harness_result_v1('{"result_kind":"wait","wait_reason":"evidence","wake":{"kind":"not_before","at":"2026-09-26T00:00:00"}}'::jsonb);
    RAISE EXCEPTION 'self-check notz';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
    IF v_msg NOT LIKE '%harness_result schema%' THEN RAISE; END IF;
  END;
  BEGIN
    PERFORM v13_validate_harness_result_v1('{"result_kind":"progress","interaction_kind":"x"}'::jsonb);
    RAISE EXCEPTION 'self-check unknown';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
    IF v_msg NOT LIKE '%harness_result schema%' THEN RAISE; END IF;
  END;
END
$self$;

CREATE FUNCTION v13_wake_is_satisfied_v1(p_sid uuid, p_effect uuid, p_wake jsonb)
RETURNS boolean LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_kind text; v_tail bigint; v_at timestamptz;
BEGIN
  IF p_wake IS NULL OR jsonb_typeof(p_wake) <> 'object' THEN
    RAISE EXCEPTION 'v13: harness_result schema';
  END IF;
  v_kind := p_wake->>'kind';
  IF v_kind = 'children_terminal' THEN
    RAISE EXCEPTION 'v13: children_terminal requires stage 18';
  ELSIF v_kind = 'event' THEN
    IF NOT EXISTS (
      SELECT 1 FROM events
       WHERE session_id = p_sid AND source_effect_id = p_effect AND type = 'effect_done') THEN
      RAISE EXCEPTION 'v13: effect_done missing';
    END IF;
    SELECT max(seq) INTO v_tail FROM events
     WHERE session_id = p_sid AND source_effect_id = p_effect
       AND type IN ('effect_done', 'tool/result', 'llm/message', 'repair/required', 'replan/required');
    IF v_tail IS NULL THEN
      RAISE EXCEPTION 'v13: effect_done missing';
    END IF;
    RETURN EXISTS (
      SELECT 1 FROM events
       WHERE session_id = p_sid AND type = p_wake->>'event_type' AND seq > v_tail);
  ELSIF v_kind = 'not_before' THEN
    v_at := (p_wake->>'at')::timestamptz;
    RETURN clock_timestamp() >= v_at;
  ELSIF v_kind = 'artifact' THEN
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'artifacts' AND column_name = 'content_hash')
       OR NOT EXISTS (
      SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'artifacts' AND column_name = 'produced_by') THEN
      RAISE EXCEPTION 'v13: artifact wake requires content_hash';
    END IF;
    RETURN EXISTS (
      SELECT 1 FROM artifacts a
      JOIN effects e ON e.effect_id = a.produced_by
       WHERE a.content_hash = p_wake->>'content_hash' AND e.status = 'succeeded');
  ELSE
    RAISE EXCEPTION 'v13: harness_result schema';
  END IF;
END $$;

CREATE FUNCTION v13_state_hash(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_turn int; v_name text; v_ver int; v_probe jsonb; v_max text;
  v_effects jsonb; v_events jsonb; v_input jsonb;
BEGIN
  SELECT turn_no, route_policy_name, route_policy_version
    INTO v_turn, v_name, v_ver
    FROM sessions WHERE session_id = p_sid;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  v_probe := v13_probe(p_sid);
  SELECT coalesce(max(seq)::text, '-1') INTO v_max FROM events
   WHERE session_id = p_sid
     AND type NOT IN ('session/completed', 'session/failed', 'session/cancelled');
  SELECT coalesce(jsonb_agg(row_j ORDER BY eid), '[]'::jsonb) INTO v_effects
    FROM (
      SELECT effect_id::text AS eid,
             jsonb_build_array(effect_id::text, kind, status, attempt_no::text, fence::text,
                               coalesce(tool_name, ''), request_hash, origin_user_seq::text) AS row_j
        FROM effects WHERE session_id = p_sid) s;
  SELECT coalesce(jsonb_agg(row_j ORDER BY seq), '[]'::jsonb) INTO v_events
    FROM (
      SELECT seq,
             jsonb_build_array(seq::text, type, payload_hash, coalesce(source_effect_id::text, '')) AS row_j
        FROM events
       WHERE session_id = p_sid
         AND type NOT IN ('session/completed', 'session/failed', 'session/cancelled')) s;
  v_input := jsonb_build_array(
    'v1',
    jsonb_build_array(p_sid::text, v_turn::text, coalesce(v_name, ''), v_ver::text,
                      coalesce(v_probe->>'goal_hash', ''),
                      coalesce(v_probe->>'tools_revision', ''),
                      coalesce(v_probe->>'candidate_generation_revision', ''),
                      v_max),
    v_effects, v_events);
  RETURN encode(digest(v_input::text, 'sha256'), 'hex');
END $$;

CREATE INDEX ix_effects_unknown ON effects (session_id) WHERE status = 'unknown';
CREATE UNIQUE INDEX ux_events_wake_satisfied ON events (session_id, source_effect_id)
  WHERE type = 'wake/satisfied';
CREATE UNIQUE INDEX ux_events_signal ON events (session_id, source_effect_id, type)
  WHERE type IN ('repair/required', 'replan/required');
CREATE UNIQUE INDEX ux_events_material ON events (session_id, source_effect_id)
  WHERE type = 'turn/material_spent';
CREATE INDEX ix_events_source_type ON events (source_effect_id, type);
CREATE UNIQUE INDEX ux_effects_approval_interaction
  ON effects (session_id, (result->>'interaction_id'))
  WHERE status = 'succeeded' AND kind = 'tool' AND request ? 'logical_turn_id'
    AND result->>'result_kind' = 'wait' AND result->>'wait_reason' = 'approval';
CREATE UNIQUE INDEX ux_effects_human_interaction_ref
  ON effects (session_id, (request->>'interaction_ref'))
  WHERE kind = 'human' AND request ? 'interaction_ref';
CREATE INDEX ix_effects_harness_pair
  ON effects (session_id, (request->>'logical_turn_id'), ((request->>'continuation_index')::int))
  WHERE kind = 'tool' AND request ? 'logical_turn_id';

CREATE FUNCTION v13_control_event_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_keys text[];
BEGIN
  IF NEW.type IN ('wake/satisfied', 'repair/required', 'replan/required',
                  'turn/material_spent', 'human/responded', 'unknown_resolved')
     AND NEW.source_effect_id IS NULL THEN
    RAISE EXCEPTION 'v13: event source required (%)', NEW.type;
  END IF;
  IF NEW.type IN ('session/completed', 'session/failed', 'session/cancelled', 'cancel/requested')
     AND NEW.source_effect_id IS NOT NULL THEN
    RAISE EXCEPTION 'v13: event source forbidden (%)', NEW.type;
  END IF;
  v_keys := v13_json_keys(NEW.payload);
  IF NEW.type = 'cancel/requested' AND v_keys IS DISTINCT FROM ARRAY['schema_version', 'scope'] THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type = 'cancel/requested'
        AND (NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
             OR NEW.payload->>'scope' IS DISTINCT FROM 'session') THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type = 'unknown_resolved'
        AND v_keys IS DISTINCT FROM ARRAY['effect_id', 'evidence_hash', 'resolution', 'schema_version'] THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type = 'turn/material_spent'
        AND v_keys IS DISTINCT FROM ARRAY['effect_id', 'schema_version'] THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type IN ('repair/required', 'replan/required')
        AND v_keys IS DISTINCT FROM ARRAY['schema_version'] THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type = 'wake/satisfied'
        AND v_keys IS DISTINCT FROM ARRAY['effect_id', 'wake_kind'] THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type = 'wake/satisfied'
        AND NEW.payload->>'wake_kind' NOT IN ('event', 'not_before', 'artifact', 'children_terminal') THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type = 'human/responded'
        AND v_keys IS DISTINCT FROM ARRAY['answers', 'interaction_ref', 'origin_user_seq', 'response', 'schema_version', 'skip'] THEN
    RAISE EXCEPTION 'v13: event payload %', NEW.type;
  ELSIF NEW.type IN ('session/completed', 'session/failed', 'session/cancelled') THEN
    IF v_keys IS DISTINCT FROM ARRAY['children', 'origin_user_seq', 'produced_hashes', 'schema_version', 'spent', 'state_hash', 'turn_end_reason', 'unconsumed'] THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
    IF v13_json_keys(NEW.payload->'spent') IS DISTINCT FROM ARRAY['cycle_no', 'material_count', 'max_cycles', 'turn_no']
       OR v13_json_keys(NEW.payload->'unconsumed') IS DISTINCT FROM ARRAY['approval_pending_effect_ids', 'material_effect_ids', 'repair_effect_ids', 'replan_effect_ids', 'wake_pending_effect_ids'] THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
    IF jsonb_typeof(NEW.payload->'children') <> 'array'
       OR jsonb_typeof(NEW.payload->'produced_hashes') <> 'array' THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_v13_control_event_guard
  BEFORE INSERT ON events
  FOR EACH ROW
  WHEN (NEW.type IN ('wake/satisfied', 'repair/required', 'replan/required',
                     'turn/material_spent', 'human/responded', 'unknown_resolved',
                     'session/completed', 'session/failed', 'session/cancelled',
                     'cancel/requested'))
  EXECUTE FUNCTION v13_control_event_guard();

CREATE FUNCTION v13_material_spent_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_src effects; v_lt text;
BEGIN
  PERFORM 1 FROM sessions WHERE session_id = NEW.session_id FOR UPDATE;
  SELECT * INTO v_src FROM effects WHERE effect_id = NEW.source_effect_id;
  IF NOT FOUND OR v_src.session_id IS DISTINCT FROM NEW.session_id
     OR v_src.status IS DISTINCT FROM 'succeeded'
     OR NOT v13_is_harness_tool(v_src.tool_name, v_src.kind)
     OR NOT v13_harness_request_ok(v_src.request) THEN
    RAISE EXCEPTION 'v13: material ledger';
  END IF;
  IF NOT (v_src.result->>'result_kind' = 'finish'
          OR (v_src.result->>'result_kind' = 'progress' AND NOT EXISTS (
                SELECT 1 FROM events ev
                 WHERE ev.source_effect_id = v_src.effect_id
                   AND ev.type IN ('repair/required', 'replan/required')))) THEN
    RAISE EXCEPTION 'v13: material ledger';
  END IF;
  v_lt := v_src.request->>'logical_turn_id';
  IF EXISTS (
    SELECT 1 FROM events ev
    JOIN effects src ON src.effect_id = ev.source_effect_id
     WHERE ev.session_id = NEW.session_id
       AND ev.type = 'turn/material_spent'
       AND src.request->>'logical_turn_id' = v_lt
       AND ev.source_effect_id IS DISTINCT FROM NEW.source_effect_id) THEN
    RAISE EXCEPTION 'v13: material ledger';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_v13_material_spent_guard
  BEFORE INSERT ON events
  FOR EACH ROW
  WHEN (NEW.type = 'turn/material_spent')
  EXECUTE FUNCTION v13_material_spent_guard();

DO $backfill$
DECLARE v_n int; v_ids uuid[];
BEGIN
  WITH u AS (
    UPDATE sessions s SET status = 'blocked_unknown'
     WHERE s.status IN ('ready', 'waiting')
       AND EXISTS (SELECT 1 FROM effects e
                    WHERE e.session_id = s.session_id AND e.status = 'unknown')
    RETURNING s.session_id)
  SELECT count(*) INTO v_n FROM u;
  RAISE NOTICE 'v13: unknown wall backfill %', v_n;
  SELECT array_agg(s.session_id) INTO v_ids
    FROM sessions s
   WHERE (s.status = 'blocked_unknown' AND NOT EXISTS (
            SELECT 1 FROM effects e WHERE e.session_id = s.session_id AND e.status = 'unknown'))
      OR (s.status IN ('ready', 'waiting') AND EXISTS (
            SELECT 1 FROM effects e WHERE e.session_id = s.session_id AND e.status = 'unknown'));
  IF v_ids IS NOT NULL THEN
    RAISE EXCEPTION 'v13: unknown wall install assert %', v_ids;
  END IF;
  SELECT array_agg(s.session_id) INTO v_ids
    FROM sessions s
   WHERE s.status IN ('completed', 'failed', 'cancelled')
     AND EXISTS (SELECT 1 FROM effects e
                  WHERE e.session_id = s.session_id AND e.status = 'unknown');
  IF v_ids IS NOT NULL THEN
    RAISE NOTICE 'v13: terminal unknown residue %', v_ids;
  END IF;
  IF EXISTS (SELECT 1 FROM events WHERE type = 'turn/material_spent') THEN
    RAISE EXCEPTION 'v13: install material_spent residue';
  END IF;
  IF EXISTS (
    SELECT 1 FROM effects
     WHERE (request ? 'logical_turn_id') IS DISTINCT FROM (request ? 'continuation_index')) THEN
    RAISE EXCEPTION 'v13: install one-sided logical pair';
  END IF;
  IF EXISTS (
    SELECT 1 FROM effects
     WHERE status = 'succeeded' AND kind = 'tool' AND result ? 'result_kind'
       AND NOT v13_harness_request_ok(request)) THEN
    RAISE EXCEPTION 'v13: install harness result missing logical pair';
  END IF;
END
$backfill$;

CREATE FUNCTION v13_unknown_wall_bijection() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_sid uuid;
  v_st text;
  v_unk boolean;
BEGIN
  IF TG_TABLE_NAME = 'effects' THEN
    IF TG_OP = 'UPDATE' AND OLD.session_id IS DISTINCT FROM NEW.session_id THEN
      PERFORM v13_assert_unknown_wall(OLD.session_id);
      PERFORM v13_assert_unknown_wall(NEW.session_id);
      RETURN NULL;
    END IF;
    v_sid := CASE WHEN TG_OP = 'DELETE' THEN OLD.session_id ELSE NEW.session_id END;
  ELSE
    v_sid := NEW.session_id;
  END IF;
  PERFORM v13_assert_unknown_wall(v_sid);
  RETURN NULL;
END $$;

CREATE FUNCTION v13_assert_unknown_wall(p_sid uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_st text; v_unk boolean;
BEGIN
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF NOT FOUND THEN
    RETURN;
  END IF;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN;
  END IF;
  SELECT EXISTS (
    SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'unknown')
    INTO v_unk;
  IF v_unk IS DISTINCT FROM (v_st = 'blocked_unknown') THEN
    RAISE EXCEPTION 'v13: unknown wall bijection (session %)', p_sid;
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_effects_unknown_wall ON effects;
DROP TRIGGER IF EXISTS trg_sessions_unknown_wall ON sessions;
CREATE CONSTRAINT TRIGGER trg_effects_unknown_wall
  AFTER INSERT OR DELETE OR UPDATE OF status, session_id ON effects
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION v13_unknown_wall_bijection();
CREATE CONSTRAINT TRIGGER trg_sessions_unknown_wall
  AFTER INSERT OR UPDATE OF status ON sessions
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION v13_unknown_wall_bijection();

CREATE FUNCTION v13_closeout(p_sid uuid, p_outcome text, p_reason text,
                             p_attempts_exhausted boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_st text; v_n int; v_seal jsonb; v_type text; v_escape boolean;
  v_end jsonb; v_hash text; v_receipt jsonb; v_ous bigint;
  v_hashes jsonb; v_repair jsonb; v_replan jsonb; v_material jsonb;
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
  IF EXISTS (SELECT 1 FROM sessions WHERE parent_session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: closeout children require stage 18';
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
       WHERE ev.session_id = p_sid AND ev.type = 'repair/required'
         AND ev.source_effect_id IS NOT NULL) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_replan
    FROM (
      SELECT DISTINCT ev.source_effect_id::text AS id
        FROM events ev
       WHERE ev.session_id = p_sid AND ev.type = 'replan/required'
         AND ev.source_effect_id IS NOT NULL) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_material
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND v13_harness_request_ok(e.request)
         AND (e.result->>'result_kind' = 'finish'
              OR (e.result->>'result_kind' = 'progress' AND NOT EXISTS (
                    SELECT 1 FROM events ev
                     WHERE ev.source_effect_id = e.effect_id
                       AND ev.type IN ('repair/required', 'replan/required'))))
         AND NOT EXISTS (
           SELECT 1 FROM events ev
            WHERE ev.source_effect_id = e.effect_id AND ev.type = 'turn/material_spent')) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_wake
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND e.result->>'result_kind' = 'wait'
         AND e.result->>'wait_reason' IN ('evidence', 'quota')
         AND NOT EXISTS (
           SELECT 1 FROM events ev
            WHERE ev.source_effect_id = e.effect_id AND ev.type = 'wake/satisfied')) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_appr
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND e.result->>'result_kind' = 'wait'
         AND e.result->>'wait_reason' = 'approval'
         AND NOT EXISTS (
           SELECT 1 FROM effects h
            WHERE h.session_id = e.session_id AND h.kind = 'human'
              AND h.status = 'succeeded'
              AND h.request->>'interaction_ref' = e.result->>'interaction_id')) q;
  v_owed := false;
  v_pred := v13_harness_predecessor(p_sid);
  IF v_pred IS NOT NULL THEN
    SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
    IF v_prow.status = 'succeeded' AND (
         (v_prow.result->>'result_kind' = 'progress' AND EXISTS (
            SELECT 1 FROM events ev
             WHERE ev.source_effect_id = v_pred
               AND ev.type IN ('repair/required', 'replan/required')))
         OR (v_prow.result->>'result_kind' = 'wait'
             AND v_prow.result->>'wait_reason' = 'approval'
             AND EXISTS (
               SELECT 1 FROM effects h
                WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
                  AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id'))
         OR (v_prow.result->>'result_kind' = 'wait'
             AND v_prow.result->>'wait_reason' IN ('evidence', 'quota')
             AND EXISTS (
               SELECT 1 FROM events ev
                WHERE ev.source_effect_id = v_pred AND ev.type = 'wake/satisfied')))
       AND NOT EXISTS (
         SELECT 1 FROM effects n
          WHERE n.session_id = p_sid AND n.kind = 'tool'
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
  v_receipt := jsonb_build_object(
    'schema_version', 1,
    'origin_user_seq', v_ous,
    'spent', jsonb_build_object(
      'turn_no', (SELECT turn_no FROM sessions WHERE session_id = p_sid),
      'cycle_no', v13_cycle_no(p_sid),
      'max_cycles', (v13_policy('turn_budget')->>'max_cycles')::int,
      'material_count', (SELECT count(*) FROM events
                          WHERE session_id = p_sid AND type = 'turn/material_spent')),
    'produced_hashes', v_hashes,
    'children', '[]'::jsonb,
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
END $$;

CREATE FUNCTION v13_cancel(p_sid uuid) RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_st text; r record;
BEGIN
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN 'replay';
  END IF;
  FOR r IN SELECT effect_id FROM effects WHERE session_id = p_sid ORDER BY effect_id FOR UPDATE LOOP
  END LOOP;
  IF NOT v13_unconsumed_cancel(p_sid) THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'cancel/requested',
      jsonb_build_object('schema_version', 1, 'scope', 'session'));
  END IF;
  UPDATE effects
     SET status = 'cancelled', fence = fence + 1, error = NULL,
         lease_owner = NULL, lease_until = NULL
   WHERE session_id = p_sid AND status = 'ready';
  RETURN 'accepted';
END $$;

CREATE FUNCTION v13_resolve_unknown(p_effect uuid, p_resolution text, p_evidence jsonb)
RETURNS text LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_sid uuid; v_row effects; v_hash text; v_obs text; v_keys text[]; v_st text;
BEGIN
  IF p_resolution NOT IN ('confirmed', 'not_happened', 'rolled_back') THEN
    RAISE EXCEPTION 'v13: resolve resolution %', p_resolution;
  END IF;
  IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN
    RAISE EXCEPTION 'v13: resolve evidence';
  END IF;
  v_keys := v13_json_keys(p_evidence);
  v_obs := p_evidence->>'observation';
  IF p_resolution = 'confirmed' THEN
    IF v_keys IS DISTINCT FROM ARRAY['observation', 'payload_hash']
       OR v_obs IS DISTINCT FROM 'committed' THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
  ELSIF p_resolution = 'not_happened' THEN
    IF v_keys IS DISTINCT FROM ARRAY['observation'] OR v_obs IS DISTINCT FROM 'absent' THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
  ELSE
    IF v_keys IS DISTINCT FROM ARRAY['compensation_ref', 'observation']
       OR v_obs IS DISTINCT FROM 'rolled_back'
       OR coalesce(p_evidence->>'compensation_ref', '') !~ '^[A-Za-z0-9_./:-]+$'
       OR length(coalesce(p_evidence->>'compensation_ref', '')) NOT BETWEEN 1 AND 256 THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
  END IF;
  SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;
  IF v_sid IS NULL THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF v_row.status IS DISTINCT FROM 'unknown' THEN
    RAISE EXCEPTION 'v13: resolve unknown required';
  END IF;
  v_hash := encode(digest(p_evidence::text, 'sha256'), 'hex');
  IF p_resolution = 'confirmed' THEN
    IF v_row.result IS NULL
       OR p_evidence->>'payload_hash' IS DISTINCT FROM encode(digest(v_row.result::text, 'sha256'), 'hex') THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
    UPDATE effects SET status = 'succeeded', error = NULL WHERE effect_id = p_effect;
  ELSE
    UPDATE effects SET status = 'failed',
           error = jsonb_build_object('code', 'unknown_resolved',
                                      'resolution', p_resolution,
                                      'evidence_hash', v_hash)
     WHERE effect_id = p_effect;
  END IF;
  PERFORM v13_append_event(v_sid, gen_random_uuid(), 'unknown_resolved',
    jsonb_build_object('schema_version', 1, 'effect_id', p_effect::text,
                       'resolution', p_resolution, 'evidence_hash', v_hash),
    p_effect);
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = v_sid AND status = 'unknown') THEN
    RETURN 'accepted';
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = v_sid;
  IF v_st = 'blocked_unknown' THEN
    IF v13_pending_human(v_sid) THEN
      UPDATE sessions SET status = 'waiting' WHERE session_id = v_sid;
    ELSE
      UPDATE sessions SET status = 'ready' WHERE session_id = v_sid;
    END IF;
  END IF;
  RETURN 'accepted';
END $$;

CREATE OR REPLACE FUNCTION v13_enqueue_effect(p_sid uuid, p_kind text, p_request jsonb,
                                              p_tool text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE v_id uuid := v13_effect_id(p_sid, p_kind, p_request); v_row effects;
BEGIN
  IF v13_unconsumed_cancel(p_sid) THEN
    RAISE EXCEPTION 'v13: unconsumed cancel/requested';
  END IF;
  PERFORM v13_reject_bad_harness_request(p_kind, p_tool, p_request);
  IF NOT (v13_policy('effect_attempt_cap') ? p_kind) THEN
    RAISE EXCEPTION
      'v13: effect_attempt_cap policy missing kind % (config error, fix the policy row)',
      p_kind;
  END IF;
  SELECT * INTO v_row FROM effects WHERE effect_id = v_id;
  IF v_row.effect_id IS NOT NULL THEN
    IF v_row.status IN ('succeeded', 'ready', 'claimed') THEN
      RETURN v_id;
    ELSIF v_row.status IN ('failed', 'cancelled') THEN
      IF NOT v13_attempt_ok(p_kind, v_row.attempt_no) THEN
        RETURN v_id;
      END IF;
      UPDATE effects SET status = 'ready', error = NULL,
             lease_owner = NULL, lease_until = NULL, fence = fence + 1
       WHERE effect_id = v_id;
      RETURN v_id;
    ELSE
      RAISE EXCEPTION 'v13: effect % is unknown — resolve explicitly', v_id;
    END IF;
  END IF;
  INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash,
                       idempotency_key, origin_user_seq)
  VALUES (v_id, p_sid, p_kind, p_tool, p_request,
          encode(digest(p_request::text, 'sha256'), 'hex'),
          'v13:' || v_id::text, v13_last_user_seq(p_sid));
  RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION v13_complete(p_effect uuid, p_attempt integer, p_fence bigint,
                                        p_status text, p_result jsonb DEFAULT NULL)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
  v_sid uuid; v_row effects; v_outcome text; v_err jsonb; v_human jsonb;
  v_resp boolean := false; v_ans boolean := false; v_skip boolean := false;
  v_n int := 0; k text; v_t text;
BEGIN
  IF p_status NOT IN ('succeeded', 'failed', 'unknown') THEN
    RAISE EXCEPTION 'v13: bad outcome %', p_status;
  END IF;
  IF p_attempt IS NULL OR p_fence IS NULL THEN
    RAISE EXCEPTION 'v13: complete requires non-NULL (attempt,fence) tokens (effect %)', p_effect;
  END IF;
  SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF v_row.attempt_no IS DISTINCT FROM p_attempt OR v_row.fence IS DISTINCT FROM p_fence THEN
    RETURN 'stale';
  END IF;
  IF v_row.status IN ('succeeded', 'failed', 'unknown', 'cancelled') THEN
    RETURN 'replay';
  END IF;
  IF v_row.status <> 'claimed' THEN
    RETURN 'stale';
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
      IF p_result->'wake'->>'kind' = 'children_terminal' THEN
        RAISE EXCEPTION 'v13: children_terminal requires stage 18';
      END IF;
    END IF;
  ELSIF v_row.request ? 'logical_turn_id' OR v_row.request ? 'continuation_index'
        OR (p_status = 'succeeded' AND v_row.kind <> 'tool' AND p_result ? 'result_kind') THEN
    RAISE EXCEPTION 'v13: logical_turn_id required';
  END IF;
  v_outcome := p_status; v_err := NULL;
  IF p_status = 'succeeded' AND v_row.kind = 'llm'
     AND (coalesce(jsonb_typeof(p_result->'text'), 'null') <> 'string'
          OR coalesce(btrim(p_result->>'text'), '') = '') THEN
    v_outcome := 'failed';
    v_err := jsonb_build_object('code', 'llm_result_shape');
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
                         'origin_user_seq', v_row.origin_user_seq));
  END IF;
  IF v_outcome = 'unknown' THEN
    PERFORM v13_raise_unknown_wall(v_sid);
  END IF;
  RETURN 'accepted';
END $$;

CREATE OR REPLACE FUNCTION v13_requeue_stale() RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_j int := 0; v_u int := 0; v_w int := 0; v_k int; v_f int := 0;
  r record; v_id uuid; v_ids uuid[] := '{}'; v_sid uuid; v_n int; v_cancel boolean;
BEGIN
  FOR v_sid IN
    SELECT DISTINCT session_id FROM effects
     WHERE status = 'claimed' AND lease_until < clock_timestamp()
     ORDER BY session_id
  LOOP
    PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
    IF NOT FOUND THEN
      CONTINUE;
    END IF;
    v_cancel := v13_unconsumed_cancel(v_sid);
    IF v_cancel THEN
      UPDATE effects
         SET status = 'cancelled', fence = fence + 1, error = NULL,
             lease_owner = NULL, lease_until = NULL
       WHERE session_id = v_sid AND status = 'claimed'
         AND kind IN ('judge', 'mgraph_consolidate')
         AND lease_until < clock_timestamp()
         AND v13_attempt_ok(kind, attempt_no);
    ELSE
      UPDATE effects
         SET status = 'ready', fence = fence + 1,
             lease_owner = NULL, lease_until = NULL
       WHERE session_id = v_sid AND status = 'claimed'
         AND kind IN ('judge', 'mgraph_consolidate')
         AND lease_until < clock_timestamp()
         AND v13_attempt_ok(kind, attempt_no);
      GET DIAGNOSTICS v_n = ROW_COUNT;
      v_j := v_j + v_n;
    END IF;
    WITH capped AS (
      UPDATE effects
         SET status = 'failed', fence = fence + 1,
             lease_owner = NULL, lease_until = NULL,
             error = jsonb_build_object('code', 'lease_exhausted')
       WHERE session_id = v_sid AND status = 'claimed'
         AND kind IN ('judge', 'mgraph_consolidate')
         AND lease_until < clock_timestamp()
         AND NOT v13_attempt_ok(kind, attempt_no)
      RETURNING effect_id)
    SELECT v_ids || coalesce(array_agg(effect_id), '{}'::uuid[]) INTO v_ids FROM capped;
    UPDATE effects
       SET status = 'unknown', fence = fence + 1,
           lease_owner = NULL, lease_until = NULL
     WHERE session_id = v_sid AND status = 'claimed'
       AND kind NOT IN ('judge', 'mgraph_consolidate')
       AND lease_until < clock_timestamp();
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_u := v_u + v_n;
    IF v_n > 0 THEN
      PERFORM v13_raise_unknown_wall(v_sid);
    END IF;
  END LOOP;
  v_f := coalesce(array_length(v_ids, 1), 0);
  FOR r IN SELECT effect_id FROM effects WHERE status = 'ready' LOOP
    PERFORM v13_send_work(r.effect_id);
    v_w := v_w + 1;
  END LOOP;
  FOREACH v_id IN ARRAY v_ids LOOP
    PERFORM v13_send_work(v_id);
  END LOOP;
  SELECT count(*) INTO v_k FROM effects WHERE status = 'unknown';
  RETURN jsonb_build_object('reclaimed_ready', v_j, 'walled_unknown', v_u,
                            'lease_exhausted', v_f, 'woken_ready', v_w, 'walls_total', v_k);
END $$;

CREATE OR REPLACE FUNCTION v13_advance(p_sid uuid, p_snap jsonb) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  v_now jsonb; v_route jsonb; v_cycles int; v_max int;
  v_effect uuid; v_est text; v_res jsonb; v_handler text; v_req jsonb; v_err jsonb;
  v_pred uuid; v_prow effects; v_sig text[]; v_ev text[]; v_cand boolean;
  v_cap_new boolean; v_cont boolean; v_idx bigint; v_st text;
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
      v_now->>'tools_revision', v_now->>'candidate_generation_revision')
     IS DISTINCT FROM
     (p_snap->'snap'->>'session_version', p_snap->'snap'->>'max_event_seq',
      p_snap->'snap'->>'goal_hash', p_snap->'snap'->>'route_policy_name',
      p_snap->'snap'->>'route_policy_version', p_snap->'snap'->>'tools_revision',
      p_snap->'snap'->>'candidate_generation_revision') THEN
    RETURN 'stale';
  END IF;
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
      PERFORM v13_closeout(p_sid, 'cancelled', 'cancel', false);
      RETURN 'terminal';
    END IF;
    RETURN 'waiting';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed')) THEN
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  v_pred := v13_harness_predecessor(p_sid);
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
       WHERE source_effect_id = v_pred AND type IN ('repair/required', 'replan/required');
      IF v_sig IS DISTINCT FROM v_ev THEN
        RAISE EXCEPTION 'v13: signals ledger';
      END IF;
      v_cand := v_prow.result->>'result_kind' = 'finish'
        OR (v_prow.result->>'result_kind' = 'progress' AND NOT EXISTS (
              SELECT 1 FROM events WHERE source_effect_id = v_pred
                AND type IN ('repair/required', 'replan/required')));
      IF v_cand THEN
        IF EXISTS (
          SELECT 1 FROM events ev
          JOIN effects src ON src.effect_id = ev.source_effect_id
           WHERE ev.session_id = p_sid AND ev.type = 'turn/material_spent'
             AND src.request->>'logical_turn_id' = v_prow.request->>'logical_turn_id'
             AND ev.source_effect_id IS DISTINCT FROM v_pred) THEN
          RAISE EXCEPTION 'v13: material ledger';
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM events WHERE source_effect_id = v_pred AND type = 'turn/material_spent') THEN
          PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/material_spent',
            jsonb_build_object('schema_version', 1, 'effect_id', v_pred::text), v_pred);
        END IF;
      END IF;
      IF v_prow.result->>'result_kind' = 'finish' THEN
        PERFORM v13_closeout(p_sid, 'completed', 'harness_finish', false);
        RETURN 'terminal';
      ELSIF v_prow.result->>'result_kind' = 'reject' THEN
        PERFORM v13_closeout(p_sid, 'failed', 'harness_reject', false);
        RETURN 'terminal';
      END IF;
      IF v_prow.result->>'result_kind' = 'wait'
         AND v_prow.result->>'wait_reason' IN ('evidence', 'quota')
         AND NOT EXISTS (
           SELECT 1 FROM events WHERE source_effect_id = v_pred AND type = 'wake/satisfied') THEN
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
            WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
              AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id') THEN
        IF EXISTS (
          SELECT 1 FROM effects h
           WHERE h.session_id = p_sid AND h.kind = 'human'
             AND h.status IN ('ready', 'claimed', 'unknown')) THEN
          RAISE EXCEPTION 'v13: approval human exists';
        END IF;
        IF v13_cycle_no(p_sid) >= (v13_policy('turn_budget')->>'max_cycles')::int THEN
          PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
          RETURN 'terminal';
        END IF;
        v_effect := v13_enqueue_effect(p_sid, 'human',
          jsonb_build_object('schema_version', 1,
                             'interaction_ref', v_prow.result->>'interaction_id'));
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          PERFORM v13_closeout(p_sid, 'failed', 'approval_exhausted', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
      v_cap_new := EXISTS (
        SELECT 1 FROM effects h
        JOIN events ev ON ev.source_effect_id = h.effect_id AND ev.type = 'human/responded'
         WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
           AND h.origin_user_seq = v13_last_user_seq(p_sid)
           AND h.request->>'interaction_kind' IN ('material_cap', 'repair_cap', 'replan_cap')
           AND ev.seq > coalesce((SELECT max(seq) FROM events
                                   WHERE source_effect_id = v_pred AND type = 'effect_done'), -1));
      v_cont := false;
      IF NOT v_cap_new THEN
        IF v_prow.result->>'result_kind' = 'progress' AND EXISTS (
             SELECT 1 FROM events WHERE source_effect_id = v_pred
               AND type IN ('repair/required', 'replan/required')) THEN
          v_cont := true;
        ELSIF v_prow.result->>'result_kind' = 'wait' AND (
              (v_prow.result->>'wait_reason' = 'approval' AND EXISTS (
                 SELECT 1 FROM effects h
                  WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
                    AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id'))
              OR (v_prow.result->>'wait_reason' IN ('evidence', 'quota') AND EXISTS (
                 SELECT 1 FROM events WHERE source_effect_id = v_pred AND type = 'wake/satisfied'))) THEN
          v_cont := true;
        END IF;
      END IF;
      IF v_cont THEN
        IF v13_cycle_no(p_sid) >= (v13_policy('turn_budget')->>'max_cycles')::int THEN
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
          PERFORM v13_closeout(p_sid, 'failed', 'harness_attempts', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
    END IF;
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
      PERFORM v13_closeout(p_sid, 'failed', 'resolve_budget', false);
      RETURN 'terminal';
    ELSIF v_est IN ('failed', 'cancelled') THEN
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
      PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
      RETURN 'terminal';
    ELSIF v_est IN ('failed', 'cancelled') THEN
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
      PERFORM v13_closeout(p_sid, 'failed', 'judge_attempts', true);
      RETURN 'terminal';
    ELSIF v_est <> 'succeeded' THEN
      PERFORM v13_send_work(v_effect);
      UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
      RETURN 'waiting';
    END IF;
  END IF;
  v_route := v13_route(p_sid, p_snap->'envelope');
  IF v_route->>'action' = 'sql' AND v13_is_harness_tool(v_route->>'tool', 'tool') THEN
    RAISE EXCEPTION 'v13: harness_turn kind';
  END IF;
  IF v_route->>'action' = 'tool' AND v13_is_harness_tool(v_route->>'tool', 'tool') THEN
    v_pred := v13_harness_predecessor(p_sid);
    IF v_pred IS NOT NULL THEN
      SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
      IF v_prow.status IN ('failed', 'cancelled') THEN
        PERFORM v13_harness_tail_gap(p_sid, v_pred);
        v_effect := v13_enqueue_effect(p_sid, 'tool', v_prow.request, v_prow.tool_name);
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
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
      v_pred := v13_harness_predecessor(p_sid);
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
    PERFORM v13_closeout(p_sid, 'completed', coalesce(v_route->>'reason', 'answered'), false);
    RETURN 'terminal';
  WHEN 'reject' THEN
    PERFORM v13_closeout(p_sid, 'failed', coalesce(v_route->>'reason', 'injection_veto'), false);
    RETURN 'terminal';
  ELSE
    RAISE EXCEPTION 'v13: route returned no action for %', p_sid;
  END CASE;
END $$;

REVOKE EXECUTE ON FUNCTION
  v13_is_harness_tool(text, text),
  v13_json_keys(jsonb),
  v13_json_int_ok(jsonb, numeric),
  v13_canonical_uuid(text),
  v13_pending_human(uuid),
  v13_unconsumed_cancel(uuid),
  v13_harness_request_ok(jsonb),
  v13_reject_bad_harness_request(text, text, jsonb),
  v13_harness_predecessor(uuid),
  v13_harness_tail_gap(uuid, uuid),
  v13_raise_unknown_wall(uuid),
  v13_validate_harness_result_v1(jsonb),
  v13_wake_is_satisfied_v1(uuid, uuid, jsonb),
  v13_state_hash(uuid),
  v13_assert_unknown_wall(uuid),
  v13_closeout(uuid, text, text, boolean),
  v13_cancel(uuid),
  v13_resolve_unknown(uuid, text, jsonb),
  v13_control_event_guard(),
  v13_material_spent_guard(),
  v13_unknown_wall_bijection(),
  v13_enqueue_effect(uuid, text, jsonb, text),
  v13_complete(uuid, integer, bigint, text, jsonb),
  v13_requeue_stale(),
  v13_advance(uuid, jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_is_harness_tool(text, text),
  v13_json_keys(jsonb),
  v13_json_int_ok(jsonb, numeric),
  v13_canonical_uuid(text),
  v13_pending_human(uuid),
  v13_unconsumed_cancel(uuid),
  v13_harness_request_ok(jsonb),
  v13_reject_bad_harness_request(text, text, jsonb),
  v13_harness_predecessor(uuid),
  v13_harness_tail_gap(uuid, uuid),
  v13_raise_unknown_wall(uuid),
  v13_validate_harness_result_v1(jsonb),
  v13_wake_is_satisfied_v1(uuid, uuid, jsonb),
  v13_state_hash(uuid),
  v13_assert_unknown_wall(uuid),
  v13_closeout(uuid, text, text, boolean),
  v13_cancel(uuid),
  v13_resolve_unknown(uuid, text, jsonb),
  v13_enqueue_effect(uuid, text, jsonb, text),
  v13_complete(uuid, integer, bigint, text, jsonb),
  v13_requeue_stale(),
  v13_advance(uuid, jsonb)
TO v13_route;
REVOKE SELECT ON effects FROM v13_recall;

COMMIT;
