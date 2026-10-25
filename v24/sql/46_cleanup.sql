-- S5 W1/W2: cleanup graph, predicates and the bounded dispose/inspect stage.
-- Every function here is SECURITY INVOKER with a pinned search_path and no
-- EXECUTE grant: the protocol reaches dispose_stage only through advance's
-- command_dispose interpreter, and the read helpers are exercised by the owner
-- connection in the gate.  No new SECURITY DEFINER is introduced (G1-A stays at
-- six entries), and no table is added.

-- One install's direct outgoing cleanup edges.  The edge direction is the
-- cleanup direction: "u -> v" means u must be disposed before v.
--   owner       child -> owner install (fixed owner_fiber_id/owner_episode_id)
--   dependency  consumer -> provider install for every live pin
-- Read-only, deterministic (UNION removes duplicate next/edge pairs).
CREATE FUNCTION v24.cleanup_edges(p_install_id uuid)
RETURNS TABLE(next_id uuid, edge text)
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  SELECT oi.install_id, 'owner'::text
    FROM v24.installs ci
    JOIN v24.fibers f ON f.fiber_id = ci.owner_fiber_id
    JOIN v24.installs oi ON oi.install_id = f.install_id
   WHERE ci.install_id = p_install_id
     AND ci.owner_fiber_id IS NOT NULL
     AND ci.owner_episode_id IS NOT NULL
     AND oi.install_id <> ci.install_id
     -- The immutable owner pair must name a real episode of that fiber.  The
     -- current_episode_id column is deliberately not consulted (design 6.6).
     AND EXISTS (SELECT 1 FROM v24.episodes e
                  WHERE e.fiber_id = f.fiber_id
                    AND e.episode_id = ci.owner_episode_id)
  UNION
  SELECT pf.install_id, 'dependency'::text
    FROM v24.fibers cf
    JOIN v24.pins p ON p.released_at IS NULL
     AND (p.consumer_episode_id IN (SELECT e.episode_id FROM v24.episodes e
                                     WHERE e.fiber_id = cf.fiber_id)
          OR p.consumer_run_id IN (SELECT r.run_id FROM v24.runs r
                                    WHERE r.owner_fiber_id = cf.fiber_id))
    JOIN v24.episodes pe ON pe.episode_id = p.provider_episode_id
    JOIN v24.fibers pf ON pf.fiber_id = pe.fiber_id
   WHERE cf.install_id = p_install_id
     AND pf.install_id <> p_install_id
$$;

-- Scope cleanup closure.  The node set is deliberately wider than the scope:
--   * this scope's installs,
--   * their transitive owner descendants (child installs may live in another
--     scope because admission only checks the fixed owner pair),
--   * dependency neighbours of those installs in both directions (the provider
--     of a live consumer pin and the consumer of a live provider pin), again
--     transitively.
-- A transitive dependency neighbour is included so scope obligations cannot be
-- declared clear while an out-of-scope consumer still holds the provider's
-- slot.  The loop is an explicit array queue with a seen set; cycles terminate
-- without relying on SQL recursion.  Read-only.
CREATE FUNCTION v24.cleanup_closure(p_scope_id uuid)
RETURNS TABLE(install_id uuid)
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_queue uuid[];
  v_seen uuid[] := '{}'::uuid[];
  v_cur uuid;
  v_next uuid;
BEGIN
  SELECT coalesce(array_agg(i.install_id ORDER BY i.install_id), '{}'::uuid[])
    INTO v_queue
    FROM v24.installs i
   WHERE i.scope_id = p_scope_id;

  WHILE cardinality(v_queue) > 0 LOOP
    v_cur := v_queue[1];
    v_queue := v_queue[2:cardinality(v_queue)];
    IF v_cur = ANY(v_seen) THEN
      CONTINUE;
    END IF;
    v_seen := v_seen || v_cur;

    FOR v_next IN
      -- Owner descendants attached through this install's fibers.
      SELECT ci.install_id
        FROM v24.fibers f
        JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
        JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                            AND e.fiber_id = f.fiber_id
       WHERE f.install_id = v_cur
         AND ci.install_id <> v_cur
      UNION
      -- Providers of live pins consumed by this install (activation + run).
      SELECT pf.install_id
        FROM v24.fibers cf
        JOIN v24.pins p ON p.released_at IS NULL
         AND (p.consumer_episode_id IN (SELECT e.episode_id FROM v24.episodes e
                                         WHERE e.fiber_id = cf.fiber_id)
              OR p.consumer_run_id IN (SELECT r.run_id FROM v24.runs r
                                        WHERE r.owner_fiber_id = cf.fiber_id))
        JOIN v24.episodes pe ON pe.episode_id = p.provider_episode_id
        JOIN v24.fibers pf ON pf.fiber_id = pe.fiber_id
       WHERE cf.install_id = v_cur
         AND pf.install_id <> v_cur
      UNION
      -- Activation consumers of live pins whose provider is this install.
      SELECT ci.install_id
        FROM v24.fibers pf
        JOIN v24.episodes pe ON pe.fiber_id = pf.fiber_id
        JOIN v24.pins p ON p.released_at IS NULL
                       AND p.provider_episode_id = pe.episode_id
        JOIN v24.episodes ce ON ce.episode_id = p.consumer_episode_id
        JOIN v24.fibers cf ON cf.fiber_id = ce.fiber_id
        JOIN v24.installs ci ON ci.install_id = cf.install_id
       WHERE pf.install_id = v_cur
         AND ci.install_id <> v_cur
      UNION
      -- Run-pin consumers of live pins whose provider is this install.
      SELECT ci.install_id
        FROM v24.fibers pf
        JOIN v24.episodes pe ON pe.fiber_id = pf.fiber_id
        JOIN v24.pins p ON p.released_at IS NULL
                       AND p.provider_episode_id = pe.episode_id
        JOIN v24.runs r ON r.run_id = p.consumer_run_id
        JOIN v24.fibers cf ON cf.fiber_id = r.owner_fiber_id
        JOIN v24.installs ci ON ci.install_id = cf.install_id
       WHERE pf.install_id = v_cur
         AND ci.install_id <> v_cur
    LOOP
      IF NOT v_next = ANY(v_seen) AND NOT v_next = ANY(v_queue) THEN
        v_queue := v_queue || v_next;
      END IF;
    END LOOP;
  END LOOP;

  RETURN QUERY
    SELECT u.install_id FROM unnest(v_seen) AS u(install_id)
     ORDER BY u.install_id;
END;
$$;

-- Cycle detection along the cleanup edges.  The result is a closed cycle path
-- (first element repeated at the end, e.g. {A,B,C,A}) when p_install_id can
-- reach a repeated node, and an empty array otherwise.
--
-- The walk is cycle-guarded (a node may not repeat inside the walk) and capped
-- at 64 edges.  A path that is still growing past 64 nodes returns the
-- fail-closed sentinel {p_install_id}: the 65th step is treated exactly like a
-- cycle so a caller can never widen the bound by retrying.  Both owner and
-- dependency edges are covered because the walk is driven by cleanup_edges.
CREATE FUNCTION v24.cleanup_cycle(p_install_id uuid)
RETURNS uuid[]
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  WITH RECURSIVE walk(node_id, path) AS (
    SELECT p_install_id, ARRAY[p_install_id]
    UNION ALL
    SELECT e.next_id, w.path || e.next_id
      FROM walk w
      CROSS JOIN LATERAL v24.cleanup_edges(w.node_id) e
     WHERE cardinality(w.path) <= 64
       AND NOT e.next_id = ANY(w.path)
  ), hit AS (
    SELECT w.path[array_position(w.path, e.next_id):] || e.next_id AS cycle_path
      FROM walk w
      CROSS JOIN LATERAL v24.cleanup_edges(w.node_id) e
     WHERE e.next_id = ANY(w.path)
  )
  SELECT coalesce(
    (SELECT h.cycle_path
       FROM hit h
      ORDER BY cardinality(h.cycle_path), h.cycle_path::text
      LIMIT 1),
    CASE WHEN EXISTS (SELECT 1 FROM walk w WHERE cardinality(w.path) > 64)
         THEN ARRAY[p_install_id]
         ELSE '{}'::uuid[] END);
