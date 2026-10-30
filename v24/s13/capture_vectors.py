"""Generate deterministic W1 candidate vectors outside the repository only.

This command is not a gate and cannot update reviewed vectors in-place.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from w1_reference import (MAX_SAFE, budget_measures, compact, frame_request,
                          manifest_digest, model_text, pg_canonical, render)
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DESIGN = ROOT / 'docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md'
FORMAT = 'v24-tool-plugin-abi-w1-vectors-1'
REFS = {
 'descriptor_v2.json':['§3.1','§3.2','§3.3','§4.2','§4.3','Appendix A'],
 'frames_v2.json':['§5.1'],
 'manifest_adapter_v2.json':['§2.4','§4.4'],
 'provider_projection_v2.json':['§6.4','§7.2'],
 'renderers.json':['§5.3','§5.3.1','§5.6'],
 'results_v2.json':['§5.2','§5.4','§5.6','§8.2'],
 'schema_v2.json':['§5.5'],
 'tool_contracts.json':['§6.1','§6.2','§6.3'],
}
CASES = {name:[] for name in REFS}

def byte_case(file, id, domain, producer, input, raw, *, status='m2_pending', owner='W1-VECTORS', stage='M2', extra=None):
 raw=bytes(raw)
 case={'id':id,'kind':'byte','domain':domain,'producer':producer,'input_id':id,
       'input':input,'expected_hex':raw.hex(),'expected_length':len(raw),
       'expected_sha256':hashlib.sha256(raw).hexdigest(),'status':status,'owner':owner,
       'first_production_stage':stage,'design_refs':REFS[file]}
 try: case['expected_text']=raw.decode('utf-8')
 except UnicodeDecodeError: pass
 if extra: case.update(extra)
 CASES[file].append(case)
 return case

def table(file,id,input,expected,*,status='m2_pending',owner='W1-VECTORS',stage='M2'):
 case={'id':id,'kind':'table','input':input,'expected':expected,'status':status,
       'owner':owner,'first_production_stage':stage,'design_refs':REFS[file]}
 CASES[file].append(case)
 return case

def source_descriptor(key,digest):
 text=DESIGN.read_text(encoding='utf-8')
 marker={'read':'### 3.2 完整','list':'### 3.3 完整','search':'## 附录 A'}[key]
 section=text.split(marker,1)[1]
 fence=re.escape(chr(96)*3)
 found=re.search(fence+r'json\n(.*?)\n'+fence,section,re.S)
 if found is None: raise AssertionError('descriptor JSON not found: '+key)
 body=found.group(1).replace('<'+key.upper()+'_RENDER_DIGEST>',digest)
 obj=json.loads(body)
 if obj['tool']['key']!=key: raise AssertionError('descriptor key mismatch')
 return obj

def descriptor_vectors(render_digests):
 file='descriptor_v2.json'
 fixed=[
 ('canon.pg.v1',{'tool':{'name':'读取','a':1,'é':[True,None,'"q"\n']},'v':2},'c1b10b0a8058cbccfc721f2418b4f5b022f87282e7ff91053265760dcf27039c'),
 ('canon.pg.v2',{'aa':'\u0001\x7f😀','b':{'z':[],'y':{}},'k':-MAX_SAFE},'0ff17e8cd7831181e61773ca0803b1168a9ac78a0692d07d5a4ccd26dc0dcbac'),
 ('canon.pg.empty_object',{},'44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'),
 ('canon.key_order_utf8',{'\ue000':1,'𐀀':2,'aa':3,'é':4,'z':5},None),
 ('canon.escape_and_unicode',{'k':'\b\f\n\r\t\u0001/\\"\u2028\u2029雪😀\x7f'},None),
 ('canon.safe_integer_edges',{'min':-MAX_SAFE,'max':MAX_SAFE,'zero':0},None)]
 for id,value,known in fixed:
  raw=pg_canonical(value)
  case=byte_case(file,id,'descriptor_pg_jsonb','python_pg_reference',value,raw)
  if known and case['expected_sha256']!=known: raise AssertionError(id+' documented SHA mismatch')
 descriptors={k:source_descriptor(k,render_digests[k]) for k in ('read','list','search')}
 for key,value in descriptors.items():
  raw=pg_canonical(value)
  byte_case(file,'descriptor.v2.'+key,'descriptor_pg_jsonb','python_pg_reference',value,raw,
            status='provisional_w2_pending',extra={'descriptor_digest':hashlib.sha256(raw).hexdigest(),
            'render_case_ref':'render.manifest.'+key})
 base=descriptors['read']
 def mutation(path,operation,value=None,expected='invalid_descriptor'):
  row={'base_ref':'descriptor.v2.read','path':path,'operation':operation,'value':value,'expected':expected}
  if operation=='add_extra': row.update(key='unexpected',value=True)
  return row
 table(file,'descriptor.closed_sets',
  [mutation(p,'delete') for p in ('v','tool')]+
  [mutation('tool.'+p,'delete') for p in base['tool']]+
  [mutation('tool.'+obj+'.'+p,'delete') for obj in ('render','limits','annotations') for p in base['tool'][obj]]+
  [mutation(p,'add_extra') for p in ('$', 'tool','tool.render','tool.limits','tool.annotations')],
  {'top_keys':['v','tool'],'tool_keys':sorted(base['tool'])})
 table(file,'descriptor.key_and_provide_match',
  [mutation('tool.key','replace',v) for v in ('','A','agent.spawn','x'*129,'read\x00')]+[
   {'base_ref':'descriptor.v2.read','provide_key':'list','expected':'descriptor_key_mismatch'}],
  {'regex':'^[a-z][a-z0-9_.-]{0,127}$','reserved':'agent.spawn'})
 table(file,'descriptor.description_boundaries',
  [mutation('tool.description','replace',{'repeat':'x','count':n},'accepted' if n in (1,4096) else 'invalid_descriptor')
   for n in (0,1,4096,4097)]+[mutation('tool.description','replace','x\x00y')],
  {'measure':'utf8_bytes','accepted':[1,4096]})
 table(file,'descriptor.render_registry_match',
  [mutation('tool.render.'+p,'replace',v) for p,v in [('id','X'),('id','x'*129),('version',0),('version',MAX_SAFE+1),('digest','A'*64),('digest','a'*63)]]+[
   {'base_ref':'descriptor.v2.read','registry_digest':'0'*64,'expected':'renderer_digest_mismatch'}],
  {'approved_digest_ref':'render.manifest.read'})
 limits={'timeout_ms':(1,25000),'max_args_bytes':(1,65536),'max_value_bytes':(1,49152),
         'max_content_bytes':(1,65536),'max_meta_bytes':(2,16384)}
 rows=[]
 for name,(lo,hi) in limits.items():
  for n in (lo-1,lo,hi,hi+1): rows.append(mutation('tool.limits.'+name,'replace',n,'accepted' if lo<=n<=hi else 'invalid_descriptor'))
 table(file,'descriptor.limits_boundaries',rows,limits)
 table(file,'descriptor.enums_annotations',
  [mutation('tool.concurrency','replace',v,'accepted' if v in ('parallel','exclusive') else 'invalid_descriptor') for v in ('parallel','exclusive','serial')]+[
   mutation('tool.replay_class','replace',v,'accepted' if v in ('read_only','idempotent','mutating','external') else 'invalid_descriptor') for v in ('read_only','idempotent','mutating','external','unsafe')]+[
   mutation('tool.annotations.'+p,'replace',v) for p,v in [('read_only',False),('destructive',True),('idempotent',False)]]+[
   mutation('tool.annotations.open_world','replace',True,'accepted')],
  {'read_only_implies':['read_only=true','destructive=false','idempotent=true'],'parallel_implies':'read_only=true'})
 probes=[]
 for size in (16384,16385):
  value=copy.deepcopy(base);value['tool']['output_schema']={'description':''}
  value['tool']['output_schema']['description']='x'*(size-len(pg_canonical(value)))
  assert len(pg_canonical(value))==size
  probes.append(dict(id='pg_bytes_'+str(size),descriptor=value,pg_bytes=size,expected='accepted' if size==16384 else 'invalid_descriptor'))
 for depth in (16,17):
  value=copy.deepcopy(base);nested=0
  for _ in range(depth-4):nested=[nested]
  value['tool']['output_schema']={'enum':[nested]}
  probes.append(dict(id='depth_'+str(depth),descriptor=value,container_depth=depth,expected='accepted' if depth==16 else 'invalid_descriptor'))
 for id,raw,e in [('safe_max',str(MAX_SAFE),'accepted'),('unsafe_plus',str(MAX_SAFE+1),'invalid_descriptor'),
  ('float','1.5','invalid_descriptor'),('exponent','1e3','invalid_descriptor'),('negative_zero','-0','invalid_descriptor'),
  ('lone_surrogate','"\\ud800"','invalid_descriptor')]:
  probes.append(dict(id=id,base_ref='descriptor.v2.read',path='tool.output_schema.enum',raw_json='['+raw+']',expected=e))
 table(file,'descriptor.pg_size_depth_integer_unicode_boundaries',probes,
  {'pg_byte_cap':16384,'depth_cap':16,'safe_integer_max':MAX_SAFE,'depth_measure':'root container=1; child container=parent+1'})
 return descriptors

def frame_vectors():
 f='frames_v2.json'
 for op in ('invoke','prepare','release','inspect'):
  args={'path':'README.md','offset':1} if op=='invoke' else {'install_id':'00000000-0000-0000-0000-000000000001'}
  reservation='v24:tool_call:w1' if op=='invoke' else 'v24:'+op+':w1'
  inp={'operation':op,'reservation':reservation,'args':args}
  if op=='invoke': inp['tool']='read'
  byte_case(f,'frame.request.'+op,'line_json_v2_request','frame_request',inp,frame_request(op,reservation,args,inp.get('tool')))
 trap={'operation':'invoke','reservation':'v24:tool_call:sort','tool':'read','args':{'\ue000':1,'𐀀':2,'a':3}}
 byte_case(f,'frame.request.utf8_sort_trap','line_json_v2_request','frame_request',trap,frame_request(**trap))
 good={'ok':True,'v':2,'result':{'value':{'path':'README.md'},'meta':{}}}
 bad={'ok':False,'v':2,'error':{'code':'not_found','message':'File not found.'}}
 for id,obj,exit_code in [('frame.response.success',good,0),('frame.response.known_error',bad,3)]:
  byte_case(f,id,'line_json_v2_response','fixed_corpus',{'operation':'invoke','exit_code':exit_code},
            compact(obj)+b'\n',extra={'classification':'success' if exit_code==0 else 'known_error'})
 base=compact(good)
 whitespace=[('leading_sp',b' '+base+b'\n'),('leading_ht',b'\t'+base+b'\n'),
  ('trailing_crlf',base+b'\r\n'),('sp_ht_cr',b' \t'+base+b' \t\r\n'),
  ('u2028_string',compact({'ok':True,'v':2,'result':{'value':{'text':'a\u2028b\u2029c'}}})+b'\n')]
 for op,values in [('prepare',[{'prepared':True}]),('release',[{'released':True}]),('inspect',[{'observed':'known'},{'observed':'absent'}])]:
  for value in values:
   whitespace.append((op+'_'+str(next(iter(value.values()))),compact({'ok':True,'v':2,'result':value})+b'\n',op))
 table(f,'frame.response.whitespace_corpus',
  [{'id':row[0],'hex':row[1].hex(),'operation':row[2] if len(row)==3 else 'invoke','exit_code':0,'classification':'success'} for row in whitespace],
  {'single_terminal_raw_lf':True,'accept_json_whitespace':'SP HT CR'})
 invalid=[('eof',b'','eof'),('empty_prefix',b'\n','bad_frame'),('bom',b'\xef\xbb\xbf'+base+b'\n','bad_frame'),
  ('missing_lf',base,'bad_frame'),('nonfinal_lf',base+b'\n ','bad_frame'),('double_lf',base+b'\n\n','extra_frame'),
  ('extra_frame',base+b'\n{}\n','extra_frame'),('tail_junk',base+b'X\n','bad_frame'),
  ('invalid_utf8',b'\xff\n','stdout_not_utf8'),
  ('duplicate_keys',b'{"ok":true,"ok":true,"v":2,"result":{"value":{}}}\n','bad_frame'),
  ('nan',b'{"ok":true,"v":2,"result":{"value":{"x":NaN}}}\n','bad_frame'),
  ('infinity',b'{"ok":true,"v":2,"result":{"value":{"x":Infinity}}}\n','bad_frame'),
  ('lone_surrogate',b'{"ok":true,"v":2,"result":{"value":{"x":"\\ud800"}}}\n','bad_frame'),
  ('wrong_v',b'{"ok":true,"v":1,"result":{"value":{}}}\n','version_mismatch'),
  ('wrong_keys',b'{"ok":true,"v":2,"result":{"value":{}},"extra":1}\n','bad_frame'),
  ('wrong_ok',b'{"ok":1,"v":2,"result":{"value":{}}}\n','bad_frame'),
  ('wrong_result',b'{"ok":true,"v":2,"result":[]}\n','bad_frame'),
  ('wrong_error',b'{"ok":false,"v":2,"error":{"code":"A","message":"x"}}\n','bad_frame'),
  ('u2028_outside',b'{"ok":true,\xe2\x80\xa8"v":2,"result":{"value":{}}}\n','bad_frame'),
  ('exit_mismatch',base+b'\n','bad_frame')]
 for value in (None,[],[1,2],'text',1,True):
  invalid.append(('generic_value_'+str(len(invalid)),compact({'ok':True,'v':2,'result':{'value':value}})+b'\n','success',0,'invoke'))
 for message in ('./a/b','1/2/x','relative/file','x'*1024):
  invalid.append(('safe_error_'+str(len(invalid)),compact({'ok':False,'v':2,'error':{'code':'x','message':message}})+b'\n','known_error',3,'invoke'))
 for label,error in [('empty_code',{'code':'','message':'x'}),('long_code',{'code':'a'*65,'message':'x'}),
   ('message_1025',{'code':'x','message':'x'*1025}),('absolute_path',{'code':'x','message':'/private/tmp/file'}),
   ('unix_single',{'code':'x','message':'/etc'}),('windows',{'code':'x','message':'C:\\private\\file'}),
   ('unc',{'code':'x','message':'\\\\host\\share'}),('stack',{'code':'x','message':'Traceback (call)'}),
   ('env',{'code':'x','message':'OPENAI_API_KEY=redacted'}),('nul_message',{'code':'x','message':'x\x00'}),('extra_error',{'code':'x','message':'x','extra':True})]:
  invalid.append((label,compact({'ok':False,'v':2,'error':error})+b'\n','bad_frame',3,'invoke'))
 for op,result in [('prepare',{'prepared':1}),('release',{'released':False}),('inspect',{'observed':'maybe'}),
                   ('invoke',{'value':{},'meta':[]}),('prepare',{'value':{}})]:
  invalid.append((op+'_shape_'+str(len(invalid)),compact({'ok':True,'v':2,'result':result})+b'\n','bad_frame',0,op))
 table(f,'frame.response.invalid_corpus',
  [{'id':row[0],'hex':row[1].hex(),'operation':row[4] if len(row)>4 else 'invoke',
    'exit_code':row[3] if len(row)>3 else 3 if row[0]=='exit_mismatch' else 0,
    'classification':row[2]} for row in invalid],
  {'reasons':['eof','extra_frame','bad_frame','version_mismatch','stdout_not_utf8']})
 table(f,'frame.process.unknown_outcomes',
  {'limits':{'stdout':65536,'stderr':16384,'stdin':1048576},
   'outcomes':['timeout','stdout_limit','stderr_limit','abnormal_exit'],
   'preflight':[{'id':id,'input':dict(operation=op,reservation='w1',args=args,**extra),'expected':'bad_request'}
     for id,op,args,extra in [('prepare_with_tool','prepare',{},dict(tool='read')),
      ('invoke_missing_tool','invoke',{},{}),('reserved_tool_agent.spawn','invoke',{},dict(tool='agent.spawn')),
      ('invalid_tool','invoke',{},dict(tool='A')),('args_not_object','invoke',[],dict(tool='read'))]]},
  {'class':'unknown','runtime_evidence':'M2_pending'})

def renderer_vectors():
 f='renderers.json'
 read_values=[
  ('empty_file',{'path':'empty','text':'','start_line':0,'end_line':0,'total_lines':0,'final_newline':False,'truncated':False,'truncated_by':None,'next_offset':None}),
  ('empty_line',{'path':'blank','text':'','start_line':1,'end_line':1,'total_lines':1,'final_newline':True,'truncated':False,'truncated_by':None,'next_offset':None}),
  ('page',{'path':'a.txt','text':'one\ntwo','start_line':1,'end_line':2,'total_lines':3,'final_newline':False,'truncated':True,'truncated_by':'lines','next_offset':3}),
  ('control',{'path':'p\n\r\x00😀','text':'\b\f\n\r\t\u0001/\\"\u2028\u2029😀','start_line':1,'end_line':1,'total_lines':1,'final_newline':False,'truncated':False,'truncated_by':None,'next_offset':None}),
  ('oversize_source',{'path':'long','text':'x'*17000,'start_line':1,'end_line':1,'total_lines':1,'final_newline':False,'truncated':False,'truncated_by':None,'next_offset':None})]
 list_values=[
  ('empty',{'path':'.','offset':1,'entries':[],'total':0,'truncated':False,'next_offset':None,'skipped_non_utf8':0,'skipped_special':0}),
  ('mixed',{'path':'.','offset':1,'entries':[{'path':'a','kind':'directory','size':None},{'path':'b','kind':'symlink','size':None},{'path':'c','kind':'file','size':5}], 'total':3,'truncated':False,'next_offset':None,'skipped_non_utf8':1,'skipped_special':1}),
  ('page',{'path':'.','offset':2,'entries':[{'path':'two','kind':'file','size':10}], 'total':3,'truncated':True,'next_offset':3,'skipped_non_utf8':0,'skipped_special':0}),
  ('oversize_path',{'path':'.','offset':1,'entries':[{'path':'p'*50000,'kind':'file','size':0}], 'total':1,'truncated':False,'next_offset':None,'skipped_non_utf8':0,'skipped_special':0})]
 skip={k:0 for k in ('hidden','symlink','binary','too_large','non_utf8','long_lines')}
 search_values=[
  ('no_hits',{'path':'.','offset':1,'hits':[],'total':0,'complete':True,'scanned_files':1,'skipped':skip,'truncated':False,'next_offset':None}),
  ('context',{'path':'.','offset':1,'hits':[{'path':'a.txt','line':3,'column':2,'text':'a\n\r\x00😀','text_truncated':False,'before':[{'line':1,'text':'before1'},{'line':2,'text':'before2'}], 'after':[{'line':4,'text':'after1'},{'line':5,'text':'after2'}]}], 'total':1,'complete':True,'scanned_files':2,'skipped':{**skip,'hidden':1},'truncated':False,'next_offset':None}),
  ('incomplete_page',{'path':'.','offset':2,'hits':[{'path':'b','line':1,'column':1,'text':'hit','text_truncated':False}], 'total':3,'complete':False,'scanned_files':4,'skipped':skip,'truncated':True,'next_offset':3}),
  ('oversize_paths_200',{'path':'.','offset':1,'hits':[{'path':'p'*120,'line':n,'column':1,'text':'x','text_truncated':False,
    'before':[{'line':n,'text':'b'*50}]*2,'after':[{'line':n,'text':'a'*50}]*2} for n in range(1,201)],
    'total':201,'complete':False,'scanned_files':201,'skipped':skip,'truncated':True,'next_offset':201})]
 # Total projection cases deliberately include semantically contradictory pages.
 read_values += [('null_cursor',dict(read_values[2][1],next_offset=None)),
  ('text_tail_lf',dict(read_values[1][1],text='a\n')),
  ('byte_footer',dict(read_values[2][1],truncated_by='bytes'))]
 list_values += [('safe_derived_decimal',dict(list_values[2][1],offset=MAX_SAFE,total=MAX_SAFE,next_offset=None,
   entries=[dict(path='a',kind='file',size=None),dict(path='b',kind='directory',size=1),dict(path='c',kind='symlink',size=None)]))]
 search_values += [('empty_context',dict(search_values[1][1],hits=[dict(path='a',line=1,column=1,text='x',text_truncated=False,before=[],after=[])])),
  ('complete_truncated',dict(search_values[2][1],complete=True)),
  ('safe_sum',dict(search_values[1][1],skipped={k:MAX_SAFE for k in skip},offset=MAX_SAFE,total=MAX_SAFE)),
  ('long_schema_path',dict(search_values[1][1],hits=[dict(path='p'*50000,line=1,column=1,text='x',text_truncated=False)]))]
 out={}
 for key,values in [('read',read_values),('list',list_values),('search',search_values)]:
  cases=[]
  for id,value in values:
   args={'path':value['path']} if key!='search' else {'query':'hit'}
   content,meta=render(key,value)
   measures=budget_measures(args,value,content,meta)
   assert measures['content']==27+len(compact(content[0]['text']))-2
   cases.append({'id':key+'.'+id,'args':args,'value':value,'content':content,'meta':meta,
                 'measures':measures})
  cases.sort(key=lambda c:c['id'].encode('utf-8'))
  table(f,'render.'+key+'.golden',{'renderer':'v24.fs.'+key+'.text','cases':cases},
        {'case_count':len(cases),'single_text_block':True,'meta':{},'counter_identity':'27+E(T)'},
        status='provisional_w2_pending',owner='W1-REFERENCE')
  digest=manifest_digest('v24.fs.'+key+'.text',1,1,
    [{k:v for k,v in case.items() if k in ('id','args','value','content','meta')} for case in cases])
  manifest={'id':'v24.fs.'+key+'.text','version':1,'projection':1,'golden_digest':digest['golden_digest']}
  byte_case(f,'render.manifest.'+key,'renderer_manifest','compact',manifest,compact(manifest),
            status='provisional_w2_pending',owner='W1-REFERENCE',extra={'render_digest':digest['render_digest']})
  out[key]=digest['render_digest']
 table(f,'render.digest.provisional_values',{'ordered_case_ids':{k:[c['id'] for c in next(
   item for item in CASES[f] if item['id']=='render.'+k+'.golden')['input']['cases']]
   for k in ('read','list','search')}},out,
   status='provisional_w2_pending',owner='W1-REFERENCE')
 return out

def q5_vectors():
 """Fixed snapshot probes: expectations are declarations, never reference output."""
 caps={'value':40960,'content':41984,'meta':4096,'frame':60000}
 def lv(entries,total=2,offset=1):
  end=offset+len(entries)-1;truncated=end<total
  return dict(path='.',offset=offset,entries=entries,total=total,truncated=truncated,
              next_offset=offset+len(entries) if truncated else None,skipped_non_utf8=0,skipped_special=0)
 entries=[dict(path=p,kind='file',size=1) for p in ('a','b')]
 short,final=lv(entries[:1]),lv(entries)
 probes=[]
 def add(id,kind,values,expected,*,args=None,budgets=None,**extra):
  probes.append(dict(id=id,input=dict(kind=kind,args={} if args is None else args,
    values=values,caps=caps if budgets is None else budgets,**extra),expected=expected))
 add('footer_nonmonotonic','list',[short,final],{'selected':2},budgets=dict(value=200,content=50,meta=2,frame=300))
 add('all_unfit','list',[short,final],{'error':'entry_too_large'},budgets=dict(caps,content=1))
 add('byte_full_below_limit','list',[short,final],{'selected':1},args={'limit':3},budgets=dict(caps,value=160))
 add('empty_overhead_unfit','list',[],{'error':'output_too_large'},empty_value=lv([],0),budgets=dict(caps,content=1))
 add('empty_complete','list',[],{'selected':0},empty_value=lv([],0))
 add('empty_offset2','list',[],{'error':'offset_out_of_range'},args={'offset':2})
 add('contradictory_cursor','list',[dict(short,next_offset=None)],{'error':'invalid_tool_output'})
 add('contradictory_size','list',[dict(short,entries=[dict(path='d',kind='directory',size=1)])],{'error':'invalid_tool_output'})
 add('decimal_width','list',[lv(entries[:1],total=10,offset=9),lv(entries,total=10,offset=9)],{'selected':2},args={'offset':9})
 add('safe_final_cursor_null','list',[lv(entries[:1],total=MAX_SAFE,offset=MAX_SAFE)],{'selected':1},args={'offset':MAX_SAFE})
 overflow=lv(entries[:1],total=MAX_SAFE,offset=MAX_SAFE);overflow.update(truncated=True,next_offset=MAX_SAFE)
 add('cursor_overflow','list',[overflow],{'error':'invalid_tool_output'},args={'offset':MAX_SAFE})
 skip={k:0 for k in ('hidden','symlink','binary','too_large','non_utf8','long_lines')}
 def sv(n,total,complete=False):
  return dict(path='.',offset=1,hits=[dict(path='a',line=i+1,column=1,text='x',text_truncated=False) for i in range(n)],
   total=total,complete=complete,scanned_files=10000,skipped=skip,truncated=not complete or n<total,
   next_offset=n+1 if not complete or n<total else None)
 add('cutoff_count_full','search',[sv(1,2),sv(2,2)],{'selected':2},args={'limit':2},scan_end='cutoff')
 add('cutoff_before_fill','search',[sv(1,1)],{'error':'search_scope_too_large'},args={'limit':2},scan_end='cutoff')
 add('cutoff_before_offset','search',[],{'error':'search_scope_too_large'},args={'offset':5},scan_end='cutoff')
 # Byte-full requires an observed complete next item; all snapshot stats stay identical.
 first,second=sv(1,2),sv(2,2)
 first_size=budget_measures({},first,*render('search',first))['value']
 add('cutoff_byte_full','search',[first,second],{'selected':1},args={'limit':3},scan_end='cutoff',budgets=dict(caps,value=first_size))
 add('eof_complete_truncated','search',[sv(1,2,True),sv(2,2,True)],{'selected':1},args={'limit':3},scan_end='eof',budgets=dict(caps,value=first_size))
 empty=sv(0,0,True);empty.update(truncated=False,next_offset=None)
 add('search_empty_offset1','search',[],{'selected':0},empty_value=empty,scan_end='eof')
 add('search_empty_offset2','search',[],{'error':'offset_out_of_range'},args={'offset':2},scan_end='eof')
 add('incomplete_empty_invalid','search',[sv(0,0)],{'error':'invalid_tool_output'})
 add('source_error_first','read',[],{'error':'not_utf8'},source_error='not_utf8')
 read_page={'path':'a','text':'one','start_line':1,'end_line':1,'total_lines':2,'final_newline':False,
  'truncated':True,'truncated_by':'bytes','next_offset':2}
 add('read_byte_full','read',[read_page],{'selected':1},args={'offset':1,'limit':3})
 add('first_item_unfit','list',[short],{'error':'entry_too_large'},budgets=dict(caps,content=1))
 add('search_hit_unfit','search',[sv(1,1,True)],{'error':'hit_too_large'},budgets=dict(caps,value=1))
 add('search_offset_past_total','search',[dict(sv(1,1,True),offset=2,hits=[],truncated=False,next_offset=None)],{'error':'invalid_tool_output'},args={'offset':2})
 add('read_line_count_mismatch','read',[dict(read_page,text='one\ntwo')],{'error':'invalid_tool_output'})
 add('read_wrong_truncated_by','read',[dict(read_page,truncated_by='lines')],{'error':'invalid_tool_output'})
 add('read_empty_offset2','read',[],{'error':'offset_out_of_range'},args={'offset':2},
  empty_value=dict(path='empty',text='',start_line=0,end_line=0,total_lines=0,final_newline=False,truncated=False,truncated_by=None,next_offset=None))
 # Each candidate's literal projection and measures are also frozen for Node checks.
 for probe in probes:
  p=probe['input'];probe['candidates']=[]
  for value in p['values']:
   content,meta=render(p['kind'],value)
   probe['candidates'].append(dict(content=content,meta=meta,measures=budget_measures(p['args'],value,content,meta)))
 return probes


def manifest_provider_vectors(descriptors):
 f='manifest_adapter_v2.json'
 adapter={}
 for language,key in [('python','read'),('node','list')]:
  decl={'adapter':'v24.line-json','language':language,'protocol':'v24.line-json.v2','version':2}
  digest=hashlib.sha256(compact(decl)).hexdigest()
  adapter[language]=digest
  byte_case(f,'manifest.adapter.python_read' if language=='python' else 'manifest.adapter.node_list_search',
    'adapter_declaration','compact',decl,compact(decl),extra={'adapter_digest':digest})
 for identity,keys,language,id in [
  ('v24.fs.python',['read'],'python','manifest.five_field_key'),
  ('v24.fs.node',['list','search'],'node','manifest.one_install_two_provides')]:
  manifest={'identity':identity,'version':'1','requires':[],
    'provides':[{'realm':'w1-fixture','key':key,'descriptor':descriptors[key]} for key in keys],
    'adapter_digest':adapter[language]}
  raw=compact(manifest)
  if id=='manifest.one_install_two_provides':
   byte_case(f,id,'manifest_bytes','compact',manifest,raw,
     status='provisional_w2_pending',extra={'manifest_digest':hashlib.sha256(raw).hexdigest()})
  else:
   table(f,id,{'identity':identity,'version':'1','manifest_digest':hashlib.sha256(raw).hexdigest(),
     'adapter_digest':adapter[language],'artifact_digest':'M3-pending','manifest':manifest,
     'manifest_expected_hex':raw.hex(),'manifest_expected_length':len(raw)},
     {'field_count':5,'fields':['identity','version','manifest_digest','artifact_digest','adapter_digest']},
     status='m3_pending',stage='M3')
 table(f,'manifest.artifact_digest_pending',
   {'python_artifact':'v24/s13/plugins/fs_read.py','node_artifact':'v24/s13/plugins/fs_tools.js'},
   {'digest':'M3-pending','reason':'production plugin files do not exist in W1'},
   status='m3_pending',stage='M3')
 f='provider_projection_v2.json'
 for key in ('read','list','search'):
  tool=descriptors[key]['tool']
  projection={'name':key,'description':tool['description'],'parameters':tool['parameters']}
  byte_case(f,'provider.projection.'+key,'provider_tool_projection','compact',projection,compact(projection),
            status='provisional_w2_pending',extra={'descriptor_ref':'descriptor.v2.'+key})
 table(f,'provider.safe_name_mapping',
   [{'name':key,'pin_key':key,'descriptor_key':key,'expected':'accepted'} for key in ('read','list','search')],
   {'projection_keys':['name','description','parameters']})
 table(f,'provider.key_mismatch',
   [{'name':'read','pin_key':'list','descriptor_key':'read','expected':'descriptor_invalid'},
    {'name':'agent.spawn','pin_key':'agent.spawn','descriptor_key':'agent.spawn','expected':'descriptor_invalid'}],
   {'check_before_projection':True})
 b0=ROOT/'v24/b0/golden/provider_requests_v1.json'
 b0_doc=json.loads(b0.read_text(encoding='utf-8'))
 table(f,'provider.v1_bytes_unchanged',
  [{'id':c['id'],'expected_sha256':c['expected_sha256'],'expected_length':c['expected_length']}
   for c in b0_doc['cases']],
  {'source':'v24/b0/golden/provider_requests_v1.json','policy':'read_only_baseline'})


def results_vectors():
 f='results_v2.json'
 success={'value':{'path':'a.txt','text':'hi'},'content':[{'type':'text','text':'hi'}],'meta':{}}
 failure={'error':{'code':'not_found','message':'File not found.'},
          'content':[{'type':'text','text':'Error [not_found]: File not found.'}],'meta':{}}
 unknown={'error':{'code':'timeout','message':'tool process exceeded its deadline'}}
 for id,value in [('result.success_envelope',success),('result.failure_envelope',failure),('result.unknown_envelope',unknown)]:
  byte_case(f,id,'result_output','compact',value,compact(value))
 table(f,'result.usage_wall_ms',
  [{'usage':{'wall_ms':0},'expected':'accepted'},{'usage':{'wall_ms':15},'expected':'accepted'},
   {'usage':{'wall_ms':0,'tokens':1},'expected':'invalid_outcome'}],
  {'allowed_keys':['wall_ms'],'tool_errors_outside_sql_error_v1':True})
 content=[{'type':'text','text':'one'},{'type':'text','text':'二\n三'}]
 byte_case(f,'result.model_text_join','model_text','join_content',content,model_text(content))
 byte_case(f,'result.meta_excluded_from_model_text','model_text','join_content',
   {'content':content,'meta':{'private':'not model text'}},model_text(content),extra={
    'v1_baseline_refs':['tool_message.success.content','tool_message.known_error.content'],
    'v1_source':'v24/b0/golden/tool_messages_v1.json'})
 table(f,'result.budget_domains',
  [{'id':'meta_absent_cap2','meta':None,'cap':2,'measure':2,'expected':'accepted'},
   {'id':'meta_empty_cap2','meta':{},'cap':2,'measure':2,'expected':'accepted'},
   {'id':'meta_nonempty_cap2','meta':{'a':1},'cap':2,'measure':7,'expected':'output_too_large'},
   {'id':'args_object_only','args':{'x':1},'measure':len(compact({'x':1})),'excludes':['frame','LF']},
   {'id':'value_40960','domain':'value','cap':40960,'threshold':40960},
   {'id':'content_41984','domain':'content','cap':41984,'threshold':41984},
   {'id':'meta_4096','domain':'meta','cap':4096,'threshold':4096}],
  {'measures':['args','value','content','meta','frame'],'meta_absent_normalizes_to_empty':True,'prefix_scenarios':q5_vectors(),
   'exact_boundaries':[dict(domain=domain,cap=cap,repeat=n-overhead,expected='accepted' if n<=cap else 'output_too_large')
    for domain,cap,overhead in [('value',40960,11),('content',41984,27),('meta',4096,8)]
    for n in (cap-1,cap,cap+1)],
   'builtin_plugin_meta':[{'meta':None,'expected':'accepted'},{'meta':{},'expected':'accepted'},
    {'meta':{'x':1},'expected':'invalid_tool_output'}]})
 frame_rows=[]
 overhead=len(compact({'ok':True,'v':2,'result':{'value':{'text':''}}}))+1
 for target in (60000,60001,65536,65537):
  n=target-overhead
  assert len(compact({'ok':True,'v':2,'result':{'value':{'text':'x'*n}}}))+1==target
  frame_rows.append({'target':target,'text_repeat':'x','repeat_count':n,
    'classification':'within_builtin_target' if target<=60000 else 'over_builtin_target_transport_valid' if target<=65536 else 'stdout_limit_unknown'})
 table(f,'result.frame_60000_60001_65536_65537',frame_rows,
   {'frame_target':60000,'transport_hard_cap':65536,'overhead':overhead})
 table(f,'result.replay_no_rerender',
  {'journal_event':'dispatch_finished','tool_message_content':'frozen rendered text','renderer_digest_changed':True},
  {'replay_source':'journal tool_message','rerender':False},status='m4_pending',stage='M4')
 table(f,'lifecycle.journal_replay_no_rerender',
  {'recovery':'restart_after_dispatch_finished','journal_model_text':'frozen rendered text'},
  {'second_spawn':False,'model_text_source':'journal'},status='m4_pending',owner='M4-LIFECYCLE',stage='M4')
 table(f,'lifecycle.tool_message_model_text_stable',
  {'content':[{'type':'text','text':'a'},{'type':'text','text':'b'}],'meta':{'ignored':1}},
  {'model_text':'a\nb','journal_event_types_unchanged':True},
  status='m4_pending',owner='M4-LIFECYCLE',stage='M4')


def schema_vectors():
 f='schema_v2.json'
 allow=['type','properties','required','additionalProperties','items','minItems','maxItems',
        'minLength','maxLength','minimum','maximum','enum','description']
 deny=['$ref','$defs','definitions','$schema','$id','oneOf','anyOf','allOf','not','if','then','else',
       'pattern','format','default','const','number','patternProperties','propertyNames',
       'uniqueItems','minProperties','maxProperties','exclusiveMinimum','exclusiveMaximum',
       'multipleOf','contentEncoding','readOnly','writeOnly','examples']
 positive={'type':{'type':'string'},'properties':{'type':'object','properties':{'x':{'type':'string'}},'additionalProperties':False},
  'required':{'type':'object','properties':{'x':{'type':'string'}},'required':['x'],'additionalProperties':False},
  'additionalProperties':{'type':'object','additionalProperties':False},
  'items':{'type':'array','items':{'type':'string'}},'minItems':{'type':'array','items':{},'minItems':0},
  'maxItems':{'type':'array','items':{},'maxItems':1},'minLength':{'type':'string','minLength':0},
  'maxLength':{'type':'string','maxLength':1},'minimum':{'type':'integer','minimum':-1},
  'maximum':{'type':'integer','maximum':1},'enum':{'enum':[None,True,1,'1']},
  'description':{'description':'note'}}
 table(f,'schema.keyword_allow_deny',
  {'allowed':[{'keyword':k,'schema':positive[k],'expected':'accepted'} for k in allow],
   'denied':[{'keyword':k,'schema':{k:True},'expected':'unsupported_schema'} for k in deny],
   'invalid_allowed':[{'keyword':k,'schema':dict(positive[k],**{k:v}),'expected':'unsupported_schema'} for k,v in [
    ('type',17),('properties',[]),('required',['absent']),('additionalProperties',{}),('items',[]),
    ('minItems',-1),('maxItems',-1),('minLength',-1),('maxLength',-1),('minimum',1.5),('maximum',True),
    ('enum',[]),('description',False)]]},
  {'allow_keywords':allow,'deny_keywords':deny,'closed':True})
 table(f,'schema.type_nullable',
  [{'schema':{'type':['integer','null'],'minimum':1},'instance':x,'expected':e}
   for x,e in [(None,'accepted'),(1,'accepted'),(0,'minimum'),('1','type')]]+[
   {'schema':{'type':['object','array','string','null'],'additionalProperties':False,'items':{}},'expected':'accepted'},
   {'schema':{'type':['string','string']},'expected':'unsupported_schema'},
   {'schema':{'type':'number'},'expected':'unsupported_schema'}],
  {'types':['object','array','string','integer','boolean','null'],'array_len':[2,4]})
 table(f,'schema.required_additional_items',
  [{'schema':{'type':'object','properties':{'x':{}},'required':['x'],'additionalProperties':False},
    'instance':{},'expected':{'path':'$.x','rule':'required'}},
   {'schema':{'type':'object','properties':{'x':{}},'required':['x','x'],'additionalProperties':False},'expected':'unsupported_schema'},
   {'schema':{'type':'object','required':['x'],'additionalProperties':False},'expected':'unsupported_schema'},
   {'schema':{'type':'object','additionalProperties':{}},'expected':'unsupported_schema'},
   {'schema':{'type':'array'},'expected':'unsupported_schema'},
   {'schema':{'type':'array','items':{}},'expected':'accepted'}],
  {'object_requires_explicit_additionalProperties':True,'array_requires_items':True})
 table(f,'schema.enum_json_distinct',
  [{'values':[{'a':1,'b':2},{'b':2,'a':1}],'expected':'duplicate_enum'},
   {'values':[[1,2],[2,1]],'expected':'accepted'},
   {'values':[True,1,'1',None],'expected':'accepted'}],
  {'object_key_order_ignored':True,'array_order_preserved':True,'json_types_distinct':True})
 bounds=[]
 for bound,cap in [('depth',16),('nodes',256),('properties',128),('enum',64)]:
  for count in (cap,cap+1):
   if bound=='depth':
    schema={}
    for _ in range(count-1):schema={'type':'array','items':schema}
   elif bound=='nodes':
    schema={'type':'object','properties':{f'p{i:03}':{'type':'array','items':{}} if i<count-129 else {} for i in range(128)},'additionalProperties':False}
   elif bound=='properties':schema={'type':'object','properties':{f'p{i:03}':{} for i in range(count)},'additionalProperties':False}
   else:schema={'enum':list(range(count))}
   bounds.append(dict(id=bound+'_'+str(count),bound=bound,count=count,schema=schema,expected='accepted' if count==cap else 'unsupported_schema'))
 table(f,'schema.schema_bounds',bounds,
  {'depth':16,'nodes':256,'properties':128,'enum':64,'measure':'root schema node=1; each properties child/items is one schema node'})
 table(f,'schema.instance_bounds',
  [{'schema':{'type':'string','minLength':2,'maxLength':2},'instance':s,'expected':e}
   for s,e in [('😀a','accepted'),('😀','min_length'),('😀ab','max_length')]]+[
   {'schema':{'type':'integer','minimum':0,'maximum':1},'instance':-1,'expected':'minimum'},
   {'schema':{'type':'integer','minimum':0,'maximum':1},'instance':2,'expected':'maximum'},
   {'schema':{'type':'array','items':{},'minItems':1,'maxItems':2},'instance':[],'expected':'min_items'},
   {'schema':{'type':'array','items':{},'minItems':1,'maxItems':2},'instance':[1,2,3],'expected':'max_items'}],
  {'string_count':'Unicode scalar','first_error_only':True})
 table(f,'schema.root_parameters',
  [{'schema':{'type':'object','additionalProperties':False},'kind':'parameters','expected':'accepted'},
   {'schema':{},'kind':'parameters','expected':'unsupported_schema'},
   {'schema':{},'kind':'output_schema','expected':'accepted'}],
  {'defaults_injected':False})
 table(f,'schema.error_path_order',
  [{'schema':{'type':'object','properties':{'z':{},'a':{}},'required':['z','a'],'additionalProperties':False},'instance':{},'first':{'path':'$.z','rule':'required'}},
   {'schema':{'type':'object','properties':{},'additionalProperties':False},'instance':{'\ue000':1,'𐀀':2},'first':{'path':'$["\ue000"]','rule':'additional'}},
   {'schema':{'type':'object','properties':{},'additionalProperties':False},'instance':{'a-b':1},'first':{'path':'$["a-b"]','rule':'additional'}},
   {'schema':{'type':'object','properties':{'items':{'type':'array','items':{'type':'string'}}},'additionalProperties':False},'instance':{'items':[0]},'first':{'path':'$.items[0]','rule':'type'}},
   {'schema':{'type':'object','properties':{'𐀀':{'type':'string'},'\ue000':{'type':'string'}},'additionalProperties':False},'instance':{'𐀀':0,'\ue000':0},'first':{'path':'$["\ue000"]','rule':'type'}}],
  {'order':['required_schema_array','extra_utf8_bytes','properties_utf8_bytes','array_index'],
   'rules':['type','required','additional','enum','min_length','max_length','minimum','maximum','min_items','max_items']})
 table(f,'schema.no_default_injection',
  {'schema':{'type':'object','properties':{'limit':{'type':'integer','description':'default 10'}},
             'required':[],'additionalProperties':False},'args':{}},
  {'args_after_host_validation':{},'default_keyword':'forbidden'})

def contract_vectors():
 f='tool_contracts.json'
 shared={'root_relative_posix':True,'absolute_inside_root':'accepted','absolute_outside_root':'path_escape',
  'dotdot':'path_escape','dotgit':'path_excluded','hidden_default':'skip','symlink_components':'symlink_denied',
  'strict_utf8':True,'nul':'invalid_path'}
 table(f,'tool.shared_paths_encoding_order',shared,
  {'path_bytes':'UTF-8 unsigned','normalization':'none','root_env':'V24_WORKSPACE_ROOT'})
 read_inputs=[
  {'id':'empty_offset1','args':{'path':'empty','offset':1},'expected':{'total_lines':0,'start_line':0,'end_line':0,'truncated':False}},
  {'id':'empty_offset2','args':{'path':'empty','offset':2},'expected':{'error':'offset_out_of_range'}},
  {'id':'tail_lf','args':{'path':'tail'},'expected':{'final_newline':True,'total_lines':1}},
  {'id':'cr_preserved','args':{'path':'cr'},'expected':{'text':'a\r'}},
  {'id':'window_bad_utf8','args':{'path':'bad-window','offset':1},'expected':{'error':'not_utf8'}},
   {'id':'outside_bad_utf8','args':{'path':'bad-outside','offset':1,'limit':1},'expected':{'value':{'text':'a','total_lines':1},'note':'unselected trailing invalid byte is not decoded'}},
   {'id':'outside_bad_utf8_offset2','args':{'path':'bad-outside','offset':2,'limit':1},'expected':{'error':'offset_out_of_range'}},
   {'id':'window_bad_utf8_offset2','args':{'path':'bad-window','offset':1,'limit':1},'expected':{'error':'not_utf8'}},
   {'id':'empty_line','args':{'path':'blank'},'expected':{'value':{'text':'','start_line':1,'end_line':1,'total_lines':1,'final_newline':True}}},
  {'id':'line_16384','args':{'path':'line-ok'},'expected':{'error':'accepted'}},
  {'id':'line_16385','args':{'path':'line-long'},'expected':{'error':'line_too_long'}},
  {'id':'file_1m','args':{'path':'one-meg'},'expected':{'error':'accepted'}},
  {'id':'file_1m_plus1','args':{'path':'too-big'},'expected':{'error':'file_too_large'}},
  {'id':'truncated_lines','args':{'path':'many','limit':2},'expected':{'truncated_by':'lines','next_offset':3}},
  {'id':'truncated_bytes','args':{'path':'wide','limit':2},'expected':{'truncated_by':'bytes'}},
  {'id':'cursor','args':{'path':'many','offset':3,'limit':2},'expected':{'next_offset':5}}]
 table(f,'tool.read.contract',{'tool':'read','language':'python','inputs':read_inputs,
  'error_codes':['invalid_path','path_escape','path_excluded','symlink_denied','not_found','permission_denied',
   'not_a_file','binary_file','not_utf8','file_too_large','offset_out_of_range','line_too_long','io_error','root_unavailable']},
  {'output_keys':['path','text','start_line','end_line','total_lines','final_newline','truncated','truncated_by','next_offset'],
   'renderer':'render.read.golden','fixtures':'portable_fixture_tree'})
 list_inputs=[
  {'id':'nonrecursive','args':{'path':'.','recursive':False},'expected':{'depth':1}},
  {'id':'dfs','args':{'path':'.','recursive':True},'expected':{'order':'UTF8 path bytes'}},
  {'id':'symlink','args':{'path':'.'},'expected':{'symlink':'listed_not_followed'}},
  {'id':'hidden','args':{'path':'.','include_hidden':False},'expected':{'skipped_non_utf8':0}},
  {'id':'offset','args':{'path':'.','offset':2,'limit':1},'expected':{'next_offset':3}},
  {'id':'10000','args':{'path':'large'},'expected':{'error':'accepted'}},
  {'id':'10001','args':{'path':'too-many'},'expected':{'error':'directory_too_large'}}]
 table(f,'tool.list.contract',{'tool':'list','language':'node','inputs':list_inputs,
  'error_codes':['invalid_path','path_escape','path_excluded','symlink_denied','not_found','permission_denied',
   'not_a_directory','directory_too_large','offset_out_of_range','entry_too_large','io_error','root_unavailable']},
  {'output_keys':['path','offset','entries','total','truncated','next_offset','skipped_non_utf8','skipped_special'],
   'renderer':'render.list.golden','same_install_as':'search'})
 search_inputs=[
  {'id':'literal_first','args':{'query':'needle'},'expected':{'one_match_per_line':True}},
  {'id':'ascii_fold','args':{'query':'ABC','ignore_case':True},'expected':{'fold':'ASCII-only'}},
  {'id':'unicode_column','args':{'query':'x'},'expected':{'column':'Unicode codepoint, 1-based'}},
  {'id':'glob_basic','args':{'query':'x','glob':'src/*.py'},'expected':{'accepted':True}},
  {'id':'glob_invalid','args':{'query':'x','glob':'[x]'},'expected':{'error':'invalid_glob'}},
  {'id':'dfs','args':{'query':'x'},'expected':{'order':'DFS pre-order'}},
  {'id':'context','args':{'query':'x','context':2},'expected':{'max_before_after':2}},
  {'id':'text_500','args':{'query':'x'},'expected':{'text_codepoints':500,'text_truncated':True}},
  {'id':'skip_counters','args':{'query':'x'},'expected':{'skipped':['hidden','symlink','binary','too_large','non_utf8','long_lines']}},
  {'id':'10000_files','args':{'query':'x'},'expected':{'error':'accepted'}},
  {'id':'file_count_cutoff','args':{'query':'x'},'expected':{'error':'search_scope_too_large'}},
  {'id':'complete_empty_offset1','args':{'query':'none','offset':1},'expected':{'complete':True,'total':0}},
  {'id':'complete_empty_offset2','args':{'query':'none','offset':2},'expected':{'error':'offset_out_of_range'}},
  {'id':'incomplete_nonempty','args':{'query':'x','offset':1},'expected':{'complete':False,'hits_nonempty':True,'next_offset':2}},
  {'id':'cutoff_before_page','args':{'query':'x','offset':5},'expected':{'error':'search_scope_too_large'}}]
 table(f,'tool.search.contract',{'tool':'search','language':'node','inputs':search_inputs,
  'error_codes':['invalid_path','path_escape','path_excluded','symlink_denied','not_found','permission_denied',
   'not_a_directory','invalid_glob','search_scope_too_large','offset_out_of_range','hit_too_large','io_error','root_unavailable']},
  {'output_keys':['path','offset','hits','total','complete','scanned_files','skipped','truncated','next_offset'],
   'renderer':'render.search.golden','budget_timing':'M3 timing gate'})
 fixture_nodes=[
  {'path':'empty','kind':'file','bytes_hex':''}, {'path':'tail','kind':'file','bytes_hex':'610a'},
  {'path':'cr','kind':'file','bytes_hex':'610d0a'}, {'path':'bad-window','kind':'file','bytes_hex':'ff0a'},
  {'path':'bad-outside','kind':'file','bytes_hex':'610aff'}, {'path':'line-ok','kind':'file','recipe':{'repeat_hex':'61','count':16384}},
  {'path':'line-long','kind':'file','recipe':{'repeat_hex':'61','count':16385}},
  {'path':'one-meg','kind':'file','recipe':{'repeat_hex':'61','count':1048576}},
  {'path':'too-big','kind':'file','recipe':{'repeat_hex':'61','count':1048577}},
  {'path':'many','kind':'file','recipe':{'lines':['a']*4,'final_newline':True}},
  {'path':'wide','kind':'file','recipe':{'lines':['a'*10000,'b'*10000,'c'],'final_newline':False}},
  {'path':'large','kind':'directory','recipe':{'regular_files':10000,'name':'f%05d.txt','content_hex':''}},
  {'path':'too-many','kind':'directory','recipe':{'regular_files':10001,'name':'f%05d.txt','content_hex':''}},
  {'path':'link','kind':'symlink','target':'empty'}, {'path':'socket','kind':'special','tag':'unix_socket'},
  {'path':'binary','kind':'file','bytes_hex':'610062'}, {'path':'dotfile','kind':'file','bytes_hex':'78'},
  {'path':'.git/config','kind':'file','bytes_hex':'78'}, {'path':'nested/child.txt','kind':'file','bytes_hex':'6e6565646c650a'},
  {'path':'nested','kind':'directory','children':['nested/child.txt']}]
 table(f,'tool.fixture_tree.portable_nodes',
  {'root':'fixture-root','nodes':fixture_nodes,'non_utf8_name':{'tag':'bytes','hex':'ff'},
   'symlink_component':{'path':'link/target','resolves_through':'link'},
   'search_files':{'max_count':10000,'cutoff':{'regular_files':10001,'result':'search_scope_too_large'}}},
  {'platform_independent_tags':True,'large_files':'repeat_hex recipe materializes exact bytes'})
 table(f,'tool.search_budget_file_count',{'file_limit':10000,'hit_limit':200,'context_limit':2},
  {'file_count_exceed':'search_scope_too_large','timing':'not_frozen'})
 table(f,'tool.search_budget_timing_m3_pending',{'wall_clock_seconds':12},
  {'status':'m3_pending','deterministic_w1_pass':False},status='m3_pending',owner='M3-TOOLS',stage='M3')

def concrete_contracts():
 """Declarative fixtures and exact outcomes; never executes real tools."""
 cases={c['id']:c for c in CASES['tool_contracts.json']}
 nodes=cases['tool.fixture_tree.portable_nodes']['input']['nodes']
 bypath={n['path']:n for n in nodes}
 bypath['bad-outside']['bytes_hex']='610aff'  # two lines; second remains undecoded on page 1
 bypath['bad-window']['bytes_hex']='610aff0a'  # selected second line is not UTF-8
 bypath['one-meg']['recipe']={'repeat_hex':'61'*16383+'0a','count':64}
 bypath['many']['recipe']={'lines':['a']*6,'final_newline':True}
 bypath['wide']['recipe']={'lines':['a'*16000,'b'*16000,'c'*16000],'final_newline':False}
 nodes.append({'path':'blank','kind':'file','bytes_hex':'0a'})
 read=cases['tool.read.contract']
 def rv(path,text,start,end,total,final,truncated=False,by=None,cursor=None):
  return dict(path=path,text=text,start_line=start,end_line=end,total_lines=total,final_newline=final,
   truncated=truncated,truncated_by=by,next_offset=cursor)
 values={
  'empty_offset1':rv('empty','',0,0,0,False),
  'tail_lf':rv('tail','a',1,1,1,True), 'cr_preserved':rv('cr','a\r',1,1,1,True),
  'empty_line':rv('blank','',1,1,1,True),
  'outside_bad_utf8':rv('bad-outside','a',1,1,2,False,True,'lines',2),
  'line_16384':rv('line-ok','a'*16384,1,1,1,False),
  'file_1m':rv('one-meg','a'*16383+'\n'+'a'*16383,1,2,64,True,True,'bytes',3),
  'truncated_lines':rv('many','a\na',1,2,6,True,True,'lines',3),
  'truncated_bytes':rv('wide','a'*16000+'\n'+'b'*16000,1,2,3,False,True,'bytes',3),
  'cursor':rv('many','a\na',3,4,6,True,True,'lines',5)}
 errors={'empty_offset2':'offset_out_of_range','window_bad_utf8':'not_utf8','window_bad_utf8_offset2':'not_utf8',
  'outside_bad_utf8_offset2':'not_utf8','line_16385':'line_too_long','file_1m_plus1':'file_too_large'}
 for row in read['input']['inputs']:
  if row['id']=='truncated_bytes':row['args']['limit']=3
  if row['id']=='window_bad_utf8_offset2':row['args'].update(offset=2,limit=1)
  row['fixture_ref']='tool.fixture_tree.portable_nodes'
  row['expected']={'value':values[row['id']]} if row['id'] in values else {'error':errors[row['id']]}
  row['renderer_ref']='render.read.golden'
 # Shared path probes use symbolic roots, never machine-specific absolute paths.
 cases['tool.shared_paths_encoding_order']['input']['probes']=[
  dict(id=id,path=path,expected=e) for id,path,e in [
   ('absolute_inside',{'root_relative':'tail','form':'absolute_under_root'},'tail'),
   ('absolute_outside',{'outside_root':'tail'},'path_escape'),('dotdot','nested/../tail','path_escape'),
   ('dotgit','.git/config','path_excluded'),('nul','a\x00b','invalid_path'),
   ('symlink_component','link/target','symlink_denied'),('collapse_dot','./nested//child.txt','nested/child.txt')]]
 # Small list tree is self-contained; root fixtures for read do not affect it.
 tree=[dict(path='a',kind='directory',size=None),dict(path='a/child',kind='file',size=1),
       dict(path='b',kind='symlink',size=None),dict(path='c',kind='file',size=2),
       dict(path='.hidden',kind='file',size=1),dict(path='.git',kind='directory',size=None),
       dict(path={'bytes_hex':'ff'},kind='file',size=0),dict(path='socket',kind='special',size=None)]
 listing=cases['tool.list.contract']
 listing['input']['fixture_tree']=tree
 def lv(entries,total,offset=1,cursor=None):
  return dict(path='.',offset=offset,entries=entries,total=total,truncated=cursor is not None,
   next_offset=cursor,skipped_non_utf8=1,skipped_special=1)
 root=[tree[i] for i in (0,2,3)];recursive=[tree[i] for i in (0,1,2,3)]
 for row in listing['input']['inputs']:
  id=row['id'];row['renderer_ref']='render.list.golden'
  if id=='10000':
   row['expected']={'value':dict(lv([dict(path='large/f%05d.txt'%i,kind='file',size=0) for i in range(500)],10000,cursor=501),path='large',skipped_non_utf8=0,skipped_special=0)}
  elif id=='10001':row['expected']={'error':'directory_too_large'}
  elif id=='dfs':row['expected']={'value':lv(recursive,4)}
  elif id=='offset':row['expected']={'value':lv([root[1]],3,offset=2,cursor=3)}
  elif id=='hidden':
   row['args']['include_hidden']=True
   row['expected']={'value':lv([tree[4]]+root,4)}
  else:row['expected']={'value':lv(root,3)}
  row['fixture_ref']='tool.fixture_tree.portable_nodes' if id in ('10000','10001') else 'inline:tool.list.contract'
 # Search cases each carry exact file bytes, so scanning and hit counts have no ambient inputs.
 search=cases['tool.search.contract'];skip={k:0 for k in ('hidden','symlink','binary','too_large','non_utf8','long_lines')}
 def hit(path='a.txt',line=1,column=1,text='x',**extra):
  return dict(path=path,line=line,column=column,text=text,text_truncated=False,**extra)
 def sv(hits,total=None,complete=True,scanned=1,cursor=None,offset=1,skipped=None):
  return dict(path='.',offset=offset,hits=hits,total=len(hits) if total is None else total,complete=complete,
   scanned_files=scanned,skipped=skip if skipped is None else skipped,truncated=cursor is not None,next_offset=cursor)
 rows={
  'literal_first':('needle needle\n',{},sv([hit(column=1,text='needle needle')])),
  'ascii_fold':('abc ABC Ää\n',{},sv([hit(text='abc ABC Ää')])),
  'unicode_column':('😀éx\r\n',{},sv([hit(column=3,text='😀éx')])),
  'glob_basic':('x\n',{'path':'src/a.py'},sv([hit(path='src/a.py')])),
  'dfs':('x\n',{},sv([hit()])),
  'context':('before1\nbefore2\nx\nafter1\nafter2\n',{},sv([hit(line=3,before=[dict(line=1,text='before1'),dict(line=2,text='before2')],after=[dict(line=4,text='after1'),dict(line=5,text='after2')])])),
  'text_500':('x'+'a'*500+'\n',{},sv([dict(hit(text='x'+'a'*499),text_truncated=True)])),
  'complete_empty_offset1':('x\n',{},sv([],scanned=1))}
 for row in search['input']['inputs']:
  id=row['id'];row['renderer_ref']='render.search.golden'
  if id in rows:
   text,extra,value=rows[id];row['fixture_tree']=[dict(path=extra.get('path','a.txt'),kind='file',bytes_hex=text.encode().hex())]
   row['expected']={'value':value}
  elif id=='glob_invalid':row.update(fixture_tree=[],expected={'error':'invalid_glob'})
  elif id=='complete_empty_offset2':row.update(fixture_tree=[dict(path='a.txt',kind='file',bytes_hex='780a')],expected={'error':'offset_out_of_range'})
  elif id in ('file_count_cutoff','cutoff_before_page'):
   row.update(fixture_tree=[dict(path='.',kind='directory',recipe={'regular_files':10001,'name':'f%05d.txt','content_hex':'780a'})],
              expected={'error':'search_scope_too_large'})
   row['args'].update(query='none',limit=200)
  elif id=='10000_files':
   row.update(fixture_tree=[dict(path='.',kind='directory',recipe={'regular_files':10000,'name':'f%05d.txt','content_hex':'780a'})],
              expected={'value':sv([],scanned=10000)})
   row['args']['query']='none'
  elif id=='incomplete_nonempty':
   row['args']['limit']=1
   row.update(fixture_tree=[dict(path='a.txt',kind='file',bytes_hex='780a780a')],expected={'value':sv([hit()],total=2,complete=False,scanned=1,cursor=2)})
  elif id=='skip_counters':
   row.update(fixture_tree=[dict(path='a.txt',kind='file',bytes_hex='780a'),
     dict(path='.hidden',kind='file',bytes_hex='78'),dict(path='link',kind='symlink',target='a.txt'),
     dict(path='binary',kind='file',bytes_hex='00'),dict(path='too-big',kind='file',recipe={'repeat_hex':'61','count':1048577}),
     dict(path={'bytes_hex':'ff'},kind='file',bytes_hex='78'),dict(path='bad',kind='file',bytes_hex='ff'),
     dict(path='long',kind='file',recipe={'repeat_hex':'61','count':4097})],
     expected={'value':sv([hit()],scanned=1,skipped=dict(hidden=1,symlink=1,binary=1,too_large=1,non_utf8=2,long_lines=1))})
 # Make DFS and non-ASCII byte ordering observable across multiple sibling subtrees.
 dfs=next(row for row in search['input']['inputs'] if row['id']=='dfs')
 dfs['fixture_tree']=[dict(path=p,kind='file',bytes_hex='780a') for p in ('a/child','b','é','𐀀')]
 dfs['expected']={'value':sv([hit(path=p) for p in ('a/child','b','é','𐀀')],scanned=4)}
 search['input']['stateless_rescan']={'fixture_policy':'same immutable tree for each request','cursor_state':'none',
  'requests':[{'query':'x','offset':1,'limit':1},{'query':'x','offset':2,'limit':1}],
  'fixture_tree':[dict(path='a.txt',kind='file',bytes_hex='780a780a')],
  'expected':[sv([hit()],total=2,cursor=2),sv([hit(line=2)],total=2,offset=2)]}
 search['input']['skip_definitions']={
  'hidden':'skipped hidden entry/subtree root, excluding .git; no descendant counting',
  'symlink':'skipped symlink entry; never follow', 'binary':'regular file with NUL in first 8192 bytes',
  'too_large':'regular file exceeds 1 MiB', 'non_utf8':'non-UTF8 name or skipped undecodable file',
  'long_lines':'file with a line exceeding 4096 UTF-8 bytes; entire file skipped before matching'}
 # Add all glob operators and every forbidden metacharacter as concrete cases.
 for pattern,path,match in [('src/*.py','src/a.py',True),('src/*.py','src/sub/a.py',False),
  ('src/**/a?.py','src/sub/ab.py',True),('?.txt','é.txt',True)]:
  search['input']['inputs'].append(dict(id='glob_'+str(len(search['input']['inputs'])),args=dict(query='x',glob=pattern),
   fixture_tree=[dict(path=path,kind='file',bytes_hex='780a')],expected={'value':sv([hit(path=path)] if match else [],scanned=1)},renderer_ref='render.search.golden'))
 for pattern in ('{x}','x}','[x]','x]','x\\y'):
  search['input']['inputs'].append(dict(id='invalid_glob_'+str(len(search['input']['inputs'])),args=dict(query='x',glob=pattern),fixture_tree=[],expected={'error':'invalid_glob'},renderer_ref='render.search.golden'))


def provider_and_result(descriptors):
 manifest_provider_vectors(descriptors)
 results_vectors(); schema_vectors(); contract_vectors(); concrete_contracts()

def run(output):
 for cases in CASES.values(): cases.clear()
 render_digests=renderer_vectors()
 descriptors=descriptor_vectors(render_digests)
 frame_vectors(); provider_and_result(descriptors)
 # Filesystem tool contracts are first behaviorally validated in M3.
 for case in CASES['tool_contracts.json']:
  case['first_production_stage'] = 'M3'
  case['status'] = 'm3_pending'
 for name,cases in CASES.items():
  payload={'format':FORMAT,'domain_file':name,'cases':cases}
  (output/name).write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 (output/'design_conformance.json').write_text(
   (ROOT/'v24/s13/vectors/design_conformance.json').read_text(encoding='utf-8'),encoding='utf-8')
 return {k:len(v) for k,v in CASES.items()}

def main(argv=None):
 parser=argparse.ArgumentParser()
 parser.add_argument('--output',required=True,type=Path)
 args=parser.parse_args(argv)
 lexical=args.output.expanduser().absolute(); dest=lexical.resolve(strict=False)
 def inside(path,parent):
  try:return os.path.commonpath((str(path),str(parent)))==str(parent)
  except ValueError:return False
 if inside(lexical,ROOT) or inside(dest,ROOT): parser.error('candidate output must resolve outside repository')
 if dest.exists(): parser.error('refusing to overwrite existing candidate directory')
 dest.parent.mkdir(parents=True,exist_ok=True)
 stage=Path(tempfile.mkdtemp(prefix='.w1-stage-',dir=dest.parent))
 try:
  counts=run(stage)
  dest.mkdir()  # Atomic absent-destination guard; never replace a racing directory.
  for source in stage.iterdir():
   with (dest/source.name).open('xb') as target:
    target.write(source.read_bytes())
   source.unlink()
  stage.rmdir()
 except BaseException:
  # Preserve failed capture/staging evidence; retry must choose a fresh path.
  raise
 print(f'[captured] {dest}; cases={counts}')
 return 0
if __name__=='__main__': raise SystemExit(main())
