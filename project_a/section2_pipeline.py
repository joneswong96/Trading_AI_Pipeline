"""Offline coordinator for the Project A Section-2 evidence request chain.

The coordinator composes pure request/state boundaries.  It performs no live
read, screenshot, provider call, write, notification, broker connection, or
order action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .evidence_bundle import (
    FreshnessRecord,
    FreshnessStatus,
    SourceIdentity,
    UnavailableEvidence,
    build_evidence_bundle_request,
)
from .make_sense import (
    MakeSenseCompiler,
    MakeSenseInput,
    MakeSenseRequest,
    ProviderNeutralRequest,
    StoryState,
    disabled_dash_request,
    disabled_final_review_request,
)
from .numeric_state import CanonicalEvent, NumericMarketState


PIPELINE_SCHEMA_V1 = "project_a.section2_offline_pipeline/1.0"


class Section2PipelineError(ValueError):
    """Raised when the offline chain cannot be compiled without guessing."""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise Section2PipelineError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _event_document(event: CanonicalEvent) -> dict[str, Any]:
    document = _json_value(event.data)
    document["canonical_event_id"] = event.canonical_event_id
    document["payload_sha256"] = event.payload_sha256
    return document


def _liquidity_document(event: CanonicalEvent | None) -> dict[str, Any]:
    if event is None:
        return {}
    document = _event_document(event)
    document["reaction_confirmed"] = document.get("lifecycle") == "REJECT" and event.confirmed
    return document


def _freshness_records(
    statuses: Mapping[str, str],
    *,
    source_time: str,
    observed_at: str,
) -> tuple[tuple[FreshnessRecord, ...], tuple[str, ...], tuple[UnavailableEvidence, ...]]:
    records = []
    missing = []
    unavailable = []
    for key, status in sorted(statuses.items()):
        if status == "MISSING":
            missing.append(key)
            continue
        try:
            rendered = FreshnessStatus(status)
        except ValueError as exc:
            raise Section2PipelineError(f"unsupported freshness status for {key}: {status}") from exc
        records.append(
            FreshnessRecord(
                evidence_key=key,
                status=rendered,
                source_time=source_time,
                observed_at=observed_at,
                confirmed=status not in {"PROVISIONAL", "CLOCK_INVALID"},
            )
        )
        if status in {"SOURCE_UNAVAILABLE", "CLOCK_INVALID", "MARKET_CLOSED"}:
            unavailable.append(UnavailableEvidence(key, status, True))
    return tuple(records), tuple(missing), tuple(unavailable)


@dataclass(frozen=True, slots=True)
class Section2PipelineResult:
    schema: str
    numeric_state: NumericMarketState
    make_sense_request: MakeSenseRequest
    evidence_bundle_request: Any
    dash_request: ProviderNeutralRequest
    final_review_request: ProviderNeutralRequest | None
    grading_preparation_requested: bool = False
    runtime_enabled: bool = False
    provider_enabled: bool = False
    writer_enabled: bool = False
    broker_enabled: bool = False
    order_placed: bool = False

    def __post_init__(self) -> None:
        if self.schema != PIPELINE_SCHEMA_V1:
            raise Section2PipelineError("unexpected pipeline schema")
        if any(
            (
                self.runtime_enabled,
                self.provider_enabled,
                self.writer_enabled,
                self.broker_enabled,
                self.order_placed,
            )
        ):
            raise Section2PipelineError("offline pipeline cannot activate side effects")


class OfflineSection2Pipeline:
    """Compose the immutable Section-2 requests from supplied offline facts."""

    def __init__(self, sources: Mapping[str, SourceIdentity]) -> None:
        self._sources = MappingProxyType(dict(sources))

    def compile(
        self,
        *,
        producer_events: Sequence[bytes | str | Mapping[str, Any]],
        trigger_event_id: str,
        requested_at: datetime,
        macd: Mapping[str, Any],
        dxy: Mapping[str, Any],
        htf_context: Mapping[str, Any],
        freshness: Mapping[str, str],
        prior_state: str = StoryState.NO_STORY.value,
        final_review: Mapping[str, Any] | None = None,
        primary_request_adapter: Any | None = None,
        supplemental_request_adapter: Any | None = None,
        screenshot_request_adapter: Any | None = None,
    ) -> Section2PipelineResult:
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise Section2PipelineError("requested_at must be timezone-aware")
        state = NumericMarketState()
        for payload in producer_events:
            state.ingest(payload)
        trigger = next(
            (event for event in state.event_history if event.producer_event_id == trigger_event_id),
            None,
        )
        if trigger is None:
            raise Section2PipelineError("trigger_event_id is not present in immutable event history")
        liquidity_event = state.current_observations.get("LIQUIDITY")
        expansion_history = tuple(_event_document(event) for event in state.expansion_history)
        event_history = tuple(_event_document(event) for event in state.event_history)
        trigger_document = _event_document(trigger)
        evidence_references = tuple(event.canonical_event_id for event in state.event_history)
        make_sense_input = MakeSenseInput(
            trigger_event=trigger_document,
            liquidity=_liquidity_document(liquidity_event),
            expansion_history=expansion_history,
            price_path={"points": _json_value(state.snapshot()["price_path"])},
            macd=_json_value(macd),
            dxy=_json_value(dxy),
            renko=_json_value(state.snapshot()["renko"]),
            htf_context=_json_value(htf_context),
            freshness=dict(freshness),
            evidence_references=evidence_references,
            prior_state=prior_state,
            final_review={} if final_review is None else _json_value(final_review),
        )
        make_sense = MakeSenseCompiler().compile(make_sense_input)
        observed_at = requested_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        source_time = str(trigger_document["source_bar_time"])
        freshness_records, missing, unavailable = _freshness_records(
            freshness, source_time=source_time, observed_at=observed_at,
        )
        bundle = build_evidence_bundle_request(
            request_id=f"evidence_{trigger.canonical_event_id}",
            requested_at=requested_at,
            triggering_events=(trigger_document,),
            event_history=event_history,
            numeric_market_state=_json_value(state.snapshot()),
            sources=self._sources,
            freshness=freshness_records,
            missing_evidence=tuple(make_sense.missing_evidence) + missing,
            unavailable_evidence=unavailable,
            active_liquidity_expansion_story=(
                make_sense.state is StoryState.B_TO_A_CANDIDATE
                and make_sense.full_capture_requested
            ),
            primary_adapter=primary_request_adapter,
            supplemental_adapter=supplemental_request_adapter,
            screenshot_adapter=screenshot_request_adapter,
        )
        dash = disabled_dash_request(make_sense)
        final = None
        if make_sense.full_capture_requested or make_sense.state in {
            StoryState.A_REVIEW_REQUIRED,
            StoryState.WAITING_5S_ENTRY,
        }:
            final = disabled_final_review_request(
                make_sense,
                evidence_bundle_sha256=str(bundle.hashes["bundle_request_sha256"]),
            )
        return Section2PipelineResult(
            schema=PIPELINE_SCHEMA_V1,
            numeric_state=state,
            make_sense_request=make_sense,
            evidence_bundle_request=bundle,
            dash_request=dash,
            final_review_request=final,
            grading_preparation_requested=bundle.trigger.full_capture_requested,
        )


__all__ = [
    "OfflineSection2Pipeline",
    "PIPELINE_SCHEMA_V1",
    "Section2PipelineError",
    "Section2PipelineResult",
]
