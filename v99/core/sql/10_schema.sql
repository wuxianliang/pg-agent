-- Phase 0 storage only. Lifecycle writers are added in 20/30; ACL in 40.
CREATE FUNCTION v99_core.v99_core_valid_interaction(p_value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v99_core AS $$
    SELECT CASE WHEN p_value IS NULL THEN true
      WHEN jsonb_typeof(p_value) <> 'object' THEN false
      ELSE COALESCE(
        (SELECT count(*) = 3 FROM jsonb_object_keys(p_value))
        AND jsonb_typeof(p_value->'id') = 'string'
        AND (p_value->>'id') ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        AND jsonb_typeof(p_value->'kind') = 'string'
        AND length(btrim(p_value->>'kind')) > 0
        AND p_value->>'channel' IN ('human', 'ce'), false) END
$$;

CREATE TABLE v99_core.core_runs (
    run_id uuid CONSTRAINT v99_core_runs_pk PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    registration_generation bigint NOT NULL DEFAULT 1 CONSTRAINT v99_core_runs_registration CHECK (registration_generation = 1),
    current_epoch_ordinal bigint NOT NULL DEFAULT 1 CONSTRAINT v99_core_runs_epoch CHECK (current_epoch_ordinal > 0),
    continuity_generation bigint NOT NULL DEFAULT 1 CONSTRAINT v99_core_runs_continuity CHECK (continuity_generation = 1),
    turn_ordinal bigint NOT NULL DEFAULT 1 CONSTRAINT v99_core_runs_turn CHECK (turn_ordinal > 0),
    status text NOT NULL CONSTRAINT v99_core_runs_status CHECK (status IN ('running','waiting_for_input','completed','failed','cancelled','blocked_unknown')),
    interaction jsonb CONSTRAINT v99_core_runs_interaction CHECK (v99_core.v99_core_valid_interaction(interaction)),
    failure_reason jsonb,
    revision bigint NOT NULL DEFAULT 1 CONSTRAINT v99_core_runs_revision CHECK (revision > 0),
    context_revision bigint NOT NULL DEFAULT 1 CONSTRAINT v99_core_runs_context CHECK (context_revision > 0),
    driving_operation_id uuid,
    driver_owner text,
    driver_lease_until timestamptz,
    driver_fence bigint NOT NULL DEFAULT 0 CONSTRAINT v99_core_runs_driver_fence CHECK (driver_fence >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE v99_core.core_epochs (
    epoch_id uuid CONSTRAINT v99_core_epochs_pk PRIMARY KEY,
    run_id uuid NOT NULL CONSTRAINT v99_core_epochs_run_fk REFERENCES v99_core.core_runs(run_id),
    ordinal bigint NOT NULL CONSTRAINT v99_core_epochs_ordinal CHECK (ordinal > 0),
    continuity_generation bigint NOT NULL CONSTRAINT v99_core_epochs_continuity CHECK (continuity_generation = 1),
    registration_generation bigint NOT NULL CONSTRAINT v99_core_epochs_registration CHECK (registration_generation = 1),
    transition_kind text NOT NULL CONSTRAINT v99_core_epochs_transition CHECK (transition_kind IN ('initial','steering')),
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    CONSTRAINT v99_core_epochs_run_ordinal UNIQUE (run_id, ordinal),
    CONSTRAINT v99_core_epochs_run_id UNIQUE (run_id, epoch_id)
);
CREATE UNIQUE INDEX v99_core_epochs_open ON v99_core.core_epochs(run_id) WHERE closed_at IS NULL;

CREATE TABLE v99_core.core_operations (
    operation_id uuid CONSTRAINT v99_core_operations_pk PRIMARY KEY,
    request_id text NOT NULL CONSTRAINT v99_core_operations_request_unique UNIQUE
        CONSTRAINT v99_core_operations_request CHECK (octet_length(request_id) BETWEEN 1 AND 512),
    run_id uuid NOT NULL CONSTRAINT v99_core_operations_run_fk REFERENCES v99_core.core_runs(run_id),
    epoch_id uuid NOT NULL CONSTRAINT v99_core_operations_epoch_fk REFERENCES v99_core.core_epochs(epoch_id),
    verb text NOT NULL CONSTRAINT v99_core_operations_verb CHECK (verb IN ('start','steer','respond','cancel','admit_turn','admit_tool')),
    turn_ordinal bigint NOT NULL CONSTRAINT v99_core_operations_turn CHECK (turn_ordinal > 0),
    attempt_seq bigint NOT NULL CONSTRAINT v99_core_operations_attempt CHECK (attempt_seq > 0),
    status text NOT NULL CONSTRAINT v99_core_operations_status CHECK (status IN ('pending','completed','archived','closed')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CONSTRAINT v99_core_operations_payload CHECK (octet_length(payload::text) <= 1048576),
    payload_digest text NOT NULL,
    result jsonb,
    archive_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT v99_core_operations_run_attempt UNIQUE (run_id, attempt_seq),
    CONSTRAINT v99_core_operations_run_id UNIQUE (run_id, operation_id),
    CONSTRAINT v99_core_operations_run_epoch_fk FOREIGN KEY (run_id, epoch_id) REFERENCES v99_core.core_epochs(run_id, epoch_id),
    CONSTRAINT v99_core_operations_control_completed CHECK (
        verb IN ('admit_turn','admit_tool') OR (status = 'completed' AND completed_at IS NOT NULL)),
    CONSTRAINT v99_core_operations_tool_payload CHECK (verb <> 'admit_tool' OR
        (jsonb_typeof(payload) = 'object' AND payload ?& ARRAY['source_operation_id','tool_call_index','tool','params']))
);
ALTER TABLE v99_core.core_runs ADD CONSTRAINT v99_core_runs_driving_fk
    FOREIGN KEY (run_id, driving_operation_id) REFERENCES v99_core.core_operations(run_id, operation_id);

CREATE TABLE v99_core.core_effects (
    effect_id uuid CONSTRAINT v99_core_effects_pk PRIMARY KEY,
    run_id uuid NOT NULL CONSTRAINT v99_core_effects_run_fk REFERENCES v99_core.core_runs(run_id),
    operation_id uuid NOT NULL,
    kind text NOT NULL CONSTRAINT v99_core_effects_kind CHECK (kind IN ('llm','tool','human')),
    tool_name text,
    request jsonb NOT NULL,
    request_digest text NOT NULL,
    idempotency_key text NOT NULL,
    epoch_ordinal bigint NOT NULL CONSTRAINT v99_core_effects_epoch CHECK (epoch_ordinal > 0),
    turn_ordinal bigint NOT NULL CONSTRAINT v99_core_effects_turn CHECK (turn_ordinal > 0),
    attempt_no integer NOT NULL DEFAULT 0 CONSTRAINT v99_core_effects_attempt CHECK (attempt_no >= 0),
    fence bigint NOT NULL DEFAULT 0 CONSTRAINT v99_core_effects_fence CHECK (fence >= 0),
    claim_driver_fence bigint,
    cancel_requested boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'ready' CONSTRAINT v99_core_effects_status CHECK (status IN ('ready','claimed','succeeded','failed','unknown','cancelled')),
    result jsonb,
    error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v99_core_effects_tool_name CHECK (kind <> 'tool' OR tool_name IS NOT NULL),
    CONSTRAINT v99_core_effects_run_key UNIQUE (run_id, idempotency_key),
    CONSTRAINT v99_core_effects_run_id UNIQUE (run_id, effect_id),
    CONSTRAINT v99_core_effects_operation_fk FOREIGN KEY (run_id, operation_id) REFERENCES v99_core.core_operations(run_id, operation_id),
    CONSTRAINT v99_core_effects_epoch_fk FOREIGN KEY (run_id, epoch_ordinal) REFERENCES v99_core.core_epochs(run_id, ordinal)
);
CREATE UNIQUE INDEX v99_core_effects_primary ON v99_core.core_effects(operation_id) WHERE kind IN ('llm','tool');
CREATE UNIQUE INDEX v99_core_effects_human ON v99_core.core_effects(operation_id) WHERE kind = 'human';
CREATE UNIQUE INDEX v99_core_effects_claimed ON v99_core.core_effects(run_id) WHERE status = 'claimed';

CREATE TABLE v99_core.core_events (
    run_id uuid NOT NULL CONSTRAINT v99_core_events_run_fk REFERENCES v99_core.core_runs(run_id),
    seq bigint NOT NULL CONSTRAINT v99_core_events_seq CHECK (seq > 0),
    event_id uuid NOT NULL CONSTRAINT v99_core_events_id UNIQUE,
    type text NOT NULL CONSTRAINT v99_core_events_type CHECK (type IN (
        'user/message','effect/claimed','effect/done','effect/unknown','receipt/mismatch','receipt/late',
        'run/steering_requested','run/snapshot','run/cancel_requested','run/closed',
        'llm/message','tool/call','tool/result','human/responded')),
    payload jsonb NOT NULL,
    payload_hash text NOT NULL,
    source_effect_id uuid,
    epoch_ordinal bigint,
    turn_ordinal bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v99_core_events_pk PRIMARY KEY (run_id, seq),
    CONSTRAINT v99_core_events_effect_fk FOREIGN KEY (run_id, source_effect_id) REFERENCES v99_core.core_effects(run_id, effect_id),
    CONSTRAINT v99_core_events_epoch_fk FOREIGN KEY (run_id, epoch_ordinal) REFERENCES v99_core.core_epochs(run_id, ordinal)
);
CREATE UNIQUE INDEX v99_core_events_closed ON v99_core.core_events(run_id, epoch_ordinal) WHERE type = 'run/closed';

CREATE TABLE v99_core.core_snapshots (
    run_id uuid CONSTRAINT v99_core_snapshots_pk PRIMARY KEY CONSTRAINT v99_core_snapshots_run_fk REFERENCES v99_core.core_runs(run_id),
    registration_generation bigint NOT NULL CONSTRAINT v99_core_snapshots_registration CHECK (registration_generation = 1),
    epoch_ordinal bigint NOT NULL,
    turn_ordinal bigint NOT NULL CONSTRAINT v99_core_snapshots_turn CHECK (turn_ordinal > 0),
    revision bigint NOT NULL CONSTRAINT v99_core_snapshots_revision CHECK (revision > 0),
    status text NOT NULL CONSTRAINT v99_core_snapshots_status CHECK (status IN ('running','waiting_for_input','completed','failed','cancelled','blocked_unknown')),
    interaction jsonb CONSTRAINT v99_core_snapshots_interaction CHECK (v99_core.v99_core_valid_interaction(interaction)),
    assistant_text text,
    failure_reason jsonb,
    last_operation_id uuid,
    interaction_effect_id uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v99_core_snapshots_epoch_fk FOREIGN KEY (run_id, epoch_ordinal) REFERENCES v99_core.core_epochs(run_id, ordinal),
    CONSTRAINT v99_core_snapshots_operation_fk FOREIGN KEY (run_id, last_operation_id) REFERENCES v99_core.core_operations(run_id, operation_id),
    CONSTRAINT v99_core_snapshots_effect_fk FOREIGN KEY (run_id, interaction_effect_id) REFERENCES v99_core.core_effects(run_id, effect_id)
);
CREATE TABLE v99_core.core_wakes (
    wake_id bigint GENERATED ALWAYS AS IDENTITY CONSTRAINT v99_core_wakes_pk PRIMARY KEY,
    run_id uuid NOT NULL CONSTRAINT v99_core_wakes_run_fk REFERENCES v99_core.core_runs(run_id),
    registration_generation bigint NOT NULL CONSTRAINT v99_core_wakes_registration CHECK (registration_generation = 1),
    epoch_ordinal bigint NOT NULL,
    reason text NOT NULL CONSTRAINT v99_core_wakes_reason CHECK (reason IN ('snapshot','steering_requested','terminal','cancelled')),
    steering_message text,
    interaction jsonb CONSTRAINT v99_core_wakes_interaction CHECK (v99_core.v99_core_valid_interaction(interaction)),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v99_core_wakes_epoch_fk FOREIGN KEY (run_id, epoch_ordinal) REFERENCES v99_core.core_epochs(run_id, ordinal)
);
CREATE INDEX v99_core_wakes_cursor ON v99_core.core_wakes(run_id, registration_generation, wake_id);
CREATE TABLE v99_core.core_effect_pins (
    effect_id uuid NOT NULL CONSTRAINT v99_core_pins_effect_fk REFERENCES v99_core.core_effects(effect_id),
    attempt_no integer NOT NULL CONSTRAINT v99_core_pins_attempt CHECK (attempt_no > 0),
    fence bigint NOT NULL CONSTRAINT v99_core_pins_fence CHECK (fence > 0),
    driver_fence bigint CONSTRAINT v99_core_pins_driver CHECK (driver_fence > 0),
    context_revision bigint NOT NULL CONSTRAINT v99_core_pins_context CHECK (context_revision > 0),
    catalog_revision bigint NOT NULL CONSTRAINT v99_core_pins_catalog CHECK (catalog_revision > 0),
    request_digest text NOT NULL,
    claimed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v99_core_pins_pk PRIMARY KEY (effect_id, attempt_no, fence)
);
CREATE TABLE v99_core.core_requests (
    request_id text CONSTRAINT v99_core_requests_pk PRIMARY KEY CONSTRAINT v99_core_requests_id CHECK (octet_length(request_id) BETWEEN 1 AND 512),
    kind text NOT NULL CONSTRAINT v99_core_requests_kind CHECK (kind IN ('start','steer','respond','cancel','receipt')),
    request_digest text NOT NULL CONSTRAINT v99_core_requests_digest CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    run_id uuid NOT NULL CONSTRAINT v99_core_requests_run_fk REFERENCES v99_core.core_runs(run_id),
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE v99_core.core_tools (
    name text CONSTRAINT v99_core_tools_pk PRIMARY KEY,
    description text NOT NULL,
    schema jsonb NOT NULL,
    enabled boolean NOT NULL
);
CREATE TABLE v99_core.core_meta (
    singleton boolean CONSTRAINT v99_core_meta_pk PRIMARY KEY CONSTRAINT v99_core_meta_singleton CHECK (singleton),
    catalog_revision bigint NOT NULL CONSTRAINT v99_core_meta_revision CHECK (catalog_revision > 0)
);
INSERT INTO v99_core.core_meta VALUES (true, 1);
INSERT INTO v99_core.core_tools VALUES (
    'spawn_subsession', 'Simulate a subsession with the Phase 0 Fake adapter; no child run is created.',
    '{"type":"object","additionalProperties":false,"required":["task"],"properties":{"task":{"type":"string","minLength":1,"maxLength":1024}}}', true);

CREATE FUNCTION v99_core.v99_core_immutable()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, v99_core AS $$
BEGIN
    RAISE EXCEPTION 'v99 core audit relation % is immutable', TG_TABLE_NAME USING ERRCODE = '23514';
END
$$;
CREATE TRIGGER v99_core_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON v99_core.core_events
    FOR EACH STATEMENT EXECUTE FUNCTION v99_core.v99_core_immutable();
CREATE TRIGGER v99_core_pins_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON v99_core.core_effect_pins
    FOR EACH STATEMENT EXECUTE FUNCTION v99_core.v99_core_immutable();
CREATE TRIGGER v99_core_requests_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON v99_core.core_requests
    FOR EACH STATEMENT EXECUTE FUNCTION v99_core.v99_core_immutable();

CREATE FUNCTION v99_core.v99_core_effect_binding()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, v99_core AS $$
DECLARE binding_id uuid;
BEGIN
    -- A shared trigger must never dereference fields absent from NEW's row
    -- type (operations has no effect_id); select the key before querying.
    IF TG_TABLE_NAME = 'core_effects' THEN
        binding_id := NEW.effect_id;
    ELSE
        binding_id := NEW.operation_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM v99_core.core_effects e
        JOIN v99_core.core_operations o ON o.operation_id = e.operation_id
        JOIN v99_core.core_epochs ep ON ep.epoch_id = o.epoch_id
        WHERE (CASE WHEN TG_TABLE_NAME = 'core_effects' THEN e.effect_id = binding_id
                    ELSE o.operation_id = binding_id END)
          AND (e.run_id <> o.run_id OR e.epoch_ordinal <> ep.ordinal
               OR e.turn_ordinal <> o.turn_ordinal
               OR NOT ((o.verb = 'admit_turn' AND e.kind IN ('llm','human'))
                       OR (o.verb = 'admit_tool' AND e.kind = 'tool')))
    ) THEN
        RAISE EXCEPTION 'effect must match admission run/epoch/turn/kind' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END
$$;
CREATE CONSTRAINT TRIGGER v99_core_effect_binding AFTER INSERT OR UPDATE ON v99_core.core_effects
    DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION v99_core.v99_core_effect_binding();
CREATE CONSTRAINT TRIGGER v99_core_operation_binding AFTER UPDATE ON v99_core.core_operations
    DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION v99_core.v99_core_effect_binding();

CREATE FUNCTION v99_core.v99_core_pin_binding()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, v99_core AS $$
DECLARE effect_kind text;
BEGIN
    SELECT kind INTO STRICT effect_kind FROM v99_core.core_effects WHERE effect_id = NEW.effect_id;
    IF (effect_kind = 'human') <> (NEW.driver_fence IS NULL) THEN
        RAISE EXCEPTION 'only human pins have NULL driver_fence' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER v99_core_pin_binding BEFORE INSERT ON v99_core.core_effect_pins
    FOR EACH ROW EXECUTE FUNCTION v99_core.v99_core_pin_binding();

-- Lock meta before any tool rows. Maintenance never takes a run lock.
CREATE FUNCTION v99_core.v99_core_catalog_changed()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, v99_core AS $$
BEGIN
    UPDATE v99_core.core_meta SET catalog_revision = catalog_revision + 1 WHERE singleton;
    IF NOT FOUND THEN RAISE EXCEPTION 'missing catalog revision'; END IF;
    RETURN NULL;
END
$$;
CREATE TRIGGER v99_core_catalog_changed BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON v99_core.core_tools
    FOR EACH STATEMENT EXECUTE FUNCTION v99_core.v99_core_catalog_changed();
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v99_core FROM PUBLIC;
