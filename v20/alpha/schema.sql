-- v20 alpha kernel. Tables are the vertical-loop subset of design 5.
-- Dropped columns are intentional: see docs/plans/v20-alpha-2026-10-14.md §4.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v20_alpha_control') THEN
        CREATE ROLE v20_alpha_control LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v20_alpha_worker') THEN
        CREATE ROLE v20_alpha_worker NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

ALTER ROLE v20_alpha_control LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE v20_alpha_worker NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;

REVOKE CONNECT ON DATABASE agent_v20_alpha FROM PUBLIC;
GRANT CONNECT ON DATABASE agent_v20_alpha TO v20_alpha_control;
REVOKE CONNECT ON DATABASE agent_v20_alpha FROM v20_alpha_worker;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO v20_alpha_control;

CREATE TABLE v20_runtime_catalog (
    profile_identifier text PRIMARY KEY,
    metadata_schema_version integer NOT NULL,
    revision bigint NOT NULL
);

CREATE TABLE v20_sessions (
    session_id text PRIMARY KEY,
    owning_runtime_id text NOT NULL,
    owning_runtime_generation bigint NOT NULL,
    registration_generation bigint NOT NULL,
    last_epoch_ordinal bigint NOT NULL,
    continuity_generation bigint NOT NULL,
    state text NOT NULL CHECK (state IN ('dormant', 'active', 'interrupted', 'terminal')),
    resumable boolean NOT NULL,
    list_hidden boolean NOT NULL DEFAULT false,
    parent_session_id text REFERENCES v20_sessions (session_id),
    revision bigint NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE v20_session_profiles (
    session_id text PRIMARY KEY REFERENCES v20_sessions (session_id),
    name text NOT NULL DEFAULT '',
    workspace_id text,
    is_mcp_originated boolean NOT NULL DEFAULT false,
    created_by_overseer_session_id text,
    document_version integer NOT NULL DEFAULT 9
);

CREATE TABLE v20_session_provider_handles (
    session_id text PRIMARY KEY REFERENCES v20_sessions (session_id),
    epoch_id text,
    attempt_seq bigint,
    provider_session_id text,
    provider_cleanup_handle jsonb,
    codex_conversation_id text,
    codex_rollout_path text,
    codex_mcp_session_key text
);

CREATE TABLE v20_runs (
    run_id text PRIMARY KEY,
    session_id text NOT NULL UNIQUE REFERENCES v20_sessions (session_id),
    revision bigint NOT NULL,
    status text NOT NULL CHECK (status IN (
        'running', 'waiting_for_input', 'completed', 'failed', 'cancelled', 'expired')),
    status_text text,
    latest_assistant_preview text,
    interaction jsonb,
    failure_reason text,
    transcript_item_count integer NOT NULL DEFAULT 0,
    owner_generation bigint NOT NULL,
    owner_backend_pid integer,
    updated_at timestamptz NOT NULL,
    CONSTRAINT v20_runs_id_aliases_session CHECK (run_id = session_id)
);

CREATE TABLE v20_epochs (
    epoch_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES v20_sessions (session_id),
    run_id text NOT NULL REFERENCES v20_runs (run_id),
    ordinal bigint NOT NULL,
    continuity_generation bigint NOT NULL,
    transition_kind text NOT NULL CHECK (transition_kind IN (
        'initial', 'related_follow_up', 'steering', 'unrelated')),
    activation_id text NOT NULL,
    registration_generation bigint NOT NULL,
    closed_at timestamptz,
    UNIQUE (session_id, ordinal)
);

CREATE TABLE v20_operations (
    request_id text PRIMARY KEY,
    verb text NOT NULL CHECK (verb IN (
        'start', 'claim_resume', 'steer', 'respond', 'admit_turn', 'admit_tool')),
    epoch_id text REFERENCES v20_epochs (epoch_id),
    owner_generation bigint,
    attempt_seq bigint NOT NULL,
    snapshot_seq bigint,
    status text NOT NULL CHECK (status IN ('pending', 'completed', 'archived', 'closed')),
    handle_state text NOT NULL CHECK (handle_state IN ('pending', 'present', 'absent')),
    expects_handle boolean NOT NULL,
    depends_on_request_id text REFERENCES v20_operations (request_id),
    input_message text,
    input_retained boolean NOT NULL CHECK (NOT input_retained),
    payload_digest text NOT NULL,
    result jsonb
);

CREATE TABLE v20_provider_handle_attempts (
    request_id text PRIMARY KEY REFERENCES v20_operations (request_id),
    attempt_seq bigint NOT NULL,
    epoch_id text REFERENCES v20_epochs (epoch_id),
    handle jsonb NOT NULL
);

CREATE TABLE v20_turns (
    turn_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES v20_operations (request_id),
    run_id text NOT NULL REFERENCES v20_runs (run_id),
    epoch_id text NOT NULL REFERENCES v20_epochs (epoch_id),
    owner_generation bigint NOT NULL,
    transcript_turn_id text,
    status text NOT NULL CHECK (status IN ('admitted', 'completed')),
    receipt jsonb
);

CREATE TABLE v20_tool_invocations (
    invocation_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES v20_operations (request_id),
    run_id text NOT NULL REFERENCES v20_runs (run_id),
    turn_id text NOT NULL REFERENCES v20_turns (turn_id),
    epoch_id text NOT NULL REFERENCES v20_epochs (epoch_id),
    owner_generation bigint NOT NULL,
    tool_name text NOT NULL,
    status text NOT NULL CHECK (status IN ('admitted', 'completed', 'failed')),
    request_digest text,
    result_digest text,
    lease_deadline timestamptz
);

CREATE TABLE v20_events (
    event_id bigserial PRIMARY KEY,
    kind text NOT NULL,
    session_id text,
    run_id text,
    epoch_id text,
    digest text,
    message text
);

CREATE INDEX v20_events_session_id_idx ON v20_events (session_id);

CREATE TABLE v20_transcript_turns (
    turn_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES v20_sessions (session_id),
    retention_tier text NOT NULL,
    summary jsonb,
    terminal_state text,
    started_at timestamptz NOT NULL,
    completed_at timestamptz
);

CREATE TABLE v20_transcript_activities (
    activity_id text PRIMARY KEY,
    turn_id text NOT NULL REFERENCES v20_transcript_turns (turn_id),
    sequence_index bigint NOT NULL,
    role text NOT NULL,
    item_kind text NOT NULL,
    text text NOT NULL DEFAULT '',
    tool_invocation_id text,
    UNIQUE (turn_id, sequence_index)
);

ALTER TABLE v20_turns
    ADD CONSTRAINT v20_turns_transcript_fk
    FOREIGN KEY (transcript_turn_id) REFERENCES v20_transcript_turns (turn_id);

INSERT INTO v20_runtime_catalog (profile_identifier, metadata_schema_version, revision)
VALUES ('alpha', 1, 1);

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO v20_alpha_control;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM v20_alpha_control;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO v20_alpha_control;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM v20_alpha_worker;
