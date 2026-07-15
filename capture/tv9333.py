"""9333 — 專用 data-read TradingView instance（同 9222 capture 完全隔離）。

定位：9222 = capture Chrome（5 tab，一隻都唔准掂）。9333 = 獨立 Chrome，做將來
DXY / H4·D·W OHLC / M2 multi-symbol 取數，唔阻住 capture。

設計：
- 一條命令 ensure：`py -m capture.tv9333 --ensure`
  health 探 9333 → 未起就 launch（持久 profile + 直接開 saved-layout URL，唔靠
  MCP layout_switch）→ connect_over_cdp(9333) 驗證 → 報 ready / drift。
- 純 Playwright CDP 通道（同 Route A 同一 proven accessor），唔經 patched MCP
  server、唔用 layout_switch（report success 但唔 reflect，夾硬載會卡死）。
- 9222 一個字都唔掂：PORT 鎖死 9333，guard 拒絕 9222。

⚠️ M1.1（2026-06-18）：ensure 喺 panes ready 後 on-launch 校 chartType→Candles(1)
（Fork B，_correct_chart_type；9333-local 逐 pane setChartType，永不 re-save cloud
layout —— cpPWuLlN/avpCVaw2 同 9222 共享，re-save 會 flip 9222 production）。chartType-19
真身 = Volume Candles（cosmetic real-OHLC，唔影響 OHLC/MACD 讀數）。其餘 auto-correct
（setSymbol / MACD detect-not-duplicate）仍留 M2。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from .base import ROOT, force_utf8_stdout, load_asset

PORT = 9333                       # 鎖死；9222 = capture，唔准掂
PROFILE = os.path.join(os.environ.get("USERPROFILE", ""), "ChromeCDP9333")
# ↑ 實況 C:\Users\<u>\ChromeCDP9333（2026-06-18 pre-flight 鎖實：喺 USERPROFILE，唔喺 LOCALAPPDATA）
CHROME = os.environ.get("TV_CHROME",
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe")
LAUNCH_TIMEOUT_S = 30
GATE_FRAGS = ("cpPWuLlN", "avpCVaw2")   # g4=5m+1m, g5=15m+30m（gate verify 目標）
EXPECT_SYMBOL = "ICMARKETS:XAUUSD"
EXPECT_CHARTTYPE = 1                     # Candles

# P1（htf_override C，2026-06-20）— g6_HTF = 9333-only HTF read tab（H4+D+W，純讀 OHLC 算方向）。
# 唔入 GATE_FRAGS：冇 MACD，唔當 gate verify 目標（加入會令 _verify 報 MACD missing 假 drift）；
# 但會接落 launch URL（開埋呢個 tab）+ 被 _correct_chart_type 全-tab loop 校 candles。
HTF_FRAG = "pNqcbOmu"                    # g6_HTF saved layout slug
HTF_IV_TO_KEY = {"240": "h4", "1D": "d", "D": "d", "1W": "w", "W": "w"}

# 防禦式 per-pane 讀：interval 用已驗 accessor；symbol/chartType/MACD best-effort +
# log，第一次真 run 睇 log 鎖實 accessor（同 Route A discovery 同一手法）。
_VERIFY_JS = r"""(function(){
  var api=window.TradingViewApi, log=[], out=[], n;
  function macdName(s){ for(var j=0;j<s.length;j++){ if(s[j].metaInfo &&
    /MACD|Convergence/i.test(s[j].metaInfo().description||'')) return s[j].metaInfo().description; } return null; }
  try{ n=api.chartsCount(); }catch(e){ return {charts:[], log:['chartsCount err:'+e]}; }
  log.push('chartsCount='+n);
  for(var i=0;i<n;i++){
    var r={interval:null, symbol:null, chartType:null, macd:null};
    try{
      var ch=api.chart(i), cw=ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget);
      var ms=cw.model().mainSeries();
      try{ r.interval=String(ms.interval()); }catch(e){ log.push('iv['+i+'] '+e); }
      try{ var si=ms.symbolInfo&&ms.symbolInfo(); r.symbol=si?(si.pro_name||si.full_name||si.name||null):null; }
        catch(e){ log.push('sym['+i+'] '+String(e).slice(0,60)); }
      try{ r.chartType=(ms.properties&&ms.properties().childs&&ms.properties().childs().style)?
        ms.properties().childs().style.value():(ms.style?ms.style():null); }
        catch(e){ log.push('type['+i+'] '+String(e).slice(0,60)); }
      try{ r.macd=macdName(cw.model().model().dataSources()); }catch(e){ log.push('macd['+i+'] '+String(e).slice(0,60)); }
    }catch(e){ log.push('chart['+i+'] '+String(e).slice(0,80)); }
    out.push(r);
    log.push('chart['+i+'] iv='+r.interval+' sym='+r.symbol+' type='+r.chartType+' macd='+(r.macd?'Y':'N'));
  }
  return {charts:out, log:log};
})()"""

# 截圖 / 取數前 hygiene：清 crosshair（accessor 待真 run 驗）+ bring_to_front。
_CLEAR_CROSSHAIR_JS = r"""(function(){ try{
  var api=window.TradingViewApi, n=api.chartsCount();
  for(var i=0;i<n;i++){ var cw=api.chart(i)._chartWidget,
    cs=cw.model().crosshairSource&&cw.model().crosshairSource();
    if(cs&&cs.clearPosition) cs.clearPosition(); }
  return true; }catch(e){ return String(e); } })()"""

# M1.1 Fork B — 全 chart ready gate（撞過 "Value is null"，未 ready 唔好 set）。
# ready = bars 有資料 AND symbolInfo().pro_name 已 resolve —— cold-load 時 symbolInfo/MACD
# 會 lag 過 bars，等 symbol resolve 先讀，令 macd_before/symbol 非 vacuous（guard-4 有效）。
_CHARTS_READY_JS = """(function(){ try{
  var api=window.TradingViewApi, n=api.chartsCount();
  for(var i=0;i<n;i++){ var ch=api.chart(i),
    cw=ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget);
    var b=cw.model().mainSeries().bars(); if(!(b && b.lastIndex()>=0)) return false;
    try{ var si=cw.model().mainSeries().symbolInfo();
         if(!si || !si.pro_name) return false; }catch(e){ return false; } }
  return n>0; }catch(e){ return false; } })()"""

# M1.1 Fork B — per-pane chartType→Candles(1)。idempotent（==1 跳）+ ready-gated + set 後
# re-read（fail-loud）+ symbol/MACD before-after（證 setChartType 只郁 mainSeries style）。
# MACD 偵測 = MACD-promote proven accessor：cw（fallback）+ cw.model().model().dataSources()。
_SET_CANDLES_JS = r"""(function(){
  var api=window.TradingViewApi, out=[], n;
  function cwOf(ch){ return ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget); }
  function macdPresent(cw){ try{ var s=cw.model().model().dataSources();
    for(var j=0;j<s.length;j++){ if(s[j].metaInfo && /MACD|Convergence/i.test(s[j].metaInfo().description||'')) return true; }
    return false; }catch(e){ return null; } }
  try{ n=api.chartsCount(); }catch(e){ return {err:'chartsCount '+e}; }
  for(var i=0;i<n;i++){
    var r={i:i};
    try{
      var ch=api.chart(i), cw=cwOf(ch), ms=cw.model().mainSeries();
      try{ r.interval=String(ms.interval()); }catch(e){}
      try{ var si=ms.symbolInfo&&ms.symbolInfo(); r.symbol=si?(si.pro_name||si.full_name||null):null; }catch(e){ r.symbol=null; }
      r.macd_before=macdPresent(cw);
      r.before=ch.chartType();
      var b=ms.bars(); r.ready=!!(b && b.lastIndex()>=0);
      if(!r.ready){ r.action='skip_not_ready'; out.push(r); continue; }
      if(r.before===1){ r.action='skip_already'; r.after=1; r.macd_after=r.macd_before; out.push(r); continue; }
      ch.setChartType(1);
      r.after=ch.chartType(); r.macd_after=macdPresent(cw);
      try{ var si2=ms.symbolInfo&&ms.symbolInfo(); r.symbol_after=si2?(si2.pro_name||si2.full_name||null):null; }catch(e){}
      r.action=(r.after===1)?'set_ok':'set_FAIL';
    }catch(e){ r.err=String(e).slice(0,100); r.action='error'; }
    out.push(r);
  }
  return {charts:out};
})()"""

# best-effort：等 MACD study 掛上（cold-load MACD lag 過 symbol）。唔做 hard gate —— M2
# 無-MACD tab 等到 timeout 就照行（唔 deadlock，macd_before 真實反映「無 MACD」）。
_MACD_READY_JS = """(function(){ try{
  var api=window.TradingViewApi, n=api.chartsCount();
  for(var i=0;i<n;i++){ var ch=api.chart(i),
    cw=ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget);
    var s=cw.model().model().dataSources(), found=false;
    for(var j=0;j<s.length;j++){ if(s[j].metaInfo && /MACD|Convergence/i.test(s[j].metaInfo().description||'')){ found=true; break; } }
    if(!found) return false; }
  return n>0; }catch(e){ return false; } })()"""

# P1 — g6_HTF 純讀 closed-bar(off1) OHLC（mirror tv_mcp._read_macd_closed，零 mutation）。
# 鎖 mainSeries()（唔讀 Weekly pane 個 "SMA 20 close" overlay study series）。off1=lastIndex-1
# （排除 forming bar）；向後攞 want 支 closed close 俾 SMA。bar value array 鎖 [time,open,high,
# low,close]→close=v[4]；off1_ohlc 全出做 audit（real-run 驗 H>=max(O,C)/L<=min/gapless 證 index 啱）。
# 注意：呢個係 function expression（唔即時 invoke），由 page.evaluate(js, want) 傳 want。
_HTF_OHLC_JS = r"""(function(want){
  var api=window.TradingViewApi, log=[], out=[], n;
  function cwOf(ch){ return ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget); }
  try{ n=api.chartsCount(); }catch(e){ return {charts:[], log:['chartsCount err:'+e]}; }
  log.push('chartsCount='+n);
  for(var i=0;i<n;i++){
    var r={interval:null, symbol:null, closes:null, off1_time:null, off1_ohlc:null, last:null};
    try{
      var ch=api.chart(i), cw=cwOf(ch), ms=cw.model().mainSeries();
      r.interval=String(ms.interval());
      try{ var si=ms.symbolInfo&&ms.symbolInfo(); r.symbol=si?(si.pro_name||si.full_name||null):null; }catch(e){}
      var b=ms.bars(), last=b.lastIndex(); r.last=last;
      var closes=[];
      for(var k=0;k<want;k++){
        var idx=last-1-k; if(idx<0) break;          // off1=last-1 起，排除 forming(last)
        var v=b.valueAt(idx); if(!v) break;          // valueAt 斷即停（唔靜靜跳空填）
        var close=(v.length>=5)?v[4]:(v.length>=4?v[3]:null);
        if(k===0){ r.off1_time=v[0];
          r.off1_ohlc=(v.length>=5)?[v[1],v[2],v[3],v[4]]:null; }
        closes.push(close);
      }
      r.closes=closes;
      log.push('chart['+i+'] iv='+r.interval+' sym='+r.symbol+' last='+last+' got='+closes.length+
               (closes.length?(' off1C='+closes[0]):''));
    }catch(e){ log.push('chart['+i+'] err:'+String(e).slice(0,90)); }
    out.push(r);
  }
  return {charts:out, log:log};
})"""


def _http_json(path: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def health() -> dict | None:
    """9333 CDP up？回 {version, chart_targets, targets} 或 None（唔 raise）。"""
    ver = _http_json("/json/version")
    if ver is None:
        return None
    lst = _http_json("/json/list") or []
    charts = [t for t in lst if "tradingview.com/chart" in (t.get("url") or "")]
    return {"version": ver.get("Browser"), "chart_targets": len(charts), "targets": charts}


def health_state() -> dict:
    """三態：down（port 唔通）/ up_no_target（chrome 起咗但冇 chart tab）/ healthy（chart tab 在）。"""
    h = health()
    if h is None:
        state = "down"
    elif not h["chart_targets"]:
        state = "up_no_target"
    else:
        state = "healthy"
    return {"state": state, "health": h}


def launch_chrome() -> None:
    """持久 profile 起 9333 + 直接開 gate layout URL（唔靠 layout_switch）。
    同 profile 已起 → Chrome single-instance 把 URL 轉去現有 instance 即退；所以
    ensure() 一定先 health() 確認 port，唔 reflect 就 fail-loud。"""
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    cfg = load_asset()
    urls = [s["url"] for s in cfg["screenshots"]
            if any(f in s["url"] for f in GATE_FRAGS)]
    htf_url = (cfg.get("htf_read") or {}).get("url")    # P1：g6_HTF（9333-only HTF read tab）
    if htf_url:
        urls.append(htf_url)                            # 接落 gate URL 後，launch 次序保留
    dxy_url = (cfg.get("dxy_read") or {}).get("url")    # P2a：g7_DXY（9333-only DXY read tab）
    if dxy_url:
        urls.append(dxy_url)                            # 接落 g6 後；留空時跳過（launch 安全）
    args = [CHROME, f"--remote-debugging-port={PORT}",
            f"--user-data-dir={PROFILE}", "--new-window", *urls]
    subprocess.Popen(args, close_fds=True)   # detach；Python 退咗 Chrome 照住


def _drift_for_charts(charts, *, symbol, intervals, macd_required) -> list:
    """per-tab data-driven drift（純判定，可單測）。每 pane 驗 expected symbol / interval /
    chartType；macd_required 先驗 MACD present。symbol 或 interval 漂 → drift（g7 正面受保護）。
    getter err 時值會係 None → 當 log 唔當 drift（同 M1 行為）。"""
    drift = []
    for ch in charts or []:
        sym, typ, macd, iv = ch.get("symbol"), ch.get("chartType"), ch.get("macd"), ch.get("interval")
        if sym not in (None, symbol):
            drift.append(f"iv{iv} symbol={sym} (want {symbol})")
        if typ not in (None, EXPECT_CHARTTYPE):
            drift.append(f"iv{iv} type={typ}")
        if intervals and iv is not None and str(iv) not in intervals:
            drift.append(f"iv{iv} unexpected (want {intervals})")
        if macd_required and macd is None:
            drift.append(f"iv{iv} MACD missing")
    return drift


def _verify() -> dict:
    """per-tab data-driven verify（2026-06-20 P2a）：iterate config tv9333_tabs，每 tab 用
    自己 expected symbol/interval 驗 drift。原本只驗 g4/g5 → 依家連 g6 HTF / g7 DXY 都正面保護。
    symbol 預設 EXPECT_SYMBOL（XAUUSD），DXY tab 喺 config 指定 TVC:DXY；共用常數唔放闊。"""
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    from playwright.sync_api import sync_playwright

    specs = load_asset().get("tv9333_tabs") or []
    report: dict = {}
    seen = 0
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "tradingview.com/chart" in pg.url]
        for spec in specs:
            frag = spec["frag"]
            pg = next((x for x in pages if frag in x.url), None)
            if pg is None:
                report[frag] = {"error": "tab not found"}
                continue
            seen += 1
            res = pg.evaluate(_VERIFY_JS)
            report[frag] = {"log": res.get("log"), "drift": _drift_for_charts(
                res.get("charts"), symbol=spec.get("symbol", EXPECT_SYMBOL),
                intervals=[str(i) for i in (spec.get("intervals") or [])],
                macd_required=bool(spec.get("macd_required")))}
    ok = bool(specs) and seen == len(specs) and all(
        not report[s["frag"]].get("drift") and not report[s["frag"]].get("error") for s in specs)
    return {"ok": ok, "note": "per-tab data-driven verify（P2a 2026-06-20）：每 tab 用 config "
            "tv9333_tabs 嘅 expected symbol/interval 驗 drift；gate=要 MACD、g6/g7=唔要；"
            "g6 HTF + g7 DXY 正面受 drift-guard 保護；auto-correct（drift 自動改）留 M2。",
            "tabs": report}


def _await_charts_ready(pg, timeout: float = 25.0) -> bool:
    """等 pane mainSeries 有 bars 先好 set（撞過 'Value is null'）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if pg.evaluate(_CHARTS_READY_JS):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def _await_macd_settled(pg, timeout: float = 15.0) -> None:
    """best-effort：等 MACD study 掛齊先返（gate tab）；timeout 就照行（M2 無-MACD tab 唔 deadlock）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if pg.evaluate(_MACD_READY_JS):
                return
        except Exception:
            pass
        time.sleep(0.5)


def _correct_tab_ok(charts) -> bool:
    """Fork B guard-4（純判定，可單測；2026-06-20 Option B 改 symbol-agnostic）。每 pane：
    - action ∈ {set_ok, skip_already}
    - setChartType 冇改 symbol：symbol_after（只 set_ok 先有）== symbol —— 驗「set 有冇 mutate
      symbol」呢個真 invariant，唔再硬鎖 EXPECT_SYMBOL（XAUUSD/TVC:DXY/M2 multi-symbol 都啱；
      tab 係咪正確 instrument 係 _verify 嘅 per-tab job）。
    - MACD 冇被 set 整跌：macd_before True 而 macd_after False = 問題。
    """
    for ch in charts or []:
        if ch.get("action") not in ("set_ok", "skip_already"):
            return False
        if ch.get("macd_before") and ch.get("macd_after") is False:
            return False
        if ch.get("symbol_after") and ch.get("symbol_after") != ch.get("symbol"):
            return False
    return True


def _correct_chart_type() -> dict:
    """M1.1 Fork B：每個 9333 chart tab 逐 pane chartType→Candles(1)。9333-local，永不
    re-save cloud layout（同 9222 共享）。idempotent + ready-gated + set 後 re-read 驗。"""
    assert PORT != 9222, "refuse: 9333 setter must never target 9222"   # guard 5
    from playwright.sync_api import sync_playwright

    report: dict = {}
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        pages = [pg for ctx in browser.contexts for pg in ctx.pages   # 全 chart tab → M2 新 tab 自動 cover
                 if "tradingview.com/chart" in pg.url]
        for pg in pages:
            key = next((f for f in GATE_FRAGS if f in pg.url),
                       pg.url.split("/chart/")[-1].strip("/"))
            if not _await_charts_ready(pg):                           # guard 3
                report[key] = {"error": "charts not ready (timeout)"}
                ok = False
                continue
            _await_macd_settled(pg)                                   # best-effort：等 MACD 掛齊
            res = pg.evaluate(_SET_CANDLES_JS)                        # guard 1+2
            report[key] = res
            if not _correct_tab_ok(res.get("charts")):               # guard 4（symbol-agnostic）
                ok = False
    return {"ok": ok, "tabs": report}


def ensure_up() -> dict:
    """P0 idempotent 冷啟動：health 探 → down 先 launch（持久 profile + 直開 gate URL，唔靠
    layout_switch）→ poll 到 port 上；up 就唔重複開。回 {"ok":True,"health","launched"} 或
    {"ok":False,"error"}。"""
    h = health()
    if h is not None:
        return {"ok": True, "health": h, "launched": False}
    launch_chrome()
    t0 = time.time()
    while time.time() - t0 < LAUNCH_TIMEOUT_S:
        time.sleep(1.0)
        h = health()
        if h:
            return {"ok": True, "health": h, "launched": True}
    return {"ok": False, "error": f"9333 port 冇上嚟（{LAUNCH_TIMEOUT_S}s）。若 ChromeCDP9333 "
            f"profile 已開住但冇 debug port，請全閂該 profile 嘅 Chrome 再跑一次 --ensure。"}


def ensure() -> dict:
    up = ensure_up()                       # P0 idempotent 冷啟動（先）
    if not up["ok"]:
        return {"ok": False, "stage": "launch", "error": up["error"]}
    correct = _correct_chart_type()        # M1.1 Fork B — 校 chartType 後先 verify（次序不變）
    verify = _verify()
    return {"ok": verify["ok"] and correct["ok"], "stage": "verify",
            "health": up["health"], "correct": correct, "verify": verify}


def hygiene(page) -> None:
    """截圖 / 取數前：清 crosshair + bring_to_front（M2 取數會用）。"""
    try:
        page.evaluate(_CLEAR_CROSSHAIR_JS)
    except Exception:
        pass
    page.bring_to_front()


SHOT_SETTLE_MS = 800   # bring_to_front 後 settle，防 9333 ad-hoc 截圖 stale frame


def shoot(out_dir: str | None = None) -> dict:
    """9333 ad-hoc 截圖：逐 gate tab hygiene（clearPosition + bring_to_front）後截圖。
    9333-only，同 9222 capture pipeline（capture/tv_mcp.py）完全隔離。未 healthy 唔 auto-launch，
    乾淨 fail（叫 user 先 --ensure），唔俾食 stack trace。"""
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    state = health_state()["state"]
    if state != "healthy":
        return {"ok": False, "error": f"9333 未 healthy（{state}），先跑 --ensure"}
    from playwright.sync_api import sync_playwright

    out = Path(out_dir) if out_dir else (
        ROOT / "storage" / "tv9333_shots" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    shots: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "tradingview.com/chart" in pg.url]
        for frag in GATE_FRAGS:
            pg = next((x for x in pages if frag in x.url), None)
            if pg is None:
                shots[frag] = {"error": "tab not found"}
                continue
            hygiene(pg)                          # clearPosition + bring_to_front（截圖前置封裝）
            pg.wait_for_timeout(SHOT_SETTLE_MS)
            shots[frag] = {"path": str(out / f"{frag}.png")}
            pg.screenshot(path=shots[frag]["path"])
    ok = len(shots) == len(GATE_FRAGS) and all("path" in v for v in shots.values())
    return {"ok": ok, "dir": str(out), "shots": shots}


def read_htf_closed(bundle_dir) -> dict:
    """P1（htf_override C）— g6_HTF 純讀 closed-bar(off1) OHLC → 算 H4/D/W 方向 → 寫
    bundle/htf_closed.json。純讀（零 setResolution/setSymbol/setChartType），mirror
    tv_mcp._read_macd_closed；9333-only，同 9222 capture 完全隔離。

    H1 readiness gate：讀前過 _await_charts_ready（symbolInfo.pro_name + bars），免 cold
    --ensure 後即讀撞 race 攞 null。H2：每 TF 記 bars_loaded/sma_len/band，不足 history →
    auditable NEUTRAL（htf_direction.summarize 計），唔靜靜過。"""
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    from playwright.sync_api import sync_playwright

    from analyze.htf_direction import summarize   # analyze/ 係 top-level package（唔喺 capture/）

    cfg = load_asset()
    knobs = cfg.get("htf_direction") or {}
    sma_len = int(knobs.get("sma_len", 20))
    band = float(knobs.get("band", 0.001))
    want = sma_len + 2                       # buffer：valueAt 若中斷未夠數 → summarize 自然 NEUTRAL
    out = Path(bundle_dir)
    out.mkdir(parents=True, exist_ok=True)
    readings: dict = {}
    discovery: dict = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
            pages = [pg for ctx in browser.contexts for pg in ctx.pages
                     if "tradingview.com/chart" in pg.url]
            pg = next((x for x in pages if HTF_FRAG in x.url), None)
            if pg is None:
                discovery[HTF_FRAG] = {"error": "g6_HTF tab 搵唔到（先 --ensure 開 9333）"}
            elif not _await_charts_ready(pg):           # H1 readiness gate
                discovery[HTF_FRAG] = {"error": "charts not ready (timeout)"}
            else:
                res = pg.evaluate(_HTF_OHLC_JS, want)   # 純讀，same Playwright channel
                discovery[HTF_FRAG] = {"log": res.get("log"),
                                       "off1_ohlc": {str(c.get("interval")): c.get("off1_ohlc")
                                                     for c in (res.get("charts") or [])}}
                for ch in res.get("charts") or []:
                    key = HTF_IV_TO_KEY.get(str(ch.get("interval")))
                    closes = ch.get("closes")
                    if not key or not closes:
                        continue
                    rec = summarize(closes, sma_len=sma_len, band=band)
                    rec["bar_time"] = ch.get("off1_time")
                    # P2b Tier 1（add-only）：surface Daily/Weekly off1 high/low = PDH/PDL/PWH/PWL。
                    # off1_ohlc = [open, high, low, close]（index 1=high, 2=low）。h4 唔加；既有
                    # key（close/sma/direction/bars_loaded/sma_len/band/bar_time）一個都唔郁。
                    if key in ("d", "w"):
                        ohlc = ch.get("off1_ohlc")
                        if ohlc and len(ohlc) >= 4:
                            rec["high"] = ohlc[1]
                            rec["low"] = ohlc[2]
                    readings[key] = rec
    except Exception as e:                              # belt-and-braces：唔好 raise 出去
        discovery["_error"] = f"{type(e).__name__}: {e}"
    record = {
        "kind": "htf_closed_bar_off1", "cycle": out.name,
        "captured_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "discovery": discovery, "readings": readings,
        "complete": all(k in readings for k in ("h4", "d", "w")),
    }
    (out / "htf_closed.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _slug(url: str) -> str:
    """https://www.tradingview.com/chart/<slug>/ → <slug>（match tab 用）。"""
    if "/chart/" not in (url or ""):
        return ""
    return url.split("/chart/")[-1].strip("/").split("?")[0].split("#")[0]


