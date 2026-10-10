-- v23 minimal agent loop: one durable Run table and post-commit wakeups only.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v23_control') THEN
        CREATE ROLE v23_control LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v23_worker') THEN
        CREATE ROLE v23_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

-- Role attributes are part of the v23 boundary and remain deterministic on reset.
ALTER ROLE v23_control LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE v23_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

-- The gate database is private to the control role; the worker is not a database client.
REVOKE CONNECT ON DATABASE agent_v23_minimal_loop FROM PUBLIC;
GRANT CONNECT ON DATABASE agent_v23_minimal_loop TO v23_control;
REVOKE CONNECT ON DATABASE agent_v23_minimal_loop FROM v23_worker;

CREATE TABLE v23_runs (
    run_id uuid PRIMARY KEY,
    parent_run_id uuid REFERENCES v23_runs(run_id),
    status text NOT NULL CHECK (status IN ('ready', 'running', 'waiting_input', 'completed', 'stopped')),
    revision bigint NOT NULL CHECK (revision >= 0),
    turn_budget integer NOT NULL CHECK (turn_budget > 0),
    turns_used integer NOT NULL DEFAULT 0 CHECK (turns_used >= 0 AND turns_used <= turn_budget),
    latest_receipt jsonb,
    active_operation_id uuid,
    active_base_revision bigint,
    active_input_digest text,
    cancel_requested boolean NOT NULL DEFAULT false,
    op_cache jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(op_cache) = 'object'),
    close_reason text CHECK (close_reason IN ('cancelled', 'worker_failed', 'invalid_worker_receipt', 'late_result_after_cancel')),
    CHECK ((status = 'stopped') = (close_reason IS NOT NULL)),
    CHECK ((status = 'running') = (active_operation_id IS NOT NULL)),
    CHECK ((active_operation_id IS NULL AND active_base_revision IS NULL AND active_input_digest IS NULL)
           OR (active_operation_id IS NOT NULL AND active_base_revision IS NOT NULL
               AND active_base_revision > 0 AND active_base_revision <= revision
               AND active_input_digest IS NOT NULL
               AND active_input_digest ~ '^[0-9a-f]{64}$')),
    CHECK (status <> 'waiting_input' OR
           (latest_receipt IS NOT NULL AND latest_receipt->>'outcome' = 'needs_input'
            AND jsonb_typeof(latest_receipt->'input_request') = 'object') IS TRUE),
    CHECK (parent_run_id IS DISTINCT FROM run_id)
);

CREATE INDEX v23_runs_parent_idx ON v23_runs(parent_run_id);
CREATE INDEX v23_runs_status_idx ON v23_runs(status);

GRANT USAGE ON SCHEMA public TO v23_control;
GRANT SELECT, INSERT ON v23_runs TO v23_control;
GRANT UPDATE (status, revision, turns_used, latest_receipt, active_operation_id,
              active_base_revision, active_input_digest, cancel_requested, op_cache, close_reason)
ON v23_runs TO v23_control;
REVOKE ALL ON v23_runs FROM v23_worker;

-- Control sends pg_notify only after its state transaction has committed.
-- Notifications are wakeups, never an automatic state transition.
