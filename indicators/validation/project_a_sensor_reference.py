"""Deterministic reference model for the Project A Pine alert surface.

This module is a test/fixture utility, not a webhook or execution runtime.  It
mirrors the feature-flagged Pine state machine closely enough to validate event
semantics, stable identifiers, lifecycle continuity, and deduplication against
Session 0's frozen EVENT_SCHEMA_V0_2 contract.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from contracts import canonical_json

Direction = Literal["UP", "DOWN", "FLAT"]
TargetSide = Literal["SUPPORT", "RESISTANCE"]


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or not value.endswith("Z"):
        raise ValueError("timestamps must be ISO 8601 UTC ending in Z")
    return value


def _compact_time(value: str) -> str:
    parsed = datetime.fromisoformat(_utc(value).replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _price_ticks(price: float, point_size: float) -> int:
    return round(price / point_size)


@dataclass(frozen=True)
class Evidence:
    bar_time: str
    created_time: str
    setup_started_at: str
    close: float
    snr_low: float
    snr_high: float
    target_side: TargetSide
    snr_type: str = "CLASSIC"
    structure: str = "RANGE"
    hpa_1m: str = "DISCOUNT"
    hpa_5m: str = "DISCOUNT"
    hpa_15m: str = "MIDDLE"
    hpa_30m: str = "MIDDLE"
    expansion: Direction = "DOWN"
    expansion_class: str = "CLEAN_PUSH"
    momentum_5s: Direction | None = None
    momentum_1m: Direction = "DOWN"
    momentum_5m: Direction = "DOWN"
    momentum_15m: Direction = "FLAT"
    momentum_30m: Direction = "FLAT"
    arrow_5s: Direction | None = None
    reaction: str | None = None
    strong_break: bool = False
    range_middle: bool = False
    valid_snr: bool = True
    valid_hpa: bool = True
    invalidated: bool = False
    expired: bool = False
    venue: str = "ICMARKETS"
    symbol: str = "XAUUSD"
    timeframe: str = "1m"
    point_size: float = 0.01
    lower_timeframe_evidence_time: str | None = None

    def validate(self) -> None:
        for value in (self.bar_time, self.created_time, self.setup_started_at):
            _utc(value)
        if self.lower_timeframe_evidence_time is not None:
            _utc(self.lower_timeframe_evidence_time)
        if self.symbol != "XAUUSD" or self.timeframe != "1m":
            raise ValueError("Project A V1 is pinned to XAUUSD/1m")
        if self.snr_low > self.snr_high:
            raise ValueError("snr_low must be <= snr_high")


class ProjectASensor:
    """Small deterministic state machine matching the Pine event boundary."""

    def __init__(self) -> None:
        self.setup_id: str | None = None
        self.correlation_id: str | None = None
        self.last_event_id: str | None = None
        self.hypothesis: str | None = None
        self.path: str | None = None
        self._last_fingerprint: str | None = None
        self._closed = False

    @staticmethod
    def setup_identity(evidence: Evidence) -> tuple[str, str]:
        side = "S" if evidence.target_side == "SUPPORT" else "R"
        centre = (evidence.snr_low + evidence.snr_high) / 2
        suffix = (
            f"XAUUSD_1m_{_compact_time(evidence.setup_started_at)}_{side}_"
            f"{_price_ticks(centre, evidence.point_size)}"
        )
        return f"setup_{suffix}", f"corr_{suffix}"

    @staticmethod
    def _approaching_target(evidence: Evidence) -> bool:
        wanted = "DOWN" if evidence.target_side == "SUPPORT" else "UP"
        return evidence.expansion == wanted and evidence.expansion_class == "CLEAN_PUSH"

    @staticmethod
    def _continuation_supported(evidence: Evidence) -> bool:
        wanted = "DOWN" if evidence.target_side == "SUPPORT" else "UP"
        slots = (
            evidence.momentum_1m,
            evidence.momentum_5m,
            evidence.momentum_15m,
            evidence.momentum_30m,
        )
        return evidence.expansion == wanted and sum(item == wanted for item in slots) >= 2

    @staticmethod
    def _context_valid(evidence: Evidence) -> bool:
        return evidence.valid_snr and evidence.valid_hpa and not evidence.range_middle

    def observe(self, evidence: Evidence) -> dict[str, Any] | None:
        evidence.validate()
        setup_id, correlation_id = self.setup_identity(evidence)
        if self.setup_id != setup_id:
            self.setup_id = setup_id
            self.correlation_id = correlation_id
            self.last_event_id = None
            self.hypothesis = None
            self.path = None
            self._last_fingerprint = None
            self._closed = False

        if evidence.invalidated and not self._closed:
            self._closed = True
            return self._emit(
                evidence, "LIFECYCLE", "SETUP_INVALIDATED", "STRUCTURAL_BREAK",
                "M1_STRUCTURE_BROKEN", "M1 closed beyond the structural invalidation level.",
                lifecycle_state="INVALIDATED",
            )
        if evidence.expired and not self._closed:
            self._closed = True
            return self._emit(
                evidence, "LIFECYCLE", "SETUP_EXPIRED", "EXPIRED",
                "SETUP_WINDOW_ELAPSED", "The deterministic setup observation window elapsed.",
                lifecycle_state="EXPIRED",
            )
        if self._closed:
            return None

        if self._context_valid(evidence) and evidence.reaction:
            self.hypothesis = "LONG" if evidence.target_side == "SUPPORT" else "SHORT"
            self.path = "SNR_REJECTION"
            return self._emit(
                evidence, "ANALYSIS_READY", "SNR_REJECTION_READY", "ACCEPTED",
                "M1_REACTION_CONFIRMED", "Valid SNR reaction confirmed by a closed M1 bar.",
                trigger=evidence.reaction, lifecycle_state="ANALYSIS_READY",
            )

        if (self._context_valid(evidence) and evidence.strong_break
                and self._continuation_supported(evidence)):
            self.hypothesis = "SHORT" if evidence.target_side == "SUPPORT" else "LONG"
            self.path = "SNR_STRONG_BREAK"
            return self._emit(
                evidence, "ANALYSIS_READY", "SNR_BREAK_READY", "ACCEPTED",
                "M1_STRONG_BREAK_CONFIRMED",
                "M1 closed through the SNR with continuing directional momentum.",
                trigger="STRONG_BREAK", lifecycle_state="ANALYSIS_READY",
            )

        if self._context_valid(evidence) and self._approaching_target(evidence):
            return self._emit(
                evidence, "SETUP_CANDIDATE", "SETUP_CANDIDATE", "ACCEPTED",
                "SNR_APPROACH_VALID",
                "Valid HPA and SNR context with a clean expansion toward the level.",
                lifecycle_state="CANDIDATE",
            )

        event_type = "EXPANSION_UPDATE" if evidence.expansion != "FLAT" else "SNR_UPDATE"
        reason = "RANGE_MIDDLE" if evidence.range_middle else "EVIDENCE_STATE_UPDATED"
        detail = (
            "Range-middle evidence is telemetry only and cannot become Analysis Ready."
            if evidence.range_middle else "Market evidence changed without a make-sense setup."
        )
        return self._emit(
            evidence, "TELEMETRY", event_type, "ACCEPTED", reason, detail,
            lifecycle_state="OBSERVING", setup_optional=True,
        )

    def _payload(
        self,
        evidence: Evidence,
        *,
        trigger: str,
        lifecycle_state: str,
        reason_code: str,
    ) -> dict[str, Any]:
        return {
            "bar_time": evidence.bar_time,
            "created_time": evidence.created_time,
            "hpa": {
                "1m": evidence.hpa_1m,
                "5m": evidence.hpa_5m,
                "15m": evidence.hpa_15m,
                "30m": evidence.hpa_30m,
                "valid": evidence.valid_hpa,
            },
            "lifecycle_state": lifecycle_state,
            "live_execution": False,
            "lower_timeframe_evidence_time": evidence.lower_timeframe_evidence_time,
            "momentum": {
                "5s": evidence.momentum_5s,
                "1m": evidence.momentum_1m,
                "5m": evidence.momentum_5m,
                "15m": evidence.momentum_15m,
                "30m": evidence.momentum_30m,
                "expansion": evidence.expansion_class,
            },
            "reason": reason_code,
            "risk_constraints": {
                "environment": "MT5_DEMO",
                "max_spread_points": 10,
                "mode": "SHADOW",
                "rr": 1.0,
            },
            "snr": {
                "high": evidence.snr_high,
                "low": evidence.snr_low,
                "side": evidence.target_side,
                "type": evidence.snr_type,
                "valid": evidence.valid_snr,
            },
            "structure": evidence.structure,
            "trigger": trigger,
            "trigger_price": evidence.close,
            "optional_5s_arrow": evidence.arrow_5s,
        }

    def _emit(
        self,
        evidence: Evidence,
        event_class: str,
        event_type: str,
        status: str,
        reason_code: str,
        detail: str,
        *,
        trigger: str = "STATE_CHANGE",
        lifecycle_state: str,
        setup_optional: bool = False,
    ) -> dict[str, Any] | None:
        payload = self._payload(
            evidence, trigger=trigger, lifecycle_state=lifecycle_state,
            reason_code=reason_code,
        )
        payload_hash = sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        setup_id = None if setup_optional and event_class == "TELEMETRY" else self.setup_id
        correlation_id = (
            self.correlation_id
            if setup_id is not None
            else f"corr_XAUUSD_1m_{_compact_time(evidence.bar_time)}_{event_type}"
        )
        event_id = f"evt_XAUUSD_1m_{_compact_time(evidence.bar_time)}_{event_type}"
        fingerprint = "|".join(
            (evidence.bar_time, event_type, setup_id or "NONE", payload_hash, status)
        )
        if fingerprint == self._last_fingerprint:
            return None
        self._last_fingerprint = fingerprint
        document = {
            "schema_version": "0.2",
            "event_id": event_id,
            "correlation_id": correlation_id,
            "causation_id": self.last_event_id,
            "occurred_at": evidence.bar_time,
            "received_at": evidence.created_time,
            "source": {
                "producer": "snr-dashboard-project-a-v1",
                "engine": "MASTER_DASHBOARD",
                "provenance": "TRADINGVIEW",
                "payload_hash": f"sha256:{payload_hash}",
                "sensitive_fields_redacted": True,
            },
            "instrument": {
                "symbol": evidence.symbol,
                "venue": evidence.venue,
                "point_size": evidence.point_size,
            },
            "timeframe": evidence.timeframe,
            "event_class": event_class,
            "event_type": event_type,
            "setup_id": setup_id,
            "hypothesis": self.hypothesis if event_class in {"ANALYSIS_READY", "LIFECYCLE"} else None,
            "path": self.path if event_class in {"ANALYSIS_READY", "LIFECYCLE"} else None,
            "disposition": {"status": status, "reason_code": reason_code, "detail": detail},
            "payload": payload,
        }
        self.last_event_id = event_id
        return document


def sample_sequence() -> dict[str, dict[str, Any]]:
    """Return the six deterministic Session 1 promotion candidates."""
    base = Evidence(
        bar_time="2026-07-16T00:00:00Z",
        created_time="2026-07-16T00:00:01Z",
        setup_started_at="2026-07-16T00:01:00Z",
        close=2420.0,
        snr_low=2419.5,
        snr_high=2420.0,
        target_side="SUPPORT",
        expansion="FLAT",
        momentum_1m="FLAT",
        momentum_5m="FLAT",
    )
    telemetry_sensor = ProjectASensor()
    telemetry = telemetry_sensor.observe(base)

    rejection_sensor = ProjectASensor()
    candidate_ev = replace(
        base, bar_time="2026-07-16T00:01:00Z", created_time="2026-07-16T00:01:01Z",
        close=2420.1, expansion="DOWN", momentum_1m="DOWN", momentum_5m="DOWN",
    )
    candidate = rejection_sensor.observe(candidate_ev)
    rejection = rejection_sensor.observe(replace(
        candidate_ev, bar_time="2026-07-16T00:02:00Z", created_time="2026-07-16T00:02:01Z",
        close=2420.3, reaction="SWEEP_RECLAIM", momentum_1m="UP",
        lower_timeframe_evidence_time="2026-07-16T00:01:55Z", arrow_5s=None,
    ))
    invalidated = rejection_sensor.observe(replace(
        candidate_ev, bar_time="2026-07-16T00:03:00Z", created_time="2026-07-16T00:03:01Z",
        close=2419.2, invalidated=True,
    ))

    break_sensor = ProjectASensor()
    break_base = replace(
        base, setup_started_at="2026-07-16T00:04:00Z", target_side="RESISTANCE",
        snr_low=2424.5, snr_high=2425.0, hpa_1m="PREMIUM", hpa_5m="PREMIUM",
        bar_time="2026-07-16T00:04:00Z", created_time="2026-07-16T00:04:01Z",
        close=2424.8, expansion="UP", momentum_1m="UP", momentum_5m="UP",
    )
    break_sensor.observe(break_base)
    strong_break = break_sensor.observe(replace(
        break_base, bar_time="2026-07-16T00:05:00Z", created_time="2026-07-16T00:05:01Z",
        close=2425.4, strong_break=True, arrow_5s=None,
    ))

    expiry_sensor = ProjectASensor()
    expiry_base = replace(
        candidate_ev, setup_started_at="2026-07-16T00:06:00Z",
        bar_time="2026-07-16T00:06:00Z", created_time="2026-07-16T00:06:01Z",
    )
    expiry_sensor.observe(expiry_base)
    expired = expiry_sensor.observe(replace(
        expiry_base, bar_time="2026-07-16T00:36:00Z", created_time="2026-07-16T00:36:01Z",
        expired=True,
    ))

    assert all(item is not None for item in (
        telemetry, candidate, rejection, strong_break, invalidated, expired,
    ))
    return {
        "telemetry": telemetry,
        "setup_candidate": candidate,
        "snr_rejection_ready": rejection,
        "snr_strong_break_ready": strong_break,
        "invalidated_lifecycle": invalidated,
        "expired_lifecycle": expired,
    }
