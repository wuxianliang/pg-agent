"""连通性测试 v2：直接测两个库的 LLM 调用函数。"""
import json
import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server


def conn(server, db):
    c = psycopg2.connect(server.get_uri(db))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SET openai.api_uri = 'https://api.deepseek.com/v1'")
        cur.execute(f"SET openai.api_key = '{os.environ['DEEPSEEK_API_KEY']}'")
        cur.execute("SET openai.model   = 'deepseek-chat'")
    return c


def main():
    server = get_server()

    msgs = json.dumps([{"role": "user", "content": '只回复这个JSON，把 n 换成 42: {"ok": true, "n": 0}'}])

    c1 = conn(server, "agent_fixed")
    with c1.cursor() as cur:
        cur.execute("SELECT call_llm(%s::jsonb)", (msgs,))
        print("[fixed  call_llm]      ", cur.fetchone()[0][:150])
    c1.close()

    c2 = conn(server, "agent_func")
    with c2.cursor() as cur:
        cur.execute("SELECT sql_retry('http_call_llm(jsonb)'::regproc, %s::jsonb, 2) ->> 'raw'", (msgs,))
        print("[func   http_call_llm] ", cur.fetchone()[0][:150])
    c2.close()

    print("\nLLM 连通 OK")


if __name__ == "__main__":
    main()