def read_dxy_closed(bundle_dir) -> dict:
    """P2a（DXY modifier）— g7_DXY 純讀 closed-bar(off1) OHLC → DXY 方向（trade-agnostic
    BULL/BEAR/NEUTRAL）→ 寫 bundle/dxy_closed.json。純讀（零 setResolution/setSymbol/
    setChartType），mirror read_htf_closed；9333-only。CONFIRM/ADVERSE 喺 /analyze 配 trade
    方向先算（map_dxy_state），呢度只存方向。url 未填 → discovery 標明、唔 crash。"""
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    from playwright.sync_api import sync_playwright

    from analyze.htf_direction import summarize    # 共用 summarize（close/sma/direction/bars_loaded/...）

    cfg = load_asset()
    url = (cfg.get("dxy_read") or {}).get("url") or ""
    frag = _slug(url)
    knobs = cfg.get("dxy_direction") or {}
    sma_len = int(knobs.get("sma_len", 20))
    band = float(knobs.get("band", 0.001))
    want = sma_len + 2
    out = Path(bundle_dir)
    out.mkdir(parents=True, exist_ok=True)
    reading: dict = {}
    discovery: dict = {}
    if not frag:
        discovery["_error"] = "dxy_read.url 未填（config）——等 g7_DXY save 好再填 URL"
    else:
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
                pages = [pg for ctx in browser.contexts for pg in ctx.pages
                         if "tradingview.com/chart" in pg.url]
                pg = next((x for x in pages if frag in x.url), None)
                if pg is None:
                    discovery[frag] = {"error": "g7_DXY tab 搵唔到（先 --ensure 開 9333）"}
                elif not _await_charts_ready(pg):           # H1 readiness gate
                    discovery[frag] = {"error": "charts not ready (timeout)"}
                else:
                    res = pg.evaluate(_HTF_OHLC_JS, want)    # 共用純讀 JS；DXY 單 pane → chart[0]
                    charts = res.get("charts") or []
                    discovery[frag] = {
                        "log": res.get("log"),
                        "off1_ohlc": charts[0].get("off1_ohlc") if charts else None}
                    ch = charts[0] if charts else None
                    if ch and ch.get("closes"):
                        rec = summarize(ch["closes"], sma_len=sma_len, band=band)
                        rec["bar_time"] = ch.get("off1_time")
                        rec["interval"] = ch.get("interval")    # 應為 "15"（15m），real-run 核
                        rec["symbol"] = ch.get("symbol")        # log DXY ticker（唔 hard-assert）
                        reading = rec
        except Exception as e:
            discovery["_error"] = f"{type(e).__name__}: {e}"
    record = {
        "kind": "dxy_closed_bar_off1", "cycle": out.name,
        "captured_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "discovery": discovery, "reading": reading,
        "complete": bool(reading.get("direction")),
    }
    (out / "dxy_closed.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


# ── P2c（Tier 3a swing-pivot 取數，2026-06-20）─────────────────────────────────────
# swing OHLC history sources：frag → {interval: tf_key}（每 tab 只取要嘅 pane；其餘 pane 跳）。
OHLC_SOURCES = {
    "cpPWuLlN": {"5": "m5"},                          # g4：m5（跳 m1）
    "avpCVaw2": {"15": "m15"},                        # g5：m15（跳 m30）
    "pNqcbOmu": {"240": "h4", "1D": "d", "1W": "w"},  # g6：h4/d/w
}

# OHLC freshness contract（data-quality only；唔係交易 gate）。集中喺 producer，避免 CLI/tests
# 各自散落 magic numbers。h4/d/w 只報 close-time age，今階段唔設 live threshold、唔影響 overall。
OHLC_INTERVAL_SECONDS = {"m5": 5 * 60, "m15": 15 * 60,
                         "h4": 4 * 60 * 60, "d": 24 * 60 * 60,
                         "w": 7 * 24 * 60 * 60}
OHLC_LIVE_FRESHNESS_THRESHOLDS = {"m5": 10 * 60, "m15": 30 * 60}
OHLC_LIVE_REQUIRED_TFS = tuple(OHLC_LIVE_FRESHNESS_THRESHOLDS)

# 純讀 N 條 full OHLC（off1 起回溯、drop volume → len-5/6 一致）。獨立新 JS；read_htf_closed /
# _HTF_OHLC_JS 零行 diff。係 function expression（唔即時 invoke），page.evaluate(js, want) 傳 want。
_OHLC_HISTORY_JS = r"""(function(want){
  var api=window.TradingViewApi, out=[], n=api.chartsCount();
  function cwOf(ch){ return ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget); }
  for(var i=0;i<n;i++){
    var r={interval:null, symbol:null, bars:null, last:null};
    try{
      var ch=api.chart(i), ms=cwOf(ch).model().mainSeries(), b=ms.bars();
      r.interval=String(ms.interval());
      try{ var si=ms.symbolInfo&&ms.symbolInfo(); r.symbol=si?(si.pro_name||null):null; }catch(e){}
      var last=b.lastIndex(); r.last=last;
      var bars=[];
      for(var k=0;k<want;k++){ var idx=last-1-k; if(idx<0) break;   // off1=last-1，排除 forming
        var v=b.valueAt(idx); if(!v) break;
        bars.push([v[0],v[1],v[2],v[3],v[4]]); }                    // [t,O,H,L,C]（drop volume）
      r.bars=bars;                                                  // newest-closed-first（off1 first）
    }catch(e){ r.err=String(e).slice(0,90); }
    out.push(r);
  }
  return {charts:out};
})"""


def _utc_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _valid_epoch(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) and value > 0 else None


def _tf_freshness(tf: str, bars: list, captured_epoch: float) -> dict:
    """Return one-TF close-time freshness. Invalid chronology fails closed.

    `bars[*][0]` is TradingView's raw bar *open* timestamp. Freshness is always measured from
    `latest open + interval`, never from the raw open timestamp itself.
    """
    interval = OHLC_INTERVAL_SECONDS[tf]
    threshold = OHLC_LIVE_FRESHNESS_THRESHOLDS.get(tf)
    base = {
        "latest_raw_bar_timestamp": None,
        "latest_raw_bar_time": None,
        "interval_seconds": interval,
        "latest_confirmed_bar_close_time": None,
        "age_since_close_seconds": None,
        "freshness_threshold_seconds": threshold,
        "enforced_in_overall": tf in OHLC_LIVE_REQUIRED_TFS,
        "fresh": False,
        "reason": None,
    }
    if not bars:
        base["reason"] = "missing_bars"
        return base

    timestamps = []
    for bar in bars:
        if not isinstance(bar, (list, tuple)) or not bar:
            base["reason"] = "missing_timestamp"
            return base
        ts = _valid_epoch(bar[0])
        if ts is None:
            base["reason"] = "invalid_timestamp"
            return base
        timestamps.append(ts)

    latest_raw = timestamps[-1]
    close_epoch = latest_raw + interval
    age = captured_epoch - close_epoch
    base.update({
        "latest_raw_bar_timestamp": int(latest_raw) if latest_raw.is_integer() else latest_raw,
        "latest_raw_bar_time": _utc_iso(latest_raw),
        "latest_confirmed_bar_close_time": _utc_iso(close_epoch),
        "age_since_close_seconds": round(age, 3),
    })
    if len(timestamps) != len(set(timestamps)):
        base["reason"] = "duplicate_timestamp"
        return base
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        base["reason"] = "non_monotonic_timestamp"
        return base
    if age < 0:
        base["reason"] = "confirmed_close_time_in_future"
        return base
    if threshold is None:
        # No threshold means we cannot certify freshness. Keep the field boolean/fail-closed;
        # `enforced_in_overall=false` makes clear this report-only result cannot fail m5/m15 live.
        base["reason"] = "report_only_no_live_threshold"
        return base
    if age <= threshold:
        base.update({"fresh": True, "reason": "within_threshold"})
    else:
        base["reason"] = "age_exceeds_threshold"
    return base


def build_ohlc_freshness(bars: dict, *, captured_at: datetime | None = None) -> dict:
    """Build additive OHLC freshness metadata; overall enforces m5/m15 only."""
    captured_at = captured_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    captured_at = captured_at.astimezone(timezone.utc)
    captured_epoch = captured_at.timestamp()
    by_tf = {tf: _tf_freshness(tf, bars.get(tf) or [], captured_epoch)
             for tf in OHLC_INTERVAL_SECONDS}
    stale = [tf for tf in OHLC_LIVE_REQUIRED_TFS if by_tf[tf]["fresh"] is not True]
    fresh = not stale
    captured_iso = captured_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "captured_at": captured_iso,
        "required_timeframes": list(OHLC_LIVE_REQUIRED_TFS),
        "by_tf": by_tf,
        "overall": {
            "fresh": fresh,
            "status": "fresh" if fresh else "stale",
            "stale_timeframes": stale,
            "reason": ("required_timeframes_fresh" if fresh else
                       f"required_timeframes_not_fresh: {','.join(stale)}"),
        },
    }


