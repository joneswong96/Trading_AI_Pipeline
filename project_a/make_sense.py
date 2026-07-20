"""Deterministic, offline Project A Make-Sense request compiler.

This module deliberately has no network, provider, writer, broker, or runtime
integration.  It turns already-observed facts into an immutable request record
whose dispatch switches are permanently disabled.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "project_a.make_sense_request.v1"
PROVIDER_SCHEMA = "project_a.provider_neutral_request.v1"
HARD_FRESHNESS_FAILURES = frozenset(
    {"STALE", "MISSING", "CLOCK_INVALID", "SOURCE_UNAVAILABLE", "MARKET_CLOSED"}
)
TERMINAL_LIQUIDITY = frozenset(
    {"BREAK", "INVALIDATED", "EXPIRED", "REMOVED", "STALE", "SOURCE_UNAVAILABLE"}
)


class StoryState(str, Enum):
    NO_STORY = "NO_STORY"
    C_INSUFFICIENT = "C_INSUFFICIENT"
    B_BUILDING = "B_BUILDING"
    B_TO_A_CANDIDATE = "B_TO_A_CANDIDATE"
    A_REVIEW_REQUIRED = "A_REVIEW_REQUIRED"
    WAITING_5S_ENTRY = "WAITING_5S_ENTRY"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class CompileError(ValueError):
    """Raised when an input cannot be interpreted without guessing."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        _thaw(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_time(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CompileError(f"{field_name} is required")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CompileError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CompileError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _event_name(event: Mapping[str, Any]) -> str:
    name = event.get("event")
    if not isinstance(name, str) or not name:
        raise CompileError("trigger_event.event is required")
    return name


def _is_confirmed(record: Mapping[str, Any] | None) -> bool:
    return bool(record and record.get("confirmed") is True)


def _fresh(statuses: Mapping[str, Any], *keys: str) -> tuple[bool, tuple[str, ...]]:
    missing = []
    for key in keys:
        status = statuses.get(key)
        if status != "FRESH":
            missing.append(f"freshness.{key}={status if status is not None else 'MISSING'}")
    return not missing, tuple(missing)


def _hard_freshness_failure(statuses: Mapping[str, Any]) -> bool:
    return any(value in HARD_FRESHNESS_FAILURES for value in statuses.values())


def _expected_expansion(side: Any) -> str | None:
    return {"ASK": "UP", "BID": "DOWN"}.get(side)


def _hypothesis(side: Any, direction: Any) -> str | None:
    if side == "ASK" and direction == "UP":
        return "POSSIBLE_BEARISH_REVERSAL"
    if side == "BID" and direction == "DOWN":
        return "POSSIBLE_BULLISH_REVERSAL"
    return None


def _matching_expansion(
    liquidity: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    trigger_time: datetime,
) -> Mapping[str, Any] | None:
    expected = _expected_expansion(liquidity.get("side"))
    if expected is None:
        return None
    candidates: list[tuple[datetime, Mapping[str, Any]]] = []
    for item in history:
        if item.get("direction") != expected or item.get("confirmed") is not True:
            continue
        if item.get("symbol") != liquidity.get("symbol") or item.get("feed") != liquidity.get("feed"):
            continue
        try:
            at = _parse_time(item.get("source_bar_time"), "expansion.source_bar_time")
        except CompileError:
            continue
        if at <= trigger_time:
            candidates.append((at, item))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], str(row[1].get("event_id", ""))))
    return candidates[-1][1]


def _active_liquidity(liquidity: Mapping[str, Any]) -> bool:
    return (
        isinstance(liquidity.get("level_id"), str)
        and bool(liquidity.get("level_id"))
        and liquidity.get("side") in {"ASK", "BID"}
        and liquidity.get("lifecycle") not in TERMINAL_LIQUIDITY
        and liquidity.get("confirmed") is True
    )