$$;

-- Merged cleanup graph for one scope.  Every returned row is deterministic;
-- a node may appear once as a node row and once per incoming edge row.
--
-- Ordering semantics (W1): the draft's depth-0 seed rows cannot guarantee
-- "child before owner" when both endpoints are also scope installs, so the
-- function returns a bounded topological order instead.  `depth` is the
-- longest-path-to-sink rank of the row's node (0 for a sink), computed over
-- simple paths inside the closure and capped at 64 edges.  For every edge
-- u -> v, rank(u) > rank(v), therefore `ORDER BY depth DESC, node_id` emits u
-- before v.  Cycles are tolerated for read-only inspection: the rank is still
-- finite/deterministic, while cleanup_cycle is the authority that rejects them
-- before any write.  Duplicate rows per node are intentional parent/edge facts.
CREATE FUNCTION v24.cleanup_graph(p_scope_id uuid)
RETURNS TABLE(node_kind text, node_id uuid, parent_kind text, parent_id uuid,
              edge text, depth int)
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  WITH RECURSIVE nodes AS (
    SELECT c.install_id FROM v24.cleanup_closure(p_scope_id) c
  ), walk(start_id, node_id, path, len) AS (
    SELECT n.install_id, n.install_id, ARRAY[n.install_id], 0
      FROM nodes n
    UNION ALL
    SELECT w.start_id, e.next_id, w.path || e.next_id, w.len + 1
      FROM walk w
      CROSS JOIN LATERAL v24.cleanup_edges(w.node_id) e
     WHERE w.len < 64
       AND e.next_id IN (SELECT n2.install_id FROM nodes n2)
       AND NOT e.next_id = ANY(w.path)
  ), rank_map AS (
    SELECT w.start_id AS install_id, max(w.len) AS rank
      FROM walk w
     GROUP BY w.start_id
  ), edges AS (
    SELECT n.install_id AS parent_id, e.next_id, e.edge
      FROM nodes n
      CROSS JOIN LATERAL v24.cleanup_edges(n.install_id) e
     WHERE e.next_id IN (SELECT n2.install_id FROM nodes n2)
  )
  SELECT 'install'::text AS node_kind,
         n.install_id AS node_id,
         NULL::text AS parent_kind,
         NULL::uuid AS parent_id,
         NULL::text AS edge,
         coalesce(r.rank, 0)::int AS depth
    FROM nodes n
    LEFT JOIN rank_map r ON r.install_id = n.install_id
  UNION ALL
  SELECT 'install'::text AS node_kind,
         e.next_id AS node_id,
         'install'::text AS parent_kind,
         e.parent_id AS parent_id,
         e.edge AS edge,
         coalesce(r.rank, 0)::int AS depth
    FROM edges e
    LEFT JOIN rank_map r ON r.install_id = e.next_id
   ORDER BY depth DESC, node_id, parent_id NULLS FIRST, edge NULLS FIRST;
$$;

-- Outstanding cleanup obligations for a scope, read-only.  This is the
-- monotone quantity used by later S5 phases: runs + installs + fibers + child
-- scopes + host/inspect effects.  It intentionally does not count slots or
-- pins directly; those are surfaced by cleanup_slots and the fiber/effect
-- predicates during dispose.
CREATE FUNCTION v24.cleanup_pending(p_scope_id uuid)
RETURNS int
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  WITH closure AS (
    SELECT c.install_id FROM v24.cleanup_closure(p_scope_id) c
  )
  SELECT
    (SELECT count(*) FROM v24.runs r
      WHERE r.scope_id = p_scope_id
        AND r.status NOT IN ('completed','failed','cancelled','blocked_unknown'))
  + (SELECT count(*) FROM closure c
       JOIN v24.installs i ON i.install_id = c.install_id
      WHERE i.state <> 'disposed')
  + (SELECT count(*) FROM closure c
       JOIN v24.fibers f ON f.install_id = c.install_id
      WHERE f.disposed_at IS NULL)
  + (SELECT count(*) FROM v24.scopes s
      WHERE s.parent_id = p_scope_id AND s.closed_at IS NULL)
  + (SELECT count(*) FROM closure c
       JOIN v24.effects e ON (e.request->>'install_id') = c.install_id::text
      WHERE e.kind IN ('host_prepare','host_release','inspect_resource')
        AND (e.status IN ('ready','claimed')
             OR (e.status = 'unknown' AND e.resource_quiesced_at IS NULL)));
$$;

-- W1 evidence surface for the contribution order.  W4 implements the actual
-- release; this helper only exposes the unreleased slots of one fiber in the
-- frozen LIFO order (`contribution_seq DESC`, slot_id as deterministic tie).
CREATE FUNCTION v24.cleanup_slots(p_fiber_id uuid)
RETURNS TABLE(slot_id uuid, contribution_seq bigint)
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  SELECT s.slot_id, s.contribution_seq
    FROM v24.slots s
   WHERE s.fiber_id = p_fiber_id
     AND s.released_at IS NULL
   ORDER BY s.contribution_seq DESC, s.slot_id;
$$;

-- C27 tombstone predicate: every one of the six frozen obligations must hold
-- against committed rows.
--
-- The two optional parameters exist for the applier, which validates a delta
-- BEFORE any DML:
--   * p_effect_id        the effect being settled; it is still claimed here and
--                        must not make its own settlement impossible;
--   * p_quiesced_effect  the host effect an inspect success is about to mark
--                        quiesced in the same delta (release known -> disposed);
--   * p_assumed_fibers   fiber tombstones the same delta is about to write
--                        (the command/direct-tombstone delta always tombstones
--                        all remaining fibers of the install).
-- A two-argument call is the frozen contract shape; the defaults make the
-- predicate recompute exactly the six obligations.
CREATE FUNCTION v24.install_disposed_ok(p_install_id uuid,
  p_effect_id uuid DEFAULT NULL,
  p_quiesced_effect uuid DEFAULT NULL,
  p_assumed_fibers uuid[] DEFAULT '{}'::uuid[])
RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  SELECT coalesce(
    p_install_id IS NOT NULL
    -- 1. every fiber of the install is tombstoned.
    AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                     WHERE f.install_id = p_install_id
                       AND f.disposed_at IS NULL
                       AND NOT (f.fiber_id = ANY(p_assumed_fibers)))
    -- 2. every episode of those fibers is closed.
    AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                      JOIN v24.episodes e ON e.fiber_id = f.fiber_id
                     WHERE f.install_id = p_install_id
                       AND e.state <> 'closed')
    -- 3. every slot of those fibers is released.
    AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                      JOIN v24.slots s ON s.fiber_id = f.fiber_id
                     WHERE f.install_id = p_install_id
                       AND s.released_at IS NULL)
    -- 4. every child install found through the fixed owner pair is disposed.
    AND NOT EXISTS (SELECT 1 FROM v24.installs ci
                      JOIN v24.fibers f ON f.fiber_id = ci.owner_fiber_id
                                       AND f.install_id = p_install_id
                      JOIN v24.episodes oe ON oe.episode_id = ci.owner_episode_id
                                          AND oe.fiber_id = f.fiber_id
                     WHERE ci.state <> 'disposed')
    -- 5. no ready|claimed host/inspect effect and no unknown-without-quiesced
    -- effect references the install, except the one being settled.
    AND NOT EXISTS (SELECT 1 FROM v24.effects e
                     WHERE (e.request->>'install_id') = p_install_id::text
                       AND e.kind IN ('host_prepare','host_release','inspect_resource')
                       AND e.effect_id IS DISTINCT FROM p_effect_id
                       AND e.effect_id IS DISTINCT FROM p_quiesced_effect
                       AND (e.status IN ('ready','claimed')
                            OR (e.status = 'unknown'
                                AND e.resource_quiesced_at IS NULL)))
    -- 6. no cleanup cycle can reach this install.
    AND cardinality(v24.cleanup_cycle(p_install_id)) = 0,
    false);
