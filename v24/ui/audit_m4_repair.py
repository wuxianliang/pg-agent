#!/usr/bin/env python3
"""Read-only precommit M4 repair audit against the user's SHA256 baseline.

Only valid for the uncommitted f4b95d4 repair tree with an empty index;
this is not a generic postcommit audit.

uv run python v24/ui/audit_m4_repair.py --baseline /tmp/v24-m4-review-fix-baseline-20261103.json --output /tmp/v24-m4-audit.json
The JSON output must be outside the repository and cannot replace the baseline.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'branch': 'v24/ui-chainlit',
    'head': 'f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35',
    'main': '1143dce6da0572bccab083da9a6be0175210b062',
}
BASELINE_SHA256 = 'c4a67b0bbb2be0117c5a6932d8145656cfd2b98b7037148b0b520ea5aacc4722'
ALLOWED_TRACKED = frozenset({
    'docs/reviews/v24-ui-conformance-matrix-2026-11-01.md',
    'docs/reviews/v24-ui-deviation-ledger-2026-11-01.md',
    'v24/ui/README.md',
    'v24/ui/app.py',
    'v24/ui/plugins/pi_tools.py',
    'v24/ui/plugins/rp_tools.py',
    'v24/ui/skills/repo-recon/SKILL.md',
    'v24/ui/skills/surgical-edit/SKILL.md',
    'v24/ui/test_ui_gate.py',
})
ALLOWED_NEW = frozenset({
    'docs/reviews/v24-ui-m4-review-fixes-2026-11-03.md',
    'v24/ui/audit_m4_repair.py',
    'v24/ui/run_m4_checks.py',
    'v24/ui/test_artifact_regressions.py',
    'v24/ui/test_backend_regressions.py',
})


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*arguments):
    return subprocess.run(
        ['git', *arguments], cwd=ROOT, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}).stdout


def paths(raw):
    return {os.fsdecode(value) for value in raw.split(b'\0') if value}


def file_digest(relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('baseline contains a non-relative path')
    target = ROOT / path
    return sha256(target.read_bytes()) if target.is_file() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline_path, output_path = args.baseline.resolve(), args.output.resolve()
    if output_path == baseline_path or output_path.is_relative_to(ROOT):
        parser.error('--output must be outside the repository and distinct from --baseline')
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    require(sha256(baseline_bytes) == BASELINE_SHA256, 'baseline SHA256 differs')
    for key, expected in EXPECTED.items():
        require(baseline.get(key) == expected, 'baseline ' + key + ' differs')
    require(len(baseline['tracked']) == 1451, 'baseline tracked count differs')
    require(len(baseline['untracked']) == 52, 'baseline original-untracked count differs')
    identity = {
        'branch': git('branch', '--show-current').decode().strip(),
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'main': git('rev-parse', 'refs/heads/main').decode().strip(),
    }
    require(identity == EXPECTED, 'branch/HEAD/main changed')
    staged = sorted(paths(git('diff', '--cached', '--name-only', '-z')))
    require(not staged, 'index is not empty')
    tracked = paths(git('ls-files', '-z'))
    require(tracked == set(baseline['tracked']), 'tracked path inventory changed')
    changed = []
    missing = []
    for relative, old_digest in baseline['tracked'].items():
        digest = file_digest(relative)
        if digest is None:
            missing.append(relative)
        if digest != old_digest:
            changed.append({'path': relative, 'before': old_digest, 'after': digest})
    require(not missing, 'tracked paths missing')
    require({row['path'] for row in changed} <= ALLOWED_TRACKED,
            'tracked changes exceed explicit repair whitelist')
    original_untracked_changed = []
    for relative, old_digest in baseline['untracked'].items():
        digest = file_digest(relative)
        if digest != old_digest:
            original_untracked_changed.append({'path': relative, 'before': old_digest, 'after': digest})
    require(not original_untracked_changed, 'original untracked files changed or missing')
    untracked = paths(git('ls-files', '--others', '--exclude-standard', '-z'))
    require(set(baseline['untracked']) <= untracked, 'original untracked inventory changed')
    new_untracked = sorted(untracked - set(baseline['untracked']))
    require(set(new_untracked) <= ALLOWED_NEW, 'new untracked paths exceed explicit repair whitelist')
    diff = subprocess.run(['git', 'diff', '--check'], cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    require(diff.returncode == 0, 'git diff --check failed')
    new_file_whitespace = []
    for relative in sorted(ALLOWED_NEW):
        target = ROOT / relative
        if not target.is_file():
            continue
        raw = target.read_bytes()
        for ordinal, line in enumerate(raw.splitlines(), 1):
            if line.rstrip(b' \t') != line:
                new_file_whitespace.append({'path': relative, 'line': ordinal,
                                            'reason': 'trailing whitespace'})
        if raw.endswith(b'\n\n'):
            new_file_whitespace.append({'path': relative, 'line': len(raw.splitlines()),
                                        'reason': 'blank line at EOF'})
    require(not new_file_whitespace, 'authorized new-file whitespace check failed')
    begin = b'# ==== BEGIN SHARED CORE (v24-ui-family-v1) ====\n'
    end = b'# ==== END SHARED CORE ====\n'
    artifacts, shared = [], []
    for name, line_cap, byte_cap in (('pi_tools.py', 1392, 63279), ('rp_tools.py', 1346, 62667)):
        raw = (ROOT / 'v24/ui/plugins' / name).read_bytes()
        text = raw.decode('utf-8')
        lines, size = len(text.splitlines()), len(raw)
        require(lines <= line_cap and size <= byte_cap and lines <= 3000 and size <= 160 * 1024,
                name + ' exceeds unchanged artifact size cap')
        require(raw.count(begin) == raw.count(end) == 1, name + ' shared markers differ')
        core = raw[raw.index(begin):raw.index(end) + len(end)]
        shared.append(core)
        artifacts.append({'path': 'v24/ui/plugins/' + name, 'lines': lines, 'bytes': size,
                          'line_cap': line_cap, 'byte_cap': byte_cap, 'sha256': sha256(raw)})
    require(shared[0] == shared[1], 'marker-inclusive shared core differs')
    catalog = ast.parse((ROOT / 'v24/ui/catalog.py').read_text())
    values = [ast.literal_eval(node.value) for node in catalog.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'MAX_SAFE_ARGS_BYTES'
                      for target in node.targets)]
    require(values == [None], 'MAX_SAFE_ARGS_BYTES is not None')
    require(baseline_path.read_bytes() == baseline_bytes, 'baseline bytes changed during audit')
    report = dict(status='passed' if not errors else 'failed', errors=errors, precommit_only=True,
                  baseline=str(baseline_path), baseline_sha256=sha256(baseline_bytes),
                  identity=identity, tracked_count=len(tracked),
                  tracked_unchanged=len(baseline['tracked']) - len(changed), tracked_changed=changed,
                  tracked_missing=missing, original_untracked_count=len(baseline['untracked']),
                  original_untracked_changed=original_untracked_changed,
                  new_untracked=[{'path': name, 'sha256': file_digest(name)} for name in new_untracked],
                  index_paths=staged, diff_check_exit=diff.returncode,
                  new_file_whitespace=new_file_whitespace,
                  diff_check_output=diff.stdout.decode('utf-8', errors='replace'),
                  artifacts=artifacts, shared_core_bytes=len(shared[0]), shared_core_sha256=sha256(shared[0]),
                  max_safe_args_bytes=None, frozen_paths_byte_identical=not missing and
                  {row['path'] for row in changed} <= ALLOWED_TRACKED)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n')
    print(f'[{report["status"]}] M4 freeze audit; tracked={len(tracked)}; '
          f'changed={len(changed)}; original_untracked={len(baseline["untracked"])}; '
          f'new={len(new_untracked)}; index={len(staged)}; errors={len(errors)}; report={output_path}')
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
