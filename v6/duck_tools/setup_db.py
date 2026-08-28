from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v6.load import load_stage,run_psql
DB='agent_v6_duck_tools'
def main():
 s=get_server(); run_psql(s,'postgres',f'DROP DATABASE IF EXISTS {DB} WITH (FORCE);'); run_psql(s,'postgres',f'CREATE DATABASE {DB};'); run_psql(s,DB,'CREATE EXTENSION IF NOT EXISTS vector;'); load_stage(s,DB,'duck_tools'); print('[ready]',DB); return 0
if __name__=='__main__': raise SystemExit(main())
