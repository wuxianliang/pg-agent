-- W2: ten tables first; every cross-table FK is added at the end.

CREATE TABLE v24.scopes (
  scope_id           uuid PRIMARY KEY,
  parent_id          uuid,
  root_id            uuid NOT NULL,
  route_path         uuid[] NOT NULL,
  realm_routes       jsonb NOT NULL DEFAULT '{}'::jsonb,
  default_realm      text,
  owner_principal    uuid NOT NULL,
  created_by_effect  uuid NOT NULL,
  close_requested_at timestamptz,
  closed_at          timestamptz,
  CONSTRAINT c_scopes_root_shape  CHECK ((parent_id IS NULL) = (root_id = scope_id)),
  CONSTRAINT c_scopes_path_len    CHECK (cardinality(route_path) >= 1),
  CONSTRAINT c_scopes_path_end    CHECK ((route_path[array_length(route_path, 1)] = scope_id) IS TRUE),
  CONSTRAINT c_scopes_close_pair  CHECK (closed_at IS NULL OR close_requested_at IS NOT NULL),
  CONSTRAINT c_scopes_close_order CHECK (closed_at IS NULL OR closed_at >= close_requested_at),
  CONSTRAINT c_scopes_routes_obj  CHECK (jsonb_typeof(realm_routes) = 'object'),
  CONSTRAINT c_scopes_realm_len   CHECK (default_realm IS NULL OR length(default_realm) BETWEEN 1 AND 128)
);
CREATE INDEX i_scopes_parent ON v24.scopes (parent_id, closed_at);
CREATE INDEX i_scopes_root   ON v24.scopes (root_id, scope_id);

CREATE TABLE v24.runs (
  run_id                  uuid PRIMARY KEY,
  scope_id                uuid NOT NULL,
  parent_run_id           uuid,
  spawn_key               text,
  spawn_request_digest    bytea,
  owner_fiber_id          uuid,
  owner_episode_id        uuid,
  status                  text NOT NULL,
  epoch_no                bigint NOT NULL DEFAULT 0,
  registration_generation bigint NOT NULL DEFAULT 1,
  turn_no                 bigint NOT NULL DEFAULT 0,
  driving_generation      bigint NOT NULL DEFAULT 0,
  remaining_steps         integer NOT NULL,
  remaining_tokens        bigint,
  remaining_tool_calls    integer NOT NULL,
  remaining_wall_ms       bigint NOT NULL,
  interaction             jsonb,
  pending_steer           jsonb,
  close_intent            jsonb,
  result                  jsonb,
  revision                bigint NOT NULL DEFAULT 0,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  ended_at                timestamptz,
  CONSTRAINT c_runs_status CHECK (status IN ('running','waiting','completed','failed','cancelled','blocked_unknown')),
  CONSTRAINT c_runs_budget CHECK (remaining_steps >= 0 AND remaining_tool_calls >= 0
                                  AND remaining_wall_ms >= 0
                                  AND (remaining_tokens IS NULL OR remaining_tokens >= 0)),
  CONSTRAINT c_runs_terminal CHECK ((status IN ('completed','failed','cancelled','blocked_unknown')) = (ended_at IS NOT NULL)),
  CONSTRAINT c_runs_waiting  CHECK ((status = 'waiting') = (interaction IS NOT NULL)),
  CONSTRAINT c_runs_steer    CHECK (ended_at IS NULL OR pending_steer IS NULL),
  CONSTRAINT c_runs_owner    CHECK ((owner_fiber_id IS NULL) = (owner_episode_id IS NULL)),
  CONSTRAINT c_runs_monotone CHECK (epoch_no >= 0 AND registration_generation >= 1 AND turn_no >= 0
                                    AND driving_generation >= 0 AND revision >= 0),
  CONSTRAINT c_runs_spawn    CHECK ((spawn_key IS NULL) = (spawn_request_digest IS NULL))
);
CREATE UNIQUE INDEX u_runs_spawn ON v24.runs (parent_run_id, spawn_key) WHERE spawn_key IS NOT NULL;
CREATE INDEX i_runs_scope ON v24.runs (scope_id, status);
CREATE INDEX i_runs_parent ON v24.runs (parent_run_id, status);
CREATE INDEX i_runs_owner_ep ON v24.runs (owner_episode_id, status);

