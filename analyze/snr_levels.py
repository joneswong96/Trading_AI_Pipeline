"""analyze/snr_levels.py — SNR 精確價 producer 純函數（P2b Tier 1，Jones 2026-06-20 拍板）。

把 SNR 價由 vision 估值改成 deterministic 精確數（殺 Anti-Failure #15 False Precision / #11）。
只覆蓋「objective、零結構判斷」嘅 SNR source：
  - PDH/PDL/PWH/PWL = Daily/Weekly off1 high/low（由 htf_closed.json readings.d/w，P2b add-only）。
  - Round numbers = 現價 ±span 內、$50 grid（$100 位標 major 高權重）。
  - config key_levels = 已係精確數，pass-through。
swing / diagonal TL / broken-S-R-flip 等結構位 = 留 vision（Tier 3 / P3，唔喺度做）。

⚠️ 唔喺 gates/、唔改 confluence 語意：本 module 只供「精確價 menu + 同價去重 + 最近位」，
   confluence layer 點數仍由 analyst 按 sop STEP 6 原規則出。零 I/O，可獨立測。
"""
from __future__ import annotations

import math


def round_levels(price, *, step: float = 50.0, span: float = 75.0) -> list:
    """現價 ±span 內、step grid 上嘅 round number。$100 倍數標 weight='major'（高權重）。
    gold 用 $50 grid（唔用 $25，免一堆垃圾位）。price None / step<=0 → []。"""
    if price is None or step <= 0:
        return []
    lo, hi = price - span, price + span
    out = []
    lv = math.ceil(lo / step) * step
    while lv <= hi + 1e-9:
        out.append({"price": round(lv, 2),
                    "weight": "major" if abs(lv % 100.0) < 1e-9 else "minor"})
        lv += step
    return out


def assemble_snr(htf_readings, key_levels, price, *,
                 round_step: float = 50.0, round_span: float = 75.0,
                 dedup_tol: float = 1.0, swing_levels=None) -> dict:
    """精確 SNR menu：PDH/PDL/PWH/PWL（htf readings.d/w high/low）+ round + key_levels
    （+ P2c swing pivot），sort + 同價去重（dedup_tol 內合併、併 sources）。回 {price, levels[], nearest}。

    swing_levels（P2c，optional）：None → output 同 P2b 逐項一致（backward-compatible）；有值 →
    每個 swing 落同一 raw、單次 sort+dedup，容差內撞 PDH/PWH/round/key_level 自動合併、sources 併列。

    levels 每項 = {price, sources:[...]}（sources 標來源，例 PDH / round·major / key_level）。
    nearest = 距現價最近嗰個 level + dist（供 analyst 判「near 唔 near」，唔喺度定 boolean）。
    純函數，唔讀 config（param 傳入）；htf_readings 缺 high/low → 嗰個 source 自動跳過。
    """
    raw: list = []
    d = (htf_readings or {}).get("d") or {}
    w = (htf_readings or {}).get("w") or {}
    if d.get("high") is not None:
        raw.append((float(d["high"]), "PDH"))
    if d.get("low") is not None:
        raw.append((float(d["low"]), "PDL"))
    if w.get("high") is not None:
        raw.append((float(w["high"]), "PWH"))
    if w.get("low") is not None:
        raw.append((float(w["low"]), "PWL"))
    for lv in (key_levels or []):
        raw.append((float(lv), "key_level"))
    for r in round_levels(price, step=round_step, span=round_span):
        raw.append((r["price"], "round" + ("·major" if r["weight"] == "major" else "")))
    for sl in (swing_levels or []):          # P2c：swing pivot 落同一 raw（None/[] → P2b 行為不變）
        raw.append((float(sl["price"]),
                    f"{sl['kind']}({str(sl.get('tf', '')).upper()},{sl.get('tier', '')})"))

    raw.sort(key=lambda x: x[0])
    merged: list = []
    for pr, src in raw:                      # 同價去重：容差內合併、併 sources（唔重覆）
        if merged and abs(pr - merged[-1]["price"]) <= dedup_tol:
            if src not in merged[-1]["sources"]:
                merged[-1]["sources"].append(src)
        else:
            merged.append({"price": round(pr, 2), "sources": [src]})

    nearest = None
    if price is not None and merged:
        m = min(merged, key=lambda x: abs(x["price"] - price))
        nearest = {"price": m["price"], "sources": m["sources"],
                   "dist": round(abs(m["price"] - price), 2)}
    return {"price": price, "levels": merged, "nearest": nearest}


def _menu_from_bundle(bundle_dir, spot) -> dict:
    """call-site glue（producer）：讀 bundle/htf_closed.json readings.d/w high/low + config
    snr/key_levels → assemble_snr。CLI（`py -m analyze.snr_levels <bundle> <spot>`）同 test 共用。
    I/O 收喺呢度，assemble_snr / round_levels 保持純函數（唔讀 config）。"""
    import json
    import os

    from capture.base import load_asset

    cfg = load_asset("xauusd")
    htf = json.load(open(os.path.join(bundle_dir, "htf_closed.json"),
                         encoding="utf-8")).get("readings", {})
    s = cfg.get("snr") or {}
    # P2c：若 bundle 有 ohlc_history.json → 算 swing pivot 落同一 menu；無檔 → 退化 P2b menu。
    swing_levels = None
    hist_path = os.path.join(bundle_dir, "ohlc_history.json")
    if os.path.exists(hist_path):
        from analyze.swing_pivots import assemble_swing
        sw = cfg.get("swing") or {}
        bars = json.load(open(hist_path, encoding="utf-8")).get("bars", {})
        swing_levels = assemble_swing(
            bars, spot, k=int(sw.get("k", 2)), strict=bool(sw.get("strict_pivot", True)),
            per_side=int(sw.get("surface_per_side", 3)))
    return assemble_snr(htf, cfg.get("key_levels", []), spot,
                        round_step=float(s.get("round_step", 50.0)),
                        round_span=float(s.get("round_span", 75.0)),
                        dedup_tol=float(s.get("dedup_tol", 1.0)),
                        swing_levels=swing_levels)


if __name__ == "__main__":
    # producer call-site：py -m analyze.snr_levels <bundle_dir> <spot_price> → 印精確 SNR menu。
    # /analyze 喺 grading 前跑佢（<spot> = 你由 chart 讀到嘅現價），出 levels[]/nearest 餵
    # layer-attribution 契約。mirror P2a `tv9333 --dxy` producer step。
    import json as _json
    import sys as _sys

    _sys.stdout.reconfigure(encoding="utf-8")
    if len(_sys.argv) < 3:
        print("用法：py -m analyze.snr_levels <bundle_dir> <spot_price>")
        raise SystemExit(2)
    print(_json.dumps(_menu_from_bundle(_sys.argv[1], float(_sys.argv[2])),
                      ensure_ascii=False, indent=2))
