"""V8-only serial keyless runner. Rebuilds test databases; never resumes.

Raw logs stay in a private temporary directory, not evidence. The lock only
coordinates cooperating runners: do NOT run manual gates concurrently.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / 'v8/regression/v8-gates.json'
EVIDENCE = ROOT / 'v8/compat/evidence/j0'
CONCLUSIONS = ('declared_support_surface_conformant', 'minimal_dual_loop_passed',
               'full_target_achieved')


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8',
                                         delete=False) as fh:
            name = fh.name
            json.dump(value, fh, ensure_ascii=False, indent=2)
            fh.write('\n')
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def child_env():
    env = os.environ.copy()
    for key in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_API_URI', 'UV_ENV_FILE'):
        env.pop(key, None)
    env['UV_NO_ENV_FILE'] = '1'
    return env


def local_path(root, relative):
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or '.claude' in p.parts:
        raise ValueError('non-local path')
    target = root / p
    if target.resolve() != target.absolute() or not target.is_file():
        raise ValueError('missing or symlinked path')
    return target


def load_manifest(path, root=ROOT):
    local_path(root, str(path.relative_to(root)))
    m = json.loads(path.read_text())
    if m.get('schema_version') != 1 or m.get('suite_id') != 'v8-cumulative-keyless':
        raise ValueError('manifest version')
    entries = m.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('empty manifest')
    ids, scripts = set(), set()
    for e in entries:
        argv = e.get('argv')
        if (not isinstance(argv, list) or len(argv) != 4
                or argv[:3] != ['uv', 'run', 'python']
                or not isinstance(argv[3], str)
                or not re.fullmatch(r'v8/[a-z]+/test_[a-z_]+\.py', argv[3])):
            raise ValueError('only keyless V8 gate argv allowed')
        local_path(root, argv[3])
        gate = e.get('gate_id')
        if not isinstance(gate, str) or not re.fullmatch(r'G\d+[abc]?', gate):
            raise ValueError('gate id')
        if gate in ids or argv[3] in scripts or e.get('required') is not True:
            raise ValueError('duplicate or non-required gate')
        stage = argv[3].split('/')[1]
        if e.get('database_group') != (None if stage == 'canonical' else 'agent_v8_' + stage):
            raise ValueError('database group mismatch')
        if (gate == 'G13') != (argv[3] == 'v8/compat/test_compat.py'):
            raise ValueError('G13 identity mismatch')
        ids.add(gate)
        scripts.add(argv[3])
    # The checked-in README is an independent inventory: a subset manifest
    # must not certify a cumulative run. Counts are not hard-coded here.
    expected = re.findall(r'^uv run python (v8/\S+\.py)\s+# (G\w+)',
                          (root / 'v8/README.md').read_text(), re.M)
    if [(e['argv'][3], e['gate_id']) for e in entries] != expected:
        raise ValueError('manifest/README inventory mismatch')
    return m


def source_snapshot(root=ROOT):
    paths = {root / p for p in ('server.py', 'pyproject.toml', 'uv.lock')}
    for path in (root / 'v8').rglob('*'):
        rel = path.relative_to(root)
        if any(part in ('evidence', '__pycache__', '.venv', '.git', '.claude') for part in rel.parts):
            continue
        if path.is_file() and path.suffix in ('.py', '.sql', '.json'):
            paths.add(path)
    files = []
    for path in sorted(paths):
        local_path(root, str(path.relative_to(root)))
        files.append({'path': path.relative_to(root).as_posix(), 'sha256': sha(path)})
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'files': files, 'digest': digest}


@contextlib.contextmanager
def runner_lock(root=ROOT):
    directory = root / '.pgdata'
    directory.mkdir(exist_ok=True)
    with (directory / 'v8-baseline.lock').open('a') as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another baseline runner holds the lock') from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_group(proc):
    # Always target the whole session, including children whose leader exited.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            proc.poll()  # reap leader before testing group existence
            if not group_alive(proc.pid):
                proc.wait()
                return
            time.sleep(.03)
    raise RuntimeError('process group termination unconfirmed')


def run_child(argv, root, env, timeout, out, err):
    started = time.monotonic()
    proc = None
    reason, interrupted, safe = '', False, True
    try:
        with out.open('wb') as stdout, err.open('wb') as stderr:
            proc = subprocess.Popen(argv, cwd=root, env=env, stdout=stdout,
                                    stderr=stderr, start_new_session=True)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                reason = 'timeout'
            except KeyboardInterrupt:
                reason, interrupted = 'execution_interrupted', True
            finally:
                if group_alive(proc.pid):
                    if not reason:
                        reason = 'descendants_remaining'
                    # A second SIGINT must not bypass cleanup and release lock.
                    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
                    try:
                        stop_group(proc)
                    except RuntimeError:
                        safe = False
                    finally:
                        signal.signal(signal.SIGINT, old)
    except OSError:
        reason = 'launch_error'
    code = proc.returncode if proc else None
    passes = 0
    if out.exists():
        with out.open('rb') as fh:
            passes = sum(1 for line in fh if line.startswith(b'[PASS]'))
    return dict(exit_code=code, signal=-code if code is not None and code < 0 else None,
                state='passed' if code == 0 and not reason else 'failed',
                reason=reason or ('' if code == 0 else 'nonzero_exit'),
                interrupted=interrupted, cleanup_confirmed=safe,
                duration_seconds=round(time.monotonic() - started, 3),
                stdout_sha256=sha(out) if out.exists() else None,
                stderr_sha256=sha(err) if err.exists() else None, pass_line_count=passes)


def read_g13(path, started, ended, reason):
    if reason == 'timeout':
        return None, 'timeout'
    if not path.exists():
        return None, 'missing'
    try:
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            raise ValueError('report file')
        data = json.loads(path.read_text())
        if data['report_schema_version'] != 2:
            raise ValueError('schema')
        stamp = datetime.fromisoformat(data['generated_at_utc'])
        if not datetime.fromisoformat(started) <= stamp <= datetime.fromisoformat(ended):
            raise ValueError('stale report')
        # Accept the full report only if reproducible from its safe facts and
        # the current source catalog. Unknown/secret fields cannot enter JSON.
        from v8.compat import p0c_report as p
        results = {r['subcase']: r['state'] for r in data['rows']
                   if r['state'] != 'blocked' and p.BY_ID[r['subcase']].implemented}
        reasons = {r['subcase']: r['not_run_reason'] for r in data['rows'] if r['state'] == 'not_run'}
        m = data['capability_matrix']
        if (set(m) != {'blocked', 'mandated_negative', 'dispatch_interception', 'driver_switch'}
                or m['dispatch_interception'] not in ('none', 'after_io_only', 'sync_before_io')
                or m['driver_switch'] not in ('supported', 'unsupported')):
            raise ValueError('matrix')
        expected = set(p.DISPATCH_REAL_ROWS) if m['dispatch_interception'] != 'sync_before_io' else set()
        if m['driver_switch'] == 'unsupported':
            expected.add(p.SWITCH_DB_ROW)
        if set(m['blocked']) != expected or m['mandated_negative'] != (
                [p.MANDATED_NEGATIVE] if m['driver_switch'] == 'unsupported' else []):
            raise ValueError('matrix rows')
        rebuilt = p.build_report(results, m, not_run_reasons=reasons,
                                 external_blocked=frozenset(data['external_blocked']))
        rebuilt['generated_at_utc'] = data['generated_at_utc']
        if rebuilt != data:
            raise ValueError('report mismatch')
        return data, ''
    except (ValueError, KeyError, TypeError, OSError, AttributeError):
        return None, 'invalid'
    except Exception:
        return None, 'invalid'


def versions(root=ROOT):
    import psycopg2
    from server import get_server
    # Query version only. Never serialize URI or startup output.
    with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        conn = psycopg2.connect(get_server().get_uri('postgres'))
        try:
            with conn.cursor() as cur:
                cur.execute('SHOW server_version')
                pg = cur.fetchone()[0]
        finally:
            conn.close()
    uv = subprocess.check_output(['uv', '--version'], cwd=root, env=child_env(), text=True).strip()
    return dict(python=sys.version.split()[0], uv=uv, postgres=pg,
                pgembed=importlib.metadata.version('pgembed'))


def provenance(root):
    base = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    paths = subprocess.check_output(['git', 'ls-files', '--modified', '--others', '--exclude-standard', '-z'], cwd=root)
    # Paths only, never file contents. Omit nonportable/control-character paths.
    dirty = sorted({p.decode('utf-8') for p in paths.split(b'\0') if p
                    and re.fullmatch(rb'[A-Za-z0-9_. /-]+', p)})
    return {'base_commit': base, 'dirty_paths': dirty}


def execute_suite(manifest, manifest_path, root, output, timeout, *,
                  version_fn=versions, provenance_fn=provenance, child_fn=run_child):
    """Dependency injection is for self-tests only; CLI has no arbitrary argv seam."""
    with runner_lock(root):
        snapshot = source_snapshot(root)
        output.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
        target = output / (run_id + '.json')
        # mkdtemp is mode 0700; raw logs intentionally remain outside the repo.
        raw = Path(tempfile.mkdtemp(prefix='v8-baseline-' + run_id + '-'))
        record = dict(schema_version=1, run_id=run_id, started_at_utc=utc(),
                      ended_at_utc=None, fresh=True, completed=False, interrupted=False,
                      eligible=False, rebuilds_test_databases=True,
                      manifest_path=str(manifest_path.relative_to(root)),
                      manifest_sha256=sha(manifest_path), source_snapshot=snapshot,
                      source_snapshot_digest=snapshot['digest'], source_drift=None,
                      versions=version_fn(root), **provenance_fn(root),
                      g13_report=None, g13_report_reason='not_run',
                      conclusions={k: 'unavailable' for k in CONCLUSIONS},
                      entries=[dict(e, state='not_run', reason='execution_interrupted',
                                    attempts=[], started_at_utc=None, ended_at_utc=None)
                               for e in manifest['entries']])
        atomic_json(target, record)
        start = time.monotonic()
        try:
            for index, entry in enumerate(record['entries']):
                entry.update(state='running', reason='', started_at_utc=utc())
                argv = list(entry['argv'])
                report_path = raw / 'g13-report.json'
                if entry['gate_id'] == 'G13':
                    argv += ['--report-json', str(report_path)]
                # Portable exact template, with explicit private-root placeholder.
                # Absolute home/tmp paths are never archived.
                entry['executed_argv'] = [a.replace(str(raw), '<private-run-dir>') for a in argv]
                atomic_json(target, record)
                result = child_fn(argv, root, child_env(), timeout,
                                  raw / f'{index}.stdout', raw / f'{index}.stderr')
                entry['ended_at_utc'] = utc()
                entry['attempts'].append(result)
                entry.update(state=result['state'], reason=result['reason'])
                if entry['gate_id'] == 'G13':
                    report, why = read_g13(report_path, entry['started_at_utc'],
                                           entry['ended_at_utc'], result['reason'])
                    record.update(g13_report=report, g13_report_reason=why)
                    if report is not None:
                        record['conclusions'] = report['conclusions']
                    elif entry['state'] == 'passed':
                        entry.update(state='failed', reason='g13_report_' + why)
                if result['interrupted']:
                    record['interrupted'] = True
                atomic_json(target, record)
                print(f"{entry['gate_id']}: {entry['state']} (exit={result['exit_code']})", flush=True)
                if record['interrupted'] or not result['cleanup_confirmed']:
                    break
            else:
                record['completed'] = True
        except KeyboardInterrupt:
            record['interrupted'] = True
        except Exception:
            record['runner_error'] = 'execution_error'  # no exception text/log leak
        finally:
            for entry in record['entries']:
                if entry['state'] == 'running':
                    entry.update(state='failed', reason='runner_interrupted')
            record['ended_at_utc'] = utc()
            record['duration_seconds'] = round(time.monotonic() - start, 3)
            try:
                end = source_snapshot(root)
                record['end_source_snapshot_digest'] = end['digest']
                record['source_drift'] = (snapshot != end or sha(manifest_path) != record['manifest_sha256'])
            except Exception:
                record['source_drift'] = True
            record['counts'] = {s: sum(e['state'] == s for e in record['entries'])
                                for s in ('passed', 'failed', 'not_run')}
            record['eligible'] = (record['completed'] and not record['interrupted']
                                  and not record['source_drift'] and not record.get('runner_error')
                                  and all(e['state'] == 'passed' for e in record['entries']))
            atomic_json(target, record)
        print('evidence: ' + str(target.relative_to(root)), flush=True)
        return (130 if record['interrupted'] else 0 if record['eligible'] else 1), target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--timeout-seconds', type=int, default=240)
    args = parser.parse_args(argv)
    try:
        if args.timeout_seconds <= 0:
            raise ValueError('positive timeout required')
        # Reject invocation from another worktree or relocated/symlinked root.
        top = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, text=True).strip()
        gitdir = subprocess.check_output(['git', 'rev-parse', '--git-dir'], cwd=ROOT, text=True).strip()
        if Path(top).resolve() != ROOT or gitdir != '.git':
            raise ValueError('main checkout required')
        path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
        manifest = load_manifest(path)
    except (ValueError, OSError, TypeError, AttributeError):
        print('baseline preflight/input error (details omitted)', file=sys.stderr)
        return 2
    try:
        return execute_suite(manifest, path, ROOT, EVIDENCE, args.timeout_seconds)[0]
    except ValueError:
        print('baseline lock/provenance precondition failed', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception:
        # Failed persistence/execution cannot be reported as invalid CLI input.
        print('baseline execution/evidence failure (details omitted)', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