CREATE TABLE v24.effects (
  effect_id         uuid PRIMARY KEY,
  parent_effect_id  uuid,
  ordinal           int,
  requester_id      uuid NOT NULL,
  request_key       text,
  scope_id          uuid,
  run_id            uuid,
  fiber_id          uuid,
  episode_id        uuid,
  pin_id            uuid,
  epoch_no          bigint,
  generation        bigint,
  kind              text NOT NULL,
  status            text NOT NULL,
  request           jsonb NOT NULL,
  request_digest    bytea NOT NULL,
  replay_policy     text NOT NULL,
  attempt_no        bigint NOT NULL DEFAULT 0,
  fence             bigint NOT NULL DEFAULT 0,
  claim_owner       text,
  lease_until       timestamptz,
  cancel_requested  boolean NOT NULL DEFAULT false,
  outcome           jsonb,
  resource_quiesced_at timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  settled_at        timestamptz,
  CONSTRAINT c_effects_status CHECK (status IN ('ready','claimed','succeeded','failed','unknown','cancelled')),
  CONSTRAINT c_effects_kind CHECK (kind IN (
    'command_start','command_cancel','command_steer','command_respond',
    'command_install','command_fiber_control','command_dispose','command_scope_control',
    'command_recover',
    'model_call','tool_call','host_prepare','host_release','inspect_resource','fiber_reconcile')),
  CONSTRAINT c_effects_replay CHECK (replay_policy IN ('no_replay','replay_safe','manual')),
  CONSTRAINT c_effects_parent_pair CHECK ((parent_effect_id IS NULL) = (ordinal IS NULL)),
  CONSTRAINT c_effects_ordinal CHECK (ordinal IS NULL OR ordinal BETWEEN 0 AND 15),
  CONSTRAINT c_effects_outcome CHECK ((status IN ('succeeded','failed','unknown')) = (outcome IS NOT NULL)),
  CONSTRAINT c_effects_settled CHECK ((status IN ('succeeded','failed','unknown','cancelled')) = (settled_at IS NOT NULL)),
  CONSTRAINT c_effects_claim_ck CHECK ((status = 'claimed') = (claim_owner IS NOT NULL AND lease_until IS NOT NULL)),
  CONSTRAINT c_effects_token CHECK (attempt_no >= 0 AND fence >= 0 AND fence <= attempt_no),
  CONSTRAINT c_effects_reqkey CHECK (request_key IS NULL OR length(request_key) BETWEEN 1 AND 512),
  CONSTRAINT c_effects_command_claim CHECK (kind NOT LIKE 'command!_%' ESCAPE '!' OR attempt_no = 0),
  CONSTRAINT u_effects_successor UNIQUE (parent_effect_id, ordinal)
);
CREATE UNIQUE INDEX u_effects_model_call ON v24.effects (run_id)
  WHERE kind = 'model_call' AND status IN ('ready','claimed');
CREATE INDEX i_effects_ready ON v24.effects (created_at) WHERE status = 'ready';
CREATE INDEX i_effects_claimed ON v24.effects (lease_until) WHERE status = 'claimed';

CREATE TABLE v24.pins (
  pin_id               uuid PRIMARY KEY,
  consumer_type        text NOT NULL,
  consumer_episode_id  uuid,
  consumer_run_id      uuid,
  consumer_id          uuid GENERATED ALWAYS AS (coalesce(consumer_episode_id, consumer_run_id)) STORED,
  consumer_epoch       bigint NOT NULL,
  key                  text NOT NULL,
  slot_id              uuid NOT NULL,
  provider_fiber_id    uuid NOT NULL,
  provider_episode_id  uuid NOT NULL,
  descriptor_digest    bytea NOT NULL,
  created_by_effect    uuid NOT NULL,
  released_by_effect   uuid,
  released_at          timestamptz,
  CONSTRAINT c_pins_type CHECK (consumer_type IN ('activation','run')),
  CONSTRAINT c_pins_xor CHECK (
       (consumer_type = 'activation' AND consumer_episode_id IS NOT NULL AND consumer_run_id IS NULL)
    OR (consumer_type = 'run'        AND consumer_run_id IS NOT NULL AND consumer_episode_id IS NULL)),
  CONSTRAINT c_pins_epoch CHECK (consumer_epoch >= 0),
  CONSTRAINT c_pins_release CHECK ((released_at IS NULL) = (released_by_effect IS NULL))
);
CREATE UNIQUE INDEX u_pins_live ON v24.pins (consumer_type, consumer_id, consumer_epoch, key)
  WHERE released_at IS NULL;
