"""analyze/structure_state.py — P3 structure-gate 第一刀：HL/LH 結構序列分類（純函數）。

⚠️ 結構冇 ground-truth oracle → **唔 wire /analyze、唔 promote**。呢度只起 deterministic 骨架 +
dump 俾 Jones 人手 eyeball adjudicate。NOT in gates/（gates/ 8 純函數零改）。

primitive（今 cut 只做呢一個）：
- 食 ohlc_history.json（P2c `tv9333 --ohlc`，5 TF chronological closed bars）+ swing_pivots 嘅
  no-repaint pivots（reuse，唔改）。
- 顯著性 filter：min_swing[tf] = atr_mult × ATR(atr_period)[tf]（per TF，closed bars 算）。
- 連續顯著 swing 分類 UPTREND(HH+HL) / DOWNTREND(LH+LL) / UNCLEAR（mixed / 不足樣本，保守，
  對齊 Anti-Failure #15 唔估）。no-repaint（同 swing_pivots 一樣唔讀 forming bar）、replayable。

breakout-follow-through / range 邊界 / touch-count / HTF price-vs-structure = 後續 STEP，唔喺度做。
"""
from __future__ import annotations

# bar array index：[time, open, high, low, close]
_HIGH, _LOW, _CLOSE = 2, 3, 4


def atr(bars, period: int = 14):
    """簡單平均 ATR：mean(True Range) over 最後 period 條 closed bar。
    TR = max(H-L, |H-prevC|, |L-prevC|)。bars chronological（caller 保證唔含 forming）。
    不足 period+1 條 → None（唔估）。"""
    n = len(bars or [])
    if n < period + 1:
        return None
    trs = []
    for i in range(n - period, n):
        h, low, pc = bars[i][_HIGH], bars[i][_LOW], bars[i - 1][_CLOSE]
        trs.append(max(h - low, abs(h - pc), abs(low - pc)))
    return sum(trs) / period


def min_swing_threshold(bars, price, cfg):
    """structure.min_swing dict → 顯著性門檻（價單位）。
    method=atr → atr_mult × ATR(atr_period)；pct_price → pct × price；fixed → value。
    不足樣本 → None。"""
    method = (cfg or {}).get("method", "atr")
    if method == "atr":
        a = atr(bars, int((cfg or {}).get("atr_period", 14)))
        return None if a is None else float((cfg or {}).get("atr_mult", 1.0)) * a
    if method == "pct_price":
        return None if price is None else float((cfg or {}).get("pct", 0.0)) * float(price)
    if method == "fixed":
        return float((cfg or {}).get("value", 0.0))
    raise ValueError(f"unknown structure.min_swing.method: {method}")


def _zigzag(pivots, min_swing):
    """pivots = chronological [{idx,kind:'H'|'L',price,time}] → alternating significant swings。
    同型 → 取更極端（H 更高 / L 更低）；異型 → 只喺 |Δprice| >= min_swing 先確認（唔顯著反轉忽略）。"""
    swings: list = []
    for p in pivots:
        if not swings:
            swings.append(dict(p))
            continue
        last = swings[-1]
        if p["kind"] == last["kind"]:
            if (p["kind"] == "H" and p["price"] > last["price"]) or \
               (p["kind"] == "L" and p["price"] < last["price"]):
                swings[-1] = dict(p)
        elif abs(p["price"] - last["price"]) >= min_swing:
            swings.append(dict(p))
    return swings


