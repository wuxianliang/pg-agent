CREATE TABLE v24_cordis.episodes (
  id uuid PRIMARY KEY,
  fiber_id uuid NOT NULL,
  epoch int NOT NULL CHECK(epoch>=0),
  state text NOT NULL CHECK(state IN ('reloading','active','closing')),
  committed_view jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(committed_view)='object'),
  iterator jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(iterator)='object'),
  outcome text CHECK(outcome IN ('ok','error','divert','retire')),
  opened_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz,
  UNIQUE(fiber_id,epoch),
  UNIQUE(fiber_id,id)
);
CREATE UNIQUE INDEX episodes_one_open ON v24_cordis.episodes(fiber_id) WHERE closed_at IS NULL;
