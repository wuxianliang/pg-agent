"""Bounded DuckDB result formatting for agent-visible observations."""
from __future__ import annotations
import base64, datetime as dt, decimal, json, math, uuid
from typing import Any
SUMMARY_LIMIT=256*1024

def json_safe(value: Any) -> Any:
    if value is None or isinstance(value,(str,bool,int)): return value
    if isinstance(value,float): return value if math.isfinite(value) else str(value)
    if isinstance(value,(decimal.Decimal,dt.date,dt.datetime,dt.time,uuid.UUID)): return str(value)
    if isinstance(value,(bytes,bytearray,memoryview)): return base64.b64encode(bytes(value)).decode('ascii')
    if isinstance(value,(list,tuple)): return [json_safe(v) for v in value]
    if isinstance(value,dict): return {str(k):json_safe(v) for k,v in value.items()}
    raise TypeError(f'unsupported result value: {type(value).__name__}')

def bounded_result(columns, rows, limit=500) -> dict:
    if limit<1: raise ValueError('limit must be positive')
    rows=list(rows); truncated=len(rows)>limit
    sample=rows[:limit]
    out={'success':True,'columns':list(columns),'data':[json_safe(r) for r in sample],'row_count':len(sample),'truncated':truncated}
    encoded=json.dumps(out,ensure_ascii=False,separators=(',',':'))
    if len(encoded.encode('utf-8'))<=SUMMARY_LIMIT: return out
    while out['data'] and len(json.dumps(out,ensure_ascii=False,separators=(',',':')).encode('utf-8'))>SUMMARY_LIMIT:
        out['data'].pop(); out['truncated']=True; out['row_count']=len(out['data'])
    out['result_truncated_by_bytes']=True
    return out
