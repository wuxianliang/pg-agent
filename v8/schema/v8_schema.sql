-- v8 G2: core database schema (tables, constraints, immutability triggers).
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digests
-- docs/analysis/v8-impl-digest/s31a-*, s31b-*, s32a-*, s32b-*.
-- The stage database is dropped and recreated by setup_db.py on every run,
-- so no IF NOT EXISTS / CREATE OR REPLACE is used.
--
-- Scope guard: this file is the schema foundation only. Command logic
-- (append/seal/dispatch/complete) is layered on top by later stages.

-- ---------------------------------------------------------------------------
-- sessions: control row (15-column closed list, s31a section 1.1)
-- ---------------------------------------------------------------------------
CREATE TABLE sessions (
    session_id                uuid PRIMARY KEY,
    driver                    text NOT NULL,
    driver_epoch              bigint NOT NULL DEFAULT 1 CHECK (driver_epoch >= 1),
    driver_mode               text NOT NULL DEFAULT 'active'
                              CONSTRAINT sessions_driver_mode_check
                              CHECK (driver_mode IN ('active', 'quiescing')),
    state                     text NOT NULL DEFAULT 'ready'
                              CONSTRAINT sessions_state_check
                              CHECK (state IN ('ready', 'claimed', 'waiting_effect',
                                               'waiting_event', 'sleeping',
                                               'cancel_requested',
                                               'blocked_unknown_effect',
                                               'completed', 'failed', 'cancelled')),
    session_fence             bigint NOT NULL DEFAULT 1 CHECK (session_fence >= 1),
    lease_owner               text,
    lease_until               timestamptz,
    lease_purpose             text,
    active_step_id            uuid,
    drain_step_id             uuid,
    next_seq                  bigint NOT NULL DEFAULT 1 CHECK (next_seq >= 1),
    cancellation_epoch        bigint NOT NULL DEFAULT 0 CHECK (cancellation_epoch >= 0),
    failure_code              text,
    active_catalog_generation uuid,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

-- New session rows MUST start in the frozen initial state (state=ready,
-- driver_mode=active, session_fence=1, driver_epoch=1, next_seq=1,
-- cancellation_epoch=0, lease/pointer/failure columns NULL).
-- Implemented as a BEFORE INSERT trigger rather than a table CHECK because
-- later legitimate transitions (claim, fail, ...) must be allowed to update
-- these very columns; the constraint only applies at insert time.
CREATE FUNCTION v8_sessions_initial_row() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state <> 'ready'
       OR NEW.driver_mode <> 'active'
       OR NEW.session_fence <> 1
       OR NEW.driver_epoch <> 1
       OR NEW.next_seq <> 1
       OR NEW.cancellation_epoch <> 0
       OR NEW.lease_owner IS NOT NULL
       OR NEW.lease_until IS NOT NULL
       OR NEW.lease_purpose IS NOT NULL
       OR NEW.active_step_id IS NOT NULL
       OR NEW.drain_step_id IS NOT NULL
       OR NEW.failure_code IS NOT NULL THEN
        RAISE EXCEPTION
            'new session rows must start in the frozen initial state '
            '(state=ready, driver_mode=active, session_fence=1, driver_epoch=1, '
            'next_seq=1, cancellation_epoch=0, lease/pointer/failure columns NULL)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sessions_initial_row
BEFORE INSERT ON sessions
FOR EACH ROW EXECUTE FUNCTION v8_sessions_initial_row();

-- ---------------------------------------------------------------------------
-- steps (s32a section 1.1; decision marks decision_only/final_tools are read
-- from the steps row by aggregation read-list B, so they are persisted here)
-- ---------------------------------------------------------------------------
CREATE TABLE steps (
    step_id                uuid PRIMARY KEY,
    session_id             uuid NOT NULL REFERENCES sessions(session_id),
    turn_id                uuid NOT NULL,
    status                 text NOT NULL
                           CONSTRAINT steps_status_check
                           CHECK (status IN ('planned', 'ready', 'waiting_effect',
                                             'failed_retryable', 'cancel_requested',
                                             'blocked_unknown_effect', 'succeeded',
                                             'failed_terminal', 'cancelled')),
    stage                  text NOT NULL
                           CONSTRAINT steps_stage_check
                           CHECK (stage IN ('decision', 'tools', 'closed')),
    plan_hash              text,
    -- Normalized tools plan canonical text persisted by the successful
    -- decision settlement (digest s31b 2.6.1: the successful decision
    -- result MUST persist the normalized tools plan); plan_hash is its
    -- SHA-256. The decision_only branch persists no plan value — its empty
    -- plan is fully determined by the decision_only mark.
    plan_canonical        text,
    sealed_batch_no        bigint NOT NULL DEFAULT 0 CHECK (sealed_batch_no >= 0),
    pending_effect_count   bigint NOT NULL DEFAULT 0 CHECK (pending_effect_count >= 0),
    unknown_effect_count   bigint NOT NULL DEFAULT 0 CHECK (unknown_effect_count >= 0),
    retryable_effect_count bigint NOT NULL DEFAULT 0 CHECK (retryable_effect_count >= 0),
    terminal_effect_count  bigint NOT NULL DEFAULT 0 CHECK (terminal_effect_count >= 0),
    cancellation_epoch     bigint NOT NULL DEFAULT 0 CHECK (cancellation_epoch >= 0),
    -- Derived caches for display/aggregation statistics only; the retry
    -- budget authority is the effect-level max_attempts (frozen).
    retry_count            bigint NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries            bigint NOT NULL DEFAULT 0 CHECK (max_retries >= 0),
    outcome_code           text,
    decision_only          boolean,
    final_tools            boolean,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    closed_at              timestamptz
);

-- Single-active-step model: at most one non-terminal step per session.
-- The partial unique index is the authoritative truth source; the session's
-- active_step_id / drain_step_id are locating pointers only.
CREATE UNIQUE INDEX steps_one_active_per_session
    ON steps (session_id)
    WHERE status NOT IN ('succeeded', 'failed_terminal', 'cancelled');

-- Session pointer FKs (added after steps exists; circular with sessions).
ALTER TABLE sessions
    ADD CONSTRAINT sessions_active_step_fk
        FOREIGN KEY (active_step_id) REFERENCES steps(step_id),
    ADD CONSTRAINT sessions_drain_step_fk
        FOREIGN KEY (drain_step_id) REFERENCES steps(step_id);

-- ---------------------------------------------------------------------------
-- session_events: append-only event log (s31b section 1.6)
-- ---------------------------------------------------------------------------
CREATE TABLE session_events (
    seq                       bigint NOT NULL CHECK (seq >= 1),
    session_id                uuid NOT NULL REFERENCES sessions(session_id),
    event_type                text NOT NULL,
    event_class               text NOT NULL
                              CONSTRAINT session_events_class_check
                              CHECK (event_class IN ('semantic', 'observational', 'audit')),
    schema_version            text NOT NULL,
    canonicalizer_version     text NOT NULL,
    event_key                 text NOT NULL,
    turn_id                   uuid,
    step_id                   uuid,
    effect_id                 uuid,
    payload                   text NOT NULL,
    payload_hash              text NOT NULL,
    semantic_input_ordinal    bigint
                              CONSTRAINT session_events_public_ordinal_range
                              CHECK (semantic_input_ordinal BETWEEN 1 AND 9223372036854775807),
    internal_semantic_ordinal bigint,
    attempt_no                bigint,
    command_id                text,
    batch_item_ordinal        bigint,
    created_at                timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq),
    UNIQUE (session_id, event_key),
    -- Column-level conditional constraint tied to event_class: public
    -- semantic rows carry semantic_input_ordinal only, internal semantic
    -- rows carry internal_semantic_ordinal only, observational/audit rows
    -- carry neither ordinal column.
    CONSTRAINT session_events_ordinal_class_check CHECK (
        (
            event_class = 'semantic'
            AND (
                (semantic_input_ordinal IS NOT NULL AND internal_semantic_ordinal IS NULL)
                OR
                (semantic_input_ordinal IS NULL AND internal_semantic_ordinal IS NOT NULL)
            )
        )
        OR (
            event_class IN ('observational', 'audit')
            AND semantic_input_ordinal IS NULL
            AND internal_semantic_ordinal IS NULL
        )
    )
);

