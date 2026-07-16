"""Read-only endpoint discovery and pinned single-tab Playwright CDP adapter."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import AbstractContextManager
from datetime import datetime, timezone

from .errors import Session3Error
from .preflight import ChartState, EndpointInfo, TargetInfo
from .profile import CaptureProfile, normalized_chart_url

TF_TO_TV = {"5s": "5S", "1m": "1", "5m": "5", "15m": "15", "30m": "30"}
TV_TO_TF = {value: key for key, value in TF_TO_TV.items()}

_STATE_JS = r"""(function(){
  var result={page_ready:document.readyState==='complete', chart_count:0, symbol:null,
    interval:null, last_bar_epoch:null, can_switch:false, header_text:'', data_status:'unknown'};
  try {
    var api=window.TradingViewApi; result.chart_count=api.chartsCount();
    if(result.chart_count!==1) return result;
    var ch=api.chart(0), cw=ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget);
    var ms=cw.model().mainSeries(), si=ms.symbolInfo&&ms.symbolInfo(), bars=ms.bars(), last=bars.lastIndex();
    result.symbol=si?(si.pro_name||si.full_name||null):null;
    result.interval=String(ms.interval()); result.can_switch=typeof ch.setResolution==='function';
    if(last>=0){ var v=bars.valueAt(last); result.last_bar_epoch=v?v[0]:null; result.data_status='streaming'; }
    var legend=document.querySelector('[data-name="legend-source-title"], [data-name="legend-source-description"]');
    result.header_text=legend?(legend.innerText||legend.textContent||''):'';
  } catch(e){ result.error=String(e).slice(0,180); }
  return result;
})()"""

_SWITCH_JS = r"""(function(value){
  var api=window.TradingViewApi;
  if(!api || api.chartsCount()!==1) return {ok:false,error:'single chart required'};
  var chart=api.chart(0);
  if(typeof chart.setResolution!=='function') return {ok:false,error:'setResolution unavailable'};
  chart.setResolution(value); return {ok:true};
})"""


def _http_json(port: int, path: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


class WindowsCdpProbe:
    """Proves listener binding/process identity, then reads standard CDP metadata."""

    def inspect(self, profile: CaptureProfile) -> tuple[EndpointInfo, list[TargetInfo]]:
        profile.validate()
        if os.name != "nt":
            raise Session3Error("UNSAFE_BINDING", "listener/process attestation is implemented for Windows only")
        script = (
            "$r=Get-NetTCPConnection -State Listen -LocalPort 4999 -ErrorAction SilentlyContinue;"
            "if($r){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$r[0].OwningProcess);"
            "[pscustomobject]@{addresses=@($r.LocalAddress);pids=@($r.OwningProcess);"
            "pid=$r[0].OwningProcess;name=$p.Name;command=$p.CommandLine}|ConvertTo-Json -Compress}"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Session3Error("MCP_UNAVAILABLE", "listener/process attestation timed out") from exc
        raw = completed.stdout.strip()
        if not raw:
            return EndpointInfo(False, "127.0.0.1", 4999), []
        try:
            listener = json.loads(raw)
        except ValueError as exc:
            raise Session3Error("MCP_UNAVAILABLE", "could not parse local listener attestation") from exc
        pids = {int(value) for value in listener.get("pids", [])}
        if len(pids) != 1:
            raise Session3Error("WRONG_PROCESS", f"port 4999 has multiple listener owners: {sorted(pids)}")
        version = _http_json(4999, "/json/version")
        targets_raw = _http_json(4999, "/json/list")
        endpoint = EndpointInfo(
            available=isinstance(version, dict) and isinstance(targets_raw, list),
            host="127.0.0.1",
            port=4999,
            local_addresses=tuple(sorted(set(listener.get("addresses") or []))),
            pid=int(listener["pid"]),
            process_name=listener.get("name"),
            command_line=listener.get("command") or "",
            browser=(version or {}).get("Browser", ""),
            protocol_version=(version or {}).get("Protocol-Version", ""),
        )
        targets = [
            TargetInfo(str(item.get("id", "")), str(item.get("type", "")),
                       str(item.get("url", "")), str(item.get("title", "")))
            for item in (targets_raw or [])
        ]
        return endpoint, targets


class PlaywrightPinnedDriver(AbstractContextManager):
    """Uses one exact URL after the HTTP target-ID pin has already been verified."""

    def __init__(self, profile: CaptureProfile):
        self.profile = profile
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp("http://127.0.0.1:4999")
            pages = [page for context in self._browser.contexts for page in context.pages
                     if _normalizable_equal(page.url, self.profile.expected_chart_url)]
            if len(pages) == 0:
                raise Session3Error("TAB_NOT_FOUND", "approved pinned chart URL is absent from Playwright contexts")
            if len(pages) != 1:
                raise Session3Error("TAB_AMBIGUOUS", "multiple Playwright pages have the approved chart URL")
            self._page = pages[0]
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc, traceback):
        # Do not call Browser.close() on a CDP-attached persistent profile: that
        # can terminate the operator's isolated browser instead of only detaching.
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._browser = self._playwright = self._page = None
        return False

    def inspect(self) -> ChartState:
        if self._page is None:
            raise Session3Error("MCP_UNAVAILABLE", "driver is not connected")
        raw = self._page.evaluate(_STATE_JS)
        if raw.get("error"):
            raise Session3Error("CHART_NOT_READY", raw["error"])
        body = self._page.inner_text("body", timeout=2000)[:20000]
        lowered = body.lower()
        auth = not any(marker in lowered for marker in (
            "to log in to see it", "sign in to tradingview", "open this chart layout for you",
        ))
        modal = any(marker in lowered for marker in ("connection lost", "reconnecting", "session expired"))
        structured = raw.get("symbol") or ""
        feed, _, symbol = structured.partition(":")
        header_tokens = set(re.findall(r"[A-Z0-9_]+", (raw.get("header_text") or "").upper()))
        observed_tf = TV_TO_TF.get(str(raw.get("interval")), "")
        epoch = raw.get("last_bar_epoch")
        if not isinstance(epoch, (int, float)):
            raise Session3Error("CHART_NOT_READY", "structured last bar timestamp is unavailable")
        last_bar = datetime.fromtimestamp(epoch, tz=timezone.utc)
        layout_id = normalized_chart_url(self._page.url).rstrip("/").split("/")[-1]
        tf_header_tokens = {
            "5s": {"5S", "S5"}, "1m": {"1M", "M1"}, "5m": {"5M", "M5"},
            "15m": {"15M", "M15"}, "30m": {"30M", "M30"},
        }.get(observed_tf, set())
        return ChartState(
            page_ready=raw.get("page_ready") is True,
            authenticated=auth,
            url=self._page.url,
            layout_id=layout_id,
            chart_count=int(raw.get("chart_count") or 0),
            structured_symbol=structured,
            canonical_symbol=symbol,
            header_symbol=self.profile.symbol if self.profile.symbol in header_tokens else "",
            broker_feed=feed,
            header_feed=self.profile.broker_feed if self.profile.broker_feed in header_tokens else "",
            timeframe=observed_tf,
            header_timeframe=observed_tf if header_tokens.intersection(tf_header_tokens) else "",
            available_timeframes=self.profile.required_timeframes if raw.get("can_switch") else (),
            data_status=str(raw.get("data_status")),
            last_bar_at=last_bar,
            last_update_at=last_bar,
            modal_blocking=modal,
            disconnected="connection lost" in lowered,
            loading="loading chart" in lowered,
        )

    def switch_and_wait(self, timeframe: str, *, timeout_seconds: float = 15.0) -> ChartState:
        try:
            tv_value = TF_TO_TV[timeframe]
        except KeyError as exc:
            raise Session3Error("MISSING_TIMEFRAME", f"unsupported timeframe {timeframe}") from exc
        result = self._page.evaluate(_SWITCH_JS, tv_value)
        if not result.get("ok"):
            raise Session3Error("MISSING_TIMEFRAME", result.get("error", "timeframe switch failed"))
        deadline = time.monotonic() + timeout_seconds
        stable = 0
        last_state = None
        while time.monotonic() < deadline:
            last_state = self.inspect()
            if last_state.timeframe == timeframe and last_state.data_status == "streaming":
                stable += 1
                if stable >= 2:
                    return last_state
            else:
                stable = 0
            self._page.wait_for_timeout(250)
        observed = last_state.timeframe if last_state else None
        raise Session3Error("CHART_NOT_READY", f"timeframe {timeframe} never stabilized; observed={observed!r}")

    def screenshot(self) -> bytes:
        try:
            return self._page.screenshot(type="png")
        except Exception as exc:
            raise Session3Error("SCREENSHOT_FAILURE", f"{type(exc).__name__}: {exc}") from exc


def _normalizable_equal(left: str, right: str) -> bool:
    try:
        return normalized_chart_url(left) == normalized_chart_url(right)
    except Session3Error:
        return False