def _macd_corroboration(macd: Mapping[str, Any]) -> bool:
    one = macd.get("1m")
    five = macd.get("5m")
    return _is_confirmed(one) and _is_confirmed(five)


@dataclass(frozen=True)
class MakeSenseInput:
    trigger_event: Mapping[str, Any]
    liquidity: Mapping[str, Any] = field(default_factory=dict)
    expansion_history: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    price_path: Mapping[str, Any] = field(default_factory=dict)
    macd: Mapping[str, Any] = field(default_factory=dict)
    dxy: Mapping[str, Any] = field(default_factory=dict)
    renko: Mapping[str, Any] = field(default_factory=dict)
    htf_context: Mapping[str, Any] = field(default_factory=dict)
    freshness: Mapping[str, Any] = field(default_factory=dict)
    evidence_references: Sequence[str] = field(default_factory=tuple)
    prior_state: str = StoryState.NO_STORY.value
    final_review: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "trigger_event", "liquidity", "price_path", "macd", "dxy",
            "renko", "htf_context", "freshness", "final_review",
        ):
            object.__setattr__(self, name, _freeze(deepcopy(dict(getattr(self, name)))))
        object.__setattr__(
            self, "expansion_history",
            tuple(_freeze(deepcopy(dict(item))) for item in self.expansion_history),
        )
        object.__setattr__(self, "evidence_references", tuple(self.evidence_references))


@dataclass(frozen=True)
class MakeSenseRequest:
    state: StoryState
    trigger_event: str
    research_started: bool
    numeric_snapshot_requested: bool
    full_capture_requested: bool
    prewarm_requested: bool
    final_trade_direction: None
    hypotheses: tuple[str, ...]
    reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    selected_expansion_event_id: str | None
    evidence_references: tuple[str, ...]
    facts: Mapping[str, Any]
    schema: str = SCHEMA
    provider_dispatch_enabled: bool = False
    network_enabled: bool = False
    writer_enabled: bool = False
    broker_enabled: bool = False
    order_placed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", _freeze(deepcopy(dict(self.facts))))

    def document(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "state": self.state.value,
            "trigger_event": self.trigger_event,
            "research_started": self.research_started,
            "numeric_snapshot_requested": self.numeric_snapshot_requested,
            "full_capture_requested": self.full_capture_requested,
            "prewarm_requested": self.prewarm_requested,
            "final_trade_direction": self.final_trade_direction,
            "hypotheses": list(self.hypotheses),
            "reasons": list(self.reasons),
            "missing_evidence": list(self.missing_evidence),
            "selected_expansion_event_id": self.selected_expansion_event_id,
            "evidence_references": list(self.evidence_references),
            "facts": _thaw(self.facts),
            "safety": {
                "provider_dispatch_enabled": self.provider_dispatch_enabled,
                "network_enabled": self.network_enabled,
                "writer_enabled": self.writer_enabled,
                "broker_enabled": self.broker_enabled,
                "order_placed": self.order_placed,
            },
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_bytes(self.document())).hexdigest()


@dataclass(frozen=True)
class ProviderNeutralRequest:
    kind: str
    make_sense_sha256: str
    evidence_bundle_sha256: str | None
    body: Mapping[str, Any]
    schema: str = PROVIDER_SCHEMA
    dispatch_enabled: bool = False
    network_enabled: bool = False
    credentials_required: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"DASH_MAKE_SENSE_AI", "FINAL_FRESH_EYES_REVIEW"}:
            raise CompileError("unsupported provider-neutral request kind")
        object.__setattr__(self, "body", _freeze(deepcopy(dict(self.body))))

    def document(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "kind": self.kind,
            "make_sense_sha256": self.make_sense_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "body": _thaw(self.body),
            "dispatch_enabled": self.dispatch_enabled,
            "network_enabled": self.network_enabled,
            "credentials_required": self.credentials_required,
        }