-- Each ordinal space is unique only within its own scope (partial indexes).
CREATE UNIQUE INDEX session_events_public_ordinal
    ON session_events (session_id, semantic_input_ordinal)
    WHERE semantic_input_ordinal IS NOT NULL;
CREATE UNIQUE INDEX session_events_internal_ordinal
    ON session_events (session_id, internal_semantic_ordinal)
    WHERE internal_semantic_ordinal IS NOT NULL;

-- session_events is append-only: no UPDATE, no DELETE, ever.
CREATE FUNCTION v8_session_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'session_events is append-only';
END;
$$;

CREATE TRIGGER trg_session_events_append_only
BEFORE UPDATE OR DELETE ON session_events
FOR EACH ROW EXECUTE FUNCTION v8_session_events_append_only();

-- ---------------------------------------------------------------------------
-- batches: sealed batch carrier (slots live on effect_requests rows)
-- ---------------------------------------------------------------------------
CREATE TABLE batches (
    batch_id        uuid PRIMARY KEY,
    session_id      uuid NOT NULL REFERENCES sessions(session_id),
    step_id         uuid NOT NULL REFERENCES steps(step_id),
    sealed_batch_no bigint NOT NULL CHECK (sealed_batch_no >= 0),
    kind            text NOT NULL
                    CONSTRAINT batches_kind_check
                    CHECK (kind IN ('decision', 'tools')),
    sealed          boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, step_id, sealed_batch_no)
);

