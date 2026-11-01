"""Versioned UI migration registry (currently intentionally empty)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class Migration:
    from_version: int
    to_version: int
    describe: str
    apply: Callable

MIGRATIONS: tuple[Migration, ...] = ()

def plan(env, loaded: dict, current: dict) -> list[Migration]:
    if loaded.get("ui_state_version") != current.get("ui_state_version"):
        return []
    return []

def run_migrations(env, plan_: list[Migration]) -> None:
    for migration in plan_:
        migration.apply(env)
