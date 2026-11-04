#!/usr/bin/env python3
"""Read-only M5 audit for the closeout snapshot (pre-commit only).

Snapshot mode certifies only integrity and snapshot identity; it is never
milestone acceptance and exits 3 (not 0) when consistent. Completion mode
derives every blocker from current evidence and exits 0 only when all are
resolved. Both modes compare against the recorded pre-commit baseline: after
the milestone commit the tracked/untracked inventory changes, so a committed
tree is expected to fail the snapshot integrity checks and must not be used
as acceptance evidence. No DB, provider, environment key values, or old audit
is executed.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'prompt-exports/v24-m5-evidence'
RETAINED_MANIFEST_SHA256 = '1d6f4b33d2176d711aca0ce69e6ab5331eaab940bfb7c5d095addacbd66386c6'
HISTORICAL_TEST_SHA256 = '6de290ea309dc7f5707d6169fd044741835c51197b6121393d3ab6564fb42642'
ABANDONMENT_PATH = ROOT / 'docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json'
ABANDONED_EVIDENCE_PROOFS = {
    'original52_pre_WI1_baseline_proof_lost':
        ('original52-baseline.json', {'original52': True, 'pre_WI1': True}),
    'WI1_preincident_PGDATA_logical_equality_unproven':
        ('wi1-preincident-pgdata-proof.json', {'preincident': True, 'logical_equality': True}),
}
ABANDONED_EVIDENCE_IDS = tuple(ABANDONED_EVIDENCE_PROOFS)
DOCS = {
    'AGENTS.md', 'v24/ui/README.md',
    'docs/plans/v24-chainlit-agent-runtime-2026-11-01.md',
    'docs/reviews/v24-ui-conformance-matrix-2026-11-01.md',
    'docs/reviews/v24-ui-deviation-ledger-2026-11-01.md',
}
NEW = {'v24/ui/audit_m5.py', 'v24/ui/run_m5_checks.py', 'v24/ui/provider.py',
       'v24/ui/test_audit_m5.py',
       'docs/reviews/v24-ui-m5-incomplete-checkpoint-2026-11-03.md',
       'docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json'}
UNRELATED_NEW = {
    '.claude/settings.local.json',
    # Unrelated M6-M10 planning note that appeared after the resume baseline.
    'docs/plans/v24-ui-usable-agent-m6-m10-2026-11-04.md',
}
WI2_UNTRACKED = {'v24/ui/real.py', 'v24/ui/test_real_entry.py'}
# Backfill of the measured safe-args bound necessarily edits the M4 gate's
# assertions and the skill text that quoted the old unmeasured value.
M5_AUTHORIZED = {'v24/ui/test_ui_gate.py', 'v24/ui/skills/surgical-edit/SKILL.md'}
CURRENT_SOURCES = (
    'v24/ui/app.py', 'v24/ui/catalog.py', 'v24/ui/control.py',
    'v24/ui/real.py', 'v24/ui/provider.py', 'v24/ui/test_real_entry.py',
    'v24/ui/audit_m5.py', 'v24/ui/run_m5_checks.py', 'v24/ui/test_audit_m5.py',
    'v24/ui/sessions.py', 'v24/ui/test_backend_regressions.py',
    'v24/ui/test_ui_gate.py', 'v24/ui/skills/surgical-edit/SKILL.md',
)
CAPACITY_EXEMPT_MANIFESTS = {
    'wi3-final-capacity-summary.run1-superseded.json':
        'eb1c64805df3fdd20cd2968cc4d82a482c45f9c5abd5ac7b4dcb8e054c4daadd',
    'wi3-final-capacity-summary.run2-superseded.json':
        'b60279dc02901bdff34565f7743af91ae2949e5dc533451bb31df4265eafd91f',
    'wi3-final-capacity-summary.run3-superseded.json':
        'f9aeec518ce85ac19a4f591381a6ad56229662391f82833d3ff32c5a99d9547e',
    'wi3-final-capacity-summary.run4-superseded.json':
        'eaff43b55f32759e9cd4275c2ba94bf3544cbd15400d52b2e66ccb8596af5b1c',
    'wi3-final-capacity-summary.run5-superseded.json':
        '25776529804f0302a1c44f65baf749dc89ac63ac7eda06def405d3e3c0ea5640',
    'wi3-final-capacity-partials.json':
        'bed5cf2997dcbac48931bececfea5c62dc48dff71fb2c6b9ff1ac83870402bd5',
}
SECRET = re.compile(r'\bsk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                    r'(?i:postgres(?:ql)?://[^\s\x22\x27]+:[^\s@\x22\x27]+@)|'
                    r'(?i:bearer)\s+(?!synthetic-token-shaped-example(?:[\x22\x27\s]|$))[A-Za-z0-9._~-]{20,}|'
                    r'(?i:(?:DEEPSEEK|OPENAI)_API_KEY)\s*[:=]\s*[\x22\x27]?[A-Za-z0-9_-]{20,}')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def git(*args):
    return subprocess.check_output(['git', '-c', 'core.quotePath=false', *args], cwd=ROOT, text=True).strip()


def mismatch(mapping, root):
    return sorted(p for p, h in mapping.items() if not (root / p).is_file() or digest(root / p) != h)


def current_source_hashes():
    return {p: digest(ROOT / p) for p in CURRENT_SOURCES if (ROOT / p).is_file()}


def runtime_source_hashes():
    """Recompute the complete runtime source map without importing production code."""
    paths = [ROOT / 'v24/load.py', ROOT / 'v24/s1/setup_db.py']
    for folder, pattern in (('host', '*.py'), ('ui', '*.py'), ('ui/plugins', '*.py'),
                            ('ui/skills', '*/SKILL.md'), ('sql', '*.sql')):
        paths.extend((ROOT / 'v24' / folder).glob(pattern))
    return {str(path.relative_to(ROOT)): digest(path)
            for path in sorted(set(paths)) if path.is_file()}


# Verification-only files do not shape a provider request or the measured tool
# effect.  Measurement bindings use this subset, so an audit/test/runner edit
# does not invalidate a retained capacity or exec11 run.
_REQUEST_EXCLUDED = re.compile(
    r'(^|/)(?:test_[^/]+\.py|audit_[^/]+\.py|run_[^/]+_checks\.py|'
    r'smoke\.py|plugin_smoke\.py|d_ui_6_acl\.py)$')


def is_verification_path(path):
    return _REQUEST_EXCLUDED.search(path) is not None


def request_source_hashes():
    """Production files that can shape the request or its measured effect."""
    runtime = runtime_source_hashes()
    return {path: value for path, value in runtime.items()
            if not is_verification_path(path)}


def review_source_hashes():
    """Everything a formal closeout review must bind: runtime plus closeout docs.

    Measurement bindings deliberately use the narrower request subset above;
    a formal review of the audit, runner, tests and documents is a different
    claim and must be invalidated by any change to those reviewed artifacts.
    """
    hashes = runtime_source_hashes()
    for path in sorted(DOCS | NEW):
        if (ROOT / path).is_file():
            hashes[path] = digest(ROOT / path)
    return hashes


def verified_relative_file(name, expected_hash, *, review_export=False):
    """Resolve a hashed relative file, rejecting absolute/traversing/symlink escapes."""
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or '..' in Path(name).parts or not isinstance(expected_hash, str)
            or re.fullmatch(r'[0-9a-f]{64}', expected_hash) is None):
        return None
    try:
        candidates = [(EVIDENCE / name, EVIDENCE)]
        if review_export:
            exports = ROOT / 'prompt-exports'
            candidates.append((exports / name, exports))
            candidates.append((ROOT / name, exports))
        for candidate, root in candidates:
            path = candidate.resolve()
            if path.is_relative_to(root.resolve()) and path.is_file() and digest(path) == expected_hash:
                return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def evidence_file_matches(name, expected_hash):
    return verified_relative_file(name, expected_hash) is not None


def review_export_matches(name, expected_hash):
    return verified_relative_file(name, expected_hash, review_export=True) is not None


def review_source_hashes_match(review, sources):
    hashes = review.get('source_sha256') if isinstance(review, dict) else None
    return isinstance(hashes, dict) and hashes == sources


def capacity_samples_match(capacity, sources_match):
    samples = capacity.get('samples')
    if not isinstance(samples, list):
        return False
    if not isinstance(capacity.get('source_sha256'), dict) or not capacity['source_sha256']:
        return False
    paths, run_ids, pairs = set(), set(), []
    def resolve(item):
        if not isinstance(item, dict):
            return None
        path = verified_relative_file(item.get('summary_path'), item.get('summary_sha256'))
        if path is None or path in paths:
            return None
        summary = read_json(path)
        if not isinstance(summary, dict):
            return None
        run_id = summary.get('run_id')
        if not isinstance(run_id, str) or not run_id.strip() or run_id in run_ids:
            return None
        target, content = item.get('target_args_bytes'), item.get('content_class')
        if (summary.get('scenario') != 'probe' or summary.get('profile') != 'current'
                or summary.get('source_unchanged') is not True or not sources_match(summary)
                or type(target) is not int or content not in ('ascii', 'cjk', 'escape')
                or summary.get('target_args_bytes') != target
                or summary.get('content_class') != content):
            return None
        paths.add(path)
        run_ids.add(run_id)
        return summary

    for sample in samples:
        summary = resolve(sample)
        if summary is None:
            return False
        checks, models = summary.get('checks'), summary.get('models')
        if (summary.get('contract_passed') is not True or summary.get('status') != 'cancelled'
                or summary.get('measurement_reason') != 'measurement_complete'
                or not isinstance(checks, dict) or checks.get('file_matches_expected') is not True
                or checks.get('write_executed_once') is not True
                or not isinstance(models, list)):
            return False
        dispatched = [model for model in models if isinstance(model, dict) and type(model.get('dispatch_count')) is int
                      and model.get('dispatch_count') == 1
                      and model.get('durable_status') == 'succeeded']
        if len(dispatched) != 1 or any(not isinstance(model, dict) or model not in dispatched
                                       and not (type(model.get('dispatch_count')) is int and model.get('dispatch_count') == 0
                                                and model.get('durable_status') == 'cancelled')
                                       for model in models):
            return False
        tool_args = dispatched[0].get('tool_args')
        if (not isinstance(tool_args, list) or len(tool_args) != 1 or not isinstance(tool_args[0], dict)
                or type(tool_args[0].get('actual_complete_args_bytes')) is not int):
            return False
        target, content = summary.get('target_args_bytes'), summary.get('content_class')
        if (type(target) is not int or target <= 0 or content not in ('ascii', 'cjk', 'escape')
                or tool_args[0]['actual_complete_args_bytes'] != target):
            return False
        for field in ('target_args_bytes', 'content_class'):
            if field in sample and (type(sample[field]) is not type(summary[field]) or sample[field] != summary[field]):
                return False
        pairs.append((target, content))
    targets = {target for target, _ in pairs}
    complete_targets = {target for target in targets
                        if all((target, content) in pairs for content in ('ascii', 'cjk', 'escape'))}
    safe = capacity.get('safe_args_bytes')
    largest_complete = max((target for target in complete_targets
                            if all(t in complete_targets for t in targets if t <= target)), default=None)
    boundary_pairs = [(target, content) for target, content in pairs if type(safe) is int and target >= safe]
    boundary_repeats = len(boundary_pairs) - len(set(boundary_pairs))
    # The record must account for the whole authoritative batch, not only the
    # passing samples.  A transport failure is infrastructure, not a capacity
    # verdict.  A finish_length at or below the bound is allowed only when the
    # record states the reason and the exact observed rate; a fidelity miss is
    # allowed only when it is named as an accepted failure.
    attempts = capacity.get('attempts')
    if not isinstance(attempts, dict):
        return False
    total, sampled, excluded, infrastructure, failed = (
        attempts.get(key) for key in ('total', 'sampled', 'excluded', 'infrastructure', 'failed'))
    infra_samples = attempts.get('infrastructure_samples')
    excluded_samples = attempts.get('excluded_samples')
    failed_samples = attempts.get('failed_samples')
    accepted = attempts.get('accepted_failures')
    reasons = accepted.get('reasons') if isinstance(accepted, dict) else None
    rate = accepted.get('finish_length_rate') if isinstance(accepted, dict) else None
    counters = (total, sampled, excluded, infrastructure, failed)
    if (any(type(value) is not int or value < 0 for value in counters)
            or total != sampled + excluded + infrastructure + failed
            or sampled != len(samples) or total < 30
            or not isinstance(infra_samples, list) or len(infra_samples) != infrastructure
            or not isinstance(excluded_samples, list) or len(excluded_samples) != excluded
            or not isinstance(failed_samples, list) or len(failed_samples) != failed
            or not isinstance(reasons, list) or (failed and not reasons)
            or any(reason not in ('target_missed', 'finish_length') for reason in reasons)):
        return False
    for item in infra_samples:
        summary = resolve(item)
        # None is not enough: a non-transport failure with a null reason must
        # not be filed as infrastructure.
        if summary is None or summary.get('measurement_reason') != 'transport':
            return False
    for item in excluded_samples:
        summary = resolve(item)
        target = item.get('target_args_bytes') if isinstance(item, dict) else None
        if (summary is None or item.get('exclusion_reason') != 'incomplete_target'
                or type(target) is not int or type(safe) is not int or target <= safe
                or target in complete_targets
                or summary.get('contract_passed') is True
                or summary.get('measurement_reason') not in ('target_missed', 'finish_length')):
            return False
    finish_length = 0
    for item in failed_samples:
        summary = resolve(item)
        if summary is None or summary.get('contract_passed') is True:
            return False
        reason = summary.get('measurement_reason')
        target = item.get('target_args_bytes')
        if reason not in ('target_missed', 'finish_length') or type(target) is not int:
            return False
        at_or_below = type(safe) is int and target <= safe
        if at_or_below and reason not in reasons:
            return False
        if reason == 'finish_length' and at_or_below:
            finish_length += 1
    if finish_length * 10 > total or failed * 10 > total or infrastructure * 10 > total:
        return False
    if finish_length:
        if 'finish_length' not in reasons or rate != f'{finish_length}/{total}':
            return False
    elif rate not in (None, f'0/{total}'):
        return False
    # Reconcile the declared counts against the exact batch that produced
    # them.  Batch identity is the request-shaping subset, not the full
    # runtime map: an audit/test-only edit must not hide a probe that ran
    # against the same request sources.  Earlier measured batches are named
    # only by the retained manifests pinned in CAPACITY_EXEMPT_MANIFESTS;
    # a new or modified manifest cannot exempt an unaccounted probe.
    exempt_paths = set()
    for name, expected in CAPACITY_EXEMPT_MANIFESTS.items():
        record = EVIDENCE / name
        try:
            if not record.is_file() or digest(record) != expected:
                continue
            old = read_json(record)
        except (OSError, ValueError, TypeError):
            continue
        rows = old.get('samples') if isinstance(old, dict) else None
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                path = verified_relative_file(item.get('summary_path'), item.get('summary_sha256'))
                if path is not None:
                    exempt_paths.add(path)
    inventory = set()
    for path in sorted(EVIDENCE.glob('v24-real-*/summary.json')):
        try:
            summary = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        resolved = path.resolve()
        if resolved in exempt_paths and resolved not in paths:
            continue
        if (isinstance(summary, dict) and summary.get('scenario') == 'probe'
                and summary.get('profile') == 'current'
                and sources_match(summary)):
            inventory.add(resolved)
    if len(inventory) != total or inventory != paths:
        return False
    return (len(targets) >= 10 and complete_targets == targets
            and largest_complete is not None and type(safe) is int and safe <= largest_complete
            and boundary_repeats >= 2
            and type(capacity.get('boundary_repeats')) is int
            and capacity['boundary_repeats'] == boundary_repeats
            and safe <= max(targets))


def audit_manifests(checkpoint_dir, browser_dir, errors):
    """Load only the audit's retained/baseline/checkpoint/browser manifests."""
    def hashes(value):
        if not isinstance(value, dict) or any(not isinstance(p, str) or not p or '\x00' in p or not isinstance(h, str)
                                             or re.fullmatch(r'[0-9a-f]{64}', h) is None
                                             for p, h in value.items()):
            raise ValueError('invalid hash map')

    def validate(kind, row):
        if kind in ('retained', 'browser'):
            hashes(row['files_sha256'])
            if kind == 'browser' and 'browser-missing-key.png' not in row['files_sha256']:
                raise ValueError('missing screenshot hash')
        elif kind == 'resume_baseline':
            hashes(row['tracked_sha256'])
            hashes(row['untracked_sha256'])
            if any(not isinstance(row[key], str) for key in ('head', 'main', 'origin_main', 'branch')):
                raise ValueError('invalid refs')
        elif kind == 'checkpoint':
            hashes(row['frozen_production_sha256'])
            if not isinstance(row['real_batch']['attempts'], list):
                raise ValueError('invalid attempts')
            for attempt in row['real_batch']['attempts']:
                if (not isinstance(attempt['last_line'], str) or 'evidence=' not in attempt['last_line']
                        or not isinstance(attempt['scenario'], str) or not isinstance(attempt['status'], str)
                        or type(attempt['contract_passed']) is not bool or type(attempt['exit']) is not int):
                    raise ValueError('invalid attempt')
            for name in ('focused', 'm4', 's10'):
                if (type(row['offline'][name]['exit']) is not int
                        or not isinstance(row['offline'][name]['last_line'], str)):
                    raise ValueError('invalid offline receipt')
        else:
            if not isinstance(row, list):
                raise ValueError('invalid M4 manifest')
            for receipt in row:
                if (not all(isinstance(receipt[key], str) for key in ('log', 'sha256', 'last_line'))
                        or type(receipt['exit']) is not int):
                    raise ValueError('invalid M4 receipt')

    manifests = {}
    for kind, path in (('resume_baseline', EVIDENCE / 'resume-baseline.json'),
                       ('retained', EVIDENCE / 'wi3-retained-manifest.json'),
                       ('checkpoint', checkpoint_dir / 'checkpoint.json'),
                       ('checkpoint_m4', checkpoint_dir / 'm4/results.json'),
                       ('browser', browser_dir / 'wi3-browser-manifest.json')):
        if not path.is_file():
            continue
        try:
            row = read_json(path)
            validate(kind, row)
            manifests[kind] = row
        except (OSError, ValueError, KeyError, TypeError):
            reason = ('checkpoint' if kind == 'checkpoint_m4' else kind) + '_evidence_invalid'
            if reason not in errors:
                errors.append(reason)
    return manifests