-- ---------------------------------------------------------------------------
-- effect_requests: logical effect parent table (s32a section 1.2)
-- ---------------------------------------------------------------------------
CREATE TABLE effect_requests (
    effect_id              uuid PRIMARY KEY,
    session_id             uuid NOT NULL REFERENCES sessions(session_id),
    step_id                uuid NOT NULL REFERENCES steps(step_id),
    batch_id               uuid NOT NULL REFERENCES batches(batch_id),
    dispatch_ordinal       bigint NOT NULL CHECK (dispatch_ordinal >= 0),
    tool_call_id           text,
    effect_kind            text NOT NULL,
    -- Authoritative execution-mode column (N05): written by the creating
    -- transaction, immutable afterwards.
    execution_mode         text NOT NULL
                           CONSTRAINT effect_requests_execution_mode_check
                           CHECK (execution_mode IN ('streaming', 'non_streaming')),
    driver                 text NOT NULL,
    driver_epoch           bigint NOT NULL CHECK (driver_epoch >= 1),
    -- Display copies of the current attempt's frozen execution snapshot.
    session_fence          bigint NOT NULL CHECK (session_fence >= 1),
    dispatch_session_fence bigint NOT NULL CHECK (dispatch_session_fence >= 1),
    -- Completion write-permission fence: the sole stale-judgment authority.
    current_job_fence      bigint NOT NULL CHECK (current_job_fence >= 1),
    request_hash           text NOT NULL,
    idempotency_key        text NOT NULL,
    -- Parent derived execution snapshot of the current (max attempt_no) row;
    -- same nine-value domain as effect_attempts.status, not a judgment source.
    status                 text NOT NULL
                           CONSTRAINT effect_requests_status_check
                           CHECK (status IN ('planned', 'ready', 'dispatch_started',
                                             'succeeded', 'failed_retryable',
                                             'failed_terminal',
                                             'cancelled_before_dispatch',
                                             'cancelled_after_dispatch',
                                             'unknown_outcome')),
    retry_class            text NOT NULL
                           CONSTRAINT effect_requests_retry_class_check
                           CHECK (retry_class IN ('provider_idempotent',
                                                  'verifiable_no_effect', 'unsafe')),
    max_attempts           bigint NOT NULL CHECK (max_attempts >= 1),
    -- Classification output column / verifiable cache (R-01), not a
    -- judgment input.
    retry_stop_reason      text
                           CONSTRAINT effect_requests_retry_stop_reason_check
                           CHECK (retry_stop_reason IN ('budget_exhausted',
                                                        'first_attempt_failure',
                                                        'not_retry_eligible')),
    attempt_no             bigint NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
    dispatch_count         bigint NOT NULL DEFAULT 0 CHECK (dispatch_count >= 0),
    provider_request_id    text,
    result_hash            text,
    grant_id               text,
    lease_owner            text,
    lease_until            timestamptz,
    dispatched_at          timestamptz,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    -- Composite unique column group referenced by the effect_attempts
    -- composite FK (ownership consistency).
    UNIQUE (effect_id, session_id, step_id),
    -- Sealed batch slot immutability carriers.
    UNIQUE (session_id, step_id, batch_id, dispatch_ordinal)
);

