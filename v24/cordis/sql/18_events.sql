CREATE TABLE v24_cordis.events (
  event_id uuid PRIMARY KEY,
  effect_id uuid,
  seq bigint NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid NOT NULL,
  event_kind text NOT NULL,
  payload jsonb NOT NULL,
  UNIQUE(entity_type,entity_id,seq),
  UNIQUE(effect_id,entity_type,entity_id,event_kind)
);