CREATE INDEX i_pins_slot ON v24.pins (slot_id) WHERE released_at IS NULL;

CREATE TABLE v24.episodes (
  episode_id         uuid PRIMARY KEY,
  fiber_id           uuid NOT NULL,
  epoch              bigint NOT NULL,
  activation_effect  uuid NOT NULL,
  state              text NOT NULL,
  target_seq         bigint NOT NULL DEFAULT 0,
  opened_at          timestamptz NOT NULL DEFAULT now(),
  retire_started_at  timestamptz,
  closed_at          timestamptz,
  failure            jsonb,
  CONSTRAINT c_episodes_state CHECK (state IN ('active','retiring','closed','blocked')),
  CONSTRAINT c_episodes_closed CHECK ((state = 'closed') = (closed_at IS NOT NULL)),
  CONSTRAINT c_episodes_retire CHECK (state IN ('retiring','closed') OR retire_started_at IS NULL),
  CONSTRAINT u_episodes_epoch  UNIQUE (fiber_id, epoch),
  CONSTRAINT u_episodes_ident  UNIQUE (fiber_id, episode_id)
);
CREATE UNIQUE INDEX u_episodes_open ON v24.episodes (fiber_id) WHERE closed_at IS NULL;

CREATE TABLE v24.fibers (
  fiber_id              uuid PRIMARY KEY,
  install_id            uuid NOT NULL,
  scope_id              uuid NOT NULL,
  owner_fiber_id        uuid,
  owner_episode_id      uuid,
  want_on               boolean NOT NULL DEFAULT false,
  control_seq           bigint NOT NULL DEFAULT 0,
  current_episode_id    uuid,
  disposed_at           timestamptz,
  failure_seq           bigint,
  failure               jsonb,
  next_contribution_seq bigint NOT NULL DEFAULT 0,
  created_by_effect     uuid NOT NULL,
  CONSTRAINT c_fibers_owner_pair CHECK ((owner_fiber_id IS NULL) = (owner_episode_id IS NULL)),
  CONSTRAINT c_fibers_no_self  CHECK (owner_fiber_id IS NULL OR owner_fiber_id <> fiber_id),
  CONSTRAINT c_fibers_tombstone CHECK (disposed_at IS NULL OR want_on = false),
  CONSTRAINT c_fibers_seq CHECK (control_seq >= 0 AND next_contribution_seq >= 0),
  CONSTRAINT c_fibers_failure CHECK ((failure IS NULL) = (failure_seq IS NULL))
);
CREATE INDEX i_fibers_scope ON v24.fibers (scope_id, disposed_at);
CREATE INDEX i_fibers_owner ON v24.fibers (owner_fiber_id, disposed_at);

CREATE TABLE v24.slots (
  slot_id           uuid PRIMARY KEY,
  fiber_id          uuid NOT NULL,
  episode_id        uuid NOT NULL,
  realm             text NOT NULL,
  key               text NOT NULL,
  descriptor        jsonb NOT NULL,
  descriptor_digest bytea NOT NULL,
  contribution_seq  bigint NOT NULL,
  withdrawn_at      timestamptz,
  released_at       timestamptz,
  CONSTRAINT c_slots_release CHECK (released_at IS NULL OR (withdrawn_at IS NOT NULL AND released_at >= withdrawn_at)),
  CONSTRAINT c_slots_realm CHECK (length(realm) BETWEEN 1 AND 128 AND length(key) BETWEEN 1 AND 256),
  CONSTRAINT u_slots_contrib UNIQUE (fiber_id, episode_id, contribution_seq)
);
CREATE UNIQUE INDEX u_slots_live ON v24.slots (realm, key) WHERE released_at IS NULL;
CREATE INDEX i_slots_realm ON v24.slots (realm, key, released_at);