class MakeSenseCompiler:
    """Compile deterministic story state without executing any requested work."""

    def compile(self, source: MakeSenseInput) -> MakeSenseRequest:
        event = _event_name(source.trigger_event)
        trigger_time = _parse_time(source.trigger_event.get("source_bar_time"), "trigger_event.source_bar_time")
        reasons: list[str] = []
        missing: list[str] = []
        hypotheses: list[str] = []
        research = event == "LIQ_TOUCH"
        snapshot = event == "LIQ_TOUCH"
        capture = False
        prewarm = event == "RENKO_E1"
        state = StoryState.NO_STORY

        lifecycle = source.liquidity.get("lifecycle")
        if event in {"LIQ_BREAK", "LIQ_INVALIDATED", "RENKO_RESET", "RENKO_INVALIDATED"} or lifecycle in {"BREAK", "INVALIDATED", "REMOVED"}:
            state = StoryState.INVALIDATED
            reasons.append("TERMINAL_SOURCE_EVENT")
        elif event == "SETUP_EXPIRED" or (
            source.prior_state not in {StoryState.NO_STORY.value, StoryState.C_INSUFFICIENT.value}
            and _hard_freshness_failure(source.freshness)
        ):
            state = StoryState.EXPIRED
            reasons.append("CRITICAL_EVIDENCE_NOT_FRESH")
        elif event.startswith("EXP_"):
            state = StoryState.NO_STORY
            reasons.append("EXPANSION_TELEMETRY_ONLY")
        else:
            active_liq = _active_liquidity(source.liquidity)
            if not active_liq:
                missing.append("active_confirmed_liquidity")
            expansion = _matching_expansion(source.liquidity, source.expansion_history, trigger_time) if active_liq else None
            if expansion is None:
                missing.append("prior_confirmed_expansion_toward_level")
            else:
                idea = _hypothesis(source.liquidity.get("side"), expansion.get("direction"))
                if idea:
                    hypotheses.append(idea)

            fresh_core, freshness_missing = _fresh(source.freshness, "xau", "atr_5m", "liquidity")
            missing.extend(freshness_missing)
            story_ready = active_liq and expansion is not None and fresh_core

            if event == "LIQ_TOUCH":
                state = StoryState.B_BUILDING if story_ready else StoryState.C_INSUFFICIENT
                reasons.append("LIQ_TOUCH_RESEARCH_STARTED")
            elif event == "RENKO_E1":
                state = StoryState.B_BUILDING if story_ready else StoryState.C_INSUFFICIENT
                reasons.append("RENKO_E1_EARLY_WATCH")
            elif event == "RENKO_E2":
                if not _is_confirmed(source.trigger_event):
                    missing.append("confirmed_renko_e2")
                if not _macd_corroboration(source.macd):
                    missing.append("confirmed_1m_5m_macd_corroboration")
                fresh_candidate, candidate_missing = _fresh(source.freshness, "macd_1m", "macd_5m", "renko")
                missing.extend(candidate_missing)
                ready = story_ready and _is_confirmed(source.trigger_event) and _macd_corroboration(source.macd) and fresh_candidate
                state = StoryState.B_TO_A_CANDIDATE if ready else StoryState.C_INSUFFICIENT
                capture = ready
                reasons.append("RENKO_E2_FULL_CAPTURE" if ready else "RENKO_E2_CORROBORATION_INCOMPLETE")
            elif event == "RENKO_MAIN":
                ready = story_ready and _is_confirmed(source.trigger_event) and _macd_corroboration(source.macd) and source.liquidity.get("reaction_confirmed") is True
                if not ready:
                    missing.append("confirmed_reaction_and_1m_5m_thesis")
                state = StoryState.A_REVIEW_REQUIRED if ready else StoryState.C_INSUFFICIENT
                reasons.append("RENKO_MAIN_CONFIRMATION_ONLY")
            elif event == "RENKO_FIRE":
                thesis_ok = (
                    source.prior_state == StoryState.WAITING_5S_ENTRY.value
                    and _is_confirmed(source.trigger_event)
                    and _macd_corroboration(source.macd)
                    and source.liquidity.get("reaction_confirmed") is True
                )
                fresh_fire, fire_missing = _fresh(source.freshness, "xau", "macd_1m", "macd_5m", "renko_fire")
                missing.extend(fire_missing)
                if not thesis_ok:
                    missing.append("valid_waiting_5s_5m_1m_thesis")
                state = StoryState.A_REVIEW_REQUIRED if thesis_ok and fresh_fire else StoryState.C_INSUFFICIENT
                reasons.append("RENKO_FIRE_TIMING_ONLY")
            elif source.final_review.get("verdict") in {"APPROVE", "MODIFY"} and source.final_review.get("grade") == "A":
                has_fire = source.renko.get("fire_confirmed") is True
                state = StoryState.A_REVIEW_REQUIRED if has_fire else StoryState.WAITING_5S_ENTRY
                reasons.append("FINAL_REVIEW_RECORDED_NO_EXECUTION")
            else:
                state = StoryState.B_BUILDING if story_ready else StoryState.C_INSUFFICIENT
                reasons.append("STORY_EVALUATED")

        facts = {
            "trigger_event": _thaw(source.trigger_event),
            "liquidity": _thaw(source.liquidity),
            "expansion_history": _thaw(source.expansion_history),
            "price_path": _thaw(source.price_path),
            "macd": _thaw(source.macd),
            "dxy": _thaw(source.dxy),
            "renko": _thaw(source.renko),
            "htf_context": _thaw(source.htf_context),
            "freshness": _thaw(source.freshness),
        }
        selected = None
        if "expansion" in locals() and expansion is not None:
            selected = str(expansion.get("event_id")) if expansion.get("event_id") is not None else None
        return MakeSenseRequest(
            state=state,
            trigger_event=event,
            research_started=research,
            numeric_snapshot_requested=snapshot,
            full_capture_requested=capture,
            prewarm_requested=prewarm,
            final_trade_direction=None,
            hypotheses=tuple(hypotheses),
            reasons=tuple(dict.fromkeys(reasons)),
            missing_evidence=tuple(dict.fromkeys(missing)),
            selected_expansion_event_id=selected,
            evidence_references=tuple(source.evidence_references),
            facts=facts,
        )


