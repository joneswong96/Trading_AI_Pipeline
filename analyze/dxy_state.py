"""analyze/dxy_state.py — DXY modifier deterministic 化（P2a，Jones 2026-06-20 拍板）。

DXY 由 vision（g3 1m）換成 9333 純讀 + 純算術：
- 方向（trade-agnostic）：reuse htf_direction.compute_direction（close vs SMA(N)±band，off1 closed bar）。
  → 單一真理源，DXY/HTF 共用同一條 close-vs-SMA 邏輯。TF=15m + 偏闊 deadband = #20 noise-kill。
- state（trade-relative）：DXY 同金 inverse → map 成 CONFIRM/NEUTRAL/ADVERSE，餵 gates.confluence
  嘅 dxy_state arg（NEUTRAL/ADVERSE 封頂 B+；CONFIRM 唔封）。

鐵則：DXY 只封頂 grade/size，**永不調入唔入/時機**（Anti-Failure #18）。
- gates/confluence.py 一個字唔郁，只改「dxy_state 點嚟」。
- dxy_closed.json 只存 trade-agnostic 方向；CONFIRM/ADVERSE 喺 /analyze 配 trade 方向先算。
"""
from __future__ import annotations

from analyze.htf_direction import compute_direction

_LONG = {"LONG", "BUY"}
_SHORT = {"SHORT", "SELL"}


def compute_dxy_direction(closes, *, sma_len: int = 20, band: float = 0.001) -> str:
    """DXY 方向（BULLISH/BEARISH/NEUTRAL），trade-agnostic。reuse htf 嘅 close-vs-SMA 邏輯
    （單一真理源）。history < sma_len 或有 None → NEUTRAL（mirror htf，唔准估）。"""
    return compute_direction(closes, sma_len=sma_len, band=band)


def map_dxy_state(dxy_direction, trade_direction) -> str:
    """DXY 同金 inverse → CONFIRM / NEUTRAL / ADVERSE（deterministic truth-table）。

      trade Long （做多金）：DXY BEARISH(跌)=CONFIRM｜BULLISH(升)=ADVERSE
      trade Short（做空金）：DXY BULLISH(升)=CONFIRM｜BEARISH(跌)=ADVERSE
      DXY NEUTRAL（死區）            → NEUTRAL
      trade 無方向 / WAIT / 認唔到   → NEUTRAL（寫死；保守，confluence 封頂 B+）
    """
    d = (dxy_direction or "").upper()
    t = (trade_direction or "").upper()
    if d not in ("BULLISH", "BEARISH"):
        return "NEUTRAL"
    if t in _LONG:
        return "CONFIRM" if d == "BEARISH" else "ADVERSE"
    if t in _SHORT:
        return "CONFIRM" if d == "BULLISH" else "ADVERSE"
    return "NEUTRAL"        # WAIT / 無方向 → NEUTRAL（寫死 rulebook）
