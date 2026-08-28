"""Conservative read-only validator for the locked DuckDB wheel."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any
import duckdb

FORBIDDEN_TOKENS = {
    'INSERT','UPDATE','DELETE','MERGE','COPY','CREATE','ALTER','DROP','TRUNCATE',
    'ATTACH','DETACH','CONNECT','DISCONNECT','INSTALL','LOAD','CALL','PRAGMA',
    'SET','RESET','USE','SECRET','EXPORT','VACUUM','CHECKPOINT','MACRO','TRIGGER',
}
FORBIDDEN_FUNCTIONS = {
    'postgres_scan','postgres_scan_pushdown','postgres_query','postgres_execute',
    'read_csv','read_csv_auto','read_json','read_json_auto','read_parquet','glob','httpfs',
}

@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    tokens: tuple[str, ...]
    statement_type: str

class QueryValidationError(ValueError):
    def __init__(self, type_: str, problem: str, solution: str):
        super().__init__(problem)
        self.envelope = {'success':False,'Type':type_,'Phase':'Validation','Problem':problem[:1000],'Solution':solution[:1000]}

def _tokens(sql: str) -> list[tuple[str,int]]:
    out=[]; i=0; n=len(sql)
    while i<n:
        c=sql[i]
        if c.isspace(): i+=1; continue
        if sql.startswith('--',i):
            j=sql.find('\n',i+2); i=n if j<0 else j+1; continue
        if sql.startswith('/*',i):
            j=sql.find('*/',i+2)
            if j<0: raise QueryValidationError('DUCK_PARSE_ERROR','unterminated block comment','Close the block comment.')
            i=j+2; continue
        if c in "'\"`":
            quote=c; j=i+1
            while j<n:
                if sql[j]==quote:
                    if j+1<n and sql[j+1]==quote: j+=2; continue
                    j+=1; break
                if quote=="'" and sql[j]=='\\' and j+1<n: j+=2; continue
                j+=1
            if j>n or (j==n and sql[n-1]!=quote):
                raise QueryValidationError('DUCK_PARSE_ERROR','unterminated quoted literal or identifier','Close the quoted value or identifier.')
            i=j; continue
        if c.isalpha() or c=='_':
            j=i+1
            while j<n and (sql[j].isalnum() or sql[j]=='_'): j+=1
            out.append((sql[i:j].upper(),i)); i=j; continue
        i+=1
    return out

def validate_read_query(sql: str, con: duckdb.DuckDBPyConnection | None = None) -> ValidatedQuery:
    if not isinstance(sql,str) or not sql.strip():
        raise QueryValidationError('DUCK_ARGUMENT_ERROR','query is empty','Provide one DuckDB SELECT statement.')
    if len(sql)>16000:
        raise QueryValidationError('DUCK_ARGUMENT_ERROR','query exceeds 16000 characters','Shorten the query.')
    owned=False
    if con is None:
        con=duckdb.connect(); owned=True
        con.execute('SET autoinstall_known_extensions=false'); con.execute('SET autoload_known_extensions=false'); con.execute('SET enable_external_access=false')
    try:
        try: statements=con.extract_statements(sql)
        except Exception as exc: raise QueryValidationError('DUCK_PARSE_ERROR',str(exc),'Correct the DuckDB SQL syntax.') from exc
        if len(statements)!=1:
            raise QueryValidationError('DUCK_PARSE_ERROR',f'expected one statement, got {len(statements)}','Send exactly one read-only statement.')
        stype=str(statements[0].type).upper()
        if not stype.endswith('SELECT'):
            raise QueryValidationError('DUCK_READ_ONLY_VIOLATION',f'outer statement type is {stype}','Use a single SELECT statement.')
        toks=_tokens(sql)
        for idx,(tok,pos) in enumerate(toks):
            if tok in FORBIDDEN_TOKENS:
                raise QueryValidationError('DUCK_READ_ONLY_VIOLATION',f'forbidden token {tok} at character {pos}','Use a read-only SELECT without DML, DDL, configuration, or external access.')
            if tok.lower() in FORBIDDEN_FUNCTIONS:
                raise QueryValidationError('DUCK_EXTERNAL_ACCESS_FORBIDDEN',f'forbidden function {tok.lower()}','Query only registered workbench artifacts; do not read files or PostgreSQL directly.')
            # Tokenizer is intentionally conservative: detect function names even
            # when capitalization differs; quoted strings/identifiers were skipped.
            if idx+1<len(toks) and toks[idx+1][0] == '(' and tok.lower() in FORBIDDEN_FUNCTIONS:
                raise QueryValidationError('DUCK_EXTERNAL_ACCESS_FORBIDDEN',f'forbidden function {tok.lower()}','Use wb_duck_register for PostgreSQL source snapshots.')
        return ValidatedQuery(sql=sql.strip().rstrip(';'),tokens=tuple(t for t,_ in toks),statement_type=stype)
    finally:
        if owned: con.close()