def disabled_dash_request(request: MakeSenseRequest) -> ProviderNeutralRequest:
    """Create a serializable Dash request that cannot dispatch itself."""
    return ProviderNeutralRequest(
        kind="DASH_MAKE_SENSE_AI",
        make_sense_sha256=request.sha256,
        evidence_bundle_sha256=None,
        body=request.document(),
    )


def disabled_final_review_request(
    request: MakeSenseRequest,
    *,
    evidence_bundle_sha256: str,
) -> ProviderNeutralRequest:
    """Create a serializable Fresh-Eyes request that cannot dispatch itself."""
    if not isinstance(evidence_bundle_sha256, str) or len(evidence_bundle_sha256) != 64:
        raise CompileError("evidence_bundle_sha256 must be 64 hexadecimal characters")
    try:
        int(evidence_bundle_sha256, 16)
    except ValueError as exc:
        raise CompileError("evidence_bundle_sha256 must be hexadecimal") from exc
    return ProviderNeutralRequest(
        kind="FINAL_FRESH_EYES_REVIEW",
        make_sense_sha256=request.sha256,
        evidence_bundle_sha256=evidence_bundle_sha256.lower(),
        body=request.document(),
    )


__all__ = [
    "CompileError",
    "MakeSenseCompiler",
    "MakeSenseInput",
    "MakeSenseRequest",
    "ProviderNeutralRequest",
    "StoryState",
    "disabled_dash_request",
    "disabled_final_review_request",
]