$$;

-- Pre-release predicate from design 5.1: the fiber/episode/slot/child/cycle
-- obligations plus unknown-without-quiesced effects.  The caller still judges
-- ready|claimed host effects (it may legitimately reuse one).  The release
-- effect being emitted does not exist yet; p_release_effect_id is accepted for
-- the frozen signature and is excluded defensively when it already exists.
CREATE FUNCTION v24.install_disposed_ok_except_release(p_install_id uuid,
  p_release_effect_id uuid DEFAULT NULL,
  p_assumed_fibers uuid[] DEFAULT '{}'::uuid[])
RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  SELECT coalesce(
    p_install_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                     WHERE f.install_id = p_install_id
                       AND f.disposed_at IS NULL
                       AND NOT (f.fiber_id = ANY(p_assumed_fibers)))
    AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                      JOIN v24.episodes e ON e.fiber_id = f.fiber_id
                     WHERE f.install_id = p_install_id
                       AND e.state <> 'closed')
    AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                      JOIN v24.slots s ON s.fiber_id = f.fiber_id
                     WHERE f.install_id = p_install_id
                       AND s.released_at IS NULL)
    AND NOT EXISTS (SELECT 1 FROM v24.installs ci
                      JOIN v24.fibers f ON f.fiber_id = ci.owner_fiber_id
                                       AND f.install_id = p_install_id
                      JOIN v24.episodes oe ON oe.episode_id = ci.owner_episode_id
                                          AND oe.fiber_id = f.fiber_id
                     WHERE ci.state <> 'disposed')
    AND NOT EXISTS (SELECT 1 FROM v24.effects e
                     WHERE (e.request->>'install_id') = p_install_id::text
                       AND e.kind IN ('host_prepare','host_release','inspect_resource')
                       AND e.effect_id IS DISTINCT FROM p_release_effect_id
                       AND e.status = 'unknown'
                       AND e.resource_quiesced_at IS NULL)
    AND cardinality(v24.cleanup_cycle(p_install_id)) = 0,
    false);
$$;

-- W3 close closure: this scope's installs plus their transitive owner
-- descendants (D-S5-10).  Dependency neighbours are deliberately not included:
-- scope close owns this scope's own obligations, while a live dependency pin is
-- surfaced separately by scope_closable's pin blocker.  `scope_depth` is the
-- route_path length of the install's own scope; callers order it DESC so child
-- scopes are cascaded before the parent.  UNION (not ALL) terminates cycles.
CREATE FUNCTION v24.cleanup_close_closure(p_scope_id uuid)
RETURNS TABLE(install_id uuid, scope_depth int)
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
  WITH RECURSIVE d(install_id) AS (
    SELECT i.install_id FROM v24.installs i WHERE i.scope_id = p_scope_id
    UNION
    SELECT ci.install_id
      FROM d
      JOIN v24.fibers f ON f.install_id = d.install_id
      JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
      JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                          AND e.fiber_id = f.fiber_id
  )
  SELECT d.install_id, cardinality(s.route_path)::int
    FROM d
    JOIN v24.installs i ON i.install_id = d.install_id
    JOIN v24.scopes s ON s.scope_id = i.scope_id
   ORDER BY cardinality(s.route_path) DESC, d.install_id;
$$;