def proof_matches(filename, markers):
    try:
        proof = read_json(EVIDENCE / filename)
        hashes = proof.get('files_sha256') if isinstance(proof, dict) else None
        return (isinstance(hashes, dict) and bool(hashes)
                and all(proof.get(k) is v for k, v in markers.items())
                and all(evidence_file_matches(p, h) for p, h in hashes.items()))
    except (OSError, ValueError, TypeError):
        return False


def catalog_constants(tree):
    values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id in ('OUTPUT_TOKEN_CAP', 'BODY_BYTE_CEILING', 'MAX_SAFE_ARGS_BYTES')}
    real_limits = next((n for n in tree.body if isinstance(n, ast.Assign)
                        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'REAL_UI_LIMITS'), None)
    ceiling = (next((k.value for k in real_limits.value.keywords if k.arg == 'body_byte_ceiling'), None)
               if real_limits is not None and isinstance(real_limits.value, ast.Call) else None)
    try:
        values['REAL_BODY_BYTE_CEILING'] = ast.literal_eval(ceiling) if ceiling is not None else None
    except (ValueError, TypeError):
        values['REAL_BODY_BYTE_CEILING'] = None
    return values


def render_contract_failures(tree, app_tree, readme, constants):
    """Concrete single-source prompt/footer/skill/README checks; no name-only passes."""
    failures = []
    def check(ok, reason):
        if not ok:
            failures.append(reason)
    prompt = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == 'build_system_prompt'), None)
    contract = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == 'limits_contract'), None)
    if prompt is None or contract is None:
        return ['render_contract_functions_missing']
    check({'completion_cap', 'body_byte_ceiling', 'max_safe_args_bytes'}
          <= {a.arg for a in contract.args.kwonlyargs}, 'render_contract_arguments')
    check({'completion_cap', 'body_byte_ceiling', 'max_safe_args_bytes'}
          <= {n.id for n in ast.walk(contract) if isinstance(n, ast.Name)}, 'render_contract_values')
    check('max_safe_args_bytes' in {a.arg for a in prompt.args.args}, 'prompt_safe_args_argument')
    check('completion_cap' in {a.arg for a in prompt.args.args + prompt.args.kwonlyargs}, 'prompt_cap_argument')

    def is_name(node, name):
        return isinstance(node, ast.Name) and node.id == name

    def is_attr(node, base, attr):
        return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == base and node.attr == attr)

    def is_none_default(node, parameter, fallback):
        """`FALLBACK if parameter is None else parameter`, exactly."""
        test = getattr(node, 'test', None)
        return (isinstance(node, ast.IfExp) and isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == parameter
                and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
                and is_name(node.body, fallback)
                and is_name(node.orelse, parameter))

    def defaults(function):
        values = {}
        for arg, default in zip(function.args.args[-len(function.args.defaults):], function.args.defaults):
            values[arg.arg] = default
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
            if default is not None:
                values[arg.arg] = default
        return values

    for name, constant in (('completion_cap', 'OUTPUT_TOKEN_CAP'),
                           ('body_byte_ceiling', 'BODY_BYTE_CEILING'),
                           ('max_safe_args_bytes', 'MAX_SAFE_ARGS_BYTES')):
        check(is_name(defaults(contract).get(name), constant),
              'render_contract_default_' + name)
        check(is_name(defaults(prompt).get(name), constant),
              'prompt_default_' + name)

    prompt_calls = [n for n in ast.walk(prompt) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'limits_contract']
    check(len(prompt_calls) == 1, 'prompt_limit_contract')
    footer_sends = [n for n in ast.walk(app_tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == 'send'
                    and any(isinstance(a, ast.JoinedStr) and any(
                        isinstance(v, ast.Constant) and isinstance(v.value, str) and 'max_out=' in v.value
                        for v in a.values) for a in n.args)]
    check(len(footer_sends) == 1, 'footer_send_missing')
    footer_calls = [n for n in ast.walk(footer_sends[0]) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == 'limits_contract'] if footer_sends else []
    check(len(footer_calls) == 1, 'footer_value_sources')

    # Presence alone is not enough.  A prompt keyword must be its exact
    # same-named parameter, not the legacy uppercase constant; the footer must
    # forward the runtime attributes, not the module defaults.  The runtime
    # attributes themselves must come from limits.
    if prompt_calls:
        for name in ('completion_cap', 'body_byte_ceiling', 'max_safe_args_bytes'):
            value = next((k.value for k in prompt_calls[0].keywords if k.arg == name), None)
            check(is_name(value, name), 'prompt_forward_' + name)
    if footer_calls:
        for name in ('completion_cap', 'body_byte_ceiling'):
            value = next((k.value for k in footer_calls[0].keywords if k.arg == name), None)
            check(is_attr(value, 'self', name), 'footer_forward_' + name)
        safe_value = next((k.value for k in footer_calls[0].keywords
                           if k.arg == 'max_safe_args_bytes'), None)
        check(safe_value is None or is_name(safe_value, 'MAX_SAFE_ARGS_BYTES')
              or is_attr(safe_value, 'catalog', 'MAX_SAFE_ARGS_BYTES'),
              'footer_forward_max_safe_args_bytes')
    runtime_assignments = {}
    for node in ast.walk(app_tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == 'self'
                    and target.attr in ('completion_cap', 'body_byte_ceiling')
                    and is_attr(node.value, 'limits', target.attr)):
                runtime_assignments[target.attr] = node.value
    check(set(runtime_assignments) == {'completion_cap', 'body_byte_ceiling'},
          'footer_runtime_limit_sources')

    # The production prompt goes through the app wrapper.  The wrapper must
    # forward all three parameters, and the turn call site must pass the two
    # runtime limits rather than module constants.
    wrapper = next((n for n in app_tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'build_system_prompt'), None)
    wrapper_calls = ([n for n in ast.walk(wrapper) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == 'build']
                     if wrapper is not None else [])
    check(len(wrapper_calls) == 1, 'app_prompt_wrapper_missing')
    if wrapper is not None:
        check([arg.arg for arg in wrapper.args.args] ==
              ['skills_block', 'history', 'completion_cap', 'body_byte_ceiling', 'max_safe_args_bytes']
              and len(wrapper.args.defaults) == 3
              and all(isinstance(default, ast.Constant) and default.value is None
                      for default in wrapper.args.defaults),
              'app_prompt_wrapper_signature')
    if wrapper_calls:
        call = wrapper_calls[0]
        args = call.args
        check(not call.keywords and len(args) == 5
              and is_name(args[0], 'skills_block') and is_name(args[1], 'history')
              and is_none_default(args[2], 'completion_cap', 'OUTPUT_TOKEN_CAP')
              and is_none_default(args[3], 'body_byte_ceiling', 'BODY_BYTE_CEILING')
              and is_none_default(args[4], 'max_safe_args_bytes', 'MAX_SAFE_ARGS_BYTES'),
              'app_prompt_wrapper_forwarding')
    app_prompt_calls = [n for n in ast.walk(app_tree) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name) and n.func.id == 'build_system_prompt']
    check(len(app_prompt_calls) == 1, 'app_prompt_call_missing')
    if app_prompt_calls:
        args = app_prompt_calls[0].args
        check(len(args) >= 4 and is_attr(args[2], 'self', 'completion_cap')
              and is_attr(args[3], 'self', 'body_byte_ceiling'),
              'app_prompt_runtime_sources')

    try:
        skill = (ROOT / 'v24/ui/skills/surgical-edit/SKILL.md').read_text()
    except OSError:
        skill = ''
    safe_value = constants.get('MAX_SAFE_ARGS_BYTES')
    rendered = {str(value) for value in re.findall(r'MAX_SAFE_ARGS_BYTES=(\d+)', skill)}
    check(safe_value is not None and rendered == {str(safe_value)},
          'skill_static_max_safe_args_value')

    values = (f"legacy_body_bytes={constants.get('BODY_BYTE_CEILING')}; "
              f"real_body_bytes={constants.get('REAL_BODY_BYTE_CEILING')}; "
              f"output_token_cap={constants.get('OUTPUT_TOKEN_CAP')}; "
              f"reserve_tokens={constants.get('RESERVE_TOKENS')}; "
              f"max_safe_args_bytes={constants.get('MAX_SAFE_ARGS_BYTES')}")
    check('<!-- M5_CURRENT_VALUES_BEGIN -->\n' + values + '\n<!-- M5_CURRENT_VALUES_END -->' in readme,
          'README_current_value_consistency')
    return failures


