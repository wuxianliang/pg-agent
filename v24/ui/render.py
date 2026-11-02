"""Durable projection: emitted tool text is verbatim; credential hits refuse rendering."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from v24.host.tool_results import join_content

_TEXT_LIMIT = 2000
_ARG_LIMIT = 500
_SECRET_KEYS = frozenset({"authorization", "api_key", "deepseek_api_key", "openai_api_key", "password", "dsn", "database_url"})
_SECRET_PATTERNS = (re.compile(r"(?i)\bBearer\s+\S+"), re.compile(r"(?i)postgres(?:ql)?://\S+"))


@dataclass(frozen=True)
class StepRecord:
    name: str
    type: str
    output: str
    effect_id: str | None = None


def _safe(value):
    if isinstance(value, dict):
        return any(str(key).lower() in _SECRET_KEYS or _safe(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_safe(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    return False


def _bounded(text: str, limit: int = _TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, {len(text)} chars total]"


def _record(name, kind, output, effect_id=None, *, secret_source=None):
    # Reject the record, never redact it. Check displayed text as well as its
    # source: waiting payloads may be supplied separately from the projection.
    if _safe(output) or _safe(secret_source):
        raise ValueError("render_secret_detected")
    return StepRecord(name, kind, output, None if effect_id is None else str(effect_id))


def render_effect(effect: dict) -> StepRecord | None:
    if not isinstance(effect, dict):
        raise ValueError("invalid_effect")
    kind, status = effect.get("kind"), effect.get("status")
    effect_id = effect.get("effect_id")
    if status in ("ready", "claimed"):
        return None
    if status == "cancelled":
        return _record(f"{kind} · cancelled", "error", "cancelled", effect_id, secret_source=effect)
    if kind not in ("model_call", "tool_call"):
        return None
    outcome = effect.get("outcome") or {}
    if status == "unknown":
        result = (outcome.get("body") or {}).get("result") or {}
        error = (result.get("output") or {}).get("error") or {}
        reason = str(outcome.get("reason") or effect.get("reason") or result.get("reason") or error.get("code") or "unknown")
        if kind == "model_call":
            name = "model · unknown"
        else:
            request = effect.get("request") or {}
            key = request.get("tool") or request.get("key") or "unknown"
            name = f"tool · {key} · unknown"
        return _record(name, "error", reason, effect_id, secret_source=effect)
    if status == "failed":
        if kind == "model_call":
            result = outcome.get("body", {}).get("result", {})
            reason = result.get("reason") or result.get("class") or "failed"
            return _record("model · failed", "error", _bounded(str(reason)), effect_id, secret_source=effect)
        content = outcome.get("body", {}).get("result", {}).get("output", {}).get("content", [])
        key = (effect.get("request") or {}).get("tool") or (effect.get("request") or {}).get("key") or "unknown"
        return _record(f"tool · {key} (error)", "tool", join_content(content), effect_id, secret_source=effect)
    result = outcome.get("body", {}).get("result", {})
    if kind == "tool_call":
        output = result.get("output") or {}
        request = effect.get("request") or {}
        key = request.get("tool") or request.get("key") or request.get("input", {}).get("tool") or "unknown"
        content = output.get("content", [])
        return _record(f"tool · {key}", "tool", join_content(content), effect_id, secret_source=effect)
    model = result.get("result", result)
    if isinstance(model.get("final"), dict):
        return _record("model · final", "llm", model["final"].get("text", ""), effect_id, secret_source=effect)
    calls = model.get("tool_calls")
    if isinstance(calls, list):
        rows = []
        for call in calls:
            key = str(call.get("key", "unknown"))
            raw = json.dumps(call.get("args", {}), ensure_ascii=False, separators=(",", ":"))
            if len(raw) > _ARG_LIMIT:
                raw = raw[:_ARG_LIMIT] + f"…[{len(raw)} chars]"
            rows.append(f"{key} {raw}")
        return _record(f"model · tools ({len(calls)})", "llm", _bounded("\n".join(rows)), effect_id, secret_source=effect)
    if "interaction" in model:
        return _record("model · interaction", "llm", "interaction", effect_id, secret_source=effect)
    reason = result.get("reason") or outcome.get("reason") or "empty"
    return _record("model · empty", "error", _bounded(str(reason)), effect_id, secret_source=effect)


def render_state(state: dict, *, seen: frozenset[str], interaction_payload=None) -> list[StepRecord]:
    run = state.get("run") or state.get("projection") or state
    result = []
    status = run.get("status")
    interaction = run.get("interaction") or {}
    if status == "waiting" and interaction:
        interaction_id = str(interaction.get("interaction_id"))
        if interaction_id not in seen:
            # Poll may carry only the interaction handle. The caller can supply
            # the payload read from its durable originating model effect.
            payload_value = interaction.get("payload", {}) if interaction_payload is None else interaction_payload
            payload = json.dumps(payload_value, ensure_ascii=False, sort_keys=True)
            result.append(_record("run · waiting", "run", _bounded(payload), interaction_id, secret_source={"run": run, "payload": payload_value}))
    if status in {"completed", "failed", "cancelled", "blocked_unknown"} and str(run.get("run_id")) not in seen:
        remaining = {key: run.get("remaining_" + key) for key in ("steps", "tokens", "tool_calls", "wall_ms")}
        run_result = run.get("result") or {}
        budget_sealed = run_result.get("close_reason") == "budget_exhausted"
        label = "budget exhausted" if budget_sealed else ("completed" if status == "completed" else status)
        final = run_result.get("final_text")
        suffix = f"\nturn_no={run.get('turn_no')} remaining={json.dumps(remaining, sort_keys=True)}"
        if budget_sealed:
            suffix = f"\nreason=budget_exhausted" + suffix
        elif status != "completed":
            reason = (run.get("close_intent") or {}).get("reason") or run_result.get("reason") or run_result.get("close_reason") or "unknown"
            suffix += f" reason={reason}"
        result.append(_record(f"run · {label}", "error" if budget_sealed or status != "completed" else "run", _bounded((final or label) + suffix), run.get("run_id"), secret_source=run))
    return result


def render_run_start(*, scope, run_id, budget, requires) -> StepRecord:
    text = f"scope={str(scope)[:8]} run={str(run_id)[:8]} budget={json.dumps(budget, sort_keys=True)} requires={','.join(requires)}"
    return _record("run · started", "run", _bounded(text), run_id, secret_source={"scope": scope, "run": run_id, "budget": budget, "requires": requires})


def render_generating() -> StepRecord:
    return StepRecord("generating", "llm", "生成中…（完成后一次性给出回答）")
