CREATE TABLE v24_cordis.fibers (
  id uuid PRIMARY KEY,
  install_id uuid NOT NULL,
  owner_id uuid,
  owner_episode_id uuid,
  scope_id uuid NOT NULL,
  want_on boolean NOT NULL DEFAULT false,
  control_seq bigint NOT NULL DEFAULT 0 CHECK(control_seq>=0),
  current_episode_id uuid,
  retire_started_at timestamptz,
  failure jsonb,
  dispose_requested_at timestamptz,
  disposed_at timestamptz,
  CHECK ((owner_id IS NULL)=(owner_episode_id IS NULL)),
  CHECK (owner_id IS DISTINCT FROM id)
);