def classify_hl_lh(bars, *, k: int = 2, strict: bool = True, min_swing=None) -> dict:
    """單 TF HL/LH：detect_pivots(reuse) → zigzag(min_swing) → 最近 2 顯著 high/low →
    UPTREND(HH+HL) / DOWNTREND(LH+LL) / UNCLEAR（不足或 mixed）。回 {state, reason, min_swing,
    sig_highs, sig_lows}。"""
    from analyze.swing_pivots import detect_pivots

    if not min_swing or min_swing <= 0:
        return {"state": "UNCLEAR", "reason": "no min_swing（不足樣本）",
                "min_swing": None, "sig_highs": [], "sig_lows": []}
    piv = detect_pivots(bars, k=k, strict=strict)
    pts = [{"idx": h["idx"], "kind": "H", "price": h["price"], "time": h["time"]}
           for h in piv["highs"]]
    pts += [{"idx": low["idx"], "kind": "L", "price": low["price"], "time": low["time"]}
            for low in piv["lows"]]
    pts.sort(key=lambda x: x["idx"])
    zz = _zigzag(pts, min_swing)
    sig_highs = [s for s in zz if s["kind"] == "H"]
    sig_lows = [s for s in zz if s["kind"] == "L"]
    if len(sig_highs) < 2 or len(sig_lows) < 2:
        state, reason = "UNCLEAR", f"顯著 swing 不足（H={len(sig_highs)},L={len(sig_lows)}）"
    else:
        hh = sig_highs[-1]["price"] > sig_highs[-2]["price"]
        hl = sig_lows[-1]["price"] > sig_lows[-2]["price"]
        lh = sig_highs[-1]["price"] < sig_highs[-2]["price"]
        ll = sig_lows[-1]["price"] < sig_lows[-2]["price"]
        if hh and hl:
            state, reason = "UPTREND", "HH+HL"
        elif lh and ll:
            state, reason = "DOWNTREND", "LH+LL"
        else:
            state, reason = "UNCLEAR", "mixed（HH/HL/LH/LL 唔一致）"
    return {"state": state, "reason": reason, "min_swing": round(min_swing, 4),
            "sig_highs": [round(s["price"], 2) for s in sig_highs[-3:]],
            "sig_lows": [round(s["price"], 2) for s in sig_lows[-3:]]}


def classify_structure(bars_by_tf, *, structure_cfg=None, swing_cfg=None) -> dict:
    """每 TF 行 HL/LH 分類。structure_cfg = config `structure`、swing_cfg = config `swing`（reuse
    k/strict 嘅 pivot）。回 {tf: {state, reason, atr14, min_swing, sig_highs, sig_lows, bars}}。"""
    structure_cfg = structure_cfg or {}
    swing_cfg = swing_cfg or {}
    k = int(swing_cfg.get("k", 2))
    strict = bool(swing_cfg.get("strict_pivot", True))
    ms_cfg = structure_cfg.get("min_swing") or {}
    out: dict = {}
    for tf, bars in (bars_by_tf or {}).items():
        bars = bars or []
        price = bars[-1][_CLOSE] if bars else None        # off1 close 做 price ref
        ms = min_swing_threshold(bars, price, ms_cfg)
        res = classify_hl_lh(bars, k=k, strict=strict, min_swing=ms)
        a = atr(bars, int(ms_cfg.get("atr_period", 14))) if ms_cfg.get("method", "atr") == "atr" else None
        res["atr14"] = round(a, 4) if a is not None else None
        res["bars"] = len(bars)
        out[tf] = res
    return out


def _structure_from_bundle(bundle_dir) -> dict:
    """dump glue：讀 bundle/ohlc_history.json + config structure/swing → classify_structure。"""
    import json
    import os

    from capture.base import load_asset

    cfg = load_asset("xauusd")
    hist = json.load(open(os.path.join(bundle_dir, "ohlc_history.json"), encoding="utf-8"))
    return classify_structure(hist.get("bars", {}),
                              structure_cfg=cfg.get("structure"), swing_cfg=cfg.get("swing"))


if __name__ == "__main__":
    # read-only dump（唔 promote、唔寫 golden/）：py -m analyze.structure_state <bundle_dir>
    # 打印每 TF HL/LH state + 用到嘅 ATR/min_swing/顯著 swing，俾 Jones eyeball adjudicate。
    import json as _json
    import sys as _sys

    _sys.stdout.reconfigure(encoding="utf-8")
    if len(_sys.argv) < 2:
        print("用法：py -m analyze.structure_state <bundle_dir>")
        raise SystemExit(2)
    print(_json.dumps(_structure_from_bundle(_sys.argv[1]), ensure_ascii=False, indent=2))
