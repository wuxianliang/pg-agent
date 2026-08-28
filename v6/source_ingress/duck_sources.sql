-- v6 W3 metadata: PostgreSQL remains the source of truth for DuckDB workbench state.
CREATE TABLE IF NOT EXISTS duck_workbench_sessions (
    run_id text PRIMARY KEY REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    session_mode text NOT NULL DEFAULT 'temp'
        CHECK (session_mode IN ('temp', 'run_schema')),
    status text NOT NULL DEFAULT 'NEW'
        CHECK (status IN ('NEW', 'OPEN', 'DEGRADED', 'LOST', 'TERMINAL')),
    next_op_seq bigint NOT NULL DEFAULT 1 CHECK (next_op_seq > 0),
    last_completed_op_seq bigint NOT NULL DEFAULT 0 CHECK (last_completed_op_seq >= 0),
    worker_id text,
    session_generation integer NOT NULL DEFAULT 0 CHECK (session_generation >= 0),
    last_error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS duck_artifacts (
    run_id text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    artifact_name text NOT NULL,
    artifact_kind text NOT NULL CHECK (artifact_kind IN ('source', 'view')),
    artifact_status text NOT NULL DEFAULT 'ACTIVE'
        CHECK (artifact_status IN ('ACTIVE', 'DROPPED', 'UNAVAILABLE', 'LOST')),
    source_id text,
    source_schema text,
    source_table text,
    ingest_mode text NOT NULL DEFAULT 'snapshot'
        CHECK (ingest_mode IN ('snapshot')),
    definition_sql text,
    depends_on jsonb NOT NULL DEFAULT '[]'::jsonb,
    columns jsonb NOT NULL DEFAULT '[]'::jsonb,
    definition_hash text NOT NULL,
    generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, artifact_name),
    CHECK (artifact_kind = 'source' OR definition_sql IS NOT NULL),
    CHECK (artifact_kind = 'source' OR source_id IS NULL)
);

CREATE TABLE IF NOT EXISTS duck_operations (
    request_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    op_seq bigint NOT NULL CHECK (op_seq > 0),
    op_kind text NOT NULL CHECK (op_kind IN (
        'register', 'query', 'brief_query', 'list', 'columns',
        'show_create', 'drop', 'hydrate')),
    queue_msg_id bigint,
    status text NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DLQ', 'REPLAYED')),
    artifact_name text,
    request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_summary jsonb,
    error jsonb,
    definition_hash text,
    worker_id text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, op_seq)
);

CREATE INDEX IF NOT EXISTS duck_artifacts_run_status_idx
    ON duck_artifacts (run_id, artifact_status, artifact_name);
CREATE INDEX IF NOT EXISTS duck_operations_run_seq_idx
    ON duck_operations (run_id, op_seq);
CREATE INDEX IF NOT EXISTS duck_operations_status_idx
    ON duck_operations (status, created_at);

CREATE OR REPLACE FUNCTION duck_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS duck_workbench_sessions_touch ON duck_workbench_sessions;
CREATE TRIGGER duck_workbench_sessions_touch
BEFORE UPDATE ON duck_workbench_sessions
FOR EACH ROW EXECUTE FUNCTION duck_touch_updated_at();

DROP TRIGGER IF EXISTS duck_artifacts_touch ON duck_artifacts;
CREATE TRIGGER duck_artifacts_touch
BEFORE UPDATE ON duck_artifacts
FOR EACH ROW EXECUTE FUNCTION duck_touch_updated_at();
