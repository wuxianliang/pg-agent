CREATE TABLE v24_cordis.requests (
  principal_id uuid NOT NULL,
  request_key text NOT NULL,
  kind text NOT NULL,
  request_bytes bytea NOT NULL,
  request_digest bytea NOT NULL CHECK(octet_length(request_digest)=32),
  effect_id uuid NOT NULL UNIQUE,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(principal_id,request_key)
);
