"""Offline Evidence Bundle request boundary for Project A.

This module describes work that a separately approved capture runtime could do.
It deliberately contains no CDP, browser, socket, provider, writer, or broker
implementation.  Adapters return immutable request specifications only.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence


EVIDENCE_BUNDLE_SCHEMA_V1 = "project_a.evidence_bundle_request.v1"
STANDARD_MACD = (12, 26, 9)


class EvidenceBundleError(ValueError):
    """Raised when a request would cross or weaken the offline boundary."""


class RequestLevel(str, Enum):
    TELEMETRY_ONLY = "TELEMETRY_ONLY"
    NUMERIC_RESEARCH = "NUMERIC_RESEARCH"
    LIQ_RESEARCH_CAPTURE = "LIQ_RESEARCH_CAPTURE"
    PREWARM_ONLY = "PREWARM_ONLY"
    FULL_B_TO_A_CAPTURE = "FULL_B_TO_A_CAPTURE"
    DIRECTION_CONFIRMATION = "DIRECTION_CONFIRMATION"
    ENTRY_TIMING_ONLY = "ENTRY_TIMING_ONLY"


FULL_EVIDENCE_CAPTURE_LEVELS = frozenset(
    (RequestLevel.LIQ_RESEARCH_CAPTURE, RequestLevel.FULL_B_TO_A_CAPTURE)
)


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    PROVISIONAL = "PROVISIONAL"
    MARKET_CLOSED = "MARKET_CLOSED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CLOCK_INVALID = "CLOCK_INVALID"


JsonValue = Any


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise EvidenceBundleError("non-finite decimal is not canonical evidence")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_value(value: JsonValue) -> JsonValue:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise EvidenceBundleError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceBundleError("non-finite float is not canonical evidence")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise EvidenceBundleError("canonical evidence keys must be strings")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise EvidenceBundleError(f"unsupported canonical evidence type: {type(value).__name__}")


def canonical_json_bytes(value: JsonValue) -> bytes:
    """Return deterministic UTF-8 JSON bytes for hashes and audit fixtures."""
    return json.dumps(
        _canonical_value(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _freeze(value: JsonValue) -> JsonValue:
    """Deep-freeze JSON-like evidence so a built request cannot be mutated."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _iso_utc(value: datetime) -> str:
    return _canonical_value(value)


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    role: str
    port: int
    layout_id: str
    target_id: str
    symbol: str
    feed: str
    timeframes: tuple[str, ...]
    chart_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.port not in (9222, 9333):
            raise EvidenceBundleError("only approved request-boundary ports 9222/9333 are valid")
        if not all((self.role, self.layout_id, self.target_id, self.symbol, self.feed)):
            raise EvidenceBundleError("source identity must be complete")
        if not self.timeframes:
            raise EvidenceBundleError("source identity must declare timeframes")
        if not self.chart_types:
            object.__setattr__(self, "chart_types", tuple("standard_candles" for _ in self.timeframes))
        if len(self.chart_types) != len(self.timeframes):
            raise EvidenceBundleError("source chart types must align one-to-one with timeframes")
        if not set(self.chart_types) <= {"standard_candles", "volume_candles"}:
            raise EvidenceBundleError("source chart types must use the approved candle allowlist")

    def canonical(self) -> dict[str, JsonValue]:
        return {
            "role": self.role,
            "port": self.port,
            "layout_id": self.layout_id,
            "target_id": self.target_id,
            "symbol": self.symbol,
            "feed": self.feed,
            "timeframes": self.timeframes,
            "chart_types": self.chart_types,
        }


@dataclass(frozen=True, slots=True)
class StructuredReadRequest:
    request_id: str
    source: SourceIdentity
    read_kind: str
    fields: tuple[str, ...]
    timeframes: tuple[str, ...]
    required: bool = True
    closed_bars_only: bool = False
    indicator_parameters: tuple[int, ...] = ()

    def canonical(self) -> dict[str, JsonValue]:
        return {
            "request_id": self.request_id,
            "source": self.source.canonical(),
            "read_kind": self.read_kind,
            "fields": self.fields,
            "timeframes": self.timeframes,
            "required": self.required,
            "closed_bars_only": self.closed_bars_only,
            "indicator_parameters": self.indicator_parameters,
        }


