CREATE TABLE v24_cordis.installs (
  id uuid PRIMARY KEY,
  scope_id uuid NOT NULL,
  owner_fiber_id uuid,
  owner_episode_id uuid,
  identity text NOT NULL,
  version text NOT NULL,
  manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest)='object'),
  artifact_digest text NOT NULL CHECK (artifact_digest ~ '^[0-9a-f]{64}$'),
  contracts jsonb NOT NULL CHECK (jsonb_typeof(contracts)='object'),
  policy_ref text,
  overlay jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(overlay)='object'),
  state text NOT NULL CHECK (state IN ('preparing','installed','prepare_failed','prepare_unknown','dispose_pending','disposed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((owner_fiber_id IS NULL)=(owner_episode_id IS NULL)),
  UNIQUE(scope_id,identity,version)
);
