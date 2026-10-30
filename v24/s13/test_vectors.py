"""Read-only W1 fixed-vector checker; no capture or blessing path."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
S1=ROOT/'v24/s1'
for path in (str(ROOT),str(S1),str(HERE)):
 if path not in sys.path:sys.path.insert(0,path)
from setup_db import server_helper_scope,setup_db  # noqa: E402
from v24.host.registry import pg_jsonb_text  # noqa: E402
from w1_reference import (budget_measures,classify_response,compact,frame_request,
 manifest_digest,model_text,pg_canonical,render,strict_loads,escaped_payload_bytes,
 render_count,page_decision)  # noqa: E402

from test_contracts import REQUIRED, DESIGN_SHA256

FORMAT='v24-tool-plugin-abi-w1-vectors-1'
FILES=('descriptor_v2.json','frames_v2.json','manifest_adapter_v2.json',
 'provider_projection_v2.json','renderers.json','results_v2.json','schema_v2.json','tool_contracts.json')

def fail_byte(id,want,got):
 at=next((i for i,(a,b) in enumerate(zip(want,got)) if a!=b),min(len(want),len(got)))
 raise AssertionError(f'{id}: byte_offset={at} expected_len={len(want)} actual_len={len(got)} '
  f'expected_sha256={hashlib.sha256(want).hexdigest()} actual_sha256={hashlib.sha256(got).hexdigest()}')

def equal_bytes(id,want,got):
 if want!=got:fail_byte(id,want,got)

def load():
 mapping=json.loads((HERE/'vectors/design_conformance.json').read_text(encoding='utf-8'))
 assert mapping['format']==FORMAT and mapping['design_input']['sha256_at_review']==DESIGN_SHA256
 assert hashlib.sha256((ROOT/mapping['design_input']['path']).read_bytes()).hexdigest()==mapping['design_input']['sha256_at_review'],'stale design SHA'
 suites=mapping['immutable_required_suites']
 assert len(suites)==10 and len({s['id'] for s in suites})==10
 docs={}
 required={name:set() for name in FILES}
 for suite in suites:
  assert suite['file'] in required
  required[suite['file']].update(suite['required_case_ids'])
 assert required==REQUIRED,'design mapping differs from independent inventory'
 ids=set()
 for name in FILES:
  doc=json.loads((HERE/'vectors'/name).read_text(encoding='utf-8'))
  assert doc['format']==FORMAT and doc['domain_file']==name
  cases=doc['cases']; local=[c['id'] for c in cases]
  assert len(local)==len(set(local)),name+' duplicate IDs'
  assert set(local)==required[name],f'{name}: missing={sorted(required[name]-set(local))}; extra={sorted(set(local)-required[name])}'
  for case in cases:
   id=case['id'];assert id not in ids,id+' global duplicate';ids.add(id)
   assert case['kind'] in ('byte','table'),id
   assert case['status'] in mapping['vocabulary']['status'],id
   assert case['owner'] in mapping['vocabulary']['owner'],id
   assert case['first_production_stage'] in mapping['vocabulary']['first_production_stage'],id
   assert case['design_refs'] and set(case['design_refs']).intersection(set(next(s for s in suites if id in s['required_case_ids'])['design_refs'])),id
   if case['kind']=='byte':
    raw=bytes.fromhex(case['expected_hex'])
    assert len(raw)==case['expected_length'],id
    assert hashlib.sha256(raw).hexdigest()==case['expected_sha256'],id
    if 'expected_text' in case:equal_bytes(id,raw,case['expected_text'].encode('utf-8'))
   else: assert 'input' in case and 'expected' in case,id
  docs[name]={c['id']:c for c in cases}
 assert len(ids)==71,len(ids)
 return docs

def python_checks(docs):
 node=[]
 for c in docs['descriptor_v2.json'].values():
  if c['kind']!='byte':continue
  raw=bytes.fromhex(c['expected_hex']);value=c['input'];id=c['id']
  equal_bytes(id,raw,pg_canonical(value))
  equal_bytes(id,raw,pg_jsonb_text(value).encode('utf-8'))
  node.append({'id':id,'action':'pg','payload':value})
 for c in docs['frames_v2.json'].values():
  id=c['id']
  if id.startswith('frame.request.'):
   i=c['input'];raw=frame_request(i['operation'],i['reservation'],i['args'],i.get('tool'))
   equal_bytes(id,bytes.fromhex(c['expected_hex']),raw)
   assert raw.endswith(b'\n') and raw.count(b'\n')==1,id
   node.append({'id':id,'action':'frame','payload':i})
  elif c['kind']=='byte':
   raw=bytes.fromhex(c['expected_hex'])
   assert classify_response(raw,c['input']['operation'],c['input']['exit_code'])==c['classification'],id
   node.append({'id':id,'action':'classify','payload':{'hex':c['expected_hex'],**c['input']}})
  elif id.startswith('frame.response.'):
   for row in c['input']:
    raw=bytes.fromhex(row['hex']);uid=id+'.'+row['id']
    assert classify_response(raw,row['operation'],row['exit_code'])==row['classification'],uid
    node.append({'id':uid,'action':'classify','payload':row})
 for name in ('manifest_adapter_v2.json','provider_projection_v2.json','results_v2.json'):
  for c in docs[name].values():
   if c['kind']!='byte':continue
   id=c['id'];want=bytes.fromhex(c['expected_hex'])
   if id.startswith('result.model_text') or id=='result.meta_excluded_from_model_text':
    content=c['input']['content'] if isinstance(c['input'],dict) else c['input']
    equal_bytes(id,want,model_text(content));node.append({'id':id,'action':'model','payload':content})
   else:
    equal_bytes(id,want,compact(c['input']));node.append({'id':id,'action':'compact','payload':c['input']})
 for kind in ('read','list','search'):
  golden=docs['renderers.json']['render.'+kind+'.golden']['input']['cases']
  digest_cases=[]
  for case in golden:
   id=case['id'];content,meta=render(kind,case['value'])
   assert content==case['content'] and meta==case['meta'],id
   m=budget_measures(case['args'],case['value'],content,meta)
   assert m==case['measures'],id
   assert m['content']==27+escaped_payload_bytes(content[0]['text']),id
   assert render_count(kind,case['value'])==m['content'],id
   node.append({'id':id,'action':'render','payload':{'kind':kind,'value':case['value']}})
   node.append({'id':id+'.budget','action':'budget','payload':{'args':case['args'],'value':case['value'],'content':content,'meta':meta}})
   digest_cases.append({k:case[k] for k in ('id','args','value','content','meta')})
  expected=manifest_digest('v24.fs.'+kind+'.text',1,1,digest_cases)
  manifest=docs['renderers.json']['render.manifest.'+kind]
  assert expected['golden_digest']==manifest['input']['golden_digest'],kind
  assert expected['render_digest']==manifest['render_digest'],kind
  equal_bytes(manifest['id'],bytes.fromhex(manifest['expected_hex']),compact(manifest['input']))
  node.append({'id':'render.digest.'+kind,'action':'digest','payload':{'id':'v24.fs.'+kind+'.text','version':1,'projection':1,'cases':digest_cases}})
  node.append({'id':manifest['id'],'action':'compact','payload':manifest['input']})
 assert docs['renderers.json']['render.digest.provisional_values']['expected']=={
  k:docs['renderers.json']['render.manifest.'+k]['render_digest'] for k in ('read','list','search')}
 # Q5: every fixed probe, candidate counter and finalized selector is executable here.
 q5=docs['results_v2.json']['result.budget_domains']['expected']['prefix_scenarios']
 for probe in q5:
  p=probe['input'];assert page_decision(p)==probe['expected'],probe['id']
  assert len(p['values'])==len(probe['candidates']),probe['id']
  for ix,(value,frozen) in enumerate(zip(p['values'],probe['candidates']),1):
   content,meta=render(p['kind'],value)
   assert content==frozen['content'] and meta==frozen['meta'],probe['id']
   assert budget_measures(p['args'],value,content,meta)==frozen['measures'],probe['id']
   assert frozen['measures']['content']==render_count(p['kind'],value),probe['id']
   node.append({'id':f'q5.{probe["id"]}.{ix}.render','action':'render','payload':{'kind':p['kind'],'value':value},'expected':[content,meta]})
   node.append({'id':f'q5.{probe["id"]}.{ix}.budget','action':'budget','payload':{'args':p['args'],'value':value,'content':content,'meta':meta},'expected':frozen['measures']})
  if 'selected' in probe['expected'] and probe['expected']['selected']:
   value=p['values'][probe['expected']['selected']-1]
   if value['truncated']:
    assert value['next_offset']>p['args'].get('offset',1) and value['next_offset']<=2**53-1,probe['id']
  node.append({'id':'q5.'+probe['id'],'action':'page','payload':p})
 # Cross-file links are fixed contract, not independently self-consistent silos.
 descriptors=docs['descriptor_v2.json']
 for key in ('read','list','search'):
  dc=descriptors['descriptor.v2.'+key]
  raw=bytes.fromhex(dc['expected_hex'])
  assert hashlib.sha256(raw).hexdigest()==dc['descriptor_digest']
  manifest=docs['renderers.json']['render.manifest.'+key]
  assert dc['input']['tool']['render']['digest']==manifest['render_digest']
  assert dc['render_case_ref']==manifest['id']
  pc=docs['provider_projection_v2.json']['provider.projection.'+key]
  tool=dc['input']['tool']
  assert pc['descriptor_ref']==dc['id']
  assert pc['input']=={'name':key,'description':tool['description'],'parameters':tool['parameters']}
  mf=docs['manifest_adapter_v2.json']
  adapter_id='manifest.adapter.python_read' if key=='read' else 'manifest.adapter.node_list_search'
  if key=='read':
   fc=mf['manifest.five_field_key']
   ad=mf[adapter_id];assert fc['input']['adapter_digest']==ad['adapter_digest']
   inp=fc['input'];manifest_raw=bytes.fromhex(inp['manifest_expected_hex'])
   equal_bytes(fc['id'],manifest_raw,compact(inp['manifest']))
   assert len(manifest_raw)==inp['manifest_expected_length']
   assert hashlib.sha256(manifest_raw).hexdigest()==inp['manifest_digest']
   assert inp['manifest']['provides']==[{'realm':'w1-fixture','key':'read','descriptor':dc['input']}]
   assert inp['manifest']['adapter_digest']==ad['adapter_digest']
   node.append({'id':'manifest.python.bytes','action':'compact','payload':inp['manifest'],'expected':inp['manifest_expected_hex']})
  else:
   mc=mf['manifest.one_install_two_provides'];
   assert hashlib.sha256(bytes.fromhex(mc['expected_hex'])).hexdigest()==mc['manifest_digest']
   value=mc['input'];assert [p['key'] for p in value['provides']]==['list','search']
   assert [p['descriptor'] for p in value['provides']]==[descriptors['descriptor.v2.'+k]['input'] for k in ('list','search')]
   assert value['adapter_digest']==mf[adapter_id]['adapter_digest']
 # Separate semantic budget domains: exact boundary bytes, optional meta, and built-in meta policy.
 budgets=docs['results_v2.json']['result.budget_domains']
 for row in budgets['input'][:3]:
  measured=len(compact({} if row['meta'] is None else row['meta']))
  assert measured==row['measure']
  assert ('accepted' if measured<=row['cap'] else 'output_too_large')==row['expected']
 for ix,row in enumerate(budgets['expected']['exact_boundaries']):
  n=row['repeat'];domain=row['domain']
  value={'text':'x'*n} if domain=='value' else {}
  content=[{'type':'text','text':'x'*n}] if domain=='content' else []
  meta={'x':'x'*n} if domain=='meta' else {}
  measured=budget_measures({},value,content,meta)
  assert ('accepted' if measured[domain]<=row['cap'] else 'output_too_large')==row['expected']
  assert measured[domain] in (row['cap']-1,row['cap'],row['cap']+1)
  node.append({'id':f'budget.boundary.{ix}','action':'budget','payload':{'args':{},'value':value,'content':content,'meta':meta},'expected':measured})
 for row in budgets['expected']['builtin_plugin_meta']:
  assert ('accepted' if row['meta'] in (None,{}) else 'invalid_tool_output')==row['expected']
 b0=json.loads((ROOT/'v24/b0/golden/provider_requests_v1.json').read_text(encoding='utf-8'))
 assert docs['provider_projection_v2.json']['provider.v1_bytes_unchanged']['input']==[
  {k:c[k] for k in ('id','expected_sha256','expected_length')} for c in b0['cases']]
 baseline=docs['results_v2.json']['result.meta_excluded_from_model_text']
 b0messages=json.loads((ROOT/baseline['v1_source']).read_text(encoding='utf-8'))
 assert set(baseline['v1_baseline_refs']) <= {c['id'] for c in b0messages['cases']}
 for row in docs['frames_v2.json']['frame.process.unknown_outcomes']['input']['preflight']:
  i=row['input']
  try:frame_request(i['operation'],i['reservation'],i['args'],i.get('tool'))
  except ValueError as exc:
   assert str(exc)==row['expected'],row['id']
   node.append({'id':'preflight.'+row['id'],'action':'preflight','payload':i,'expected':row['expected']})
  else:raise AssertionError(row['id']+' accepted preflight rejection')
 for row in docs['results_v2.json']['result.frame_60000_60001_65536_65537']['input']:
  n=row['repeat_count'];target=row['target']
  assert len(compact({'ok':True,'v':2,'result':{'value':{'text':'x'*n}}}))+1==target
  classification='within_builtin_target' if target<=60000 else 'over_builtin_target_transport_valid' if target<=65536 else 'stdout_limit_unknown'
  assert row['classification']==classification
 for raw in ('-0','1.5','1e3','{"a":1,"a":2}','"\\ud800"','9007199254740992'):
  try:strict_loads(raw)
  except ValueError:pass
  else:raise AssertionError('strict parser accepted '+raw)
 return node

def pg_checks(docs):
 with server_helper_scope():
  db=setup_db()
  try:
   conn=db.connect('owner')
   try:
    for c in docs['descriptor_v2.json'].values():
     if c['kind']!='byte':continue
     with conn.cursor() as cur:
      cur.execute('SELECT v24.canonical_json(%s::jsonb)',(json.dumps(c['input'],ensure_ascii=False),))
      result=cur.fetchone()[0]
     conn.rollback()
     equal_bytes(c['id']+'.pg',bytes.fromhex(c['expected_hex']),result.encode('utf-8'))
   finally:conn.close()
  finally:db.close()

def node_checks(requests,docs):
 node=shutil.which('node')
 if not node:
  print('[SKIP] node unavailable')
  raise SystemExit(2)
 raw=json.dumps(requests,ensure_ascii=False,separators=(',',':')).encode('utf-8')
 result=subprocess.run([node,str(HERE/'w1_reference.js')],input=raw,stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,timeout=30,check=False)
 assert result.returncode==0,f'Node reference exit {result.returncode}: {result.stderr[:200]!r}'
 rows=json.loads(result.stdout)
 assert len(rows)==len(requests)
 expected_ids=[r['id'] for r in requests]
 assert [r['id'] for r in rows]==expected_ids and len(set(expected_ids))==len(expected_ids)
 for req,row in zip(requests,rows):
  id=req['id'];want=None;action=req['action']
  if action in ('pg','frame','compact','model'):
   if 'expected' in req:
    assert row['result']==req['expected'],id
    continue
   case=next(c for file in docs.values() for c in file.values() if c['id']==id)
   want=case['expected_hex'];assert row['result']==want,id
  elif action=='classify':
   if id in docs['frames_v2.json']:want=docs['frames_v2.json'][id]['classification']
   else:want=req['payload']['classification']
   assert row['result']==want,id
  elif action=='render':
   if 'expected' in req:
    assert row['result']==req['expected'],id
    continue
   kind=id.split('.')[0];case=next(c for c in docs['renderers.json']['render.'+kind+'.golden']['input']['cases'] if c['id']==id)
   assert row['result']==[case['content'],case['meta']],id
  elif action=='budget':
   if 'expected' in req:
    assert row['result']==req['expected'],id
    continue
   kind=id.split('.')[0];case=next(c for c in docs['renderers.json']['render.'+kind+'.golden']['input']['cases'] if c['id']==id[:-7])
   assert row['result']==case['measures'],id
  elif action=='preflight':assert row['result']==req['expected'],id
  elif action=='page':
   probe=next(p for p in docs['results_v2.json']['result.budget_domains']['expected']['prefix_scenarios'] if 'q5.'+p['id']==id)
   assert row['result']==probe['expected'],id
  elif action=='digest':
   kind=id.rsplit('.',1)[1]
   manifest=docs['renderers.json']['render.manifest.'+kind]
   assert row['result']=={'golden_digest':manifest['input']['golden_digest'],'render_digest':manifest['render_digest']},id
 for raw in ('-0','1.5','1e3','{"a":1,"a":2}','"\\ud800"','9007199254740992'):
  p=subprocess.run([node,str(HERE/'w1_reference.js')],input=json.dumps([{'id':'strict','action':'strict','payload':{'raw':raw}}]).encode(),
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
  assert p.returncode==0 and json.loads(p.stdout)[0]['result']!='accepted',raw

def main(argv=None):
 parser=argparse.ArgumentParser();parser.add_argument('--node',action='store_true');args=parser.parse_args(argv)
 docs=load();requests=python_checks(docs);pg_checks(docs)
 if args.node:node_checks(requests,docs)
 print(f'[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node={"checked" if args.node else "not_requested"}')
 return 0
if __name__=='__main__':raise SystemExit(main())
