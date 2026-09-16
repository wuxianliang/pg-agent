import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v9.load import load_stage, run_psql

DB = 'agent_v9_ctx_queue'

def main() -> int:
    s = get_server()
    run_psql(s, 'postgres', f'DROP DATABASE IF EXISTS {DB} WITH (FORCE);')
    run_psql(s, 'postgres', f'CREATE DATABASE {DB};')
    run_psql(s, DB, 'CREATE EXTENSION IF NOT EXISTS vector;')
    load_stage(s, DB, 'ctx_queue')
    print('[ready]', DB)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
