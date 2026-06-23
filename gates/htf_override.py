"""gates/htf_override.py — HTF Override（純函數，deterministic）。

純輸入方向 → 輸出 verdict。冇 I/O、冇 network、冇 vision。Claude 只讀 g2 trend panel
嘅 4H / Daily / Weekly 方向 + 你個 trade 方向 + 現 tier，判定交呢度。

contract §G（源自 SPEC A，locked 2026-06-11 golden 靠佢）：
  4H + Daily + Weekly **全同向** → **逆向** trade 強制降一級（SNIPER→HIGH→STAND→WAIT）；
  順向不受影響。三者唔齊同向 → 唔觸發（順/逆都唔郁）。
"""
from __future__ import annotations

TIER_LADDER = ("SNIPER", "HIGH", "STAND", "WAIT")
_BULL = {"BULL", "BULLISH", "UP", "LONG"}
_BEAR = {"BEAR", "BEARISH", "DOWN", "SHORT"}


def _norm(direction) -> str | None:
    """BULLISH/UP/LONG → BULL；BEARISH/DOWN/SHORT → BEAR；其餘 → None。"""
    if direction is None:
        return None
    u = str(direction).upper()
    if u in _BULL:
        return "BULL"
    if u in _BEAR:
        return "BEAR"
    return None


def _downgrade(tier: str) -> str:
    if tier not in TIER_LADDER:
        return tier                      # 未知 tier 唔郁
    i = TIER_LADDER.index(tier)
    return TIER_LADDER[min(i + 1, len(TIER_LADDER) - 1)]   # clamp 喺 WAIT


def compute_htf_override(
    *,
    htf_4h,
    htf_daily,
    htf_weekly,
    trade_direction,
    tier: str = "STAND",
) -> dict:
    """回 {htf_override_triggered, htf_aligned, stack_direction, counter_trend, tier_in, tier_out}。"""
    a, d, w = _norm(htf_4h), _norm(htf_daily), _norm(htf_weekly)
    aligned = a is not None and a == d == w
    stack_direction = a if aligned else None

    td = _norm(trade_direction)          # Long→BULL、Short→BEAR
    counter_trend = bool(aligned and td is not None and td != stack_direction)
    triggered = counter_trend

    tier_in = str(tier).upper()
    tier_out = _downgrade(tier_in) if triggered else tier_in

    return {
        "htf_override_triggered": triggered,
        "htf_aligned": aligned,
        "stack_direction": stack_direction,
        "counter_trend": counter_trend,
        "tier_in": tier_in,
        "tier_out": tier_out,
    }
