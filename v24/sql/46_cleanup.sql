-- S5 W1: cleanup graph, predicates and the bounded dispose stage.
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

-- One bounded dispose stage.  Iterative array stack (no recursive function
-- calls), at most 16 installs+fibers update rows and 16 successors per stage.
--
-- W1 semantics:
--   * every reachable owner descendant is marked dispose_pending with
--     dispose_effect = by_effect; direct children use the immutable
--     (owner_fiber_id, owner_episode_id) pair;
--   * releases are evaluated children-before-owners, but only from committed
--     row state: a child that is still dispose_pending keeps its owner pending
--     with zero release;
--   * a leaf with no active fiber disposes its own fibers and emits exactly one
--     deterministic host_release; a leaf with an active fiber only writes
--     dispose_pending and waits for fiber_control(off);
--   * an existing ready|claimed host_release is reused, never duplicated;
--   * preparing/prepare_unknown keeps the S2 G3a-K behavior for W1: state is
--     moved to dispose_pending with no release and no inspect.  W2 replaces
--     this branch with inspect convergence - do not add inspect here.
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
  v_children uuid[];
  v_cycle uuid[];
  v_rows int := 0;
  v_idx int;
  v_fiber_count int;
  v_existing uuid;
  v_release uuid;
  v_ordinal int := 0;
  v_installs jsonb := '[]'::jsonb;
  v_fibers jsonb := '[]'::jsonb;
  v_events jsonb := '[]'::jsonb;
  v_succ jsonb := '[]'::jsonb;
  v_releases jsonb := '[]'::jsonb;
  v_blocked_reason text := NULL;
BEGIN
  IF p_install_id IS NULL OR p_by_effect IS NULL
     OR p_mode IS NULL OR p_mode NOT IN ('command','cascade') THEN
    -- `close` is accepted by the shared C27 helper only from W3; W1 rejects it
    -- as invalid_args exactly like any other bad mode.
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
        'installs',v_installs,'fibers',v_fibers,'events',v_events,
        'successors',v_succ,'releases',v_releases);
    END IF;

    -- A new command key must re-stamp dispose_effect so the release identity
    -- stays derived from the command that actually drives this stage.
    IF v_i.state <> 'dispose_pending'
       OR v_i.dispose_effect IS DISTINCT FROM p_by_effect THEN
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

    -- W1 preserves the S2 G3a-K prepare boundary exactly: persist the pending
    -- intent, but do not cascade children and do not release/inspect.  A
    -- prepare-unknown target may later turn out to be installed, so touching
    -- its subtree now would be premature.  W2 replaces this with inspect
    -- convergence; do not add inspect here.
    IF v_i.state IN ('preparing','prepare_unknown') THEN
      CONTINUE;
    END IF;

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

  -- Pass 2: release/terminal decision in reverse discovery order.  Because the
  -- walk is parent-first, this is children-before-owners.  The decisions below
  -- read committed rows; an install marked pending in this stage is not
  -- disposed yet, so its owner always remains blocked.
  IF cardinality(v_order) > 0 THEN
    FOR v_idx IN REVERSE array_length(v_order, 1)..1 LOOP
      v_cur := v_order[v_idx];
      SELECT * INTO v_i FROM v24.installs AS it WHERE it.install_id = v_cur;

      IF v_i.state = 'disposed' THEN
        CONTINUE;
      END IF;

      -- W1 preserves the S2 G3a-K prepare boundary exactly.  W2 replaces this
      -- with the inspect convergence matrix; do not emit inspect here.
      IF v_i.state IN ('preparing','prepare_unknown') THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'prepare');
        CONTINUE;
      END IF;

      -- Obligation 1: every episode of every own fiber is closed and no fiber
      -- still points at a current episode.  Active work blocks the release.
      IF EXISTS (SELECT 1 FROM v24.fibers f
                  WHERE f.install_id = v_cur
                    AND f.current_episode_id IS NOT NULL)
         OR EXISTS (SELECT 1 FROM v24.fibers f
                      JOIN v24.episodes e ON e.fiber_id = f.fiber_id
                     WHERE f.install_id = v_cur AND e.state <> 'closed') THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'fiber');
        CONTINUE;
      END IF;

      -- Obligation 2: every slot released.
      IF EXISTS (SELECT 1 FROM v24.fibers f
                   JOIN v24.slots s ON s.fiber_id = f.fiber_id
                  WHERE f.install_id = v_cur AND s.released_at IS NULL) THEN
        v_blocked_reason := coalesce(v_blocked_reason, 'slot');
        CONTINUE;
      END IF;

      -- Obligation 3: every direct child (fixed owner pair) is disposed.
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

      SELECT count(*) INTO v_fiber_count
        FROM v24.fibers f
       WHERE f.install_id = v_cur AND f.disposed_at IS NULL;

      IF v_rows + v_fiber_count > 16 THEN
        RETURN jsonb_build_object('action','blocked','reason','budget',
          'installs',v_installs,'fibers',v_fibers,'events',v_events,
          'successors',v_succ,'releases',v_releases);
      END IF;

      -- Own fibers are inactive and obligation-free: tombstone them with the
      -- release in the same bounded stage (S2 leaf semantics).
      FOR v_f IN SELECT * FROM v24.fibers f
                  WHERE f.install_id = v_cur AND f.disposed_at IS NULL
                  ORDER BY f.fiber_id LOOP
        v_fibers := v_fibers || jsonb_build_array(jsonb_build_object(
          'key', jsonb_build_object('fiber_id', v_f.fiber_id),
          'set', jsonb_build_object('disposed_at', now(), 'want_on', false)));
        v_rows := v_rows + 1;
      END LOOP;

      IF v_existing IS NULL THEN
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
                WHEN jsonb_array_length(v_installs) > 0
                  OR jsonb_array_length(v_fibers) > 0 THEN 'progress'
                ELSE 'blocked'
              END,
    'reason', CASE WHEN v_blocked_reason IS NOT NULL THEN v_blocked_reason END,
    'installs', v_installs,
    'fibers', v_fibers,
    'events', v_events,
    'successors', v_succ,
    'releases', v_releases);
END;
$$;
