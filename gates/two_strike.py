"""gates/two_strike.py — Two-Strike 斷路器（純函數，deterministic）。

純輸入歷史 → 輸出 verdict。冇 I/O、冇 network、冇 vision。

SPEC B（L79）/ contract §B / Anti-Failure #22：
  同一 band 連續 2 個方向 call 都被 invalidate → 強制宣告 chop、停止畀方向。

注意 Fresh Eyes（#6）：呢度收嘅係**已發生嘅結局**（trigger/invalidate 記錄，屬 #22
「frame 咗要 track 結局」），唔係 carry-forward 上一 cycle 嘅判斷/分析。歷史由 caller
明確傳入（manual 模式由 Jones／command 提供），本函數純計，唔自己記 state。
"""
from __future__ import annotations

DEFAULT_THRESHOLD = 2


def evaluate_two_strike(
    calls: list[dict] | None,
    *,
    band_key=None,
    threshold: int = DEFAULT_THRESHOLD,
) -> dict:
    """calls = 時序 list（舊→新），每個 {"band","direction","invalidated"}。

    只計**方向 call**（有 direction，WAIT/SKIP 唔計）。睇目標 band 尾段連續被
    invalidate 嘅方向 call 數；≥threshold → chop。
    band_key=None → 用最新一個方向 call 嘅 band。
    回 {chop, stop_direction, band, strikes, threshold, reason}。
    """
    direction_calls = [c for c in (calls or []) if c.get("direction")]
    if band_key is None:
        band_key = direction_calls[-1].get("band") if direction_calls else None

    band_calls = [c for c in direction_calls if c.get("band") == band_key]
    streak = 0
    for c in reversed(band_calls):
        if c.get("invalidated"):
            streak += 1
        else:
            break

    chop = streak >= threshold
    if band_key is None:
        reason = "no direction calls"
    elif chop:
        reason = f"{streak} consecutive invalidated direction calls on band {band_key} → chop"
    else:
        reason = f"{streak} strike(s) on band {band_key} (need {threshold})"

    return {
        "chop": chop,
        "stop_direction": chop,
        "band": band_key,
        "strikes": streak,
        "threshold": threshold,
        "reason": reason,
    }
