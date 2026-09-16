"""W7 gate: start-gate freshness branches - fresh / sync_refresh / drift_delta / retired."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg2
from server import get_server
from v9.ctx_lifecycle.setup_db import DB, main as setup_db

QUEUE = 'ctx_heavy_requests'


def check(label, cond, detail=''):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f": {detail}" if detail else ''))
    if not cond:
        raise AssertionError(f'{label}: {detail}')


def make_slice(slice_id, seq, dep_uri, body):
    return {'slice_id': slice_id, 'seq': seq, 'kind': 'source_excerpt',
            'dep_uri': dep_uri, 'title': f'{slice_id} title', 'body': body,
            'content_hash': hashlib.md5(body.encode()).hexdigest(), 'deps': [dep_uri]}


def main() -> int:
    check('setup', setup_db() == 0)
    c = psycopg2.connect(get_server().get_uri(DB))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SELECT pgmq.purge_queue(%s)", (QUEUE,))

        # --- rebuild a fresh pack: head c0, build at c0
        cur.execute("SELECT ctx_on_commit('default', 'c0', ARRAY[]::text[])")
        cur.fetchone()
        cur.execute("SELECT ctx_create_task(%s)", ('w7 gate',))
        run = cur.fetchone()[0]
        cur.execute("SELECT ctx_ensure_pack(%s, 'default')", (run,))
        ens = cur.fetchone()[0]
        pack, rid1 = ens['pack_id'], ens['request_id']
        cur.execute("SELECT msg_id FROM pgmq.read(%s, 30, 1)", (QUEUE,))
        msg1 = cur.fetchone()[0]
        cur.execute("SELECT pgmq.archive(%s, %s)", (QUEUE, msg1))
        build = {'request_id': rid1, 'op_seq': 1, 'success': True, 'run_id': run,
                 'worker_id': 'w7-hand', 'base_commit': 'c0', 'trigger_kind': 'build',
                 'token_count': 11,
                 'slices': [make_slice('src_orders', 1, 'src:orders', '{"rows":["o-v1"]}'),
                            make_slice('src_users', 2, 'src:users', '{"rows":["u-v1"]}')]}
        cur.execute("SELECT apply_ctx_result(%s, %s::jsonb)", (run, json.dumps(build)))
        check('build applied', cur.fetchone()[0].get('ok') is True)

        # --- branch 1: base == head -> fresh, action none
        cur.execute("SELECT ctx_gate(%s)", (run,))
        g = cur.fetchone()[0]
        check('gate fresh at base==head',
              g.get('success') is True and g.get('fresh') is True
              and g.get('action') == 'none' and g.get('base_commit') == 'c0'
              and g.get('head') == 'c0' and g.get('drift') == [], g)

        # --- branch 2: one dependent uri touched -> sync_refresh
        cur.execute("SELECT ctx_on_commit('default', 'c1', ARRAY['src:orders'])")
        cur.fetchone()
        cur.execute("SELECT ctx_gate(%s)", (run,))
        g2 = cur.fetchone()[0]
        check('gate sync_refresh after one dirty slice',
              g2.get('success') is True and g2.get('fresh') is False
              and g2.get('action') == 'sync_refresh'
              and g2.get('dirty_slices') == [{'slice_id': 'src_orders', 'dep_uri': 'src:orders'}]
              and g2.get('changed_uris') == ['src:orders']
              and (g2.get('base_commit'), g2.get('head')) == ('c0', 'c1'), g2)

        # --- branch 3: both slices dirty, threshold 1 -> drift_delta
        cur.execute("SELECT ctx_on_commit('default', 'c2', ARRAY['src:orders', 'src:users'])")
        cur.fetchone()
        cur.execute("SELECT ctx_gate(%s, 1)", (run,))
        g3 = cur.fetchone()[0]
        drift = g3.get('drift')
        check('gate drift_delta above threshold',
              g3.get('success') is True and g3.get('fresh') is False
              and g3.get('action') == 'drift_delta' and g3.get('dirty_count') == 2, g3)
        check('drift lists {commit,dep_uri} pairs from the window',
              {'commit': 'c1', 'dep_uri': 'src:orders'} in drift
              and {'commit': 'c2', 'dep_uri': 'src:orders'} in drift
              and {'commit': 'c2', 'dep_uri': 'src:users'} in drift, drift)
        # default threshold 3 would still sync_refresh at dirty_count 2
        cur.execute("SELECT ctx_gate(%s)", (run,))
        g3b = cur.fetchone()[0]
        check('default threshold keeps dirty_count 2 in sync_refresh',
              g3b.get('action') == 'sync_refresh' and len(g3b.get('dirty_slices')) == 2, g3b)

        # --- branch 4: RETIRED pack and unknown task
        cur.execute("SELECT ctx_retire_pack(%s)", (run,))
        retired = cur.fetchone()[0]
        check('ctx_retire_pack succeeds',
              retired.get('success') is True and retired.get('status') == 'RETIRED', retired)
        cur.execute("SELECT ctx_gate(%s)", (run,))
        g4 = cur.fetchone()[0]
        check('gate rejects RETIRED pack',
              g4.get('success') is False and g4.get('Type') == 'CTX_PACK_RETIRED', g4)
        cur.execute("SELECT ctx_gate(%s)", ('no-such-run',))
        g5 = cur.fetchone()[0]
        check('gate rejects unknown task with CTX_PACK_NOT_FOUND',
              g5.get('success') is False and g5.get('Type') == 'CTX_PACK_NOT_FOUND', g5)

    c.close()
    print('[W7] all gates passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
