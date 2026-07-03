"""analyze/structure_read.py — P3 STEP 1 structure primitives（純函數，唔喺 gates/）。

⚠️ 結構冇 ground-truth oracle → **唔 wire /analyze、唔 promote**。呢度只起 deterministic primitive +
餵 scripts/structure_adjudicate.py dump 俾 Jones 人手 eyeball sign-off（P3 特有，代替 machine-verify）。

同 analyze/structure_state.py 嘅分工（Jones 2026-07-03 拍板：structure_read import structure_state）：
- structure_state = categorical 骨架（classify_hl_lh → UPTREND/DOWNTREND/UNCLEAR，睇最近 2 顯著 swing）。
- structure_read（本檔）= 更 rich 嘅 primitive：`consecutive_hl_lh` 連續 HL/LH **計數 + 方向**。
- 底層 ATR / zigzag significance **reuse structure_state**（唔 copy）：atr14→structure_state.atr(·,14)、
  swing_sequence→structure_state._zigzag。swing pivots reuse analyze.swing_pivots.detect_pivots（零改）。

primitive（STEP 1 只做呢三個 + 一條 bundle glue）：
- atr14(bars, tf)：per-TF ATR14（closed bars；period 固定 14）。
- swing_sequence(pivots, min_swing)：食 detect_pivots 現有輸出 → zigzag 顯著性過濾（min_swing =
  atr_mult × ATR14[tf]）→ alternating 顯著 HL/LH swing sequence。
- consecutive_hl_lh(sequence)：sequence tail 連續 confirming swing 計數 → {count:int, direction, labels}。

只讀 ohlc_history.json（P2c `tv9333 --ohlc` 現有 producer；唔加新 CDP 讀法）。no-repaint（同 swing_pivots
一樣唔讀 forming bar）、replayable、零 I/O side-effect（glue 只 read）。range 邊界 / touch-count /
breakout follow-through / fib = 後續 STEP，唔喺度做。
"""
from __future__ import annotations

from analyze.structure_state import _zigzag, atr, min_swing_threshold

# bar array index：[time, open, high, low, close]
_HIGH, _LOW, _CLOSE = 2, 3, 4

_UP_LABELS = frozenset({"HH", "HL"})
_DOWN_LABELS = frozenset({"LH", "LL"})


def atr14(bars, tf=None):
    """per-TF ATR14：closed bars 算（period 固定 14，reuse structure_state.atr）。tf 只做
    annotation（bars 已經係單一 TF；caller 保證唔含 forming bar）。不足 15 條 → None（唔估）。"""
    return atr(bars, 14)


def swing_sequence(pivots, min_swing):
    """食 analyze.swing_pivots.detect_pivots 現有輸出 {"highs":[{idx,time,price}], "lows":[...]}，
    用 min_swing 過濾 insignificant swing → alternating 顯著 HL/LH swing sequence（chronological）。

    normalize → 標 kind H/L → 按 idx 排 → reuse structure_state._zigzag（同型取更極端、異型只喺
    |Δprice| >= min_swing 先確認）。min_swing 冇/≤0 → 回空 list（不足樣本，唔估）。
    """
    if not min_swing or min_swing <= 0:
        return []
    highs = (pivots or {}).get("highs") or []
    lows = (pivots or {}).get("lows") or []
    pts = [{"idx": h["idx"], "kind": "H", "price": h["price"], "time": h.get("time")}
           for h in highs]
    pts += [{"idx": low["idx"], "kind": "L", "price": low["price"], "time": low.get("time")}
            for low in lows]
    pts.sort(key=lambda x: x["idx"])
    # _zigzag 零 pivot 偵測：唯一 pivot 來源 = detect_pivots（掃 bars 揾 fractal swing）；_zigzag
    # 只食佢已標好嘅 H/L 點做 significance filter（同型 collapse / 異型 min_swing 確認），零讀 bars。
    return _zigzag(pts, min_swing)


