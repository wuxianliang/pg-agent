"""Read-only contract coverage checker for W1 tables and tool fixtures."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FORMAT = 'v24-tool-plugin-abi-w1-vectors-1'
DESIGN_SHA256 = '778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d'
# Independent immutable inventory. Do not derive this from design_conformance.json.
REQUIRED = {
 'descriptor_v2.json': {
  'canon.pg.v1','canon.pg.v2','canon.pg.empty_object','canon.key_order_utf8','canon.escape_and_unicode','canon.safe_integer_edges',
  'descriptor.v2.read','descriptor.v2.list','descriptor.v2.search','descriptor.closed_sets','descriptor.key_and_provide_match',
  'descriptor.description_boundaries','descriptor.render_registry_match','descriptor.limits_boundaries','descriptor.enums_annotations',
  'descriptor.pg_size_depth_integer_unicode_boundaries'},
 'frames_v2.json': {'frame.request.invoke','frame.request.prepare','frame.request.release','frame.request.inspect',
  'frame.request.utf8_sort_trap','frame.response.success','frame.response.known_error','frame.response.whitespace_corpus',
  'frame.response.invalid_corpus','frame.process.unknown_outcomes'},
 'manifest_adapter_v2.json': {'manifest.adapter.python_read','manifest.adapter.node_list_search','manifest.one_install_two_provides',
  'manifest.five_field_key','manifest.artifact_digest_pending'},
 'provider_projection_v2.json': {'provider.projection.read','provider.projection.list','provider.projection.search',
  'provider.safe_name_mapping','provider.key_mismatch','provider.v1_bytes_unchanged'},
 'renderers.json': {'render.read.golden','render.list.golden','render.search.golden','render.manifest.read','render.manifest.list',
  'render.manifest.search','render.digest.provisional_values'},
 'results_v2.json': {'result.success_envelope','result.failure_envelope','result.unknown_envelope','result.usage_wall_ms',
  'result.model_text_join','result.meta_excluded_from_model_text','result.budget_domains','result.frame_60000_60001_65536_65537',
  'result.replay_no_rerender','lifecycle.journal_replay_no_rerender','lifecycle.tool_message_model_text_stable'},
 'schema_v2.json': {'schema.keyword_allow_deny','schema.type_nullable','schema.required_additional_items','schema.enum_json_distinct',
  'schema.schema_bounds','schema.instance_bounds','schema.root_parameters','schema.error_path_order','schema.no_default_injection'},
 'tool_contracts.json': {'tool.shared_paths_encoding_order','tool.read.contract','tool.list.contract','tool.search.contract',
  'tool.fixture_tree.portable_nodes','tool.search_budget_file_count','tool.search_budget_timing_m3_pending'},
}
FILES = tuple(REQUIRED)

def main():
 mapping = json.loads((HERE/'vectors/design_conformance.json').read_text(encoding='utf-8'))
 assert mapping['format'] == FORMAT and mapping['inventory_version'] == 1
 design = mapping['design_input']
 assert design['path'] == 'docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md'
 assert design['sha256_at_review'] == DESIGN_SHA256
 assert hashlib.sha256((ROOT/design['path']).read_bytes()).hexdigest() == DESIGN_SHA256, 'stale design SHA'
 suites = mapping['immutable_required_suites']
 assert len(suites) == 10 and len({s['id'] for s in suites}) == 10
 assert {s['file'] for s in suites} <= set(FILES)
 inventory = {name: set() for name in FILES}
 for suite in suites:
  assert suite['required_case_ids'] and suite['design_refs']
  assert suite['status'] in mapping['vocabulary']['status']
  assert suite['owner'] in mapping['vocabulary']['owner']
  assert suite['first_production_stage'] in mapping['vocabulary']['first_production_stage']
  spans=suite['design_sections']
  assert [span['ref'] for span in spans]==suite['design_refs']
  lines=(ROOT/design['path']).read_text(encoding='utf-8').splitlines(keepends=True)
  for span in spans:
   start,end=span['line_start'],span['line_end']
   assert 1<=start<=end<=len(lines)
   assert lines[start-1].rstrip()==span['heading']
   assert hashlib.sha256(''.join(lines[start-1:end]).encode('utf-8')).hexdigest()==span['sha256']
  inventory[suite['file']].update(suite['required_case_ids'])
 assert inventory == REQUIRED, 'design mapping differs from independently pinned W1 inventory'
 docs = {name: json.loads((HERE/'vectors'/name).read_text(encoding='utf-8')) for name in FILES}
 allcases = {}
 for name, doc in docs.items():
  assert doc['format'] == FORMAT and doc['domain_file'] == name
  local = [case['id'] for case in doc['cases']]
  assert len(local) == len(set(local)), f'{name}: duplicate IDs'
  assert set(local) == REQUIRED[name], f'{name}: inventory mismatch'
  for case in doc['cases']:
   assert case['design_refs'] and case['status'] != 'passed'
   assert case['status'] in mapping['vocabulary']['status']
   assert case['owner'] in mapping['vocabulary']['owner']
   assert case['first_production_stage'] in mapping['vocabulary']['first_production_stage']
   assert case['id'] not in allcases
   allcases[case['id']] = case
 assert len(allcases) == 71
 assert mapping['compatibility']['b0_format_and_case_ids_unchanged'] is True
 assert mapping['compatibility']['b0_descriptor_v2_rejected_is_malformed_pre_m2_observation'] is True
 assert mapping['compatibility']['production_behavior_claimed'] is False
 assert mapping['compatibility']['gate_pass_claimed'] is False

 from w1_reference import render, budget_measures, page_error
 # Every tool input is a concrete, deterministic fixture-backed contract.
 tool = docs['tool_contracts.json']['cases']
 cases = {c['id']: c for c in tool}
 fixture_case = cases['tool.fixture_tree.portable_nodes']
 nodes = fixture_case['input']['nodes']
 node_paths = {json.dumps(n['path'], sort_keys=True): n for n in nodes}
 assert len(node_paths) == len(nodes), 'duplicate portable fixture node'
 assert 'portable_fixture_tree' in cases['tool.read.contract']['expected']['fixtures']
 for cid in ('tool.read.contract','tool.list.contract','tool.search.contract'):
  case = cases[cid]
  inputs = case['input']['inputs']
  assert inputs and len({row['id'] for row in inputs}) == len(inputs), cid
  assert case['expected'].get('renderer') == 'render.'+case['input']['tool']+'.golden'
  for row in inputs:
   assert row.get('renderer_ref') == case['expected']['renderer'], (cid,row['id'],'renderer')
   expected = row.get('expected')
   assert isinstance(expected, dict) and len(expected) == 1 and ('value' in expected or 'error' in expected), (cid,row['id'],'non-concrete expected')
   if 'value' in expected:
    value=expected['value'];kind=case['input']['tool']
    assert set(value)==set(case['expected']['output_keys']), (cid,row['id'],'output shape')
    assert not page_error(kind,row['args'],value), (cid,row['id'],'page relations')
    content,meta=render(kind,value)
    measures=budget_measures(row['args'],value,content,meta)
    assert all(measures[k]<=cap for k,cap in [('value',40960),('content',41984),('meta',4096),('frame',60000)]), (cid,row['id'],'over-budget expectation')
   if 'error' in expected:
    assert isinstance(expected['error'], str) and expected['error'] not in ('accepted','pending','TBD'), (cid,row['id'])
   if cid == 'tool.read.contract':
    ref = row.get('fixture_ref')
    assert ref == 'tool.fixture_tree.portable_nodes', (row['id'],ref)
    args = row['args']; path = args['path']
    if row['id'] in ('absolute_inside','absolute_outside','dotdot','dotgit','nul','symlink_component','collapse_dot'):
     continue
    assert any(n.get('path') == path for n in nodes), (row['id'],path)
   elif cid == 'tool.list.contract':
    assert row.get('fixture_ref') in ('inline:tool.list.contract','tool.fixture_tree.portable_nodes'), (row['id'],'fixture')
   else:
    assert isinstance(row.get('fixture_tree'), list), (row['id'],'missing fixture tree')
    for node in row['fixture_tree']:
     assert 'kind' in node and ('bytes_hex' in node or 'recipe' in node or node['kind'] in ('directory','symlink','special')), (row['id'],node)

 assert all(c['first_production_stage']=='M3' for c in tool)
 schema=allcases['schema.keyword_allow_deny']['input']
 assert {row['keyword'] for row in schema['allowed']}=={row['keyword'] for row in schema['invalid_allowed']}
 assert all(row['expected']=='unsupported_schema' for row in schema['invalid_allowed'])
 assert cases['tool.search_budget_timing_m3_pending']['status'] == 'm3_pending'
 assert cases['tool.search.contract']['expected']['budget_timing'] == 'M3 timing gate'
 assert cases['tool.search_budget_file_count']['expected']['file_count_exceed'] == 'search_scope_too_large'
 assert allcases['result.replay_no_rerender']['status'] == 'm4_pending'
 assert allcases['lifecycle.journal_replay_no_rerender']['status'] == 'm4_pending'
 assert allcases['render.digest.provisional_values']['status'] == 'provisional_w2_pending'
 assert allcases['descriptor.limits_boundaries']['expected']['max_meta_bytes'] == [2,16384]
 print('[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true')
 return 0

if __name__ == '__main__':
 raise SystemExit(main())
