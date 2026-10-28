"""CDP6-H: drain-based upgrade, explicit rollback and the pre-deployed HMR trigger.

Run with: uv run python v24/cordis/dp6/test_upgrade.py

Every declaration, control command and dispose request goes through the existing
``advance`` protocol.  The only owner-only writes are explicitly named fixtures:
an open run whose settlement/wake is DP4's job, an unknown terminal effect the
production loop cannot create, a rotated owner episode used as a fault object,
and the unique-address negative insert.  The switch driver itself only reads the
observer surface and submits the same ``command_install``/``command_reconcile``
requests; drain progress is produced by the W1 ``Maintainer``.

The gate is deliberately independent of DP1-DP5 and W1-W3: it reuses their
production fixtures, never re-implements a lifecycle step, and proves:

  H1  new declaration identity, unchanged digest, in-place install overwrite rejected
  H2  old run / activation pin / created listener child block address release
  H3  single live provider per slot, observable empty window, late activation
  H3b activation attempted before release fails without two live versions
  H4  real child-process SIGKILL after start/off/release/on commit plus rollback start
  H5  same operation different payload/actor, same-slot concurrency, stale seq,
      independently enabled target, changed owner episode, digest/duplicate faults
  H6  rollback reuse declaration, new fiber/episode, old declaration unchanged and
      whole-install dispose covering every historical instance
  H7  terminal unknown stops upgrade/rollback without clearing debt
  H8  upgraded service + event listener resolve to the new generation only
  H9  HMR tick submits the identical stable request; no download/ESM path exists
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
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
from test_support import (query, api, command, snapshot, reconcile_payload,  # noqa: E402
                          install_payload)
from test_activation import (install, phases, commit_new, one, rows,  # noqa: E402
                             commit_child)
from test_teardown import (root_install, activate, owner_of, enter_closing,  # noqa: E402
                           drain, p6_slot)
from test_dispatch import (HOST, listener, create as dispatch_create,  # noqa: E402
                           settle_success)
import driver as drv  # noqa: E402

EXIT_KILLED = -signal.SIGKILL
CHILD_ENV = 'DP6_UPGRADE_CHILD'
LIVE_SQL = ("SELECT count(*) FROM v24_cordis.contributions WHERE kind='service' "
            "AND realm='root' AND key=%s AND released_at IS NULL")


# --------------------------------------------------------------------- helpers

def owner_rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        got = query(conn, statement, params)
        conn.rollback()
        return got


def owner_one(db, statement, params=()):
    return owner_rows(db, statement, params)[0][0]


def owner_do(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, statement, params)
        conn.commit()


def snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        value = snapshot(conn)
        conn.rollback()
        return value


def zero_write(db, call):
    before = snap(db)
    result = call()
    assert snap(db) == before, ('unexpected write', result)
    return result


def error_code(result):
    return (result or {}).get('error', {}).get('code')


def error_reason(result):
    return ((result or {}).get('error', {}).get('detail') or {}).get('reason')


def run_command(db, alias, kind, payload, key):
    with contextlib.closing(db.connect(alias)) as conn:
        effect, outcome = command(db, conn, alias, kind, payload, key=key)
        result = api(conn, effect, outcome)
        conn.commit()
    return effect, result, outcome


def rolled_back(db, alias, kind, payload, key):
    with contextlib.closing(db.connect(alias)) as conn:
        effect, outcome = command(db, conn, alias, kind, payload, key=key)
        result = api(conn, effect, outcome)
        conn.rollback()
    return result


def factories(db):
    def observer():
        return db.server.connect(db.name, db.roles['observer'])

    def actor(login):
        return db.server.connect(db.name, login)

    return observer, actor


def switch_driver(db):
    observer, actor = factories(db)
    maintainer = drv.Maintainer(observer_connect=observer, actor_connect=actor,
                                ensure_actor=db.roles['service'])
    return drv.SwitchDriver(observer_connect=observer, actor_connect=actor,
                            maintainer=maintainer), maintainer


def install_row(db, install_id):
    row = owner_rows(db, 'SELECT scope_id,owner_fiber_id,owner_episode_id,identity,version,'
                         'manifest,artifact_digest,contracts,policy_ref,overlay,state '
                         'FROM v24_cordis.installs WHERE id=%s', (install_id,))
    return row[0] if row else None


def declaration_for(db, old_install, new_install, new_fiber, version, digest):
    scope, owner_fiber, owner_episode, identity, _ver, manifest, _digest, contracts, \
        policy, overlay, _state = install_row(db, old_install)
    payload = install_payload(mode='existing',
                              owner={'fiber_id': str(owner_fiber),
                                     'episode_id': str(owner_episode)},
                              existing_scope=str(scope))
    payload.update(install_id=str(new_install), fiber_id=str(new_fiber),
                   identity=identity, version=version, manifest=manifest,
                   artifact_digest=digest, contracts=contracts,
                   policy_ref=policy, overlay=overlay)
    return payload


def upgrade_plan(db, driver, old, new_install=None, new_fiber=None, version='2',
                 digest='b' * 64, operation=None):
    new_install = new_install or uuid.uuid4()
    new_fiber = new_fiber or uuid.uuid4()
    old_fiber = uuid.UUID(old['fiber_id'])
    old_install = uuid.UUID(old['install_id'])
    plan = driver.plan_upgrade(
        operation=operation or uuid.uuid4(), actor=db.roles['service'],
        source_fiber=old_fiber, install_id=new_install, target_fiber=new_fiber,
        declaration=declaration_for(db, old_install, new_install, new_fiber,
                                    version, digest))
    return plan, new_install, new_fiber


def live_count(db, key='svc'):
    return owner_one(db, LIVE_SQL, (key,))


def resolved(db, scope, key='svc'):
    return owner_rows(db, 'SELECT provider_fiber_id,provider_episode_id,available '
                          'FROM v24_cordis.resolve(%s,%s)', (scope, [key]))[0]


def source_drained(db, fiber):
    return owner_one(db, 'SELECT NOT want_on AND current_episode_id IS NULL '
                         'AND retire_started_at IS NULL FROM v24_cordis.fibers WHERE id=%s',
                     (fiber,))


def step_until(driver, plan, phase, limit=60):
    seen = []
    for _ in range(limit):
        state = driver.status(plan)
        seen.append(state['phase'])
        if state['phase'] == phase:
            return state
        outcome = driver.step(plan)
        if outcome['action'] == 'none':
            return outcome['state']
    raise AssertionError(('phase not reached', phase, seen))


def drive(driver, plan, limit=80):
    outcome = driver.drive(plan, limit=limit)
    assert outcome['phase'] in ('complete', 'failed'), outcome
    return outcome


def request_keys(db):
    return [row[0] for row in owner_rows(
        db, 'SELECT request_key FROM v24_cordis.requests WHERE request_key LIKE %s '
            'ORDER BY request_key', (drv.SWITCH_KEY_PREFIX + '/%',))]


def count_switch(db, suffix):
    pattern = '%/start' if suffix == 'start' else '%/' + suffix + '/%'
    return owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE request_key '
                         'LIKE %s AND request_key LIKE %s',
                     (drv.SWITCH_KEY_PREFIX + '/%', pattern))


def open_run(db, fiber):
    scope = owner_one(db, 'SELECT scope_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    run = uuid.uuid4()
    owner_do(db, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,'
                 'remaining_steps) VALUES(%s,%s,%s,%s,1)', (run, fiber, episode, scope))
    return run


def end_run(db, run):
    owner_do(db, 'UPDATE v24_cordis.runs SET ended_at=clock_timestamp() WHERE id=%s', (run,))


def host_calls(db, fiber, status=None):
    statement = ("SELECT id,ordinal,status,input->>'listener_id' FROM v24_cordis.effects "
                 "WHERE kind='listener_call' AND fiber_id=%s")
    params = [fiber]
    if status is not None:
        statement += ' AND status=%s'
        params.append(status)
    return owner_rows(db, statement + ' ORDER BY ordinal,id', tuple(params))


def settle_host_calls(db, fiber):
    """Settle ready host listener children through claim/settle (DP5 production helpers)."""
    from dp4_support import claim, settle
    calls = host_calls(db, fiber, 'ready')
    for effect, _ordinal, _status, _listener in calls:
        token = claim(db, uuid.UUID(str(effect)))
        assert token.get('disposition') == 'claimed', token
        result = settle(db, uuid.UUID(str(effect)),
                        {'kind': 'listener_call', 'result': {'value': {'ok': True}}},
                        token['claim'])
        assert result.get('disposition') == 'committed', result
    return len(calls)


# ------------------------------------------------------------- child process

def _child():
    cfg = json.loads(os.environ[CHILD_ENV])
    base = dict(cfg['dsn'])

    def connect(login):
        return psycopg2.connect(make_dsn(**dict(base, dbname=cfg['dbname'], user=login)))

    observer = lambda: connect(cfg['observer'])  # noqa: E731

    def actor(login):
        return connect(login)

    maintainer = drv.Maintainer(observer_connect=observer, actor_connect=actor,
                                ensure_actor=cfg['actor'])
    driver = drv.SwitchDriver(observer_connect=observer, actor_connect=actor,
                              maintainer=maintainer)
    plan = drv.SwitchPlan.from_dict(cfg['plan']) if cfg.get('plan') else None
    action = cfg['action']
    if action == 'start':
        driver.start(plan)
    elif action == 'off':
        driver._submit(plan, 'off')
    elif action == 'on':
        for _ in range(60):
            if driver.status(plan)['phase'] == 'on_pending':
                driver._submit(plan, 'on')
                break
            maintainer.run_once()
        else:
            raise AssertionError('on_pending not reached')
    elif action == 'release':
        for _ in range(60):
            left = owner_count(observer, plan.source_fiber)
            if left == 0:
                break
            maintainer.run_once()
        else:
            raise AssertionError('address was not released')
    elif action == 'drain':
        maintainer.run_once()
    elif action == 'start_rollback':
        driver.start(plan)
    else:
        raise AssertionError('unknown child action ' + action)
    os.kill(os.getpid(), signal.SIGKILL)


def owner_count(observer, fiber):
    conn = observer()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s "
                        "AND kind='service' AND released_at IS NULL", (fiber,))
            value = cur.fetchone()[0]
        conn.rollback()
        return value
    finally:
        conn.close()


def run_child(db, action, plan=None):
    cfg = {'dsn': {k: v for k, v in db.server.params.items() if k != 'dbname'},
           'dbname': db.name, 'observer': db.roles['observer'],
           'actor': db.roles['service'], 'action': action,
           'plan': plan.as_dict() if plan is not None else None}
    env = dict(os.environ)
    env[CHILD_ENV] = json.dumps(cfg)
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child'],
                            env=env, cwd=str(CORDIS.parent), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    out, err = proc.communicate(timeout=180)
    assert proc.returncode == EXIT_KILLED, (proc.returncode, out[-2000:], err[-2000:])
    return out, err


# ---------------------------------------------------------------------- H1

def test_h1_declaration_identity(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    old_install = uuid.UUID(old['install_id'])
    old_fiber = uuid.UUID(old['fiber_id'])
    driver, _maintainer = switch_driver(db)
    before = install_row(db, old_install)

    # A new declaration must be a new install row; in-place overwrite is refused by
    # the driver, by the command admission and by the immutable-install trigger.
    other_fiber = uuid.uuid4()
    takeover = declaration_for(db, old_install, old_install, other_fiber, '2', 'a' * 64)
    try:
        driver.plan_upgrade(operation=uuid.uuid4(), actor=db.roles['service'],
                            source_fiber=old_fiber, install_id=old_install,
                            target_fiber=other_fiber, declaration=takeover)
    except drv.SwitchStateError as exc:
        assert exc.reason == 'switch_target_install_exists', exc
    else:
        raise AssertionError('in-place install id admitted')

    result = zero_write(db, lambda: rolled_back(
        db, 'service', 'command_install',
        declaration_for(db, old_install, old_install, uuid.uuid4(), '2', 'a' * 64),
        'w4/h1/inplace/' + uuid.uuid4().hex))
    assert error_code(result) == 'invalid_args' and error_reason(result) == 'install_id', result

    with contextlib.closing(db.connect('owner')) as conn:
        try:
            query(conn, "UPDATE v24_cordis.installs SET version='9' WHERE id=%s", (old_install,))
        except psycopg2.Error as exc:
            assert exc.pgcode == '55000', exc.pgcode
            conn.rollback()
        else:
            conn.rollback()
            raise AssertionError('install declaration was overwritten')

    duplicate = declaration_for(db, old_install, uuid.uuid4(), uuid.uuid4(), '1', 'a' * 64)
    result = zero_write(db, lambda: rolled_back(
        db, 'service', 'command_install', duplicate, 'w4/h1/dup/' + uuid.uuid4().hex))
    assert error_code(result) == 'install_identity_conflict', result

    # A new version may keep the artifact digest; the declaration is still distinct.
    new_install, new_fiber = uuid.uuid4(), uuid.uuid4()
    plan = driver.plan_upgrade(
        operation=uuid.uuid4(), actor=db.roles['service'], source_fiber=old_fiber,
        install_id=new_install, target_fiber=new_fiber,
        declaration=declaration_for(db, old_install, new_install, new_fiber, '2', 'a' * 64),
        expected_digest='a' * 64)
    outcome = driver.start(plan)
    assert outcome['action'] == 'start' and outcome['phase'] == 'off_pending', outcome
    replay = driver.start(plan)
    assert replay['action'] == 'start_replay', replay
    assert count_switch(db, 'start') == 1
    assert install_row(db, old_install) == before
    new_row = install_row(db, new_install)
    assert new_row[4] == '2' and new_row[6] == 'a' * 64 and new_row[10] == 'installed', new_row
    assert owner_rows(db, 'SELECT want_on,control_seq,install_id,owner_id '
                         'FROM v24_cordis.fibers WHERE id=%s', (new_fiber,)) == [
        (False, 0, new_install, before[1])]
    assert owner_rows(db, 'SELECT event_kind FROM v24_cordis.events WHERE entity_id=%s',
                      (new_install,)) == [('install_created',)]
    key = owner_one(db, 'SELECT request_key FROM v24_cordis.requests WHERE effect_id='
                        '(SELECT id FROM v24_cordis.effects WHERE kind=%s AND status=%s '
                        'AND input->>%s=%s LIMIT 1)',
                    ('command_install', 'succeeded', 'install_id', str(new_install)))
    assert key == plan.start_key(), (key, plan.start_key())
    actor = owner_one(db, "SELECT request_actor FROM v24_cordis.effects WHERE kind='command_install' "
                          "AND input->>'install_id'=%s", (str(new_install),))
    assert actor == db.roles['service'], actor
    print('[CDP6-H1] a new version is a new immutable declaration; in-place overwrite, '
          'duplicate (scope,identity,version) and same-digest new version are separated')


# ---------------------------------------------------------------------- H2

def test_h2_old_obligations_block_release(db):
    root = root_install(db)
    scope = uuid.UUID(root['scope']['id'])
    host = listener('w4-host', 'emit', 10, {'type': 'host', 'capability': 'listener_call'})
    provider, fiber, result = dispatch_create(
        db, scope, owner_of(db, root['fiber_id']), provides=['svc'], listeners=[host],
        contracts={'listener_call': HOST})
    assert result.get('disposition') == 'committed', result
    consumer_payload, consumer, consumer_result = dispatch_create(
        db, scope, owner_of(db, root['fiber_id']), requires=['svc'])
    assert consumer_result.get('disposition') == 'committed', consumer_result
    assert host_calls(db, fiber, 'ready'), 'provider activation did not create host children'
    run = open_run(db, fiber)

    driver, maintainer = switch_driver(db)
    plan, _ni, new_fiber = upgrade_plan(db, driver, provider)
    driver.start(plan)
    driver._submit(plan, 'off')
    state = driver.status(plan)
    assert state['phase'] == 'draining', state
    assert {'pin', 'run', 'effect'} <= set(state['drain']['reasons']), state['drain']
    assert live_count(db) == 1, 'off withdraws visibility but must not release the address'
    assert resolved(db, scope)[2] is False
    assert owner_rows(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions '
                          'WHERE fiber_id=%s AND kind=%s', (fiber, 'service')) == [(True,)]
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE released_at IS NULL') == 1

    settle_host_calls(db, fiber)
    assert not host_calls(db, fiber, 'ready')
    maintainer.run_once()
    state = driver.status(plan)
    assert 'effect' not in state['drain']['reasons'], state['drain']
    assert {'pin', 'run'} <= set(state['drain']['reasons']), state['drain']

    end_run(db, run)
    maintainer.run_once()
    state = driver.status(plan)
    assert 'run' not in state['drain']['reasons'], state['drain']
    assert 'pin' in state['drain']['reasons'], state['drain']
    assert live_count(db) == 1, 'the consumer pin must keep the old address live'

    # The scanner converges the now-unlive consumer; its P6 is the only thing that
    # releases the pin, and the upgrade may not activate before that release.
    for _ in range(30):
        if owner_one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE released_at IS NULL') == 0:
            break
        assert count_switch(db, 'on') == 0
        assert live_count(db) == 1, 'the old address must survive until the pin is released'
        maintainer.run_once()
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE released_at IS NULL') == 0
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE released_at IS NOT NULL') >= 1

    outcome = drive(driver, plan)
    assert outcome['phase'] == 'complete', outcome
    assert live_count(db) == 1
    provider_fiber, provider_episode, available = resolved(db, scope)
    assert available is True and provider_fiber == new_fiber
    assert provider_episode == owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers '
                                              'WHERE id=%s', (new_fiber,))
    old = owner_rows(db, 'SELECT released_at IS NOT NULL,withdrawn_at IS NOT NULL '
                         'FROM v24_cordis.contributions WHERE fiber_id=%s', (fiber,))
    assert old and all(row[0] and row[1] for row in old), old
    assert consumer_payload['fiber_id'] == str(consumer)
    print('[CDP6-H2] old run, activation pin and created host listener child each block '
          'address release; released pin/history stays readable and resolve moves to the '
          'new generation')


# ---------------------------------------------------------------------- H3

def test_h3_window_and_unique_address(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    fiber = uuid.UUID(old['fiber_id'])
    scope = uuid.UUID(root['scope']['id'])
    driver, _maintainer = switch_driver(db)
    plan, _ni, new_fiber = upgrade_plan(db, driver, old)
    driver.start(plan)
    # While the old address is live, a second live provider on the same slot is
    # refused by the existing partial unique index.
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    seq = owner_one(db, 'SELECT coalesce(max(seq),-1)+1 FROM v24_cordis.contributions '
                        'WHERE fiber_id=%s AND episode_id=%s', (fiber, episode))
    with contextlib.closing(db.connect('owner')) as conn:
        try:
            query(conn, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,"
                        "realm,key,descriptor,inverse,contract_version) VALUES "
                        "(%s,%s,%s,%s,'service','root','svc','{}',"
                        "'{\"op\":\"delete_row\"}','1')",
                  (uuid.uuid4(), fiber, episode, seq))
        except psycopg2.Error as exc:
            assert exc.pgcode == '23505', (exc.pgcode, str(exc))
            conn.rollback()
        else:
            conn.rollback()
            raise AssertionError('two live providers on one address')
    driver._submit(plan, 'off')
    samples = []
    for _ in range(40):
        state = driver.status(plan)
        samples.append((state['phase'], live_count(db)))
        assert live_count(db) <= 1, samples
        if state['phase'] == 'on_pending':
            break
        outcome = driver.step(plan)
        if outcome['action'] == 'none':
            break
    else:
        raise AssertionError(('drain did not converge', samples))
    assert driver.status(plan)['phase'] == 'on_pending', driver.status(plan)
    # The empty window is observable: no live provider, no live contribution row,
    # and the released old row is still readable.
    assert live_count(db) == 0
    assert resolved(db, scope)[2] is False
    assert owner_rows(db, 'SELECT released_at IS NOT NULL FROM v24_cordis.contributions '
                          'WHERE fiber_id=%s', (fiber,)) == [(True,)]
    assert owner_rows(db, 'SELECT want_on,control_seq,current_episode_id IS NULL '
                          'FROM v24_cordis.fibers WHERE id=%s', (new_fiber,)) == [(False, 0, True)]
    outcome = drive(driver, plan)
    assert outcome['phase'] == 'complete', outcome
    assert live_count(db) == 1
    assert resolved(db, scope)[0] == new_fiber
    print('[CDP6-H3] one live provider per slot throughout; the empty window is observable '
          'and the new provider activates only after the old release')


# --------------------------------------------------------------------- H3b

def test_h3b_early_activation_is_rejected(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    fiber = uuid.UUID(old['fiber_id'])
    run = open_run(db, fiber)
    driver, maintainer = switch_driver(db)
    plan, _ni, new_fiber = upgrade_plan(db, driver, old)
    driver.start(plan)
    driver._submit(plan, 'off')
    maintainer.run_once()
    assert live_count(db) == 1, 'the old provider must still hold the address'
    early = driver._submit(plan, 'on')
    assert early['action'] == 'on', early
    failure = None
    for _ in range(12):
        target = owner_rows(db, 'SELECT control_seq,failure FROM v24_cordis.fibers WHERE id=%s',
                            (new_fiber,))[0]
        if isinstance(target[1], dict) and target[1].get('control_seq') == target[0]:
            failure = target[1]
            break
        maintainer.run_once()
    assert failure is not None and failure.get('code') == 'provide_conflict', failure
    assert live_count(db) == 1
    assert resolved(db, uuid.UUID(root['scope']['id']))[2] is False
    assert owner_rows(db, 'SELECT released_at IS NULL FROM v24_cordis.contributions '
                          'WHERE fiber_id=%s', (fiber,)) == [(True,)]
    assert owner_rows(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                          'AND released_at IS NULL', (new_fiber,)) == [(0,)]
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE kind=%s '
                         'AND released_at IS NULL', ('service',)) == 1
    end_run(db, run)
    for _ in range(30):
        if driver.status(plan)['phase'] != 'draining':
            break
        maintainer.run_once()
    assert live_count(db) == 0, 'the old provider was not drained after the run ended'
    state = driver.status(plan)
    assert state['phase'] == 'failed', state
    target = owner_rows(db, 'SELECT want_on,current_episode_id IS NULL FROM v24_cordis.fibers '
                            'WHERE id=%s', (new_fiber,))
    assert target == [(True, True)], target
    # The failed operation is terminal-stable; a new explicit rollback may proceed.
    a2 = uuid.uuid4()
    rollback = driver.plan_rollback(operation=uuid.uuid4(), actor=db.roles['service'],
                                    source_fiber=new_fiber, target_install=uuid.UUID(old['install_id']),
                                    target_fiber=a2, expected_digest=old['artifact_digest'],
                                    provides=('svc',))
    outcome = drive(driver, rollback)
    assert outcome['phase'] == 'complete', outcome
    assert resolved(db, uuid.UUID(root['scope']['id']))[0] == a2
    print('[CDP6-H3b] activating before the old release fails with provide_conflict, never '
          'creates two live versions, and a fresh rollback activates the old declaration again')


# --------------------------------------------------------------------- H3c

def test_h3c_dependency_unresolved(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    scope = uuid.UUID(root['scope']['id'])
    old_fiber = uuid.UUID(old['fiber_id'])
    driver, maintainer = switch_driver(db)
    new_install, new_fiber = uuid.uuid4(), uuid.uuid4()
    declaration = declaration_for(db, uuid.UUID(old['install_id']), new_install,
                                  new_fiber, '2', 'b' * 64)
    declaration['manifest'] = dict(declaration['manifest'], requires=['missing-svc'])
    plan = driver.plan_upgrade(operation=uuid.uuid4(), actor=db.roles['service'],
                               source_fiber=old_fiber, install_id=new_install,
                               target_fiber=new_fiber, declaration=declaration)
    driver.start(plan)
    driver._submit(plan, 'off')
    for _ in range(60):
        if driver.status(plan)['phase'] == 'on_pending':
            break
        driver.step(plan)
    else:
        raise AssertionError(('drain did not reach on_pending', driver.status(plan)))
    assert driver._submit(plan, 'on')['action'] == 'on'
    dependency = False
    for _ in range(8):
        outcome = driver.step(plan)
        report = outcome.get('report')
        if report is not None:
            dependency = dependency or any(
                row.get('disposition') == 'dependency_unresolved'
                for row in report.actions + report.diagnostics if isinstance(row, dict))
    state = driver.status(plan)
    assert state['phase'] == 'activating', state
    assert dependency, 'the scanner never surfaced dependency_unresolved'
    assert live_count(db) == 0
    assert owner_rows(db, 'SELECT current_episode_id IS NULL,want_on,failure FROM '
                          'v24_cordis.fibers WHERE id=%s', (new_fiber,)) == [(True, True, None)]
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                     (new_fiber,)) == 0
    a2 = uuid.uuid4()
    rollback = driver.plan_rollback(operation=uuid.uuid4(), actor=db.roles['service'],
                                    source_fiber=new_fiber,
                                    target_install=uuid.UUID(old['install_id']),
                                    target_fiber=a2, expected_digest=old['artifact_digest'],
                                    provides=('svc',))
    outcome = drive(driver, rollback)
    assert outcome['phase'] == 'complete', outcome
    assert live_count(db) == 1
    assert resolved(db, scope)[0] == a2
    assert owner_rows(db, 'SELECT want_on,current_episode_id IS NULL FROM v24_cordis.fibers '
                          'WHERE id=%s', (new_fiber,)) == [(False, True)]
    print('[CDP6-H3c] an unmet dependency keeps the switch activating with no episode and no '
          'failure write; the address stays empty and an explicit rollback restores the old '
          'declaration on a new fiber')


# ---------------------------------------------------------------------- H4

def crash_setup(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    driver, maintainer = switch_driver(db)
    plan, new_install, new_fiber = upgrade_plan(db, driver, old)
    return root, old, driver, maintainer, plan, new_install, new_fiber


def resume_fresh(db, plan):
    driver, maintainer = switch_driver(db)
    resumed = driver.resume(plan.kind, plan.operation, plan.actor)
    assert resumed is not None and resumed.start_key() == plan.start_key()
    return driver, maintainer, resumed


def assert_one_switch(db, plan):
    assert count_switch(db, 'start') == 1
    assert count_switch(db, 'off') == 1
    assert count_switch(db, 'on') == 1
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE request_key=%s',
                     (plan.start_key(),)) == 1
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s',
                     (plan.target_install,)) == 1


def test_h4a_start_commit_and_retry(db):
    root, old, driver, _maintainer, plan, new_install, new_fiber = crash_setup(db)
    before = snap(db)
    result = rolled_back(db, 'service', 'command_install', plan.payload, plan.start_key())
    assert result.get('disposition') == 'committed', result
    assert snap(db) == before, 'a rolled-back start must leave no request/install/fiber'
    assert count_switch(db, 'start') == 0
    assert install_row(db, new_install) is None
    run_child(db, 'start', plan)
    assert count_switch(db, 'start') == 1
    assert install_row(db, new_install) is not None
    assert owner_one(db, 'SELECT want_on OR control_seq<>0 FROM v24_cordis.fibers WHERE id=%s',
                     (new_fiber,)) is False
    driver, _m, resumed = resume_fresh(db, plan)
    outcome = drive(driver, resumed)
    assert outcome['phase'] == 'complete', outcome
    assert_one_switch(db, resumed)
    assert source_drained(db, uuid.UUID(old['fiber_id']))
    # A repeated identical request after completion replays, adding no row.
    assert driver.start(resumed)['action'] == 'start_replay'
    assert driver._submit(resumed, 'off')['action'] == 'off_replay'
    assert driver._submit(resumed, 'on')['action'] == 'on_replay'
    assert_one_switch(db, resumed)
    print('[CDP6-H4a] pre-COMMIT rollback leaves no intent; a real SIGKILL after the start '
          'commit resumes from the committed request and completes with one request per phase')


def test_h4b_off_commit_kill(db):
    root, old, driver, _maintainer, plan, _ni, _nf = crash_setup(db)
    driver.start(plan)
    run_child(db, 'off', plan)
    assert count_switch(db, 'off') == 1
    source = owner_rows(db, 'SELECT want_on,control_seq FROM v24_cordis.fibers WHERE id=%s',
                        (uuid.UUID(old['fiber_id']),))[0]
    assert source == (False, plan.source_seq + 1), source
    driver, _m, resumed = resume_fresh(db, plan)
    outcome = drive(driver, resumed)
    assert outcome['phase'] == 'complete', outcome
    assert_one_switch(db, resumed)
    print('[CDP6-H4b] SIGKILL immediately after the off COMMIT resumes draining and activates '
          'the target exactly once')


def test_h4c_release_kill(db):
    root, old, driver, _maintainer, plan, _ni, _nf = crash_setup(db)
    driver.start(plan)
    driver._submit(plan, 'off')
    # First kill mid-P6 (one real maintenance pass after the off COMMIT).
    run_child(db, 'drain', plan)
    driver, _m, resumed = resume_fresh(db, plan)
    assert driver.status(resumed)['phase'] == 'draining', driver.status(resumed)
    # Second kill at the exact address-release boundary.
    run_child(db, 'release', resumed)
    assert live_count(db) == 0, 'the child must stop after the address release'
    assert owner_one(db, 'SELECT released_at IS NOT NULL FROM v24_cordis.contributions '
                         'WHERE fiber_id=%s', (uuid.UUID(old['fiber_id']),))
    driver, _m, resumed = resume_fresh(db, plan)
    outcome = drive(driver, resumed)
    assert outcome['phase'] == 'complete', outcome
    assert_one_switch(db, resumed)
    print('[CDP6-H4c] SIGKILL mid-P6 and again at the address-release boundary both resume '
          'from committed drain state and activate the new generation once')


def test_h4d_on_commit_kill(db):
    root, old, driver, _maintainer, plan, _ni, new_fiber = crash_setup(db)
    driver.start(plan)
    driver._submit(plan, 'off')
    for _ in range(60):
        state = driver.status(plan)
        if state['phase'] == 'on_pending':
            break
        driver.step(plan)
    else:
        raise AssertionError('drain did not reach on_pending')
    run_child(db, 'on', plan)
    assert count_switch(db, 'on') == 1
    driver, _m, resumed = resume_fresh(db, plan)
    outcome = drive(driver, resumed)
    assert outcome['phase'] == 'complete', outcome
    assert_one_switch(db, resumed)
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                     (new_fiber,)) == 1
    print('[CDP6-H4d] SIGKILL after the on COMMIT resumes activation without a second on '
          'request or duplicate episode')


# ---------------------------------------------------------------------- H5

def test_h5_operation_rejections(db):
    root = root_install(db)
    scope = uuid.UUID(root['scope']['id'])
    owner = owner_of(db, root['fiber_id'])
    a1 = activate(db, root, provides=['svc-a'])
    a2 = activate(db, root, provides=['svc-b'])
    driver, maintainer = switch_driver(db)
    plan1, _ni, _nf = upgrade_plan(db, driver, a1, digest='b' * 64)

    # Same operation/source/target but different payload bytes: the committed
    # request wins and conflicting bytes cannot start a second declaration.
    changed = declaration_for(db, uuid.UUID(a1['install_id']), uuid.UUID(plan1.target_install),
                              uuid.UUID(plan1.target_fiber), '2', 'c' * 64)
    plan_same = driver.plan_upgrade(operation=plan1.operation, actor=db.roles['service'],
                                    source_fiber=uuid.UUID(a1['fiber_id']),
                                    install_id=uuid.UUID(plan1.target_install),
                                    target_fiber=uuid.UUID(plan1.target_fiber),
                                    declaration=changed)
    driver.start(plan1)
    before = snap(db)
    try:
        driver.start(plan_same)
    except drv.SwitchStateError as exc:
        assert exc.code == 'request_conflict' and exc.reason == 'switch_operation_payload', exc
    else:
        raise AssertionError('same operation accepted different bytes')
    assert snap(db) == before

    # The same operation from another actor is not the same principal.
    decl = declaration_for(db, uuid.UUID(a1['install_id']), uuid.UUID(plan1.target_install),
                           uuid.UUID(plan1.target_fiber), '2', 'b' * 64)
    try:
        driver.plan_upgrade(operation=plan1.operation, actor=db.roles['admin'],
                            source_fiber=uuid.UUID(a1['fiber_id']),
                            install_id=uuid.UUID(plan1.target_install),
                            target_fiber=uuid.UUID(plan1.target_fiber),
                            declaration=decl)
    except drv.SwitchStateError as exc:
        assert exc.code == 'effect_id_conflict' and exc.reason == 'switch_actor', exc
    else:
        raise AssertionError('a different actor reused the operation identity')

    # A second unfinished operation on the same install slot is refused.
    other_install, other_fiber = uuid.uuid4(), uuid.uuid4()
    try:
        driver.plan_upgrade(operation=uuid.uuid4(), actor=db.roles['service'],
                            source_fiber=uuid.UUID(a1['fiber_id']),
                            install_id=other_install, target_fiber=other_fiber,
                            declaration=declaration_for(db, uuid.UUID(a1['install_id']),
                                                        other_install, other_fiber, '3',
                                                        'd' * 64))
    except drv.SwitchStateError as exc:
        assert exc.reason == 'switch_slot_busy', exc
    else:
        raise AssertionError('two unfinished operations shared one slot')

    # An independent control change makes the frozen source sequence stale.
    effect, result, _ = run_command(
        db, 'service', 'command_reconcile',
        reconcile_payload(uuid.UUID(a1['fiber_id']), 'off', plan1.source_seq),
        'w4/h5/external-off/' + uuid.uuid4().hex)
    assert result.get('disposition') == 'committed', result
    assert count_switch(db, 'off') == 0
    before = snap(db)
    state = driver.step(plan1)
    assert state['action'] == 'none' and state['phase'] == 'blocked', state
    assert state['state']['reason'] == 'stale_control_seq', state['state']
    assert snap(db) == before

    # Reuse preflight rejects duplicate fiber ids and a digest mismatch before any write.
    reuse_bad_fiber = {'mode': 'reuse', 'install_id': a1['install_id'],
                       'fiber_id': a1['fiber_id'],
                       'expected_digest': install_row(db, uuid.UUID(a1['install_id']))[6]}
    result = zero_write(db, lambda: rolled_back(
        db, 'service', 'command_install', reuse_bad_fiber,
        'w4/h5/dup-fiber/' + uuid.uuid4().hex))
    assert error_code(result) == 'invalid_args' and error_reason(result) == 'fiber_id', result
    reuse_bad_digest = {'mode': 'reuse', 'install_id': a1['install_id'],
                        'fiber_id': str(uuid.uuid4()), 'expected_digest': 'e' * 64}
    result = zero_write(db, lambda: rolled_back(
        db, 'service', 'command_install', reuse_bad_digest,
        'w4/h5/digest/' + uuid.uuid4().hex))
    assert error_code(result) == 'install_identity_conflict' \
        and error_reason(result) == 'install_reuse_digest', result

    # A target independently enabled after draining stops the switch.
    plan2, _ni2, new2 = upgrade_plan(db, driver, a2, digest='f' * 64)
    driver2, _m2 = switch_driver(db)
    # The first plan's source is still live but off-requested; the second slot is
    # independent, so a fresh driver can plan it.
    plan2 = driver2.plan_upgrade(
        operation=uuid.uuid4(), actor=db.roles['service'],
        source_fiber=uuid.UUID(a2['fiber_id']),
        install_id=uuid.UUID(plan2.target_install),
        target_fiber=uuid.UUID(plan2.target_fiber),
        declaration=declaration_for(db, uuid.UUID(a2['install_id']),
                                    uuid.UUID(plan2.target_install),
                                    uuid.UUID(plan2.target_fiber), '2', 'f' * 64))
    driver2.start(plan2)
    driver2._submit(plan2, 'off')
    for _ in range(40):
        if driver2.status(plan2)['phase'] == 'on_pending':
            break
        driver2.step(plan2)
    assert driver2.status(plan2)['phase'] == 'on_pending'
    _, result, _ = run_command(
        db, 'service', 'command_reconcile',
        reconcile_payload(uuid.UUID(plan2.target_fiber), 'on', 0),
        'w4/h5/external-on/' + uuid.uuid4().hex)
    assert result.get('disposition') == 'committed', result
    before = snap(db)
    state = driver2.step(plan2)
    assert state['action'] == 'none' and state['state']['reason'] == 'switch_target_moved', state
    assert snap(db) == before

    # A changed owner episode makes the reuse declaration unresumable.
    owner_fiber = uuid.UUID(root['fiber_id'])
    old_episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                            (owner_fiber,))
    new_episode = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'UPDATE v24_cordis.episodes SET closed_at=clock_timestamp() WHERE id=%s',
              (old_episode,))
        query(conn, 'INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) '
                    "VALUES(%s,%s,(SELECT coalesce(max(epoch),-1)+1 FROM v24_cordis.episodes "
                    "WHERE fiber_id=%s),'active','{}',%s)",
              (new_episode, owner_fiber, owner_fiber,
               Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0))))
        query(conn, 'UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',
              (new_episode, owner_fiber))
        conn.commit()
    reuse_owner = {'mode': 'reuse', 'install_id': a2['install_id'],
                   'fiber_id': str(uuid.uuid4()),
                   'expected_digest': install_row(db, uuid.UUID(a2['install_id']))[6]}
    result = zero_write(db, lambda: rolled_back(
        db, 'service', 'command_install', reuse_owner,
        'w4/h5/owner/' + uuid.uuid4().hex))
    assert error_code(result) == 'owner_closing' \
        and error_reason(result) == 'install_reuse_owner', result
    print('[CDP6-H5] conflicting payload/actor, same-slot concurrency, stale control '
          'sequence, independently enabled target, duplicate fiber, digest mismatch and a '
          'changed owner episode are all refused or safely blocked without a write')


# ---------------------------------------------------------------------- H6

def test_h6_rollback_new_episode_and_dispose(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    old_fiber = uuid.UUID(old['fiber_id'])
    old_install = uuid.UUID(old['install_id'])
    before_declaration = install_row(db, old_install)
    before_episodes = owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                                (old_fiber,))
    driver, maintainer = switch_driver(db)
    upgrade, new_install, new_fiber = upgrade_plan(db, driver, old)
    assert drive(driver, upgrade)['phase'] == 'complete'
    assert source_drained(db, old_fiber)

    a2 = uuid.uuid4()
    rollback = driver.plan_rollback(
        operation=uuid.uuid4(), actor=db.roles['service'], source_fiber=new_fiber,
        target_install=old_install, target_fiber=a2,
        expected_digest=old['artifact_digest'], provides=('svc',))
    run_child(db, 'start_rollback', rollback)
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE id=%s', (a2,)) == 1
    driver, _m, resumed = resume_fresh(db, rollback)
    for _ in range(60):
        state = driver.status(resumed)
        if state['phase'] == 'on_pending':
            break
        driver.step(resumed)
    else:
        raise AssertionError(('rollback did not reach on_pending', driver.status(resumed)))
    run_child(db, 'on', resumed)
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE request_key=%s',
                     (resumed.on_key(),)) == 1
    driver, maintainer, resumed = resume_fresh(db, rollback)
    assert drive(driver, resumed)['phase'] == 'complete'
    assert count_switch(db, 'start') == 2          # one U + one R
    assert install_row(db, old_install) == before_declaration
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                     (old_fiber,)) == before_episodes, 'the old fiber must not be revived'
    assert owner_rows(db, 'SELECT want_on,current_episode_id IS NULL FROM v24_cordis.fibers '
                          'WHERE id=%s', (old_fiber,)) == [(False, True)]
    assert owner_rows(db, 'SELECT want_on,current_episode_id IS NOT NULL FROM v24_cordis.fibers '
                          'WHERE id=%s', (a2,)) == [(True, True)]
    a2_episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                           (a2,))
    provider, episode, available = resolved(db, uuid.UUID(root['scope']['id']))
    assert available and provider == a2 and episode == a2_episode
    assert live_count(db) == 1
    children = owner_rows(db, "SELECT descriptor->>'child_fiber_id' FROM v24_cordis.contributions "
                              "WHERE kind='child' AND released_at IS NULL AND descriptor->>'child_fiber_id' "
                              'IN (%s,%s) ORDER BY 1', (str(old_fiber), str(a2)))
    assert {row[0] for row in children} == {str(old_fiber), str(a2)}, children
    assert install_row(db, old_install)[4] == before_declaration[4]

    subtree = owner_rows(db, 'SELECT id FROM v24_cordis.dispose_subtree(%s)', (old_install,))
    assert {row[0] for row in subtree} == {old_fiber, a2}, subtree
    _, result, _ = run_command(db, 'service', 'command_dispose',
                               {'install_id': str(old_install)},
                               'w4/h6/dispose/' + uuid.uuid4().hex)
    assert result.get('disposition') == 'committed', result
    for _ in range(80):
        if owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                     (old_install,)) == 'disposed':
            break
        maintainer.run_once()
    assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                     (old_install,)) == 'disposed'
    assert {row[0] for row in owner_rows(db, 'SELECT id FROM v24_cordis.fibers WHERE install_id=%s '
                                             'AND disposed_at IS NOT NULL', (old_install,))} == {
        old_fiber, a2}
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                     (old_fiber,)) == before_episodes
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                     (old_fiber,)) >= 1

    try:
        driver.plan_rollback(operation=uuid.uuid4(), actor=db.roles['service'],
                             source_fiber=a2, target_install=old_install,
                             target_fiber=uuid.uuid4(),
                             expected_digest=old['artifact_digest'], provides=('svc',))
    except drv.SwitchStateError as exc:
        assert exc.reason == 'switch_rollback_state', exc
    else:
        raise AssertionError('a disposed install was admitted for rollback')
    reuse = {'mode': 'reuse', 'install_id': str(old_install),
             'fiber_id': str(uuid.uuid4()), 'expected_digest': old['artifact_digest']}
    result = zero_write(db, lambda: rolled_back(
        db, 'service', 'command_install', reuse, 'w4/h6/reuse/' + uuid.uuid4().hex))
    assert error_code(result) == 'install_not_ready' \
        and error_reason(result) == 'install_reuse_state', result
    print('[CDP6-H6] rollback creates a new fiber/episode on the immutable old declaration, '
          'keeps the old fiber asleep, and disposing the install covers every historical '
          'instance; a disposed install cannot be reused')


# ---------------------------------------------------------------------- H7

def add_unknown_effect(db, fiber):
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    effect = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,input,"
                 "request_actor,outcome,settled_at) VALUES(%s,%s,%s,'model_call','unknown',"
                 "'{}',%s,%s,clock_timestamp())",
             (effect, fiber, episode, db.roles['service'],
              Json({'v': 1, 'class': 'unknown', 'claim': None,
                    'body': {'kind': 'model_call'}})))
    return effect


def test_h7_unknown_debt_stops_switch(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    fiber = uuid.UUID(old['fiber_id'])
    debt = add_unknown_effect(db, fiber)
    driver, maintainer = switch_driver(db)
    plan, _ni, new_fiber = upgrade_plan(db, driver, old)
    driver.start(plan)
    driver._submit(plan, 'off')
    blocked = False
    for _ in range(10):
        outcome = driver.step(plan)
        report = outcome.get('report')
        if report is not None:
            blocked = blocked or any(
                row.get('disposition') == 'blocked_unknown'
                for row in report.actions + report.diagnostics
                if isinstance(row, dict))
    state = driver.status(plan)
    assert state['phase'] == 'draining', state
    assert 'effect' in state['drain']['reasons'], state['drain']
    assert count_switch(db, 'on') == 0
    assert live_count(db) == 1, 'the debt must keep the old provider from releasing'
    assert owner_rows(db, 'SELECT status,outcome IS NOT NULL FROM v24_cordis.effects '
                          'WHERE id=%s', (debt,)) == [('unknown', True)]
    stable = snap(db)
    for _ in range(3):
        maintainer.run_once()
    assert snap(db) == stable, 'a blocked debt must reach a write-free steady state'
    assert blocked, 'the scanner never surfaced blocked_unknown'

    a2 = uuid.uuid4()
    rollback = driver.plan_rollback(
        operation=uuid.uuid4(), actor=db.roles['service'], source_fiber=new_fiber,
        target_install=uuid.UUID(old['install_id']), target_fiber=a2,
        expected_digest=old['artifact_digest'], provides=('svc',))
    before = snap(db)
    try:
        driver.start(rollback)
    except drv.SwitchStateError as exc:
        assert exc.code == 'blocked_unknown' and exc.reason == 'install_reuse_debt', exc
    else:
        raise AssertionError('rollback reused an install with terminal unknown debt')
    assert snap(db) == before
    assert owner_rows(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
                      (debt,)) == [('unknown',)]
    assert live_count(db) == 1
    print('[CDP6-H7] a terminal unknown keeps the upgrade draining and refuses rollback reuse; '
          'the debt row is never cleared or rewritten')


# ---------------------------------------------------------------------- H8

def test_h8_listener_switch_is_not_mixed(db):
    root = root_install(db)
    scope = uuid.UUID(root['scope']['id'])
    host = listener('w4-host', 'emit', 10, {'type': 'host', 'capability': 'listener_call'})
    provider, fiber, result = dispatch_create(
        db, scope, owner_of(db, root['fiber_id']), provides=['svc'], listeners=[host],
        contracts={'listener_call': HOST})
    assert result.get('disposition') == 'committed', result
    old_calls = host_calls(db, fiber, 'ready')
    assert old_calls
    settle_host_calls(db, fiber)
    driver, maintainer = switch_driver(db)
    plan, _ni, new_fiber = upgrade_plan(db, driver, provider)
    assert driver.start(plan)['action'] == 'start'
    driver._submit(plan, 'off')
    for _ in range(60):
        state = driver.status(plan)
        if state['phase'] == 'on_pending':
            break
        driver.step(plan)
    assert driver.status(plan)['phase'] == 'on_pending', driver.status(plan)
    # The window carries neither generation: the old listener is released and the
    # new one does not exist yet.
    assert owner_one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE kind='listener' "
                         'AND released_at IS NULL') == 0
    assert live_count(db) == 0
    assert resolved(db, scope)[2] is False
    assert drive(driver, plan)['phase'] == 'complete'
    assert owner_one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE kind='listener' "
                         'AND released_at IS NULL AND fiber_id=%s', (new_fiber,)) == 1
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE kind=%s '
                         'AND released_at IS NULL AND fiber_id=%s', ('listener', fiber)) == 0
    new_episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                            (new_fiber,))
    new_calls = owner_rows(db,
                           "SELECT e.id,e.episode_id,d.fiber_id FROM v24_cordis.effects e "
                           "JOIN v24_cordis.effects d ON d.id=e.parent_id "
                           "WHERE e.kind='listener_call' AND e.fiber_id=%s AND e.status='ready'",
                           (new_fiber,))
    assert new_calls and all(row[1] == new_episode and row[2] == new_fiber
                             for row in new_calls), new_calls
    provider_fiber, provider_episode, available = resolved(db, scope)
    assert available and provider_fiber == new_fiber and provider_episode == new_episode
    print('[CDP6-H8] the upgraded service and its event listener both resolve to the new '
          'generation; the window and dispatch children never mix generations')


# ---------------------------------------------------------------------- H9

def test_h9_hmr_trigger(db):
    root = root_install(db)
    old = activate(db, root, provides=['svc'])
    driver, maintainer = switch_driver(db)
    new_install, new_fiber = uuid.uuid4(), uuid.uuid4()
    declaration = declaration_for(db, uuid.UUID(old['install_id']), new_install,
                                  new_fiber, '2', 'b' * 64)
    descriptor = {'identity': declaration['identity'], 'version': '2',
                  'artifact_digest': 'b' * 64,
                  'operation_uuid': str(uuid.uuid4()),
                  'source_fiber_id': old['fiber_id'],
                  'install_id': str(new_install), 'target_fiber_id': str(new_fiber),
                  'manifest': declaration['manifest'],
                  'contracts': declaration['contracts'],
                  'policy_ref': declaration['policy_ref'],
                  'overlay': declaration['overlay']}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, 'svc.json')
        path.write_text(json.dumps(descriptor))
        trigger = drv.HmrTrigger(driver, tmp, db.roles['service'])
        first = trigger.tick()
        assert first[0]['driver'] == 'hmr_started' and first[0]['action'] == 'start', first
        second = trigger.tick()
        assert second[0]['driver'] == 'hmr_inflight', second
        assert second[0]['action'] == 'start_replay', second
        assert count_switch(db, 'start') == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s',
                         (new_install,)) == 1
        resumed = driver.resume('U', uuid.UUID(descriptor['operation_uuid']),
                                db.roles['service'])
        assert drive(driver, resumed)['phase'] == 'complete'
        current = dict(descriptor, operation_uuid=str(uuid.uuid4()),
                       source_fiber_id=str(new_fiber), install_id=str(uuid.uuid4()),
                       target_fiber_id=str(uuid.uuid4()), version='2',
                       artifact_digest='b' * 64)
        path.write_text(json.dumps(current))
        before = snap(db)
        clock = trigger.tick()
        assert clock[0]['driver'] == 'hmr_current', clock
        assert snap(db) == before
        path.write_text(json.dumps({'identity': 'x'}))
        bad = trigger.tick()
        assert bad[0]['driver'] == 'hmr_descriptor_invalid', bad
        assert snap(db) == before
        path.write_text(json.dumps(dict(descriptor, identity='other-identity',
                                        operation_uuid=str(uuid.uuid4()))))
        mismatch = trigger.tick()
        assert mismatch[0]['driver'] == 'hmr_identity_mismatch', mismatch
        assert snap(db) == before
    source = __import__('inspect').getsource(drv.HmrTrigger)
    for token in ('socket', 'urllib', 'requests.', 'importlib', 'subprocess', 'exec(',
                  'eval(', 'os.system', 'import '):
        assert token not in source, (token, source)
    print('[CDP6-H9] HMR ticks submit the identical stable request, a repeated tick replays '
          'instead of installing again, and the trigger has no download/ESM path')


# --------------------------------------------------------------------- main

def main():
    if '--child' in sys.argv[1:]:
        _child()
        return
    tests = (test_h1_declaration_identity, test_h2_old_obligations_block_release,
             test_h3_window_and_unique_address, test_h3b_early_activation_is_rejected,
             test_h3c_dependency_unresolved,
             test_h4a_start_commit_and_retry, test_h4b_off_commit_kill,
             test_h4c_release_kill, test_h4d_on_commit_kill,
             test_h5_operation_rejections, test_h6_rollback_new_episode_and_dispose,
             test_h7_unknown_debt_stops_switch, test_h8_listener_switch_is_not_mixed,
             test_h9_hmr_trigger)
    with Server() as server:
        for test in tests:
            with TestDB(server) as db:
                test(db)
    print('[passed] CDP6-H')


if __name__ == '__main__':
    main()