def render_contract_ok():
    """Derive the render blocker from the current source and marked README block."""
    try:
        tree = ast.parse((ROOT / 'v24/ui/catalog.py').read_text())
        app_tree = ast.parse((ROOT / 'v24/ui/app.py').read_text())
        readme = (ROOT / 'v24/ui/README.md').read_text()
        constants = catalog_constants(tree)
        constants['RESERVE_TOKENS'] = int(re.search(r"'reserve_tokens'\s*,\s*(\d+)",
                                                    (ROOT / 'v24/sql/48_loop.sql').read_text())[1])
    except (OSError, SyntaxError, TypeError, ValueError):
        return False
    return not render_contract_failures(tree, app_tree, readme, constants)


GATE_NAMES = ('real_entry', 'ui_gate', 'audit_contracts', 'backend', 'm4')
GATE_SCRIPTS = {
    'real_entry': 'v24/ui/test_real_entry.py',
    'ui_gate': 'v24/ui/test_ui_gate.py',
    'audit_contracts': 'v24/ui/test_audit_m5.py',
    'backend': 'v24/ui/test_backend_regressions.py',
    'm4': 'v24/ui/run_m4_checks.py',
}


def gate_receipt_failures(path, current):
    """Verify the runner's hashed current-gate receipt without trusting it."""
    try:
        receipt = read_json(path)
    except (OSError, ValueError, TypeError):
        return ['gate_receipt_missing_or_unreadable']
    if not isinstance(receipt, dict) or receipt.get('schema') != 'm5-gates-v1':
        return ['gate_receipt_schema']
    if receipt.get('gates_ok') is not True or receipt.get('source_map') != current:
        return ['gate_receipt_not_current']
    gates = receipt.get('gates')
    if not isinstance(gates, list):
        return ['gate_receipt_gates']
    failures, by_name = [], {}
    for row in gates:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str):
            failures.append('gate_receipt_row')
            continue
        if row['name'] in by_name:
            failures.append('gate_receipt_duplicate:' + row['name'])
        by_name[row['name']] = row
    if set(by_name) != set(GATE_NAMES):
        failures.append('gate_receipt_names')
    root = Path(path).resolve().parent
    for name in GATE_NAMES:
        row = by_name.get(name)
        if row is None:
            continue
        if row.get('exit') != 0:
            failures.append('gate_exit:' + name)
        argv = row.get('argv')
        if (not isinstance(argv, list) or len(argv) < 2
                or argv[1] != GATE_SCRIPTS[name]):
            failures.append('gate_argv:' + name)
        if not isinstance(row.get('last_line'), str) or not row['last_line'].startswith('[passed]'):
            failures.append('gate_last_line_prefix:' + name)
        if (row.get('source_unchanged') is not True
                or row.get('source_before') != row.get('source_after')
                or row.get('source_after') != current):
            failures.append('gate_source:' + name)
        try:
            log = Path(row.get('log', '')).resolve()
            if not log.is_relative_to(root) or not log.is_file() or digest(log) != row.get('log_sha256'):
                failures.append('gate_log:' + name)
            else:
                lines = log.read_text().splitlines()
                if (lines[-1] if lines else '[no output]') != row.get('last_line'):
                    failures.append('gate_last_line:' + name)
        except (OSError, TypeError, ValueError):
            failures.append('gate_log:' + name)
    return failures