def _write_ohlc_history(bundle_dir, *, bars: dict, discovery: dict, n_bars: int,
                        min_bars: int, captured_at: datetime | None = None) -> dict:
    """Write the replayable record. `complete` remains count/schema-only by contract."""
    captured_at = captured_at or datetime.now(timezone.utc)
    freshness = build_ohlc_freshness(bars, captured_at=captured_at)
    captured_iso = freshness["captured_at"]
    out = Path(bundle_dir)
    out.mkdir(parents=True, exist_ok=True)
    record = {
        "kind": "ohlc_history", "cycle": out.name,
        "captured_utc": captured_iso,               # backward-compatible existing field
        "captured_at": captured_iso,                # explicit freshness contract field
        "history_bars": n_bars,
        "bars": bars,
        "count": {k: len(v) for k, v in bars.items()},
        # IMPORTANT: freshness must never be folded into `complete`.
        "complete": all(len(v) >= min_bars for v in bars.values()) and bool(bars),
        "freshness": freshness,
        "discovery": discovery,
    }
    (out / "ohlc_history.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _freshness_failure_lines(freshness: dict) -> list[str]:
    lines = []
    by_tf = freshness.get("by_tf") or {}
    for tf in (freshness.get("overall") or {}).get("stale_timeframes") or []:
        item = by_tf.get(tf) or {}
        lines.append(
            f"{tf}: close_time={item.get('latest_confirmed_bar_close_time')} "
            f"age={item.get('age_since_close_seconds')}s "
            f"threshold={item.get('freshness_threshold_seconds')}s "
            f"reason={item.get('reason')}")
    return lines


def read_ohlc_history(bundle_dir) -> dict:
    """P2c — 純讀 g4(m5)/g5(m15)/g6(h4/d/w) 每 TF N 條 closed-bar OHLC → 寫 bundle/
    ohlc_history.json（chronological，bars[tf][-1]=off1）。一條 Playwright 連線讀 3 tab，純讀
    （零 setResolution/setSymbol/setChartType）。read_htf_closed / htf_closed.json 零郁。swing
    pivot 由 analyze.swing_pivots analyze-time 算（呢度只存 raw history，frozen/replayable）。

    guard (i) interval fail-loud：iv_map 每個 expected interval 都要配到 pane，否則 raise（唔靜靜
    drop TF；m1/m30 唔喺 iv_map = 有意跳過，唔當 error）。guard (ii)：每 pane symbol assert XAUUSD。"""
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    from playwright.sync_api import sync_playwright

    cfg = load_asset()
    swing = cfg.get("swing") or {}
    n_bars = int(swing.get("history_bars", 300))
    min_bars = 2 * int(swing.get("k", 2)) + 1
    out = Path(bundle_dir)
    out.mkdir(parents=True, exist_ok=True)
    bars: dict = {}
    discovery: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "tradingview.com/chart" in pg.url]
        for frag, iv_map in OHLC_SOURCES.items():
            pg = next((x for x in pages if frag in x.url), None)
            if pg is None:
                raise RuntimeError(f"{frag} tab 搵唔到（先 --ensure 開 9333）")   # fail-loud
            if not _await_charts_ready(pg):                       # H1 readiness gate
                raise RuntimeError(f"{frag} charts not ready (timeout)")
            res = pg.evaluate(_OHLC_HISTORY_JS, n_bars)
            seen_iv, log = set(), []
            for ch in res.get("charts") or []:
                iv = str(ch.get("interval"))
                if iv not in iv_map:                              # 有意跳過 m1/m30
                    continue
                if ch.get("symbol") not in (None, EXPECT_SYMBOL):  # guard (ii)
                    raise RuntimeError(
                        f"{frag} iv{iv} symbol={ch.get('symbol')} != {EXPECT_SYMBOL}")
                chrono = list(reversed(ch.get("bars") or []))     # newest-first → chronological
                bars[iv_map[iv]] = chrono                         # bars[tf][-1] = off1
                seen_iv.add(iv)
                log.append(f"{iv_map[iv]} iv{iv} got={len(chrono)}")
            missing_iv = set(iv_map) - seen_iv                    # guard (i)：expected interval 配唔到
            if missing_iv:
                raise RuntimeError(
                    f"{frag}: expected interval(s) {sorted(missing_iv)} 配唔到 pane（唔靜靜 drop TF）")
            discovery[frag] = {"log": log}
    return _write_ohlc_history(out, bars=bars, discovery=discovery, n_bars=n_bars,
                               min_bars=min_bars)


