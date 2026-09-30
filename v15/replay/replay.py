"""ReplayLLM: serve recorded frames by (path, iteration). Zero worker edits."""
from __future__ import annotations

import psycopg2

from v15.replay.trace import TraceInvalid, index_frames
from v15.worker import connect_worker, parse_json


class ReplayLLM:
    def __init__(self, dsn: str, owner: str, trace: dict) -> None:
        self.dsn = dsn
        self.owner = owner
        self.frames = index_frames(trace)
        self.used: set[tuple[str, int]] = set()

    def leftover_llm(self) -> list[tuple[str, int]]:
        leftover = []
        for key, step in self.frames.items():
            if step.get("logical_digest") is not None and key not in self.used:
                leftover.append(key)
        return leftover

    def complete(self, logical_digest: str, n: int, request: dict, llm_config=None) -> dict:
        if not isinstance(logical_digest, str) or type(n) is not int:
            raise TypeError("logical_digest and n")
        if not isinstance(request, dict):
            raise TypeError("request")
        attempt_id = request.get("attempt_id")
        conn = connect_worker(self.dsn)
        try:
            cur = conn.cursor()
            if type(n) is not int or n != 1 or attempt_id is None:
                cur.execute(
                    "SELECT v15.v15_replay_missing(%s, %s)",
                    (attempt_id, self.owner),
                )
                conn.commit()
                raise TraceInvalid("missing did not raise")
            cur.execute("SELECT v15.v15_replay_attempt_context(%s)", (attempt_id,))
            ctx = parse_json(cur.fetchone()[0])
            key = (ctx["path"], int(ctx["iteration"]))
            frame = self.frames.get(key)
            if frame is None or frame.get("logical_digest") is None:
                cur.execute(
                    "SELECT v15.v15_replay_missing(%s, %s)",
                    (attempt_id, self.owner),
                )
                conn.commit()
                raise TraceInvalid("missing did not raise")
            cur.execute(
                "SELECT v15.v15_replay_assert_digest(%s, %s, %s)",
                (attempt_id, self.owner, frame["logical_digest"]),
            )
            conn.commit()
            self.used.add(key)
            content = frame["response_content"]
            if not isinstance(content, str):
                raise TraceInvalid("response_content")
            return {"content": content, "cost_usd": 0}
        except psycopg2.Error:
            conn.rollback()
            raise
        finally:
            conn.close()