CREATE TABLE v24.installs (
  install_id      uuid PRIMARY KEY,
  scope_id        uuid NOT NULL,
  owner_fiber_id  uuid,
  owner_episode_id uuid,
  identity        text NOT NULL,
  version         text NOT NULL,
  manifest        jsonb NOT NULL,
  manifest_digest bytea NOT NULL,
  requires        jsonb NOT NULL,
  provides        jsonb NOT NULL,
  artifact_digest bytea NOT NULL,
  adapter_digest  bytea NOT NULL,
  owner_principal uuid NOT NULL,
  state           text NOT NULL,
  created_by_effect uuid NOT NULL,
  dispose_effect  uuid,
  disposed_at     timestamptz,
  CONSTRAINT c_installs_state CHECK (state IN ('preparing','installed','prepare_failed','prepare_unknown','dispose_pending','disposed')),
  CONSTRAINT c_installs_owner_pair CHECK ((owner_fiber_id IS NULL) = (owner_episode_id IS NULL)),
  CONSTRAINT c_installs_disposed CHECK ((state = 'disposed') = (disposed_at IS NOT NULL)),
  CONSTRAINT c_installs_dispose_eff CHECK (dispose_effect IS NULL OR state IN ('dispose_pending','disposed')),
  CONSTRAINT c_installs_manifest CHECK (jsonb_typeof(requires) = 'array' AND jsonb_typeof(provides) = 'array'
                                        AND jsonb_typeof(manifest) = 'object'),
  CONSTRAINT c_installs_identity_len CHECK (length(identity) BETWEEN 1 AND 256 AND length(version) BETWEEN 1 AND 64),
  CONSTRAINT u_installs_ident UNIQUE (scope_id, identity, version)
);
CREATE INDEX i_installs_owner ON v24.installs (owner_fiber_id, owner_episode_id, state);

CREATE TABLE v24.events (
  event_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  effect_id      uuid NOT NULL,
  seq            bigint NOT NULL,
  entity_type    text NOT NULL,
  entity_id      uuid NOT NULL,
  event_kind     text NOT NULL,
  payload        jsonb NOT NULL DEFAULT '{}'::jsonb,
  payload_digest bytea NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT c_events_seq CHECK (seq >= 1),
  CONSTRAINT c_events_entity CHECK (entity_type IN ('scope','run','fiber','episode','slot','install','pin','request','effect')),
  CONSTRAINT u_events_cursor UNIQUE (entity_type, entity_id, seq),
  CONSTRAINT u_events_once   UNIQUE (effect_id, entity_type, entity_id, event_kind)
);
CREATE INDEX i_events_entity ON v24.events (entity_type, entity_id, seq);

CREATE TABLE v24.requests (
  principal_id  uuid NOT NULL,
  request_key   text NOT NULL,
  kind          text NOT NULL,
  request_bytes bytea NOT NULL,
  request_digest bytea NOT NULL,
  effect_id     uuid NOT NULL,
  response      jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_requests PRIMARY KEY (principal_id, request_key),
  CONSTRAINT c_requests_key CHECK (length(request_key) BETWEEN 1 AND 512),
  CONSTRAINT u_requests_effect UNIQUE (effect_id)
);

-- 指向 effect 的列：全部延迟（领域行先插，effect 后插）
ALTER TABLE v24.scopes   ADD CONSTRAINT f_scopes_created_by   FOREIGN KEY (created_by_effect) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.fibers   ADD CONSTRAINT f_fibers_created_by   FOREIGN KEY (created_by_effect) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.episodes ADD CONSTRAINT f_episodes_activation FOREIGN KEY (activation_effect) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.pins     ADD CONSTRAINT f_pins_created_by     FOREIGN KEY (created_by_effect) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.pins     ADD CONSTRAINT f_pins_released_by    FOREIGN KEY (released_by_effect) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.installs ADD CONSTRAINT f_installs_created_by FOREIGN KEY (created_by_effect) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.installs ADD CONSTRAINT f_installs_dispose_by FOREIGN KEY (dispose_effect)    REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24.requests ADD CONSTRAINT f_requests_effect    FOREIGN KEY (effect_id)         REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;

-- All effect references are deferred, including the self-reference and events.
ALTER TABLE v24.effects ADD CONSTRAINT f_effects_parent  FOREIGN KEY (parent_effect_id) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;

