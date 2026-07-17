"""Read-only endpoint discovery and pinned single-tab Playwright CDP adapter."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from .errors import Session3Error
from .preflight import ChartState, EndpointInfo, TargetInfo
from .profile import CaptureProfile, normalized_chart_url

TF_TO_TV = {"5s": "5S", "1m": "1", "5m": "5", "15m": "15", "30m": "30"}
TV_TO_TF = {value: key for key, value in TF_TO_TV.items()}

_HEADER_SCOPES = {"active_chart_header", "active_chart_legend"}


def normalize_header_symbol(raw: str) -> str:
    """Normalize only a complete, visible symbol identity; labels like ``Gold`` fail closed."""
    value = " ".join(str(raw or "").upper().split())
    if "GOLD SPOT" in value and re.search(r"U\.?\s*S\.?\s*DOLLAR", value):
        return "XAUUSD"
    match = re.search(r"(?:^|[^A-Z0-9])([A-Z]{3}USD)(?:$|[^A-Z0-9])", value)
    return match.group(1) if match else ""


def normalize_header_feed(raw: str) -> str:
    """Normalize a complete venue identity without inferring one from symbol data."""
    value = " ".join(str(raw or "").upper().split())
    if re.search(r"\bIC\s*MARKETS\b", value) or "ICMARKETS" in value:
        return "ICMARKETS"
    venue = re.search(r"(?:^|[^A-Z0-9_])([A-Z][A-Z0-9_]{2,}):[A-Z0-9_]+", value)
    if venue:
        return venue.group(1)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value) else ""


def normalize_header_timeframe(raw: str) -> str:
    """Normalize the five approved TradingView display forms, including legacy combined labels."""
    value = " ".join(str(raw or "").upper().split())
    exact = {
        "5S": "5s", "S5": "5s", "5 SEC": "5s", "5 SECONDS": "5s",
        "1": "1m", "1M": "1m", "M1": "1m", "1 MIN": "1m", "1 MINUTE": "1m",
        "5": "5m", "5M": "5m", "M5": "5m", "5 MIN": "5m", "5 MINUTES": "5m",
        "15": "15m", "15M": "15m", "M15": "15m", "15 MIN": "15m", "15 MINUTES": "15m",
        "30": "30m", "30M": "30m", "M30": "30m", "30 MIN": "30m", "30 MINUTES": "30m",
    }
    if value in exact:
        return exact[value]
    patterns = (
        (r"(?<![A-Z0-9])5\s*(?:S|SEC(?:OND)?S?)(?![A-Z0-9])", "5s"),
        (r"(?<![A-Z0-9])30\s*(?:M|MIN(?:UTE)?S?)?(?![A-Z0-9])", "30m"),
        (r"(?<![A-Z0-9])15\s*(?:M|MIN(?:UTE)?S?)?(?![A-Z0-9])", "15m"),
        (r"(?<![A-Z0-9])5\s*(?:M|MIN(?:UTE)?S?)?(?![A-Z0-9])", "5m"),
        (r"(?<![A-Z0-9])1\s*(?:M|MIN(?:UTE)?S?)?(?![A-Z0-9])", "1m"),
    )
    matches = {timeframe for pattern, timeframe in patterns if re.search(pattern, value)}
    return next(iter(matches)) if len(matches) == 1 else ""


def resolve_header_identity(evidence: dict | None) -> tuple[str, str, str, dict]:
    """Resolve an independent active-chart header channel and reject ambiguous or unrelated DOM."""
    evidence = evidence if isinstance(evidence, dict) else {}
    declared_status = evidence.get("status")
    chart_region_count = evidence.get("chart_region_count")
    audit = {
        "declared_status": declared_status or "MISSING",
        "strategy": evidence.get("strategy") or "NONE",
        "chart_region_count": chart_region_count,
        "accepted_candidate_count": 0,
        "resolution_status": "MISSING",
    }
    if declared_status != "OK" or chart_region_count != 1:
        audit["resolution_status"] = "AMBIGUOUS" if declared_status == "AMBIGUOUS" or (
            isinstance(chart_region_count, int) and chart_region_count > 1
        ) else "MISSING"
        return "", "", "", audit

    candidates = [
        item for item in evidence.get("candidates", [])
        if isinstance(item, dict) and item.get("visible") is True and item.get("scope") in _HEADER_SCOPES
    ]
    audit["accepted_candidate_count"] = len(candidates)

    def values(kind: str, normalizer) -> set[str]:
        normalized = set()
        for item in candidates:
            if item.get("kind") not in {kind, "combined"}:
                continue
            value = normalizer(item.get("raw", ""))
            if value:
                normalized.add(value)
        return normalized

    symbols = values("symbol", normalize_header_symbol)
    feeds = values("feed", normalize_header_feed)
    timeframes = values("timeframe", normalize_header_timeframe)
    audit["resolved_value_counts"] = {
        "symbol": len(symbols), "feed": len(feeds), "timeframe": len(timeframes),
    }
    if any(len(items) > 1 for items in (symbols, feeds, timeframes)):
        audit["resolution_status"] = "AMBIGUOUS"
    elif all(len(items) == 1 for items in (symbols, feeds, timeframes)):
        audit["resolution_status"] = "OK"
    symbol = next(iter(symbols)) if len(symbols) == 1 else ""
    feed = next(iter(feeds)) if len(feeds) == 1 else ""
    timeframe = next(iter(timeframes)) if len(timeframes) == 1 else ""
    return symbol, feed, timeframe, audit


@dataclass(frozen=True)
class TransitionConfig:
    timeout_seconds: float = 15.0
    poll_interval_seconds: float = 0.25
    required_stable_samples: int = 2

    def __post_init__(self):
        if self.timeout_seconds <= 0 or self.poll_interval_seconds <= 0:
            raise ValueError("transition timeout and poll interval must be positive")
        if self.required_stable_samples != 2:
            raise ValueError("Session 3 requires exactly two stable transition samples")


DEFAULT_TRANSITION_CONFIG = TransitionConfig()
_TRANSIENT_SWITCH_ERRORS = {"CHART_NOT_READY", "PAGE_NOT_READY", "STALE_CHART", "WRONG_TIMEFRAME"}


def _hard_transition_identity(profile: CaptureProfile, pin, state: ChartState) -> None:
    if state.target_match_count > 1:
        raise Session3Error("TAB_AMBIGUOUS", "multiple matching TradingView targets appeared during transition")
    if state.target_match_count != 1:
        raise Session3Error("TAB_NOT_FOUND", "the pinned TradingView target disappeared during transition")
    if state.target_id != pin.target_id:
        raise Session3Error("WRONG_TAB", f"target changed during transition: {state.target_id!r}")
    if not state.authenticated:
        raise Session3Error("AUTH_UNUSABLE", "authenticated chart state changed during transition")
    if _normalizable_equal(state.url, profile.expected_chart_url) is not True:
        raise Session3Error("WRONG_TAB", "chart URL changed during transition")
    if state.layout_id != profile.expected_layout_id:
        raise Session3Error("WRONG_LAYOUT", f"layout changed during transition: {state.layout_id!r}")
    if state.chart_count != profile.expected_chart_count:
        raise Session3Error("WRONG_LAYOUT", f"chart count changed during transition: {state.chart_count}")
    if state.structured_symbol not in profile.aliases or state.canonical_symbol != profile.symbol:
        raise Session3Error("WRONG_SYMBOL", f"structured symbol changed: {state.structured_symbol!r}")
    header_resolution = (state.header_identity_evidence or {}).get("resolution", {})
    if header_resolution.get("resolution_status") == "AMBIGUOUS":
        raise Session3Error("WRONG_SYMBOL", "independent header identity became ambiguous")
    if state.header_symbol != profile.symbol:
        raise Session3Error("WRONG_SYMBOL", f"independent header symbol changed: {state.header_symbol!r}")
    if state.broker_feed != profile.broker_feed or state.header_feed != profile.broker_feed:
        raise Session3Error(
            "WRONG_FEED", f"structured/header feed changed: {state.broker_feed!r}/{state.header_feed!r}"
        )
    if state.modal_blocking:
        raise Session3Error("MODAL_BLOCKING", "a blocking modal appeared during transition")


def _transition_ready(state: ChartState, requested: str, observed_at: datetime) -> tuple[bool, str]:
    if not state.page_ready:
        return False, "PAGE_NOT_READY"
    if state.timeframe != requested or state.header_timeframe != requested:
        return False, "INTERVAL_MISMATCH"
    if state.timeframe != state.header_timeframe:
        return False, "CHANNEL_DISAGREEMENT"
    if state.last_bar_at is None or state.last_update_at is None:
        return False, "LAST_BAR_MISSING"
    if state.data_status != "streaming" or state.loading or state.disconnected:
        return False, "STREAM_NOT_STABLE"
    bar_at = state.last_bar_at.astimezone(timezone.utc)
    update_at = state.last_update_at.astimezone(timezone.utc)
    observed_at = observed_at.astimezone(timezone.utc)
    if update_at < bar_at or update_at > observed_at or bar_at > observed_at:
        return False, "CHRONOLOGY_NOT_STABLE"
    return True, "STABLE"


def wait_for_timeframe_stability(
    profile: CaptureProfile,
    pin,
    requested_timeframe: str,
    previous_timeframe: str,
    observe: Callable[[], ChartState],
    *,
    config: TransitionConfig = DEFAULT_TRANSITION_CONFIG,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    wall_clock: Callable[[], datetime] | None = None,
) -> ChartState:
    """Wait for two bounded structured/header observations without retrying the switch itself."""
    wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
    started = monotonic()
    deadline = started + config.timeout_seconds
    max_observations = math.ceil(config.timeout_seconds / config.poll_interval_seconds) + 1
    stable_samples = 0
    observation_count = 0
    last_state = None
    last_reason = "NO_OBSERVATION"

    def timeout_error() -> Session3Error:
        elapsed = max(0.0, monotonic() - started)
        detail = {
            "requested_timeframe": requested_timeframe,
            "previous_timeframe": previous_timeframe,
            "latest_structured_interval": last_state.timeframe if last_state else "",
            "latest_header_interval": last_state.header_timeframe if last_state else "",
            "stable_sample_count": stable_samples,
            "last_bar_present": bool(last_state and last_state.last_bar_at is not None),
            "elapsed_seconds": round(elapsed, 3),
            "observation_count": observation_count,
            "last_transition_state": last_reason,
        }
        return Session3Error("TIMEFRAME_STABILIZATION_TIMEOUT", json.dumps(detail, sort_keys=True))

    while observation_count < max_observations and monotonic() < deadline:
        observation_count += 1
        try:
            state = observe()
        except Session3Error as exc:
            if exc.code not in _TRANSIENT_SWITCH_ERRORS:
                raise
            stable_samples = 0
            last_reason = exc.code
        else:
            last_state = state
            _hard_transition_identity(profile, pin, state)
            ready, last_reason = _transition_ready(state, requested_timeframe, wall_clock())
            stable_samples = stable_samples + 1 if ready else 0
            if stable_samples >= config.required_stable_samples:
                evidence = {
                    "status": "STABLE",
                    "requested_timeframe": requested_timeframe,
                    "previous_timeframe": previous_timeframe,
                    "structured_timeframe": state.timeframe,
                    "header_timeframe": state.header_timeframe,
                    "stable_sample_count": stable_samples,
                    "required_stable_samples": config.required_stable_samples,
                    "observation_count": observation_count,
                    "elapsed_seconds": round(max(0.0, monotonic() - started), 3),
                    "last_bar_present": True,
                    "target_id": state.target_id,
                }
                return replace(state, transition_evidence=evidence)
        remaining = deadline - monotonic()
        if remaining <= 0 or observation_count >= max_observations:
            break
        sleep(min(config.poll_interval_seconds, remaining))
    raise timeout_error()

_STATE_JS = r"""(function(){
  function visible(node){
    if(!node || !node.isConnected || node.getClientRects().length===0) return false;
    var style=window.getComputedStyle(node);
    return style.visibility!=='hidden' && style.display!=='none';
  }
  function text(node){ return ((node && (node.innerText||node.textContent))||'').trim(); }
  function candidate(kind, channel, scope, node){
    return {kind:kind, channel:channel, scope:scope, raw:text(node), visible:visible(node)};
  }
  function inspectHeader(){
    var regions=Array.from(document.querySelectorAll('[role="region"][aria-label^="Chart #"]')).filter(visible);
    var evidence={status:'MISSING', strategy:'NONE', chart_region_count:regions.length,
      old_selector_visible_matches:0, candidates:[], supplementary:[]};
    if(regions.length!==1){ evidence.status=regions.length>1?'AMBIGUOUS':'MISSING'; return evidence; }
    var region=regions[0];
    var symbols=Array.from(region.querySelectorAll('button[aria-label="Change symbol"]')).filter(visible);
    var intervals=Array.from(region.querySelectorAll('button[aria-label="Change interval"]')).filter(visible);
    symbols.forEach(function(node){ evidence.candidates.push(candidate('symbol','accessible_header_controls','active_chart_header',node)); });
    intervals.forEach(function(node){ evidence.candidates.push(candidate('timeframe','accessible_header_controls','active_chart_header',node)); });
    var feeds=[];
    if(intervals.length===1){
      var intervalWrap=intervals[0].closest('[title="Change interval"]');
      var group=intervalWrap && intervalWrap.parentElement;
      if(group){
        var children=Array.from(group.children), index=children.indexOf(intervalWrap);
        feeds=children.slice(index+1).filter(function(node){ return visible(node) && text(node); });
      }
    }
    feeds.forEach(function(node){ evidence.candidates.push(candidate('feed','accessible_header_controls','active_chart_header',node)); });
    Array.from(region.querySelectorAll('canvas[aria-label^="Chart for "]')).filter(visible).forEach(function(node){
      evidence.supplementary.push({kind:'canvas_label', channel:'accessible_canvas_label',
        scope:'active_chart_canvas', raw:node.getAttribute('aria-label')||'', visible:true});
    });
    if(symbols.length || intervals.length){
      evidence.strategy='ACCESSIBLE_HEADER_CONTROLS';
      evidence.status=(symbols.length===1 && intervals.length===1 && feeds.length===1)?'OK':
        ((symbols.length>1 || intervals.length>1 || feeds.length>1)?'AMBIGUOUS':'MISSING');
      return evidence;
    }
    var old=Array.from(region.querySelectorAll('[data-name="legend-source-title"], [data-name="legend-source-description"]')).filter(visible);
    evidence.old_selector_visible_matches=old.length;
    old.forEach(function(node){ evidence.candidates.push(candidate('combined','legacy_data_name','active_chart_legend',node)); });
    evidence.strategy=old.length?'LEGACY_DATA_NAME':'NONE';
    evidence.status=old.length===1?'OK':(old.length>1?'AMBIGUOUS':'MISSING');
    return evidence;
  }
  var result={page_ready:document.readyState==='complete', chart_count:0, symbol:null,
    interval:null, last_bar_epoch:null, can_switch:false, data_status:'unknown',
    header_identity:inspectHeader()};
  try {
    var api=window.TradingViewApi; result.chart_count=api.chartsCount();
    if(result.chart_count!==1) return result;
    var ch=api.chart(0), cw=ch._chartWidget||(typeof ch.chartWidget==='function'?ch.chartWidget():ch.chartWidget);
    var ms=cw.model().mainSeries(), si=ms.symbolInfo&&ms.symbolInfo(), bars=ms.bars(), last=bars.lastIndex();
    result.symbol=si?(si.pro_name||si.full_name||null):null;
    result.interval=String(ms.interval()); result.can_switch=typeof ch.setResolution==='function';
    if(last>=0){ var v=bars.valueAt(last); result.last_bar_epoch=v?v[0]:null; result.data_status='streaming'; }
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
        profile.require_real_browser_activation()
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

    def __init__(self, profile: CaptureProfile, pin, *,
                 transition_config: TransitionConfig = DEFAULT_TRANSITION_CONFIG,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] | None = None,
                 wall_clock: Callable[[], datetime] | None = None):
        self.profile = profile
        self.pin = pin
        self.transition_config = transition_config
        self._monotonic = monotonic
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._playwright = None
        self._browser = None
        self._page = None
        self._last_observed_timeframe = ""

    def __enter__(self):
        self.profile.require_real_browser_activation()
        if (self.pin.chart_url != self.profile.expected_chart_url
                or self.pin.layout_id != self.profile.expected_layout_id):
            raise Session3Error("WRONG_TAB", "driver pin differs from the approved profile")
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
        observed_tf = TV_TO_TF.get(str(raw.get("interval")), "")
        header_symbol, header_feed, header_timeframe, header_audit = resolve_header_identity(
            raw.get("header_identity")
        )
        epoch = raw.get("last_bar_epoch")
        last_bar = datetime.fromtimestamp(epoch, tz=timezone.utc) if isinstance(epoch, (int, float)) else None
        layout_id = normalized_chart_url(self._page.url).rstrip("/").split("/")[-1]
        targets = _http_json(4999, "/json/list")
        matching = [
            item for item in (targets or [])
            if item.get("type") == "page" and _normalizable_equal(
                str(item.get("url", "")), self.profile.expected_chart_url
            )
        ]
        target_id = str(matching[0].get("id", "")) if len(matching) == 1 else ""
        self._last_observed_timeframe = observed_tf or self._last_observed_timeframe
        return ChartState(
            page_ready=raw.get("page_ready") is True,
            authenticated=auth,
            url=self._page.url,
            layout_id=layout_id,
            chart_count=int(raw.get("chart_count") or 0),
            structured_symbol=structured,
            canonical_symbol=symbol,
            header_symbol=header_symbol,
            broker_feed=feed,
            header_feed=header_feed,
            timeframe=observed_tf,
            header_timeframe=header_timeframe,
            available_timeframes=self.profile.required_timeframes if raw.get("can_switch") else (),
            data_status=str(raw.get("data_status")),
            last_bar_at=last_bar,
            last_update_at=last_bar,
            modal_blocking=modal,
            disconnected="connection lost" in lowered,
            loading="loading chart" in lowered,
            header_identity_evidence={
                "raw": raw.get("header_identity") or {},
                "resolution": header_audit,
            },
            target_id=target_id,
            target_match_count=len(matching),
        )

    def switch_and_wait(self, timeframe: str, *, timeout_seconds: float | None = None) -> ChartState:
        try:
            tv_value = TF_TO_TV[timeframe]
        except KeyError as exc:
            raise Session3Error("MISSING_TIMEFRAME", f"unsupported timeframe {timeframe}") from exc
        previous_timeframe = self._last_observed_timeframe
        result = self._page.evaluate(_SWITCH_JS, tv_value)
        if not result.get("ok"):
            raise Session3Error("MISSING_TIMEFRAME", result.get("error", "timeframe switch failed"))
        configured = (
            self.transition_config if timeout_seconds is None
            else replace(self.transition_config, timeout_seconds=timeout_seconds)
        )
        sleeper = self._sleep or (lambda seconds: self._page.wait_for_timeout(seconds * 1000))
        return wait_for_timeframe_stability(
            self.profile,
            self.pin,
            timeframe,
            previous_timeframe,
            self.inspect,
            config=configured,
            monotonic=self._monotonic,
            sleep=sleeper,
            wall_clock=self._wall_clock,
        )

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
