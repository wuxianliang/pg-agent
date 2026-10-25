CREATE TABLE v24_cordis.runs (
  id uuid PRIMARY KEY,
  owner_fiber_id uuid NOT NULL,
  owner_episode_id uuid NOT NULL,
  scope_id uuid NOT NULL,
  parent_run_id uuid,
  spawn_key text,
  state jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(state)='object'),
  remaining_steps int NOT NULL CHECK(remaining_steps>=0),
  ended_at timestamptz,
  result jsonb
);
CREATE UNIQUE INDEX runs_spawn_slot ON v24_cordis.runs(parent_run_id,spawn_key) WHERE spawn_key IS NOT NULL;