-- C26 barrier predicate.  The result is a structured blocker report:
--   {ok, blockers:{runs,fibers,installs,children,effects,pins}, pending:{...}}
-- `pending` is the frozen four-key phase payload; `blockers` carries the extra
-- effect/pin counts the barrier must also clear.  Read-only and INVOKER.
CREATE FUNCTION v24.scope_closable(p_scope_id uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_children int := 0;
  v_installs int := 0;
  v_fibers int := 0;
  v_runs int := 0;
  v_effects int := 0;
  v_pins int := 0;
  v_pending jsonb;
  v_blockers jsonb;
BEGIN
  IF p_scope_id IS NULL
     OR NOT EXISTS (SELECT 1 FROM v24.scopes s WHERE s.scope_id = p_scope_id) THEN
    RETURN jsonb_build_object('ok', false,
      'blockers', jsonb_build_object('missing', 1),
      'pending', jsonb_build_object('runs',0,'fibers',0,'installs',0,'children',0));
  END IF;

  SELECT count(*) INTO v_children
    FROM v24.scopes c
   WHERE c.parent_id = p_scope_id AND c.closed_at IS NULL;

  SELECT count(*) INTO v_installs
    FROM v24.cleanup_close_closure(p_scope_id) c
    JOIN v24.installs i ON i.install_id = c.install_id
   WHERE i.state <> 'disposed';

  SELECT count(*) INTO v_fibers
    FROM v24.cleanup_close_closure(p_scope_id) c
    JOIN v24.fibers f ON f.install_id = c.install_id
   WHERE f.disposed_at IS NULL;

  SELECT count(*) INTO v_runs
    FROM v24.runs r
   WHERE r.scope_id = p_scope_id
     AND r.status NOT IN ('completed','failed','cancelled','blocked_unknown');

  SELECT count(*) INTO v_effects
    FROM v24.cleanup_close_closure(p_scope_id) c
    JOIN v24.effects e ON (e.request->>'install_id') = c.install_id::text
   WHERE e.kind IN ('host_prepare','host_release','inspect_resource')
     AND (e.status IN ('ready','claimed')
          OR (e.status = 'unknown' AND e.resource_quiesced_at IS NULL));

  -- A live pin references the closure when the provider side belongs to a
  -- closure fiber/slot, or when the consumer side is a closure fiber or a run
  -- in this scope.  Both directions block: neither can be released by retire.
  SELECT count(*) INTO v_pins
    FROM v24.pins p
   WHERE p.released_at IS NULL
     AND (
       EXISTS (SELECT 1 FROM v24.cleanup_close_closure(p_scope_id) c
                 JOIN v24.fibers f ON f.install_id = c.install_id
                 JOIN v24.episodes ep ON ep.fiber_id = f.fiber_id
                WHERE ep.episode_id = p.provider_episode_id)
       OR EXISTS (SELECT 1 FROM v24.cleanup_close_closure(p_scope_id) c
                    JOIN v24.fibers f ON f.install_id = c.install_id
                    JOIN v24.slots s ON s.fiber_id = f.fiber_id
                   WHERE s.slot_id = p.slot_id)
       OR p.consumer_run_id IN
            (SELECT r.run_id FROM v24.runs r WHERE r.scope_id = p_scope_id)
       OR EXISTS (SELECT 1 FROM v24.cleanup_close_closure(p_scope_id) c
                    JOIN v24.fibers f ON f.install_id = c.install_id
                    JOIN v24.episodes ep ON ep.fiber_id = f.fiber_id
                   WHERE ep.episode_id = p.consumer_episode_id)
     );

  v_pending := jsonb_build_object(
    'runs', v_runs, 'fibers', v_fibers,
    'installs', v_installs, 'children', v_children);
  v_blockers := jsonb_build_object(
    'runs', v_runs, 'fibers', v_fibers, 'installs', v_installs,
    'children', v_children, 'effects', v_effects, 'pins', v_pins);
  RETURN jsonb_build_object(
    'ok', (v_runs + v_fibers + v_installs + v_children + v_effects + v_pins) = 0,
    'blockers', v_blockers,
    'pending', v_pending);
END;
$$;

-- One bounded fiber-deactivation stage (C24/C27).  Read/write helper shared by
-- interpret_fiber_control's `off` and dispose_stage's release/close phase.
--
-- Order inside one call:
--   1. lock the fiber and the current (or first open) episode;
--   2. if the episode is active, retire it and withdraw up to five of its
--      unreleased slots.  Modes other than 'control' stop here: install
--      dispose advances one bounded stage per request key, so a retire-only
--      stage never also emits a host_release.  'control' continues in the same
--      call when the C24 barrier is clear;
--   3. barrier: live provider pins on the episode/fiber, undisposed child
--      installs of this fiber, and ready|claimed or unknown-without-quiesced
--      host/inspect effects of the install.  A blocked stage writes nothing
--      past the retire rows;
--   4. release up to eight live consumer pins held by the episode (provider
--      pins are the barrier above, never released here);
--   5. release exactly ONE unreleased slot, the maximum contribution_seq
--      (cleanup_slots), setting withdrawn_at as needed;
--   6. close the episode (and clear current_episode_id) only when every slot is
--      released, the barrier is clear and the child installs are disposed.
--
-- The returned delta is bounded: 1 fiber row + 1 episode row + 5 withdrawn
-- slots + 8 pins + 1 released slot = 16 rows.  `fiber_done` is true only when
-- this call finished the fiber, `released_slot` is true only when a
-- contribution was released, and `blocked` marks a barrier stop.  The helper
-- never writes fibers.disposed_at: install dispose owns the tombstone.
CREATE FUNCTION v24.deactivate_stage(p_fiber_id uuid, p_by_effect uuid, p_mode text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_f v24.fibers%ROWTYPE;
  v_ep v24.episodes%ROWTYPE;
  v_barrier boolean := false;
  v_retired boolean := false;
  v_released boolean := false;
  v_closed boolean := false;
  v_fiber_done boolean := false;
  v_reserved uuid;
  v_slot uuid;
  v_pin_count int := 0;
  v_ep_set jsonb := '{}'::jsonb;
  v_fiber_set jsonb := jsonb_build_object('want_on', false);
  v_slots jsonb := '[]'::jsonb;
  v_pins jsonb := '[]'::jsonb;
  v_events jsonb := '[]'::jsonb;
  r record;
BEGIN
  IF p_fiber_id IS NULL OR p_by_effect IS NULL OR p_mode IS NULL
     OR p_mode NOT IN ('control','command','cascade','close') THEN
    RETURN jsonb_build_object('error', v24.error_v1('invalid_args'));
  END IF;

  SELECT * INTO v_f FROM v24.fibers f WHERE f.fiber_id = p_fiber_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', v24.error_v1('invalid_args'));
  END IF;

  IF v_f.current_episode_id IS NOT NULL THEN
    SELECT * INTO v_ep FROM v24.episodes e
     WHERE e.episode_id = v_f.current_episode_id FOR UPDATE;
  ELSE
    SELECT * INTO v_ep FROM v24.episodes e
     WHERE e.fiber_id = p_fiber_id
       AND (e.state <> 'closed'
            OR EXISTS (SELECT 1 FROM v24.slots s
                        WHERE s.episode_id = e.episode_id
                          AND s.released_at IS NULL))
     ORDER BY e.epoch DESC, e.episode_id
     LIMIT 1 FOR UPDATE;
  END IF;

  IF v_ep.episode_id IS NULL THEN
    RETURN jsonb_build_object('action','idle','blocked',false,
      'fiber_done',false,'released_slot',false,
      'fibers',jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('fiber_id',p_fiber_id),'set',v_fiber_set)),
      'episodes','[]'::jsonb,'slots','[]'::jsonb,'pins','[]'::jsonb,
      'events','[]'::jsonb);
  END IF;

  -- C24 barrier, evaluated once on committed rows.  The child test is
  -- fiber-wide: an episode may close only after every child install attached to
  -- this fiber is disposed.
  SELECT (
    EXISTS (SELECT 1 FROM v24.pins p
             WHERE p.released_at IS NULL
               AND (p.provider_episode_id = v_ep.episode_id
                    OR p.slot_id IN (SELECT s.slot_id FROM v24.slots s
                                      WHERE s.fiber_id = p_fiber_id)))
    OR EXISTS (SELECT 1 FROM v24.installs ci
                WHERE ci.owner_fiber_id = p_fiber_id
                  AND ci.owner_episode_id IS NOT NULL
                  AND ci.state <> 'disposed')
    OR EXISTS (SELECT 1 FROM v24.effects he
                WHERE (he.request->>'install_id') = v_f.install_id::text
                  AND he.kind IN ('host_prepare','host_release','inspect_resource')
                  AND (he.status IN ('ready','claimed')
                       OR (he.status = 'unknown'
                           AND he.resource_quiesced_at IS NULL)))
  ) INTO v_barrier;

  IF v_ep.state = 'active' THEN
    v_retired := true;
    v_ep_set := jsonb_build_object('state','retiring','retire_started_at',now());
    v_events := v_events || jsonb_build_array(jsonb_build_object(
      'entity_type','episode','entity_id',v_ep.episode_id,
      'event_kind','episode_retire_started',
      'payload',jsonb_build_object('episode_id',v_ep.episode_id)));

    -- In control mode a clear barrier reserves the LIFO release candidate so it
    -- is not withdrawn twice in the same delta.
    IF p_mode = 'control' AND NOT v_barrier THEN
      SELECT s.slot_id INTO v_reserved
        FROM v24.cleanup_slots(p_fiber_id) s
        JOIN v24.slots sl ON sl.slot_id = s.slot_id
       WHERE sl.episode_id = v_ep.episode_id
       ORDER BY s.contribution_seq DESC, s.slot_id
       LIMIT 1;
    END IF;

    FOR r IN
      SELECT s.slot_id, s.contribution_seq
        FROM v24.slots s
       WHERE s.episode_id = v_ep.episode_id
         AND s.released_at IS NULL AND s.withdrawn_at IS NULL
         AND (v_reserved IS NULL OR s.slot_id <> v_reserved)
       ORDER BY s.contribution_seq DESC, s.slot_id
       LIMIT 5
    LOOP
      v_slots := v_slots || jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('slot_id',r.slot_id),
        'set',jsonb_build_object('withdrawn_at',now())));
      v_events := v_events || jsonb_build_array(jsonb_build_object(
        'entity_type','slot','entity_id',r.slot_id,
        'event_kind','slot_withdrawn',
        'payload',jsonb_build_object('slot_id',r.slot_id)));
    END LOOP;

    IF p_mode <> 'control' OR v_barrier THEN
      RETURN jsonb_build_object('action','retire','blocked',v_barrier,
        'fiber_done',false,'released_slot',false,
        'fibers',jsonb_build_array(jsonb_build_object(
          'key',jsonb_build_object('fiber_id',p_fiber_id),'set',v_fiber_set)),
        'episodes',jsonb_build_array(jsonb_build_object(
          'key',jsonb_build_object('episode_id',v_ep.episode_id),'set',v_ep_set)),
        'slots',v_slots,'pins','[]'::jsonb,'events',v_events);
    END IF;
  ELSIF v_barrier THEN
    RETURN jsonb_build_object('action','blocked','blocked',true,
      'fiber_done',false,'released_slot',false,
      'fibers',jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('fiber_id',p_fiber_id),'set',v_fiber_set)),
      'episodes','[]'::jsonb,'slots','[]'::jsonb,'pins','[]'::jsonb,
      'events','[]'::jsonb);
  END IF;

  -- Consumer-side pins held by this episode are released before its
  -- contribution.  Bound the batch so rows and events stay inside 16/64 even
  -- when a fiber holds many dependencies; a second stage drains the rest.
  SELECT count(*) INTO v_pin_count
    FROM v24.pins p
   WHERE p.consumer_episode_id = v_ep.episode_id
     AND p.released_at IS NULL;

  IF v_pin_count > 0 THEN
    FOR r IN SELECT p.pin_id FROM v24.pins p
              WHERE p.consumer_episode_id = v_ep.episode_id
                AND p.released_at IS NULL
              ORDER BY p.pin_id
              LIMIT 8
    LOOP
      v_pins := v_pins || jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('pin_id',r.pin_id),
        'set',jsonb_build_object('released_at',now(),
                                 'released_by_effect',p_by_effect)));
      v_events := v_events || jsonb_build_array(jsonb_build_object(
        'entity_type','pin','entity_id',r.pin_id,
        'event_kind','pin_released',
        'payload',jsonb_build_object('pin_id',r.pin_id)));
    END LOOP;
    IF v_pin_count > 8 THEN
      RETURN jsonb_build_object('action','release','blocked',false,
        'fiber_done',false,'released_slot',false,
        'fibers',jsonb_build_array(jsonb_build_object(
          'key',jsonb_build_object('fiber_id',p_fiber_id),'set',v_fiber_set)),
        'episodes',CASE WHEN v_ep_set = '{}'::jsonb THEN '[]'::jsonb
                        ELSE jsonb_build_array(jsonb_build_object(
                          'key',jsonb_build_object('episode_id',v_ep.episode_id),
                          'set',v_ep_set)) END,
        'slots',v_slots,'pins',v_pins,'events',v_events);
    END IF;
  END IF;

  -- Exactly one contribution per stage, in the frozen LIFO order.
  SELECT s.slot_id INTO v_slot
    FROM v24.cleanup_slots(p_fiber_id) s
    JOIN v24.slots sl ON sl.slot_id = s.slot_id
   WHERE sl.episode_id = v_ep.episode_id
   ORDER BY s.contribution_seq DESC, s.slot_id
   LIMIT 1;

  IF v_slot IS NOT NULL THEN
    v_released := true;
    IF EXISTS (SELECT 1 FROM v24.slots s
                WHERE s.slot_id = v_slot AND s.withdrawn_at IS NULL) THEN
      v_slots := v_slots || jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('slot_id',v_slot),
        'set',jsonb_build_object('withdrawn_at',now(),'released_at',now())));
    ELSE
      v_slots := v_slots || jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('slot_id',v_slot),
        'set',jsonb_build_object('released_at',now())));
    END IF;
    v_events := v_events || jsonb_build_array(jsonb_build_object(
      'entity_type','slot','entity_id',v_slot,
      'event_kind','slot_released',
      'payload',jsonb_build_object('slot_id',v_slot)));
  END IF;

  -- Close only after every slot of the episode/fiber is released; v_barrier
  -- already guarantees the provider pins and child installs are clear.
  IF v_ep.state <> 'closed'
     AND NOT EXISTS (SELECT 1 FROM v24.slots s
                      WHERE s.episode_id = v_ep.episode_id
                        AND s.released_at IS NULL
                        AND s.slot_id IS DISTINCT FROM v_slot)
     AND NOT EXISTS (SELECT 1 FROM v24.slots s
                      WHERE s.fiber_id = p_fiber_id
                        AND s.released_at IS NULL
                        AND s.slot_id IS DISTINCT FROM v_slot) THEN
    v_closed := true;
    v_ep_set := v_ep_set || jsonb_build_object('state','closed','closed_at',now());
    IF v_f.current_episode_id IS NOT DISTINCT FROM v_ep.episode_id THEN
      v_fiber_set := v_fiber_set || jsonb_build_object('current_episode_id', NULL);
    END IF;
    v_events := v_events || jsonb_build_array(jsonb_build_object(
      'entity_type','episode','entity_id',v_ep.episode_id,
      'event_kind','episode_closed',
      'payload',jsonb_build_object('episode_id',v_ep.episode_id)));
  ELSIF v_ep.state = 'closed'
        AND v_f.current_episode_id IS NOT DISTINCT FROM v_ep.episode_id
        AND NOT EXISTS (SELECT 1 FROM v24.slots s
                         WHERE s.episode_id = v_ep.episode_id
                           AND s.released_at IS NULL) THEN
    -- Defensive cleanup of a stale pointer to an already-drained episode.
    v_closed := true;
    v_fiber_set := v_fiber_set || jsonb_build_object('current_episode_id', NULL);
  END IF;

  IF v_closed
     AND NOT EXISTS (SELECT 1 FROM v24.slots s
                      WHERE s.fiber_id = p_fiber_id
                        AND s.released_at IS NULL
                        AND s.slot_id IS DISTINCT FROM v_slot)
     AND NOT EXISTS (SELECT 1 FROM v24.episodes e
                      WHERE e.fiber_id = p_fiber_id
                        AND e.state <> 'closed'
                        AND e.episode_id <> v_ep.episode_id) THEN
    v_fiber_done := true;
  END IF;

  RETURN jsonb_build_object(
    'action', CASE WHEN v_closed THEN 'close'
                   WHEN v_released THEN 'release'
                   WHEN v_retired THEN 'retire'
                   ELSE 'idle' END,
    'blocked',false,'fiber_done',v_fiber_done,'released_slot',v_released,
    'fibers',jsonb_build_array(jsonb_build_object(
      'key',jsonb_build_object('fiber_id',p_fiber_id),'set',v_fiber_set)),
    'episodes',CASE WHEN v_ep_set = '{}'::jsonb THEN '[]'::jsonb
                    ELSE jsonb_build_array(jsonb_build_object(
                      'key',jsonb_build_object('episode_id',v_ep.episode_id),
                      'set',v_ep_set)) END,
    'slots',v_slots,'pins',v_pins,'events',v_events);
