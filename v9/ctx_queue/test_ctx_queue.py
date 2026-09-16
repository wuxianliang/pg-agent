"""W3 gate: ctx_heavy queue overlay, plugin registration, and apply dispatch."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg2

from server import get_server
from v9.ctx_queue.setup_db import DB, main as setup_db


def check(label: str, cond: bool, detail: object = '') -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f": {detail}" if detail else ''))
    if not cond:
        raise AssertionError(f'{label}: {detail}')


def main() -> int:
    check('setup', setup_db() == 0)
    c = psycopg2.connect(get_server().get_uri(DB))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(
            "SELECT fn::text, queue_kind, consumer FROM plugin_bindings "
            "WHERE binding_type='queue_handler' AND queue_name='ctx_heavy_requests'")
        row = cur.fetchone()
        check('queue_handler binding registered', row is not None, row)
        check('binding fn is apply_ctx_result',
              row is not None and 'apply_ctx_result' in row[0], row)
        check('binding queue_kind is ctx_heavy',
              row is not None and row[1] == 'ctx_heavy', row)
        check('binding consumer is python_worker',
              row is not None and row[2] == 'python_worker', row)

        cur.execute("SELECT count(*) FROM pgmq.meta "
                    "WHERE queue_name IN ('ctx_heavy_requests','ctx_heavy_requests_dlq')")
        check('pgmq queues ctx_heavy_requests and _dlq exist', cur.fetchone()[0] == 2)

        # Dispatch chain: apply_queue_result must insert the marker row and then
        # hand (p_run_id, p_result) to apply_ctx_result, which rejects the
        # unknown request id. The aborted statement rolls the marker back.
        try:
            cur.execute("SELECT apply_queue_result('ctx_heavy_requests', 999999, "
                        "'nonexistent', '{\"request_id\":\"nonexistent\"}'::jsonb)")
            check('dispatch reaches apply_ctx_result', False, 'call unexpectedly succeeded')
        except Exception as exc:
            check('dispatch reaches apply_ctx_result',
                  'unknown ctx operation' in str(exc), exc)

        # Literally per spec: an empty result object is rejected by the handler's
        # first guard before the op lookup.
        try:
            cur.execute("SELECT apply_queue_result('ctx_heavy_requests', 999999, "
                        "'nonexistent', '{}'::jsonb)")
            check('empty result rejected by handler', False, 'call unexpectedly succeeded')
        except Exception as exc:
            check('empty result rejected by handler',
                  'ctx result missing request_id' in str(exc), exc)

        cur.execute("SELECT count(*) FROM processed_queue_messages "
                    "WHERE queue_name='ctx_heavy_requests' AND msg_id=999999")
        check('failed dispatch leaves no marker row', cur.fetchone()[0] == 0)
    c.close()
    print('[W3] all gates passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
