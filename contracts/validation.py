"""Deterministic structural and semantic validation for frozen contracts."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Mapping

from referencing import Registry, Resource

from jsonschema import Draft202012Validator, FormatChecker

from .registry import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    EVENT_SCHEMA_V0_2,
    PROJECT_A_CANONICAL_EVENT_V1,
    PROJECT_A_WIRE_EVENT_V1,
    SCHEMA_FILES,
    THESIS_SCHEMA_V1,
    schema_path,
)

MAX_DOCUMENT_BYTES = 262_144
MAX_CANONICAL_SIGNIFICANT_DIGITS = 64
MAX_CANONICAL_ABS_EXPONENT = 10_000
MAX_CANONICAL_NUMBER_CHARS = 2_048
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


def canonical_json(document: Any) -> str:
    """Return Project A deterministic JSON (deliberately not RFC 8785).

    Object keys are Unicode-code-point sorted, strings are UTF-8/JSON escaped
    without NFC normalization, arrays retain order, and all finite numeric
    values use a normalized base-10 representation.  ``1``, ``1.0``, ``1e0``
    and negative zero therefore serialize identically.  Binary floats first
    pass through their stable shortest decimal spelling; trusted Wire V1 byte
    parsing uses :class:`Decimal` directly.
    """

    def render(value: Any) -> str:
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, int):
            if value and abs(value).bit_length() > 220:
                raise ContractError(
                    "canonical_number_significant_digits",
                    f"maximum is {MAX_CANONICAL_SIGNIFICANT_DIGITS}",
                )
            rendered = str(value)
            if len(rendered.removeprefix("-")) > MAX_CANONICAL_SIGNIFICANT_DIGITS:
                raise ContractError(
                    "canonical_number_significant_digits",
                    f"maximum is {MAX_CANONICAL_SIGNIFICANT_DIGITS}",
                )
            return rendered
        if isinstance(value, (float, Decimal)):
            decimal = Decimal(str(value)) if isinstance(value, float) else value
            if not decimal.is_finite():
                raise ContractError("non_finite_number", "number must be finite")
            if decimal.is_zero():
                return "0"
            sign, digits, exponent = decimal.as_tuple()
            if len(digits) > MAX_CANONICAL_SIGNIFICANT_DIGITS:
                raise ContractError(
                    "canonical_number_significant_digits",
                    f"maximum is {MAX_CANONICAL_SIGNIFICANT_DIGITS}",
                )
            adjusted = exponent + len(digits) - 1
            if abs(exponent) > MAX_CANONICAL_ABS_EXPONENT or abs(adjusted) > MAX_CANONICAL_ABS_EXPONENT:
                raise ContractError(
                    "canonical_number_exponent",
                    f"absolute exponent/adjusted exponent maximum is {MAX_CANONICAL_ABS_EXPONENT}",
                )
            if adjusted >= 0 and exponent < 0:
                estimated_length = sign + adjusted + 1 + 1 + (-exponent)
            elif adjusted >= 0:
                estimated_length = sign + adjusted + 1
            else:
                estimated_length = sign + 2 + (-adjusted - 1) + len(digits)
            if estimated_length > MAX_CANONICAL_NUMBER_CHARS:
                raise ContractError(
                    "canonical_number_rendered_length",
                    f"maximum is {MAX_CANONICAL_NUMBER_CHARS} characters",
                )
            # Decimal.normalize() applies the ambient decimal context and can
            # silently round values with more than its default 28 digits.
            # Fixed formatting is exact and is safe after the bounds above.
            rendered = format(decimal, "f")
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
            if len(rendered) > MAX_CANONICAL_NUMBER_CHARS:
                raise ContractError(
                    "canonical_number_rendered_length",
                    f"maximum is {MAX_CANONICAL_NUMBER_CHARS} characters",
                )
            return rendered
        if isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise TypeError("JSON object keys must be strings")
            return "{" + ",".join(
                f"{render(key)}:{render(value[key])}" for key in sorted(value)
            ) + "}"
        if isinstance(value, (list, tuple)):
            return "[" + ",".join(render(item) for item in value) + "]"
        raise TypeError(f"unsupported JSON value: {type(value).__name__}")

    return render(document)


def canonical_json_bytes(document: Any) -> bytes:
    """Return the one canonical JSON representation encoded as exact UTF-8 bytes."""
    return canonical_json(document).encode("utf-8")


@lru_cache(maxsize=1)
def _schema_registry() -> Registry:
    resources = []
    for path in SCHEMA_FILES.values():
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate_contract(contract: str, document: dict) -> dict:
    """Return the original document or fail closed with a stable reason code."""
    if not isinstance(document, dict):
        raise ContractError("document_type", "document must be a JSON object")
    try:
        encoded = canonical_json_bytes(document)
    except ContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise ContractError("serialization", str(exc)) from exc
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ContractError("document_too_large", f"maximum is {MAX_DOCUMENT_BYTES} bytes")

    errors = sorted(
        Draft202012Validator(
            _schema(contract),
            format_checker=FormatChecker(),
            registry=_schema_registry(),
        ).iter_errors(document),
        key=lambda e: (list(e.absolute_path), e.validator or ""),
    )
    if errors:
        err = errors[0]
        path = "$" + "".join(f"[{item!r}]" for item in err.absolute_path)
        raise ContractError(f"schema_{err.validator}", err.message, path)

    _reject_sensitive_values(document)
    if contract == EVENT_SCHEMA_V0_2:
        _validate_event(document)
    elif contract in {PROJECT_A_WIRE_EVENT_V1, PROJECT_A_CANONICAL_EVENT_V1}:
        # Family-specific semantic validation lives in contracts.event_v1 to
        # keep the frozen Event 0.2 path unchanged and independently callable.
        pass
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
