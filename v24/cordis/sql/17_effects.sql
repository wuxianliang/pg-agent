CREATE TABLE v24_cordis.effects (
  id uuid PRIMARY KEY,
  parent_id uuid,
  ordinal int CHECK(ordinal BETWEEN 0 AND 15),
  fiber_id uuid,
  episode_id uuid,
  run_id uuid,
  kind text NOT NULL CHECK(kind IN ('command_install','command_reconcile','command_dispose','dispatch','listener_call','model_call','tool_call','run_start','host_io')),
  status text NOT NULL CHECK(status IN ('ready','claimed','succeeded','failed','unknown','cancelled')),
  input jsonb NOT NULL CHECK(jsonb_typeof(input)='object'),
  request_actor text NOT NULL,
  claim_owner text,
  attempt bigint NOT NULL DEFAULT 0 CHECK(attempt>=0),
  fence bigint NOT NULL DEFAULT 0 CHECK(fence>=0 AND fence<=attempt),
  lease_until timestamptz,
  outcome jsonb,
  settled_at timestamptz,
  CHECK((parent_id IS NULL)=(ordinal IS NULL)),
  CHECK(episode_id IS NULL OR fiber_id IS NOT NULL),
  CHECK((outcome IS NOT NULL)=(status IN ('succeeded','failed','unknown'))),
  CHECK((settled_at IS NOT NULL)=(status IN ('succeeded','failed','unknown','cancelled'))),
  CHECK((status='claimed' AND claim_owner IS NOT NULL AND lease_until IS NOT NULL)
     OR (status<>'claimed' AND claim_owner IS NULL AND lease_until IS NULL)),
  UNIQUE(parent_id,ordinal)
);
CREATE UNIQUE INDEX effects_one_model_inflight ON v24_cordis.effects(run_id) WHERE kind='model_call' AND status IN ('ready','claimed');
CREATE UNIQUE INDEX effects_one_reconcile ON v24_cordis.effects(fiber_id) WHERE kind='command_reconcile' AND status IN ('ready','claimed');
