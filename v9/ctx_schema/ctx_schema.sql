-- v9 W2: context pack state
CREATE TABLE IF NOT EXISTS ctx_sources (
    source_id   text PRIMARY KEY,
    repo_path   text NOT NULL DEFAULT 'default',
    schema_name text NOT NULL,
    table_name  text NOT NULL,
    max_rows    integer NOT NULL DEFAULT 1000 CHECK (max_rows BETWEEN 1 AND 100000),
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repo_heads (
    repo_path   text PRIMARY KEY,
    head_commit text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS context_commits (
    repo_path  text NOT NULL,
    commit_id  text NOT NULL,
    seq        bigint GENERATED ALWAYS AS IDENTITY,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_path, commit_id)
);
CREATE INDEX IF NOT EXISTS ctx_commits_seq_idx ON context_commits (repo_path, seq);

CREATE TABLE IF NOT EXISTS context_commit_files (
    repo_path  text NOT NULL,
    commit_id  text NOT NULL,
    dep_uri    text NOT NULL,
    PRIMARY KEY (repo_path, commit_id, dep_uri)
);

CREATE TABLE IF NOT EXISTS context_packs (
    pack_id        text PRIMARY KEY,
    task_run_id    text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    repo_path      text NOT NULL,
    status         text NOT NULL DEFAULT 'BUILDING'
                   CHECK (status IN ('BUILDING','FRESH','STALE','REFRESHING','FAILED','RETIRED')),
    base_commit    text NOT NULL DEFAULT 'INIT',
    generation     integer NOT NULL DEFAULT 0 CHECK (generation >= 0),
    next_op_seq    bigint NOT NULL DEFAULT 1 CHECK (next_op_seq > 0),
    last_completed_op_seq bigint NOT NULL DEFAULT 0 CHECK (last_completed_op_seq >= 0),
    pending_refresh boolean NOT NULL DEFAULT false,
    token_count    integer,
    worker_id      text,
    last_error     jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_run_id)
);

CREATE TABLE IF NOT EXISTS context_slices (
    pack_id       text NOT NULL REFERENCES context_packs(pack_id) ON DELETE CASCADE,
    slice_id      text NOT NULL,
    seq           integer NOT NULL CHECK (seq > 0),
    kind          text NOT NULL CHECK (kind IN ('source_excerpt','summary','prompt_part')),
    dep_uri       text NOT NULL,
    title         text,
    body          text NOT NULL,
    content_hash  text NOT NULL,
    generation    integer NOT NULL DEFAULT 0,
    stale         boolean NOT NULL DEFAULT false,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_id, slice_id)
);
CREATE INDEX IF NOT EXISTS ctx_slices_stale_idx ON context_slices (pack_id) WHERE stale;

CREATE TABLE IF NOT EXISTS slice_dependencies (
    pack_id        text NOT NULL,
    slice_id       text NOT NULL,
    dep_uri        text NOT NULL,
    built_at_commit text NOT NULL,
    PRIMARY KEY (pack_id, slice_id, dep_uri)
);
CREATE INDEX IF NOT EXISTS slice_dep_uri_idx ON slice_dependencies (dep_uri);

CREATE TABLE IF NOT EXISTS context_refresh_log (
    pack_id        text NOT NULL,
    seq            bigint GENERATED ALWAYS AS IDENTITY,
    trigger_kind   text NOT NULL CHECK (trigger_kind IN ('build','run_completed','git_hook','manual','start_gate')),
    trigger_ref    text,
    dirty_slices   text[] NOT NULL DEFAULT '{}',
    rebuilt_slices text[] NOT NULL DEFAULT '{}',
    base_from      text,
    base_to        text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_id, seq)
);

CREATE TABLE IF NOT EXISTS ctx_operations (
    request_id     text PRIMARY KEY,
    pack_id        text NOT NULL REFERENCES context_packs(pack_id) ON DELETE CASCADE,
    op_kind        text NOT NULL CHECK (op_kind IN ('build','refresh')),
    op_seq         bigint NOT NULL CHECK (op_seq > 0),
    status         text NOT NULL DEFAULT 'QUEUED'
                   CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','DLQ')),
    built_at_commit text,
    worker_id      text,
    result_summary jsonb,
    error          jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    started_at     timestamptz,
    finished_at    timestamptz,
    UNIQUE (pack_id, op_seq)
);
CREATE INDEX IF NOT EXISTS ctx_ops_pack_idx ON ctx_operations (pack_id, op_seq);
CREATE INDEX IF NOT EXISTS ctx_ops_open_idx ON ctx_operations (pack_id, status)
    WHERE status IN ('QUEUED','RUNNING');
