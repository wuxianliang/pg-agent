"""W4 gate: pack build lifecycle - create task, ensure pack, build apply, replay, ordering."""
from __future__ import annotations
import hashlib, json, sys, uuid
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


def read_queue(cur):
    cur.execute("SELECT msg_id, read_ct, message FROM pgmq.read(%s, 30, 1)", (QUEUE,))
    return cur.fetchone()


def as_dict(message):
    return message if isinstance(message, dict) else json.loads(message)


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

        # --- parked task: run row, zero steps, nothing on the LLM queue
        cur.execute("SELECT ctx_create_task(%s)", ('w4 build gate',))
        run = cur.fetchone()[0]
        check('ctx_create_task returns run_id', bool(run), run)
        cur.execute("SELECT count(*) FROM agent_runs WHERE run_id=%s", (run,))
        check('agent_runs has the parked row', cur.fetchone()[0] == 1)
        cur.execute("SELECT count(*) FROM agent_steps WHERE run_id=%s", (run,))
        check('parked run has zero steps', cur.fetchone()[0] == 0)

        # --- ensure pack
        cur.execute("SELECT ctx_ensure_pack(%s, 'default')", (run,))
        ensured = cur.fetchone()[0]
        check('ctx_ensure_pack success', ensured.get('success') is True, ensured)
        pack = ensured['pack_id']
        rid1 = ensured['request_id']
        cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
        check('parked run enqueues no LLM message', cur.fetchone()[0] == 0)
        cur.execute("SELECT status, base_commit, next_op_seq, last_completed_op_seq FROM context_packs WHERE pack_id=%s", (pack,))
        status, base, nxt, lastc = cur.fetchone()
        check('pack BUILDING at INIT, next_op_seq=2', (status, base, nxt, lastc) == ('BUILDING', 'INIT', 2, 0), (status, base, nxt, lastc))
        cur.execute("SELECT op_kind, op_seq, status FROM ctx_operations WHERE pack_id=%s", (pack,))
        ops = cur.fetchall()
        check('exactly one QUEUED build op_seq=1', ops == [('build', 1, 'QUEUED')], ops)

        # --- the enqueued message carries the op identity
        row = read_queue(cur)
        check('build message readable from ctx_heavy_requests', row is not None)
        msg_id, _read_ct, message = row
        payload = as_dict(message)
        check('payload identifies the op',
              payload.get('request_id') == rid1 and payload.get('pack_id') == pack
              and payload.get('task_run_id') == run and payload.get('op_kind') == 'build'
              and payload.get('op_seq') == 1 and payload.get('repo_path') == 'default'
              and payload.get('trigger') == 'ensure',
              payload)
        cur.execute("SELECT pgmq.archive(%s, %s)", (QUEUE, msg_id))

        # --- idempotent ensure
        cur.execute("SELECT ctx_ensure_pack(%s, 'default')", (run,))
        again = cur.fetchone()[0]
        check('second ensure replays the same pack',
              again.get('pack_id') == pack and again.get('replayed') is True, again)
        cur.execute("SELECT count(*) FROM ctx_operations WHERE pack_id=%s", (pack,))
        check('ops still exactly one after replay', cur.fetchone()[0] == 1)
        check('no second queue message', read_queue(cur) is None)

        # --- hand-crafted build result (2 slices at base INIT) via generic dispatch
        result = {'request_id': rid1, 'op_seq': 1, 'success': True, 'run_id': run,
                  'worker_id': 'w4-hand', 'base_commit': 'INIT', 'trigger_kind': 'build',
                  'token_count': 42,
                  'slices': [make_slice('src_orders', 1, 'src:orders', '{"rows":["o1"]}'),
                             make_slice('src_users', 2, 'src:users', '{"rows":["u1"]}')]}
        cur.execute("SELECT apply_queue_result(%s, %s, %s, %s::jsonb)",
                    (QUEUE, msg_id, run, json.dumps(result)))
        applied = cur.fetchone()[0]
        check('build apply dispatches ok', applied.get('ok') is True, applied)
        cur.execute("SELECT status, generation, last_completed_op_seq, base_commit, token_count FROM context_packs WHERE pack_id=%s", (pack,))
        status, gen, lastc, pbase, tok = cur.fetchone()
        check('pack FRESH generation=1 last_completed=1',
              (status, gen, lastc, pbase) == ('FRESH', 1, 1, 'INIT'), (status, gen, lastc, pbase))
        cur.execute("SELECT slice_id, stale, generation, content_hash FROM context_slices WHERE pack_id=%s ORDER BY seq", (pack,))
        rows = cur.fetchall()
        check('two fresh slices generation=1',
              [r[:3] for r in rows] == [('src_orders', False, 1), ('src_users', False, 1)]
              and rows[0][3] == result['slices'][0]['content_hash'], rows)
        cur.execute("SELECT slice_id, dep_uri, built_at_commit FROM slice_dependencies WHERE pack_id=%s ORDER BY slice_id", (pack,))
        deps = cur.fetchall()
        check('dependency rows written',
              deps == [('src_orders', 'src:orders', 'INIT'), ('src_users', 'src:users', 'INIT')], deps)
        cur.execute("SELECT trigger_kind, dirty_slices, rebuilt_slices, base_from, base_to FROM context_refresh_log WHERE pack_id=%s ORDER BY seq", (pack,))
        logs = cur.fetchall()
        check('refresh_log has one build row',
              len(logs) == 1 and logs[0][0] == 'build' and logs[0][1] == []
              and sorted(logs[0][2]) == ['src_orders', 'src_users']
              and (logs[0][3], logs[0][4]) == ('INIT', 'INIT'), logs)

        # --- replay: same msg_id, then direct apply of the same result
        cur.execute("SELECT apply_queue_result(%s, %s, %s, %s::jsonb)",
                    (QUEUE, msg_id, run, json.dumps(result)))
        replay1 = cur.fetchone()[0]
        check('same msg replay is harmless', replay1.get('replayed') is True, replay1)
        cur.execute("SELECT count(*) FROM context_slices WHERE pack_id=%s", (pack,))
        check('slice count unchanged after replay', cur.fetchone()[0] == 2)
        cur.execute("SELECT apply_ctx_result(%s, %s::jsonb)", (run, json.dumps(result)))
        replay2 = cur.fetchone()[0]
        check('direct apply replays the SUCCEEDED op',
              replay2.get('replayed') is True and replay2.get('ok') is True, replay2)
        cur.execute("SELECT count(*) FROM context_slices WHERE pack_id=%s", (pack,))
        check('slice count still 2 after direct replay', cur.fetchone()[0] == 2)

        # --- out of order: op_seq=2 result while last_completed_op_seq=0
        cur.execute("SELECT ctx_create_task(%s)", ('w4 ordering',))
        run2 = cur.fetchone()[0]
        cur.execute("SELECT ctx_ensure_pack(%s, 'default')", (run2,))
        ensured2 = cur.fetchone()[0]
        pack2 = ensured2['pack_id']
        rid2 = str(uuid.uuid4())
        cur.execute("INSERT INTO ctx_operations(request_id, pack_id, op_kind, op_seq, status, built_at_commit) VALUES(%s, %s, 'refresh', 2, 'QUEUED', 'INIT')", (rid2, pack2))
        forged = {'request_id': rid2, 'op_seq': 2, 'success': True, 'run_id': run2,
                  'worker_id': 'w4-hand', 'base_commit': 'INIT',
                  'token_count': 0, 'slices': []}
        try:
            cur.execute("SELECT apply_ctx_result(%s, %s::jsonb)", (run2, json.dumps(forged)))
            cur.fetchone()
            check('apply rejects out-of-order result', False)
        except Exception as exc:
            check('apply rejects out-of-order result', 'out of order' in str(exc).lower(), exc)

    c.close()
    print('[W4] all gates passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
