"""scripts/structure_adjudicate.py — P3 adjudication pack（代替 machine-verify）。

P3 冇 ground-truth oracle → 唔可以自動 verify。呢個 script 對真 capture bundle 逐個 dump algo 判斷
（用咗邊啲 pivots、ATR14、min_swing、顯著 HL/LH sequence、consecutive count + 方向）成一份人眼可核嘅
markdown（+ JSON），俾 Jones 對圖 eyeball sign-off。**只讀、零寫、唔 promote。**

用法：
  py -m scripts.structure_adjudicate --bundle <id|dir|ohlc_history.json>
  py -m scripts.structure_adjudicate --recent 3         # storage/screenshots 最近 3 個有 ohlc 嘅 bundle
  py -m scripts.structure_adjudicate --bundle tests/fixtures/structure_ohlc_sample.json  # demo/fixture

⚠️ 現況（2026-07-03）：storage/screenshots 舊 bundle 全部冇 ohlc_history.json（--ohlc producer 後補、
   從未 persist 落舊 bundle）。真 3-bundle adjudication 要 Jones 先開 CDP 跑 tv9333 --ohlc 影 fresh bundle。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # trading-auto/
SHOTS = os.path.join(ROOT, "storage", "screenshots")


def _resolve(bundle: str) -> str:
    """--bundle 值 → ohlc_history.json 實際路徑。接受：.json 檔 / bundle dir / bare cycle id。"""
    if bundle.endswith(".json") and os.path.isfile(bundle):
        return bundle
    if os.path.isdir(bundle):
        return os.path.join(bundle, "ohlc_history.json")
    cand = os.path.join(SHOTS, bundle, "ohlc_history.json")          # bare cycle id
    if os.path.isfile(cand):
        return cand
    return bundle                                                    # 交俾 loader loud-fail


def _recent(n: int) -> list:
    """storage/screenshots 掃有 ohlc_history.json 嘅 bundle dir，按 mtime 新→舊取 n 個。"""
    if not os.path.isdir(SHOTS):
        return []
    hits = []
    for name in os.listdir(SHOTS):
        p = os.path.join(SHOTS, name)
        oh = os.path.join(p, "ohlc_history.json")
        if os.path.isdir(p) and os.path.isfile(oh):
            hits.append((os.path.getmtime(oh), oh))
    hits.sort(reverse=True)
    return [oh for _, oh in hits[:n]]


def _adjudicate_one(path: str) -> dict:
    from analyze.structure_read import read_bundle

    res = read_bundle(path)
    res["source"] = os.path.relpath(path, ROOT)
    return res


def _to_markdown(res: dict) -> str:
    lines = [f"## bundle `{res.get('cycle')}`  ({res.get('source')})",
             f"- captured_utc: {res.get('captured_utc')}", ""]
    lines.append("| TF | bars | ATR14 | min_swing | pivots(H/L) | sig sequence (kind@price) | labels | consecutive |")
    lines.append("|----|------|-------|-----------|-------------|---------------------------|--------|-------------|")
    for tf, r in res.get("by_tf", {}).items():
        seq = " → ".join(f"{s['kind']}{s['price']}" for s in r["sequence"]) or "—"
        chl = r["consecutive_hl_lh"]
        labels = ",".join(chl["labels"]) or "—"
        piv = r["pivots"]
        lines.append(f"| {tf} | {r['bars']} | {r['atr14']} | {r['min_swing']} | "
                     f"{piv['highs']}/{piv['lows']} | {seq} | {labels} | "
                     f"**{chl['direction']} ×{chl['count']}** |")
    lines.append("")
    lines.append("> ⚠️ P3 冇 oracle：algo 判斷僅供 Jones **對圖 eyeball**。sign-off 前唔 promote / 唔 wire /analyze。")
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="P3 structure adjudication dump（只讀）")
    ap.add_argument("--bundle", help="cycle id / bundle dir / ohlc_history.json 路徑")
    ap.add_argument("--recent", type=int, metavar="N", help="storage/screenshots 最近 N 個有 ohlc 嘅 bundle")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args(argv)

    if not args.bundle and not args.recent:
        ap.error("要俾 --bundle <id|dir|json> 或 --recent N")

    paths = []
    if args.bundle:
        paths.append(_resolve(args.bundle))
    if args.recent:
        paths.extend(_recent(args.recent))
    if not paths:
        print("冇搵到有 ohlc_history.json 嘅 bundle。先開 CDP 跑 `py -m capture.tv9333 --ohlc` "
              "影 fresh bundle，或用 --bundle 指去 fixture。", file=sys.stderr)
        return 3

    results = []
    for p in paths:
        if not os.path.isfile(p):
            print(f"[skip] 揾唔到 {p}（bundle 冇 ohlc_history.json？）", file=sys.stderr)
            continue
        results.append(_adjudicate_one(p))

    if not results:
        return 3
    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(_to_markdown(r) for r in results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
