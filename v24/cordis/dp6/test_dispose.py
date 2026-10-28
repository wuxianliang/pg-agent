"""CDP6-U/D: unknown debt discovery/blocking and production dispose convergence.

Run with: uv run python v24/cordis/dp6/test_dispose.py

Every install, activation, listener, run fact, dispose request, P6 step and
settlement goes through the existing ``advance`` protocol unless the line says
"owner fixture": those are owner-only DML setups for a debt/fault object the
production registrars do not create (an unverifiable external inverse, an
unknown outcome, a corrupt graph) plus the graph-bound negatives.  No SQL is
added by this gate and no second planner is used: the assertions read the
existing ``p6_plan``/``dispose_plan``/``dispose_subtree`` results and the ten
tables.

The gate is deliberately separate from ``test_recovery`` (CDP6-R) and does not
re-prove claim/receipt/journal mechanics.  It reuses the W2 executor only to
show that explicitly replayable work keeps moving while a terminal unknown debt
blocks disposal, and that no debt is resolved by guessing.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import make_dsn
from psycopg2.extras import Json

CORDIS = Path(__file__).resolve().parents[1]
DP1 = CORDIS / 'dp1'
DP2 = CORDIS / 'dp2'
DP3 = CORDIS / 'dp3'
DP4 = CORDIS / 'dp4'
DP5 = CORDIS / 'dp5'
DP6 = Path(__file__).resolve().parent
for path in (CORDIS, DP1, DP2, DP3, DP4, DP5, DP6):
    sys.path.insert(0, str(path))

from setup_db import Server, TestDB  # noqa: E402
from test_support import (query, api, command, snapshot, no_write,  # noqa: E402
                          reconcile_payload)
from test_activation import one, commit_new  # noqa: E402
from test_teardown import (root_install, activate, enter_closing, p6_slot,  # noqa: E402
                           drain, owner_of)
from dp4_support import claim, settle  # noqa: E402
from test_dispatch import HOST, listener, create as dispatch_create  # noqa: E402
from test_recovery import Handler, Provider, make_maintainer  # noqa: E402
import driver as drv  # noqa: E402

EXIT_KILLED = -signal.SIGKILL
DISPOSE_CHILD_ENV = 'DP6_DISPOSE_CHILD'


# ------------------------------------------------------------------ fixtures

def owner_rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        got = query(conn, statement, params)
        conn.rollback()
        return got


def owner_one(db, statement, params=()):
    return owner_rows(db, statement, params)[0][0]


def owner_do(db, statement, params=()):
    """Owner-only fixture write.  Every writer takes G before row locks."""
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, statement, params)
        conn.commit()


def snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        got = snapshot(conn)
        conn.rollback()
        return got


def zero_write(db, fn):
    """Run one rejected/no-op path and prove all ten tables are unchanged."""
    before = snap(db)
    result = fn()
    after = snap(db)
    assert after == before, (result, 'ten-table write on a blocked/deferred path')
    return result


def error_code(result):
    return (result or {}).get('error', {}).get('code')


def plan_of(db, install):
    return one(db, 'SELECT v24_cordis.dispose_plan(%s)', (install,))


def p6_of(db, fiber, effect=None):
    """Read-only P6 diagnosis; pass the live slot id so the planner excludes itself."""
    return one(db, 'SELECT v24_cordis.p6_plan(%s,%s)', (effect, fiber))


def scanner(db, actors=None):
    provider_obj = Provider(db, {db.roles['service']} if actors is None else actors)
    return drv.Maintainer(observer_connect=provider_obj.observer,
                          actor_connect=provider_obj.actor,
                          ensure_actor=db.roles['service'])


def dispose(db, install, *, key=None, effect=None, alias='service'):
    with contextlib.closing(db.connect(alias)) as conn:
        eff, outcome = command(db, conn, alias, 'command_dispose',
                               {'install_id': str(install)}, key=key, effect=effect)
        result = api(conn, eff, outcome)
        conn.commit()
    return eff, result, outcome


def request_dispose(db, install):
    """The production dispose intent: installed -> dispose_pending."""
    effect, result, outcome = dispose(db, install)
    assert result.get('disposition') == 'committed', result
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (install,)) == 'dispose_pending'
    return effect, outcome


def tree(db, *, listeners=0, consumers=0, requires=True):
    """root -> child -> grandchild, plus sibling consumers outside child's subtree.

    The grandchild is the provider (``gc-svc`` + optional host listener) and the
    consumers pin its contribution from outside the disposed install, so a
    dispose of ``child`` must wait for those external pins.  A run is injected
    later per test because a legal run needs a settled ``run_start``.
    """
    root = root_install(db)
    scope = uuid.UUID(root['scope']['id'])
    child = activate(db, root, provides=['tree-svc'])
    ls = ([listener('tree-host', 'emit', 10,
                    {'type': 'host', 'capability': 'listener_call'})]
          if listeners else None)
    contracts = {'listener_call': HOST} if listeners else None
    payload_g, grand, result_g = dispatch_create(
        db, scope, owner_of(db, child['fiber_id']), provides=['gc-svc'],
        listeners=ls, contracts=contracts, requires=['tree-svc'] if requires else ())
    assert result_g.get('disposition') == 'committed', result_g
    pins = []
    for _ in range(consumers):
        payload_k, fiber_k, result_k = dispatch_create(
            db, scope, owner_of(db, root['fiber_id']), requires=['gc-svc'])
        assert result_k.get('disposition') == 'committed', result_k
        pins.append(dict(payload=payload_k, fiber=fiber_k,
                         install=uuid.UUID(payload_k['install_id'])))
    return dict(root=root, scope=scope, child=child,
                grand=dict(payload=payload_g, fiber=grand), consumers=pins)


def host_calls(db, fiber, status=None):
    statement = ("SELECT id,ordinal,status,input->>'listener_id' FROM v24_cordis.effects "
                 "WHERE kind='listener_call' AND fiber_id=%s")
    params = [fiber]
    if status is not None:
        statement += ' AND status=%s'
        params.append(status)
    return owner_rows(db, statement + ' ORDER BY ordinal,id', tuple(params))


def settle_host_calls(db, fiber):
    """Settle every ready host listener_call owned by this provider fiber."""
    calls = host_calls(db, fiber, 'ready')
    for effect, _ordinal, _status, _listener in calls:
        effect = uuid.UUID(str(effect))
        token = claim(db, effect)
        assert token.get('disposition') == 'claimed', token
        result = settle(db, effect, {'kind': 'listener_call',
                                     'result': {'value': {'ok': True}}}, token['claim'])
        assert result.get('disposition') == 'committed', result
    return len(calls)


def open_run(db, t):
    fiber = t['grand']['fiber']
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    run = uuid.uuid4()
    owner_do(db, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,'
                 'remaining_steps) VALUES(%s,%s,%s,%s,1)',
             (run, fiber, episode, t['scope']))
    return run


def end_run(db, run):
    owner_do(db, 'UPDATE v24_cordis.runs SET ended_at=clock_timestamp() WHERE id=%s', (run,))


def add_unknown_effect(db, fiber, kind='model_call'):
    """Owner fixture: a terminal unknown outcome the production loop cannot create."""
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    effect = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,input,"
                 "request_actor,outcome,settled_at) VALUES(%s,%s,%s,%s,'unknown','{}',%s,%s,"
                 'clock_timestamp())',
             (effect, fiber, episode, kind, db.roles['service'],
              Json({'v': 1, 'class': 'unknown', 'claim': None,
                    'body': {'kind': kind}})))
    return effect


def add_inverse_unknown(db, fiber, *, key='external-resource'):
    """Owner fixture: an external inverse the closed inverse set cannot verify."""
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    seq = owner_one(db, 'SELECT coalesce(max(seq),-1)+1 FROM v24_cordis.contributions '
                        'WHERE fiber_id=%s AND episode_id=%s', (fiber, episode))
    contribution = uuid.uuid4()
    debt = {'resource': key, 'compensate': 'close-handle', 'replay_authorized': False}
    owner_do(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,"
                 "key,descriptor,inverse,contract_version) VALUES(%s,%s,%s,%s,'service','root',%s,"
                 "'{}',%s,'1')",
             (contribution, fiber, episode, seq, key,
              Json({'op': 'unknown', 'debt': debt})))
    return contribution, debt


def subtree_states(db, install):
    return owner_rows(db, 'SELECT DISTINCT i.id,i.state FROM v24_cordis.installs i '
                          'WHERE i.id IN (SELECT install_id FROM '
                          'v24_cordis.dispose_subtree(%s)) ORDER BY i.id', (install,))


def drive(db, install, maintainer, limit=80):
    """Bounded fair driving; one page per topic per pass, no sleeps."""
    for passes in range(1, limit + 1):
        states = subtree_states(db, install)
        if states and all(state == 'disposed' for _id, state in states):
            return passes
        maintainer.run_once()
    raise AssertionError(('dispose subtree did not converge', states))


def quiet_passes(db, maintainer, *, settle=14, quiet=3):
    """Settle legitimate non-debt work, then prove the blocked steady state is write-free.

    A sealed install still has to run its normal leave/closing P6 sequence; that is
    real protocol progress, not debt churn.  Once two consecutive passes leave the
    ten tables unchanged, the next ``quiet`` passes must stay unchanged too.
    """
    last = snap(db)
    reports = []
    for _ in range(settle):
        reports.append(maintainer.run_once())
        now = snap(db)
        if now == last:
            break
        last = now
    else:
        raise AssertionError('maintenance did not reach a quiet steady state')
    for _ in range(quiet):
        reports.append(maintainer.run_once())
        assert snap(db) == last, 'a blocked steady state must not write any of the ten tables'
    return reports


def event_phases(db, install):
    return owner_rows(db, "SELECT payload->>'phase',payload->>'fiber_id',"
                          "payload->>'child_install_id' FROM v24_cordis.events "
                          "WHERE entity_type='install' AND entity_id=%s "
                          "AND event_kind='install_dispose_progress' ORDER BY seq", (install,))


def expect_sqlstate(db, alias, statement, params=(), code='42501'):
    with contextlib.closing(db.connect(alias)) as conn:
        try:
            query(conn, statement, params)
        except psycopg2.Error as exc:
            conn.rollback()
            assert exc.pgcode == code, (exc.pgcode, str(exc))
        else:
            conn.rollback()
            raise AssertionError('expected SQLSTATE ' + code)


# ------------------------------------------------------- CDP6-U1/U2: debts

def test_unknown_effect_debt(db):
    t = tree(db)
    child_install = uuid.UUID(t['child']['install_id'])
    child_fiber = uuid.UUID(t['child']['fiber_id'])
    grand_fiber = t['grand']['fiber']
    deep = add_unknown_effect(db, grand_fiber)
    own = add_unknown_effect(db, child_fiber)
    request_dispose(db, child_install)

    # Enter the closing generation so the P6 planner can report the debt barrier.
    control = enter_closing(db, grand_fiber)
    p6_slot(db, grand_fiber, control)
    plan = plan_of(db, child_install)
    assert plan == {'kind': 'blocked_unknown', 'reason': 'effect'}, plan
    assert p6_of(db, grand_fiber) == {'kind': 'blocked_unknown', 'reason': 'effect'}

    result = zero_write(db, lambda: dispose(db, child_install)[1])
    assert error_code(result) == 'blocked_unknown', result
    maintainer = scanner(db)
    commands_before = owner_one(db, "SELECT count(*) FROM v24_cordis.effects "
                                    "WHERE kind='command_dispose'")
    reports = quiet_passes(db, maintainer)
    assert owner_one(db, "SELECT count(*) FROM v24_cordis.effects "
                         "WHERE kind='command_dispose'") == commands_before
    steady = snap(db)
    debts = {d['effect_id']: d for report in reports for d in report.diagnostics
             if d.get('driver') == 'unknown_effect_debt'}
    assert set(debts) == {str(deep), str(own)}, debts
    assert debts[str(deep)]['fiber_id'] == str(grand_fiber)
    assert debts[str(deep)]['kind'] == 'model_call'
    assert debts[str(deep)]['fiber_disposed'] is False
    assert debts[str(deep)]['install_state'] == 'installed'
    assert 'fiber_drain' in debts[str(deep)]['blocks'], debts[str(deep)]
    assert debts[str(own)]['fiber_id'] == str(child_fiber)
    assert debts[str(own)]['install_state'] == 'dispose_pending'
    assert {'install_dispose', 'fiber_drain'} <= set(debts[str(own)]['blocks'])

    # Terminal facts are immutable; no claim or receipt may rewrite the outcome.
    expect_sqlstate(db, 'owner', "UPDATE v24_cordis.effects SET status='succeeded' "
                                 'WHERE id=%s', (deep,), '55000')
    claim_result = claim(db, deep)
    assert error_code(claim_result) == 'receipt_conflict', claim_result
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (deep,)) == 'unknown'

    # A restart with empty scanner memory sees the same terminal debt.
    restarted = scanner(db)
    for _ in range(2):
        restarted.run_once()
    assert snap(db) == steady
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (deep,)) == 'unknown'
    states = dict(subtree_states(db, child_install))
    assert states[child_install] == 'dispose_pending'
    assert all(state != 'disposed' for state in states.values()), states
    print('[CDP6-U1] terminal effect unknown is discovered as stable debt, blocks P6/dispose '
          'with ten-table zero write, cannot be re-claimed or rewritten, and survives restart')


def test_inverse_unknown_debt(db):
    t = tree(db)
    child_install = uuid.UUID(t['child']['install_id'])
    grand_fiber = t['grand']['fiber']
    contribution, debt = add_inverse_unknown(db, grand_fiber)
    request_dispose(db, child_install)
    control = enter_closing(db, grand_fiber)
    p6_slot(db, grand_fiber, control)

    plan = plan_of(db, child_install)
    assert plan == {'kind': 'blocked_unknown', 'reason': 'inverse'}, plan
    assert p6_of(db, grand_fiber) == {'kind': 'blocked_unknown', 'reason': 'inverse'}
    result = zero_write(db, lambda: dispose(db, child_install)[1])
    assert error_code(result) == 'blocked_unknown', result
    # Nothing silently released the unverifiable contribution or finished the owner.
    assert owner_one(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions '
                         'WHERE id=%s', (contribution,)) is True

    commands_before = owner_one(db, "SELECT count(*) FROM v24_cordis.effects "
                                    "WHERE kind='command_dispose'")
    maintainer = scanner(db)
    reports = quiet_passes(db, maintainer)
    steady = snap(db)
    assert owner_one(db, "SELECT count(*) FROM v24_cordis.effects "
                         "WHERE kind='command_dispose'") == commands_before
    debts = [d for report in reports for d in report.diagnostics
             if d.get('driver') == 'inverse_unknown_debt']
    assert debts and all(d['contribution_id'] == str(contribution) for d in debts)
    got = debts[0]
    assert got['fiber_id'] == str(grand_fiber) and got['inverse_op'] == 'unknown'
    assert got['debt_digest'] == drv.sha256_hex(debt), got
    assert got['install_state'] == 'installed'
    assert 'fiber_drain' in got['blocks'], got
    # The descriptor content is never copied into host diagnostics.
    assert 'close-handle' not in json.dumps(got, default=str)

    expect_sqlstate(db, 'owner', "UPDATE v24_cordis.contributions SET inverse='{\"op\":"
                                 "\"delete_row\"}'::jsonb WHERE id=%s", (contribution,), '55000')
    expect_sqlstate(db, 'service', 'UPDATE v24_cordis.contributions SET released_at=now() '
                                   'WHERE id=%s', (contribution,), '42501')
    assert snap(db) == steady
    restarted = scanner(db)
    for _ in range(2):
        restarted.run_once()
    assert snap(db) == steady
    states = dict(subtree_states(db, child_install))
    assert states[child_install] == 'dispose_pending'
    assert all(state != 'disposed' for state in states.values()), states
    print('[CDP6-U2] inverse unknown is a separate debt with a stable digest, blocks dispose/P6 '
          'with zero write, is never released or re-inverted, and survives restart')


def test_safe_replay_under_debt(db):
    t = tree(db, listeners=1)
    child_install = uuid.UUID(t['child']['install_id'])
    grand_fiber = t['grand']['fiber']
    unknown = add_unknown_effect(db, grand_fiber)
    request_dispose(db, child_install)
    ready = host_calls(db, grand_fiber, 'ready')
    assert ready, ready
    listener_effect = uuid.UUID(str(ready[0][0]))

    # The debt blocks disposal but an explicitly replayable effect still moves:
    # the claim is lost to lease expiry, then the W2 executor reclaims it once.
    token = claim(db, listener_effect, lease=150)
    assert token.get('disposition') == 'claimed', token
    time.sleep(0.25)
    journal_dir = Path('/tmp') / ('dp6-u3-' + uuid.uuid4().hex)
    handler = Handler('model_final')
    maintainer, executor, _provider = make_maintainer(
        db, handler, drv.ReceiptJournal(journal_dir), None, lease_ms=150)
    for _ in range(4):
        maintainer.run_once()
    status = owner_rows(db, 'SELECT status,attempt,fence FROM v24_cordis.effects WHERE id=%s',
                        (listener_effect,))[0]
    assert status[0] == 'succeeded', status
    calls = [c for c in handler.calls if c['effect_id'] == str(listener_effect)]
    assert len(calls) == 1 and calls[0]['fence'] == status[2] == 2, calls
    assert status[1] == 2
    # No guess about the debt: it is still terminal unknown and still blocks.
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
                     (unknown,)) == 'unknown'
    assert plan_of(db, child_install) == {'kind': 'blocked_unknown', 'reason': 'effect'}
    assert error_code(dispose(db, child_install)[1]) == 'blocked_unknown'
    # A terminal unknown cannot be claimed (no unauthorized replay).
    assert error_code(claim(db, unknown)) == 'receipt_conflict'
    print('[CDP6-U3] under a terminal debt an expired claim with repeat+concurrent is reclaimed '
          'once and settles; the debt itself is never re-claimed or replayed into a result')


def test_no_time_based_unknown_upgrade(db):
    t = tree(db, listeners=0)
    child_install = uuid.UUID(t['child']['install_id'])
    grand_fiber = t['grand']['fiber']
    unknown = add_unknown_effect(db, grand_fiber)
    before = owner_rows(db, 'SELECT status,outcome,settled_at,attempt,fence FROM '
                            'v24_cordis.effects WHERE id=%s', (unknown,))[0]
    request_dispose(db, child_install)
    maintainer = scanner(db)
    quiet_passes(db, maintainer)
    steady = snap(db)
    # Lease time passes; nothing may turn the unknown into success/failure or add events.
    time.sleep(0.2)
    assert snap(db) == steady
    for _ in range(3):
        maintainer.run_once()
    assert snap(db) == steady
    after = owner_rows(db, 'SELECT status,outcome,settled_at,attempt,fence FROM '
                           'v24_cordis.effects WHERE id=%s', (unknown,))[0]
    assert after == before, (before, after)
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s',
                     (unknown,)) == 0
    assert p6_of(db, grand_fiber) == {'kind': 'blocked_unknown', 'reason': 'effect'}
    print('[CDP6-U4] elapsed time, repeated scans and a quiet return never upgrade an unknown '
          'outcome or emit reducer/event rows for it')


# ------------------------------------------------- CDP6-D1: subtree obligations

def test_dispose_tree_obligations(db):
    t = tree(db, listeners=1, consumers=2)
    child_install = uuid.UUID(t['child']['install_id'])
    grand_fiber = t['grand']['fiber']
    child_fiber = uuid.UUID(t['child']['fiber_id'])
    run = open_run(db, t)
    request_dispose(db, child_install)

    assert len(host_calls(db, grand_fiber, 'ready')) >= 1
    assert plan_of(db, child_install) == {'kind': 'deferred', 'reason': 'effect'}

    assert settle_host_calls(db, grand_fiber) >= 1
    assert plan_of(db, child_install) == {'kind': 'deferred', 'reason': 'run'}
    end_run(db, run)

    # Enter the closing generation through the production off/advance pair, then let
    # P6 report the external-pin barrier.  No second planner is involved.
    control = enter_closing(db, grand_fiber)
    slot, _slot_outcome, _slot_seq = p6_slot(db, grand_fiber, control)
    assert p6_of(db, grand_fiber, slot) == {'kind': 'deferred', 'reason': 'pin'}, \
        p6_of(db, grand_fiber, slot)

    # Two consumers share the same provider contribution: releasing one pin is not enough.
    pins = owner_one(db, 'SELECT count(*) FROM v24_cordis.pins p JOIN '
                         'v24_cordis.contributions c ON c.id=p.contribution_id '
                         'WHERE c.fiber_id=%s AND p.released_at IS NULL', (grand_fiber,))
    assert pins == 2, pins
    first, second = t['consumers']
    drain(db, first['fiber'], enter_closing(db, first['fiber']))
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins p JOIN '
                         'v24_cordis.contributions c ON c.id=p.contribution_id '
                         'WHERE c.fiber_id=%s AND p.released_at IS NULL', (grand_fiber,)) == 1
    assert p6_of(db, grand_fiber, slot) == {'kind': 'deferred', 'reason': 'pin'}
    assert owner_one(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions c '
                         'WHERE c.fiber_id=%s AND c.kind=%s', (grand_fiber, 'service')) is True
    noop = dispose(db, child_install)[1]
    assert noop.get('disposition') == 'committed' and noop['emitted'] == [], noop
    assert p6_of(db, grand_fiber, slot) == {'kind': 'deferred', 'reason': 'pin'}
    assert owner_one(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions c '
                         'WHERE c.fiber_id=%s AND c.kind=%s', (grand_fiber, 'service')) is True
    maintainer = scanner(db)

    drain(db, second['fiber'], enter_closing(db, second['fiber']))
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins p JOIN '
                         'v24_cordis.contributions c ON c.id=p.contribution_id '
                         'WHERE c.fiber_id=%s AND p.released_at IS NULL', (grand_fiber,)) == 0
    drive(db, child_install, maintainer)

    states = dict(subtree_states(db, child_install))
    assert states and all(state == 'disposed' for state in states.values()), states
    # child-before-owner, grandchild-first, one tombstone each, history retained.
    grand_disposed = owner_one(db, 'SELECT disposed_at FROM v24_cordis.fibers WHERE id=%s',
                               (grand_fiber,))
    child_disposed = owner_one(db, 'SELECT disposed_at FROM v24_cordis.fibers WHERE id=%s',
                               (child_fiber,))
    assert grand_disposed is not None and child_disposed is not None
    assert grand_disposed <= child_disposed, (grand_disposed, child_disposed)
    phases = event_phases(db, child_install)
    grand_completed = [i for i, (phase, _f, ci) in enumerate(phases)
                       if phase == 'completed' and ci == t['grand']['payload']['install_id']]
    child_completed = [i for i, (phase, _f, ci) in enumerate(phases)
                       if phase == 'completed' and ci is None]
    grand_fiber_disposed = [i for i, (phase, f, _c) in enumerate(phases)
                            if phase == 'fiber_disposed' and f == str(grand_fiber)]
    child_fiber_disposed = [i for i, (phase, f, _c) in enumerate(phases)
                            if phase == 'fiber_disposed' and f == str(child_fiber)]
    assert grand_completed and child_completed and grand_fiber_disposed and child_fiber_disposed
    assert grand_completed[0] < child_completed[0], phases
    assert grand_fiber_disposed[0] < child_fiber_disposed[0], phases
    assert len(set(phases)) == len(phases), phases
    # History rows and tombstones are retained, not deleted or re-created.
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                     (grand_fiber,)) == 1
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                         'AND released_at IS NOT NULL', (grand_fiber,)) >= 1
    assert owner_one(db, 'SELECT disposed_at FROM v24_cordis.fibers WHERE id=%s',
                     (uuid.UUID(t['root']['fiber_id']),)) is None
    print('[CDP6-D1] ready listener, open run and two shared external pins each defer the '
          'sealed subtree; after release the grandchild install/fiber completes before the '
          'child install/fiber, with tombstones and history retained')


def test_repeat_dispose_and_replay(db):
    t = tree(db, listeners=0)
    child_install = uuid.UUID(t['child']['install_id'])
    key = 'cordis/dp6/test/dispose/' + str(child_install) + '/replay'
    effect, first, outcome = dispose(db, child_install, key=key)
    assert first.get('disposition') == 'committed' and first['emitted'] == [], first
    events = owner_one(db, 'SELECT count(*) FROM v24_cordis.events')
    requests = owner_one(db, 'SELECT count(*) FROM v24_cordis.requests')

    replay = zero_write(db, lambda: dispose(db, child_install, key=key, effect=effect)[1])
    assert replay.get('disposition') == 'committed', replay
    assert replay == first
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.events') == events
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests') == requests

    # Same key with different bytes is a conflict, not a second dispose step.
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        eff2, out2 = command(db, conn, 'service', 'command_dispose',
                             {'install_id': str(uuid.uuid4())}, key=key)
        result = api(conn, eff2, out2)
        conn.commit()
    assert error_code(result) == 'request_conflict', result
    assert snap(db) == before

    maintainer = scanner(db)
    drive(db, child_install, maintainer)
    assert all(state == 'disposed' for _id, state in subtree_states(db, child_install))
    # Replaying the original command after the tombstone still returns the original receipt.
    again = zero_write(db, lambda: dispose(db, child_install, key=key, effect=effect)[1])
    assert again == first
    tombstone = owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                          (child_install,))
    assert tombstone == 'disposed'
    # A new command is already terminal and never revives or rewrites the tombstone.
    terminal = zero_write(db, lambda: dispose(db, child_install)[1])
    assert error_code(terminal) == 'already_terminal', terminal
    assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                     (child_install,)) == tombstone
    print('[CDP6-D2] one dispose key replays byte-identically with no new event/request, a '
          'conflicting payload is rejected, and post-tombstone commands stay already_terminal')


def test_restart_mid_dispose(db):
    t = tree(db, listeners=0)
    child_install = uuid.UUID(t['child']['install_id'])
    request_dispose(db, child_install)
    maintainer = scanner(db)
    for _ in range(2):
        maintainer.run_once()
    assert not all(state == 'disposed' for _id, state in subtree_states(db, child_install))

    key = 'cordis/dp6/test/dispose/' + str(child_install) + '/kill'
    effect = kill_after_dispose_commit(db, child_install, key, maintainer)
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'succeeded'
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                     (effect,)) == 1
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (child_install,)) in (
        'dispose_pending', 'disposed')

    # Empty-memory restart: a brand-new Maintainer finishes from committed facts only.
    restarted = scanner(db)
    drive(db, child_install, restarted)
    assert all(state == 'disposed' for _id, state in subtree_states(db, child_install))
    phases = event_phases(db, child_install)
    completed = [phase for phase, _f, _c in phases if phase == 'completed']
    assert len(set(phases)) == len(phases), phases
    # No duplicated dispose step for the killed command and one completion per install.
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                     (effect,)) == 1
    assert len(completed) == len(subtree_states(db, child_install)), (completed, phases)
    # The killed command replays; the tombstone is durable.
    replay = zero_write(db, lambda: dispose(db, child_install, key=key, effect=effect)[1])
    assert replay.get('disposition') == 'committed', replay
    print('[CDP6-D3] a dispose COMMIT followed by SIGKILL leaves one receipt; a fresh empty-memory '
          'maintainer converges the subtree without duplicating a step or a tombstone')


# --------------------------------------------- CDP6-D5: graphs and bounds

def test_cycle_and_overflow_bounds(db):
    root = root_install(db)
    root_episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                       (root['fiber_id'],))
    # Owner re-parenting is immutable and a dangling owner is rejected by the FK.
    expect_sqlstate(db, 'owner', 'UPDATE v24_cordis.fibers SET owner_id=%s,owner_episode_id=%s '
                                 'WHERE id=%s',
                    (uuid.uuid4(), root_episode, root['fiber_id']), '55000')
    expect_sqlstate(db, 'owner', 'INSERT INTO v24_cordis.fibers(id,install_id,scope_id,owner_id,'
                                 'owner_episode_id) VALUES(%s,%s,%s,%s,%s)',
                    (uuid.uuid4(), root['install_id'], root['scope']['id'], uuid.uuid4(),
                     root_episode), '23503')

    # A two-node pin cycle, and a mixed owner+pin cycle, are rejected at COMMIT.
    a, ep_a, ca = seed_cycle_fiber(db, root)
    b, ep_b, cb = seed_cycle_fiber(db, root)
    for label, statements in (
            ('pin', [('INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                      'contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,0)',
                      (uuid.uuid4(), a, ep_a, 'cyc', cb)),
                     ('INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                      'contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,0)',
                      (uuid.uuid4(), b, ep_b, 'cyc', ca))]),
            ('mixed', [('UPDATE v24_cordis.fibers SET owner_id=%s,owner_episode_id=%s WHERE id=%s',
                        (a, ep_a, b)),
                       ('INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,'
                        'key,contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,0)',
                        (uuid.uuid4(), a, ep_a, 'cyc', cb))])):
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            if label == 'mixed':
                query(conn, 'ALTER TABLE v24_cordis.fibers DISABLE TRIGGER fibers_immutable')
            for statement, params in statements:
                query(conn, statement, params)
            try:
                conn.commit()
            except psycopg2.Error as exc:
                conn.rollback()
                assert exc.pgcode == '23514', (label, exc.pgcode, str(exc))
                assert 'fiber graph cycle' in str(exc), (label, str(exc))
            else:
                conn.rollback()
                raise AssertionError(label + ' cycle committed')
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins') == 0

    # The committed owner graph is bounded: a deep but legal chain terminates, and
    # the 512-edge boundary is rejected at COMMIT by the existing graph trigger.
    deep = build_chain(db, 64)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, "SET LOCAL statement_timeout='4s'")
        got = query(conn, 'SELECT count(*),max(depth) FROM v24_cordis.dispose_subtree(%s)',
                    (deep,))
        plan = query(conn, 'SELECT v24_cordis.dispose_plan(%s)', (deep,))
        conn.rollback()
    # dispose_subtree emits one row per path; callers use the id set and max(depth).
    base = owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s', (deep,))
    ids = owner_rows(db, 'SELECT id,max(depth) FROM v24_cordis.dispose_subtree(%s) '
                         'GROUP BY id', (deep,))
    assert len(ids) == base, (len(ids), base)
    assert got[0][1] >= 64, got
    assert plan[0][0]['kind'] in ('request', 'unsupported', 'deferred'), plan
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        try:
            insert_chain_tail(db, conn, 512 - 64)
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            assert exc.pgcode in ('23502', '23514'), (exc.pgcode, str(exc))
            assert 'fiber graph' in str(exc), str(exc)
        else:
            conn.rollback()
            raise AssertionError('over-deep chain committed')

    # Withdraw closure: 257 releasable contributions exceed the leave budget, so the
    # P6 slot stays ready with a stable retry_with_closure.  A coalesced dispose refresh
    # keeps the inherited committed no-op contract (DP3-D5); no contribution is released
    # and no tombstone/close happens while the closure cannot make progress.
    over = overflow_fiber(db, root, 257)
    request_dispose(db, over['install'])
    released = owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                             'AND released_at IS NOT NULL', (over['fiber'],))
    maintainer = scanner(db)
    for _ in range(3):
        maintainer.run_once()
    assert plan_of(db, over['install'])['kind'] == 'wait_slot', plan_of(db, over['install'])
    assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                     (over['install'],)) == 'dispose_pending'
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                         'AND released_at IS NOT NULL', (over['fiber'],)) == released
    assert owner_one(db, 'SELECT current_episode_id IS NOT NULL FROM v24_cordis.fibers '
                         'WHERE id=%s', (over['fiber'],)) is True
    print('[CDP6-D4] owner re-parent/dangling owner are rejected; pin and mixed cycles are '
          'rejected at COMMIT; a 64-deep chain terminates and the over-deep/over-budget '
          'closures are stable blocks with no release, close or tombstone')


def seed_cycle_fiber(db, root):
    fiber, install, scope, episode, contribution = (uuid.uuid4() for _ in range(5))
    owner_episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (root['fiber_id'],))
    owner_do(db, 'INSERT INTO v24_cordis.fibers(id,install_id,scope_id,owner_id,owner_episode_id) '
                 'VALUES(%s,%s,%s,%s,%s)',
             (fiber, root['install_id'], root['scope']['id'], root['fiber_id'], owner_episode))
    owner_do(db, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) "
                 "VALUES(%s,%s,0,'active','{}',%s)",
             (episode, fiber, Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0))))
    owner_do(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
                 "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'service','root',%s,"
                 "'{}','{\"op\":\"delete_row\"}','1')",
             (contribution, fiber, episode, 'cycle-' + fiber.hex[:8]))
    return fiber, episode, contribution


def build_chain(db, count):
    """A legal owner chain under the unique root; returns the root install id."""
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, '''
DO $body$
DECLARE parent uuid; child uuid; ep uuid; i int; v_install uuid; v_scope uuid; v_owner_ep uuid;
BEGIN
  SELECT id,install_id,scope_id,current_episode_id INTO parent,v_install,v_scope,v_owner_ep
    FROM v24_cordis.fibers WHERE owner_id IS NULL LIMIT 1;
  FOR i IN 1..%s LOOP
    child:=gen_random_uuid(); ep:=gen_random_uuid();
    INSERT INTO v24_cordis.fibers(id,install_id,scope_id,owner_id,owner_episode_id)
      VALUES(child,v_install,v_scope,parent,v_owner_ep);
    INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator)
      VALUES(ep,child,0,'active','{}',%s);
    parent:=child; v_owner_ep:=ep;
  END LOOP;
END $body$''' % (count, Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0))))
        conn.commit()
    return one(db, 'SELECT install_id FROM v24_cordis.fibers WHERE owner_id IS NULL')


def insert_chain_tail(db, conn, count):
    """Extend the current deepest chain to ``count`` more edges inside one transaction."""
    query(conn, '''
DO $body$
DECLARE parent uuid; child uuid; ep uuid; i int; v_install uuid; v_scope uuid; v_owner_ep uuid;
BEGIN
  SELECT f.id,f.install_id,f.scope_id,coalesce(f.current_episode_id,e.id) INTO
    parent,v_install,v_scope,v_owner_ep
    FROM v24_cordis.fibers f LEFT JOIN LATERAL (
      SELECT id FROM v24_cordis.episodes WHERE fiber_id=f.id ORDER BY epoch DESC LIMIT 1) e
      ON true
    WHERE f.owner_id IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM v24_cordis.fibers c WHERE c.owner_id=f.id)
    ORDER BY (SELECT count(*) FROM v24_cordis.fiber_chain(f.id)) DESC
    LIMIT 1;
  FOR i IN 1..%s LOOP
    child:=gen_random_uuid(); ep:=gen_random_uuid();
    INSERT INTO v24_cordis.fibers(id,install_id,scope_id,owner_id,owner_episode_id)
      VALUES(child,v_install,v_scope,parent,v_owner_ep);
    INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator)
      VALUES(ep,child,0,'active','{}',%s);
    parent:=child; v_owner_ep:=ep;
  END LOOP;
END $body$''' % (count, Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0))))


def overflow_fiber(db, root, count):
    """A child install whose fiber has ``count`` unreleased withdrawable contributions."""
    payload, _, _ = dispatch_create(db, uuid.UUID(root['scope']['id']),
                                   owner_of(db, root['fiber_id']), provides=[])
    fiber = uuid.UUID(payload['fiber_id'])
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,"
                    "descriptor,inverse,contract_version) SELECT gen_random_uuid(),%s,%s,g,'cell',"
                    "'{}'::jsonb,'{\"op\":\"delete_row\"}'::jsonb,'1' "
                    'FROM generate_series(0,%s) g', (fiber, episode, count - 1))
        conn.commit()
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed' and result['emitted'], result
    slot = uuid.UUID(result['emitted'][0])
    with contextlib.closing(db.connect('owner')) as conn:
        slot_payload = query(conn, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (slot,))[0][0]
        conn.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', slot_payload,
                             key='cordis/reconcile/%s/0' % off, effect=slot)
        try:
            blocked = api(conn, slot, outcome)
        finally:
            conn.rollback()
    assert error_code(blocked) == 'retry_with_closure', blocked
    return dict(payload=payload, fiber=fiber, install=uuid.UUID(payload['install_id']))


# --------------------------------------- CDP6-U5: debt is not writable by actors

def test_debt_permissions(db):
    t = tree(db, listeners=0)
    child_install = uuid.UUID(t['child']['install_id'])
    grand_fiber = t['grand']['fiber']
    unknown = add_unknown_effect(db, grand_fiber)
    contribution, _debt = add_inverse_unknown(db, grand_fiber)
    request_dispose(db, child_install)
    before = snap(db)
    for alias in ('service', 'operator', 'admin'):
        for statement, params in (
                ("UPDATE v24_cordis.effects SET status='succeeded' WHERE id=%s", (unknown,)),
                ("UPDATE v24_cordis.contributions SET released_at=now() WHERE id=%s",
                 (contribution,)),
                ('DELETE FROM v24_cordis.contributions WHERE id=%s', (contribution,)),
                ('INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                 'contribution_id,provider_epoch) VALUES(%s,NULL,NULL,NULL,%s,0)',
                 (uuid.uuid4(), contribution))):
            expect_sqlstate(db, alias, statement, params, '42501')
    expect_sqlstate(db, 'observer', 'SELECT manifest FROM v24_cordis.installs LIMIT 1', (), '42501')
    expect_sqlstate(db, 'observer', 'SELECT v24_cordis.advance(%s,%s)',
                    (unknown, Json({'v': 1})), '42501')
    expect_sqlstate(db, 'observer', "INSERT INTO v24_cordis.effects(id,kind,status,input,"
                                    "request_actor) VALUES(%s,'host_io','ready','{}','x')",
                    (uuid.uuid4(),), '42501')
    assert snap(db) == before
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (unknown,)) == 'unknown'
    assert owner_one(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions '
                         'WHERE id=%s', (contribution,)) is True

    # No protocol path resolves the debt by supplying a different receipt.
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, unknown,
                 {'v': 1, 'class': 'success',
                  'claim': {'attempt': 1, 'fence': 1, 'owner': db.roles['service']},
                  'body': {'kind': 'model_call', 'result': {'text': 'forged'}}},
                 code='receipt_conflict')
    assert snap(db) == before
    print('[CDP6-U5] no service/operator/admin/observer LOGIN can rewrite, release or insert around '
          'a debt; only the owner fixture may create it and advance refuses a forged receipt')


def test_compensation_without_abi_stays_blocked(db):
    """CDP6-U/D #7: manual reconciliation cannot be represented without a design change."""
    t = tree(db)
    child_install = uuid.UUID(t['child']['install_id'])
    grand_fiber = t['grand']['fiber']
    contribution, debt = add_inverse_unknown(db, grand_fiber)
    request_dispose(db, child_install)
    marker = Path('/tmp') / ('dp6-compensated-' + uuid.uuid4().hex)
    marker.write_text(json.dumps({'contribution_id': str(contribution), 'debt': debt}))
    try:
        # The external operator says the resource was compensated; the database still
        # has no approved ABI to express that fact, so the debt must stay blocked.
        assert plan_of(db, child_install) == {'kind': 'blocked_unknown', 'reason': 'inverse'}
        result = zero_write(db, lambda: dispose(db, child_install)[1])
        assert error_code(result) == 'blocked_unknown'
        assert owner_one(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions '
                             'WHERE id=%s', (contribution,)) is True
        states = dict(subtree_states(db, child_install))
        assert states[child_install] == 'dispose_pending'
        assert all(state != 'disposed' for state in states.values()), states
    finally:
        marker.unlink()
    print('[CDP6-U6] an out-of-band compensation claim cannot clear the debt: no approved ABI '
          'exists, so W3 records a design block instead of inventing a state transition')


