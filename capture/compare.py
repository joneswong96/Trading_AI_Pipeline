"""Step 1c：兩條 capture 路線各跑 N 次，出穩定性對比報告（Jones 拍板用，我唔代揀）。

用法：
    python -m capture.compare --trials 10                  # 兩路各跑 10 次
    python -m capture.compare --trials 10 --routes playwright
報告寫去 docs/capture_comparison.md。
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .base import ROOT, CycleResult, force_utf8_stdout

REPORT_PATH = ROOT / "docs" / "capture_comparison.md"


def run_trials(adapter, n: int, pause_s: float = 2.0) -> list[CycleResult]:
    results = []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for i in range(1, n + 1):
        r = adapter.capture_bundle(f"trial-{adapter.route}-{stamp}-{i:02d}")
        print(f"  [{adapter.route}] {i}/{n}: {'✅' if r.ok else '❌'} {r.seconds:.1f}s"
              + (f" — {r.error}" if r.error else ""))
        results.append(r)
        if i < n:
            time.sleep(pause_s)
    return results


def summarize(results: list[CycleResult]) -> dict:
    n = len(results)
    ok = [r for r in results if r.ok]
    durs = [r.seconds for r in ok] or [0.0]
    errors = Counter()
    for r in results:
        if r.error:
            errors[r.error.split("\n")[0][:120]] += 1
        for s in r.shots:
            if not s.ok and s.error:
                errors[f"{s.shot_id}: {s.error.split(chr(10))[0][:100]}"] += 1
    return {
        "n": n, "ok": len(ok),
        "success_rate": f"{len(ok)}/{n}",
        "avg_s": sum(durs) / len(durs),
        "worst_s": max(durs),
        "errors": errors,
    }


def write_report(summaries: dict[str, dict], all_results: dict[str, list[CycleResult]],
                 path: Path = REPORT_PATH) -> Path:
    lines = [
        "# Capture 雙路穩定性對比（Step 1c）",
        "",
        f"> 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M %Z')}（AEDT）",
        "> **用途：Jones 揀主力路線用。本報告淨係出數據，唔落結論。**",
        "",
        "| 路線 | 成功率 | 平均耗時(成功) | 最差耗時 | 失敗原因 |",
        "|---|---|---|---|---|",
    ]
    for route, s in summaries.items():
        errs = "；".join(f"{m}×{c}" for m, c in s["errors"].most_common(3)) or "—"
        lines.append(f"| {route} | {s['success_rate']} | {s['avg_s']:.1f}s | "
                     f"{s['worst_s']:.1f}s | {errs} |")
    lines += ["", "## 逐次明細", ""]
    for route, results in all_results.items():
        lines.append(f"### {route}")
        lines.append("")
        lines.append("| # | ok | 耗時 | error |")
        lines.append("|---|---|---|---|")
        for i, r in enumerate(results, 1):
            lines.append(f"| {i} | {'✅' if r.ok else '❌'} | {r.seconds:.1f}s | "
                         f"{(r.error or '').split(chr(10))[0][:120] or '—'} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    force_utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--routes", default="playwright,tv_mcp_cdp")
    ap.add_argument("--pause", type=float, default=2.0)
    args = ap.parse_args()

    adapters = {}
    if "playwright" in args.routes:
        from .screenshot import PlaywrightCapture
        adapters["playwright"] = PlaywrightCapture()
    if "tv_mcp_cdp" in args.routes:
        from .tv_mcp import CdpCapture
        adapters["tv_mcp_cdp"] = CdpCapture()

    all_results, summaries = {}, {}
    for route, adapter in adapters.items():
        print(f"== {route}: {args.trials} 次 ==")
        all_results[route] = run_trials(adapter, args.trials, args.pause)
        summaries[route] = summarize(all_results[route])
    out = write_report(summaries, all_results)
    print(f"\n報告：{out}")


if __name__ == "__main__":
    main()