def read_price_9333() -> float | None:
    """備路現價（read-only）：連 9333 g4 tab，**reuse `_HTF_OHLC_JS`** 讀 m5 **off1 closed-bar** close。

    用 off1（唔用 forming bar）= 同全系統 closed-bar 紀律一致（殺 live jitter；MACD/HTF/DXY 都 off1）。
    invalidation_watch daemon 用做價源。9333 down / g4 tab 缺 / 讀唔到 → **None**（caller skip，唔 crash
    唔 mutate）。**9222 零掂**（PORT 鎖死 + assert）。零 setResolution/setSymbol/setChartType（純讀）。
    """
    assert PORT != 9222, "refuse: 9333 helper must never target 9222"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
            pages = [pg for ctx in browser.contexts for pg in ctx.pages
                     if "tradingview.com/chart" in pg.url]
            pg = next((x for x in pages if "cpPWuLlN" in x.url), None)   # g4 5m+1m
            if pg is None:
                return None
            res = pg.evaluate(_HTF_OHLC_JS, 1)                          # want=1 支 off1
            charts = res.get("charts") or []
            for ch in charts:                                           # 優先 m5 pane
                if str(ch.get("interval")) == "5" and ch.get("closes"):
                    return float(ch["closes"][0])
            for ch in charts:                                           # fallback：任何 pane
                if ch.get("closes"):
                    return float(ch["closes"][0])
            return None
    except Exception:
        return None