# ------------------------------------------------------------- child process

def _child_dispose():
    cfg = json.loads(os.environ[DISPOSE_CHILD_ENV])
    conn = psycopg2.connect(cfg['dsn'])
    try:
        result = query(conn, 'SELECT v24_cordis.advance(%s,%s)',
                       (uuid.UUID(cfg['effect']), Json(cfg['outcome'])))[0][0]
        conn.commit()
        print('DP6DISPOSE ' + json.dumps({'result': result}), flush=True)
    finally:
        os.kill(os.getpid(), signal.SIGKILL)


WRITING_PLAN = ('request', 'fiber_request', 'fiber_control', 'schedule', 'fiber_finish',
                'child_install_finish', 'install_finish')


def kill_after_dispose_commit(db, install, key, maintainer):
    """Kill one real dispose COMMIT: the step must select an object that can write."""
    for _ in range(24):
        if plan_of(db, install).get('kind') in WRITING_PLAN:
            break
        maintainer.run_once()
    else:
        raise AssertionError(('no writing dispose plan', plan_of(db, install)))
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_dispose',
                                  {'install_id': str(install)}, key=key)
        conn.rollback()
    cfg = {'dsn': make_dsn(**dict(db.server.params, dbname=db.name,
                                  user=db.roles['service'])),
           'effect': str(effect), 'outcome': outcome}
    env = dict(os.environ)
    env[DISPOSE_CHILD_ENV] = json.dumps(cfg)
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                             '--child-dispose'], env=env, cwd=str(CORDIS.parent),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == EXIT_KILLED, (proc.returncode, out, err)
    return effect


# -------------------------------------------------------------------- main

def main():
    if '--child-dispose' in sys.argv[1:]:
        _child_dispose()
        return
    tests = (test_unknown_effect_debt, test_inverse_unknown_debt,
             test_safe_replay_under_debt, test_no_time_based_unknown_upgrade,
             test_dispose_tree_obligations, test_repeat_dispose_and_replay,
             test_restart_mid_dispose, test_cycle_and_overflow_bounds,
             test_debt_permissions, test_compensation_without_abi_stays_blocked)
    with Server() as server:
        for test in tests:
            with TestDB(server) as db:
                test(db)
    print('[passed] CDP6-U/D')


if __name__ == '__main__':
    main()