def consecutive_hl_lh(sequence):
    """alternating 顯著 swing sequence → 連續 HL/LH 計數 + 方向（P3 STEP 1 primitive）。

    每個 swing 對「上一個同型 swing」標 label：H → HH（更高）/ LH（更低）；L → HL（更高）/ LL（更低）；
    相等（strict pivot 下罕見）→ EQ。由 tail（最近）向後數連續 confirming label：
      up   = {HH, HL}（uptrend structure）；down = {LH, LL}（downtrend structure）。
    tail label 屬 up → direction='up'、屬 down → 'down'、EQ/空 → 'none'。count = tail 連續同向 label 數。

    回 {count:int, direction:'up'|'down'|'none', labels:[...]}。labels 保留全序（俾 adjudicate eyeball）。
    sequence 少於 2 個同型 swing → labels 空、count 0、direction 'none'（不足，保守）。
    """
    prev = {"H": None, "L": None}
    labels: list = []
    for s in sequence or []:
        kind = s["kind"]
        p = prev[kind]
        if p is not None:
            if kind == "H":
                lbl = "HH" if s["price"] > p["price"] else ("LH" if s["price"] < p["price"] else "EQ")
            else:
                lbl = "HL" if s["price"] > p["price"] else ("LL" if s["price"] < p["price"] else "EQ")
            labels.append(lbl)
        prev[kind] = s

    count = 0
    direction = "none"
    for lbl in reversed(labels):
        if direction == "none":
            if lbl in _UP_LABELS:
                direction, target = "up", _UP_LABELS
            elif lbl in _DOWN_LABELS:
                direction, target = "down", _DOWN_LABELS
            else:
                break                                     # tail = EQ → 唔起 run
            count = 1
            continue
        if lbl in target:
            count += 1
        else:
            break
    return {"count": count, "direction": direction, "labels": labels}


def read_tf(bars, *, structure_cfg=None, swing_cfg=None) -> dict:
    """單 TF：detect_pivots(reuse) → swing_sequence(min_swing = atr_mult×ATR14) → consecutive_hl_lh。
    回 {atr14, min_swing, bars, pivots:{highs,lows}, sequence:[{kind,price,idx}], consecutive_hl_lh}。"""
    from analyze.swing_pivots import detect_pivots

    structure_cfg = structure_cfg or {}
    swing_cfg = swing_cfg or {}
    k = int(swing_cfg.get("k", 2))
    strict = bool(swing_cfg.get("strict_pivot", True))
    ms_cfg = structure_cfg.get("min_swing") or {}

    bars = bars or []
    price = bars[-1][_CLOSE] if bars else None            # off1 close 做 price ref（pct_price 用）
    a = atr14(bars)
    ms = min_swing_threshold(bars, price, ms_cfg)
    piv = detect_pivots(bars, k=k, strict=strict)
    seq = swing_sequence(piv, ms)
    chl = consecutive_hl_lh(seq)
    return {
        "atr14": round(a, 4) if a is not None else None,
        "min_swing": round(ms, 4) if ms is not None else None,
        "bars": len(bars),
        "pivots": {"highs": len(piv["highs"]), "lows": len(piv["lows"])},
        "sequence": [{"kind": s["kind"], "price": round(s["price"], 2), "idx": s["idx"]} for s in seq],
        "consecutive_hl_lh": chl,
    }


def read_structure(bars_by_tf, *, structure_cfg=None, swing_cfg=None) -> dict:
    """每 TF 行 read_tf。回 {tf: read_tf(...)}。deterministic（同 input 同 output）。"""
    return {tf: read_tf(bars or [], structure_cfg=structure_cfg, swing_cfg=swing_cfg)
            for tf, bars in (bars_by_tf or {}).items()}


def _load_ohlc(path) -> dict:
    """讀一份 ohlc_history 記錄。path = bundle dir（讀 dir/ohlc_history.json）或直接指向 .json。
    回 {bars, cycle, captured_utc, ...}。純讀，零寫。"""
    import json
    import os

    if os.path.isdir(path):
        path = os.path.join(path, "ohlc_history.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_bundle(path) -> dict:
    """glue：ohlc_history.json（bundle dir 或 .json 檔）+ config structure/swing → read_structure。
    只讀，零寫（守 floor：9333 read-only、唔 mutate bundle）。"""
    from capture.base import load_asset

    cfg = load_asset("xauusd")
    rec = _load_ohlc(path)
    result = read_structure(rec.get("bars", {}),
                            structure_cfg=cfg.get("structure"), swing_cfg=cfg.get("swing"))
    return {"cycle": rec.get("cycle"), "captured_utc": rec.get("captured_utc"),
            "by_tf": result}


if __name__ == "__main__":
    # read-only dump（唔 promote、唔寫 golden/）：py -m analyze.structure_read <bundle_dir|ohlc.json>
    import json as _json
    import sys as _sys

    _sys.stdout.reconfigure(encoding="utf-8")
    if len(_sys.argv) < 2:
        print("用法：py -m analyze.structure_read <bundle_dir|ohlc_history.json>")
        raise SystemExit(2)
    print(_json.dumps(read_bundle(_sys.argv[1]), ensure_ascii=False, indent=2))
