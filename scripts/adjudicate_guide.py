"""scripts/adjudicate_guide.py — P3「點核導讀」generator（STEP 2 前置，由 scratchpad 歸位）。

忠實 re-walk structure_state._zigzag 邏輯（逐 pivot decision log）抽每 TF：入選 surviving swing /
被 min_swing 過濾嘅 pivot（price + reason + Δ）、HL/LH labels、consecutive count+direction、borderline
（confirm/drop 貼 min_swing 邊界 / near-tie equal-high）。**fidelity guard**：re-walk 嘅 surviving
sequence 同 analyze.structure_read.read_bundle 官方 sequence 逐 TF 對（MISMATCH 即 loud）。

權威 = scripts/structure_adjudicate.py（table）+ analyze/structure_read.py；本檔只抽 detail 俾人眼核。
唔改 P3 producer / 唔 promote；純讀 ohlc_history.json。
"""
from __future__ import annotations

from analyze.structure_read import consecutive_hl_lh, read_tf
from analyze.structure_state import atr, min_swing_threshold
from analyze.swing_pivots import detect_pivots

_TFS = ("m5", "m15", "h4", "d", "w")


def verbose_zigzag(pivots, min_swing):
    """同 structure_state._zigzag 同邏輯，但逐 pivot log 決定（seed/confirm/drop_insignificant/
    collapse_replace/collapse_keep + Δ）。回 (swings, log)。"""
    swings, log = [], []
    for p in pivots:
        if not swings:
            swings.append(dict(p))
            log.append((p, "seed", None))
            continue
        last = swings[-1]
        if p["kind"] == last["kind"]:
            more = (p["kind"] == "H" and p["price"] > last["price"]) or \
                   (p["kind"] == "L" and p["price"] < last["price"])
            log.append((p, "collapse_replace" if more else "collapse_keep", p["price"] - last["price"]))
            if more:
                swings[-1] = dict(p)
        else:
            d = abs(p["price"] - last["price"])
            log.append((p, "confirm" if d >= min_swing else "drop_insignificant", d))
            if d >= min_swing:
                swings.append(dict(p))
    return swings, log


def _points(piv):
    pts = [{"idx": h["idx"], "kind": "H", "price": h["price"]} for h in piv["highs"]]
    pts += [{"idx": low["idx"], "kind": "L", "price": low["price"]} for low in piv["lows"]]
    pts.sort(key=lambda x: x["idx"])
    return pts


_FILT_TAG = {"drop_insignificant": "反轉 Δ<min_swing 忽略",
             "collapse_keep": "同型非更極端→棄",
             "collapse_replace": "同型更極端→取代前一個"}


def tf_guide(bars, *, structure_cfg, swing_cfg) -> dict:
    """單 TF 導讀 + fidelity（re-walk surviving vs read_tf 官方 sequence）。"""
    k = int((swing_cfg or {}).get("k", 2))
    strict = bool((swing_cfg or {}).get("strict_pivot", True))
    ms_cfg = (structure_cfg or {}).get("min_swing") or {}
    bars = bars or []
    price = bars[-1][4] if bars else None
    ms = min_swing_threshold(bars, price, ms_cfg)
    a = atr(bars, 14)

    piv = detect_pivots(bars, k=k, strict=strict)
    swings, log = verbose_zigzag(_points(piv), ms) if ms else ([], [])
    chl = consecutive_hl_lh(swings)

    official = read_tf(bars, structure_cfg=structure_cfg, swing_cfg=swing_cfg)
    off_seq = [(s["kind"], s["price"]) for s in official["sequence"]]
    my_seq = [(s["kind"], round(s["price"], 2)) for s in swings]
    fidelity = "OK" if off_seq == my_seq else f"MISMATCH off={off_seq} me={my_seq}"

    filtered = [{"kind": p["kind"], "price": round(p["price"], 2), "idx": p["idx"],
                 "reason": _FILT_TAG[why], "delta": round(abs(d), 3)}
                for (p, why, d) in log if why in _FILT_TAG]
    borderline = _borderline(log, ms)
    return {
        "atr14": round(a, 4) if a is not None else None,
        "min_swing": round(ms, 4) if ms is not None else None,
        "bars": len(bars),
        "pivots": {"highs": len(piv["highs"]), "lows": len(piv["lows"])},
        "surviving": [{"kind": s["kind"], "price": round(s["price"], 2), "idx": s["idx"]}
                      for s in swings],
        "filtered": filtered,
        "labels": chl["labels"],
        "consecutive": {"direction": chl["direction"], "count": chl["count"]},
        "borderline": borderline,
        "fidelity": fidelity,
    }