def abandoned_evidence():
    """Return explicitly abandoned evidence ids; fail closed on any malformed record.

    Abandonment is a dated coordinator decision that a proof is unavailable and
    will not be synthesized. It is never a proof: the ids stay visible in the
    audit result under ``abandoned_evidence`` and are excluded only from the
    completion blocker list.
    """
    try:
        record = read_json(ABANDONMENT_PATH)
    except (OSError, ValueError, TypeError):
        return set()
    if (not isinstance(record, dict)
            or record.get('schema') != 'm5-abandoned-evidence-v1'
            or record.get('decision') != 'abandoned'
            or record.get('synthetic_proof') is not False
            or not isinstance(record.get('decided_at'), str)
            or re.fullmatch(r'\d{4}-\d{2}-\d{2}', record['decided_at']) is None
            or not isinstance(record.get('basis'), str) or not record['basis'].strip()
            or not isinstance(record.get('decided_by'), str)
            or not record['decided_by'].strip()):
        return set()
    rows = record.get('abandoned')
    if not isinstance(rows, list) or len(rows) != len(ABANDONED_EVIDENCE_IDS):
        return set()
    ids = []
    for row in rows:
        if (not isinstance(row, dict)
                or row.get('id') not in ABANDONED_EVIDENCE_IDS
                or row.get('status') != 'abandoned'
                or row.get('proof') != 'unavailable'
                or not isinstance(row.get('reason'), str)
                or not row['reason'].strip()):
            return set()
        ids.append(row['id'])
    return set(ids) if len(set(ids)) == len(ABANDONED_EVIDENCE_IDS) else set()


