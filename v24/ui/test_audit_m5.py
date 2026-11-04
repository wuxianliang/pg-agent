#!/usr/bin/env python3
"""Offline M5 audit contracts: O_EXCL output, snapshot semantics, derived blockers."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from v24.ui import audit_m5


def require(value, message):
    if not value:
        raise AssertionError(message)


def run(mode, output):
    with patch.object(sys, 'argv', ['audit_m5', '--' + mode, '--output', str(output)]), \
         contextlib.redirect_stdout(io.StringIO()) as stream:
        code = audit_m5.main()
    return code, stream.getvalue().strip()


def current_sources():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in audit_m5.CURRENT_SOURCES if (ROOT / p).is_file()}


CAPACITY_BLOCKER = 'final_profile_capacity_repeats_and_recommendation_incomplete'
REVIEW_BLOCKER = 'full_UI_acceptance_and_formal_M5_review_not_accepted'
EXEC11_BLOCKER = 'current_exec11_guard_rejected_before_write_bind_bash_readback_final'
RENDER_BLOCKER = 'full_prompt_footer_README_render_contract_needs_coordinator_scope_review'


def save_json(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + '\n')
    return audit_m5.digest(path)


def capacity_fixture(directory, current):
    pairs = [(64 + 64 * i, content) for i in range(10) for content in ('ascii', 'cjk', 'escape')]
    pairs += [pairs[-1], pairs[-2]]
    summaries, samples = [], []
    for i, (target, content) in enumerate(pairs):
        summary = {'scenario': 'probe', 'profile': 'current', 'run_id': f'probe-run-{i}', 'source_unchanged': True,
                   'source_sha256': current, 'contract_passed': True, 'status': 'cancelled',
                   'measurement_reason': 'measurement_complete',
                   'checks': {'file_matches_expected': True, 'write_executed_once': True},
                   'models': [{'dispatch_count': 1, 'durable_status': 'succeeded',
                               'tool_args': [{'actual_complete_args_bytes': target}]}],
                   'target_args_bytes': target, 'content_class': content}
        name = f'v24-real-probe-{i}/summary.json'
        samples.append({'summary_path': name, 'summary_sha256': save_json(directory / name, summary),
                        'target_args_bytes': target, 'content_class': content})
        summaries.append(summary)
    return ({'profile': 'current', 'safe_args_bytes': 512, 'boundary_repeats': 2,
             'source_unchanged': True, 'source_sha256': current, 'samples': samples,
             'attempts': {'total': len(samples), 'sampled': len(samples), 'excluded': 0,
                          'excluded_samples': [],
                          'infrastructure': 0, 'infrastructure_samples': [],
                          'failed': 0, 'failed_samples': [],
                          'accepted_failures': {'reasons': ['target_missed'],
                                                'finish_length_rate': None}}}, summaries)


def completion_evidence_contracts():
    current = audit_m5.runtime_source_hashes()
    require(set(current_sources()) <= current.keys(), 'runtime map lost current UI identities')
    for prefix in ('v24/host/', 'v24/sql/', 'v24/ui/plugins/', 'v24/ui/skills/'):
        require(any(path.startswith(prefix) for path in current), ('runtime map missing area', prefix))
    mutations = ('good', 'good_continuation', 'scenario', 'profile', 'source', 'missing_source', 'source_unchanged',
                 'contract', 'status', 'reason', 'file_check', 'write_check', 'models', 'tool_args',
                 'actual_bytes', 'actual_target_mismatch', 'missing_summary', 'bad_hash', 'duplicate_path', 'alias_path',
                 'duplicate_pairs', 'repeat_mismatch', 'too_few_repeats', 'safe_above_target',
                 'sample_target', 'sample_content', 'missing_dimensions',
                 'missing_class', 'too_few_targets', 'duplicate_run_id', 'cross_category_duplicate_run_id',
                 'empty_run_id', 'missing_run_id',
                 'repeats_below_safe', 'undispatched_ready', 'undispatched_succeeded', 'dispatched_cancelled',
                 'dispatched_failed', 'double_dispatch', 'no_dispatched', 'bad_continuation',
                 'host_source', 'sql_source', 'plugin_source', 'skill_source', 'missing_runtime_source',
                 'capacity_runtime_source', 'attempts_missing', 'accepted_missing',
                 'negative_excluded', 'excluded_unreferenced',
                 'failure_at_safe', 'failure_miss_at_safe', 'failure_above_safe',
                 'failure_fl_accepted', 'failure_fl_bad_rate',
                 'infrastructure_transport', 'infrastructure_bad',
                 'excluded_below_safe', 'excluded_transport', 'excluded_valid_above_safe',
                 'infrastructure_null', 'omitted_inventory', 'omitted_failure_verification',
                 'superseded_extra', 'partials_extra', 'unapproved_manifest',
                 'unapproved_run_manifest', 'omitted_undeclared_target', 'removed_production_source',
                 'verification_extra')
    for mutation in mutations:
        with tempfile.TemporaryDirectory(prefix='audit-capacity-') as directory, \
             patch.object(audit_m5, 'EVIDENCE', Path(directory)):
            directory = Path(directory)
            capacity, summaries = capacity_fixture(directory, current)
            exempt_override = {}
            summary = copy.deepcopy(summaries[0])
            if mutation in ('scenario', 'profile'):
                summary[mutation] = 'short' if mutation == 'scenario' else 'legacy'
            elif mutation == 'source':
                summary['source_sha256'] = dict(current, **{'v24/ui/app.py': '0' * 64})
            elif mutation == 'missing_source':
                summary['source_sha256'] = {}
            elif mutation in ('host_source', 'sql_source', 'plugin_source', 'skill_source', 'missing_runtime_source'):
                prefix = {'host_source': 'v24/host/', 'sql_source': 'v24/sql/',
                          'plugin_source': 'v24/ui/plugins/', 'skill_source': 'v24/ui/skills/'}.get(mutation, 'v24/host/')
                key = next(path for path in current if path.startswith(prefix))
                summary['source_sha256'] = dict(current)
                if mutation == 'missing_runtime_source':
                    summary['source_sha256'].pop(key)
                else:
                    summary['source_sha256'][key] = '0' * 64
                require(all(summary['source_sha256'].get(p) == h for p, h in current_sources().items()),
                        'runtime negative altered 11-file identity')
            elif mutation == 'attempts_missing':
                capacity.pop('attempts')
            elif mutation == 'accepted_missing':
                capacity['attempts'].pop('accepted_failures')
            elif mutation == 'negative_excluded':
                capacity['attempts']['excluded'] = -1
                capacity['attempts']['total'] -= 1
            elif mutation == 'excluded_unreferenced':
                capacity['attempts']['excluded'] = 1
                capacity['attempts']['total'] += 1
            elif mutation in ('infrastructure_transport', 'infrastructure_bad'):
                failing = copy.deepcopy(summaries[0])
                failing['run_id'] = 'synthetic-' + mutation
                failing['contract_passed'] = False
                failing['measurement_reason'] = ('transport' if mutation == 'infrastructure_transport'
                                                 else 'finish_length')
                failing['target_args_bytes'] = 512
                failing['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 512
                fname = f'v24-real-failed-{mutation}/summary.json'
                fhash = save_json(directory / fname, failing)
                capacity['attempts']['total'] += 1
                capacity['attempts']['infrastructure'] += 1
                capacity['attempts']['infrastructure_samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': 512, 'content_class': 'ascii'})
            elif mutation == 'infrastructure_null':
                failing = copy.deepcopy(summaries[0])
                failing['run_id'] = 'infra-null'
                failing['contract_passed'] = False
                failing['measurement_reason'] = None
                failing['target_args_bytes'] = 512
                failing['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 512
                fname = 'v24-real-failed-infrastructure-null/summary.json'
                fhash = save_json(directory / fname, failing)
                capacity['attempts']['total'] += 1
                capacity['attempts']['infrastructure'] += 1
                capacity['attempts']['infrastructure_samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': 512, 'content_class': 'ascii'})
            elif mutation == 'excluded_transport':
                failing = copy.deepcopy(summaries[0])
                failing['run_id'] = 'excluded-transport'
                failing['contract_passed'] = False
                failing['measurement_reason'] = 'transport'
                failing['target_args_bytes'] = 700
                failing['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 700
                fname = 'v24-real-failed-excluded-transport/summary.json'
                fhash = save_json(directory / fname, failing)
                capacity['attempts']['total'] += 1
                capacity['attempts']['excluded'] += 1
                capacity['attempts']['excluded_samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': 700, 'content_class': 'ascii',
                    'exclusion_reason': 'incomplete_target'})
            elif mutation == 'excluded_valid_above_safe':
                failing = copy.deepcopy(summaries[0])
                failing['run_id'] = 'excluded-valid-above-safe'
                failing['contract_passed'] = False
                failing['measurement_reason'] = 'target_missed'
                failing['target_args_bytes'] = 700
                failing['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 700
                fname = 'v24-real-failed-excluded-valid-above-safe/summary.json'
                fhash = save_json(directory / fname, failing)
                capacity['attempts']['total'] += 1
                capacity['attempts']['excluded'] += 1
                capacity['attempts']['excluded_samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': 700, 'content_class': 'ascii',
                    'exclusion_reason': 'incomplete_target'})
            elif mutation == 'excluded_below_safe':
                failing = copy.deepcopy(summaries[0])
                failing['run_id'] = 'excluded-below-safe'
                failing['contract_passed'] = False
                failing['measurement_reason'] = 'target_missed'
                failing['target_args_bytes'] = 500
                failing['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 500
                fname = 'v24-real-failed-excluded-below-safe/summary.json'
                fhash = save_json(directory / fname, failing)
                capacity['attempts']['total'] += 1
                capacity['attempts']['excluded'] += 1
                capacity['attempts']['excluded_samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': 500, 'content_class': 'ascii',
                    'exclusion_reason': 'incomplete_target'})
            elif mutation == 'omitted_inventory':
                extra = copy.deepcopy(summaries[1])
                extra['run_id'] = 'omitted-inventory'
                save_json(directory / 'v24-real-omitted/summary.json', extra)
            elif mutation == 'omitted_failure_verification':
                extra = copy.deepcopy(summaries[0])
                extra['run_id'] = 'omitted-failure-verification'
                extra['contract_passed'] = False
                extra['measurement_reason'] = 'target_missed'
                extra['target_args_bytes'] = 512
                extra['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 512
                extra['source_sha256'] = dict(current, **{
                    'v24/ui/test_audit_m5.py': 'f' * 64})
                name = 'v24-real-omitted-failure-verification/summary.json'
                save_json(directory / name, extra)
            elif mutation == 'omitted_undeclared_target':
                extra = copy.deepcopy(summaries[0])
                extra['run_id'] = 'omitted-undeclared-target'
                extra['contract_passed'] = False
                extra['measurement_reason'] = 'target_missed'
                extra['target_args_bytes'] = 76
                extra['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 76
                name = 'v24-real-omitted-undeclared-target/summary.json'
                save_json(directory / name, extra)
            elif mutation in ('removed_production_source', 'verification_extra'):
                summary['source_sha256'] = dict(summary['source_sha256'])
                path = ('v24/ui/skills/removed/SKILL.md' if mutation == 'removed_production_source'
                        else 'v24/ui/test_new.py')
                summary['source_sha256'][path] = 'f' * 64
            elif mutation == 'superseded_extra':
                extra = copy.deepcopy(summaries[0])
                extra['run_id'] = 'superseded-extra'
                name = 'v24-real-superseded/summary.json'
                extra_hash = save_json(directory / name, extra)
                manifest_hash = save_json(directory / 'wi3-final-capacity-summary.run1-superseded.json',
                          {'samples': [{'summary_path': name, 'summary_sha256': extra_hash}]})
                exempt_override = {'wi3-final-capacity-summary.run1-superseded.json': manifest_hash}
            elif mutation == 'unapproved_manifest':
                extra = copy.deepcopy(summaries[0])
                extra['run_id'] = 'unapproved-manifest'
                extra['contract_passed'] = False
                extra['measurement_reason'] = 'target_missed'
                extra['target_args_bytes'] = 512
                extra['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 512
                name = 'v24-real-unapproved/summary.json'
                extra_hash = save_json(directory / name, extra)
                for manifest in ('wi3-final-capacity-summary-evil-superseded.json',
                                 'wi3-final-capacity-summary-partials.json'):
                    save_json(directory / manifest,
                              {'samples': [{'summary_path': name, 'summary_sha256': extra_hash}]})
            elif mutation == 'unapproved_run_manifest':
                extra = copy.deepcopy(summaries[0])
                extra['run_id'] = 'unapproved-run-manifest'
                extra['contract_passed'] = False
                extra['measurement_reason'] = 'target_missed'
                extra['target_args_bytes'] = 512
                extra['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 512
                name = 'v24-real-unapproved-run/summary.json'
                extra_hash = save_json(directory / name, extra)
                save_json(directory / 'wi3-final-capacity-summary.run999-superseded.json',
                          {'samples': [{'summary_path': name, 'summary_sha256': extra_hash}]})
            elif mutation == 'partials_extra':
                extra = copy.deepcopy(summaries[0])
                extra['run_id'] = 'partials-extra'
                name = 'v24-real-partials/summary.json'
                extra_hash = save_json(directory / name, extra)
                manifest_hash = save_json(directory / 'wi3-final-capacity-partials.json',
                          {'samples': [{'summary_path': name, 'summary_sha256': extra_hash}]})
                exempt_override = {'wi3-final-capacity-partials.json': manifest_hash}
            elif mutation in ('failure_at_safe', 'failure_miss_at_safe', 'failure_above_safe',
                              'failure_fl_accepted', 'failure_fl_bad_rate',
                              'cross_category_duplicate_run_id'):
                failing = copy.deepcopy(summaries[0])
                failing['run_id'] = (summaries[0]['run_id'] if mutation == 'cross_category_duplicate_run_id'
                                     else 'synthetic-' + mutation)
                failing['contract_passed'] = False
                failing['measurement_reason'] = ('target_missed'
                                                 if mutation in ('failure_miss_at_safe',
                                                                 'cross_category_duplicate_run_id')
                                                 else 'finish_length')
                failing['target_args_bytes'] = 640 if mutation == 'failure_above_safe' else 512
                failing['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = failing['target_args_bytes']
                fname = f'v24-real-failed-{mutation}/summary.json'
                fhash = save_json(directory / fname, failing)
                capacity['attempts']['total'] += 1
                capacity['attempts']['failed'] += 1
                capacity['attempts']['failed_samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': failing['target_args_bytes'],
                    'content_class': 'ascii'})
                if mutation in ('failure_fl_accepted', 'failure_fl_bad_rate'):
                    capacity['attempts']['accepted_failures']['reasons'] = ['target_missed', 'finish_length']
                    capacity['attempts']['accepted_failures']['finish_length_rate'] = (
                        f"1/{capacity['attempts']['total']}" if mutation == 'failure_fl_accepted' else '0/1')
            elif mutation == 'capacity_runtime_source':
                capacity['source_sha256'] = {p: h for p, h in current.items()
                                             if p != 'v24/ui/catalog.py'}
            elif mutation in ('source_unchanged', 'contract'):
                summary['source_unchanged' if mutation == 'source_unchanged' else 'contract_passed'] = False
            elif mutation == 'status':
                summary['status'] = 'completed'
            elif mutation == 'reason':
                summary['measurement_reason'] = 'stalled'
            elif mutation in ('file_check', 'write_check'):
                summary['checks']['file_matches_expected' if mutation == 'file_check' else 'write_executed_once'] = False
            elif mutation == 'models':
                summary['models'] *= 2
            elif mutation in ('good_continuation', 'bad_continuation', 'undispatched_ready', 'undispatched_succeeded'):
                summary['models'].insert(0, {'dispatch_count': 0,
                    'durable_status': {'undispatched_ready': 'ready', 'undispatched_succeeded': 'succeeded'}.get(mutation, 'cancelled'),
                    'tool_args': []})
                if mutation == 'bad_continuation':
                    summary['models'][0]['dispatch_count'] = 1
            elif mutation in ('dispatched_cancelled', 'dispatched_failed', 'double_dispatch', 'no_dispatched'):
                if mutation.startswith('dispatched_'):
                    summary['models'][0]['durable_status'] = mutation.split('_')[1]
                else:
                    summary['models'][0]['dispatch_count'] = 2 if mutation == 'double_dispatch' else 0
            elif mutation in ('duplicate_run_id', 'empty_run_id', 'missing_run_id'):
                if mutation == 'missing_run_id':
                    summary.pop('run_id')
                else:
                    summary['run_id'] = summaries[1]['run_id'] if mutation == 'duplicate_run_id' else ' '
            elif mutation == 'missing_class':
                capacity['samples'].pop(1)
                capacity['attempts']['sampled'] -= 1
                capacity['attempts']['total'] -= 1
                (directory / 'v24-real-probe-1/summary.json').unlink()
            elif mutation == 'too_few_targets':
                removed = capacity['samples'][:3]
                capacity['samples'] = capacity['samples'][3:]
                for item in removed:
                    (directory / item['summary_path']).unlink()
                extra = copy.deepcopy(summaries[27])
                extra['run_id'] = 'probe-run-extra-boundary'
                fname = 'v24-real-extra-boundary/summary.json'
                fhash = save_json(directory / fname, extra)
                capacity['samples'].append({
                    'summary_path': fname, 'summary_sha256': fhash,
                    'target_args_bytes': 640, 'content_class': 'ascii'})
                capacity['attempts']['sampled'] = len(capacity['samples'])
                capacity['attempts']['total'] = len(capacity['samples'])
                capacity['boundary_repeats'] = 3
            elif mutation == 'repeats_below_safe':
                for i, pair in zip((30, 31), ((64, 'ascii'), (64, 'cjk'))):
                    capacity['samples'][i].update(target_args_bytes=pair[0], content_class=pair[1])
                    row = summaries[i]
                    row.update(target_args_bytes=pair[0], content_class=pair[1])
                    row['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = pair[0]
                    capacity['samples'][i]['summary_sha256'] = save_json(directory / f'v24-real-probe-{i}/summary.json', row)
            elif mutation == 'tool_args':
                summary['models'][0]['tool_args'] = []
            elif mutation == 'actual_bytes':
                summary['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = True
            elif mutation == 'actual_target_mismatch':
                summary['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 63
            elif mutation == 'duplicate_pairs':
                for i, row in enumerate(summaries):
                    row.update(target_args_bytes=512, content_class='ascii')
                    row['models'][0]['tool_args'][0]['actual_complete_args_bytes'] = 512
                    capacity['samples'][i].update(target_args_bytes=512, content_class='ascii')
                    capacity['samples'][i]['summary_sha256'] = save_json(directory / f'v24-real-probe-{i}/summary.json', row)
                summary = summaries[0]
                capacity['boundary_repeats'] = len(summaries) - 1
            elif mutation == 'repeat_mismatch':
                capacity['boundary_repeats'] = 3
            elif mutation == 'too_few_repeats':
                capacity['samples'].pop()
                capacity['attempts']['sampled'] -= 1
                capacity['attempts']['total'] -= 1
                (directory / 'v24-real-probe-31/summary.json').unlink()
                capacity['boundary_repeats'] = 1
            elif mutation == 'safe_above_target':
                capacity['safe_args_bytes'] = 641
            elif mutation in ('sample_target', 'sample_content'):
                capacity['samples'][0]['target_args_bytes' if mutation == 'sample_target' else 'content_class'] = 999 if mutation == 'sample_target' else 'escape'
            elif mutation == 'missing_dimensions':
                summary.pop('target_args_bytes')
            if mutation != 'too_few_targets':
                capacity['samples'][0]['summary_sha256'] = save_json(
                    directory / 'v24-real-probe-0/summary.json', summary)
            if mutation == 'missing_summary':
                (directory / 'v24-real-probe-0/summary.json').unlink()
            elif mutation == 'bad_hash':
                capacity['samples'][0]['summary_sha256'] = '0' * 64
            elif mutation == 'duplicate_path':
                capacity['samples'][-1] = dict(capacity['samples'][-2])
            elif mutation == 'alias_path':
                alias = directory / 'v24-real-alias/summary.json'
                alias.parent.mkdir(parents=True, exist_ok=True)
                alias.symlink_to(directory / 'v24-real-probe-30/summary.json')
                capacity['samples'][-1] = dict(capacity['samples'][-2], summary_path='v24-real-alias/summary.json')
            if mutation == 'good':
                capacity['samples'][0].update(target_args_bytes=64, content_class='ascii')
            save_json(directory / 'wi3-final-capacity-summary.json', capacity)
            with patch.object(audit_m5, 'CAPACITY_EXEMPT_MANIFESTS', exempt_override):
                blockers = audit_m5.completion_blockers(current, {'MAX_SAFE_ARGS_BYTES': capacity['safe_args_bytes']})
            require((CAPACITY_BLOCKER not in blockers) == (mutation in (
                'good', 'good_continuation', 'failure_miss_at_safe', 'failure_above_safe',
                'failure_fl_accepted', 'infrastructure_transport', 'superseded_extra',
                'partials_extra', 'excluded_valid_above_safe', 'verification_extra')), ('capacity validation', mutation, blockers))
            require(RENDER_BLOCKER not in blockers, 'render contract regressed')
    with tempfile.TemporaryDirectory(prefix='audit-exec11-') as directory, \
         patch.object(audit_m5, 'EVIDENCE', Path(directory)):
        path = Path(directory) / 'v24-real-exec11/summary.json'
        row = {'scenario': 'exec11', 'profile': 'current', 'contract_passed': True, 'status': 'completed',
               'source_unchanged': True, 'source_sha256': current, 'guard_rejections': [],
               'limits': {'body_byte_ceiling': 16384},
               'checks': {key: True for key in ('skill_before_write', 'skill_continuation', 'bash_executed',
                                               'readback_after_bash', 'durable_final', 'file_matches_expected')}}
        for mutation in ('good', 'profile', 'skill_before_write', 'skill_continuation', 'bash_executed',
                         'readback_after_bash', 'durable_final', 'file_matches_expected', 'status',
                         'guard_rejections', 'missing_guards', 'ceiling', 'missing_limits', 'runtime_source'):
            changed = copy.deepcopy(row)
            if mutation == 'profile':
                changed['profile'] = 'legacy'
            elif mutation == 'status':
                changed['status'] = 'cancelled'
            elif mutation == 'guard_rejections':
                changed['guard_rejections'] = [{'predicate': 'content_mismatch'}]
            elif mutation == 'missing_guards':
                changed.pop('guard_rejections')
            elif mutation == 'ceiling':
                changed['limits']['body_byte_ceiling'] = 8192
            elif mutation == 'missing_limits':
                changed.pop('limits')
            elif mutation == 'runtime_source':
                changed['source_sha256'] = current_sources()
            elif mutation != 'good':
                changed['checks'][mutation] = False
            save_json(path, changed)
            blockers = audit_m5.completion_blockers(current, {})
            require((EXEC11_BLOCKER not in blockers) == (mutation == 'good'), ('exec11 proof', mutation))
    with tempfile.TemporaryDirectory(prefix='audit-render-') as directory:
        root = Path(directory)
        for name in ('v24/ui/catalog.py', 'v24/ui/app.py', 'v24/ui/README.md',
                     'v24/sql/48_loop.sql',
                     'v24/ui/skills/surgical-edit/SKILL.md'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        with patch.object(audit_m5, 'ROOT', root):
            require(audit_m5.render_contract_ok(), 'render contract not derived from current source')
            readme = root / 'v24/ui/README.md'
            original = readme.read_text()
            readme.write_text(original.replace('real_body_bytes=16384', 'real_body_bytes=8192'))
            require(not audit_m5.render_contract_ok(), 'stale README values accepted')
            readme.write_text(original)
            catalog = root / 'v24/ui/catalog.py'
            text = catalog.read_text()
            start = text.index('        + limits_contract(')
            end = text.index('\n', text.index('max_safe_args_bytes=max_safe_args_bytes)', start))
            catalog.write_text(text[:start] + "        + 'limits omitted'" + text[end:])
            require(not audit_m5.render_contract_ok(), 'prompt without the shared limit contract accepted')
            require(RENDER_BLOCKER in audit_m5.completion_blockers(current, {}),
                    'render blocker not derived after prompt regression')
            catalog.write_text(text)
            catalog.write_text(text.replace('body_byte_ceiling=body_byte_ceiling', 'body_byte_ceiling=8000', 1))
            require(not audit_m5.render_contract_ok(), 'hardcoded prompt ceiling accepted')
            catalog.write_text(text)
            catalog.write_text(text.replace('body_byte_ceiling=body_byte_ceiling', 'body_byte_ceiling=completion_cap', 1))
            require(not audit_m5.render_contract_ok(), 'swapped prompt ceiling accepted')
            catalog.write_text(text)
            catalog.write_text(text.replace('body_byte_ceiling=body_byte_ceiling', 'body_byte_ceiling=BODY_BYTE_CEILING', 1))
            require(not audit_m5.render_contract_ok(), 'legacy constant accepted for runtime prompt ceiling')
            catalog.write_text(text)
            app = root / 'v24/ui/app.py'
            app_text = app.read_text()
            app.write_text(app_text.replace('body_byte_ceiling=self.body_byte_ceiling',
                                            'body_byte_ceiling=catalog.BODY_BYTE_CEILING'))
            require(not audit_m5.render_contract_ok(), 'legacy constant accepted for runtime footer ceiling')
            app.write_text(app_text.replace(', body_byte_ceiling=self.body_byte_ceiling', ''))
            require(not audit_m5.render_contract_ok(), 'footer without the runtime ceiling accepted')
            app.write_text(app_text)
            swapped = app_text.replace(
                'OUTPUT_TOKEN_CAP if completion_cap is None else completion_cap,\n'
                '                 BODY_BYTE_CEILING if body_byte_ceiling is None else body_byte_ceiling,',
                'BODY_BYTE_CEILING if body_byte_ceiling is None else body_byte_ceiling,\n'
                '                 OUTPUT_TOKEN_CAP if completion_cap is None else completion_cap,')
            require(swapped != app_text, 'wrapper swap fixture missing')
            app.write_text(swapped)
            require(not audit_m5.render_contract_ok(), 'swapped wrapper positional args accepted')
            legacy_branch = app_text.replace(
                'BODY_BYTE_CEILING if body_byte_ceiling is None else body_byte_ceiling',
                'BODY_BYTE_CEILING if body_byte_ceiling is None else BODY_BYTE_CEILING')
            require(legacy_branch != app_text, 'wrapper legacy-branch fixture missing')
            app.write_text(legacy_branch)
            require(not audit_m5.render_contract_ok(), 'wrapper legacy non-default branch accepted')
            app.write_text(app_text)
            skill = root / 'v24/ui/skills/surgical-edit/SKILL.md'
            skill_text = skill.read_text()
            skill.write_text(skill_text.replace('MAX_SAFE_ARGS_BYTES=128', 'MAX_SAFE_ARGS_BYTES=160'))
            require(not audit_m5.render_contract_ok(), 'stale static skill value accepted')
            skill.write_text(skill_text)
    with tempfile.TemporaryDirectory(prefix='audit-review-evidence-') as directory, \
         tempfile.TemporaryDirectory(prefix='audit-review-export-', dir=ROOT / 'prompt-exports') as exports, \
         patch.object(audit_m5, 'EVIDENCE', Path(directory)):
        export = Path(exports) / 'review.md'
        export.write_text('Offline synthetic review export.\n')
        relative = str(export.relative_to(ROOT))
        sha = audit_m5.digest(export)
        review_hashes = audit_m5.review_source_hashes()
        row = {'accepted': True, 'oracle_lanes': 2, 'source_sha256': review_hashes,
               'oracle_export_path': relative, 'oracle_export_sha256': sha}
        for mutation in ('good', 'bad_hash', 'runtime_source', 'review_docs', 'review_code'):
            row['oracle_export_sha256'] = '0' * 64 if mutation == 'bad_hash' else sha
            if mutation == 'runtime_source':
                row['source_sha256'] = current_sources()
            elif mutation == 'review_docs':
                row['source_sha256'] = {p: h for p, h in review_hashes.items()
                                        if p != 'docs/reviews/v24-ui-deviation-ledger-2026-11-01.md'}
            elif mutation == 'review_code':
                row['source_sha256'] = {p: h for p, h in review_hashes.items()
                                        if p != 'v24/ui/audit_m5.py'}
            else:
                row['source_sha256'] = review_hashes
            save_json(Path(directory) / 'm5-formal-review.json', row)
            require((REVIEW_BLOCKER in audit_m5.completion_blockers(current, {})) == (mutation != 'good'), 'review export hash/root/source')
        require(audit_m5.review_export_matches(str(export.relative_to(ROOT / 'prompt-exports')), sha), 'exports-relative path rejected')
        require(not audit_m5.review_export_matches(str(export), sha), 'absolute review export accepted')
        require(not audit_m5.review_export_matches('../' + relative, sha), 'traversing review export accepted')
        link = Path(directory) / 'export-link'
        link.symlink_to(export)
        require(not audit_m5.evidence_file_matches(link.name, sha), 'evidence symlink escape accepted')
        require(not audit_m5.review_export_matches(link.name, sha), 'review symlink escape accepted')
    with tempfile.TemporaryDirectory(prefix='audit-missing-') as directory, \
         patch.object(audit_m5, 'EVIDENCE', Path(directory)):
        directory = Path(directory)
        save_json(directory / 'current-sources.json', {'files_sha256': current_sources()})
        code, line = run('snapshot', directory / 'result.json')
        result = json.loads((directory / 'result.json').read_text())
        require(code == 1 and not result['checks_passed'] and not result['milestone_acceptance'], ('missing evidence', line))
        require(set(result['errors']) == {'resume_baseline_evidence_missing', 'retained_evidence_missing',
                                         'checkpoint_evidence_missing', 'browser_evidence_missing'}, 'missing evidence names')
    print('[case] capacity: 10 targets x 3 classes; boundary run repeats; runtime hashes; model rows; exec11 proof; review exports')


def malformed_manifest_contracts():
    cases = (
        ('resume-baseline.json', 'resume_baseline_evidence_invalid'),
        ('wi3-retained-manifest.json', 'retained_evidence_invalid'),
        ('wi2a-20261103T134358Z/checkpoint.json', 'checkpoint_evidence_invalid'),
        ('wi2a-20261103T134358Z/m4/results.json', 'checkpoint_evidence_invalid'),
        ('wi3-missing-key-ui/wi3-browser-manifest.json', 'browser_evidence_invalid'),
    )
    for filename, error in cases:
        malformed_rows = ['{', 'null', '[]', '{}', '{"files_sha256": null}']
        if filename.endswith('wi3-browser-manifest.json'):
            malformed_rows += ['{"files_sha256": {}}', '{"files_sha256": {"other.png": "' + '0' * 64 + '"}}']
        for malformed in malformed_rows:
            with tempfile.TemporaryDirectory(prefix='audit-invalid-manifest-') as directory, \
                 patch.object(audit_m5, 'EVIDENCE', Path(directory)):
                directory = Path(directory)
                save_json(directory / 'current-sources.json', {'files_sha256': current_sources()})
                path = directory / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(malformed)
                # An empty M4 receipt list is structurally valid; its count is checked later.
                if filename.endswith('m4/results.json') and malformed == '[]':
                    continue
                for mode in ('snapshot', 'completion'):
                    output = directory / (mode + '.json')
                    code, line = run(mode, output)
                    result = json.loads(output.read_text())
                    require(code == 1 and error in result['errors'] and not result['checks_passed']
                            and not result['milestone_acceptance'], ('malformed manifest', filename, malformed, mode, line))
    print('[case] malformed retained/baseline/checkpoint/browser manifests: named errors and rejected results')


def gate_fixture(directory, current):
    gates = []
    for name in audit_m5.GATE_NAMES:
        log = directory / (name + '.log')
        log.write_text(f'[passed] {name}\n')
        gates.append({'name': name, 'argv': ['synthetic', audit_m5.GATE_SCRIPTS[name]],
                      'exit': 0, 'log': str(log),
                      'log_sha256': audit_m5.digest(log), 'last_line': f'[passed] {name}',
                      'source_before': current, 'source_after': current,
                      'source_unchanged': True})
    document = {'schema': 'm5-gates-v1', 'gates': gates, 'gates_ok': True,
                'source_map': current}
    path = directory / 'gates.json'
    save_json(path, document)
    return path, document


def gate_receipt_contracts():
    current = audit_m5.runtime_source_hashes()
    with tempfile.TemporaryDirectory(prefix='audit-gates-') as directory:
        directory = Path(directory)
        path, document = gate_fixture(directory, current)
        require(not audit_m5.gate_receipt_failures(path, current), 'good gate receipt rejected')
        for mutation in ('exit', 'source', 'log', 'missing', 'schema', 'last_line', 'argv'):
            changed = copy.deepcopy(document)
            if mutation == 'exit':
                changed['gates'][0]['exit'] = 1
            elif mutation == 'source':
                changed['gates'][0]['source_after'] = dict(current, **{'v24/ui/app.py': '0' * 64})
            elif mutation == 'log':
                changed['gates'][0]['log_sha256'] = '0' * 64
            elif mutation == 'missing':
                changed['gates'] = changed['gates'][:-1]
            elif mutation == 'schema':
                changed['schema'] = 'wrong'
            elif mutation == 'last_line':
                changed['gates'][0]['last_line'] = '[failed]'
            elif mutation == 'argv':
                changed['gates'][0]['argv'] = ['synthetic', 'wrong.py']
            save_json(path, changed)
            require(audit_m5.gate_receipt_failures(path, current),
                    ('gate mutation accepted', mutation))
        require(audit_m5.gate_receipt_failures(directory / 'absent.json', current),
                'missing gate receipt accepted')
    with tempfile.TemporaryDirectory(prefix='audit-gate-blocker-') as directory, \
         patch.object(audit_m5, 'EVIDENCE', Path(directory)):
        directory = Path(directory)
        path, _ = gate_fixture(directory, current)
        blockers = audit_m5.completion_blockers(audit_m5.current_source_hashes(),
                                                {'MAX_SAFE_ARGS_BYTES': 128},
                                                gates_path=path, require_gates=True)
        require('current_gate_receipt_missing_or_failed' not in blockers,
                'current gate receipt still blocked completion')
        blockers = audit_m5.completion_blockers(audit_m5.current_source_hashes(),
                                                {'MAX_SAFE_ARGS_BYTES': 128},
                                                gates_path=directory / 'absent.json',
                                                require_gates=True)
        require('current_gate_receipt_missing_or_failed' in blockers,
                'missing gate receipt did not block completion')
    print('[case] five-gate receipt: exit/source/log/last-line/name/schema mutations rejected; completion requires it')


def abandonment_contracts():
    current = current_sources()
    valid = {
        'schema': 'm5-abandoned-evidence-v1',
        'decision': 'abandoned',
        'decided_at': '2026-11-04',
        'decided_by': 'coordinator',
        'basis': 'user instruction to abandon the lost proofs',
        'synthetic_proof': False,
        'abandoned': [
            {'id': audit_m5.ABANDONED_EVIDENCE_IDS[0], 'status': 'abandoned',
             'proof': 'unavailable', 'reason': 'original baseline lost'},
            {'id': audit_m5.ABANDONED_EVIDENCE_IDS[1], 'status': 'abandoned',
             'proof': 'unavailable', 'reason': 'pre-incident equality unprovable'},
        ],
    }
    with tempfile.TemporaryDirectory(prefix='audit-abandon-') as directory:
        directory = Path(directory)
        path = directory / 'abandonment.json'
        with patch.object(audit_m5, 'EVIDENCE', directory / 'no-evidence'), \
             patch.object(audit_m5, 'ABANDONMENT_PATH', path):
            def blockers():
                return set(audit_m5.completion_blockers(current, {'MAX_SAFE_ARGS_BYTES': 128}))
            require(audit_m5.abandoned_evidence() == set(), 'missing abandonment record waived')
            require(set(audit_m5.ABANDONED_EVIDENCE_IDS) <= blockers(),
                    'missing abandonment record did not block')
            path.write_text(json.dumps(valid) + '\n')
            require(audit_m5.abandoned_evidence() == set(audit_m5.ABANDONED_EVIDENCE_IDS),
                    'valid abandonment record not read')
            require(set(audit_m5.ABANDONED_EVIDENCE_IDS).isdisjoint(blockers()),
                    ('valid abandonment still blocked', blockers()))
            mutations = {
                'schema': lambda row: row.update(schema='m5-other'),
                'decision': lambda row: row.update(decision='accepted'),
                'synthetic': lambda row: row.update(synthetic_proof=True),
                'decided_by': lambda row: row.update(decided_by=' '),
                'decided_by_type': lambda row: row.update(decided_by=7),
                'decided_at': lambda row: row.update(decided_at='yesterday'),
                'basis': lambda row: row.update(basis=''),
                'missing_key': lambda row: row.pop('decided_by'),
                'missing_id': lambda row: row['abandoned'].pop(),
                'unknown_id': lambda row: row['abandoned'][0].update(id='other_proof'),
                'third_row': lambda row: row['abandoned'].append(copy.deepcopy(row['abandoned'][0])),
                'duplicate_id': lambda row: row['abandoned'].__setitem__(1, row['abandoned'][0]),
                'status': lambda row: row['abandoned'][0].update(status='proved'),
                'proof': lambda row: row['abandoned'][0].update(proof='synthesized'),
                'reason': lambda row: row['abandoned'][0].update(reason=''),
            }
            for name, mutate in mutations.items():
                row = copy.deepcopy(valid)
                mutate(row)
                path.write_text(json.dumps(row) + '\n')
                require(audit_m5.abandoned_evidence() == set(),
                        ('malformed abandonment accepted', name))
                require(set(audit_m5.ABANDONED_EVIDENCE_IDS) <= blockers(),
                        ('malformed abandonment waived', name))
            for name, text in (('malformed_json', '{not json\n'),
                               ('non_dict', '[]\n'),
                               ('non_list', json.dumps(dict(valid, abandoned={})) + '\n')):
                path.write_text(text)
                require(audit_m5.abandoned_evidence() == set(),
                        ('malformed abandonment accepted', name))
                require(set(audit_m5.ABANDONED_EVIDENCE_IDS) <= blockers(),
                        ('malformed abandonment waived', name))


def main():
    abandonment_contracts()
    completion_evidence_contracts()
    gate_receipt_contracts()
    malformed_manifest_contracts()
    parent = audit_m5.EVIDENCE
    with tempfile.TemporaryDirectory(prefix='audit-contract-', dir=parent) as directory:
        directory = Path(directory)
        sources = directory / 'current-sources.json'
        sources.write_text(json.dumps({'files_sha256': current_sources()}, indent=2, sort_keys=True) + '\n')
        sources.chmod(0o600)
        output = directory / 'snapshot.json'
        code, line = run('snapshot', output)
        require(code == 3 and 'NOT ACCEPTED' in line and 'milestone_acceptance=false' in line,
                ('snapshot semantics', code, line))
        require(stat.S_IMODE(output.stat().st_mode) == 0o600, 'audit output is not 0600')
        require(stat.S_IMODE(sources.stat().st_mode) == 0o600, 'manifest is not 0600')
        before = hashlib.sha256(output.read_bytes()).hexdigest()
        code, line = run('snapshot', output)
        require(code == 1 and 'output already exists' in line, ('overwrite refusal', code, line))
        require(hashlib.sha256(output.read_bytes()).hexdigest() == before, 'existing output changed')
        result = json.loads(output.read_text())
        require(result['milestone_acceptance'] is False and result['checks_passed'] is True,
                ('snapshot result', result['errors']))
        # The checkpoint may advance: exec11/capacity/safe-args clear as evidence
        # lands, and formal review clears when accepted. The two unrecoverable
        # historical evidence losses must never disappear silently.
        historical_blockers = {
            'original52_pre_WI1_baseline_proof_lost',
            'WI1_preincident_PGDATA_logical_equality_unproven',
        }
        optional_blockers = {'full_UI_acceptance_and_formal_M5_review_not_accepted'}
        require(set(result['abandoned_evidence']) == historical_blockers,
                ('abandoned evidence not reported', result.get('abandoned_evidence')))
        require(historical_blockers.isdisjoint(result['blockers'])
                and set(result['blockers']) <= optional_blockers,
                ('snapshot blockers', result['blockers']))
        require(result['browser_missing_key']['service_status'] == 'pid_only_unverified', 'pid claim widened')
        require('pid_exists' in result['browser_missing_key'], 'pid field missing')
        completion = directory / 'completion.json'
        code, line = run('completion', completion)
        result = json.loads(completion.read_text())
        for cleared in ('max_safe_args_bytes_none',
                        'current_exec11_guard_rejected_before_write_bind_bash_readback_final',
                        'final_profile_capacity_repeats_and_recommendation_incomplete'):
            require(cleared not in result['blockers'], ('stale blocker', cleared))
        require('current_gate_receipt_missing_or_failed' in result['blockers'],
                'standalone completion did not require the current gate receipt')
        require((code == 0) == result['milestone_acceptance'], ('acceptance/code', code, line))
        if code == 0:
            require(result['blockers'] == [] and result['checks_passed'],
                    ('accepted with blockers', result['blockers']))
        else:
            require(historical_blockers.isdisjoint(result['blockers']),
                    ('abandoned blocker returned', result['blockers']))
        require(set(result['errors']) == set(result['blockers']), ('completion errors', result['errors']))
        invalid = directory / 'invalid.json'
        sources.write_text(json.dumps({'files_sha256': None}), encoding='utf-8')
        code, line = run('snapshot', invalid)
        require(code == 1, ('null manifest accepted', code, line))
        result = json.loads(invalid.read_text())
        require('current_sources_manifest_invalid' in result['errors'], 'null manifest not reported')
        sources.write_text(json.dumps({'files_sha256': current_sources()}, indent=2, sort_keys=True) + '\n')
        require('max_safe_args_bytes_none' not in audit_m5.completion_blockers(current_sources(), {'MAX_SAFE_ARGS_BYTES': 256}),
                'measured safe args still blocked')
        tampered = directory / 'tampered.json'
        sources.write_text(json.dumps({'files_sha256': {'v24/ui/app.py': '0' * 64}}), encoding='utf-8')
        code, line = run('snapshot', tampered)
        require(code == 1, ('tampered manifest accepted', code, line))
        result = json.loads(tampered.read_text())
        require('current_sources_mismatch' in result['errors'], 'tampered manifest not reported')
        sources.write_text(json.dumps({'files_sha256': current_sources()}, indent=2, sort_keys=True) + '\n')
    print('[passed] M5 audit contracts; snapshot=3/NOT ACCEPTED; overwrite and tamper rejected; blockers derived')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