def _borderline(log, ms):
    if not ms:
        return []
    hi_b, lo_b = 1.15 * ms, 0.85 * ms
    out = []
    for p, why, d in log:
        ad = abs(d) if d is not None else None
        if ad is None:
            continue
        if why == "confirm" and ms <= ad <= hi_b:
            out.append(f"confirm {p['kind']}@{round(p['price'],2)} Δ={round(ad,3)} 啱啱過 min_swing({round(ms,3)})")
        elif why == "drop_insignificant" and lo_b <= ad < ms:
            out.append(f"dropped {p['kind']}@{round(p['price'],2)} Δ={round(ad,3)} 啱啱唔過（貼邊界）")
        elif why in ("collapse_keep", "collapse_replace") and ad <= 0.10 * ms:
            out.append(f"near-tie {p['kind']}@{round(p['price'],2)} Δ={round(ad,3)} equal-high/low 附近")
    return out


def guide_bundle(bundle_dir) -> dict:
    """讀 ohlc_history.json + config → 逐 TF tf_guide。回 {cycle, captured_utc, by_tf, regime}。"""
    import json
    import os

    from capture.base import load_asset
    cfg = load_asset("xauusd")
    path = bundle_dir if str(bundle_dir).endswith(".json") else os.path.join(bundle_dir, "ohlc_history.json")
    rec = json.load(open(path, encoding="utf-8"))
    bars_by_tf = rec.get("bars", {})
    by_tf = {tf: tf_guide(bars_by_tf.get(tf) or [],
                          structure_cfg=cfg.get("structure"), swing_cfg=cfg.get("swing"))
             for tf in _TFS if tf in bars_by_tf}
    regime = {"up": 0, "down": 0, "none": 0}
    for g in by_tf.values():
        regime[g["consecutive"]["direction"]] += 1
    return {"cycle": rec.get("cycle"), "captured_utc": rec.get("captured_utc"),
            "by_tf": by_tf, "regime": regime}


def render_markdown(guide: dict) -> str:
    lines = ["═" * 67,
             f"# 點核導讀 — bundle `{guide.get('cycle')}`  (captured {guide.get('captured_utc')})",
             "═" * 67]
    for tf, g in guide["by_tf"].items():
        lines.append(f"\n## {tf.upper()}   (bars={g['bars']}, ATR14=min_swing={g['min_swing']}, "
                     f"fidelity={g['fidelity']})")
        lines.append(f"raw pivots：{g['pivots']['highs']} H / {g['pivots']['lows']} L → "
                     f"surviving {len(g['surviving'])}")
        lines.append("**入選 surviving swing：** " +
                     " → ".join(f"{s['kind']}{s['price']}(#{s['idx']})" for s in g["surviving"]))
        lines.append(f"**被過濾（{len(g['filtered'])}）：** " +
                     ("；".join(f"{f['kind']}@{f['price']}({f['reason']},Δ{f['delta']})"
                               for f in g["filtered"]) or "無"))
        lines.append(f"**labels：** {g['labels'] or '—'}")
        lines.append(f"**consecutive：** {g['consecutive']['direction']} × {g['consecutive']['count']}")
        lines.append("**borderline：** " + ("；".join(g["borderline"]) or "（無）"))
    r = guide["regime"]
    lines.append("\n" + "═" * 67)
    lines.append(f"# regime 分佈：up={r['up']} / down={r['down']} / none={r['none']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("用法：py -m scripts.adjudicate_guide <bundle_dir|ohlc_history.json>")
        raise SystemExit(2)
    print(render_markdown(guide_bundle(sys.argv[1])))
