'use strict';
// Independent W1-only Node reference, not a production plugin.
const crypto = require('node:crypto');
const fs = require('node:fs');
function scalar(s) {
  if (typeof s !== 'string') throw Error('not_string');
  for(let i=0;i<s.length;i++) {
    const n=s.charCodeAt(i);
    if(n>=0xD800&&n<=0xDBFF) {
      if(++i>=s.length||s.charCodeAt(i)<0xDC00||s.charCodeAt(i)>0xDFFF) throw Error('lone_surrogate');
    } else if(n>=0xDC00&&n<=0xDFFF) throw Error('lone_surrogate');
  }
  return s;
}
const bytes=s=>Buffer.from(s,'utf8');
const quoted=s=>JSON.stringify(scalar(s));
function encode(v,pg=false) {
  if(v===null)return 'null';
  if(typeof v==='string')return quoted(v);
  if(typeof v==='boolean')return v?'true':'false';
  if(typeof v==='number') {
    if(!Number.isSafeInteger(v)||Object.is(v,-0))throw Error('unsafe_integer');
    return String(v);
  }
  if(Array.isArray(v))return '['+v.map(x=>encode(x,pg)).join(pg?', ':',')+']';
  if(typeof v==='object')return '{'+Object.keys(v).sort((a,b)=>{
    const x=bytes(a),y=bytes(b);
    return pg&&x.length!==y.length?x.length-y.length:Buffer.compare(x,y);
  }).map(k=>quoted(k)+(pg?': ':':')+encode(v[k],pg)).join(pg?', ':',')+'}';
  throw Error('unsupported_json_value');
}
const compact=v=>bytes(encode(v));
const pgCanonical=v=>bytes(encode(v,true));
const sha=v=>crypto.createHash('sha256').update(v).digest('hex');
function strictParse(src) {
  if(Buffer.isBuffer(src))src=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(src);
  let i=0;
  const ws=()=>{while(i<src.length&&/[ \t\r\n]/.test(src[i]))i++;};
  function string(){
    if(src[i]!=='"')throw Error('json_string');
    const start=i++;
    while(i<src.length){if(src[i]==='\\'){i+=2;continue;}
      if(src[i++]==='"')return scalar(JSON.parse(src.slice(start,i)));}
    throw Error('json_string');
  }
  function value(){
    ws();const c=src[i];
    if(c==='"')return string();
    if(c==='{'){
      i++;ws();const o=Object.create(null),seen=new Set();if(src[i]==='}'){i++;return o;}
      while(true){ws();const k=string();if(seen.has(k))throw Error('duplicate_key');seen.add(k);
        ws();if(src[i++]!==':')throw Error('json_colon');o[k]=value();ws();
        if(src[i]==='}'){i++;return o;}if(src[i++]!==',')throw Error('json_comma');}
    }
    if(c==='['){i++;ws();const a=[];if(src[i]===']'){i++;return a;}
      while(true){a.push(value());ws();if(src[i]===']'){i++;return a;}
        if(src[i++]!==',')throw Error('json_comma');}}
    if(src.startsWith('true',i)){i+=4;return true;}
    if(src.startsWith('false',i)){i+=5;return false;}
    if(src.startsWith('null',i)){i+=4;return null;}
    const m=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(src.slice(i));
    if(m){i+=m[0].length;if(m[0]==='-0'||/[.eE]/.test(m[0]))throw Error('non_integer_number');
      const n=Number(m[0]);if(!Number.isSafeInteger(n))throw Error('unsafe_integer');return n;}
    throw Error('json_value');
  }
  const out=value();ws();if(i!==src.length)throw Error('json_trailing');return out;
}
function frameRequest(operation,reservation,args,tool){
  if(!['invoke','prepare','release','inspect'].includes(operation)||!args||Array.isArray(args)||typeof args!=='object')throw Error('bad_request');
  const frame={v:2,operation,reservation,args};
  if(operation==='invoke'){if(typeof tool!=='string'||! /^[a-z][a-z0-9_.-]{0,127}$/.test(tool)||tool==='agent.spawn')throw Error('bad_request');frame.tool=tool;}
  else if(tool!=null)throw Error('bad_request');
  return Buffer.concat([compact(frame),bytes('\n')]);
}
function classifyResponse(raw,operation='invoke',exitCode=0){
  if(!raw.length)return 'eof';let s;
  try{s=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw);}catch{return 'stdout_not_utf8';}
  const lf=raw.filter(x=>x===10).length;if(lf>1)return 'extra_frame';
  if(lf!==1||raw[raw.length-1]!==10||s.startsWith('\uFEFF'))return 'bad_frame';
  let o;try{o=strictParse(s.slice(0,-1).replace(/^[ \t\r]+|[ \t\r]+$/g,''));}catch{return 'bad_frame';}
  if(!o||Array.isArray(o)||typeof o!=='object')return 'bad_frame';
  if(o.v!==2)return 'version_mismatch';
  if(typeof o.ok!=='boolean')return 'bad_frame';
  const keys=x=>Object.keys(x).sort().join(',');
  if(o.ok){
    if(exitCode!==0||keys(o)!=='ok,result,v'||!o.result||Array.isArray(o.result)||typeof o.result!=='object')return 'bad_frame';
    const r=o.result;
    if(operation==='invoke'){
      if(!Object.hasOwn(r,'value')||Object.keys(r).some(k=>!['value','meta'].includes(k))||('meta'in r&&(!r.meta||Array.isArray(r.meta)||typeof r.meta!=='object')))return 'bad_frame';
    }else if(operation==='prepare'&&(keys(r)!=='prepared'||r.prepared!==true))return 'bad_frame';
    else if(operation==='release'&&(keys(r)!=='released'||r.released!==true))return 'bad_frame';
    else if(operation==='inspect'&&(keys(r)!=='observed'||!['known','absent'].includes(r.observed)))return 'bad_frame';
    else if(!['invoke','prepare','release','inspect'].includes(operation))return 'bad_frame';
    return 'success';
  }
  if(exitCode!==3||keys(o)!=='error,ok,v'||!o.error||Array.isArray(o.error)||typeof o.error!=='object'||keys(o.error)!=='code,message')return 'bad_frame';
  if(typeof o.error.code!=='string'||! /^[a-z][a-z0-9_]{0,63}$/.test(o.error.code)||typeof o.error.message!=='string'||bytes(o.error.message).length>1024||['\0','Traceback (','stack trace','DEEPSEEK_API_KEY=','OPENAI_API_KEY='].some(x=>o.error.message.includes(x))||/(?:^|\s)(?:\/\S*|[A-Za-z]:[\\/]|\\\\)/.test(o.error.message))return 'bad_frame';
  return 'known_error';
}
function render(kind,v){
  const d=x=>x===null?'null':String(x);let t;
  if(kind==='read'){
    t=v.total_lines===0?'[empty file]':v.text;
    if(v.truncated)t+='\n\n[Showing lines '+d(v.start_line)+'-'+d(v.end_line)+' of '+d(v.total_lines)+'. Use offset='+d(v.next_offset)+' to continue.]';
  }else if(kind==='list'){
    const lines=v.entries.map(e=>e.kind==='directory'?e.path+'/':e.kind==='symlink'?e.path+'@':e.path+' ('+d(e.size)+' B)');
    t=lines.length?lines.join('\n'):'[empty directory]';
    if(v.truncated)t+='\n\n[Showing '+d(v.offset)+'-'+d(BigInt(v.offset)+BigInt(v.entries.length)-1n)+' of '+d(v.total)+'. Use offset='+d(v.next_offset)+' to continue.]';
  }else if(kind==='search'){
    const lines=[];for(const h of v.hits){
      for(const c of h.before||[])lines.push(h.path+'-'+d(c.line)+'- '+c.text);
      lines.push(h.path+':'+d(h.line)+':'+d(h.column)+': '+h.text);
      for(const c of h.after||[])lines.push(h.path+'-'+d(c.line)+'- '+c.text);
    }
    t=lines.length?lines.join('\n'):'[no matches]';const n=v.hits.length;
    const skipped=Object.values(v.skipped).reduce((a,b)=>a+BigInt(b),0n);
    t+='\n\n[hits '+(n?d(v.offset):'0')+'-'+(n?d(BigInt(v.offset)+BigInt(n)-1n):'0')+' of '+d(v.total)+(v.complete?'':'+')+'; scanned '+d(v.scanned_files)+'; skipped '+skipped.toString()+']';
    if(v.truncated)t+='\n[Use offset='+d(v.next_offset)+' to continue.]';
  }else throw Error('unknown_renderer');
  return [[{type:'text',text:t}],{}];
}
function renderCount(kind,v) {
  const d=x=>x===null?'null':String(x);let t=[];
  if(kind==='read') {
    t=[v.total_lines===0?'[empty file]':v.text];
    if(v.truncated)t.push('\n\n[Showing lines ',d(v.start_line),'-',d(v.end_line),' of ',d(v.total_lines),'. Use offset=',d(v.next_offset),' to continue.]');
  } else if(kind==='list') {
    for(const e of v.entries) {if(t.length)t.push('\n');t.push(e.path);
      t.push(...(e.kind==='directory'?['/']:e.kind==='symlink'?['@']:[' (',d(e.size),' B)']));}
    if(!t.length)t=['[empty directory]'];
    if(v.truncated)t.push('\n\n[Showing ',d(v.offset),'-',d(BigInt(v.offset)+BigInt(v.entries.length)-1n),' of ',d(v.total),'. Use offset=',d(v.next_offset),' to continue.]');
  } else {
    const line=a=>{if(t.length)t.push('\n');t.push(...a);};
    for(const h of v.hits) {
      for(const c of h.before??[])line([h.path,'-',d(c.line),'- ',c.text]);
      line([h.path,':',d(h.line),':',d(h.column),': ',h.text]);
      for(const c of h.after??[])line([h.path,'-',d(c.line),'- ',c.text]);
    }
    if(!t.length)t=['[no matches]'];const n=v.hits.length;
    const skipped=Object.values(v.skipped).reduce((a,b)=>a+BigInt(b),0n);
    t.push('\n\n[hits ',n?d(v.offset):'0','-',n?d(BigInt(v.offset)+BigInt(n)-1n):'0',' of ',d(v.total),v.complete?'':'+','; scanned ',d(v.scanned_files),'; skipped ',d(skipped),']');
    if(v.truncated)t.push('\n[Use offset=',d(v.next_offset),' to continue.]');
  }
  let size=27;for(const token of t)for(const c of token)size+='"\\\b\f\n\r\t'.includes(c)?2:c.codePointAt(0)<32?6:bytes(c).length;
  return size;
}
const escapedPayloadBytes=s=>bytes(quoted(s)).length-2;
const budgetMeasures=(args,value,content,meta)=>({args:compact(args).length,value:compact(value).length,content:compact(content).length,meta:compact(meta==null?{}:meta).length,frame:compact({ok:true,v:2,result:{value}}).length+1});
function manifestDigest(id,version,projection,cases){
  const ordered=[...cases].sort((a,b)=>Buffer.compare(bytes(a.id),bytes(b.id)));
  const golden_digest=sha(compact(ordered));
  return {golden_digest,render_digest:sha(compact({id,version,projection,golden_digest}))};
}
function selectPrefix(kind,args,values,caps) {
  let selected=null;
  for(let k=1;k<=values.length;k++) {
    const [content,meta]=render(kind,values[k-1]);
    const m=budgetMeasures(args,values[k-1],content,meta);
    if(['value','content','meta','frame'].every(n=>m[n]<=caps[n])) selected=k;
  }
  return selected;
}
function pageError(kind,args,v) {
  const unsafe=x=>typeof x==='number'?!Number.isSafeInteger(x):x&&typeof x==='object'?Object.values(x).some(unsafe):false;
  if(unsafe(v))return true;
  const offset=args.offset??1,limit=args.limit??({read:2000,list:500,search:200}[kind]);
  let k,total,truncated;
  if(kind==='read') {
    total=v.total_lines;
    if(total===0)return v.text!==''||v.start_line!==0||v.end_line!==0||v.final_newline!==false||v.truncated!==false||v.truncated_by!==null||v.next_offset!==null;
    k=v.end_line-v.start_line+1;
    if(v.start_line!==offset||offset<1||v.end_line<offset||v.end_line>total||k<1||k>limit)return true;
    const lines=v.text.split('\n');
    if(lines.length!==k||lines.some(s=>bytes(s).length>16384))return true;
    truncated=v.end_line<total;
    if(v.truncated_by!==(truncated?(k===limit?'lines':'bytes'):null))return true;
  }else {
    const items=kind==='list'?v.entries:v.hits;k=items.length;total=v.total;
    if(v.offset!==offset||k>limit)return true;
    if(k===0)return !(offset===1&&total===0&&(kind!=='search'||v.complete)&&!v.truncated&&v.next_offset===null);
    if(BigInt(offset)+BigInt(k)-1n>BigInt(total))return true;
    if(kind==='list'&&items.some(e=>(e.kind==='file')!==(typeof e.size==='number')))return true;
    truncated=BigInt(offset)+BigInt(k)-1n<BigInt(total)||(kind==='search'&&!v.complete);
  }
  const cursor=truncated?BigInt(offset)+BigInt(k):null;
  return v.truncated!==truncated||(cursor===null?v.next_offset!==null:cursor>9007199254740991n||v.next_offset===null||BigInt(v.next_offset)!==cursor);
}
function pageDecision(p) {
  const {kind,args,values,caps}=p;
  if(p.source_error)return {error:p.source_error};
  if(values.some(v=>pageError(kind,args,v)))return {error:'invalid_tool_output'};
  if(!values.length) {
    if(p.scan_end==='cutoff')return {error:'search_scope_too_large'};
    if(!p.empty_value||(args.offset??1)!==1)return {error:'offset_out_of_range'};
    if(pageError(kind,args,p.empty_value))return {error:'invalid_tool_output'};
    const [c,m]=render(kind,p.empty_value),sizes=budgetMeasures(args,p.empty_value,c,m);
    return Object.keys(caps).every(n=>sizes[n]<=caps[n])?{selected:0}:{error:'output_too_large'};
  }
  const selected=selectPrefix(kind,args,values,caps);
  if(selected===null)return {error:{read:'line_too_long',list:'entry_too_large',search:'hit_too_large'}[kind]};
  if(kind==='search'&&p.scan_end==='cutoff'&&!(selected===values.length&&selected===(args.limit??200)||selected<values.length))return {error:'search_scope_too_large'};
  return {selected};
}
const modelText=content=>bytes(content.map(b=>b.text).join('\n'));
function run(req){const p=req.payload,a=req.action;
  if(a==='pg')return pgCanonical(p).toString('hex');
  if(a==='compact')return compact(p).toString('hex');
  if(a==='frame')return frameRequest(p.operation,p.reservation,p.args,p.tool).toString('hex');
  if(a==='render'){const out=render(p.kind,p.value);if(compact(out[0]).length!==renderCount(p.kind,p.value))throw Error('counter_mismatch');return out;}
  if(a==='digest')return manifestDigest(p.id,p.version,p.projection,p.cases);
  if(a==='model')return modelText(p).toString('hex');
  if(a==='classify')return classifyResponse(Buffer.from(p.hex,'hex'),p.operation,p.exit_code);
  if(a==='strict'){try{strictParse(p.raw);return 'accepted';}catch(e){return e.message;}}
  if(a==='budget')return budgetMeasures(p.args,p.value,p.content,p.meta);
  if(a==='select')return selectPrefix(p.kind,p.args,p.values,p.caps);
  if(a==='page')return pageDecision(p);
  if(a==='preflight'){try{frameRequest(p.operation,p.reservation,p.args,p.tool);return 'accepted';}catch(e){return e.message;}}
  throw Error('unknown_action');
}
if(require.main===module){
  try{const input=JSON.parse(fs.readFileSync(0,'utf8'));const requests=Array.isArray(input)?input:[input];
    process.stdout.write(JSON.stringify(requests.map(req=>({id:req.id,result:run(req)})))+'\n');}
  catch(e){process.stderr.write(String(e.message)+'\n');process.exitCode=1;}
}
module.exports={strictParse,pgCanonical,compact,frameRequest,classifyResponse,render,escapedPayloadBytes,budgetMeasures,manifestDigest,modelText,selectPrefix,pageDecision};
