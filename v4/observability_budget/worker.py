"""W6 worker: normalize bounded LLM metrics. No secrets. No SQL-side routing."""
from __future__ import annotations

import json
import time
from typing import Any

from v4.queue_kinds.worker import AgentWorker as BaseWorker

DB = "agent_v4_observability"
ALLOWED_METRIC_KEYS = {
    "queue", "queue_kind", "msg_id", "worker_id", "attempts", "duration_ms",
    "model", "provider", "input_tokens", "output_tokens", "total_tokens", "cost_usd",
}


def normalize_metrics(metrics: dict | None, **extra) -> dict:
    out = {}
    src = dict(metrics or {})
    src.update({k: v for k, v in extra.items() if v is not None})
    for k in ALLOWED_METRIC_KEYS:
        if k in src and src[k] is not None:
            out[k] = src[k]
    return out


class AgentWorker(BaseWorker):
    def process_message(self, queue: str, payload: dict) -> dict:
        if queue != "llm_requests":
            body = super().process_message(queue, payload)
            if isinstance(body, dict):
                body.setdefault("metrics", normalize_metrics(
                    {},
                    queue=queue,
                    queue_kind={"embed_requests": "embed", "sql_heavy_requests": "sql_heavy"}.get(queue),
                    model=self.model,
                    provider="openai",
                ))
            return body

        t0 = time.time()
        last: Exception | None = None
        attempts = max(1, self.llm_retries + 1)
        used = 0
        out: Any = None
        for i in range(attempts):
            used = i + 1
            try:
                if self.llm_fn is not None:
                    out = self.llm_fn(
                        payload["messages"],
                        model=self.model,
                        api_uri=self.api_uri,
                        api_key=self.api_key,
                    )
                else:
                    from v4.plugin_taxonomy.worker import call_llm
                    out = call_llm(
                        payload["messages"],
                        model=self.model,
                        api_uri=self.api_uri,
                        api_key=self.api_key,
                        num_retries=0,
                    )
                last = None
                break
            except Exception as exc:
                last = exc
                time.sleep(0.05 * (i + 1))
        if last is not None:
            raise last
        duration_ms = round((time.time() - t0) * 1000, 3)
        raw = out
        metrics: dict = {}
        if isinstance(out, dict) and ("raw" in out or "metrics" in out):
            raw = out.get("raw")
            if isinstance(raw, dict):
                raw = json.dumps(raw, ensure_ascii=False)
            metrics = dict(out.get("metrics") or {})
        elif isinstance(out, dict):
            raw = json.dumps(out, ensure_ascii=False)
        return {
            "raw": raw,
            "metrics": normalize_metrics(
                metrics,
                queue=queue,
                queue_kind="llm",
                attempts=used,
                duration_ms=duration_ms,
                model=self.model,
                provider="openai",
                worker_id="worker-1",
            ),
        }
