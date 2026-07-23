"""Frozen public contracts for the single Project A capture tool."""
from __future__ import annotations

from typing import Any, Literal
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


TOOL_NAME = "project_a_capture_snapshot"
CAPTURE_PLAN_VERSION = "project_a.capture_plan/1.3"
EXPECTED_ACCOUNT = "Jonesy_Wong"
EXPECTED_SYMBOL = "ICMARKETS:XAUUSD"
CDP_ENDPOINT = "http://127.0.0.1:9333"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LiquidityEventFacts(StrictModel):
    producer_id: Literal["LIQ_V2"]
    producer_revision: Literal["9"]
    event: Literal["LIQ_TOUCH"]
    level_id: str = Field(pattern=r"^liq1_[0-9a-f]{64}$")
    level_version: str = Field(min_length=1, max_length=32)
    side: Literal["ASK", "BID"]
    level_price: str = Field(min_length=1, max_length=64)
    touch_count: StrictInt = Field(ge=1)
    source_bar_time: str = Field(min_length=20, max_length=40)
    symbol: Literal["XAUUSD"]
    feed: Literal["ICMARKETS"]
    anchor_timeframe: Literal["5m"]

    @field_validator("level_price")
    @classmethod
    def validate_level_price(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("level_price must be an exact decimal string") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError("level_price must be finite and positive")
        return value

    @field_validator("source_bar_time")
    @classmethod
    def validate_source_bar_time(cls, value: str) -> str:
        return _rfc3339_utc(value, "source_bar_time")


def _rfc3339_utc(value: str, field: str) -> str:
    if not value.endswith("Z"):
        raise ValueError(f"{field} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be RFC3339 UTC") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


class CaptureToolRequest(StrictModel):
    request_id: str = Field(pattern=r"^job_[0-9a-f]{16,64}$", max_length=68)
    story_id: str = Field(pattern=r"^story_[0-9a-f]{16,64}$", max_length=70)
    analysis_id: str = Field(pattern=r"^analysis_[0-9a-f]{16,64}$", max_length=73)
    stage: Literal["LIQ_BASELINE", "E1_DELTA"]
    capture_scope: Literal["FULL_BASELINE", "BOUNDED_DELTA"]
    canonical_event_id: str = Field(min_length=1, max_length=160)
    event_timestamp: str = Field(min_length=20, max_length=40)
    expected_account: Literal["Jonesy_Wong"]
    expected_symbol: Literal["ICMARKETS:XAUUSD"]
    liquidity_event_facts: LiquidityEventFacts
    required_capture_plan_version: Literal["project_a.capture_plan/1.3"]
    capture_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_timestamp")
    @classmethod
    def validate_event_timestamp(cls, value: str) -> str:
        return _rfc3339_utc(value, "event_timestamp")


class ViewIdentity(StrictModel):
    role: str
    target_id: str
    layout_id: str
    url: str
    account: Literal["Jonesy_Wong"]
    symbol: str
    feed: str
    timeframes: list[str]
    chart_types: list[str]
    indicator_names: list[str]
    observed_at: str
    last_bar_at: str
    status: Literal["COMPLETE"]


class ScreenshotArtifact(StrictModel):
    evidence_id: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/png"]
    width: int = Field(ge=320, le=16384)
    height: int = Field(ge=200, le=16384)
    captured_at: str
    role: str
    target_id: str


class ConstituentStatus(StrictModel):
    constituent_id: str
    kind: Literal["STRUCTURED_READ", "SCREENSHOT"]
    status: Literal["COMPLETED", "UNAVAILABLE"]
    technical_failure_code: str | None = None


class CaptureToolResult(StrictModel):
    status: Literal["COMPLETED"]
    request_id: str
    job_id: str
    story_id: str
    analysis_id: str
    stage: Literal["LIQ_BASELINE", "E1_DELTA"]
    capture_scope: Literal["FULL_BASELINE", "BOUNDED_DELTA"]
    source_event_id: str
    event_timestamp: str
    capture_plan_version: Literal["project_a.capture_plan/1.3"]
    capture_started_at: str
    capture_completed_at: str
    captured_at: str
    account: Literal["Jonesy_Wong"]
    symbol: Literal["XAUUSD"]
    feed: Literal["ICMARKETS"]
    cdp_endpoint: Literal["http://127.0.0.1:9333"]
    evidence_freshness: Literal["FRESH"]
    structured_reads_complete: Literal[True]
    screenshots_complete: Literal[True]
    capture_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_evidence_ids: list[str]
    immutable_evidence_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_id: Literal["tradingview_read_state"]
    script_version: Literal["1.1"]
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    views: list[ViewIdentity]
    screenshot_artifacts: list[ScreenshotArtifact]
    constituent_statuses: list[ConstituentStatus]
    structured_evidence: dict[str, Any]
    technical_failure_code: None = None


CAPTURE_INPUT_SCHEMA = CaptureToolRequest.model_json_schema()
CAPTURE_OUTPUT_SCHEMA = CaptureToolResult.model_json_schema()
