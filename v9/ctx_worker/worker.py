"""v9 ctx_heavy worker: poll PGMQ, snapshot ctx_sources, apply results.

v9-local (track E): self-contained — no v6 import anywhere; inherited SQL
(apply_queue_result dispatch, pgmq) is loaded path-read-only by v9/load.py.
Crash simulation raises WorkerCrash (not os._exit) so in-process tests keep
the "read but neither archived nor applied" semantics without dying.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from server import get_server

DB = 'agent_v9_ctx_worker'
QUEUE = 'ctx_heavy_requests'
DLQ = 'ctx_heavy_requests_dlq'
VT_SECONDS = 180
MAX_READ_CT = 5
IDENT_RE = r'^[a-z_][a-z0-9_]*$'
TERMINAL_OP_STATUSES = ('SUCCEEDED', 'FAILED', 'DLQ')
REQUIRED_PAYLOAD_FIELDS = (
    'request_id', 'pack_id', 'op_kind', 'op_seq', 'repo_path', 'task_run_id',
)


class WorkerCrash(RuntimeError):
    """Simulated crash between pgmq.read and apply: message is left queued."""


def _as_json(value) -> dict:
    """Coerce a psycopg2 jsonb/str/bytes/memoryview value into a dict."""
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8')
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    return value


class CtxWorker:
    """Poll ctx_heavy_requests, snapshot whitelisted sources into slices,
    and apply results via apply_queue_result in a single transaction."""

    def __init__(self, uri, *, db, worker_id='v9-ctx-1', vt=VT_SECONDS,
                 max_read_ct=MAX_READ_CT, poll=0.2, crash_after_read=0):
        self.uri = uri
        self.db = db
        self.worker_id = worker_id
        self.vt = vt
        self.max_read_ct = max_read_ct
        self.poll = poll
        self._crash_counter = crash_after_read
        self.poll_conn = psycopg2.connect(uri, cursor_factory=RealDictCursor)
        self.poll_conn.autocommit = True

    def close(self) -> None:
        try:
            self.poll_conn.close()
        except Exception:
            pass

    def read_one(self):
        """Read at most one message from ctx_heavy_requests; None when empty."""
        with self.poll_conn.cursor() as cur:
            cur.execute(
                'SELECT msg_id, read_ct, message FROM pgmq.read(%s, %s, 1)',
                (QUEUE, self.vt),
            )
            row = cur.fetchone()
        return dict(row) if row is not None else None

    def dead_letter(self, msg_id, payload, reason) -> dict:
        """Copy the message to the DLQ, archive it, and mark its op DLQ if open."""
        body = dict(payload) if isinstance(payload, dict) else {'payload': repr(payload)}
        body['dlq_reason'] = reason
        body['original_msg_id'] = msg_id
        request_id = body.get('request_id')
        with self.poll_conn.cursor() as cur:
            cur.execute(
                'SELECT pgmq.send(%s, %s::jsonb)',
                (DLQ, json.dumps(body, ensure_ascii=False, default=str)),
            )
            cur.execute('SELECT pgmq.archive(%s, %s)', (QUEUE, int(msg_id)))
            if request_id:
                cur.execute(
                    "UPDATE ctx_operations SET status='DLQ', error=%s::jsonb, "
                    "finished_at=now() WHERE request_id=%s "
                    "AND status IN ('QUEUED','RUNNING')",
                    (json.dumps({
                        'success': False,
                        'Type': 'CTX_QUEUE_DLQ',
                        'Problem': str(reason)[:500],
                        'Solution': 'inspect ctx_heavy_requests_dlq and re-enqueue after fixing',
                    }, ensure_ascii=False), request_id),
                )
        return {'dead_lettered': True, 'ok': False, 'msg_id': int(msg_id),
                'request_id': request_id, 'dlq_reason': reason}

    def _snapshot_source(self, cur, source) -> dict:
        """Snapshot one whitelisted source table -> {'slice', 'token_count'}.

        `source` is a ctx_sources row dict plus the caller-assigned 'seq'
        (build: 1..n in source_id order; refresh: the stale slice's original
        seq). Identifiers are regex-validated first, then composed with
        psycopg2.sql.Identifier; max_rows is a bound parameter.
        """
        source_id = str(source['source_id'])
        schema_name = str(source['schema_name'])
        table_name = str(source['table_name'])
        max_rows = int(source.get('max_rows') or 1000)
        seq = int(source['seq'])
        for ident in (schema_name, table_name):
            if not re.match(IDENT_RE, ident):
                raise ValueError(f'illegal source identifier: {schema_name}.{table_name}')
        cur.execute(
            sql.SQL('SELECT * FROM {}.{} LIMIT %s').format(
                sql.Identifier(schema_name), sql.Identifier(table_name)),
            (max_rows,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        body = json.dumps(rows, default=str, ensure_ascii=False)
        dep_uri = f'src:{source_id}'
        return {
            'slice': {
                'slice_id': f'src_{source_id}',
                'seq': seq,
                'kind': 'source_excerpt',
                'dep_uri': dep_uri,
                'title': f'{schema_name}.{table_name}',
                'body': body,
                'content_hash': hashlib.md5(body.encode('utf-8')).hexdigest(),
                'deps': [dep_uri],
            },
            'token_count': len(body) // 4,
        }

    def build_result(self, msg) -> dict:
        """Claim the queued op and snapshot sources into a result envelope."""
        payload = msg['payload']
        msg_id = int(msg['msg_id'])
        request_id = payload['request_id']
        pack_id = payload['pack_id']
        op_kind = payload['op_kind']
        op_seq = payload['op_seq']
        repo_path = payload['repo_path']
        task_run_id = payload['task_run_id']

        with self.poll_conn.cursor() as cur:
            cur.execute(
                'SELECT status FROM ctx_operations WHERE request_id=%s',
                (request_id,),
            )
            row = cur.fetchone()
            if row is None:
                return self.dead_letter(
                    msg_id, payload, f'unknown ctx operation: {request_id}')
            if row['status'] in TERMINAL_OP_STATUSES:
                # apply already happened elsewhere: archive directly, no re-apply
                return {'skip': True, 'request_id': request_id, 'status': row['status']}

            cur.execute(
                "UPDATE ctx_operations SET status='RUNNING', worker_id=%s, "
                "started_at=now() WHERE request_id=%s AND status='QUEUED'",
                (self.worker_id, request_id),
            )
            if cur.rowcount != 1:
                cur.execute(
                    'SELECT status FROM ctx_operations WHERE request_id=%s',
                    (request_id,),
                )
                again = cur.fetchone()
                current = again['status'] if again is not None else None
                if current == 'RUNNING' or current in TERMINAL_OP_STATUSES:
                    # a live worker owns the op, or it finished between the reads
                    return {'skip': True, 'request_id': request_id, 'status': current}
                return self.dead_letter(
                    msg_id, payload, f'ctx operation not claimable: status={current}')

            def current_head() -> str:
                cur.execute(
                    'SELECT head_commit FROM repo_heads WHERE repo_path=%s',
                    (repo_path,),
                )
                hrow = cur.fetchone()
                return hrow['head_commit'] if hrow is not None else 'INIT'

            v_built = current_head()  # baseline at claim time

            jobs = []  # ctx_sources rows + assigned 'seq'
            if op_kind == 'build':
                cur.execute(
                    'SELECT * FROM ctx_sources WHERE repo_path=%s AND enabled '
                    'ORDER BY source_id',
                    (repo_path,),
                )
                for seq, src in enumerate(cur.fetchall(), start=1):
                    jobs.append({**dict(src), 'seq': seq})
            elif op_kind == 'refresh':
                cur.execute(
                    'SELECT slice_id, seq, dep_uri FROM context_slices '
                    'WHERE pack_id=%s AND stale ORDER BY slice_id',
                    (pack_id,),
                )
                stale_rows = cur.fetchall()
                source_ids = sorted(
                    {str(r['dep_uri'])[4:] for r in stale_rows
                     if str(r['dep_uri']).startswith('src:')}
                )
                sources = {}
                if source_ids:
                    cur.execute(
                        'SELECT * FROM ctx_sources WHERE repo_path=%s AND enabled '
                        'AND source_id = ANY(%s) ORDER BY source_id',
                        (repo_path, source_ids),
                    )
                    sources = {r['source_id']: dict(r) for r in cur.fetchall()}
                seq_by_dep = {str(r['dep_uri']): int(r['seq']) for r in stale_rows}
                for sid in source_ids:
                    src = sources.get(sid)
                    if src is None:
                        continue  # source left the whitelist; keep the old slice
                    jobs.append({**src, 'seq': seq_by_dep[f'src:{sid}']})
                # no stale slices -> empty refresh: only advances base_commit
            else:
                return self.dead_letter(msg_id, payload, f'unknown op_kind: {op_kind}')

            # re-read head right before touching source tables: the build base
            v_built = current_head()
            slices = []
            token_count = 0
            for job in jobs:
                snap = self._snapshot_source(cur, job)
                slices.append(snap['slice'])
                token_count += snap['token_count']

        return {
            'request_id': request_id,
            'op_seq': op_seq,
            'success': True,
            'run_id': task_run_id,
            'worker_id': self.worker_id,
            'base_commit': v_built,
            'trigger_kind': 'build' if op_kind == 'build' else 'run_completed',
            'token_count': token_count,
            'slices': slices,
        }

    def process_one(self):
        """Read, validate, build, and apply one message; None when queue empty."""
        msg = self.read_one()
        if msg is None:
            return None
        if self._crash_counter > 0:
            self._crash_counter -= 1
            if self._crash_counter == 0:
                raise WorkerCrash('simulated crash after read')

        msg_id = int(msg['msg_id'])
        read_ct = int(msg.get('read_ct') or 0)
        try:
            payload = _as_json(msg['message'])
        except Exception as exc:
            return self.dead_letter(
                msg_id, {'payload_error': str(exc)}, 'malformed queue message')
        msg['payload'] = payload

        missing = [f for f in REQUIRED_PAYLOAD_FIELDS if payload.get(f) in (None, '')]
        if missing:
            return self.dead_letter(
                msg_id, payload, f"message missing fields: {','.join(missing)}")
        if read_ct > self.max_read_ct:
            return self.dead_letter(
                msg_id, payload,
                f'read_ct {read_ct} exceeded max {self.max_read_ct}')

        try:
            result = self.build_result(msg)
        except Exception as exc:
            return self.dead_letter(msg_id, payload, f'build failed: {exc}')
        if result.get('skip'):
            with self.poll_conn.cursor() as cur:
                cur.execute('SELECT pgmq.archive(%s, %s)', (QUEUE, msg_id))
            return {'skip': True, 'archived': True, 'msg_id': msg_id,
                    'request_id': payload['request_id'],
                    'status': result.get('status')}
        if result.get('dead_lettered'):
            return result

        run_id = payload['task_run_id']
        body = json.dumps(result, ensure_ascii=False, default=str)
        conn = psycopg2.connect(self.uri, cursor_factory=RealDictCursor)
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT apply_queue_result(%s, %s, %s, %s::jsonb) AS applied',
                    (QUEUE, msg_id, run_id, body),
                )
                applied = _as_json(cur.fetchone()['applied'])
                cur.execute('SELECT pgmq.archive(%s, %s)', (QUEUE, msg_id))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            return self.dead_letter(msg_id, payload, f'apply failed: {exc}')
        finally:
            conn.close()
        applied['msg_id'] = msg_id
        applied['run_id'] = run_id
        return applied

    def pump_once(self):
        """Process exactly one message; returns its result or None."""
        return self.process_one()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',
                        default=os.environ.get('PG_AGENT_DB') or 'agent_v9_integration')
    parser.add_argument('--worker-id',
                        default=os.environ.get('PG_AGENT_WORKER_ID') or 'v9-ctx-1')
    parser.add_argument('--poll', type=float, default=0.2)
    args = parser.parse_args()
    server = get_server()
    worker = CtxWorker(server.get_uri(args.db), db=args.db,
                       worker_id=args.worker_id, poll=args.poll)
    print(f"[worker] queue={QUEUE} db={args.db} worker_id={args.worker_id} "
          f"vt={worker.vt} max_read_ct={worker.max_read_ct}", flush=True)
    try:
        while True:
            try:
                result = worker.pump_once()
            except WorkerCrash:
                raise  # simulated crashes must surface; the loop never eats them
            except Exception as exc:
                print(f'[worker] ERROR: {exc}', flush=True)
                time.sleep(1)
                continue
            if result is None:
                time.sleep(args.poll)
                continue
            print(f"[worker] request_id={result.get('request_id')} "
                  f"ok={result.get('ok')} skip={result.get('skip', False)} "
                  f"dlq={result.get('dead_lettered', False)}", flush=True)
    finally:
        worker.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main() or 0)
