"""W6 gate: partial refresh keeps untouched slices, pending_refresh tail chains the next op."""
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


def as_dict(message):
    return message if isinstance(message, dict) else json.loads(message)


def make_slice(slice_id, seq, dep_uri, body):
    return {'slice_id': slice_id, 'seq': seq, 'kind': 'source_excerpt',
            'dep_uri': dep_uri, 'title': f'{slice_id} title', 'body': body,
            'content_hash': hashlib.md5(body.encode()).hexdigest(), 'deps': [dep_uri]}


def read_queue(cur):
    cur.execute("SELECT msg_id, read_ct, message FROM pgmq.read(%s, 30, 1)", (QUEUE,))
    return cur.fetchone()


def main() -> int:
    check('setup', setup_db() == 0)
    c = psycopg2.connect(get_server().get_uri(DB))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SELECT pgmq.purge_queue(%s)", (QUEUE,))

        # --- rebuild the W5 state from scratch via public functions only
        cur.execute("SELECT ctx_on_commit('default', 'c0', ARRAY[]::text[])")
        cur.fetchone()
        cur.execute("SELECT ctx_create_task(%s)", ('w6 refresh gate',))
        run = cur.fetchone()[0]
        cur.execute("SELECT ctx_ensure_pack(%s, 'default')", (run,))
        ens = cur.fetchone()[0]
        pack, rid1 = ens['pack_id'], ens['request_id']
        row = read_queue(cur)
        check('build message readable', row is not None)
        msg1 = row[0]
        cur.execute("SELECT pgmq.archive(%s, %s)", (QUEUE, msg1))

        build = {'request_id': rid1, 'op_seq': 1, 'success': True, 'run_id': run,
                 'worker_id': 'w6-hand', 'base_commit': 'c0', 'trigger_kind': 'build',
                 'token_count': 11,
                 'slices': [make_slice('src_orders', 1, 'src:orders', '{"rows":["o-v1"]}'),
                            make_slice('src_users', 2, 'src:users', '{"rows":["u-v1"]}')]}
        cur.execute("SELECT apply_ctx_result(%s, %s::jsonb)", (run, json.dumps(build)))
        check('build applied', cur.fetchone()[0].get('ok') is True)
        cur.execute("SELECT content_hash FROM context_slices WHERE pack_id=%s AND slice_id='src_users'", (pack,))
        users_hash_before = cur.fetchone()[0]

        # --- c1 dirties orders only; refresh rebuilds orders and leaves users untouched
        cur.execute("SELECT ctx_on_commit('default', 'c1', ARRAY['src:orders'])")
        cur.fetchone()
        row = read_queue(cur)
        check('refresh message readable', row is not None)
        msg2, _read_ct, message2 = row
        rid2 = as_dict(message2)['request_id']
        cur.execute("SELECT op_kind, op_seq, status FROM ctx_operations WHERE request_id=%s", (rid2,))
        check('enqueued op is refresh seq 2', cur.fetchone() == ('refresh', 2, 'QUEUED'))

        refresh = {'request_id': rid2, 'op_seq': 2, 'success': True, 'run_id': run,
                   'worker_id': 'w6-hand', 'base_commit': 'c1',
                   'trigger_kind': 'run_completed', 'token_count': 8,
                   'slices': [make_slice('src_orders', 1, 'src:orders', '{"rows":["o-v2"]}'),]}
        cur.execute("SELECT apply_queue_result(%s, %s, %s, %s::jsonb)",
                    (QUEUE, msg2, run, json.dumps(refresh)))
        applied = cur.fetchone()[0]
        check('refresh apply ok', applied.get('ok') is True, applied)
        cur.execute("SELECT pgmq.archive(%s, %s)", (QUEUE, msg2))

        cur.execute("SELECT generation, base_commit, last_completed_op_seq, pending_refresh FROM context_packs WHERE pack_id=%s", (pack,))
        gen, pbase, lastc, pend = cur.fetchone()
        check('generation=2 base=c1 last_completed=2',
              (gen, pbase, lastc) == (2, 'c1', 2), (gen, pbase, lastc))
        cur.execute("SELECT slice_id, stale, body, content_hash FROM context_slices WHERE pack_id=%s ORDER BY slice_id", (pack,))
        rows = cur.fetchall()
        check('orders rebuilt clean with new body',
              rows[0] == ('src_orders', False, '{"rows":["o-v2"]}',
                          hashlib.md5('{"rows":["o-v2"]}'.encode()).hexdigest()), rows[0])
        check('users content_hash untouched by partial rebuild',
              rows[1][3] == users_hash_before and rows[1][1] is False, rows[1])
        cur.execute("SELECT trigger_kind, dirty_slices, rebuilt_slices, base_from, base_to FROM context_refresh_log WHERE pack_id=%s ORDER BY seq", (pack,))
        logs = cur.fetchall()
        check('refresh_log rows: build then run_completed refresh',
              len(logs) == 2 and logs[1][0] == 'run_completed'
              and logs[1][1] == ['src_orders'] and sorted(logs[1][2]) == ['src_orders']
              and (logs[1][3], logs[1][4]) == ('c0', 'c1'), logs)
        cur.execute("SELECT count(*) FROM ctx_operations WHERE pack_id=%s", (pack,))
        check('no tail op without pending_refresh', cur.fetchone()[0] == 2)

        # --- pending_refresh tail: c2 re-dirties orders (enqueue op 3), c3 arrives
        #     while op 3 is in flight -> pending latched; applying the empty refresh
        #     (base = current head) consumes the pending flag and auto-enqueues the
        #     next refresh op.
        cur.execute("SELECT ctx_on_commit('default', 'c2', ARRAY['src:orders'])")
        cur.fetchone()
        cur.execute("SELECT ctx_on_commit('default', 'c3', ARRAY['src:orders'])")
        cur.fetchone()
        cur.execute("SELECT pending_refresh FROM context_packs WHERE pack_id=%s", (pack,))
        check('c3 while op in flight latches pending_refresh', cur.fetchone()[0] is True)
        row = read_queue(cur)
        check('refresh op 3 message readable', row is not None)
        msg3, _rc, message3 = row
        rid3 = as_dict(message3)['request_id']
        cur.execute("SELECT pgmq.archive(%s, %s)", (QUEUE, msg3))
        cur.execute("SELECT head_commit FROM repo_heads WHERE repo_path='default'")
        head_now = cur.fetchone()[0]
        check('head advanced to c3 before empty refresh', head_now == 'c3')

        empty = {'request_id': rid3, 'op_seq': 3, 'success': True, 'run_id': run,
                 'worker_id': 'w6-hand', 'base_commit': head_now,
                 'trigger_kind': 'run_completed', 'token_count': 0, 'slices': []}
        cur.execute("SELECT apply_ctx_result(%s, %s::jsonb)", (run, json.dumps(empty)))
        out = cur.fetchone()[0]
        check('empty refresh apply ok', out.get('ok') is True, out)
        cur.execute("SELECT status, pending_refresh, base_commit, next_op_seq FROM context_packs WHERE pack_id=%s", (pack,))
        status, pend, pbase, nxt = cur.fetchone()
        # Empty refresh at base==head leaves the pack FRESH; the tail enqueue may then
        # legitimately transition FRESH->REFRESHING (same 6 steps as _ctx_enqueue_op),
        # so both are accepted here - the load-bearing assertions are below.
        check('pack clean after empty refresh (FRESH or REFRESHING via tail enqueue)',
              status in ('FRESH', 'REFRESHING'), status)
        check('pending_refresh consumed', pend is False)
        check('empty refresh advanced base to head', pbase == 'c3', pbase)
        cur.execute("SELECT op_kind, op_seq, status FROM ctx_operations WHERE pack_id=%s ORDER BY op_seq", (pack,))
        ops = cur.fetchall()
        check('tail auto-enqueued next QUEUED refresh op_seq=4',
              ops[-1] == ('refresh', 4, 'QUEUED') and len(ops) == 4, ops)
        check('next_op_seq advanced past the tail op', nxt == 5, nxt)
        row = read_queue(cur)
        check('tail op message landed on the queue',
              row is not None and as_dict(row[2]).get('op_seq') == 4, row)

    c.close()
    print('[W6] all gates passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