-- Tool slots: tool_call_id is unique within a batch; decision slots have no
-- tool_call_id, so the constraint applies only where it is NOT NULL.
CREATE UNIQUE INDEX effect_requests_tool_slot
    ON effect_requests (session_id, batch_id, tool_call_id)
    WHERE tool_call_id IS NOT NULL;

-- Effect-level immutable metadata (retry_class/max_attempts/request_hash/
-- idempotency_key/execution_mode/driver/driver_epoch) is frozen at creation;
-- any UPDATE to these columns is rejected. Execution authority columns
-- (status, dispatch_count, current_job_fence, ...) stay updatable.
CREATE FUNCTION v8_effect_requests_metadata_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.retry_class IS DISTINCT FROM NEW.retry_class
       OR OLD.max_attempts IS DISTINCT FROM NEW.max_attempts
       OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
       OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
       OR OLD.execution_mode IS DISTINCT FROM NEW.execution_mode
       OR OLD.driver IS DISTINCT FROM NEW.driver
       OR OLD.driver_epoch IS DISTINCT FROM NEW.driver_epoch THEN
        RAISE EXCEPTION
            'effect_requests immutable metadata (retry_class, max_attempts, '
            'request_hash, idempotency_key, execution_mode, driver, '
            'driver_epoch) cannot be updated';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_effect_requests_metadata_immutable
BEFORE UPDATE ON effect_requests
FOR EACH ROW EXECUTE FUNCTION v8_effect_requests_metadata_immutable();

-- ---------------------------------------------------------------------------
-- effect_attempts: per-execution attempt authority table (s32b section 1.1)
-- ---------------------------------------------------------------------------
CREATE TABLE effect_attempts (
    effect_id               uuid NOT NULL,
    attempt_no              bigint NOT NULL CHECK (attempt_no >= 1),
    session_id              uuid NOT NULL,
    step_id                 uuid NOT NULL,
    driver                  text NOT NULL,
    driver_epoch            bigint NOT NULL CHECK (driver_epoch >= 1),
    session_fence           bigint NOT NULL CHECK (session_fence >= 1),
    dispatch_session_fence  bigint NOT NULL CHECK (dispatch_session_fence >= 1),
    dispatch_job_fence      bigint NOT NULL CHECK (dispatch_job_fence >= 1),
    request_hash            text NOT NULL,
    idempotency_key         text NOT NULL,
    execution_mode          text NOT NULL
                            CONSTRAINT effect_attempts_execution_mode_check
                            CHECK (execution_mode IN ('streaming', 'non_streaming')),
    status                  text NOT NULL
                            CONSTRAINT effect_attempts_status_check
                            CHECK (status IN ('planned', 'ready', 'dispatch_started',
                                              'succeeded', 'failed_retryable',
                                              'failed_terminal',
                                              'cancelled_before_dispatch',
                                              'cancelled_after_dispatch',
                                              'unknown_outcome')),
    superseded_by_attempt_no bigint
                             CONSTRAINT effect_attempts_superseded_gt
                             CHECK (superseded_by_attempt_no > attempt_no),
    dispatched_at           timestamptz,
    provider_request_id     text,
    result_hash             text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    completed_at            timestamptz,
    PRIMARY KEY (effect_id, attempt_no),
    UNIQUE (effect_id, dispatch_job_fence),
    -- Composite FK: ownership must match the same effect_requests row;
    -- cross effect-session-step combinations are rejected by the database.
    FOREIGN KEY (effect_id, session_id, step_id)
        REFERENCES effect_requests (effect_id, session_id, step_id),
    -- Deferred self-reference: the allocating transaction writes the old
    -- attempt's superseded marker before inserting the successor row.
    CONSTRAINT effect_attempts_superseded_fk
        FOREIGN KEY (effect_id, superseded_by_attempt_no)
        REFERENCES effect_attempts (effect_id, attempt_no)
        DEFERRABLE INITIALLY DEFERRED
);

