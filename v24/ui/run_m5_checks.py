#!/usr/bin/env python3
"""Private M5 snapshot/completion runner; no provider and no PG socket.

Completion mode runs the current offline gates first (real entry, UI gate,
audit contracts, backend regressions, full M4 sweep), records each exit code,
log hash and source map, and refuses to run the audit if any gate fails or
changes a source file.  The resulting receipt is the current-check receipt;
snapshot mode only runs the read-only audit.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CURRENT_SOURCES = (
    'v24/ui/app.py', 'v24/ui/catalog.py', 'v24/ui/control.py',
    'v24/ui/real.py', 'v24/ui/provider.py', 'v24/ui/test_real_entry.py',
    'v24/ui/audit_m5.py', 'v24/ui/run_m5_checks.py', 'v24/ui/test_audit_m5.py',
    'v24/ui/sessions.py', 'v24/ui/test_backend_regressions.py',
    'v24/ui/test_ui_gate.py', 'v24/ui/skills/surgical-edit/SKILL.md',
)
GATES = (
    ('real_entry', ('v24/ui/test_real_entry.py',)),
    ('ui_gate', ('v24/ui/test_ui_gate.py',)),
    ('audit_contracts', ('v24/ui/test_audit_m5.py',)),
    ('backend', ('v24/ui/test_backend_regressions.py',)),
)


def current_source_map():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in CURRENT_SOURCES if (ROOT / p).is_file()}


def runtime_source_map():
    """Full gate-covered source map; tests/audits are included deliberately."""
    paths = [ROOT / 'v24/load.py', ROOT / 'v24/s1/setup_db.py']
    for folder, pattern in (('host', '*.py'), ('ui', '*.py'), ('ui/plugins', '*.py'),
                            ('ui/skills', '*/SKILL.md'), ('sql', '*.sql')):
        paths.extend((ROOT / 'v24' / folder).glob(pattern))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths)) if path.is_file()}


def gate_env():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('PG', 'V24_')) or key in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
            env.pop(key, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env

def run_gate(name, argv, directory):
    before = runtime_source_map()
    log = directory / (name + '.log')
    result = subprocess.run([sys.executable, *map(str, argv)], cwd=ROOT,
                            env=gate_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_bytes(result.stdout)
    log.chmod(0o600)
    after = runtime_source_map()
    lines = result.stdout.decode(errors='replace').splitlines()
    return {'name': name, 'argv': [sys.executable, *map(str, argv)],
            'exit': result.returncode, 'log': str(log),
            'log_sha256': hashlib.sha256(result.stdout).hexdigest(),
            'last_line': lines[-1] if lines else '[no output]',
            'source_before': before, 'source_after': after,
            'source_unchanged': before == after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--completion', action='store_true')
    args = parser.parse_args()
    mode = 'completion' if args.completion else 'snapshot'
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = ROOT / 'prompt-exports/v24-m5-evidence' / ('wi3-checks-' + stamp + '-' + mode)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    script = ROOT / 'v24/ui/audit_m5.py'
    before = hashlib.sha256(script.read_bytes()).hexdigest()
    current = current_source_map()
    runtime_current = runtime_source_map()
    sources = directory / 'current-sources.json'
    sources.write_text(json.dumps({'files_sha256': current}, indent=2, sort_keys=True) + '\n')
    sources.chmod(0o600)
    gates = []
    if mode == 'completion':
        m4_dir = directory / 'm4-gates'
        for name, argv in GATES:
            gates.append(run_gate(name, argv, directory))
        gates.append(run_gate('m4', ('v24/ui/run_m4_checks.py', '--log-dir', m4_dir), directory))
    gates_ok = bool(gates) and all(
        row['exit'] == 0 and row['source_unchanged'] and not any(
            row['source_after'].get(p) != h for p, h in row['source_before'].items())
        for row in gates) and runtime_source_map() == runtime_current
    gates_path = directory / 'gates.json'
    if mode == 'completion':
        gates_doc = {'schema': 'm5-gates-v1',
                     'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'gates': gates, 'gates_ok': gates_ok,
                     'source_map': runtime_current, 'current_sources': current}
        gates_path.write_text(json.dumps(gates_doc, indent=2, sort_keys=True) + '\n')
        gates_path.chmod(0o600)
    gates_sha256 = hashlib.sha256(gates_path.read_bytes()).hexdigest() if gates_path.is_file() else None
    if mode == 'completion' and not gates_ok:
        path = directory / ('wi3-runner-' + mode + '-receipt.json')
        receipt = {'mode': mode, 'milestone_acceptance': False,
                   'exit': 1, 'last_line': '[failed] current gates; audit skipped',
                   'gates': gates, 'gates_ok': False,
                   'gates_path': str(gates_path), 'gates_sha256': gates_sha256,
                   'current_sources_sha256': hashlib.sha256(sources.read_bytes()).hexdigest(),
                   'runtime_gates_rerun': True, 'real_provider_calls': 0,
                   'audit_skipped': 'current gates failed'}
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        path.chmod(0o600)
        print('receipt=' + str(path))
        print('[failed] current gates; audit skipped')
        return 1
    command = [sys.executable, str(script), '--' + mode, '--output', str(directory / ('wi3-audit-' + mode + '.json'))]
    # Explicit minimal env; no provider values or PG* are read or forwarded.
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = directory / ('wi3-runner-' + mode + '.log')
    log.write_bytes(result.stdout)
    log.chmod(0o600)
    lines = result.stdout.decode(errors='replace').splitlines()
    last_line = lines[-1] if lines else '[no output]'
    source_unchanged = before == hashlib.sha256(script.read_bytes()).hexdigest()
    accepted = (mode == 'completion' and result.returncode == 0 and source_unchanged
                and gates_ok)
    receipt = {'mode': mode, 'milestone_acceptance': accepted, 'command': command,
               'exit': result.returncode, 'last_line': last_line,
               'log': str(log), 'log_sha256': hashlib.sha256(result.stdout).hexdigest(),
               'audit_source_sha256': before,
               'runner_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'current_sources_sha256': hashlib.sha256(sources.read_bytes()).hexdigest(),
               'source_unchanged': source_unchanged,
               'gates': gates, 'gates_ok': gates_ok,
               'gates_path': str(gates_path), 'gates_sha256': gates_sha256,
               'runtime_gates_rerun': bool(gates), 'real_provider_calls': 0}
    path = directory / ('wi3-runner-' + mode + '-receipt.json')
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    path.chmod(0o600)
    print('receipt=' + str(path))
    print(receipt['last_line'])
    return result.returncode if source_unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
