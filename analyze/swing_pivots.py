"""analyze/swing_pivots.py — 自動 swing-pivot 偵測純函數（P2c Tier 3a，Jones 2026-06-20 拍板）。

系統自己用 deterministic fractal 算法掃 OHLC 歷史揾 swing high/low（S/R），唔手畫、唔 vision 估。
餵 analyze.snr_levels.assemble_snr 做多一個 SNR source（swing_high/swing_low），dedup→1 層。

- 唔喺 gates/、零 I/O；input = chronological OHLC bars（由 ohlc_history.json，bars[-1]=off1）。
- no-repaint：pivot 要左右各 k 條 closed bar 確認 → scan i ∈ [k, len-1-k]；forming bar 唔喺 bars。
- 嚴格 >/<（strict）：平頂/平底唔當 pivot，保 determinism。
- tier（major/intermediate/minor）= TF-tiered annotation only，唔改 deterministic 層數（confluence.py 零改）。
"""
from __future__ import annotations

# bar array index：[time, open, high, low, close]
_HIGH, _LOW, _TIME = 2, 3, 0

TF_TIER = {"w": "major", "d": "major", "h4": "intermediate", "m15": "minor", "m5": "minor"}


def classify_tier(tf) -> str:
    """TF-tiered：D/W=major、H4=intermediate、5m/15m=minor（其餘預設 minor）。"""
    return TF_TIER.get(tf, "minor")


def detect_pivots(bars, *, k: int = 2, strict: bool = True) -> dict:
    """bars = chronological [[t,O,H,L,C],...]（oldest→newest，最後=off1）。

    fractal strength k：swing_high at i = high[i] 嚴格大過左右各 k 條 high（strict=True 用 `>`）；
    swing_low 對稱用 `<`。no-repaint：只 scan i ∈ [k, len-1-k]（最後 k 條 + forming 唔 host pivot）。
    tie（平頂平底，strict=True）→ 唔當 pivot。回 {"highs":[{idx,time,price}], "lows":[...]}。
    """
    highs: list = []
    lows: list = []
    n = len(bars or [])
    if n < 2 * k + 1:
        return {"highs": highs, "lows": lows}
    for i in range(k, n - k):                      # i ∈ [k, n-1-k]，no-repaint 邊界
        hi, lo, t = bars[i][_HIGH], bars[i][_LOW], bars[i][_TIME]
        nb = range(i - k, i + k + 1)
        is_high = all((hi > bars[j][_HIGH]) if strict else (hi >= bars[j][_HIGH])
                      for j in nb if j != i)
        is_low = all((lo < bars[j][_LOW]) if strict else (lo <= bars[j][_LOW])
                     for j in nb if j != i)
        if is_high:
            highs.append({"idx": i, "time": t, "price": hi})
        if is_low:
            lows.append({"idx": i, "time": t, "price": lo})
    return {"highs": highs, "lows": lows}


def surface_nearest(items, price, *, per_side: int = 3) -> list:
    """每邊（price 之上 / 之下）取距 price 最近 per_side 個。price None → 原樣返。
    等距 tie-break：按 (dist, price, tf) 排序保 determinism（guard iii）。"""
    if price is None:
        return list(items or [])

    def keyf(it):
        return (abs(it["price"] - price), it["price"], str(it.get("tf", "")), str(it.get("kind", "")))

    above = sorted((it for it in items if it["price"] > price), key=keyf)
    below = sorted((it for it in items if it["price"] < price), key=keyf)
    return above[:per_side] + below[:per_side]


def assemble_swing(bars_by_tf, price, *, k: int = 2, strict: bool = True,
                   per_side: int = 3) -> list:
    """逐 TF detect_pivots → 標 tier/tf/kind → 每 TF 每邊 surface per_side → 收集成 flat list。
    回 [{price, kind:'swing_high'|'swing_low', tf, tier, time}]（未跨 TF dedup；交 assemble_snr
    統一同價去重，避免兩套 dedup）。"""
    out: list = []
    for tf, bars in (bars_by_tf or {}).items():
        if not bars:
            continue
        piv = detect_pivots(bars, k=k, strict=strict)
        tier = classify_tier(tf)
        items = [{"price": h["price"], "kind": "swing_high", "tf": tf, "tier": tier,
                  "time": h["time"]} for h in piv["highs"]]
        items += [{"price": low["price"], "kind": "swing_low", "tf": tf, "tier": tier,
                   "time": low["time"]} for low in piv["lows"]]
        out.extend(surface_nearest(items, price, per_side=per_side))
    return out
