"""analyze/htf_direction.py — HTF 方向 producer 純函數（deterministic, off1 closed-bar）。

P1 接數（htf_override C，Jones 2026-06-20 拍板）：H4/D/W 各讀 last CLOSED bar（off1）close →
close vs SMA(N) ± deadband → 方向，餵 gates.htf_override 嘅 htf_4h/htf_daily/htf_weekly input。

- 唔喺 gates/：純 producer 層，gates/ 8 個純函數一個字唔郁。
- NEUTRAL → gates.htf_override._norm() 收唔到 BULL/BEAR → None → 唔 aligned → 唔觸發（safe）。
- 冇 structure ground-truth → 唔做 fidelity shadow（呢個係另一個更簡單嘅算術定義，由 Jones eyeball ratify）。
- knob：sma_len=20、band=0.001（0.1%），放 config/assets.yaml 可調。
- 零 I/O，可獨立單測（tests/test_htf_direction.py）。
"""
from __future__ import annotations


def compute_direction(closes, *, sma_len: int = 20, band: float = 0.001) -> str:
    """closes = closed-bar 收市價 list，**newest-closed（off1）排第一**（off1, off2, ... offN, ...）。

    C = closes[0]（off1 收市）；SMA = mean(closes[0..sma_len-1]) = off1..offN 平均。
      C > SMA × (1 + band) → BULLISH
      C < SMA × (1 − band) → BEARISH
      其餘（落喺 ±band 死區） → NEUTRAL
    history < sma_len 或 window 內有 None → NEUTRAL（唔准估，Anti-Failure #15）。
    """
    if not closes or len(closes) < sma_len:
        return "NEUTRAL"
    window = closes[:sma_len]
    if any(c is None for c in window):
        return "NEUTRAL"
    c = closes[0]
    sma = sum(window) / sma_len
    if c > sma * (1 + band):
        return "BULLISH"
    if c < sma * (1 - band):
        return "BEARISH"
    return "NEUTRAL"


def summarize(closes, *, sma_len: int = 20, band: float = 0.001) -> dict:
    """方向 + 可 audit 數字（寫入 htf_closed.json 每個 TF）。

    direction 用 compute_direction（單一真理源，唔重複算 threshold 邏輯）；
    sma 只喺 history 足夠且無 None 時計，否則 None（auditable，唔靜靜當 0）。
    """
    n = len(closes) if closes else 0
    direction = compute_direction(closes, sma_len=sma_len, band=band)
    window = closes[:sma_len] if closes else []
    enough = n >= sma_len and all(c is not None for c in window)
    sma = (sum(window) / sma_len) if enough else None
    return {
        "close": closes[0] if n else None,
        "sma": round(sma, 4) if sma is not None else None,
        "direction": direction,
        "bars_loaded": n,
        "sma_len": sma_len,
        "band": band,
    }