def main() -> int:
    force_utf8_stdout()
    if "--health" in sys.argv:                     # 三態：down / up_no_target / healthy
        print(json.dumps(health_state(), ensure_ascii=False, indent=2))
        return 0
    if "--launch" in sys.argv:                     # 淨 idempotent 冷啟動（唔 correct/verify）
        print(json.dumps(ensure_up(), ensure_ascii=False, indent=2))
        return 0
    if "--verify" in sys.argv:                     # 9333 已起時淨驗，唔 launch
        print(json.dumps(_verify(), ensure_ascii=False, indent=2))
        return 0
    if "--correct" in sys.argv:                    # 淨跑 Fork B setter（debug）
        print(json.dumps(_correct_chart_type(), ensure_ascii=False, indent=2))
        return 0
    if "--shot" in sys.argv:                       # 9333 ad-hoc 截圖（hygiene 前置）
        print(json.dumps(shoot(), ensure_ascii=False, indent=2))
        return 0
    if "--htf" in sys.argv:                        # P1：g6_HTF 純讀 closed-bar → bundle/htf_closed.json
        i = sys.argv.index("--htf")
        bundle = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if not bundle:
            print(json.dumps({"ok": False, "error": "--htf 要 <bundle_dir>"}, ensure_ascii=False))
            return 1
        rec = read_htf_closed(bundle)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0 if rec.get("complete") else 1
    if "--dxy" in sys.argv:                        # P2a：g7_DXY 純讀 closed-bar → bundle/dxy_closed.json
        i = sys.argv.index("--dxy")
        bundle = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if not bundle:
            print(json.dumps({"ok": False, "error": "--dxy 要 <bundle_dir>"}, ensure_ascii=False))
            return 1
        rec = read_dxy_closed(bundle)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0 if rec.get("complete") else 1
    if "--ohlc" in sys.argv:                       # P2c：g4/g5/g6 純讀 N 條 OHLC → bundle/ohlc_history.json
        i = sys.argv.index("--ohlc")
        bundle = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if not bundle:
            print(json.dumps({"ok": False, "error": "--ohlc 要 <bundle_dir>"}, ensure_ascii=False))
            return 1
        rec = read_ohlc_history(bundle)            # bars 巨大 → 只印摘要
        print(json.dumps({"kind": rec["kind"], "cycle": rec["cycle"],
                          "history_bars": rec["history_bars"], "count": rec["count"],
                          "complete": rec["complete"],
                          "freshness": rec["freshness"]}, ensure_ascii=False, indent=2))
        if not rec.get("complete"):
            return 1
        if not rec["freshness"]["overall"]["fresh"]:
            details = " | ".join(_freshness_failure_lines(rec["freshness"]))
            if "--require-fresh" in sys.argv:
                print("OHLC freshness gate failed: " + details, file=sys.stderr)
                return 2
            print("OHLC freshness warning (non-strict; bundle retained): " + details,
                  file=sys.stderr)
        return 0
    if "--require-fresh" in sys.argv:
        print(json.dumps({"ok": False,
                          "error": "--require-fresh 必須配合 --ohlc <bundle_dir>"},
                         ensure_ascii=False))
        return 1
    r = ensure()                                   # default = --ensure
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
