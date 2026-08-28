from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class DuckBudget:
    preview_rows:int=500
    brief_rows:int=20
    max_brief_rows:int=50
    query_chars:int=16000
    timeout_ms:int=120000
    memory_limit:str='512 MiB'
    max_result_bytes:int=256*1024
    source_rows:int=100000
    source_bytes:int=64*1024*1024
    def validate(self):
        if not (1<=self.brief_rows<=self.max_brief_rows): raise ValueError('invalid brief budget')
        if self.preview_rows<1 or self.query_chars<1 or self.timeout_ms<1: raise ValueError('invalid DuckDB budget')