@dataclass(frozen=True, slots=True)
class ScreenshotRequest:
    request_id: str
    source: SourceIdentity
    artifact_name: str
    required: bool = True
    authority: str = "VISUAL_ONLY"
    may_override_numeric: bool = False
    may_upgrade_confirmation: bool = False

    def __post_init__(self) -> None:
        if (
            self.authority != "VISUAL_ONLY"
            or self.may_override_numeric
            or self.may_upgrade_confirmation
        ):
            raise EvidenceBundleError("screenshots must remain visual-only evidence")

    def canonical(self) -> dict[str, JsonValue]:
        return {
            "request_id": self.request_id,
            "source": self.source.canonical(),
            "artifact_name": self.artifact_name,
            "required": self.required,
            "authority": self.authority,
            "may_override_numeric": self.may_override_numeric,
            "may_upgrade_confirmation": self.may_upgrade_confirmation,
        }


@dataclass(frozen=True, slots=True)
class FreshnessRecord:
    evidence_key: str
    status: FreshnessStatus
    source_time: str | None
    observed_at: str | None
    confirmed: bool

    def canonical(self) -> dict[str, JsonValue]:
        return {
            "evidence_key": self.evidence_key,
            "status": self.status.value,
            "source_time": self.source_time,
            "observed_at": self.observed_at,
            "confirmed": self.confirmed,
        }


