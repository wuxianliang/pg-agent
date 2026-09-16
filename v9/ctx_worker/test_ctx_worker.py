"""W8 gate: ctx_heavy worker — snapshot build, incremental refresh, DLQ paths.

ctx_worker has no setup_db.py (spec §1); the DB bootstrap is inlined here with
the same template (DB=agent_v9_ctx_worker, stage 'ctx_worker' -> all 24 files).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v9.load import load_stage, run_psql
from v9.ctx_worker.worker import CtxWorker, DLQ, QUEUE

DB = 'agent_v9_ctx_worker'


def setup_db() -> int:
    s = get_server()
    run_psql(s, 'postgres', f'DROP DATABASE IF EXISTS {DB} WITH (FORCE);')
    run_psql(s, 'postgres', f'CREATE DATABASE {DB};')
    run_psql(s, DB, 'CREATE EXTENSION IF NOT EXISTS vector;')
    load_stage(s, DB, 'ctx_worker')
    print('[ready]', DB)
    return 0


def check(label, cond, detail=''):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f': {detail}' if detail else ''))
    if not cond:
        raise AssertionError(f'{label}: {detail}')


def fixture_body(conn) -> str:
    """Serialize the fixture exactly the way the worker does."""
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM public.ctx_fixture_orders LIMIT 1000')
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return json.dumps(rows, default=str, ensure_ascii=False)


def main() -> int:
    check('setup', setup_db() == 0)
    s = get_server()
    uri = s.get_uri(DB)
    c = psycopg2.connect(uri)
    c.autocommit = True

    # -- fixture source + whitelist + parked run + pack ------------------------
    with c.cursor() as cur:
        cur.execute('CREATE TABLE public.ctx_fixture_orders (id int, item text, qty int)')
        cur.execute("INSERT INTO public.ctx_fixture_orders VALUES (1,'widget',4),(2,'gizmo',7)")
        cur.execute(
            "INSERT INTO ctx_sources(source_id, repo_path, schema_name, table_name, "
            "max_rows, enabled) VALUES ('orders','default','public','ctx_fixture_orders',1000,true)"
        )
        cur.execute('SELECT ctx_create_task(%s)', ('ctx worker gate',))
        run_id = cur.fetchone()[0]
        cur.execute('SELECT ctx_ensure_pack(%s, %s)', (run_id, 'default'))
        ensured = cur.fetchone()[0]
    check('ensure_pack succeeds', isinstance(ensured, dict) and ensured.get('success') is True, ensured)
    pack_id = ensured['pack_id']

    with c.cursor() as cur:
        cur.execute('SELECT op_seq, op_kind, status FROM ctx_operations WHERE pack_id=%s', (pack_id,))
        ops = cur.fetchall()
    check('build op queued as op_seq 1', ops == [(1, 'build', 'QUEUED')], ops)

    # -- worker build -----------------------------------------------------------
    w = CtxWorker(uri, db=DB)
    r1 = w.pump_once()
    check('worker build applies', r1 is not None and r1.get('ok') is True, r1)
    check('apply result reports pack/generation',
          r1 is not None and r1.get('pack_id') == pack_id and r1.get('generation') == 1, r1)

    expected_body = fixture_body(c)
    with c.cursor() as cur:
        cur.execute(
            'SELECT status, generation, base_commit, token_count, last_completed_op_seq '
            'FROM context_packs WHERE pack_id=%s', (pack_id,))
        pack = cur.fetchone()
        cur.execute(
            'SELECT slice_id, seq, kind, dep_uri, title, body, content_hash, stale '
            'FROM context_slices WHERE pack_id=%s', (pack_id,))
        slices = cur.fetchall()
        cur.execute(
            'SELECT slice_id, dep_uri, built_at_commit FROM slice_dependencies '
            'WHERE pack_id=%s', (pack_id,))
        deps = cur.fetchall()
    check('pack FRESH after build', pack[0] == 'FRESH', pack)
    check('generation 1 after build', pack[1] == 1, pack)
    check('base INIT after build', pack[2] == 'INIT', pack)
    check('last_completed_op_seq 1', pack[4] == 1, pack)
    check('token_count is body//4', pack[3] == len(expected_body) // 4,
          (pack[3], len(expected_body) // 4))
    check('one source slice built', len(slices) == 1, slices)
    sl = slices[0]
    check('slice body is fixture rows json', sl[5] == expected_body, sl[5][:120])
    check('content_hash is md5 of body',
          sl[6] == hashlib.md5(expected_body.encode('utf-8')).hexdigest(), sl[6])
    check('slice identity fields',
          sl[0] == 'src_orders' and sl[1] == 1 and sl[2] == 'source_excerpt'
          and sl[3] == 'src:orders' and sl[4] == 'public.ctx_fixture_orders'
          and sl[7] is False, sl[:5])
    check('slice dependency recorded', deps == [('src_orders', 'src:orders', 'INIT')], deps)

    # -- source change -> worker incremental refresh -----------------------------
    with c.cursor() as cur:
        cur.execute('UPDATE public.ctx_fixture_orders SET qty=9 WHERE id=2')
        cur.execute('SELECT ctx_on_commit(%s, %s, %s)', ('default', 'c1', ['src:orders']))
        committed = cur.fetchone()[0]
    check('on_commit succeeds', isinstance(committed, dict) and committed.get('success') is True, committed)
    with c.cursor() as cur:
        cur.execute("SELECT stale FROM context_slices WHERE pack_id=%s AND slice_id='src_orders'", (pack_id,))
        check('on_commit marks slice stale', cur.fetchone()[0] is True)
        cur.execute('SELECT op_kind, status FROM ctx_operations WHERE pack_id=%s ORDER BY op_seq', (pack_id,))
        ops_pre = cur.fetchall()
    check('refresh op auto-enqueued', ops_pre == [('build', 'SUCCEEDED'), ('refresh', 'QUEUED')], ops_pre)

    r2 = w.pump_once()
    check('worker refresh applies', r2 is not None and r2.get('ok') is True, r2)

    expected_body2 = fixture_body(c)
    with c.cursor() as cur:
        cur.execute(
            'SELECT status, generation, base_commit, last_completed_op_seq '
            'FROM context_packs WHERE pack_id=%s', (pack_id,))
        pack2 = cur.fetchone()
        cur.execute(
            'SELECT slice_id, seq, body, content_hash, stale '
            'FROM context_slices WHERE pack_id=%s', (pack_id,))
        slices2 = cur.fetchall()
        cur.execute(
            'SELECT dep_uri, built_at_commit FROM slice_dependencies WHERE pack_id=%s', (pack_id,))
        deps2 = cur.fetchall()
        cur.execute(
            'SELECT trigger_kind, rebuilt_slices, base_from, base_to '
            'FROM context_refresh_log WHERE pack_id=%s ORDER BY seq', (pack_id,))
        logs = cur.fetchall()
        cur.execute('SELECT status FROM ctx_operations WHERE pack_id=%s ORDER BY op_seq', (pack_id,))
        ops2 = [row[0] for row in cur.fetchall()]
    check('refresh advances generation to 2', pack2[1] == 2, pack2)
    check('refresh rebases to c1 and stays FRESH',
          pack2[2] == 'c1' and pack2[0] == 'FRESH' and pack2[3] == 2, pack2)
    check('refresh body tracks new data', slices2[0][2] == expected_body2, slices2[0][2][:120])
    check('refresh preserves original seq', slices2[0][1] == 1, slices2[0][:2])
    check('refresh hash is md5 of new body',
          slices2[0][3] == hashlib.md5(expected_body2.encode('utf-8')).hexdigest(), slices2[0][3])
    check('slice no longer stale', slices2[0][4] is False, slices2[0][4])
    check('dependency rebuilt at c1', deps2 == [('src:orders', 'c1')], deps2)
    check('both ops terminal', ops2 == ['SUCCEEDED', 'SUCCEEDED'], ops2)
    check('refresh log recorded',
          len(logs) == 2 and logs[1][0] == 'run_completed'
          and logs[1][1] == ['src_orders'] and logs[1][2] == 'INIT' and logs[1][3] == 'c1',
          logs)

    # -- poison message (missing request_id) -> DLQ -------------------------------
    with c.cursor() as cur:
        cur.execute('SELECT pgmq.send(%s, %s::jsonb)',
                    (QUEUE, json.dumps({'op_kind': 'build', 'pack_id': 'nope'})))
        cur.execute(f'SELECT count(*) FROM pgmq.q_{DLQ}')
        dlq_before = cur.fetchone()[0]
    r3 = w.pump_once()
    check('poison message dead-lettered',
          r3 is not None and r3.get('dead_lettered') is True, r3)
    with c.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM pgmq.q_{DLQ}')
        dlq_after = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM pgmq.q_{QUEUE}')
        queue_left = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ctx_operations WHERE status IN ('QUEUED','RUNNING')")
        dangling = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM ctx_operations')
        total_ops = cur.fetchone()[0]
    check('DLQ received poison', dlq_after == dlq_before + 1, (dlq_before, dlq_after))
    check('original queue archived empty', queue_left == 0, queue_left)
    check('no dangling ctx operations', dangling == 0 and total_ops == 2, (dangling, total_ops))

    # -- read_ct overrun -> DLQ -----------------------------------------------------
    with c.cursor() as cur:
        cur.execute('SELECT ctx_on_commit(%s, %s, %s)', ('default', 'c2', ['src:orders']))
        cur.fetchone()
        cur.execute("SELECT request_id FROM ctx_operations WHERE pack_id=%s AND status='QUEUED'", (pack_id,))
        rid = cur.fetchone()[0]
    for i in range(6):
        time.sleep(1.1)  # let vt=1 expire so the message becomes readable again
        with c.cursor() as cur:
            cur.execute('SELECT read_ct FROM pgmq.read(%s, 1, 1)', (QUEUE,))
            row = cur.fetchone()
        check(f'manual read {i + 1} sees message', row is not None and row[0] == i + 1, row)
    time.sleep(1.1)
    r4 = w.pump_once()
    check('read_ct overrun dead-letters',
          r4 is not None and r4.get('dead_lettered') is True, r4)
    with c.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM pgmq.q_{DLQ}')
        dlq_final = cur.fetchone()[0]
        cur.execute('SELECT status FROM ctx_operations WHERE request_id=%s', (rid,))
        op_status = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM pgmq.q_{QUEUE}')
        queue_final = cur.fetchone()[0]
    check('DLQ grew again', dlq_final == dlq_after + 1, (dlq_after, dlq_final))
    check('DLQ marks ctx operation', op_status == 'DLQ', op_status)
    check('queue empty after overrun', queue_final == 0, queue_final)

    w.close()
    c.close()
    print('[W8] all gates passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
