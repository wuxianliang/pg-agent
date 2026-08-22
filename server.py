"""启动 pgembed 嵌入式 PostgreSQL，供整个测试流程复用。

用法:
    uv run server.py status   # 查看状态
    uv run server.py start    # 启动（幂等）
    uv run server.py stop     # 停止
    uv run server.py uri      # 打印连接串
"""
import sys
from pathlib import Path

import pgembed

PGDATA = Path(__file__).parent / ".pgdata"


def get_server() -> pgembed.PostgresServer:
    server = pgembed.get_server(PGDATA)
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()
    return server


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        server = get_server()
        print("running at:", server.get_uri())
    elif cmd == "stop":
        server = pgembed.get_server(PGDATA)
        server.cleanup()
        print("stopped")
    elif cmd == "uri":
        server = get_server()
        print(server.get_uri())
    elif cmd == "status":
        if not (PGDATA / "PG_VERSION").exists():
            print("not initialized:", PGDATA)
            return
        server = pgembed.get_server(PGDATA)
        pid = server.get_pid()
        print("pgdata:", PGDATA)
        print("pid:", pid if pid else "(not running)")
        if pid:
            print("uri:", server.get_uri())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
