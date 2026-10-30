-- Round-two facade experiment. One database, one writer: Control.execute.
-- Events are append-only. Extra identity tables exist so each design can
-- show its own repair; a design that does not write a table leaves it empty.

CREATE SEQUENCE ids;

CREATE TABLE workflow_runs (
    workflow_run_id text PRIMARY KEY,
    revision bigint NOT NULL,
    status text NOT NULL,
    message text NOT NULL DEFAULT '',
    current_run_id text
);

CREATE TABLE runs (
    run_id text PRIMARY KEY,
    revision bigint NOT NULL,
    status text NOT NULL,
    message text NOT NULL DEFAULT '',
    parent_run_id text,
    workflow_run_id text REFERENCES workflow_runs (workflow_run_id),
    owner_generation bigint NOT NULL DEFAULT 1,
    owner_backend_pid integer
);

CREATE TABLE workflow_steps (
    step_id text PRIMARY KEY,
    seq bigint NOT NULL,
    workflow_run_id text NOT NULL REFERENCES workflow_runs (workflow_run_id),
    run_id text,
    input_artifact_refs text[] NOT NULL DEFAULT '{}',
    output_artifact_refs text[] NOT NULL DEFAULT '{}',
    status text NOT NULL
);

CREATE TABLE artifacts (
    digest text PRIMARY KEY,
    kind text NOT NULL,
    body jsonb NOT NULL,
    path text,
    run_id text
);

CREATE TABLE events (
    event_id bigserial PRIMARY KEY,
    kind text NOT NULL,
    run_id text,
    workflow_run_id text,
    session_id text,
    digest text,
    artifact_refs text[] NOT NULL DEFAULT '{}',
    message text,
    scope text
);

CREATE INDEX events_session_id_idx ON events (session_id);
CREATE INDEX events_workflow_run_id_idx ON events (workflow_run_id);
CREATE INDEX events_run_id_idx ON events (run_id);

CREATE TABLE operations (
    request_id text PRIMARY KEY,
    verb text NOT NULL,
    payload_digest text NOT NULL,
    result jsonb NOT NULL
);

CREATE TABLE turns (
    turn_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES runs (run_id),
    status text NOT NULL,
    receipt jsonb
);

CREATE TABLE macro_tasks (
    macro_id text PRIMARY KEY,
    title text NOT NULL,
    revision bigint NOT NULL
);

CREATE TABLE macro_workflows (
    macro_id text NOT NULL REFERENCES macro_tasks (macro_id),
    workflow_run_id text NOT NULL REFERENCES workflow_runs (workflow_run_id),
    position integer NOT NULL,
    PRIMARY KEY (macro_id, workflow_run_id)
);

-- Design 1 repair: stable caller id, separate from run_id.
CREATE TABLE session_aliases (
    session_id text PRIMARY KEY,
    current_run_id text,
    revision bigint NOT NULL
);

CREATE TABLE alias_runs (
    session_id text NOT NULL REFERENCES session_aliases (session_id),
    run_id text NOT NULL REFERENCES runs (run_id),
    PRIMARY KEY (session_id, run_id)
);

-- Design 3 repair: stable session id points at one workflow.
-- No revision and no current_run_id here; those stay on workflow_runs.
CREATE TABLE sessions (
    session_id text PRIMARY KEY,
    workflow_run_id text NOT NULL REFERENCES workflow_runs (workflow_run_id),
    status text NOT NULL
);

-- Design 4 repair: external id is a committed row, written with the run.
CREATE TABLE external_ids (
    external_id text PRIMARY KEY,
    run_id text,
    profile_name text NOT NULL,
    status text NOT NULL
);

CREATE TABLE external_runs (
    external_id text NOT NULL REFERENCES external_ids (external_id),
    run_id text NOT NULL REFERENCES runs (run_id),
    PRIMARY KEY (external_id, run_id)
);
