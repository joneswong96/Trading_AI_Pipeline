"""Deterministic structural and semantic validation for frozen contracts."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .registry import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    EVENT_SCHEMA_V0_2,
    THESIS_SCHEMA_V1,
    schema_path,
)

MAX_DOCUMENT_BYTES = 262_144
_SENSITIVE_KEYS = {"api_key", "apikey", "password", "secret", "token", "private_key"}


@dataclass(frozen=True)
class ContractError(ValueError):
    code: str
    message: str
    path: str = "$"

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


@lru_cache(maxsize=None)
def _schema(contract: str) -> dict:
    return json.loads(schema_path(contract).read_text(encoding="utf-8"))


def canonical_json(document: dict) -> str:
    """UTF-8-safe RFC-8259 JSON with sorted keys and no insignificant space."""
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def validate_contract(contract: str, document: dict) -> dict:
    """Return the original document or fail closed with a stable reason code."""
    if not isinstance(document, dict):
        raise ContractError("document_type", "document must be a JSON object")
    try:
        encoded = canonical_json(document).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("serialization", str(exc)) from exc
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ContractError("document_too_large", f"maximum is {MAX_DOCUMENT_BYTES} bytes")

    errors = sorted(
        Draft202012Validator(_schema(contract), format_checker=FormatChecker()).iter_errors(document),
        key=lambda e: (list(e.absolute_path), e.validator or ""),
    )
    if errors:
        err = errors[0]
        path = "$" + "".join(f"[{item!r}]" for item in err.absolute_path)
        raise ContractError(f"schema_{err.validator}", err.message, path)

    _reject_sensitive_values(document)
    if contract == EVENT_SCHEMA_V0_2:
        _validate_event(document)
    elif contract == ANALYSIS_REQUEST_SCHEMA_V1:
        _validate_request(document)
    elif contract == AI_VERDICT_SCHEMA_V1:
        _validate_verdict(document)
    elif contract == THESIS_SCHEMA_V1:
        _validate_thesis(document)
    else:
        raise ContractError("unsupported_contract", contract)
    return document


def _utc(value: str, field: str) -> datetime:
    if not value.endswith("Z"):
        raise ContractError("timezone_not_utc", "timestamp must end in Z", f"$.{field}")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ContractError("timestamp_invalid", str(exc), f"$.{field}") from exc


def _validate_event(doc: dict) -> None:
    occurred = _utc(doc["occurred_at"], "occurred_at")
    received = _utc(doc["received_at"], "received_at")
    if received < occurred:
        raise ContractError("received_before_occurred", "received_at precedes occurred_at")
    if doc["event_class"] == "ANALYSIS_READY":
        for field in ("setup_id", "hypothesis", "path"):
            if doc.get(field) is None:
                raise ContractError(f"analysis_ready_{field}_required", f"{field} is required")
    if doc["disposition"]["status"] == "ACCEPTED" and doc["event_class"] == "LIFECYCLE":
        raise ContractError("lifecycle_disposition", "lifecycle events cannot be ACCEPTED alerts")


def _validate_request(doc: dict) -> None:
    created = _utc(doc["created_at"], "created_at")
    expires = _utc(doc["expires_at"], "expires_at")
    if expires <= created:
        raise ContractError("request_not_future", "expires_at must follow created_at")
    if doc["snr"]["low"] > doc["snr"]["high"]:
        raise ContractError("snr_bounds", "snr.low must be <= snr.high")
    if doc["spread_points"] > doc["risk"]["max_spread_points"]:
        raise ContractError("spread_gate", "spread exceeds the pinned maximum")
    _validate_trade_geometry(doc["hypothesis"], doc["entry_candidate"],
                             doc["sl_candidate"], doc["tp_candidate"])


def _validate_verdict(doc: dict) -> None:
    _utc(doc["generated_at"], "generated_at")
    if doc.get("valid_until") is not None:
        _utc(doc["valid_until"], "valid_until")
    if doc["verdict"] in {"APPROVE", "MODIFY"}:
        if not all(doc["hard_gates"].values()):
            raise ContractError("hard_gate_failed", "actionable verdict requires every hard gate")
        _validate_trade_geometry(doc["hypothesis"], doc["entry"], doc["sl"], doc["tp"])
        if doc["valid_until"] is None:
            raise ContractError("valid_until_required", "actionable verdict requires valid_until")
    elif any(doc.get(key) is not None for key in ("entry", "sl", "tp")):
        raise ContractError("non_actionable_prices", "REJECT/EXPIRED must not contain order prices")


def _validate_thesis(doc: dict) -> None:
    _utc(doc["created_at"], "created_at")
    if doc.get("valid_until") is not None:
        _utc(doc["valid_until"], "valid_until")
    actionable = doc["decision"] in {"APPROVE", "MODIFY"}
    if actionable:
        if doc["state"] not in {"ARMED", "IN_TRADE"}:
            raise ContractError("thesis_state", "actionable thesis must be ARMED or IN_TRADE")
        _validate_trade_geometry(doc["direction"], doc["entry"], doc["sl"], doc["tp"])
        if doc["valid_until"] is None:
            raise ContractError("valid_until_required", "actionable thesis requires valid_until")
    elif any(doc.get(key) is not None for key in ("entry", "sl", "tp")):
        raise ContractError("non_actionable_prices", "non-actionable thesis must not contain prices")


def _validate_trade_geometry(direction: str, entry: Any, sl: Any, tp: Any) -> None:
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (entry, sl, tp)):
        raise ContractError("trade_prices_required", "entry, sl, and tp must be finite numbers")
    if direction == "LONG" and not (sl < entry < tp):
        raise ContractError("trade_geometry", "LONG requires sl < entry < tp")
    if direction == "SHORT" and not (tp < entry < sl):
        raise ContractError("trade_geometry", "SHORT requires tp < entry < sl")
    if not math.isclose(abs(tp - entry), abs(entry - sl), abs_tol=1e-9):
        raise ContractError("rr_not_one_to_one", "TP distance must equal SL distance")


def _reject_sensitive_values(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}"
            if key.lower() in _SENSITIVE_KEYS and child not in (None, "", "REDACTED"):
                raise ContractError("sensitive_value", "secret-like value must be omitted or REDACTED",
                                    key_path)
            _reject_sensitive_values(child, key_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_values(child, f"{path}[{index}]")
