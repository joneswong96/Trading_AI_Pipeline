"""路線 1b（最簡版）：CDP port 9222 接 Jones 部機開住 TV 嘅 Chrome 截圖。

PDF 路線 2 係 TradingView MCP（78–81 tools）；M0 對比測試淨係要「截圖」一個
功能，所以最簡版直接用 CDP（同 TV MCP 同一條通道）接現成 Chrome 嘅 TV tab
截圖。完整 TV MCP（精準 level／replay）係 M2/M3 先升級。

前置（runbook 有詳細步驟）：Jones 用 CDP 模式開 Chrome，並開定 5 個 layout tab。

用法：
    python -m capture.tv_mcp --once    # 截一個 bundle
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from .base import (
    CycleResult, ShotResult, bundle_dir, detect_login_wall, force_utf8_stdout,
    load_asset, shot_url, timer,
)

TAB_SETTLE_MS = 1000  # tab 本身 render 緊，bring_to_front 後少少 settle 就夠

# Route A — closed-bar (off1) MACD per pane. Validated accessor: chartsCount()+chart(i)._chartWidget.
_MACD_OFF1_JS = r"""(function(){
  var api = window.TradingViewApi;
  function norm(v){ if(!v) return null; return v.length>=5 ? [v[0],v[1],v[3],v[4]] : [v[0],v[1],v[2],v[3]]; }
  var log=[], out=[], n;
  try{ n=api.chartsCount(); }catch(e){ return {charts:[], log:['chartsCount err:'+e]}; }
  log.push('chartsCount='+n);
  for(var i=0;i<n;i++){
    try{
      var ch=api.chart(i);
      var cw=ch._chartWidget || (typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget);
      var iv=String(cw.model().mainSeries().interval());
      var off1=null, name=null, src=cw.model().model().dataSources();
      for(var j=0;j<src.length;j++){ if(src[j].metaInfo && /MACD|Convergence/i.test(src[j].metaInfo().description||'')){
        name=src[j].metaInfo().description; var d=src[j].data(); off1=norm(d.valueAt(d.lastIndex()-1)); break; } }
      out.push({interval:iv, off1:off1, macd:name});
      log.push('chart['+i+'] iv='+iv+(off1?' off1 ok':' off1 MISSING'));
    }catch(e){ log.push('chart['+i+'] err:'+String(e).slice(0,80)); }
  }
  return {charts:out, log:log};
})()"""


class CdpCapture:
    route = "tv_mcp_cdp"

    def __init__(self, asset: str = "xauusd", port: int | None = None):
        self.cfg = load_asset(asset)
        self.port = port or int(os.environ.get("TV_CDP_PORT", "9222"))

    def _find_page(self, pages, shot: dict, index: int):
        """配對 tab：URL 有設 → 淨係靠 URL 匹配（配唔到回 None，唔好靜靜截錯 tab）；
        冇設 URL → 先 fallback 按開 tab 次序（runbook 教 Jones 順序開 ①→⑤）。"""
        want = shot_url(shot, self.cfg)
        if want:
            for pg in pages:
                if pg.url.split("?")[0].rstrip("/") == want.split("?")[0].rstrip("/"):
                    return pg
            return None  # URL 有設但搵唔到 → loud fail，唔好 fallback 去 index 截錯 instrument
        return pages[index] if index < len(pages) else None

    def capture_bundle(self, cycle_id: str) -> CycleResult:
        from playwright.sync_api import sync_playwright

        out = bundle_dir(cycle_id)
        shots: list[ShotResult] = []
        err: str | None = None
        with timer() as t_all:
            try:
                with sync_playwright() as p:
                    # 127.0.0.1（唔用 localhost）：Windows localhost 行 ::1 先，但 Chrome CDP
                    # 淨係 listen 127.0.0.1（IPv4），用 localhost 會先撞 ::1 timeout 慢 ~3s。
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
                    pages = [pg for ctx in browser.contexts for pg in ctx.pages
                             if "tradingview.com/chart" in pg.url]
                    if not pages:
                        raise RuntimeError(
                            f"CDP {self.port} 連到 Chrome 但搵唔到 TV chart tab（睇 runbook Step 1b）")
                    for i, shot in enumerate(self.cfg["screenshots"]):
                        shots.append(self._shot(pages, shot, i, out))
                    # Route A — capture-time closed-bar off1 MACD → bundle/macd_closed.json (replayable).
                    self._read_macd_closed(pages, out)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
        ok = err is None and bool(shots) and all(s.ok for s in shots)
        return CycleResult(self.route, cycle_id, ok, t_all.seconds, shots, err)

    def _shot(self, pages, shot: dict, index: int, out) -> ShotResult:
        path: str | None = None
        err: str | None = None
        with timer() as t:
            try:
                pg = self._find_page(pages, shot, index)
                if pg is None:
                    want = shot_url(shot, self.cfg) or f"按次序第 {index + 1} 個"
                    raise RuntimeError(
                        f"搵唔到 {shot['id']} 嘅 tab（want={want}）— "
                        f"要喺 CDP Chrome 開齊 5 個 layout 並登入")
                pg.bring_to_front()
                pg.wait_for_timeout(TAB_SETTLE_MS)
                path = str(out / f"{shot['id']}.png")
                pg.screenshot(path=path)
                # 留住截圖做證物，但登入牆 → ok=False（唔好當成功）。
                err = detect_login_wall(pg)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                path = None
        return ShotResult(shot["id"], err is None, path, t.seconds, err)

    GATE_TAB_FRAGS = ("cpPWuLlN", "avpCVaw2")     # g4=5m+1m, g5=15m+30m
    IV_TO_KEY = {"1": "m1", "5": "m5", "15": "m15", "30": "m30"}

    def _read_macd_closed(self, pages, out) -> None:
        """Closed-bar (off1) MACD for the 4 gate TFs, stored in bundle. Non-fatal: the 5
        screenshots are capture's primary contract — never raise out of here."""
        readings: dict = {}
        discovery: dict = {}
        try:
            for frag in self.GATE_TAB_FRAGS:
                pg = next((x for x in pages if frag in x.url), None)
                if pg is None:
                    discovery[frag] = {"error": "tab not found"}
                    continue
                res = pg.evaluate(_MACD_OFF1_JS)           # same Playwright channel, pure read
                discovery[frag] = {"log": res.get("log")}
                for ch in res.get("charts") or []:
                    key = self.IV_TO_KEY.get(str(ch.get("interval")))
                    off1 = ch.get("off1")
                    if key and off1:
                        readings[key] = {"hist": round(off1[1], 4), "macd": round(off1[2], 4),
                                         "signal": round(off1[3], 4), "bar_time": off1[0]}
        except Exception as e:                              # belt-and-braces: never break capture
            discovery["_error"] = f"{type(e).__name__}: {e}"
        record = {
            "kind": "macd_closed_bar_off1", "cycle": out.name,
            "captured_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "discovery": discovery, "readings": readings,
            "complete": all(k in readings for k in ("m1", "m5", "m15", "m30")),
        }
        (out / "macd_closed.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    force_utf8_stdout()
    if "--once" in sys.argv:
        cid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-manual"
        r = CdpCapture().capture_bundle(cid)
        print(f"[{r.route}] cycle={r.cycle_id} ok={r.ok} {r.seconds:.1f}s"
              + (f" — {r.error}" if r.error else ""))
        for s in r.shots:
            print(f"  {s.shot_id}: {'✅' if s.ok else '❌ ' + (s.error or '')} {s.seconds:.1f}s")
    else:
        print(__doc__)
