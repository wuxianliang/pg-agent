"""W9 integration: full ctx chain - build, staleness, gate, crash replay, retire."""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path
import psycopg2
ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))
from server import get_server
from v9.integration.setup_db import DB, main as setup_db
from v9.ctx_worker.worker import CtxWorker, WorkerCrash

QUEUE = 'ctx_heavy_requests'
REPO = 'default'
RESULTS: list[tuple[str, str]] = []


def check(label, cond, detail=''):
    mark = 'PASS' if cond else 'FAIL'
    RESULTS.append((label, mark))
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ''))
    if not cond:
        raise AssertionError(f'{label}: {detail}')


def main() -> int:
    check('setup', setup_db() == 0)
    uri = get_server().get_uri(DB)
    c = psycopg2.connect(uri)
    c.autocommit = True
    with c.cursor() as cur:
        def q(sql, args=()):
            cur.execute(sql, args)
            return cur.fetchone()

        def qa(sql, args=()):
            cur.execute(sql, args)
            return cur.fetchall()

        # Fixture tables + whitelisted ctx_sources for the pack build.
        cur.execute('CREATE TABLE ctx_fixture_orders(id int PRIMARY KEY, item text NOT NULL, qty int NOT NULL)')
        cur.execute('CREATE TABLE ctx_fixture_users(id int PRIMARY KEY, name text NOT NULL, role text NOT NULL)')
        cur.execute("INSERT INTO ctx_fixture_orders VALUES (1,'widget',100),(2,'gizmo',7)")
        cur.execute("INSERT INTO ctx_fixture_users VALUES (1,'ada','admin'),(2,'lin','dev')")
        cur.execute("INSERT INTO ctx_sources(source_id,repo_path,schema_name,table_name) VALUES"
                    " ('orders','default','public','ctx_fixture_orders'),"
                    " ('users','default','public','ctx_fixture_users')")

        print('[1] full chain: task -> ensure -> worker build -> gate fresh')
        run_id = q('SELECT ctx_create_task(%s)', ('v9 integration: track orders and users',))[0]
        check('ctx_create_task returns parked run', bool(run_id), run_id)
        ensure = q('SELECT ctx_ensure_pack(%s)', (run_id,))[0]
        check('ctx_ensure_pack enqueues build', ensure.get('success') is True, ensure)
        pack_id = ensure['pack_id']
        status, next_seq, base = q('SELECT status, next_op_seq, base_commit FROM context_packs WHERE pack_id=%s', (pack_id,))
        check('fresh pack BUILDING base INIT', status == 'BUILDING' and next_seq == 2 and base == 'INIT', (status, next_seq, base))

        worker = CtxWorker(uri, db=DB)
        res = worker.pump_once()
        check('worker build pump applied', res is not None, res)
        status, gen, base, last_seq, tokens = q(
            'SELECT status, generation, base_commit, last_completed_op_seq, token_count'
            ' FROM context_packs WHERE pack_id=%s', (pack_id,))
        check('pack FRESH generation 1 after build',
              status == 'FRESH' and gen == 1 and base == 'INIT' and last_seq == 1
              and tokens is not None and tokens > 0, (status, gen, base, last_seq, tokens))
        slices = qa('SELECT slice_id, seq, kind, stale FROM context_slices WHERE pack_id=%s ORDER BY seq', (pack_id,))
        check('two source slices built',
              [s[0] for s in slices] == ['src_orders', 'src_users']
              and all(s[2] == 'source_excerpt' and s[3] is False for s in slices), slices)
        deps = qa('SELECT slice_id, dep_uri FROM slice_dependencies WHERE pack_id=%s ORDER BY slice_id', (pack_id,))
        check('slice dependencies recorded',
              deps == [('src_orders', 'src:orders'), ('src_users', 'src:users')], deps)
        body, chash = q("SELECT body, content_hash FROM context_slices WHERE pack_id=%s AND slice_id='src_orders'", (pack_id,))
        check('slice body is fixture snapshot with md5 hash',
              json.loads(body) and chash == hashlib.md5(body.encode()).hexdigest(), chash)
        gate = q('SELECT ctx_gate(%s)', (run_id,))[0]
        check('gate fresh after build', gate.get('fresh') is True and gate.get('action') == 'none', gate)

        print('[2] source mutation -> on_commit -> gate sync_refresh -> worker pump -> gate fresh')
        users_hash_before = q("SELECT content_hash FROM context_slices WHERE pack_id=%s AND slice_id='src_users'", (pack_id,))[0]
        cur.execute('UPDATE ctx_fixture_orders SET qty=250 WHERE id=1')
        oc = q('SELECT ctx_on_commit(%s,%s,%s)', (REPO, 'c1', ['src:orders']))[0]
        check('on_commit marks exactly the orders slice',
              oc.get('success') is True and 'src_orders' in json.dumps(oc.get('marked_slices'))
              and pack_id in json.dumps(oc.get('affected_packs')), oc)
        status, = q('SELECT status FROM context_packs WHERE pack_id=%s', (pack_id,))
        check('pack STALE after commit', status == 'STALE', status)
        op = q('SELECT op_seq, op_kind, status FROM ctx_operations WHERE pack_id=%s ORDER BY op_seq DESC LIMIT 1', (pack_id,))
        check('refresh op auto-queued', op == (2, 'refresh', 'QUEUED'), op)
        gate = q('SELECT ctx_gate(%s)', (run_id,))[0]
        check('gate sync_refresh with dirty slice',
              gate.get('fresh') is False and gate.get('action') == 'sync_refresh'
              and 'src_orders' in json.dumps(gate.get('dirty_slices')), gate)

        res = worker.pump_once()
        check('worker refresh pump applied', res is not None, res)
        status, gen, base = q('SELECT status, generation, base_commit FROM context_packs WHERE pack_id=%s', (pack_id,))
        check('pack FRESH generation 2 at c1', status == 'FRESH' and gen == 2 and base == 'c1', (status, gen, base))
        body, stale = q("SELECT body, stale FROM context_slices WHERE pack_id=%s AND slice_id='src_orders'", (pack_id,))
        rows = json.loads(body)
        row1 = next(r for r in rows if r.get('id') == 1)
        check('orders slice carries updated data',
              stale is False and row1.get('qty') == 250 and not any(r.get('qty') == 100 for r in rows), row1)
        users_hash_after = q("SELECT content_hash FROM context_slices WHERE pack_id=%s AND slice_id='src_users'", (pack_id,))[0]
        check('untouched users slice unchanged', users_hash_after == users_hash_before, users_hash_after)
        gate = q('SELECT ctx_gate(%s)', (run_id,))[0]
        check('gate fresh after refresh', gate.get('fresh') is True and gate.get('action') == 'none', gate)

        print('[3] multi-source drift -> gate drift_delta')
        cur.execute('UPDATE ctx_fixture_orders SET qty=300 WHERE id=2')
        cur.execute("UPDATE ctx_fixture_users SET role='lead' WHERE id=2")
        oc = q('SELECT ctx_on_commit(%s,%s,%s)', (REPO, 'c2', ['src:orders', 'src:users']))[0]
        check('second commit marks both slices',
              oc.get('success') is True and 'src_users' in json.dumps(oc.get('marked_slices')), oc)
        gate_sync = q('SELECT ctx_gate(%s)', (run_id,))[0]
        check('default threshold 3 stays sync_refresh',
              gate_sync.get('action') == 'sync_refresh' and gate_sync.get('fresh') is False, gate_sync)
        gate_drift = q('SELECT ctx_gate(%s,%s)', (run_id, 1))[0]
        drift = gate_drift.get('drift') or []
        drift_text = json.dumps(drift)
        check('threshold 1 yields drift_delta',
              gate_drift.get('action') == 'drift_delta' and gate_drift.get('fresh') is False
              and len(drift) == 2 and 'c2' in drift_text
              and 'src:orders' in drift_text and 'src:users' in drift_text, gate_drift)

        print('[4] crash replay: crash_after_read=1, vt expiry, apply exactly once')
        queued = qa('SELECT msg_id FROM pgmq.q_ctx_heavy_requests')
        check('exactly one queued refresh message', len(queued) == 1, queued)
        crash_msg_id = queued[0][0]
        gen_before = q('SELECT generation FROM context_packs WHERE pack_id=%s', (pack_id,))[0]

        crash_worker = CtxWorker(uri, db=DB, vt=1, crash_after_read=1)
        crashed = False
        try:
            crash_worker.pump_once()
        except WorkerCrash:
            crashed = True
        check('crash worker raises WorkerCrash after read', crashed)
        op_status, = q('SELECT status FROM ctx_operations WHERE pack_id=%s AND op_seq=3', (pack_id,))
        check('op still QUEUED after crash (no apply, no archive)', op_status == 'QUEUED', op_status)
        time.sleep(2.0)  # let the crashing read's vt=1 expire so the same msg is readable again

        replay_worker = CtxWorker(uri, db=DB)
        res = replay_worker.pump_once()
        check('fresh worker replays the crashed message', res is not None, res)
        processed, = q('SELECT count(*) FROM processed_queue_messages WHERE queue_name=%s AND msg_id=%s', (QUEUE, crash_msg_id))
        check('crashed message applied exactly once', processed == 1, processed)
        total_processed, = q('SELECT count(*) FROM processed_queue_messages WHERE queue_name=%s', (QUEUE,))
        check('whole run applied exactly three messages', total_processed == 3, total_processed)
        n, distinct_n = q('SELECT count(*), count(DISTINCT slice_id) FROM context_slices WHERE pack_id=%s', (pack_id,))
        check('no duplicate slices after replay', n == 2 and distinct_n == 2, (n, distinct_n))
        status, gen, base = q('SELECT status, generation, base_commit FROM context_packs WHERE pack_id=%s', (pack_id,))
        check('generation advanced exactly once past crash',
              status == 'FRESH' and gen == gen_before + 1 and base == 'c2', (status, gen, base))
        body, = q("SELECT body FROM context_slices WHERE pack_id=%s AND slice_id='src_orders'", (pack_id,))
        check('replayed refresh carries latest data',
              any(r.get('qty') == 300 for r in json.loads(body)), body[:80])

        print('[5] retire -> ensure replayed(RETIRED) -> gate RETIRED')
        rp = q('SELECT ctx_retire_pack(%s)', (run_id,))[0]
        check('ctx_retire_pack succeeds', rp.get('success') is True, rp)
        status, = q('SELECT status FROM context_packs WHERE pack_id=%s', (pack_id,))
        check('pack RETIRED', status == 'RETIRED', status)
        replay = q('SELECT ctx_ensure_pack(%s)', (run_id,))[0]
        check('ensure after retire replays RETIRED pack',
              replay.get('success') is True and replay.get('replayed') is True
              and replay.get('status') == 'RETIRED' and replay.get('pack_id') == pack_id, replay)
        ops, left = q('SELECT (SELECT count(*) FROM ctx_operations WHERE pack_id=%s),'
                      ' (SELECT count(*) FROM pgmq.q_ctx_heavy_requests)', (pack_id,))
        check('replay enqueues nothing', ops == 3 and left == 0, (ops, left))
        gate = q('SELECT ctx_gate(%s)', (run_id,))[0]
        check('gate reports RETIRED pack',
              gate.get('success') is False and gate.get('Type') == 'CTX_PACK_RETIRED', gate)

    c.close()
    passed = sum(1 for _, mark in RESULTS if mark == 'PASS')
    print(f"[W9] all gates passed: build / staleness / gate / refresh / crash replay / retire")
    print(f"[PASS] W9 summary: {passed}/{len(RESULTS)} checks green")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
