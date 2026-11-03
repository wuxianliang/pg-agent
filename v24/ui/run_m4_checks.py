#!/usr/bin/env python3
"""Run M4 checks against private PGDATA; never initialize/reset persistent state.

uv run python v24/ui/run_m4_checks.py --log-dir /tmp/v24-m4-checks
Use --only ui / s13 / backend / artifacts to reproduce a focused group.
All database connections use the fixture's local Unix socket; no provider is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
S13 = ('contracts', 'descriptor', 'pages', 'registry', 'renderers', 'results',
       'schema', 'tools', 'vectors', 'line_json', 'lifecycle', 'wiring', 'node')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-dir', type=Path, required=True)
    parser.add_argument('--only', choices=('ui', 's13', 'backend', 'artifacts'))
    args = parser.parse_args()
    logs = args.log_dir.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    checks = [('ui', 'v24/ui/test_ui_gate.py', [])]
    checks += [('s13', f'v24/s13/test_{name}.py', ['--node'] if name == 'node' else []) for name in S13]
    checks += [('backend', 'v24/ui/test_backend_regressions.py', []),
               ('artifacts', 'v24/ui/test_artifact_regressions.py', [])]
    if args.only:
        checks = [check for check in checks if check[0] == args.only]
    results = []
    with tempfile.TemporaryDirectory(prefix='v24-m4-checks-') as directory:
        private = Path(directory)
        bootstrap = private / 'bootstrap'
        bootstrap.mkdir()
        (bootstrap / 'sitecustomize.py').write_text(
            'import os\nfrom pathlib import Path\n'
            'if os.environ.get("V24_M4_CHECK_PGDATA"):\n'
            '    import server\n'
            '    server.PGDATA = Path(os.environ["V24_M4_CHECK_PGDATA"]).resolve()\n')
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('PG', 'DEEPSEEK_', 'OPENAI_', 'V24_'))}
        environment.update(PYTHONPATH=str(bootstrap) + os.pathsep + str(ROOT),
                           V24_M4_CHECK_PGDATA=str(private / 'pgdata'),
                           UV_NO_ENV_FILE='1', PYTHONDONTWRITEBYTECODE='1',
                           V24_UI_MODE='fake')
        for group, script, extra in checks:
            command = [sys.executable, script, *extra]
            log = logs / (Path(script).stem + '.log')
            with log.open('wb') as output:
                process = subprocess.run(command, cwd=ROOT, env=environment,
                                         stdout=output, stderr=subprocess.STDOUT)
            raw = log.read_bytes()
            lines = raw.decode('utf-8', errors='replace').splitlines()
            row = dict(command=command, reproduce_command=['uv', 'run', 'python', script, *extra], group=group,
                       exit=process.returncode, last_line=lines[-1] if lines else '',
                       log=str(log), sha256=hashlib.sha256(raw).hexdigest())
            results.append(row)
            (logs / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
            print(json.dumps(row), flush=True)
            if process.returncode != 0 or any('[SKIP]' in line for line in lines):
                print('[failed] M4 checks; stopped at nonzero/SKIP; see results.json', flush=True)
                return 1
    print(f'[passed] M4 private checks; commands={len(results)}; exits=0; skips=0; persistent_pgdata_untouched=true')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
