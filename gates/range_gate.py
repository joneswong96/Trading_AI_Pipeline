"""gates/range_gate.py — Range / No-Trade gate（純函數，deterministic）。

純輸入數字 → 輸出 verdict。冇 I/O、冇 network、冇 vision。Claude 只負責由圖讀出
結構事實（掂咗邊界幾多次、有冇 5m 收盤破邊界、幾耐冇破、邊界價、現價）；
RANGE 判定 + mid-band 判定喺呢度 deterministic 做（contract §B、Anti-Failure #17）。

contract §B：
  RANGE 確認 = (≥3 次掂邊界收唔穿) 或 (≥30 分鐘冇 5m 收盤破邊界)，且當前未有 5m 收盤破。
  RANGE 確認 → mid-band 一律 🚫 唔畀方向。
  5m 收盤破邊界 → 結構上容許方向（另需 DXY confirm + gate ≥3/4，**唔喺本函數**）。
mid-band = 區間中段 60%（兩邊各去 20%）。
"""
from __future__ import annotations

DEFAULT_TOUCH_THRESHOLD = 3
DEFAULT_TIME_THRESHOLD_MIN = 30
_MIDBAND_EDGE = 0.20      # 兩邊各去 20% → 中段 60%


def _midband(bounds, price) -> bool | None:
    if not bounds or price is None or len(bounds) != 2:
        return None
    lo, hi = sorted(float(b) for b in bounds)
    if hi <= lo:
        return None
    span = hi - lo
    return (lo + _MIDBAND_EDGE * span) <= float(price) <= (hi - _MIDBAND_EDGE * span)


def compute_range_gate(
    *,
    boundary_touches: int = 0,
    fivemin_close_broke: bool = False,
    minutes_since_break: float = 0.0,
    bounds: list | None = None,
    price: float | None = None,
    touch_threshold: int = DEFAULT_TOUCH_THRESHOLD,
    time_threshold_min: float = DEFAULT_TIME_THRESHOLD_MIN,
) -> dict:
    """回 {range_confirmed, allow_direction, price_in_midband, reason}。

    - fivemin_close_broke=True → range_confirmed=False、allow_direction=True（結構破）。
    - 否則 range_confirmed = (touches≥門檻) 或 (no-break 分鐘≥門檻)；allow_direction=False。
    - price_in_midband：有 bounds+price 先計（中段 60%），否則 None。
    """
    midband = _midband(bounds, price)

    if fivemin_close_broke:
        return {
            "range_confirmed": False,
            "allow_direction": True,
            "price_in_midband": midband,
            "reason": "5m_close_break",
        }

    by_touch = int(boundary_touches) >= int(touch_threshold)
    by_time = float(minutes_since_break) >= float(time_threshold_min)
    range_confirmed = by_touch or by_time
    if range_confirmed:
        reason = "+".join(
            r for r, on in (("touch", by_touch), ("time", by_time)) if on
        )
    else:
        reason = "undecided"
    return {
        "range_confirmed": range_confirmed,
        "allow_direction": False,
        "price_in_midband": midband,
        "reason": reason,
    }
