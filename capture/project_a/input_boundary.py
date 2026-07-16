"""Canonical Event V1 input and disabled analysis-adapter boundary."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from contracts import (
    CanonicalEventV1Document,
    ContractError,
    canonical_json_bytes,
    semantic_evidence_projection,
    validate_canonical_event_v1,
)

from .errors import Session3Error

ADAPTER_FAMILY = "PROJECT_A_SESSION_2_CAPTURE_ADAPTER"
ADAPTER_VERSION = "1.0"
ADAPTER_STATUS = "DISABLED_RECORDED_ONLY"
_ADAPTER_FIELDS = {"adapter_family", "adapter_version", "runtime_enabled", "status", "source", "payload"}
_ADAPTER_SOURCE_FIELDS = {
    "canonical_event_id",
    "canonical_content_hash",
    "semantic_evidence_hash",
    "setup_id",
    "producer_event_id",
    "receipt_id",
    "raw_content_hash",
    "immutable_raw_reference",
}
_ANALYSIS_FIELDS = {
    "expires_at",
    "bar_time",
    "session",
    "instrument",
    "snr",
    "hpa",
    "momentum",
    "trigger_price",
    "spread_points",
    "entry_candidate",
    "sl_candidate",
    "tp_candidate",
}


def parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Session3Error("SOURCE_INVALID", f"{field} must be UTC and end in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise Session3Error("SOURCE_INVALID", f"invalid {field}: {exc}") from exc


def utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("clock values must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _document(value: dict | CanonicalEventV1Document) -> dict:
    if isinstance(value, CanonicalEventV1Document):
        return value.document
    if not isinstance(value, dict):
        raise Session3Error("SOURCE_INVALID", "Canonical Event V1 must be a JSON object")
    return value


def _request_source_event_id(canonical_event_id: str) -> str:
    return "evt_" + canonical_event_id.removeprefix("cevt_")


@dataclass(frozen=True)
class AnalysisAuthority:
    canonical_event: dict
    wire_event: dict
    analysis_adapter: dict[str, Any] | None
    analysis: dict[str, Any] | None
    occurred_at: datetime
    received_at: datetime
    canonicalized_at: datetime
    bar_time: datetime
    expires_at: datetime | None
    adapter_output_hash: str | None

    @property
    def event_id(self) -> str:
        """Frozen Analysis Request-compatible alias for the canonical source."""
        return _request_source_event_id(self.canonical_event["canonical_event_id"])

    @property
    def producer_event_id(self) -> str:
        return self.wire_event["producer_event_id"]

    @property
    def canonical_event_id(self) -> str:
        return self.canonical_event["canonical_event_id"]

    @property
    def canonical_content_hash(self) -> str:
        return self.canonical_event["canonical_content_hash"]

    @property
    def semantic_evidence_hash(self) -> str:
        return self.canonical_event["semantic_evidence_hash"]

    @property
    def raw_content_hash(self) -> str:
        return self.canonical_event["receipt"]["raw_content_hash"]

    @property
    def receipt_id(self) -> str:
        return self.canonical_event["receipt"]["receipt_id"]

    @property
    def immutable_raw_reference(self) -> str:
        return self.canonical_event["audit"]["immutable_raw_reference"]

    @property
    def setup_id(self) -> str:
        return self.canonical_event["setup_id"]

    @property
    def correlation_id(self) -> str:
        return self.canonical_event["correlation_id"]

    def require_compiler_fields(self) -> dict:
        if not isinstance(self.analysis, dict):
            raise Session3Error(
                "COMPILATION_INPUT_MISSING",
                f"{ADAPTER_FAMILY}/{ADAPTER_VERSION} payload.analysis is required",
            )
        missing = sorted(_ANALYSIS_FIELDS - self.analysis.keys())
        if missing:
            raise Session3Error(
                "COMPILATION_INPUT_MISSING",
                "missing versioned adapter payload.analysis fields: " + ", ".join(missing),
            )
        return self.analysis

    def ensure_unexpired(self, now: datetime) -> None:
        if self.expires_at is None:
            raise Session3Error(
                "COMPILATION_INPUT_MISSING",
                "versioned adapter payload.analysis.expires_at is required",
            )
        if now.astimezone(timezone.utc) >= self.expires_at:
            raise Session3Error("SOURCE_EXPIRED", f"source authority expired at {utc_z(self.expires_at)}")

    def ensure_capture_chronology(self, observed_at: datetime) -> None:
        observed_at = observed_at.astimezone(timezone.utc)
        if observed_at < self.canonicalized_at:
            raise Session3Error("SOURCE_INVALID", "capture clock precedes trusted canonicalization")
        if self.bar_time > observed_at:
            raise Session3Error("SOURCE_INVALID", "source bar time is in the future")
        self.ensure_unexpired(observed_at)


def _validate_canonical_lineage(document: dict) -> tuple[dict, dict]:
    try:
        shaped = validate_canonical_event_v1(document).document
    except ContractError as exc:
        raise Session3Error("SOURCE_INVALID", str(exc)) from exc
    wire = shaped["wire_event"]
    content_hash = _sha256(canonical_json_bytes(wire))
    projection = semantic_evidence_projection(wire)
    semantic_hash = _sha256(canonical_json_bytes(projection))
    expected_id = "cevt_" + content_hash.removeprefix("sha256:")
    problems = []
    if shaped["canonical_content_hash"] != content_hash:
        problems.append("canonical_content_hash")
    if shaped["canonical_event_id"] != expected_id:
        problems.append("canonical_event_id")
    if shaped["semantic_evidence_hash"] != semantic_hash:
        problems.append("semantic_evidence_hash")
    if shaped["setup_id"] != projection["setup_id"] or shaped["setup_id"] is None:
        problems.append("setup_id")
    if shaped["correlation_id"] is None:
        problems.append("correlation_id")
    validation = shaped["validation"]
    dedupe = shaped["dedupe"]
    if validation != {
        "status": "ACCEPTED",
        "reason_codes": ["VALIDATED"],
        "state_mutation_allowed": False,
        "dispatch_allowed": True,
    }:
        problems.append("validation")
    if dedupe["exact_receipt_duplicate"] or dedupe["semantic_evidence_duplicate"]:
        problems.append("dedupe")
    if dedupe["prior_canonical_event_ids"]:
        problems.append("prior_canonical_event_ids")
    if shaped["audit"]["receipt_provenance"] != "TRUSTED_INGRESS":
        problems.append("receipt_provenance")
    execution = shaped["execution_profile"]
    if (
        execution["symbol"] != wire["symbol"]
        or execution["base_tf"] != wire["base_tf"]
        or execution["mode"] != wire["mode"]
        or execution["execution_environment"] != wire["execution_environment"]
        or execution["live_execution"] != wire["live_execution"]
    ):
        problems.append("execution_profile")
    if problems:
        raise Session3Error(
            "CANONICAL_LINEAGE_INVALID",
            "canonical lineage mismatch: " + ", ".join(sorted(set(problems))),
        )
    return shaped, wire


def _expected_adapter_source(canonical: dict, wire: dict) -> dict:
    return {
        "canonical_event_id": canonical["canonical_event_id"],
        "canonical_content_hash": canonical["canonical_content_hash"],
        "semantic_evidence_hash": canonical["semantic_evidence_hash"],
        "setup_id": canonical["setup_id"],
        "producer_event_id": wire["producer_event_id"],
        "receipt_id": canonical["receipt"]["receipt_id"],
        "raw_content_hash": canonical["receipt"]["raw_content_hash"],
        "immutable_raw_reference": canonical["audit"]["immutable_raw_reference"],
    }


def bind_disabled_analysis_adapter(canonical_event: dict | CanonicalEventV1Document, adapter_fixture: dict) -> dict:
    """Bind a recorded disabled adapter fixture to one exact canonical/receipt lineage."""
    canonical, wire = _validate_canonical_lineage(_document(canonical_event))
    if not isinstance(adapter_fixture, dict):
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter fixture must be an object")
    adapter = {
        "adapter_family": adapter_fixture.get("adapter_family"),
        "adapter_version": adapter_fixture.get("adapter_version"),
        "runtime_enabled": adapter_fixture.get("runtime_enabled"),
        "status": adapter_fixture.get("status"),
        "source": _expected_adapter_source(canonical, wire),
        "payload": adapter_fixture.get("payload"),
    }
    _validate_analysis_adapter(adapter, canonical, wire)
    return adapter


def _validate_analysis_adapter(adapter: dict, canonical: dict, wire: dict) -> tuple[dict, str]:
    if set(adapter) != _ADAPTER_FIELDS:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter fields do not match the versioned convention")
    if (
        adapter.get("adapter_family") != ADAPTER_FAMILY
        or adapter.get("adapter_version") != ADAPTER_VERSION
        or adapter.get("runtime_enabled") is not False
        or adapter.get("status") != ADAPTER_STATUS
    ):
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter identity/status is not the approved disabled convention")
    source = adapter.get("source")
    if not isinstance(source, dict) or set(source) != _ADAPTER_SOURCE_FIELDS:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter source lineage is incomplete")
    expected_source = _expected_adapter_source(canonical, wire)
    if source != expected_source:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter source lineage differs from Canonical Event V1")
    payload = adapter.get("payload")
    analysis = payload.get("analysis") if isinstance(payload, dict) and set(payload) == {"analysis"} else None
    if not isinstance(analysis, dict):
        raise Session3Error("COMPILATION_INPUT_MISSING", "versioned adapter payload.analysis is required")
    missing = sorted(_ANALYSIS_FIELDS - analysis.keys())
    if missing:
        raise Session3Error("COMPILATION_INPUT_MISSING", "missing payload.analysis fields: " + ", ".join(missing))
    if set(analysis) != _ANALYSIS_FIELDS:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "payload.analysis fields do not match adapter version 1.0")
    instrument = analysis["instrument"]
    if instrument != {"symbol": "XAUUSD", "venue": "ICMARKETS", "point_size": 0.01}:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter instrument must be exact XAUUSD/ICMARKETS/0.01")
    evidence = wire["evidence"]
    snr = evidence["snr"]
    if snr is None or analysis["snr"] != {"low": snr["low"], "high": snr["high"], "type": snr["type"]}:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter SNR differs from canonical evidence")
    if evidence["trigger"] is None or analysis["trigger_price"] != evidence["trigger"]["price"]:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter trigger differs from canonical evidence")
    geometry = evidence["geometry"]
    if geometry is None or any(
        analysis[field] != geometry[source]
        for field, source in (
            ("entry_candidate", "entry"),
            ("sl_candidate", "sl"),
            ("tp_candidate", "tp"),
        )
    ):
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter geometry differs from canonical evidence")
    observed_spread = wire["extensions"].get("observed_spread_points")
    if observed_spread is None or analysis["spread_points"] != observed_spread:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter spread differs from canonical observed spread")
    expected_hpa = [
        f"M{item['timeframe'].removesuffix('m')}_{item['classification']}"
        for item in sorted(evidence["hpa"], key=lambda item: int(item["timeframe"].removesuffix("m")))
    ]
    if analysis["hpa"] != expected_hpa:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter HPA projection differs from canonical evidence")
    bar_time = parse_utc(analysis["bar_time"], "payload.analysis.bar_time")
    trigger_time = parse_utc(evidence["trigger"]["evidence_time"], "wire_event.evidence.trigger.evidence_time")
    if bar_time != trigger_time:
        raise Session3Error("ADAPTER_LINEAGE_INVALID", "adapter bar_time differs from canonical trigger evidence")
    adapter_hash = _sha256(canonical_json_bytes(adapter))
    return analysis, adapter_hash


def validate_analysis_ready(
    canonical_event: dict | CanonicalEventV1Document,
    analysis_adapter: dict | None = None,
    *,
    require_compiler_fields: bool = False,
) -> AnalysisAuthority:
    canonical, wire = _validate_canonical_lineage(_document(canonical_event))
    if wire["event_class"] != "ANALYSIS_READY":
        raise Session3Error("SOURCE_INVALID", "only canonical event_class=ANALYSIS_READY has capture authority")
    if wire["event_type"] not in {"SNR_REJECTION_READY", "SNR_BREAK_READY"}:
        raise Session3Error("SOURCE_INVALID", f"event_type={wire['event_type']} is not Analysis Ready")
    if wire["symbol"] != "XAUUSD":
        raise Session3Error("WRONG_SYMBOL", f"source symbol is {wire['symbol']}")
    if wire["base_tf"] != "1m":
        raise Session3Error("WRONG_TIMEFRAME", f"source base timeframe is {wire['base_tf']}")
    occurred = parse_utc(wire["occurred_at"], "wire_event.occurred_at")
    received = parse_utc(canonical["receipt"]["received_at"], "receipt.received_at")
    canonicalized = parse_utc(canonical["audit"]["canonicalized_at"], "audit.canonicalized_at")
    if received < occurred or canonicalized < received:
        raise Session3Error("CANONICAL_LINEAGE_INVALID", "occurred/received/canonicalized chronology is invalid")
    analysis = None
    adapter_hash = None
    bar_time = occurred
    expires = None
    if analysis_adapter is not None:
        analysis, adapter_hash = _validate_analysis_adapter(analysis_adapter, canonical, wire)
        bar_time = parse_utc(analysis["bar_time"], "payload.analysis.bar_time")
        expires = parse_utc(analysis["expires_at"], "payload.analysis.expires_at")
        if expires <= occurred:
            raise Session3Error("SOURCE_INVALID", "adapter expiry must follow canonical occurred_at")
    authority = AnalysisAuthority(
        canonical,
        wire,
        analysis_adapter,
        analysis,
        occurred,
        received,
        canonicalized,
        bar_time,
        expires,
        adapter_hash,
    )
    if require_compiler_fields:
        authority.require_compiler_fields()
    return authority
