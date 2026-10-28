"""DP4 disposable fixtures shared by the run/reducer/loop/boundary gates.

Provider and agent fibers are activated through the real P0-P4 path. The only
owner DML is explicit negative/ledger setup in the individual gates.
"""
from __future__ import annotations
import contextlib
from pathlib import Path
import sys
import uuid

CORDIS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORDIS / 'dp2'))
sys.path.insert(0, str(CORDIS / 'dp1'))

from psycopg2.extras import Json  # noqa: E402
from test_support import (Server, TestDB, snapshot, query, api, command, env,  # noqa: E402
                          no_write, install_payload, reconcile_payload, successor_key,
                          function_defs, replace_function, active_owner)
from test_activation import (one, rows, install, phases, commit_new, child_call, commit_child, p0)  # noqa: E402


def q1(db, statement, params=()):
    return one(db, statement, params)


def claim(db, effect, lease=300000, alias='service'):
    with contextlib.closing(db.connect(alias)) as conn:
        result = api(conn, effect, env('claim', {'lease_ms': lease}))
        conn.commit()
    return result


def settle(db, effect, body, token, cls='success', alias='service'):
    with contextlib.closing(db.connect(alias)) as conn:
        result = api(conn, effect, env(cls, body, token))
        conn.commit()
    return result


def claim_success(db, effect, body, lease=300000):
    c = claim(db, effect, lease)
    assert c.get('disposition') == 'claimed', c
    return c, settle(db, effect, body, c['claim'])


def provider(db, capability, key, *, replay=(True, True), digest='b' * 64):
    root = active_owner(db)
    payload = install_payload(mode='existing', existing_scope=root['scope'],
                              owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])))
    payload['manifest'] = dict(
        requires=[], provides=[dict(key=key, descriptor={'capability': capability},
                                    contract_version='1')],
        priority=0, check={})
    payload['contracts'] = {capability: dict(
        contract_version='1', handler_digest=digest,
        replay=dict(repeat=bool(replay[0]), concurrent=bool(replay[1])))}
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    phases(db, fiber, 1)
    return dict(payload=payload, effect=effect, fiber=fiber,
                key=key, capability=capability)


def agent(db, requires=('model', 'tool'), *, policy='chat_tool', run_contract=True,
          phases_count=0):
    root = active_owner(db)
    payload = install_payload(mode='existing', existing_scope=root['scope'],
                              owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])))
    payload['manifest'] = dict(
        requires=list(requires), provides=[], priority=0, check={})
    payload['contracts'] = ({'run_start': dict(
        contract_version='1', handler_digest='c' * 64,
        replay=dict(repeat=True, concurrent=True))} if run_contract else {})
    payload['policy_ref'] = policy
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, started, _ = p0(db, fiber)
    assert started.get('emitted'), started
    step, result = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert result.get('disposition') == 'committed', result
    if phases_count:
        phases(db, fiber, phases_count)
    else:
        step, result = commit_child(db, step, reconcile_payload(fiber, 'advance', 1))
        assert result.get('disposition') == 'committed', result
    return dict(payload=payload, effect=effect, fiber=fiber, p4_effect=step,
                p4_result=result, run_start=(result['emitted'][0]
                                             if result.get('emitted') else None))


def run_start_effect(db, result):
    if not result.get('emitted'):
        return None
    return uuid.UUID(result['emitted'][0])


def run_row(db, run_id):
    return rows(db, 'SELECT state,remaining_steps,ended_at,result,owner_fiber_id,'
                    'owner_episode_id,scope_id FROM v24_cordis.runs WHERE id=%s',
                (run_id,))[0]


def count(db, statement, params=()):
    return q1(db, statement, params)


def event_payload(db, effect):
    return q1(db, "SELECT payload FROM v24_cordis.events WHERE effect_id=%s "
                  "AND event_kind='run_progress'", (effect,))
