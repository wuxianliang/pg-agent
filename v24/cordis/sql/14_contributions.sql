CREATE TABLE v24_cordis.contributions (
  id uuid PRIMARY KEY,
  fiber_id uuid NOT NULL,
  episode_id uuid NOT NULL,
  seq int NOT NULL CHECK(seq>=0),
  kind text NOT NULL CHECK(kind IN ('service','listener','cell','reservation','child')),
  realm text,
  key text,
  descriptor jsonb NOT NULL CHECK(jsonb_typeof(descriptor)='object'),
  prev_contribution_id uuid,
  inverse jsonb NOT NULL CHECK((jsonb_typeof(inverse)='object' AND jsonb_typeof(inverse->'op')='string'
    AND inverse ? 'op' AND inverse->>'op' IN ('delete_row','restore_prev','release_reservation','dispose_child','unknown')
    AND (inverse->>'op'<>'unknown' OR (inverse ? 'debt' AND inverse->'debt'<>'null'::jsonb))) IS TRUE),
  contract_version text NOT NULL,
  withdrawn_at timestamptz,
  released_at timestamptz,
  CHECK(released_at IS NULL OR (withdrawn_at IS NOT NULL AND released_at>=withdrawn_at)),
  UNIQUE(fiber_id,episode_id,seq)
);
CREATE UNIQUE INDEX contributions_service_addr ON v24_cordis.contributions(realm,key)
  WHERE kind='service' AND released_at IS NULL;
CREATE UNIQUE INDEX contributions_listener_addr ON v24_cordis.contributions
  (fiber_id,episode_id,(descriptor->>'event'),(descriptor->>'listener_id')) WHERE kind='listener' AND released_at IS NULL;
