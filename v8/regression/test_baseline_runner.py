"""J0 runner self-tests: temporary fake subprocesses, no DB/provider access.
Not a 25th V8 product gate. Run: uv run python v8/regression/test_baseline_runner.py
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v8.regression import run_baseline as r
from v8.compat import p0c_report as p

COUNT = 0


def check(label, condition):
    global COUNT
    assert condition, label
    COUNT += 1
    print('[PASS] ' + label)


def rejects(label, fn):
    try:
        fn()
    except (ValueError, OSError, json.JSONDecodeError):
        check(label, True)
    else:
        check(label, False)


def fake_root(root, n=3):
    (root / 'v8/fake').mkdir(parents=True)
    for name in ('server.py', 'pyproject.toml', 'uv.lock'):
        (root / name).write_text('# fixture\n')
    entries = []
    for i in range(n):
        path = 'v8/fake/test_' + chr(97 + i) + '.py'
        (root / path).write_text('print("[PASS] temporary child")\n')
        entries.append(dict(gate_id='G' + str(i + 1), argv=['uv', 'run', 'python', path],
                            database_group='agent_v8_fake', required=True))
    (root / 'v8/README.md').write_text('\n'.join(
        ' '.join(e['argv']) + ' # ' + e['gate_id'] for e in entries))
    manifest = dict(schema_version=1, suite_id='v8-cumulative-keyless', entries=entries)
    path = root / 'v8/manifest.json'
    path.write_text(json.dumps(manifest))
    return manifest, path


def run_fixture(root, manifest, path, child=None, timeout=2):
    def default(argv, cwd, env, seconds, out, err):
        return r.run_child([sys.executable, argv[3]], cwd, env, seconds, out, err)
    with contextlib.redirect_stdout(io.StringIO()):
        return r.execute_suite(manifest, path, root, root / 'v8/compat/evidence/j0', timeout,
                               version_fn=lambda root: {'test_only': 'no DB'},
                               provenance_fn=lambda root: {'base_commit': 'test-only', 'dirty_paths': []},
                               child_fn=child or default)


def honest_report():
    matrix = dict(dispatch_interception='none', driver_switch='unsupported',
                  blocked=list(p.DISPATCH_REAL_ROWS) + [p.SWITCH_DB_ROW],
                  mandated_negative=[p.MANDATED_NEGATIVE])
    results = {s.subcase_id: 'passed' for s in p.CATALOG if s.implemented}
    results['c12-db-real-provider-protocol'] = 'not_run'
    report = p.build_report(results, matrix,
        external_blocked=frozenset(p.EXTERNAL_BLOCKED - {'blocked:real-provider-credentials'}),
        not_run_reasons={'c12-db-real-provider-protocol': 'not_requested'})
    return report | {'generated_at_utc': r.utc()}


def test_manifest():
    actual = r.load_manifest(r.MANIFEST)
    ids = [e['gate_id'] for e in actual['entries']]
    check('production exact 24 IDs/order + independent README inventory', ids == [
        'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7a', 'G7b', 'G7c', 'G8a', 'G8b',
        'G9a', 'G10', 'G11', 'G12', 'G13', 'G14', 'G9b', 'G16', 'G17', 'G15', 'G18', 'G19a', 'G19b'])
    groups = {e['gate_id']: e['database_group'] for e in actual['entries']}
    check('shared DB groups remain explicit', groups['G7a'] == groups['G7b'] == 'agent_v8_retry'
          and groups['G8a'] == groups['G8b'] == 'agent_v8_cancel'
          and groups['G9a'] == groups['G9b'] == 'agent_v8_stream')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        manifest, path = fake_root(root)
        r.load_manifest(path, root)
        mutations = [
            lambda m: m['entries'].append(m['entries'][0]),
            lambda m: m['entries'][1].update(argv=m['entries'][0]['argv']),
            lambda m: m['entries'][0]['argv'].append('--real-provider-smoke'),
            lambda m: m['entries'][0].update(argv=['sh', '-c', 'echo hi']),
            lambda m: m['entries'][0]['argv'].__setitem__(3, 'v8/../../escape.py'),
            lambda m: m['entries'][0].update(required=False),
            lambda m: m['entries'][0].update(database_group='wrong'),
            lambda m: m['entries'].pop(),
            lambda m: m.update(schema_version=99),
        ]
        for index, mutate in enumerate(mutations):
            m = json.loads(json.dumps(manifest))
            mutate(m)
            path.write_text(json.dumps(m))
            rejects(f'invalid manifest {index}', lambda: r.load_manifest(path, root))
        path.write_text(json.dumps(manifest))
        script = root / manifest['entries'][0]['argv'][3]
        script.unlink()
        script.symlink_to(root / 'server.py')
        rejects('symlink script refused', lambda: r.load_manifest(path, root))
        script.unlink()
        rejects('missing script refused', lambda: r.load_manifest(path, root))
    for argv in (['--resume', 'old.json'], ['--timeout-seconds', '0']):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                code = r.main(argv)
            except SystemExit as exc:
                code = exc.code
        check('CLI rejects resume/nonpositive timeout', code == 2)


def test_environment_and_sources():
    sentinel = 'j0-SENTINEL-NOT-A-REAL-SECRET'
    with patch.dict(os.environ, {k: sentinel for k in (
            'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_API_URI', 'UV_ENV_FILE')}):
        original = dict(os.environ)
        child = r.child_env()
        check('credentials/dotenv stripped, parent unchanged', os.environ == original
              and child['UV_NO_ENV_FILE'] == '1'
              and not any(k in child for k in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_API_URI', 'UV_ENV_FILE')))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            manifest, path = fake_root(root)
            script = root / manifest['entries'][0]['argv'][3]
            script.write_text('import os\nassert os.environ["UV_NO_ENV_FILE"] == "1"\n'
                'assert not any(k in os.environ for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENAI_API_URI", "UV_ENV_FILE"))\n'
                'print("Authorization: Bearer j0-SENTINEL-NOT-A-REAL-SECRET")\n'
                'print("api_key=j0-SENTINEL-NOT-A-REAL-SECRET postgres://user:pass@localhost/db /Users/private/home")\n')
            code, evidence = run_fixture(root, manifest, path)
            text = evidence.read_text()
            check('real child stripped; raw secrets/URI/home never archived', code == 0
                  and sentinel not in text and 'Bearer' not in text
                  and 'postgres://' not in text and '/Users/' not in text)
            snap = r.source_snapshot(root)
            sql = root / 'v8/fake/contract.sql'
            sql.write_text('select 1;')
            check('source snapshot detects new SQL', r.source_snapshot(root) != snap)
            before = r.source_snapshot(root)
            sql.write_text('select 2;')
            check('source snapshot detects SQL edits', r.source_snapshot(root) != before)
            sql.unlink()
            check('source snapshot detects deletion and restores original set', r.source_snapshot(root) == snap)
            artifact = root / 'v8/compat/evidence/j0/noise.json'
            artifact.write_text('not source')
            (root / 'v8/README.md').write_text('docs-only')
            check('evidence and docs excluded from source hash', r.source_snapshot(root) == snap)
    production = {f['path'] for f in r.source_snapshot()['files']}
    check('production snapshot includes dependency + SQL + runner/test inputs', {
        'uv.lock', 'pyproject.toml', 'server.py', 'v8/load.py', 'v8/compat/v8_compat.sql',
        'v8/compat/pinned_host_manifest.json', 'v8/regression/run_baseline.py',
        'v8/regression/test_baseline_runner.py', 'v8/regression/v8-gates.json'} <= production)


def test_serial_and_failures():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        manifest, path = fake_root(root)
        seen = []
        def ordered(argv, cwd, env, seconds, out, err):
            check('no previous test subprocess live', not (root / 'active').exists())
            seen.append(argv[3])
            script = root / argv[3]
            # Child confirms the same invariant, not just a mocked scheduler.
            old = script.read_text()
            script.write_text('from pathlib import Path\nimport time\n'
                'p=Path("active")\nf=p.open("x"); f.close()\ntime.sleep(.03)\np.unlink()\n' + old)
            try:
                return r.run_child([sys.executable, argv[3]], cwd, env, seconds, out, err)
            finally:
                script.write_text(old)
        code, evidence = run_fixture(root, manifest, path, ordered)
        record = json.loads(evidence.read_text())
        check('serial fresh all-zero eligible, one attempt per entry', code == 0 and record['eligible']
              and seen == [e['argv'][3] for e in manifest['entries']]
              and all(len(e['attempts']) == 1 for e in record['entries']))
        script = root / manifest['entries'][0]['argv'][3]
        script.write_text('print("[PASS] misleading count")\nraise SystemExit(1)\n')
        code, failed = run_fixture(root, manifest, path)
        rec = json.loads(failed.read_text())
        check('exit1 beats PASS count; later diagnostics run without retry', code == 1
              and rec['counts'] == {'passed': 2, 'failed': 1, 'not_run': 0}
              and rec['entries'][0]['attempts'][0]['pass_line_count'] == 1)
        script.write_text('import os,signal\nos.kill(os.getpid(),signal.SIGTERM)\n')
        code, signaled = run_fixture(root, manifest, path)
        rec = json.loads(signaled.read_text())
        check('signal retained and failed', code == 1 and rec['entries'][0]['attempts'][0]['signal'] == signal.SIGTERM)
        script.write_text('import time\ntime.sleep(30)\n')
        code, timed = run_fixture(root, manifest, path, timeout=1)
        rec = json.loads(timed.read_text())
        check('timeout kills/waits, later diagnostic safe', code == 1
              and rec['entries'][0]['attempts'][0]['reason'] == 'timeout'
              and rec['entries'][0]['attempts'][0]['cleanup_confirmed']
              and rec['counts']['passed'] == 2)
        check('failed/success artifacts immutable separate run IDs', len({evidence.name, failed.name, signaled.name, timed.name}) == 4
              and evidence.exists() and failed.exists())
        with r.runner_lock(root):
            rejects('second runner lock refused', lambda: run_fixture(root, manifest, path))
        def drift(argv, cwd, env, seconds, out, err):
            (root / 'v8/fake/drift.sql').write_text('select 42;')
            return r.run_child([sys.executable, '-c', 'print("[PASS] x")'], cwd, env, seconds, out, err)
        code, changed = run_fixture(root, manifest, path, drift)
        rec = json.loads(changed.read_text())
        check('all exits zero cannot override source drift', code == 1 and rec['source_drift'] and not rec['eligible'])
        # A damaged old checkpoint is never read as a resume input.
        failed.write_text('{broken')
        script.write_text('print("[PASS] fresh")\n')
        code, fresh = run_fixture(root, manifest, path)
        check('new run does not read corrupted/historical checkpoint', code == 0 and fresh != failed
              and failed.read_text() == '{broken')
        with patch.object(r.os, 'replace', side_effect=OSError('private-error')):
            rejects('atomic checkpoint failure never returns success', lambda: run_fixture(root, manifest, path))


def test_interrupt_and_process_tree():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        manifest, path = fake_root(root)
        script = root / manifest['entries'][0]['argv'][3]
        script.write_text('import os,signal,time\ntime.sleep(.1)\nos.kill(os.getppid(),signal.SIGINT)\ntime.sleep(30)\n')
        code, target = run_fixture(root, manifest, path)
        rec = json.loads(target.read_text())
        check('SIGINT checkpoints, stops later gates, returns 130', code == 130 and rec['interrupted']
              and rec['counts']['not_run'] == 2 and not rec['eligible']
              and rec['entries'][0]['attempts'][0]['cleanup_confirmed'])
        # Both leader and child must leave the process group before release.
        script.write_text('import subprocess,sys,signal,time\n'
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
            'def stop(*args):\n p.wait(); sys.exit(0)\n'
            'signal.signal(signal.SIGTERM,stop)\ntime.sleep(30)\n')
        result = r.run_child([sys.executable, str(script)], root, r.child_env(), 1,
                             root / 'out', root / 'err')
        check('timeout reaps entire process group including grandchild', result['reason'] == 'timeout'
              and result['cleanup_confirmed'])
        def unconfirmed(argv, cwd, env, seconds, out, err):
            result = r.run_child([sys.executable, '-c', 'pass'], cwd, env, seconds, out, err)
            return result | {'cleanup_confirmed': False, 'state': 'failed', 'reason': 'cleanup_unconfirmed'}
        code, target = run_fixture(root, manifest, path, unconfirmed)
        rec = json.loads(target.read_text())
        check('unconfirmed cleanup stops subsequent gates', code == 1 and rec['counts']['not_run'] == 2)


def test_g13_reports():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        path = root / 'report.json'
        start = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        check('missing G13 report unavailable', r.read_g13(path, start, end, '') == (None, 'missing'))
        path.write_text('{truncated')
        check('truncated/timeout G13 report unavailable', r.read_g13(path, start, end, '') == (None, 'invalid')
              and r.read_g13(path, start, end, 'timeout') == (None, 'timeout'))
        good = honest_report()
        path.write_text(json.dumps(good))
        check('full schema-v2 report round-trips unchanged', r.read_g13(path, start, end, '') == (good, ''))
        for bad in (good | {'secret': 'sentinel'}, good | {'report_schema_version': 99},
                    good | {'generated_at_utc': '2000-01-01T00:00:00+00:00'}):
            path.write_text(json.dumps(bad))
            check('foreign/stale/secret-bearing report refused', r.read_g13(path, start, end, '') == (None, 'invalid'))
        manifest, mp = fake_root(root)
        manifest['entries'][0]['gate_id'] = 'G13'
        def missing(argv, cwd, env, seconds, out, err):
            check('G13 report path unique private parent, not historical file', '--report-json' in argv
                  and not Path(argv[-1]).exists() and Path(argv[-1]).parent.stat().st_mode & 0o777 == 0o700)
            return r.run_child([sys.executable, '-c', 'raise SystemExit(1)'], cwd, env, seconds, out, err)
        code, target = run_fixture(root, manifest, mp, missing)
        rec = json.loads(target.read_text())
        check('G13 missing report is run failure not preflight; conclusions unavailable', code == 1
              and rec['g13_report'] is None and rec['g13_report_reason'] == 'missing'
              and set(rec['conclusions'].values()) == {'unavailable'})


def main():
    test_manifest()
    test_environment_and_sources()
    test_serial_and_failures()
    test_interrupt_and_process_tree()
    test_g13_reports()
    print(f'[J0 runner self-check] {COUNT} checks passed (not a product gate)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