-- Frozen execution-snapshot columns (driver/driver_epoch/session_fence/
-- dispatch_session_fence/dispatch_job_fence/execution_mode) are immutable
-- after creation. superseded_by_attempt_no is write-once: only the first
-- write (NULL -> value) is accepted; afterwards all updates/clears are
-- rejected. The "only via retry_cohort_allocation" path restriction is
-- enforced by the protected function of the later stage.
CREATE FUNCTION v8_effect_attempts_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.driver IS DISTINCT FROM NEW.driver
       OR OLD.driver_epoch IS DISTINCT FROM NEW.driver_epoch
       OR OLD.session_fence IS DISTINCT FROM NEW.session_fence
       OR OLD.dispatch_session_fence IS DISTINCT FROM NEW.dispatch_session_fence
       OR OLD.dispatch_job_fence IS DISTINCT FROM NEW.dispatch_job_fence
       OR OLD.execution_mode IS DISTINCT FROM NEW.execution_mode THEN
        RAISE EXCEPTION
            'effect_attempts frozen execution-snapshot columns are immutable';
    END IF;
    IF OLD.superseded_by_attempt_no IS NOT NULL
       AND NEW.superseded_by_attempt_no IS DISTINCT FROM OLD.superseded_by_attempt_no THEN
        RAISE EXCEPTION
            'effect_attempts.superseded_by_attempt_no is write-once';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_effect_attempts_guard
BEFORE UPDATE ON effect_attempts
FOR EACH ROW EXECUTE FUNCTION v8_effect_attempts_guard();

-- ---------------------------------------------------------------------------
-- command_receipts (s31b section 1.1)
-- ---------------------------------------------------------------------------
CREATE TABLE command_receipts (
    session_id        uuid NOT NULL REFERENCES sessions(session_id),
    command_id        text NOT NULL,
    command_kind      text,
    receipt_key_kind  text NOT NULL
                      CONSTRAINT command_receipts_key_kind_check
                      CHECK (receipt_key_kind IN ('canonical_request_hash',
                                                  'rejection_fingerprint',
                                                  'transport_rejection_key')),
    receipt_key_value text NOT NULL,
    outcome           text NOT NULL
                      CONSTRAINT command_receipts_outcome_check
                      CHECK (outcome IN ('accepted', 'rejected_stale',
                                         'rejected_mismatch', 'repair_required')),
    code              text,
    result_canonical  text,
    result_hash       text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    -- Equivalent to UNIQUE(session_id, command_id, command_request_hash)
    -- with the typed key pair.
    UNIQUE (session_id, command_id, receipt_key_kind, receipt_key_value)
);

-- ---------------------------------------------------------------------------
-- command_bindings (s31b section 1.2)
-- ---------------------------------------------------------------------------
CREATE TABLE command_bindings (
    session_id      uuid NOT NULL REFERENCES sessions(session_id),
    command_id      text NOT NULL,
    first_key_kind  text NOT NULL
                    CONSTRAINT command_bindings_key_kind_check
                    CHECK (first_key_kind IN ('canonical_request_hash',
                                              'rejection_fingerprint',
                                              'transport_rejection_key')),
    first_key_value text NOT NULL,
    first_outcome   text NOT NULL
                    CONSTRAINT command_bindings_outcome_check
                    CHECK (first_outcome IN ('accepted', 'rejected_stale',
                                             'rejected_mismatch', 'repair_required')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, command_id)
);

-- ---------------------------------------------------------------------------
-- turn_end_slots (s31b section 1.4)
-- ---------------------------------------------------------------------------
CREATE TABLE turn_end_slots (
    session_id                    uuid NOT NULL REFERENCES sessions(session_id),
    turn_id                       uuid NOT NULL,
    -- Derived via turn_end_key@v1, never caller-supplied, immutable.
    turn_end_key                  text NOT NULL,
    -- Event key of the current supersedes-chain head.
    head_event_key                text NOT NULL,
    slot_status                   text NOT NULL
                                  CONSTRAINT turn_end_slots_status_check
                                  CHECK (slot_status IN ('provisional', 'known')),
    resolution_identity_canonical bytea,
    -- Slot row version, +1 per protected update (CAS).
    version                       bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    PRIMARY KEY (session_id, turn_id),
    UNIQUE (session_id, turn_id, turn_end_key)
);

