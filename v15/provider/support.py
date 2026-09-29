"""Seed and open helpers shared by the provider gate and smoke. No network."""
from __future__ import annotations

import json

from v15.protocol.render_prompt import render_system

SEED_SCOPE = "00000000-0000-4000-8000-0000000000b1"
FLASH_PROFILE = "00000000-0000-4000-8000-0000000000a2"
FLASH_SCOPE = "00000000-0000-4000-8000-0000000000b2"
_REPL = {"timeout_ms": 30000}
_PROTOCOL = {
    "max_invoke_input_length": 100000,
    "truncation_prefix_ratio": 0.7,
    "max_repl_output_length": 4000,
}


def seed_flash_profile(cur) -> None:
    cur.execute(
        """
        SELECT v15.v15_register_profile(
          %s, %s::jsonb, %s::jsonb, %s::jsonb, '[]'::jsonb
        )
        """,
        (
            FLASH_PROFILE,
            json.dumps({"model": "deepseek-flash"}),
            json.dumps(_REPL),
            json.dumps(_PROTOCOL),
        ),
    )
    cur.execute(
        "SELECT v15.v15_register_scope(%s, %s)",
        (FLASH_SCOPE, FLASH_PROFILE),
    )


def open_invoke(
    conn,
    invoke_id: str,
    *,
    scope_id: str = SEED_SCOPE,
    max_io: int = 3,
    pool_id: str | None = None,
    system: str | None = None,
) -> None:
    if system is None:
        system = render_system(recursion_available=True, bindings=[])
    ceilings = json.dumps(
        {
            "max_iterations": 10,
            "max_depth": 8,
            "max_io_attempts": max_io,
            "max_statement_ms": 30000,
        }
    )
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(
          %s, %s, NULL, '[]'::jsonb, %s, %s::jsonb, %s, NULL
        )
        """,
        (invoke_id, scope_id, pool_id, ceilings, system),
    )
    conn.commit()
