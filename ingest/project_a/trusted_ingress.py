"""Production receipt-context issuance owned by the Session 2 ingress boundary."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from contracts._trusted_ingress import _TrustedReceiptContextV1
from contracts.validation import MAX_DOCUMENT_BYTES, ContractError

_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$")
_RECEIPT_ID = re.compile(r"^rcpt_[A-Za-z0-9._:-]{8,120}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,119}$")


def _utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ContractError("timestamp_not_rfc3339_utc", "expected strict UTC RFC 3339", field)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ContractError("timestamp_invalid", str(exc), field) from exc


def issue_production_receipt_context(
    raw_bytes: bytes,
    *,
    receipt_id: str,
    received_at: str,
    transport_identity: str,
    source_adapter_identity: str,
    immutable_raw_reference: str,
    canonicalized_at: str,
    transport_attempt_id: str,
) -> _TrustedReceiptContextV1:
    """Issue production trust only after the exact bytes have durable storage."""
    if not isinstance(raw_bytes, bytes):
        raise ContractError("raw_bytes_required", "production receipt requires exact bytes")
    if len(raw_bytes) > MAX_DOCUMENT_BYTES:
        raise ContractError("raw_document_too_large", f"maximum is {MAX_DOCUMENT_BYTES} bytes")
    if not _RECEIPT_ID.fullmatch(receipt_id):
        raise ContractError("trusted_receipt_id", "invalid receipt_id")
    for name, value in {
        "transport_identity": transport_identity,
        "source_adapter_identity": source_adapter_identity,
        "immutable_raw_reference": immutable_raw_reference,
        "transport_attempt_id": transport_attempt_id,
    }.items():
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ContractError("trusted_receipt_identity", f"invalid {name}")
    received = _utc(received_at, "$.trusted_receipt.received_at")
    canonicalized = _utc(canonicalized_at, "$.trusted_receipt.canonicalized_at")
    if canonicalized < received:
        raise ContractError(
            "canonicalized_before_received", "canonicalized_at precedes received_at"
        )
    return _TrustedReceiptContextV1(
        receipt_id=receipt_id,
        received_at=received_at,
        transport_identity=transport_identity,
        source_adapter_identity=source_adapter_identity,
        receipt_provenance="TRUSTED_INGRESS",
        raw_content_hash="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        immutable_raw_reference=immutable_raw_reference,
        canonicalized_at=canonicalized_at,
        replay_clock=None,  # Production uses the actual receipt clock, never a replay clock.
        transport_attempt_id=transport_attempt_id,
        context_kind="PRODUCTION",
    )


__all__ = ["issue_production_receipt_context"]