@dataclass(frozen=True, slots=True)
class UnavailableEvidence:
    evidence_key: str
    reason: str
    required: bool

    def canonical(self) -> dict[str, JsonValue]:
        return {
            "evidence_key": self.evidence_key,
            "reason": self.reason,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    level: RequestLevel
    research_started: bool = False
    prewarm_only: bool = False
    b_to_a_candidate: bool = False
    direction_confirmation: bool = False
    entry_timing_only: bool = False
    full_capture_requested: bool = False
    provider_call_permitted: bool = False
    order_permitted: bool = False

    def canonical(self) -> dict[str, JsonValue]:
        return {
            "level": self.level.value,
            "research_started": self.research_started,
            "prewarm_only": self.prewarm_only,
            "b_to_a_candidate": self.b_to_a_candidate,
            "direction_confirmation": self.direction_confirmation,
            "entry_timing_only": self.entry_timing_only,
            "full_capture_requested": self.full_capture_requested,
            "provider_call_permitted": self.provider_call_permitted,
            "order_permitted": self.order_permitted,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBundleRequest:
    schema: str
    request_id: str
    requested_at: str
    trigger: TriggerDecision
    triggering_events: tuple[JsonValue, ...]
    event_history: tuple[JsonValue, ...]
    numeric_market_state: Mapping[str, JsonValue]
    structured_reads: tuple[StructuredReadRequest, ...]
    screenshot_requests: tuple[ScreenshotRequest, ...]
    source_identities: tuple[SourceIdentity, ...]
    freshness: tuple[FreshnessRecord, ...]
    missing_evidence: tuple[str, ...]
    unavailable_evidence: tuple[UnavailableEvidence, ...]
    hashes: Mapping[str, str] = field(repr=False)
    promotion_allowed: bool = False
    runtime_execution_enabled: bool = False
    writer_enablement: str = "DISABLED"

    def __post_init__(self) -> None:
        if self.schema != EVIDENCE_BUNDLE_SCHEMA_V1:
            raise EvidenceBundleError("unexpected Evidence Bundle schema")
        if self.promotion_allowed or self.runtime_execution_enabled:
            raise EvidenceBundleError("Evidence Bundle request cannot activate runtime promotion")
        if self.writer_enablement != "DISABLED":
            raise EvidenceBundleError("Evidence Bundle writers must remain disabled")
        if self.trigger.provider_call_permitted or self.trigger.order_permitted:
            raise EvidenceBundleError("Evidence Bundle trigger cannot call providers or place orders")
        object.__setattr__(self, "triggering_events", tuple(_freeze(item) for item in self.triggering_events))
        object.__setattr__(self, "event_history", tuple(_freeze(item) for item in self.event_history))
        object.__setattr__(self, "numeric_market_state", _freeze(self.numeric_market_state))
        object.__setattr__(self, "structured_reads", tuple(self.structured_reads))
        object.__setattr__(self, "screenshot_requests", tuple(self.screenshot_requests))
        object.__setattr__(self, "source_identities", tuple(self.source_identities))
        object.__setattr__(self, "freshness", tuple(self.freshness))
        object.__setattr__(self, "missing_evidence", tuple(self.missing_evidence))
        object.__setattr__(self, "unavailable_evidence", tuple(self.unavailable_evidence))
        object.__setattr__(self, "hashes", _freeze(self.hashes))

    def document(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "requested_at": self.requested_at,
            "trigger": self.trigger.canonical(),
            "triggering_events": self.triggering_events,
            "event_history": self.event_history,
            "numeric_market_state": self.numeric_market_state,
            "structured_reads": tuple(item.canonical() for item in self.structured_reads),
            "screenshot_requests": tuple(item.canonical() for item in self.screenshot_requests),
            "source_identities": tuple(item.canonical() for item in self.source_identities),
            "freshness": tuple(item.canonical() for item in self.freshness),
            "missing_evidence": self.missing_evidence,
            "unavailable_evidence": tuple(item.canonical() for item in self.unavailable_evidence),
            "hashes": self.hashes,
            "promotion_allowed": self.promotion_allowed,
            "runtime_execution_enabled": self.runtime_execution_enabled,
            "writer_enablement": self.writer_enablement,
        }


class StructuredRequestAdapter(Protocol):
    """Injectable boundary: creates specifications and performs no reads."""

    def compile_requests(
        self,
        sources: Mapping[str, SourceIdentity],
        level: RequestLevel,
    ) -> tuple[StructuredReadRequest, ...]: ...


class ScreenshotRequestAdapter(Protocol):
    """Injectable boundary: creates visual artifact intents only."""

    def compile_requests(
        self,
        sources: Mapping[str, SourceIdentity],
        level: RequestLevel,
    ) -> tuple[ScreenshotRequest, ...]: ...


PRIMARY_ROLES = ("xau_intraday", "xau_30m_15m", "xau_htf", "dxy_15m")
SUPPLEMENTAL_ROLES = ("dxy_1m", "renko")
FULL_CAPTURE_SCREENSHOT_ROLES = (
    "xau_intraday", "xau_30m_15m", "xau_htf", "dxy_15m", "renko",
)
SOURCE_AUTHORITY = {
    "xau_intraday": (9333, "cpPWuLlN", "XAUUSD", "ICMARKETS", ("1m", "5m"), ("volume_candles", "standard_candles")),
    "xau_30m_15m": (9333, "avpCVaw2", "XAUUSD", "ICMARKETS", ("15m", "30m"), ("standard_candles", "standard_candles")),
    "xau_htf": (9333, "pNqcbOmu", "XAUUSD", "ICMARKETS", ("4H", "D", "W"), ("volume_candles", "volume_candles", "volume_candles")),
    "dxy_15m": (9333, "n9qjfufV", "DXY", "TVC", ("15m",), ("standard_candles",)),
    "dxy_1m": (9222, "ocVwlz2C", "DXY", "TVC", ("1m",), ("standard_candles",)),
    "renko": (9333, "YclFo8Ax", "XAUUSD", "ICMARKETS", ("5s",), ("standard_candles",)),
}


def approved_source_identities() -> dict[str, SourceIdentity]:
    """Return request-only identities; the capture preflight must bind live targets."""
    return {
        role: SourceIdentity(
            role=role,
            port=authority[0],
            layout_id=authority[1],
            target_id=f"UNBOUND_REQUIRES_PREFLIGHT:{role}",
            symbol=authority[2],
            feed=authority[3],
            timeframes=authority[4],
            chart_types=authority[5],
        )
        for role, authority in SOURCE_AUTHORITY.items()
    }


def _require_source(
    sources: Mapping[str, SourceIdentity], role: str, port: int,
) -> SourceIdentity:
    try:
        source = sources[role]
    except KeyError as exc:
        raise EvidenceBundleError(f"missing source identity: {role}") from exc
    expected = SOURCE_AUTHORITY[role]
    if (
        source.role != role
        or source.port != port
        or (source.port, source.layout_id, source.symbol, source.feed,
            source.timeframes, source.chart_types) != expected
    ):
        raise EvidenceBundleError(
            f"source {role} must match approved port/layout/symbol/feed/timeframe/chart-type authority"
        )
    return source


class Port9333RequestAdapter:
    """Describe exact primary structured reads; never connect to port 9333."""

    def compile_requests(
        self,
        sources: Mapping[str, SourceIdentity],
        level: RequestLevel,
    ) -> tuple[StructuredReadRequest, ...]:
        if level in (RequestLevel.TELEMETRY_ONLY, RequestLevel.PREWARM_ONLY,
                     RequestLevel.DIRECTION_CONFIRMATION,
                     RequestLevel.ENTRY_TIMING_ONLY):
            return ()
        intraday = _require_source(sources, "xau_intraday", 9333)
        xau_30m_15m = _require_source(sources, "xau_30m_15m", 9333)
        requests = [
            StructuredReadRequest(
                "read_9333_xau_current", intraday, "CURRENT_FORMING_PRICE",
                (
                    "market_price", "bid", "ask", "spread", "normalized_spread",
                    "symbol", "feed",
                    "quote_source", "quote_provider_id", "quote_source_symbol",
                    "quote_source_feed", "timeframe", "atr", "atr_period",
                    "atr_method", "atr_source_time", "liquidity_level_id",
                    "liquidity_level_version", "liquidity_level_side",
                    "liquidity_level_price", "liquidity_touch_count",
                    "liquidity_event_timestamp", "liquidity_producer_id",
                    "liquidity_producer_revision", "distance_reference_price",
                    "distance_reference_side", "distance_to_level", "distance_atr",
                    "source_time", "observed_at",
                ),
                ("5m",),
            ),
            StructuredReadRequest(
                "read_9333_xau_closed_ohlc_5m", intraday, "CLOSED_OHLC",
                ("open", "high", "low", "close", "source_bar_time", "confirmed"),
                ("5m",), closed_bars_only=True,
            ),
            StructuredReadRequest(
                "read_9333_xau_macd_5m", intraday, "STANDARD_MACD",
                ("macd", "signal", "histogram", "previous_histogram", "source_bar_time", "confirmed"),
                ("5m",), closed_bars_only=True,
                indicator_parameters=STANDARD_MACD,
            ),
            StructuredReadRequest(
                "read_9333_xau_closed_ohlc_15m_30m", xau_30m_15m, "CLOSED_OHLC",
                ("open", "high", "low", "close", "source_bar_time", "confirmed"),
                ("15m", "30m"), closed_bars_only=True,
            ),
            StructuredReadRequest(
                "read_9333_xau_macd_15m_30m", xau_30m_15m, "STANDARD_MACD",
                ("macd", "signal", "histogram", "previous_histogram", "source_bar_time", "confirmed"),
                ("15m", "30m"), closed_bars_only=True,
                indicator_parameters=STANDARD_MACD,
            ),
            StructuredReadRequest(
                "read_9333_xau_expansion_context", intraday, "EXPANSION_CONTEXT",
                (
                    "direction", "start_price", "market_price", "displacement",
                    "atr", "atr_multiple", "path_efficiency", "body_quality",
                    "opposing_bars", "source_bar_time", "confirmed",
                ),
                ("5m",), closed_bars_only=True,
            ),
            StructuredReadRequest(
                "read_9333_xau_snr_hpa_context", intraday, "SNR_HPA_CONTEXT",
                (
                    "levels", "structure", "momentum", "source_bar_time",
                    "confirmed",
                ),
                ("5m",), closed_bars_only=True,
            ),
        ]
        if level in FULL_EVIDENCE_CAPTURE_LEVELS:
            _require_source(sources, "xau_htf", 9333)
            dxy = _require_source(sources, "dxy_15m", 9333)
            renko = _require_source(sources, "renko", 9333)
            requests.extend((
                StructuredReadRequest(
                    "read_9333_dxy_15m", dxy, "DXY_CONTEXT",
                    ("current", "close", "change", "sma20", "distance", "source_bar_time", "confirmed"),
                    ("15m",), closed_bars_only=True,
                ),
                StructuredReadRequest(
                    "read_9333_renko_5s", renko, "RENKO_STATE",
                    ("stage", "direction", "signal_price", "source_bar_time", "confirmed", "score", "power", "mode", "transfer"),
                    ("5s",),
                ),
                StructuredReadRequest(
                    "read_9333_xau_5s_price_action", renko, "SHORT_TERM_PRICE_ACTION",
                    (
                        "open", "high", "low", "close", "price_path", "source_bar_time",
                        "confirmed",
                    ),
                    ("5s",), closed_bars_only=True,
                ),
            ))
        return tuple(requests)


class Port9222RequestAdapter:
    """Describe approved supplemental reads; never connect to port 9222."""

    def compile_requests(
        self,
        sources: Mapping[str, SourceIdentity],
        level: RequestLevel,
    ) -> tuple[StructuredReadRequest, ...]:
        if level not in FULL_EVIDENCE_CAPTURE_LEVELS:
            return ()
        dxy = _require_source(sources, "dxy_1m", 9222)
        return (
            StructuredReadRequest(
                "read_9222_dxy_1m", dxy, "DXY_SUPPLEMENTAL",
                ("current", "close", "source_bar_time", "confirmed"), ("1m",),
                required=False, closed_bars_only=True,
            ),
        )


class ApprovedScreenshotRequestAdapter:
    """Describe the fixed visual bundle; cannot provide numeric authority."""

    def __init__(self, *, include_approved_dxy_1m_visual: bool = False) -> None:
        # The supplemental visual is opt-in: its inclusion represents a separate,
        # explicit approval by the caller, never a fallback chosen by this adapter.
        self._include_approved_dxy_1m_visual = include_approved_dxy_1m_visual

    def compile_requests(
        self,
        sources: Mapping[str, SourceIdentity],
        level: RequestLevel,
    ) -> tuple[ScreenshotRequest, ...]:
        if level not in FULL_EVIDENCE_CAPTURE_LEVELS:
            return ()
        requests = []
        for role in FULL_CAPTURE_SCREENSHOT_ROLES:
            port = 9333
            source = _require_source(sources, role, port)
            requests.append(ScreenshotRequest(
                request_id=f"screenshot_{port}_{role}",
                source=source,
                artifact_name=f"{port}/{source.layout_id}/{role}.png",
            ))
        if self._include_approved_dxy_1m_visual:
            source = _require_source(sources, "dxy_1m", 9222)
            requests.append(ScreenshotRequest(
                request_id="screenshot_9222_dxy_1m_supplemental",
                source=source,
                artifact_name=f"9222/{source.layout_id}/dxy_1m_supplemental.png",
                required=False,
            ))
        return tuple(requests)


def decide_trigger(
    triggering_events: Sequence[Mapping[str, JsonValue]],
    *,
    active_liquidity_expansion_story: bool,
    requested_at: datetime,
) -> TriggerDecision:
    """Apply the fixed trigger policy without inferring a trade direction."""
    names = tuple(str(event.get("event", event.get("event_type", ""))).upper()
                  for event in triggering_events)
    def valid_liq_touch(event: Mapping[str, JsonValue]) -> bool:
        name = str(event.get("event", event.get("event_type", ""))).upper()
        source_time = event.get("source_bar_time")
        if not isinstance(source_time, str):
            return False
        try:
            parsed = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        age = requested_at.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)
        touch_count = event.get("touch_count")
        return (
            name == "LIQ_TOUCH"
            and event.get("producer_id") == "LIQ_V2"
            and str(event.get("producer_revision")) == "9"
            and event.get("symbol") == "XAUUSD"
            and event.get("feed") == "ICMARKETS"
            and event.get("anchor_timeframe", event.get("timeframe")) == "5m"
            and event.get("confirmed") is True
            and event.get("freshness_status") == "FRESH"
            and event.get("level_freshness_status") == "FRESH"
            and event.get("market_price_freshness_status") == "FRESH"
            and isinstance(touch_count, int)
            and not isinstance(touch_count, bool)
            and touch_count >= 1
            and timedelta(0) <= age <= timedelta(minutes=15)
        )

    if any(valid_liq_touch(event) for event in triggering_events):
        return TriggerDecision(
            RequestLevel.LIQ_RESEARCH_CAPTURE,
            research_started=True,
            full_capture_requested=True,
        )
    if any(name.startswith(("EXP_", "RENKO_")) for name in names):
        return TriggerDecision(RequestLevel.TELEMETRY_ONLY)
    return TriggerDecision(RequestLevel.TELEMETRY_ONLY)


def _request_body(
    request_id: str,
    requested_at: str,
    trigger: TriggerDecision,
    triggering_events: Sequence[JsonValue],
    event_history: Sequence[JsonValue],
    numeric_market_state: Mapping[str, JsonValue],
    structured_reads: Sequence[StructuredReadRequest],
    screenshots: Sequence[ScreenshotRequest],
    sources: Sequence[SourceIdentity],
    freshness: Sequence[FreshnessRecord],
    missing: Sequence[str],
    unavailable: Sequence[UnavailableEvidence],
) -> dict[str, JsonValue]:
    return {
        "schema": EVIDENCE_BUNDLE_SCHEMA_V1,
        "request_id": request_id,
        "requested_at": requested_at,
        "trigger": trigger.canonical(),
        "triggering_events": triggering_events,
        "event_history": event_history,
        "numeric_market_state": numeric_market_state,
        "structured_reads": tuple(item.canonical() for item in structured_reads),
        "screenshot_requests": tuple(item.canonical() for item in screenshots),
        "source_identities": tuple(item.canonical() for item in sources),
        "freshness": tuple(item.canonical() for item in freshness),
        "missing_evidence": tuple(missing),
        "unavailable_evidence": tuple(item.canonical() for item in unavailable),
        "promotion_allowed": False,
        "runtime_execution_enabled": False,
        "writer_enablement": "DISABLED",
    }


def build_evidence_bundle_request(
    *,
    request_id: str,
    requested_at: datetime,
    triggering_events: Sequence[Mapping[str, JsonValue]],
    event_history: Sequence[Mapping[str, JsonValue]],
    numeric_market_state: Mapping[str, JsonValue],
    sources: Mapping[str, SourceIdentity],
    freshness: Sequence[FreshnessRecord] = (),
    missing_evidence: Sequence[str] = (),
    unavailable_evidence: Sequence[UnavailableEvidence] = (),
    active_liquidity_expansion_story: bool = False,
    primary_adapter: StructuredRequestAdapter | None = None,
    supplemental_adapter: StructuredRequestAdapter | None = None,
    screenshot_adapter: ScreenshotRequestAdapter | None = None,
) -> EvidenceBundleRequest:
    """Compile one immutable, canonical, non-executable request.

    ``promotion_allowed`` is intentionally always false: this model gathers
    evidence for later deterministic and Fresh-Eyes review boundaries.  It can
    neither call a provider nor place an order.
    """
    if not request_id or not triggering_events:
        raise EvidenceBundleError("request_id and at least one triggering event are required")
    requested_at_text = _iso_utc(requested_at)
    trigger = decide_trigger(
        triggering_events,
        active_liquidity_expansion_story=active_liquidity_expansion_story,
        requested_at=requested_at,
    )
    primary = primary_adapter or Port9333RequestAdapter()
    supplemental = supplemental_adapter or Port9222RequestAdapter()
    visual = screenshot_adapter or ApprovedScreenshotRequestAdapter()

    structured_reads = (
        primary.compile_requests(sources, trigger.level)
        + supplemental.compile_requests(sources, trigger.level)
    )
    screenshot_requests = visual.compile_requests(sources, trigger.level)
    ordered_sources = tuple(sorted(sources.values(), key=lambda item: item.role))
    missing = tuple(sorted(set(missing_evidence)))
    unavailable = tuple(sorted(
        unavailable_evidence,
        key=lambda item: (item.evidence_key, item.reason, item.required),
    ))
    frozen_events = tuple(_freeze(_canonical_value(item)) for item in triggering_events)
    frozen_history = tuple(_freeze(_canonical_value(item)) for item in event_history)
    frozen_state = _freeze(_canonical_value(numeric_market_state))
    body = _request_body(
        request_id, requested_at_text, trigger, frozen_events, frozen_history,
        frozen_state, structured_reads, screenshot_requests, ordered_sources,
        freshness, missing, unavailable,
    )
    hashes = {
        "triggering_events_sha256": canonical_sha256(frozen_events),
        "event_history_sha256": canonical_sha256(frozen_history),
        "numeric_market_state_sha256": canonical_sha256(frozen_state),
        "structured_reads_sha256": canonical_sha256(body["structured_reads"]),
        "screenshot_requests_sha256": canonical_sha256(body["screenshot_requests"]),
        "bundle_request_sha256": canonical_sha256(body),
    }
    return EvidenceBundleRequest(
        schema=EVIDENCE_BUNDLE_SCHEMA_V1,
        request_id=request_id,
        requested_at=requested_at_text,
        trigger=trigger,
        triggering_events=frozen_events,
        event_history=frozen_history,
        numeric_market_state=frozen_state,
        structured_reads=structured_reads,
        screenshot_requests=screenshot_requests,
        source_identities=ordered_sources,
        freshness=tuple(freshness),
        missing_evidence=missing,
        unavailable_evidence=unavailable,
        hashes=MappingProxyType(hashes),
    )
