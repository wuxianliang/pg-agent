CREATE TABLE v24_cordis.scopes (
  id uuid PRIMARY KEY,
  parent_id uuid,
  realm_overrides jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(realm_overrides)='object'),
  intercept jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(intercept)='object'),
  closed_at timestamptz
);
