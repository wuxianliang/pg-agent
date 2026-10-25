"""v24 host execution layer.

The kernel keeps the single write entry point and the ten-table domain.  This
package contains only the trusted, single-writer host: a synchronous RPC client
for the frozen public surface, a durable JSONL journal, bounded process
execution scaffolding for M-P, and the v24 DeepSeek adapter.  Importing this
package has no side effects and opens no sockets.
"""
from __future__ import annotations

__all__ = ["db", "journal", "worker", "process_io", "deepseek", "smoke"]
