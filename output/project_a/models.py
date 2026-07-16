"""Small deterministic value types shared by Session 5 output modules."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from contracts import canonical_json


class Session5Error(RuntimeError):
    """Fail-closed error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Session5Error("timezone_not_utc", "timestamp must end in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise Session5Error("timestamp_invalid", str(exc)) from exc


def utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise Session5Error("timezone_not_utc", "naive datetime is not allowed")
    value = value.astimezone(timezone.utc)
    rendered = value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return rendered.replace(".000000Z", "Z")


def document_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: str, length: int = 32) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:length]}"


class RendererType(str, Enum):
    TRADINGVIEW = "TRADINGVIEW"
    TELEGRAM = "TELEGRAM"
    NOTION = "NOTION"
    MT5_DEMO = "MT5_DEMO"


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    BLOCKED_SAFETY = "BLOCKED_SAFETY"
    DRY_RUN_SUCCESS = "DRY_RUN_SUCCESS"
    UNCERTAIN = "UNCERTAIN"


COMPLETED_DELIVERY_STATUSES = {"SUCCEEDED", "DRY_RUN_SUCCEEDED"}


@dataclass(frozen=True)
class RendererResult:
    setup_id: str
    thesis_id: str
    delivery_id: str
    attempt_id: str
    status: ResultStatus
    timestamp: str
    dry_run: bool
    external_reference: str | None = None
    error_code: str | None = None
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True)
class DeliveryContext:
    thesis: dict[str, Any]
    request: dict[str, Any]
    verdict: dict[str, Any]
    delivery: dict[str, Any]
    audit_ref: str


def result(
    context: DeliveryContext,
    attempt_id: str,
    status: ResultStatus,
    now: datetime,
    *,
    dry_run: bool = True,
    external_reference: str | None = None,
    error_code: str | None = None,
    detail: dict[str, Any] | None = None,
) -> RendererResult:
    return RendererResult(
        setup_id=context.thesis["setup_id"],
        thesis_id=context.thesis["thesis_id"],
        delivery_id=context.delivery["delivery_id"],
        attempt_id=attempt_id,
        status=status,
        timestamp=utc_z(now),
        dry_run=dry_run,
        external_reference=external_reference,
        error_code=error_code,
        detail=detail,
    )
