"""gates/day_type.py — Day-Type Gate（純函數，deterministic）。

純輸入結構事實 → 輸出 day_type。冇 I/O、冇 network、冇 vision。Claude 只讀結構事實
（5m 單邊移動點數、有冇連續 HL/LH、突破有冇跟進、邊界掂幾多次 / 幾耐冇破 / 有冇 5m
收破），判定交呢度。

contract §A / SOP STEP 1 / SPEC：
  TREND：5m ≥50 點單邊 + 連續 HL/LH + 突破有跟進。
  RANGE：3+ 次掂邊界收唔穿，或 30+ 分鐘冇 5m 收盤破邊界（且未有 5m 收破）。
  兩者都唔成立 → NEITHER（regime 未確認；/analyze 保守處理：唔當 trend 去追、
            亦唔套 range mid-band 規則，傾向 WAIT/觀望）。
Range 部分直接 call gates.range_gate（single source of truth，唔重複實作門檻）。
"""
from __future__ import annotations

from gates.range_gate import compute_range_gate

DEFAULT_TREND_MOVE_PTS = 50.0


def compute_day_type(
    *,
    fivemin_move_pts: float = 0.0,
    consecutive_hl_lh: bool = False,
    breakout_with_followthrough: bool = False,
    boundary_touches: int = 0,
    fivemin_close_broke: bool = False,
    minutes_since_break: float = 0.0,
    trend_move_threshold: float = DEFAULT_TREND_MOVE_PTS,
) -> dict:
    """回 {day_type, trend_confirmed, range_confirmed, reasons}。

    day_type ∈ {"TREND","RANGE","NEITHER"}。TREND 優先（同時成立時）。
    """
    trend_confirmed = (
        abs(float(fivemin_move_pts)) >= float(trend_move_threshold)
        and bool(consecutive_hl_lh)
        and bool(breakout_with_followthrough)
    )
    rg = compute_range_gate(
        boundary_touches=boundary_touches,
        fivemin_close_broke=fivemin_close_broke,
        minutes_since_break=minutes_since_break,
    )
    range_confirmed = rg["range_confirmed"]

    if trend_confirmed:
        day_type = "TREND"
    elif range_confirmed:
        day_type = "RANGE"
    else:
        day_type = "NEITHER"

    reasons: list[str] = []
    if trend_confirmed:
        reasons.append(f"5m_move>={trend_move_threshold:g}pt+HL/LH+followthrough")
    if range_confirmed:
        reasons.append(f"range:{rg['reason']}")
    if day_type == "NEITHER":
        reasons.append("no confirmed regime")

    return {
        "day_type": day_type,
        "trend_confirmed": trend_confirmed,
        "range_confirmed": range_confirmed,
        "reasons": reasons,
    }