-- effects 指向领域表：普通 FK（领域行已存在）
ALTER TABLE v24.effects ADD CONSTRAINT f_effects_scope   FOREIGN KEY (scope_id)   REFERENCES v24.scopes(scope_id);
ALTER TABLE v24.effects ADD CONSTRAINT f_effects_run     FOREIGN KEY (run_id)     REFERENCES v24.runs(run_id);
ALTER TABLE v24.effects ADD CONSTRAINT f_effects_fiber   FOREIGN KEY (fiber_id)   REFERENCES v24.fibers(fiber_id);
ALTER TABLE v24.effects ADD CONSTRAINT f_effects_episode FOREIGN KEY (episode_id) REFERENCES v24.episodes(episode_id);
ALTER TABLE v24.effects ADD CONSTRAINT f_effects_pin     FOREIGN KEY (pin_id)     REFERENCES v24.pins(pin_id);

-- 领域表之间
ALTER TABLE v24.scopes  ADD CONSTRAINT f_scopes_parent FOREIGN KEY (parent_id) REFERENCES v24.scopes(scope_id);
ALTER TABLE v24.scopes  ADD CONSTRAINT f_scopes_root   FOREIGN KEY (root_id)   REFERENCES v24.scopes(scope_id);
ALTER TABLE v24.runs    ADD CONSTRAINT f_runs_scope    FOREIGN KEY (scope_id)  REFERENCES v24.scopes(scope_id);
ALTER TABLE v24.runs    ADD CONSTRAINT f_runs_parent   FOREIGN KEY (parent_run_id) REFERENCES v24.runs(run_id);
ALTER TABLE v24.runs    ADD CONSTRAINT f_runs_owner_ep FOREIGN KEY (owner_fiber_id, owner_episode_id) REFERENCES v24.episodes(fiber_id, episode_id);
ALTER TABLE v24.episodes ADD CONSTRAINT f_episodes_fiber FOREIGN KEY (fiber_id) REFERENCES v24.fibers(fiber_id);
ALTER TABLE v24.fibers  ADD CONSTRAINT f_fibers_install FOREIGN KEY (install_id) REFERENCES v24.installs(install_id);
ALTER TABLE v24.fibers  ADD CONSTRAINT f_fibers_scope   FOREIGN KEY (scope_id)   REFERENCES v24.scopes(scope_id);
ALTER TABLE v24.fibers  ADD CONSTRAINT f_fibers_owner_f FOREIGN KEY (owner_fiber_id) REFERENCES v24.fibers(fiber_id);
ALTER TABLE v24.fibers  ADD CONSTRAINT f_fibers_owner_e FOREIGN KEY (owner_fiber_id, owner_episode_id) REFERENCES v24.episodes(fiber_id, episode_id);
ALTER TABLE v24.fibers  ADD CONSTRAINT f_fibers_current FOREIGN KEY (current_episode_id) REFERENCES v24.episodes(episode_id);
ALTER TABLE v24.slots   ADD CONSTRAINT f_slots_ep      FOREIGN KEY (fiber_id, episode_id) REFERENCES v24.episodes(fiber_id, episode_id);
ALTER TABLE v24.installs ADD CONSTRAINT f_installs_scope FOREIGN KEY (scope_id) REFERENCES v24.scopes(scope_id);
ALTER TABLE v24.installs ADD CONSTRAINT f_installs_owner FOREIGN KEY (owner_fiber_id, owner_episode_id) REFERENCES v24.episodes(fiber_id, episode_id);
ALTER TABLE v24.pins    ADD CONSTRAINT f_pins_slot     FOREIGN KEY (slot_id) REFERENCES v24.slots(slot_id);
ALTER TABLE v24.pins    ADD CONSTRAINT f_pins_pfiber   FOREIGN KEY (provider_fiber_id) REFERENCES v24.fibers(fiber_id);
ALTER TABLE v24.pins    ADD CONSTRAINT f_pins_pepisode FOREIGN KEY (provider_fiber_id, provider_episode_id) REFERENCES v24.episodes(fiber_id, episode_id);
ALTER TABLE v24.events  ADD CONSTRAINT f_events_effect FOREIGN KEY (effect_id) REFERENCES v24.effects(effect_id) DEFERRABLE INITIALLY DEFERRED;
