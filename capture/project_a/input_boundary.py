"""Narrow validated Analysis Ready event boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from contracts import EVENT_SCHEMA_V0_2, ContractError, validate_contract

from .errors import Session3Error


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


@dataclass(frozen=True)
class AnalysisAuthority:
    event: dict
    analysis: dict[str, Any] | None
    occurred_at: datetime
    bar_time: datetime
    expires_at: datetime | None

    @property
    def event_id(self) -> str:
        return self.event["event_id"]

    @property
    def setup_id(self) -> str:
        return self.event["setup_id"]

    @property
    def correlation_id(self) -> str:
        return self.event["correlation_id"]

    def require_compiler_fields(self) -> dict:
        if not isinstance(self.analysis, dict):
            raise Session3Error("COMPILATION_INPUT_MISSING", "payload.analysis is required")
        required = {
            "expires_at", "bar_time", "session", "snr", "hpa", "momentum",
            "trigger_price", "spread_points", "entry_candidate", "sl_candidate",
            "tp_candidate", "source_event_ids",
        }
        missing = sorted(required - self.analysis.keys())
        if missing:
            raise Session3Error("COMPILATION_INPUT_MISSING", "missing payload.analysis fields: " + ", ".join(missing))
        return self.analysis

    def ensure_unexpired(self, now: datetime) -> None:
        if self.expires_at is None:
            raise Session3Error("COMPILATION_INPUT_MISSING", "payload.analysis.expires_at is required")
        if now.astimezone(timezone.utc) >= self.expires_at:
            raise Session3Error("SOURCE_EXPIRED", f"source authority expired at {utc_z(self.expires_at)}")


def validate_analysis_ready(event: dict, *, require_compiler_fields: bool = False) -> AnalysisAuthority:
    try:
        validate_contract(EVENT_SCHEMA_V0_2, event)
    except ContractError as exc:
        raise Session3Error("SOURCE_INVALID", str(exc)) from exc
    if event["event_class"] != "ANALYSIS_READY":
        raise Session3Error("SOURCE_INVALID", "only event_class=ANALYSIS_READY has capture authority")
    if event["event_type"] not in {"SNR_REJECTION_READY", "SNR_BREAK_READY"}:
        raise Session3Error("SOURCE_INVALID", f"event_type={event['event_type']} is not Analysis Ready")
    if event["disposition"]["status"] != "ACCEPTED":
        raise Session3Error("SOURCE_INVALID", "capture authority requires disposition.status=ACCEPTED")
    if event["instrument"]["symbol"] != "XAUUSD":
        raise Session3Error("WRONG_SYMBOL", f"source symbol is {event['instrument']['symbol']}")
    if event["timeframe"] != "1m":
        raise Session3Error("WRONG_TIMEFRAME", f"source base timeframe is {event['timeframe']}")
    occurred = parse_utc(event["occurred_at"], "occurred_at")
    analysis = event.get("payload", {}).get("analysis")
    bar_time = occurred
    expires = None
    if isinstance(analysis, dict):
        if "bar_time" in analysis:
            bar_time = parse_utc(analysis["bar_time"], "payload.analysis.bar_time")
        if "expires_at" in analysis:
            expires = parse_utc(analysis["expires_at"], "payload.analysis.expires_at")
            if expires <= occurred:
                raise Session3Error("SOURCE_INVALID", "source expiry must follow occurred_at")
    authority = AnalysisAuthority(event, analysis, occurred, bar_time, expires)
    if require_compiler_fields:
        authority.require_compiler_fields()
    return authority