def completion_blockers(current, constants, *, gates_path=None, require_gates=False):
    """Derive blockers from current evidence; never append a fixed sentence."""
    blockers = []
    if require_gates and gate_receipt_failures(gates_path, runtime_source_hashes()):
        blockers.append('current_gate_receipt_missing_or_failed')
    if constants.get('MAX_SAFE_ARGS_BYTES') is None:
        blockers.append('max_safe_args_bytes_none')
    runtime = request_source_hashes()
    def sources_match(row):
        hashes = row.get('source_sha256')
        if not isinstance(hashes, dict):
            return False
        return {path: value for path, value in hashes.items()
                if not is_verification_path(path)} == runtime

    exec11_ok = False
    capacity_ok = False
    for path in sorted(EVIDENCE.glob('v24-real-*/summary.json')):
        try:
            summary = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(summary, dict) or summary.get('scenario') != 'exec11' or summary.get('contract_passed') is not True:
            continue
        if (summary.get('profile') == 'current' and summary.get('source_unchanged') is True
                and summary.get('status') == 'completed'
                and isinstance(summary.get('checks'), dict)
                and summary['checks'].get('skill_before_write') is True
                and summary['checks'].get('skill_continuation') is True
                and summary['checks'].get('bash_executed') is True
                and summary['checks'].get('readback_after_bash') is True
                and summary['checks'].get('durable_final') is True
                and summary['checks'].get('file_matches_expected') is True
                and isinstance(summary.get('limits'), dict)
                and summary['limits'].get('body_byte_ceiling') == 16384
                and summary.get('guard_rejections') == []
                and sources_match(summary)):
            exec11_ok = True
    if not exec11_ok:
        blockers.append('current_exec11_guard_rejected_before_write_bind_bash_readback_final')
    capacity_path = EVIDENCE / 'wi3-final-capacity-summary.json'
    if capacity_path.is_file():
        try:
            capacity = read_json(capacity_path)
            capacity_ok = (isinstance(capacity, dict) and capacity.get('profile') == 'current'
                           and type(capacity.get('safe_args_bytes')) is int
                           and 1 <= capacity['safe_args_bytes'] <= 16384
                           and capacity['safe_args_bytes'] == constants.get('MAX_SAFE_ARGS_BYTES')
                           and capacity_samples_match(capacity, sources_match)
                           and capacity.get('source_unchanged') is True
                           and sources_match(capacity))
        except (OSError, ValueError, TypeError):
            capacity_ok = False
    if not capacity_ok:
        blockers.append('final_profile_capacity_repeats_and_recommendation_incomplete')
    abandoned = abandoned_evidence()
    for evidence_id, (filename, markers) in ABANDONED_EVIDENCE_PROOFS.items():
        if evidence_id not in abandoned and not proof_matches(filename, markers):
            blockers.append(evidence_id)
    review_path = EVIDENCE / 'm5-formal-review.json'
    review_ok = False
    if review_path.is_file():
        try:
            review = read_json(review_path)
            review_ok = (isinstance(review, dict) and review.get('accepted') is True
                         and type(review.get('oracle_lanes')) is int and review['oracle_lanes'] >= 2
                         and review_export_matches(review.get('oracle_export_path'), review.get('oracle_export_sha256'))
                         and review_source_hashes_match(review, review_source_hashes()))
        except (OSError, ValueError, TypeError):
            review_ok = False
    if not review_ok:
        blockers.append('full_UI_acceptance_and_formal_M5_review_not_accepted')
    if not render_contract_ok():
        blockers.append('full_prompt_footer_README_render_contract_needs_coordinator_scope_review')
    return blockers


