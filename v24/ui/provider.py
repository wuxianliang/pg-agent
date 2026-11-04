"""Credential resolution and adapter construction for controlled real entries.

This module is the only production dependency of the real UI entry. It never
opens files, databases, locks or sockets; preflight is local and explicit.
"""
from __future__ import annotations

import os

from v24.host.deepseek import DeepSeekAdapter
from v24.ui import catalog


def provider_key() -> str:
    """Prefer DEEPSEEK_API_KEY; retain the existing OPENAI_API_KEY fallback."""
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""


def create_real_adapter(limits: catalog.UiLimits | None = None, *, transport=None) -> DeepSeekAdapter:
    """Resolve credentials and locally preflight before any app resources.

    Transport injection permits exercising the real adapter without sockets.
    Only stable reasons escape; arbitrary preflight payloads never reach UI/CLI.
    """
    key = provider_key()
    if not key:
        raise RuntimeError("credentials_absent")
    limits = limits or catalog.REAL_UI_LIMITS
    try:
        adapter = DeepSeekAdapter(api_key=key, timeout_s=limits.timeout_s,
                                  transport=transport,
                                  body_byte_ceiling=limits.body_byte_ceiling)
        failure = adapter.preflight()
    except Exception:
        raise RuntimeError("preflight_failed") from None
    if failure is not None:
        raise RuntimeError("preflight_failed")
    return adapter
