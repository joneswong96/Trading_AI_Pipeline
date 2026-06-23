"""路線 1a（最簡版）：Playwright headless Chromium 開 save 好嘅 TV layout 截圖。

用 persistent profile 保住 TV 登入（Jones 用 --login 登入一次就記住）。

用法：
    python -m capture.screenshot --login          # 開有頭 browser 俾 Jones 登入 TV
    python -m capture.screenshot --once           # 截一個 bundle（5 張圖）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from .base import (
    ROOT, CycleResult, ShotResult, bundle_dir, detect_login_wall, force_utf8_stdout,
    load_asset, shot_url, timer,
)

RENDER_WAIT_MS = 4000  # 最簡版：固定等 chart render；對比測試會反映呢個成本


class PlaywrightCapture:
    route = "playwright"

    def __init__(self, asset: str = "xauusd", headless: bool = True):
        self.cfg = load_asset(asset)
        self.headless = headless
        self.profile_dir = os.environ.get(
            "PLAYWRIGHT_PROFILE_DIR", str(ROOT / "storage" / "pw_profile"))

    def capture_bundle(self, cycle_id: str) -> CycleResult:
        from playwright.sync_api import sync_playwright

        out = bundle_dir(cycle_id)
        shots: list[ShotResult] = []
        err: str | None = None
        with timer() as t_all:
            try:
                with sync_playwright() as p:
                    ctx = p.chromium.launch_persistent_context(
                        self.profile_dir, headless=self.headless,
                        viewport={"width": 1600, "height": 900})
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    for shot in self.cfg["screenshots"]:
                        shots.append(self._shot(page, shot, out))
                    ctx.close()
            except Exception as e:  # browser 層 fail：成個 bundle 算 fail
                err = f"{type(e).__name__}: {e}"
        ok = err is None and bool(shots) and all(s.ok for s in shots)
        return CycleResult(self.route, cycle_id, ok, t_all.seconds, shots, err)

    def _shot(self, page, shot: dict, out) -> ShotResult:
        url = shot_url(shot, self.cfg)
        path: str | None = None
        err: str | None = None
        with timer() as t:
            try:
                if not url:
                    raise RuntimeError("未設定 layout URL（填 config/assets.yaml）")
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(RENDER_WAIT_MS)
                path = str(out / f"{shot['id']}.png")
                page.screenshot(path=path)
                # 留住截圖做證物，但登入牆 → ok=False（唔好當成功）。
                err = detect_login_wall(page)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                path = None
        return ShotResult(shot["id"], err is None, path, t.seconds, err)


def login():
    """開有頭 browser 俾 Jones 登入 TV 一次，persistent profile 記住 session。"""
    from playwright.sync_api import sync_playwright
    cap = PlaywrightCapture(headless=False)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            cap.profile_dir, headless=False, viewport={"width": 1600, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tradingview.com/")
        print("👉 喺個 browser 登入 TradingView，搞掂就閂咗個 browser。")
        try:
            ctx.wait_for_event("close", timeout=0)
        except Exception:
            pass


if __name__ == "__main__":
    force_utf8_stdout()
    if "--login" in sys.argv:
        login()
    elif "--once" in sys.argv:
        cid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-manual"
        r = PlaywrightCapture().capture_bundle(cid)
        print(f"[{r.route}] cycle={r.cycle_id} ok={r.ok} {r.seconds:.1f}s"
              + (f" — {r.error}" if r.error else ""))
        for s in r.shots:
            print(f"  {s.shot_id}: {'✅' if s.ok else '❌ ' + (s.error or '')} {s.seconds:.1f}s")
    else:
        print(__doc__)
