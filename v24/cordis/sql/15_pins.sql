CREATE TABLE v24_cordis.pins (
  id uuid PRIMARY KEY,
  consumer_fiber_id uuid,
  consumer_episode_id uuid,
  consumer_run_id uuid,
  key text NOT NULL,
  contribution_id uuid NOT NULL,
  provider_epoch int NOT NULL CHECK(provider_epoch>=0),
  created_at timestamptz NOT NULL DEFAULT now(),
  released_at timestamptz,
  CHECK((consumer_fiber_id IS NOT NULL)<>(consumer_run_id IS NOT NULL)),
  CHECK((consumer_fiber_id IS NULL)=(consumer_episode_id IS NULL))
);
CREATE UNIQUE INDEX pins_fiber_active ON v24_cordis.pins(consumer_fiber_id,consumer_episode_id,key) WHERE released_at IS NULL;
CREATE UNIQUE INDEX pins_run_active ON v24_cordis.pins(consumer_run_id,key) WHERE released_at IS NULL;
CREATE INDEX pins_contribution_live ON v24_cordis.pins(contribution_id) WHERE released_at IS NULL;
