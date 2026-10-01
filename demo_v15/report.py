"""Markdown evidence report. Strips API keys before writing."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent / "reports"
D28 = "cost_used 不是发票；工作日假日按高峰多报。"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _assertion_lines(result: dict, meta: dict) -> list[str]:
    lines = ["## Assertions", ""]
    items = result.get("assertions")
    if not items:
        lines.append("- assertions: absent")
    else:
        for item in items:
            lines.append(f"- {item['n']}. {item['name']}: {bool(item['ok'])}")
    lines.append("- cost_rule: real each settled attempt prompt_tokens>=1 and cost_usd>0")
    lines.append(f"- cost_checks_ok: {result.get('cost_checks_ok')}")
    lines.append(f"- cost_missing: {result.get('cost_missing')}")
    if meta.get("mode") == "real":
        checks = result.get("settled_cost_checks") or []
        if not checks:
            lines.append("- settled_cost_checks: none")
        for row in checks:
            lines.append(
                "- settled {invoke} iteration={iteration} n={n} "
                "prompt_tokens={prompt_tokens} cost_usd={cost_usd} ok={ok}".format(
                    invoke=row.get("invoke_id"),
                    iteration=row.get("iteration"),
                    n=row.get("n"),
                    prompt_tokens=row.get("prompt_tokens"),
                    cost_usd=row.get("cost_usd"),
                    ok=row.get("ok"),
                )
            )
    lines.append(f"- events_ok: {result.get('events_ok')}")
    lines.append(f"- scratch_clear: {result.get('scratch_clear')}")
    lines.append(f"- running: {result.get('running')}")
    lines.append(f"- leased: {result.get('leased')}")
    lines.append("")
    return lines


def render_report(result: dict, meta: dict) -> str:
    lines = [
        "# v15 tail-delegation demo",
        "",
        f"- time: {meta['started_at']}",
        f"- mode: {meta['mode']}",
        f"- scenario: {meta.get('scenario')}",
        f"- hops: {meta.get('hops')}",
        f"- note: {meta['note_revision']}",
        f"- database: {meta['dbname']}",
        f"- root: {result.get('root_id')}",
        f"- lease: {meta['lease']}",
        f"- ceilings: {json.dumps(meta['ceilings'], separators=(',', ':'))}",
        f"- pool: calls_limit={meta['calls_limit']} cost_limit={meta['cost_limit']}",
        "",
        f"- outcome: {result.get('outcome')}",
        f"- failure_class: {result.get('failure_class')}",
        f"- relay_ok: {result.get('relay_ok')}",
        f"- relay_flags: {', '.join(result.get('relay_flags') or []) or '-'}",
        f"- recall_ok: {result.get('recall_ok')}",
        f"- recall_flags: {', '.join(result.get('recall_flags') or []) or '-'}",
        f"- csi_ok: {result.get('csi_ok')}",
        f"- csi_flags: {', '.join(result.get('csi_flags') or []) or '-'}",
        f"- warning_ok: {result.get('warning_ok')}",
        "",
    ]
    lines.extend(_assertion_lines(result, meta))
    lines.extend(
        [
        "## Nodes",
        "",
        "| id | depth | role | hops | seal | note | status | error | attempts | return_value |",
        "|---|---:|---|---:|---|---|---|---|---|---|",
        ]
    )
    for node in result.get("nodes") or []:
        inputs = node.get("inputs") or {}
        attempts = ",".join(
            f"{item['iteration']}:{item['count']}"
            for item in node.get("attempts_by_iteration") or []
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(node.get("invoke_id")),
                    _cell(node.get("depth")),
                    _cell(inputs.get("role")),
                    _cell(inputs.get("hops")),
                    _cell(inputs.get("seal")),
                    _cell(inputs.get("note")),
                    _cell(node.get("status")),
                    _cell(node.get("error_code")),
                    attempts,
                    _cell(node.get("return_value")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## §0.2 edges", ""])
    lines.append(
        "| parent | bind_iteration | settled | max_n | next | var_eq | suspend | deliver | repl_exits |"
    )
    lines.append("|---|---:|---:|---:|---|---|---:|---:|---:|")
    for node in result.get("nodes") or []:
        if node.get("bind_iteration") is None and node.get("suspend_seq") is None:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(node.get("invoke_id")),
                    _cell(node.get("bind_iteration")),
                    _cell(node.get("settled_on_bind_iteration")),
                    _cell(node.get("max_n_on_bind_iteration")),
                    _cell(node.get("next_kind")),
                    _cell(node.get("var_matches_child")),
                    _cell(node.get("suspend_seq")),
                    _cell(node.get("deliver_seq")),
                    _cell(node.get("repl_exits_between")),
                ]
            )
            + " |"
        )
    transcript = result.get("transcript") or {}
    cost = result.get("cost") or {}
    lines.extend(
        [
            "",
            "## Transcript",
            "",
            f"- assistant_messages: {transcript.get('assistant_messages')}",
            f"- markdown_fence_messages: {transcript.get('markdown_fence_messages')}",
            f"- split_failures: {json.dumps(transcript.get('split_failures') or {}, separators=(',', ':'))}",
            f"- classified: {json.dumps(transcript.get('classified') or {}, separators=(',', ':'))}",
            f"- legal_statement_rate: {transcript.get('legal_statement_rate')}",
            f"- finish_reasons: {json.dumps(transcript.get('finish_reasons') or {}, separators=(',', ':'))}",
            "",
            "## Cost",
            "",
            f"- sum_cost_usd: {cost.get('sum_cost_usd')}",
            f"- cost_used: {cost.get('cost_used')}",
            f"- calls_used: {cost.get('calls_used')}",
            f"- calls_charged: {cost.get('calls_charged')}",
            f"- calls_limit: {cost.get('calls_limit')}",
            f"- cost_limit: {cost.get('cost_limit')}",
            f"- pricing_revision: {cost.get('pricing_revision')}",
            f"- any_peak: {cost.get('any_peak')}",
            f"- provider_meta: {cost.get('provider_meta')}",
            f"- {D28}",
            "",
            "## Assistant previews",
            "",
        ]
    )
    for preview in transcript.get("assistant_previews") or []:
        lines.append(f"- {json.dumps(preview, ensure_ascii=False)}")
    warning = result.get("warning") or {}
    sizer = meta.get("sizer") or {}
    lines.extend(
        [
            "",
            "## Recall",
            "",
            f"- token: {meta.get('token') or ''}",
            f"- facts_len: {meta.get('facts_len')}",
            f"- facts_prefix: {json.dumps(meta.get('facts_prefix') or '', ensure_ascii=False)}",
            f"- sizer: {json.dumps(sizer, separators=(',', ':'))}",
            f"- protocol_limit: {result.get('protocol_limit')}",
            f"- hook_count: {result.get('hook_count')}",
            f"- root_sends: {json.dumps(warning.get('root_sends') or [], separators=(',', ':'))}",
            f"- nonroot_max: {warning.get('nonroot_max')}",
            f"- root_tail_warned: {warning.get('root_tail_warned')}",
            f"- nonroot_warning_count: {warning.get('nonroot_warning_count')}",
            "",
        ]
    )
    if result.get("pgcode"):
        lines.extend(["", f"- pgcode: {result['pgcode']}"])
    lines.extend(["", "## Exception", "", "no spec change", ""])
    return "\n".join(lines)


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def write_report(result: dict, meta: dict, secrets: list[str]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    body = redact(render_report(result, meta), secrets)
    stamp = meta["stamp"]
    path = REPORT_DIR / f"e2e_report-{stamp}.md"
    latest = REPORT_DIR / "latest.md"
    path.write_text(body, encoding="utf-8")
    latest.write_text(body, encoding="utf-8")
    return path


def stamp_now() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y%m%dT%H%M%SZ")
