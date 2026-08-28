"""Redacted DuckDB exception envelopes."""
from __future__ import annotations
import re
_SECRET=re.compile(r'(?i)(postgres(?:ql)?://[^\s"\']+|(?:password|api[_-]?key|token|secret)\s*[=:]\s*[^\s,;]+)')
def redact(text: str) -> str: return _SECRET.sub('[REDACTED]',str(text))[:1000]
def error_envelope(exc: Exception, *, phase='DuckDB', request_id=None, op_seq=None) -> dict:
    name=type(exc).__name__.lower(); msg=redact(str(exc))
    if 'interrupt' in name or 'interrupt' in msg.lower(): typ='DUCK_TIMEOUT'
    elif 'memory' in name or 'memory' in msg.lower(): typ='DUCK_MEMORY_LIMIT'
    elif 'parser' in name or 'syntax' in msg.lower(): typ='DUCK_PARSE_ERROR'
    elif 'binder' in name or 'catalog' in name: typ='DUCK_EXECUTION_ERROR'
    else: typ='DUCK_EXECUTION_ERROR'
    out={'success':False,'Type':typ,'Phase':phase,'Problem':msg,'Solution':'根据错误修正 DuckDB 查询后重试。'}
    if request_id is not None: out['request_id']=request_id
    if op_seq is not None: out['op_seq']=op_seq
    return out