def write_result(out, result):
    out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('[failed] M5 audit; output already exists; nothing overwritten')
        return False
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--snapshot', action='store_true')
    mode.add_argument('--completion', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(EVIDENCE.resolve()):
        parser.error('output must remain under ignored private M5 evidence root')
    sources_path = out.parent / 'current-sources.json'
    gates_path = out.parent / 'gates.json'
    if not sources_path.is_file():
        print('[failed] M5 audit; current-sources manifest missing; nothing written')
        return 1
    errors = []
    def check(ok, reason):
        if not ok:
            errors.append(reason)
    current = current_source_hashes()
    try:
        recorded = read_json(sources_path)['files_sha256']
        if not isinstance(recorded, dict):
            raise ValueError('files_sha256 must be a dict')
    except (OSError, ValueError, KeyError, TypeError):
        recorded = None
        check(False, 'current_sources_manifest_invalid')
    if recorded is not None:
        check(recorded == current, 'current_sources_mismatch')
    checkpoint_dir = EVIDENCE / 'wi2a-20261103T134358Z'
    browser_dir = EVIDENCE / 'wi3-missing-key-ui'
    required = {
        'resume_baseline_evidence_missing': [EVIDENCE / 'resume-baseline.json'],
        'retained_evidence_missing': [EVIDENCE / 'wi3-retained-manifest.json'],
        'checkpoint_evidence_missing': [checkpoint_dir / name for name in
            ('checkpoint.json', 'm4/results.json', 'focused-wi2a.log', 'm4-command.log', 's10-g9.log')],
        'browser_evidence_missing': [browser_dir / name for name in
            ('wi3-browser-manifest.json', 'browser-receipt.json', 'browser-after-submit.json',
             'browser-submit.json', 'service.json', 'server.log')],
    }
    manifests = audit_manifests(checkpoint_dir, browser_dir, errors)
    for reason, kind, root in (
            ('retained_evidence_missing', 'retained', EVIDENCE),
            ('browser_evidence_missing', 'browser', browser_dir)):
        if kind in manifests:
            required[reason].extend(root / name for name in manifests[kind]['files_sha256'])
    if 'checkpoint' in manifests:
        for attempt in manifests['checkpoint']['real_batch']['attempts']:
            directory = attempt['last_line'].split('evidence=')[-1]
            required['checkpoint_evidence_missing'].append(checkpoint_dir / directory / 'summary.json')
            required['checkpoint_evidence_missing'].append(checkpoint_dir / (
                'real-short-module.log' if attempt['scenario'] == 'short' else 'real-' + attempt['scenario'] + '.log'))
    if 'checkpoint_m4' in manifests:
        required['checkpoint_evidence_missing'].extend(Path(row['log']) for row in manifests['checkpoint_m4'])
    missing = [reason for reason, paths in required.items() if any(not path.is_file() for path in paths)]
    if missing or errors:
        errors.extend(missing)
        try:
            known_constants = catalog_constants(ast.parse((ROOT / 'v24/ui/catalog.py').read_text()))
        except (OSError, SyntaxError, TypeError, ValueError):
            known_constants = {}
        blockers = completion_blockers(current, known_constants,
                                       gates_path=gates_path, require_gates=args.completion)
        gate_failures = gate_receipt_failures(gates_path, runtime_source_hashes())
        result = {'mode': 'completion_rejected' if args.completion else 'INCOMPLETE_snapshot',
                  'milestone_acceptance': False, 'checks_passed': False,
                  'errors': errors, 'blockers': blockers,
                  'abandoned_evidence': sorted(abandoned_evidence()),
                  'gate_receipt': {'path': str(gates_path),
                                   'sha256': digest(gates_path) if gates_path.is_file() else None,
                                   'failures': gate_failures,
                                   'required': args.completion}}
        write_result(out, result)
        print('[failed] M5 audit; required evidence missing or invalid; errors=' + str(len(errors)))
        return 1
    baseline = manifests['resume_baseline']
    checkpoint = manifests['checkpoint']
    retained_path = EVIDENCE / 'wi3-retained-manifest.json'
    check(digest(retained_path) == RETAINED_MANIFEST_SHA256, 'retained_manifest_hash')
    retained = manifests['retained']['files_sha256']
    check(not mismatch(retained, EVIDENCE), 'retained_evidence_hash_mismatch')
    refs = {k: git('rev-parse', ref) for k, ref in [('head', 'HEAD'), ('main', 'main'), ('origin_main', 'origin/main')]}
    refs['branch'] = git('branch', '--show-current')
    check(all(refs[k] == baseline[k] for k in refs), 'refs_changed_since_resume')
    index = git('diff', '--cached', '--name-only')
    check(not index, 'index_not_empty')
    tracked = git('ls-files').splitlines()
    untracked = git('ls-files', '--others', '--exclude-standard').splitlines()
    changed_resume = mismatch(baseline['tracked_sha256'], ROOT)
    changed_head = git('diff', 'HEAD', '--name-only').splitlines()
    changed_untracked = mismatch(baseline['untracked_sha256'], ROOT)
    added = sorted(set(untracked) - baseline['untracked_sha256'].keys())
    check(set(changed_resume) == DOCS | M5_AUTHORIZED | {'v24/ui/app.py', 'v24/ui/catalog.py', 'v24/ui/sessions.py', 'v24/ui/test_backend_regressions.py'}, 'unexpected_resume_tracked_changes')
    check(set(changed_head) == DOCS | M5_AUTHORIZED | {'v24/ui/app.py', 'v24/ui/catalog.py', 'v24/ui/control.py', 'v24/ui/sessions.py', 'v24/ui/test_backend_regressions.py'}, 'unexpected_HEAD_changes')
    check(set(changed_untracked) == WI2_UNTRACKED, 'unexpected_captured_untracked_changes')
    check(set(added) - UNRELATED_NEW == NEW, 'unexpected_new_untracked_paths')
    unrelated = sorted(set(added) & UNRELATED_NEW)
    check(set(tracked) == baseline['tracked_sha256'].keys(), 'tracked_inventory_changed')
    # Historical WI-2A snapshots remain historical; current-source identity is
    # the separately generated per-run manifest above.
    for attempt in checkpoint['real_batch']['attempts']:
        directory = attempt['last_line'].split('evidence=')[-1]
        summary = read_json(checkpoint_dir / directory / 'summary.json')
        check(all(summary.get('source_sha256', {}).get(p) == h
                  for p, h in checkpoint['frozen_production_sha256'].items()),
              'historical_real_source:' + attempt['scenario'])
        check(summary.get('source_sha256', {}).get('v24/ui/test_real_entry.py') == HISTORICAL_TEST_SHA256,
              'historical_real_test_source:' + attempt['scenario'])
        check(summary['source_unchanged'], 'historical_real_within_run:' + attempt['scenario'])
        check(summary['status'] == attempt['status'] and summary['contract_passed'] == attempt['contract_passed'],
              'historical_real_status:' + attempt['scenario'])
    frozen = {p: h for p, h in baseline['tracked_sha256'].items()
              if p not in DOCS | M5_AUTHORIZED | {'v24/ui/app.py', 'v24/ui/catalog.py', 'v24/ui/control.py', 'v24/ui/sessions.py', 'v24/ui/test_backend_regressions.py'}}
    check(not mismatch(frozen, ROOT), 'frozen_tracked_mismatch')
    excluded = ['.chainlit/config.toml', 'v24/ui/uv.lock']
    check(not any(p in changed_untracked for p in excluded), 'generated_config_changed')
    check(not any(p.startswith(('.chainlit/', 'prompt-exports/')) or Path(p).name in ('.env', 'mineru.json')
                  for p in git('diff', '--cached', '--name-only').splitlines()), 'key_config_in_index')
    scan_paths = sorted(DOCS | NEW | WI2_UNTRACKED | M5_AUTHORIZED |
                        {'v24/ui/app.py', 'v24/ui/catalog.py', 'v24/ui/control.py',
                         'v24/ui/sessions.py', 'v24/ui/test_backend_regressions.py'})
    check(not any(SECRET.search((ROOT / p).read_text()) for p in scan_paths), 'credential_shape_in_changed_files')
    unrelated_secret_shapes = []
    for p in unrelated:
        data = (ROOT / p).read_bytes()[:1_000_000]
        if SECRET.search(data.decode('utf-8', errors='ignore')):
            unrelated_secret_shapes.append(p)
    for p in NEW:
        data = (ROOT / p).read_bytes()
        check(data.endswith(b'\n') and not data.endswith(b'\n\n'), 'EOF:' + p)
    diff = subprocess.run(['git', '-c', 'core.quotePath=false', 'diff', '--check'],
                          cwd=ROOT, text=True, capture_output=True, check=False)
    check(diff.returncode == 0, 'tracked_diff_whitespace')
    for p in NEW:
        check(not any(line.rstrip() != line for line in (ROOT / p).read_text().splitlines()), 'new_file_whitespace:' + p)
    receipts = []
    for path in sorted(EVIDENCE.glob('*-command.json')):
        row = read_json(path)
        log = Path(row['log'])
        check(digest(log) == row['log_sha256'], 'receipt_log_hash:' + path.name)
        check(log.read_text().splitlines()[-1] == row['last_line'], 'receipt_last_line:' + path.name)
        check(row['source_before'] == row['source_after'] and row['source_unchanged'], 'within_command_source:' + path.name)
        check(not mismatch(row.get('evidence_files_sha256', {}), EVIDENCE), 'receipt_evidence:' + path.name)
        receipts.append({'receipt': path.name, 'receipt_sha256': digest(path), 'exit': row['exit'],
                         'source_differences_now': mismatch(row['source_after'], ROOT)})
    m4 = manifests['checkpoint_m4']
    check(len(m4) == 16, 'M4_receipt_count')
    for row in m4:
        check(row['exit'] == 0 and '[SKIP]' not in Path(row['log']).read_text(), 'M4_exit_or_skip')
        check(digest(row['log']) == row['sha256'], 'M4_log_hash')
        check(Path(row['log']).read_text().splitlines()[-1] == row['last_line'], 'M4_last_line')
    offline = [('focused', 'focused-wi2a.log'), ('m4', 'm4-command.log'), ('s10', 's10-g9.log')]
    for name, filename in offline:
        check(checkpoint['offline'][name]['exit'] == 0, name + '_exit')
        check((checkpoint_dir / filename).read_text().splitlines()[-1] == checkpoint['offline'][name]['last_line'], name + '_last_line')
    real = []
    for attempt in checkpoint['real_batch']['attempts']:
        directory = attempt['last_line'].split('evidence=')[-1]
        summary = read_json(checkpoint_dir / directory / 'summary.json')
        check(summary['status'] == attempt['status'] and summary['contract_passed'] == attempt['contract_passed'],
              'current_real_status')
        log = checkpoint_dir / ('real-short-module.log' if attempt['scenario'] == 'short' else 'real-' + attempt['scenario'] + '.log')
        check(log.read_text().splitlines()[-1] == attempt['last_line'], 'current_real_last_line')
        real.append({'scenario': attempt['scenario'], 'exit_recorded': attempt['exit'],
                     'summary_sha256': digest(checkpoint_dir / directory / 'summary.json'),
                     'http': summary['http_count'],
                     'current_source_match': all(summary.get('source_sha256', {}).get(p) == h
                                                 for p, h in runtime_source_hashes().items()),
                     'checks': summary['checks']})
    check(sum(r['http'] for r in real) == 8, 'current_real_count')
    browser_dir = EVIDENCE / 'wi3-missing-key-ui'
    browser_manifest = browser_dir / 'wi3-browser-manifest.json'
    check(digest(browser_manifest) == '0780b360881ecf2880a98ccf752bb608bef005c5cfb43d35e0e8d3624a2289d9', 'browser_manifest_hash')
    browser_hashes = manifests['browser']['files_sha256']
    check(not mismatch(browser_hashes, browser_dir), 'browser_evidence_hash')
    browser = read_json(browser_dir / 'browser-receipt.json')
    check(browser['observed_missing_credentials_ui'] and browser['service_http_after_submit'] == 200
          and browser['provider_calls_requested'] is False, 'browser_missing_key_contract')
    check(all(browser.get('source_sha256', {}).get(p) == h
              for p, h in checkpoint['frozen_production_sha256'].items()), 'browser_source_historical')
    after = read_json(browser_dir / 'browser-after-submit.json')
    check('凭证缺失' in json.dumps(after, ensure_ascii=False), 'browser_missing_key_DOM')
    check(read_json(browser_dir / 'browser-submit.json')['data']['success'], 'browser_actual_submit')
    service = read_json(browser_dir / 'service.json')
    check(service['provider_keys_absent'] and service['pg_env_absent'], 'service_environment_exclusion')
    try:
        os.kill(browser['service_pid'], 0)
        pid_exists = True
    except ProcessLookupError:
        pid_exists = False
    except PermissionError:
        pid_exists = True
    # Pure AST/current text assertions: no production imports or DB side effects.
    tree = ast.parse((ROOT / 'v24/ui/catalog.py').read_text())
    constants = catalog_constants(tree)
    safe_args = constants.get('MAX_SAFE_ARGS_BYTES')
    check(constants.get('OUTPUT_TOKEN_CAP') == 512 and constants.get('BODY_BYTE_CEILING') == 8000
          and 'MAX_SAFE_ARGS_BYTES' in constants
          and (safe_args is None or (type(safe_args) is int and 1 <= safe_args <= 16384)),
          'current_capacity_constants')
    app_tree = ast.parse((ROOT / 'v24/ui/app.py').read_text())
    real_ceiling = constants.get('REAL_BODY_BYTE_CEILING')
    sql = (ROOT / 'v24/sql/48_loop.sql').read_text()
    reserve = int(re.search(r"'reserve_tokens'\s*,\s*(\d+)", sql)[1])
    check(real_ceiling == 16384 and reserve == 4096, 'real_ceiling_or_SQL_reserve')
    readme = (ROOT / 'v24/ui/README.md').read_text()
    render_failures = render_contract_failures(tree, app_tree, readme,
                                               dict(constants, RESERVE_TOKENS=reserve))
    errors.extend(render_failures)
    gate_failures = gate_receipt_failures(gates_path, runtime_source_hashes())
    blockers = completion_blockers(current, constants,
                                   gates_path=gates_path, require_gates=args.completion)
    if args.completion:
        errors.extend(blockers)
    accepted = bool(args.completion and not errors and not blockers)
    result = {
        'mode': ('completion_accepted' if accepted else
                 'completion_rejected' if args.completion else 'INCOMPLETE_snapshot'),
        'milestone_acceptance': accepted, 'checks_passed': not errors,
        'errors': errors, 'blockers': blockers,
        'abandoned_evidence': sorted(abandoned_evidence()),
        'gate_receipt': {'path': str(gates_path),
                         'sha256': digest(gates_path) if gates_path.is_file() else None,
                         'failures': gate_failures,
                         'required': args.completion},
        'refs': refs, 'index_empty': not index,
        'provenance': 'RESUME ONLY; original /tmp manifest and WI1 logs unavailable; no original52 or preincident logical proof',
        'tracked_HEAD': {'count': len(tracked), 'changed': changed_head},
        'tracked_resume': {'count': len(baseline['tracked_sha256']), 'changed': changed_resume},
        'frozen_resume': {'count': len(frozen), 'mismatches': mismatch(frozen, ROOT)},
        'captured_untracked_resume': {'count': 55, 'preserved': 55 - len(changed_untracked),
                                      'changed': changed_untracked, 'new_since_resume': added,
                                      'unrelated_new': unrelated,
                                      'unrelated_secret_shapes': unrelated_secret_shapes},
        'key_config': {'changed_files_shape_scan': True, 'generated_config_excluded_and_preserved': excluded,
                       'index_empty': not index, 'environment_key_values_read': False},
        'retained_manifest_sha256': digest(retained_path), 'retained_files': len(retained),
        'receipts': receipts, 'WI2A_offline_receipts': len(m4) + 2, 'WI2A_real': real,
        'browser_missing_key': {'actual_coordinator_observation': True, 'receipt_sha256': digest(browser_dir / 'browser-receipt.json'),
                                'screenshot_sha256': browser_hashes['browser-missing-key.png'],
                                'pid': browser['service_pid'], 'pid_exists': pid_exists,
                                'service_status': 'pid_only_unverified',
                                'service_log_sha256_at_audit': digest(browser_dir / 'server.log'),
                                'full_M5_UI_acceptance': False},
        'current_sources': {'manifest': str(sources_path), 'manifest_sha256': digest(sources_path),
                            'files_sha256': current},
        'current_value_consistency': {'assertion': 'single-source limit renderer; exact prompt parameter forwarding; runtime footer attributes; checked defaults; static skill value; README block',
                                      'full_render_contract': 'verified' if not render_failures else 'INCOMPLETE'},
        'deliverable_sha256': {p: digest(ROOT / p) for p in sorted(DOCS | NEW)},
        'known_incomplete': blockers,
    }
    if not write_result(out, result):
        return 1
    if errors:
        print('[failed] M5 audit; mode=' + result['mode'] + '; errors=' + str(len(errors))
              + '; blockers=' + str(len(blockers)))
        return 1
    if args.completion:
        print('[passed] M5 completion checks; milestone_acceptance=true; blockers=0; abandoned_evidence='
              + str(len(result['abandoned_evidence'])))
        return 0
    print('[snapshot-consistent; NOT ACCEPTED] M5 INCOMPLETE snapshot; milestone_acceptance=false; blockers='
          + str(len(blockers)) + '; abandoned_evidence=' + str(len(result['abandoned_evidence']))
          + '; original52_proof=unavailable')
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
