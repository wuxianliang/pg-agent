"""Opt-in DeepSeek adapter smoke. Not a gate. No database."""
from __future__ import annotations

import contextlib
import io
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_REQUEST = {
    "messages": [{"role": "user", "content": "Reply with exactly: SELECT 1;"}],
}
_LLM = {"model": "deepseek-flash"}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--real-provider-smoke" not in args:
        print("not_requested")
        return 0
    return _flagged()


def _flagged() -> int:
    import v15.provider.deepseek as deepseek

    provider = deepseek.DeepSeekProvider()
    try:
        if provider.api_key == "":
            print("credentials_absent")
            return 2
        return _live(provider)
    finally:
        provider.close()


def _live(provider) -> int:
    try:
        result = _complete(provider)
        _require(result)
        _print_summary(provider, result)
        return 0
    except Exception:
        raise RuntimeError("real-provider smoke failed") from None


def _complete(provider):
    calls = {"n": 0}
    transport = provider.transport
    previous = transport.opener_factory

    def factory():
        import v15.provider.deepseek as deepseek

        opener = (previous or deepseek.build_opener)()
        real_open = opener.open

        def opened(*args, **kwargs):
            calls["n"] += 1
            return real_open(*args, **kwargs)

        opener.open = opened
        return opener

    transport.opener_factory = factory
    try:
        sink_out = io.StringIO()
        sink_err = io.StringIO()
        with contextlib.redirect_stdout(sink_out), contextlib.redirect_stderr(sink_err):
            result = provider.complete("<smoke>", 1, _REQUEST, _LLM)
        if sink_out.getvalue() or sink_err.getvalue():
            raise AssertionError("printed")
    finally:
        transport.opener_factory = previous
    if calls["n"] != 1:
        raise AssertionError("http")
    return result


def _require(result) -> None:
    from v15.provider.pricing import PRICING_REVISION

    if not isinstance(result, dict):
        raise AssertionError("result")
    if type(result.get("content")) is not str:
        raise AssertionError("content")
    tokens = result.get("prompt_tokens")
    if type(tokens) is not int or tokens < 1:
        raise AssertionError("prompt_tokens")
    cost = result.get("cost_usd")
    if not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0:
        raise AssertionError("cost")
    meta = result.get("provider")
    if not isinstance(meta, dict):
        raise AssertionError("provider")
    if meta.get("pricing_revision") != PRICING_REVISION:
        raise AssertionError("pricing_revision")
    if meta.get("model") != "deepseek-flash":
        raise AssertionError("model")


def _print_summary(provider, result) -> None:
    host = urlparse(provider.base_url).hostname
    if not isinstance(host, str) or host == "":
        raise AssertionError("host")
    finish = result["provider"].get("finish_reason")
    if not isinstance(finish, str):
        finish = ""
    line = f"{host} deepseek-flash {result['prompt_tokens']} {result['cost_usd']} {finish}"
    key = provider.api_key
    content = result["content"]
    if key and key in line:
        raise AssertionError("leak")
    if "Authorization" in line or "reasoning" in line:
        raise AssertionError("leak")
    if len(content) >= 8 and content in line:
        raise AssertionError("leak")
    print(line)


if __name__ == "__main__":
    raise SystemExit(main())
