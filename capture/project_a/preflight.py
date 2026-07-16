"""Pure strict preflight gates for the dedicated Project A chart route."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .errors import Session3Error
from .input_boundary import AnalysisAuthority
from .profile import CaptureProfile, TabPin, normalized_chart_url

TIMEFRAME_SECONDS = {"5s": 5, "1m": 60, "5m": 300, "15m": 900, "30m": 1800}


@dataclass(frozen=True)
class EndpointInfo:
    available: bool
    host: str
    port: int
    local_addresses: tuple[str, ...] = ()
    pid: int | None = None
    process_name: str | None = None
    command_line: str = ""
    browser: str = ""
    protocol_version: str = ""


@dataclass(frozen=True)
class TargetInfo:
    target_id: str
    target_type: str
    url: str
    title: str = ""


@dataclass(frozen=True)
class ChartState:
    page_ready: bool
    authenticated: bool
    url: str
    layout_id: str
    chart_count: int
    structured_symbol: str
    canonical_symbol: str
    header_symbol: str
    broker_feed: str
    header_feed: str
    timeframe: str
    header_timeframe: str
    available_timeframes: tuple[str, ...]
    data_status: str
    last_bar_at: datetime
    last_update_at: datetime
    modal_blocking: bool = False
    disconnected: bool = False
    loading: bool = False


def verify_endpoint(profile: CaptureProfile, endpoint: EndpointInfo) -> None:
    profile.validate()
    if endpoint.host != "127.0.0.1" or endpoint.port != 4999:
        raise Session3Error("PORT_MISMATCH", f"observed {endpoint.host}:{endpoint.port}")
    if not endpoint.available:
        raise Session3Error("PORT_UNAVAILABLE", "127.0.0.1:4999 has no compatible CDP endpoint")
    if not endpoint.local_addresses or any(address not in {"127.0.0.1", "::1"}
                                               for address in endpoint.local_addresses):
        raise Session3Error("UNSAFE_BINDING", f"listener addresses={endpoint.local_addresses!r}")
    process_name = (endpoint.process_name or "").lower()
    command = endpoint.command_line.lower()
    if process_name not in profile.process_names:
        raise Session3Error("WRONG_PROCESS", f"listener process={endpoint.process_name!r}")
    if "--remote-debugging-port=4999" not in command or profile.profile_marker.lower() not in command:
        raise Session3Error("WRONG_PROCESS", "listener command does not attest port 4999 and the isolated profile marker")
    if not endpoint.browser or not endpoint.protocol_version:
        raise Session3Error("MCP_UNAVAILABLE", "CDP /json/version identity is incomplete")


def select_pinned_target(profile: CaptureProfile, pin: TabPin,
                         targets: list[TargetInfo]) -> TargetInfo:
    if pin.chart_url != profile.expected_chart_url or pin.layout_id != profile.expected_layout_id:
        raise Session3Error("WRONG_TAB", "tab pin does not match the configured layout identity")
    exact_url = []
    for target in targets:
        if target.target_type != "page":
            continue
        try:
            matches = normalized_chart_url(target.url) == profile.expected_chart_url
        except Session3Error:
            matches = False
        if matches:
            exact_url.append(target)
    if len(exact_url) > 1:
        raise Session3Error("TAB_AMBIGUOUS", f"{len(exact_url)} page targets have the approved URL")
    pinned = [target for target in targets if target.target_id == pin.target_id]
    if not pinned:
        raise Session3Error("TAB_NOT_FOUND", f"pinned target {pin.target_id!r} is absent")
    if len(pinned) != 1:
        raise Session3Error("TAB_AMBIGUOUS", "pinned target ID is not unique")
    selected = pinned[0]
    try:
        selected_url = normalized_chart_url(selected.url)
    except Session3Error as exc:
        raise Session3Error("WRONG_TAB", "pinned target is not a TradingView chart") from exc
    if selected.target_type != "page" or selected_url != profile.expected_chart_url:
        raise Session3Error("WRONG_TAB", "pinned target is not the exact approved TradingView chart")
    return selected


def verify_chart_state(profile: CaptureProfile, authority: AnalysisAuthority,
                       state: ChartState, *, expected_timeframe: str,
                       observed_at: datetime) -> dict:
    observed_at = observed_at.astimezone(timezone.utc)
    authority.ensure_unexpired(observed_at)
    if not state.page_ready:
        raise Session3Error("PAGE_NOT_READY", "document/chart structured state is not ready")
    if not state.authenticated:
        raise Session3Error("AUTH_UNUSABLE", "authenticated TradingView state is unavailable")
    if state.modal_blocking or state.loading:
        raise Session3Error("MODAL_BLOCKING", "modal or loading overlay blocks verified capture")
    if state.disconnected or state.data_status != "streaming":
        raise Session3Error("STALE_CHART", f"chart data_status={state.data_status!r}")
    if normalized_chart_url(state.url) != profile.expected_chart_url:
        raise Session3Error("WRONG_TAB", "observed page URL differs from the pinned chart URL")
    if state.layout_id != profile.expected_layout_id or state.chart_count != profile.expected_chart_count:
        raise Session3Error("WRONG_LAYOUT", f"layout={state.layout_id!r}, chart_count={state.chart_count}")
    if state.structured_symbol not in profile.aliases or state.canonical_symbol != profile.symbol:
        raise Session3Error("WRONG_SYMBOL", f"structured symbol={state.structured_symbol!r}")
    if state.header_symbol != profile.symbol:
        raise Session3Error("WRONG_SYMBOL", f"independent header symbol={state.header_symbol!r}")
    if state.broker_feed != profile.broker_feed or state.header_feed != profile.broker_feed:
        raise Session3Error("WRONG_FEED", f"structured/header feed={state.broker_feed!r}/{state.header_feed!r}")
    if state.timeframe != expected_timeframe or state.header_timeframe != expected_timeframe:
        raise Session3Error("WRONG_TIMEFRAME", f"observed/header timeframe={state.timeframe!r}/{state.header_timeframe!r}")
    missing = sorted(set(profile.required_timeframes) - set(state.available_timeframes))
    if missing:
        raise Session3Error("MISSING_TIMEFRAME", "unavailable: " + ", ".join(missing))
    bar_at = state.last_bar_at.astimezone(timezone.utc)
    update_at = state.last_update_at.astimezone(timezone.utc)
    if bar_at + timedelta(seconds=TIMEFRAME_SECONDS[expected_timeframe]) <= authority.bar_time:
        raise Session3Error("STALE_CHART", "latest chart bar interval ends before the source bar")
    if update_at < bar_at or update_at > observed_at:
        raise Session3Error("STALE_CHART", "structured chart update chronology is invalid")
    if bar_at > observed_at:
        raise Session3Error("STALE_CHART", "chart reports a future bar timestamp")
    return {
        "page_ready": True,
        "authenticated": True,
        "tab_url_verified": True,
        "layout_verified": True,
        "symbol_verified": True,
        "feed_verified": True,
        "timeframe_verified": True,
        "required_timeframes_available": True,
        "streaming_verified": True,
        "source_bar_covered": True,
    }


def verify_preflight(profile: CaptureProfile, pin: TabPin, endpoint: EndpointInfo,
                     targets: list[TargetInfo], state: ChartState,
                     authority: AnalysisAuthority, *, observed_at: datetime,
                     destination_writable: bool) -> dict:
    verify_endpoint(profile, endpoint)
    selected = select_pinned_target(profile, pin, targets)
    if not destination_writable:
        raise Session3Error("DESTINATION_UNWRITABLE", "artifact root preflight failed")
    verification = verify_chart_state(
        profile, authority, state, expected_timeframe=profile.base_timeframe,
        observed_at=observed_at,
    )
    return {
        "endpoint_verified": True,
        "local_only_verified": True,
        "process_verified": True,
        "target_id": selected.target_id,
        "destination_writable": True,
        **verification,
    }
