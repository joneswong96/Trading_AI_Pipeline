"""Step 6：scheduler 骨架 —— 每分鐘一 cycle，串起成條 M0 pipeline。

cycle：capture(route 1b) → precheck → [trigger?] analyze → call_writer → dedupe → [push] → store。
- 單一 cycle fail **唔可以**炒車成個 loop（PLAN）：run_cycle 全程 try/except，catch→log→下一 cycle。
- **未 go-live**：analyze() 未 wire（Step 3）會 raise；run_cycle 會接住、log error。真 push
  （Telegram/Notion）係 TODO，publisher 未配就唔 send（log only）。
- 守 floor：notify-only、單一 asset、永不落單。

run_cycle 嘅依賴用 `CycleDeps` 注入 → 可離線測（fake capture/prefilter/analyzer/store/publisher）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from capture.base import ROOT, force_utf8_stdout
from analyze import call_writer
from publish import dedupe

CALLS_DIR = ROOT / "storage" / "calls"
SCREENSHOTS_DIR = ROOT / "storage" / "screenshots"


@dataclass
class CycleDeps:
    capture: object        # .capture_bundle(cid) -> CycleResult；.route
    prefilter: object      # .check() -> PrecheckDecision
    analyzer: object       # .analyze(paths) -> AnalyzeResult（未 wire 會 raise）
    store: object          # .log_cycle(rec) / .last_pushed_features()
    publisher: object | None = None   # .enabled()/.push(text,img)；None/未配 = log only


def _make_marked(bundle, call: dict, cid: str, rec: dict) -> str | None:
    """M0 marked 圖（level legend box 畫喺主圖 g4）。失敗唔致命：log marker_error、回 None。"""
    try:
        from publish import marker
        main = next((s.path for s in bundle.shots
                     if s.ok and getattr(s, "shot_id", None) == "g4_5m_1m" and s.path),
                    None)
        if not main:
            return None
        out = str(CALLS_DIR / cid / "marked.png")
        # bottom-right：避開 top toolbar + 中右近期 price action（push contract 要求）
        return marker.mark_legend_box(main, out, marker.levels_from_call(call),
                                      title="Levels", corner="bottomright")
    except Exception as e:
        rec["marker_error"] = f"{type(e).__name__}: {e}"
        return None


def run_cycle(deps: CycleDeps, cycle_id: str | None = None) -> dict:
    cid = cycle_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    rec: dict = {
        "cycle_id": cid,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "route": getattr(deps.capture, "route", "?"),
        "pushed": 0,
        "bundle_dir": str(SCREENSHOTS_DIR / cid),
    }
    try:
        bundle = deps.capture.capture_bundle(cid)
        if not bundle.ok:
            rec["error"] = f"capture fail: {bundle.error or 'shot fail'}"
            rec["push_reason"] = "capture fail → 唔 push"
            deps.store.log_cycle(rec)
            return rec

        pre = deps.prefilter.check()
        rec["price"] = pre.price
        rec["precheck_triggered"] = int(pre.triggered)
        if not pre.triggered:
            rec["push_reason"] = f"precheck skip: {pre.reason}"
            deps.store.log_cycle(rec)
            return rec

        paths = [s.path for s in bundle.shots if s.ok and s.path]
        result = deps.analyzer.analyze(paths)          # ⏳ 未 wire → raise（接住）
        writ = call_writer.write_call(str(CALLS_DIR / cid), result.call, cycle_id=cid)
        feats = writ["features"]
        rec.update(
            action=feats.get("action"), grade=feats.get("grade"),
            trigger_price=feats.get("trigger"), alerts=feats.get("alerts"),
            has_ant=int(bool(feats.get("has_ant"))))

        marked = _make_marked(bundle, result.call, cid, rec)   # M0 level legend box（非致命）

        pd = dedupe.should_push(
            deps.store.last_pushed_features(), feats,
            prev_price=pre.prev_price, cur_price=pre.price)
        rec["push_reason"] = pd.reason

        if pd.push and deps.publisher is not None and deps.publisher.enabled():
            deps.publisher.push(writ["push"], marked)
            rec["pushed"] = 1
        elif pd.push:
            rec["push_reason"] = pd.reason + "（publisher 未配 → log only）"
    except Exception as e:                              # 單 cycle 出事唔炒車
        rec["error"] = f"{type(e).__name__}: {e}"
        rec.setdefault("push_reason", "error → 唔 push")
    deps.store.log_cycle(rec)
    return rec


def build_default_deps() -> CycleDeps:
    """真 deps（go-live 用）。analyze 仲 raise，所以淨係齊料先有意義。"""
    from capture.tv_mcp import CdpCapture
    from precheck.prefilter import Prefilter
    from analyze.claude_client import AnalyzeClient
    from publish.telegram import TelegramPublisher
    from storage.db import Store
    return CycleDeps(
        capture=CdpCapture(), prefilter=Prefilter(), analyzer=AnalyzeClient(),
        store=Store(), publisher=TelegramPublisher())


def main(argv: list[str] | None = None) -> None:
    import sys

    force_utf8_stdout()
    argv = sys.argv[1:] if argv is None else argv
    secs = 60
    try:
        import yaml
        with open(ROOT / "config" / "assets.yaml", encoding="utf-8") as f:
            secs = yaml.safe_load(f)["scheduler"]["interval_seconds"]
    except Exception:
        pass

    if "--start" not in argv:
        # 純 dry-run：只 check analyze 齊唔齊料，**唔好** build_default_deps（會 new Store → 開 db）。
        from analyze.claude_client import AnalyzeClient
        ok, missing = AnalyzeClient().ready()
        print("Step 6 scheduler 骨架。**未 go-live**："
              + ("料齊" if ok else f"analyze 未 wire（{missing}）→ 跑落每 cycle 只會 log error。"))
        print(f"確認要跑：py -m scheduler.run --start（每 {secs}s 一 cycle）")
        return

    # go-live 先 build deps（會 new Store → 開 db）+ 掛每日 prune job（唔入每分鐘 cycle）。
    from apscheduler.schedulers.blocking import BlockingScheduler
    from storage.retention import run_prune
    deps = build_default_deps()
    sched = BlockingScheduler()
    sched.add_job(lambda: print(run_cycle(deps)), "interval", seconds=secs,
                  next_run_time=datetime.now())
    sched.add_job(lambda: run_prune(deps.store), "cron", hour=4, minute=0)
    print(f"scheduler 起動，每 {secs}s 一 cycle + 每日 04:00 prune（Ctrl+C 停）。")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("scheduler 停咗。")


if __name__ == "__main__":
    main()