END;
$$;

-- One bounded dispose/inspect stage.  Iterative array stack (no recursive
-- function calls), at most 16 installs+fibers update rows and 16 successors per
-- stage.
--
-- W2 semantics (C25/D-S5-11):
--   * preparing|prepare_unknown never write dispose_pending and never emit a
--     release.  A ready|claimed host_prepare blocks (the effect was not
--     executed); an unknown host_prepare with no resource_quiesced_at emits or
--     reuses exactly one inspect_resource successor targeting that effect;
--   * dispose_pending with a host_release status='unknown' AND
--     resource_quiesced_at IS NULL emits or reuses exactly one inspect for the
--     release, never a second release;
--   * prepare_failed is the one direct-tombstone state: after all obligations
--     are clear it writes disposed+disposed_at and one install_disposed
--     {released:false} without emitting any host_release;
--   * every other leaf keeps W1 child-before-owner release semantics and reuses
--     an existing ready|claimed host_release.
--
-- Cycle detection runs before the root traversal and again for every queued
-- install; any hit aborts the whole stage with an error object, so the caller
-- discards every accumulated update (failed command receipt, zero domain write).
CREATE FUNCTION v24.dispose_stage(p_install_id uuid, p_by_effect uuid, p_mode text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_stack uuid[] := ARRAY[p_install_id];
  v_seen uuid[] := '{}'::uuid[];
  v_order uuid[] := '{}'::uuid[];
  v_cur uuid;
  v_i v24.installs%ROWTYPE;
  v_f v24.fibers%ROWTYPE;
  v_target v24.effects%ROWTYPE;
  v_children uuid[];
  v_cycle uuid[];
  v_rows int := 0;
  v_idx int;
  v_fiber_count int;
  v_existing uuid;
  v_existing_inspect uuid;
  v_release uuid;
  v_inspect uuid;
  v_direct boolean;
  v_fiber uuid;
  v_planned uuid[];
  v_stage jsonb;
  v_stage_rows int;
  v_did_fiber boolean;
  v_ordinal int := 0;
  v_installs jsonb := '[]'::jsonb;
  v_fibers jsonb := '[]'::jsonb;
  v_eps jsonb := '[]'::jsonb;
  v_slots jsonb := '[]'::jsonb;
  v_pins jsonb := '[]'::jsonb;
  v_events jsonb := '[]'::jsonb;
  v_succ jsonb := '[]'::jsonb;
  v_releases jsonb := '[]'::jsonb;
  v_inspects jsonb := '[]'::jsonb;
  v_blocked_reason text := NULL;
BEGIN
  IF p_install_id IS NULL OR p_by_effect IS NULL
     OR p_mode IS NULL OR p_mode NOT IN ('command','cascade','close') THEN
    RETURN jsonb_build_object('error', v24.error_v1('invalid_args'));
  END IF;

  -- Fail closed before touching even one install row: an already-cyclic root
  -- must not accumulate a dispose_pending update that a later error discards.
  v_cycle := v24.cleanup_cycle(p_install_id);
  IF cardinality(v_cycle) > 0 THEN
    RETURN jsonb_build_object('error', v24.error_v1('cleanup_cycle',
      jsonb_build_object('path', to_jsonb(v_cycle), 'install_id', p_install_id)));
  END IF;

  -- Pass 1: mark the owner subtree pending, parent-first with depth-first
  -- discovery.  Child-before-owner matters for the release decision below, not
  -- for the intent write, so this order is deterministic and cheap.
  WHILE cardinality(v_stack) > 0 LOOP
    v_cur := v_stack[cardinality(v_stack)];
    v_stack := v_stack[1:cardinality(v_stack) - 1];
    IF v_cur = ANY(v_seen) THEN
      CONTINUE;
    END IF;

    SELECT * INTO v_i FROM v24.installs AS it
     WHERE it.install_id = v_cur FOR UPDATE;
    IF NOT FOUND THEN
      RETURN jsonb_build_object('error', v24.error_v1('invalid_args'));
    END IF;
    v_seen := v_seen || v_cur;
    IF v_i.state = 'disposed' THEN
      CONTINUE;
    END IF;

    -- Defensive: every queued install is checked before it is touched.
    v_cycle := v24.cleanup_cycle(v_cur);
    IF cardinality(v_cycle) > 0 THEN
      RETURN jsonb_build_object('error', v24.error_v1('cleanup_cycle',
        jsonb_build_object('path', to_jsonb(v_cycle), 'install_id', v_cur)));
    END IF;

    IF v_rows >= 16 THEN
      RETURN jsonb_build_object('action','blocked','reason','budget',
        'installs',v_installs,'fibers',v_fibers,'episodes',v_eps,
        'slots',v_slots,'pins',v_pins,'events',v_events,
        'successors',v_succ,'releases',v_releases,'inspects',v_inspects);
    END IF;

    -- C25 prepare convergence: keep the state untouched (the inspect matrix
    -- owns preparing|prepare_unknown -> installed|prepare_failed) and do not
    -- cascade children until the target is known.
    IF v_i.state IN ('preparing','prepare_unknown') THEN
      v_order := v_order || v_cur;
      CONTINUE;
    END IF;

    -- prepare_failed is the direct-tombstone state.  It also skips the pending
    -- intent so a blocked retry keeps saying "never prepared" instead of
    -- masquerading as an installed install awaiting release.
    IF v_i.state = 'prepare_failed' THEN
      v_order := v_order || v_cur;
      v_children := ARRAY(
        SELECT ci.install_id
          FROM v24.fibers f
          JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
          JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                              AND e.fiber_id = f.fiber_id
         WHERE f.install_id = v_cur
           AND ci.state <> 'disposed'
         ORDER BY ci.install_id);
      IF cardinality(v_children) > 0 THEN
        FOR v_idx IN REVERSE array_length(v_children, 1)..1 LOOP
          v_stack := v_stack || v_children[v_idx];
        END LOOP;
      END IF;
      CONTINUE;
    END IF;

    -- Stamp dispose_effect once, when the intent is first persisted.  The
    -- release identity is derived from the current command effect
    -- (p_by_effect) at release time, so re-stamping an already-pending install
    -- on every new key would only burn the 16-row budget and starve deep
    -- chains (the W1 contract still holds: the first disposing command owns the
    -- stored dispose_effect).
    IF v_i.state <> 'dispose_pending' THEN
      v_installs := v_installs || jsonb_build_array(jsonb_build_object(
        'key', jsonb_build_object('install_id', v_cur),
        'set', jsonb_build_object('state','dispose_pending',
                                  'dispose_effect', p_by_effect)));
      v_events := v_events || jsonb_build_array(jsonb_build_object(
        'entity_type','install','entity_id',v_cur,
        'event_kind','install_dispose_pending',
        'payload', jsonb_build_object('install_id', v_cur, 'by', p_mode)));
      v_rows := v_rows + 1;
    END IF;
    v_order := v_order || v_cur;

    v_children := ARRAY(
      SELECT ci.install_id
        FROM v24.fibers f
        JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
        JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                            AND e.fiber_id = f.fiber_id
       WHERE f.install_id = v_cur
         AND ci.state <> 'disposed'
       ORDER BY ci.install_id);
    IF cardinality(v_children) > 0 THEN
      -- Reverse push makes the smallest child pop first (deterministic DFS).
      FOR v_idx IN REVERSE array_length(v_children, 1)..1 LOOP
        v_stack := v_stack || v_children[v_idx];
      END LOOP;
    END IF;
  END LOOP;

  -- Pass 2: release/inspect/terminal decision in reverse discovery order.
  -- Because the walk is parent-first, this is children-before-owners.  One
  -- fiber stage per install per advance: a retire stage, a non-final
  -- contribution release, or a close-only stage stops here.  Only the stage
  -- that releases the final contribution may continue to the install release.
  IF cardinality(v_order) > 0 THEN
    FOR v_idx IN REVERSE array_length(v_order, 1)..1 LOOP
      v_cur := v_order[v_idx];
      v_did_fiber := false;
      SELECT * INTO v_i FROM v24.installs AS it WHERE it.install_id = v_cur;

      IF v_i.state = 'disposed' THEN
        CONTINUE;
      END IF;

      -- C25 prepare branch: inspect the executed-but-unknown host_prepare.
      -- A ready|claimed prepare has not run yet, so the only safe action is to
      -- block; a missing target is likewise not inspectable.
      IF v_i.state IN ('preparing','prepare_unknown') THEN
        SELECT * INTO v_target FROM v24.effects e
         WHERE e.kind = 'host_prepare'
           AND (e.request->>'install_id') = v_cur::text
         ORDER BY e.created_at DESC, e.effect_id DESC
         LIMIT 1;
        IF NOT FOUND THEN
          v_blocked_reason := coalesce(v_blocked_reason, 'prepare');
          CONTINUE;
        END IF;
        IF v_target.status IN ('ready','claimed') THEN
          v_blocked_reason := coalesce(v_blocked_reason, 'host_effect');
          CONTINUE;
        END IF;
        IF v_target.status IS DISTINCT FROM 'unknown'
           OR v_target.resource_quiesced_at IS NOT NULL THEN
          v_blocked_reason := coalesce(v_blocked_reason, 'prepare');
          CONTINUE;
        END IF;
        SELECT e.effect_id INTO v_existing_inspect
          FROM v24.effects e
         WHERE e.kind = 'inspect_resource'
           AND e.status IN ('ready','claimed')
           AND (e.request->>'install_id') = v_cur::text
           AND (e.request->>'target_effect_id') = v_target.effect_id::text
         ORDER BY e.created_at, e.effect_id
         LIMIT 1;
        IF EXISTS (SELECT 1 FROM v24.effects e
                    WHERE (e.request->>'install_id') = v_cur::text
                      AND e.status IN ('ready','claimed')
                      AND e.effect_id IS DISTINCT FROM v_existing_inspect) THEN
          v_blocked_reason := coalesce(v_blocked_reason, 'host_effect');
          CONTINUE;
        END IF;
        IF v_existing_inspect IS NULL THEN
          IF v_ordinal >= 16 THEN
            RETURN jsonb_build_object('action','blocked','reason','budget',
              'installs',v_installs,'fibers',v_fibers,'episodes',v_eps,
              'slots',v_slots,'pins',v_pins,'events',v_events,
              'successors',v_succ,'releases',v_releases,'inspects',v_inspects);
          END IF;
          v_inspect := md5(p_by_effect::text || ':inspect_resource:'
                           || v_cur::text || ':0')::uuid;
          v_succ := v_succ || jsonb_build_array(jsonb_build_object(
            'effect_id', v_inspect,
            'ordinal', v_ordinal,
            'kind', 'inspect_resource',
            'request', jsonb_build_object(
              'v', 1,
              'install_id', v_cur,
              'target', 'host_prepare',
              'target_effect_id', v_target.effect_id,
              'target_reservation', v_target.request->>'reservation',
              'target_request_digest', encode(v_target.request_digest,'hex'))));
          v_ordinal := v_ordinal + 1;
          v_events := v_events || jsonb_build_array(jsonb_build_object(
            'entity_type','install','entity_id',v_cur,
            'event_kind','install_inspect_requested',
            'payload', jsonb_build_object('install_id', v_cur,
              'inspect_effect_id', v_inspect,
              'target_effect_id', v_target.effect_id)));
        ELSE
          v_inspect := v_existing_inspect;
        END IF;
        v_inspects := v_inspects || jsonb_build_array(jsonb_build_object(
          'install_id', v_cur, 'effect_id', v_inspect,
          'reused', v_existing_inspect IS NOT NULL));
        CONTINUE;
      END IF;

      -- C25/D-S5-7 unknown recovery: any host effect that settled unknown
      -- without a quiescence proof is inspected, never re-released.  A host
      -- release is preferred over a stray host_prepare.
      IF v_i.state = 'dispose_pending' THEN
        SELECT * INTO v_target FROM v24.effects e
         WHERE e.kind IN ('host_prepare','host_release')
           AND e.status = 'unknown'
           AND e.resource_quiesced_at IS NULL
           AND (e.request->>'install_id') = v_cur::text
         ORDER BY (e.kind = 'host_release') DESC, e.created_at, e.effect_id
         LIMIT 1;
        IF v_target.effect_id IS NOT NULL THEN
          SELECT e.effect_id INTO v_existing_inspect
            FROM v24.effects e
           WHERE e.kind = 'inspect_resource'
             AND e.status IN ('ready','claimed')
             AND (e.request->>'install_id') = v_cur::text
             AND (e.request->>'target_effect_id') = v_target.effect_id::text
           ORDER BY e.created_at, e.effect_id
           LIMIT 1;
          IF EXISTS (SELECT 1 FROM v24.effects e
                      WHERE (e.request->>'install_id') = v_cur::text
                        AND e.status IN ('ready','claimed')
                        AND e.effect_id IS DISTINCT FROM v_existing_inspect) THEN
            v_blocked_reason := coalesce(v_blocked_reason, 'host_effect');
            CONTINUE;
          END IF;
          IF v_existing_inspect IS NULL THEN
            IF v_ordinal >= 16 THEN
              RETURN jsonb_build_object('action','blocked','reason','budget',
                'installs',v_installs,'fibers',v_fibers,'episodes',v_eps,
                'slots',v_slots,'pins',v_pins,'events',v_events,
                'successors',v_succ,'releases',v_releases,'inspects',v_inspects);
            END IF;
            v_inspect := md5(p_by_effect::text || ':inspect_resource:'
                             || v_cur::text || ':0')::uuid;
            v_succ := v_succ || jsonb_build_array(jsonb_build_object(
              'effect_id', v_inspect,
              'ordinal', v_ordinal,
              'kind', 'inspect_resource',
              'request', jsonb_build_object(
                'v', 1,
                'install_id', v_cur,
                'target', v_target.kind,
                'target_effect_id', v_target.effect_id,
                'target_reservation', v_target.request->>'reservation',
                'target_request_digest', encode(v_target.request_digest,'hex'))));
            v_ordinal := v_ordinal + 1;
            v_events := v_events || jsonb_build_array(jsonb_build_object(
              'entity_type','install','entity_id',v_cur,
              'event_kind','install_inspect_requested',
              'payload', jsonb_build_object('install_id', v_cur,
                'inspect_effect_id', v_inspect,
                'target_effect_id', v_target.effect_id)));
          ELSE
            v_inspect := v_existing_inspect;
          END IF;
          v_inspects := v_inspects || jsonb_build_array(jsonb_build_object(
            'install_id', v_cur, 'effect_id', v_inspect,
            'reused', v_existing_inspect IS NOT NULL));
          CONTINUE;
        END IF;
      END IF;

      -- C27 release/close: choose one fiber that still needs work.  Fibers
      -- with unreleased contributions come first (frozen LIFO release), then
      -- fibers with an open or not-yet-cleared episode.
      SELECT f.fiber_id INTO v_fiber
        FROM v24.fibers f
       WHERE f.install_id = v_cur
         AND (EXISTS (SELECT 1 FROM v24.slots s
                       WHERE s.fiber_id = f.fiber_id
                         AND s.released_at IS NULL)
              OR EXISTS (SELECT 1 FROM v24.episodes e
                          WHERE e.fiber_id = f.fiber_id
                            AND e.state <> 'closed')
              OR EXISTS (SELECT 1 FROM v24.episodes e
                          WHERE e.episode_id = f.current_episode_id
                            AND e.state <> 'closed'))
       ORDER BY (CASE WHEN EXISTS (SELECT 1 FROM v24.slots s
                                    WHERE s.fiber_id = f.fiber_id
                                      AND s.released_at IS NULL)
                      THEN 0 ELSE 1 END),
                f.fiber_id
       LIMIT 1;

      IF v_fiber IS NOT NULL THEN
        v_stage := v24.deactivate_stage(v_fiber, p_by_effect, p_mode);
        IF v_stage ? 'error' THEN
          RETURN jsonb_build_object('error', v_stage->'error');
        END IF;
        v_stage_rows := jsonb_array_length(coalesce(v_stage->'fibers','[]'::jsonb))
                      + jsonb_array_length(coalesce(v_stage->'episodes','[]'::jsonb))
                      + jsonb_array_length(coalesce(v_stage->'slots','[]'::jsonb))
                      + jsonb_array_length(coalesce(v_stage->'pins','[]'::jsonb));
        IF v_rows + v_stage_rows > 16 THEN
          RETURN jsonb_build_object('action','blocked','reason','budget',
            'installs',v_installs,'fibers',v_fibers,'episodes',v_eps,
            'slots',v_slots,'pins',v_pins,'events',v_events,
            'successors',v_succ,'releases',v_releases,'inspects',v_inspects);
        END IF;
        IF v_stage->>'action' = 'blocked' THEN
          -- Pure barrier: commit nothing for this install in this stage.
          v_blocked_reason := coalesce(v_blocked_reason, 'fiber');
          CONTINUE;
        END IF;
        v_fibers := v_fibers || coalesce(v_stage->'fibers','[]'::jsonb);
        v_eps := v_eps || coalesce(v_stage->'episodes','[]'::jsonb);
        v_slots := v_slots || coalesce(v_stage->'slots','[]'::jsonb);
        v_pins := v_pins || coalesce(v_stage->'pins','[]'::jsonb);
        v_events := v_events || coalesce(v_stage->'events','[]'::jsonb);
        v_rows := v_rows + v_stage_rows;
        IF v_stage->>'action' IN ('retire','release')
           OR NOT coalesce((v_stage->>'fiber_done')::boolean,false)
           OR NOT coalesce((v_stage->>'released_slot')::boolean,false) THEN
          -- This install consumed its one fiber stage; other installs in the
          -- same bounded advance may still take theirs (e.g. an inactive leaf
          -- release after a sibling retire).
          CONTINUE;
        END IF;
        -- Fall through only when no other fiber of this install still needs
        -- release/close work.  Other fibers' rows are still committed state,
        -- so this check is exact.
        IF EXISTS (SELECT 1 FROM v24.fibers f
                    WHERE f.install_id = v_cur
                      AND f.fiber_id <> v_fiber
                      AND (EXISTS (SELECT 1 FROM v24.slots s
                                    WHERE s.fiber_id = f.fiber_id
                                      AND s.released_at IS NULL)
                           OR EXISTS (SELECT 1 FROM v24.episodes e
                                       WHERE e.fiber_id = f.fiber_id
                                         AND e.state <> 'closed')
                           OR EXISTS (SELECT 1 FROM v24.episodes e
                                       WHERE e.episode_id = f.current_episode_id
                                         AND e.state <> 'closed'))) THEN
          v_did_fiber := true;
          CONTINUE;
        END IF;
        -- The final contribution was released and every fiber is done, so the
        -- same stage may tombstone and release the install.  The committed-
        -- state predicates below are skipped for this install: the episode/
        -- slot rows are in this delta, and the settlement-time
        -- install_disposed_ok recheck is the authority for the tombstone.
        v_did_fiber := true;
      END IF;

      -- Obligation 4: every direct child (fixed owner pair) is disposed.
      IF EXISTS (SELECT 1 FROM v24.fibers f
                   JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
                   JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                                       AND e.fiber_id = f.fiber_id
                  WHERE f.install_id = v_cur AND ci.state <> 'disposed') THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'child');
        CONTINUE;
      END IF;

      -- Reuse an existing ready|claimed release for this install instead of
      -- emitting a second one.  Any other ready|claimed host effect blocks.
      SELECT e.effect_id INTO v_existing
        FROM v24.effects e
       WHERE (e.request->>'install_id') = v_cur::text
         AND e.kind = 'host_release'
         AND e.status IN ('ready','claimed')
       ORDER BY e.created_at, e.effect_id
       LIMIT 1;
      IF EXISTS (SELECT 1 FROM v24.effects e
                  WHERE (e.request->>'install_id') = v_cur::text
                    AND e.status IN ('ready','claimed')
                    AND (e.kind <> 'host_release'
                         OR e.effect_id IS DISTINCT FROM v_existing)) THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'host_effect');
        CONTINUE;
      END IF;
      IF EXISTS (SELECT 1 FROM v24.effects e
                  WHERE (e.request->>'install_id') = v_cur::text
                    AND e.kind IN ('host_prepare','host_release','inspect_resource')
                    AND e.status = 'unknown'
                    AND e.resource_quiesced_at IS NULL) THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'host_effect');
        CONTINUE;
      END IF;

      v_direct := v_i.state = 'prepare_failed';
      v_planned := ARRAY(
        SELECT f.fiber_id FROM v24.fibers f
         WHERE f.install_id = v_cur AND f.disposed_at IS NULL
         ORDER BY f.fiber_id);

      IF v_rows + cardinality(v_planned)
         + (CASE WHEN v_direct AND v_existing IS NULL THEN 1 ELSE 0 END) > 16 THEN
        RETURN jsonb_build_object('action','blocked','reason','budget',
          'installs',v_installs,'fibers',v_fibers,'episodes',v_eps,
          'slots',v_slots,'pins',v_pins,'events',v_events,
          'successors',v_succ,'releases',v_releases,'inspects',v_inspects);
      END IF;

      -- Own fibers are inactive and obligation-free: tombstone them with the
      -- release/direct-tombstone in the same bounded stage (S2 leaf semantics).
      FOR v_f IN SELECT * FROM v24.fibers f
                  WHERE f.install_id = v_cur AND f.disposed_at IS NULL
                  ORDER BY f.fiber_id LOOP
        v_fibers := v_fibers || jsonb_build_array(jsonb_build_object(
          'key', jsonb_build_object('fiber_id', v_f.fiber_id),
          'set', jsonb_build_object('disposed_at', now(), 'want_on', false)));
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','fiber','entity_id',v_f.fiber_id,
          'event_kind','fiber_disposed',
          'payload', jsonb_build_object('fiber_id', v_f.fiber_id,
                                        'install_id', v_cur)));
        v_rows := v_rows + 1;
      END LOOP;

      -- C27 direct tombstone (G4-J2): a prepare that never succeeded leaves no
      -- external artifact, so the install becomes disposed with zero releases.
      IF v_direct AND v_existing IS NULL THEN
        IF v_did_fiber THEN
          -- One phase per advance: the fiber/episode/slot rows are still
          -- uncommitted, so the direct tombstone waits for the next key.
          CONTINUE;
        END IF;
        IF NOT v24.install_disposed_ok(v_cur, NULL, NULL, v_planned) THEN
          v_blocked_reason := coalesce(v_blocked_reason, 'obligation');
          CONTINUE;
        END IF;
        v_installs := v_installs || jsonb_build_array(jsonb_build_object(
          'key', jsonb_build_object('install_id', v_cur),
          'set', jsonb_build_object('state','disposed',
                                    'dispose_effect',p_by_effect,
                                    'disposed_at',now())));
        v_rows := v_rows + 1;
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','install','entity_id',v_cur,
          'event_kind','install_disposed',
          'payload', jsonb_build_object('state','disposed','released',false)));
        CONTINUE;
      END IF;

      -- Pre-release predicate: everything except the not-yet-created release.
      -- When this delta already closed the last episode/released the last
      -- slot, the committed rows still look open; the settlement-time
      -- install_disposed_ok recheck owns the tombstone instead.
      IF NOT v_did_fiber
         AND NOT v24.install_disposed_ok_except_release(v_cur, NULL, v_planned) THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'obligation');
        CONTINUE;
      END IF;

      IF v_existing IS NULL THEN
        IF v_ordinal >= 16 THEN
          RETURN jsonb_build_object('action','blocked','reason','budget',
            'installs',v_installs,'fibers',v_fibers,'episodes',v_eps,
            'slots',v_slots,'pins',v_pins,'events',v_events,
            'successors',v_succ,'releases',v_releases,'inspects',v_inspects);
        END IF;
        v_release := md5(p_by_effect::text || ':host_release:'
                         || v_cur::text || ':0')::uuid;
        v_succ := v_succ || jsonb_build_array(jsonb_build_object(
          'effect_id', v_release,
          'ordinal', v_ordinal,
          'kind', 'host_release',
          'request', jsonb_build_object(
            'install_id', v_cur,
            'reservation', 'v24:host_release:' || v_release::text)));
        v_ordinal := v_ordinal + 1;
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','install','entity_id',v_cur,
          'event_kind','install_release_requested',
          'payload', jsonb_build_object('install_id', v_cur,
                                        'release_effect_id', v_release)));
      ELSE
        v_release := v_existing;
      END IF;

      v_releases := v_releases || jsonb_build_array(jsonb_build_object(
        'install_id', v_cur,
        'effect_id', v_release,
        'reused', v_existing IS NOT NULL));
    END LOOP;
  END IF;

  RETURN jsonb_build_object(
    'action', CASE
                WHEN jsonb_array_length(v_releases) > 0 THEN 'release'
                WHEN jsonb_array_length(v_inspects) > 0 THEN 'inspect'
                WHEN jsonb_array_length(v_installs) > 0
                  OR jsonb_array_length(v_fibers) > 0
                  OR jsonb_array_length(v_eps) > 0
                  OR jsonb_array_length(v_slots) > 0
                  OR jsonb_array_length(v_pins) > 0 THEN 'progress'
                ELSE 'blocked'
              END,
    'reason', CASE WHEN v_blocked_reason IS NOT NULL THEN v_blocked_reason END,
    'installs', v_installs,
    'fibers', v_fibers,
    'episodes', v_eps,
    'slots', v_slots,
    'pins', v_pins,
    'events', v_events,
    'successors', v_succ,
    'releases', v_releases,
    'inspects', v_inspects);
END;
$$;
