"""W5 gate: precise staleness marking, no duplicate enqueue, unrelated-change no-op."""
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

        # --- head first so the pack builds from base c0
        cur.execute("SELECT ctx_on_commit('default', 'c0', ARRAY[]::text[])")
        head0 = cur.fetchone()[0]
        check('c0 head commit accepted',
              head0.get('success') is True and head0.get('commit') == 'c0'
              and head0.get('marked_slices') == [] and head0.get('affected_packs') == [], head0)

        cur.execute("SELECT ctx_create_task(%s)", ('w5 staleness gate',))
        run = cur.fetchone()[0]
        cur.execute("SELECT ctx_ensure_pack(%s, 'default')", (run,))
        ens = cur.fetchone()[0]
        check('ensure succeeds', ens.get('success') is True, ens)
        pack, rid1 = ens['pack_id'], ens['request_id']
        cur.execute("SELECT base_commit FROM context_packs WHERE pack_id=%s", (pack,))
        check('pack builds from base c0', cur.fetchone()[0] == 'c0')

        # --- build apply at base c0: two source slices
        result = {'request_id': rid1, 'op_seq': 1, 'success': True, 'run_id': run,
                  'worker_id': 'w5-hand', 'base_commit': 'c0', 'trigger_kind': 'build',
                  'token_count': 11,
                  'slices': [make_slice('src_orders', 1, 'src:orders', '{"rows":["o-v1"]}'),
                             make_slice('src_users', 2, 'src:users', '{"rows":["u-v1"]}')]}
        cur.execute("SELECT apply_ctx_result(%s, %s::jsonb)", (run, json.dumps(result)))
        applied = cur.fetchone()[0]
        check('build applied', applied.get('ok') is True, applied)
        cur.execute("SELECT status FROM context_packs WHERE pack_id=%s", (pack,))
        check('pack FRESH after build', cur.fetchone()[0] == 'FRESH')

        # --- c1 touches exactly src:orders
        cur.execute("SELECT ctx_on_commit('default', 'c1', ARRAY['src:orders'])")
        c1 = cur.fetchone()[0]
        check('c1 marks exactly one slice',
              c1.get('success') is True and c1.get('marked_slices') == [f'{pack}:src_orders']
              and c1.get('affected_packs') == [pack], c1)
        cur.execute("SELECT slice_id, stale FROM context_slices WHERE pack_id=%s ORDER BY slice_id", (pack,))
        rows = cur.fetchall()
        check('orders stale, users still clean',
              rows == [('src_orders', True), ('src_users', False)], rows)
        cur.execute("SELECT status FROM context_packs WHERE pack_id=%s", (pack,))
        check('pack STALE after c1', cur.fetchone()[0] == 'STALE')
        cur.execute("SELECT count(*) FROM context_commits WHERE repo_path='default' AND commit_id='c1'")
        check('c1 journaled in context_commits', cur.fetchone()[0] == 1)
        cur.execute("SELECT head_commit FROM repo_heads WHERE repo_path='default'")
        check('repo head is c1', cur.fetchone()[0] == 'c1')
        cur.execute("SELECT op_kind, op_seq, status FROM ctx_operations WHERE pack_id=%s ORDER BY op_seq", (pack,))
        ops = cur.fetchall()
        check('refresh op enqueued at seq 2',
              ops == [('build', 1, 'SUCCEEDED'), ('refresh', 2, 'QUEUED')], ops)
        cur.execute("SELECT built_at_commit FROM ctx_operations WHERE pack_id=%s AND op_seq=2", (pack,))
        check('refresh op built_at_commit is c1', cur.fetchone()[0] == 'c1')

        # --- c2 touches src:orders again while the refresh is queued
        cur.execute("SELECT ctx_on_commit('default', 'c2', ARRAY['src:orders'])")
        c2 = cur.fetchone()[0]
        check('c2 marks nothing new (already stale)',
              c2.get('marked_slices') == [] and c2.get('affected_packs') == [pack], c2)
        cur.execute("SELECT count(*) FROM ctx_operations WHERE pack_id=%s", (pack,))
        check('no duplicate op enqueued', cur.fetchone()[0] == 2)
        cur.execute("SELECT pending_refresh FROM context_packs WHERE pack_id=%s", (pack,))
        check('pending_refresh latched true', cur.fetchone()[0] is True)
        cur.execute("SELECT stale FROM context_slices WHERE pack_id=%s AND slice_id='src_orders'", (pack,))
        check('orders still stale, not double-marked', cur.fetchone()[0] is True)
        cur.execute("SELECT head_commit FROM repo_heads WHERE repo_path='default'")
        check('repo head advanced to c2', cur.fetchone()[0] == 'c2')

        # --- unrelated change is a no-op for this pack
        cur.execute("SELECT ctx_on_commit('default', 'c3', ARRAY['src:nothing'])")
        c3 = cur.fetchone()[0]
        check('unrelated commit touches nothing',
              c3.get('marked_slices') == [] and c3.get('affected_packs') == [], c3)
        cur.execute("SELECT slice_id, stale FROM context_slices WHERE pack_id=%s ORDER BY slice_id", (pack,))
        rows = cur.fetchall()
        check('slice staleness unchanged by unrelated commit',
              rows == [('src_orders', True), ('src_users', False)], rows)
        cur.execute("SELECT count(*) FROM ctx_operations WHERE pack_id=%s", (pack,))
        check('still exactly two ops', cur.fetchone()[0] == 2)
        cur.execute("SELECT pending_refresh FROM context_packs WHERE pack_id=%s", (pack,))
        check('pending_refresh unchanged by unrelated commit', cur.fetchone()[0] is True)

    c.close()
    print('[W5] all gates passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