-- turn_end_key is immutable forever. The four protected columns
-- (head_event_key, slot_status, resolution_identity_canonical, version)
-- may only change through the protected slot update function of the later
-- stage; that function signals itself via the transaction-local GUC
-- v8.slot_protected_write = 'on'. Outside that path every update is rejected.
CREATE FUNCTION v8_turn_end_slots_protected() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.turn_end_key IS DISTINCT FROM OLD.turn_end_key THEN
        RAISE EXCEPTION 'turn_end_slots.turn_end_key is immutable';
    END IF;
    IF coalesce(current_setting('v8.slot_protected_write', true), '') <> 'on' THEN
        IF NEW.head_event_key IS DISTINCT FROM OLD.head_event_key
           OR NEW.slot_status IS DISTINCT FROM OLD.slot_status
           OR NEW.resolution_identity_canonical IS DISTINCT FROM OLD.resolution_identity_canonical
           OR NEW.version IS DISTINCT FROM OLD.version THEN
            RAISE EXCEPTION
                'turn_end_slots protected columns (head_event_key, slot_status, '
                'resolution_identity_canonical, version) may only be updated by '
                'the protected slot update function';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_turn_end_slots_protected
BEFORE UPDATE ON turn_end_slots
FOR EACH ROW EXECUTE FUNCTION v8_turn_end_slots_protected();

-- ---------------------------------------------------------------------------
-- effect_audit: base columns (s32b section 1.2 + L4-R04 / Q05 joint CHECKs)
-- ---------------------------------------------------------------------------
CREATE TABLE effect_audit (
    audit_id                bigserial PRIMARY KEY,
    -- Taken from the authorized command calling context, never from the
    -- untrusted received binding fields.
    audit_context_session_id uuid NOT NULL,
    session_id              uuid,
    step_id                 uuid,
    effect_id               uuid,
    attempt_no              bigint,
    audit_key_kind          text NOT NULL
                            CONSTRAINT effect_audit_key_kind_check
                            CHECK (audit_key_kind IN ('canonical_binding',
                                                      'malformed_binding',
                                                      'invalid_binding')),
    audit_key_value         text NOT NULL,
    result_fingerprint      text NOT NULL,
    reason                  text NOT NULL,
    internal_op_kind        text
                            CONSTRAINT effect_audit_internal_op_kind_check
                            CHECK (internal_op_kind IN ('failure_drain',
                                                        'shared_cancel_closure',
                                                        'compact_terminal_abort',
                                                        'infra_closure',
                                                        'generation_revocation_drain')),
    parent_command_id       text,
    internal_op_ordinal     bigint,
    created_at              timestamptz NOT NULL DEFAULT now(),
    -- Attribution four columns: all NULL or all NOT NULL.
    CONSTRAINT effect_audit_attribution_all_or_none CHECK (
        (session_id IS NULL AND step_id IS NULL AND effect_id IS NULL AND attempt_no IS NULL)
        OR (session_id IS NOT NULL AND step_id IS NOT NULL
            AND effect_id IS NOT NULL AND attempt_no IS NOT NULL)
    ),
    -- Internal sub-operation triple: all NULL (plain completion audit row)
    -- or all NOT NULL with ordinal >= 0 (Q05).
    CONSTRAINT effect_audit_internal_triple_all_or_none CHECK (
        (internal_op_kind IS NULL AND parent_command_id IS NULL AND internal_op_ordinal IS NULL)
        OR (internal_op_kind IS NOT NULL AND parent_command_id IS NOT NULL
            AND internal_op_ordinal IS NOT NULL AND internal_op_ordinal >= 0)
    ),
    -- Internal rows must carry full effect attribution (L4-R04).
    CONSTRAINT effect_audit_internal_needs_attribution CHECK (
        internal_op_kind IS NULL
        OR (session_id IS NOT NULL AND step_id IS NOT NULL
            AND effect_id IS NOT NULL AND attempt_no IS NOT NULL)
    ),
    UNIQUE NULLS NOT DISTINCT
        (audit_context_session_id, effect_id, attempt_no,
         audit_key_kind, audit_key_value, result_fingerprint, reason,
         internal_op_kind, parent_command_id, internal_op_ordinal)
);
