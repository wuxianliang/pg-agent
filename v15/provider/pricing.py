"""Versioned DeepSeek flash prices. No I/O and no global clock.

Checked 2026-09-29 against
https://api-docs.deepseek.com/quick_start/pricing
and https://api-docs.deepseek.com/zh-cn/quick_start/pricing.

USD per 1M tokens, deepseek-flash only (page writes $0.3 / $0.6 / $1.2 for the
peak miss / off-peak output / peak output cells; those are 0.30 / 0.60 / 1.20):

  cache miss  off-peak 0.15   peak 0.30
  cache hit   off-peak 0.003  peak 0.006
  output      off-peak 0.60   peak 1.20

Chinese page: 北京时间周一至周五 9:00 - 12:00、14:00 - 18:00 为高峰时段。
English page: 01:00 - 04:00 and 06:00 - 10:00 UTC, the same windows in
Asia/Shanghai. Neither page says the end minute is inside the peak window, so
the half-open intervals [09:00, 12:00) and [14:00, 18:00) stand. 12:00 and
18:00 are off-peak. Weekday Chinese public holidays are priced as peak
(over-report). This module does not embed a holiday calendar.
deepseek-v4-pro is not priced.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

PRICING_REVISION = "deepseek-2026-09-29"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MILLION = Decimal(1000000)
_QUANTUM = Decimal("0.000000000001")
_OFF = (
    Decimal("0.15") / _MILLION,
    Decimal("0.003") / _MILLION,
    Decimal("0.60") / _MILLION,
)
_PEAK = (
    Decimal("0.30") / _MILLION,
    Decimal("0.006") / _MILLION,
    Decimal("1.20") / _MILLION,
)
_MORNING = (time(9, 0), time(12, 0))
_AFTERNOON = (time(14, 0), time(18, 0))


def _aware(at: datetime) -> bool:
    return (
        isinstance(at, datetime)
        and at.tzinfo is not None
        and at.tzinfo.utcoffset(at) is not None
    )


def is_peak(at: datetime) -> bool | None:
    if not _aware(at):
        return None
    local = at.astimezone(_SHANGHAI)
    if local.weekday() >= 5:
        return False
    clock = local.time()
    return (_MORNING[0] <= clock < _MORNING[1]) or (
        _AFTERNOON[0] <= clock < _AFTERNOON[1]
    )


def _count(value) -> Decimal | None:
    if isinstance(value, bool) or type(value) is not int or value < 0:
        return None
    return Decimal(value)


def compute_cost(
    model,
    *,
    prompt_cache_miss_tokens,
    prompt_cache_hit_tokens,
    completion_tokens,
    at: datetime,
) -> Decimal | None:
    if model != "deepseek-flash":
        return None
    peak = is_peak(at)
    if peak is None:
        return None
    miss = _count(prompt_cache_miss_tokens)
    hit = _count(prompt_cache_hit_tokens)
    completion = _count(completion_tokens)
    if miss is None or hit is None or completion is None:
        return None
    miss_rate, hit_rate, output_rate = _PEAK if peak else _OFF
    cost = miss * miss_rate + hit * hit_rate + completion * output_rate
    if not cost.is_finite():
        return None
    return cost.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
