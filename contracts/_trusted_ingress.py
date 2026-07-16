"""Internal replay-only receipt issuance for the reader foundation.

This module is intentionally absent from ``contracts.__init__``.  It is not a
security sandbox: same-process Python code can inspect it.  Safety therefore
depends on point-of-use verification against exact bytes and a current committed
dedupe transaction, never on possession of this context object.

No production ingress issuer exists until a separately accepted Session 2
adapter supplies immutable storage and a durable dedupe implementation.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .validation import MAX_DOCUMENT_BYTES, ContractError

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


@dataclass(frozen=True, slots=True)
class _TrustedReceiptContextV1:
    receipt_id: str
    received_at: str
    transport_identity: str
    source_adapter_identity: str
    receipt_provenance: str
    raw_content_hash: str
    immutable_raw_reference: str
    canonicalized_at: str
    replay_clock: str
    transport_attempt_id: str | None
    context_kind: str = "REPLAY_ONLY"


def issue_replay_receipt_context(
    raw_bytes: bytes,
    *,
    receipt_id: str,
    received_at: str,
    transport_identity: str,
    source_adapter_identity: str,
    immutable_raw_reference: str,
    canonicalized_at: str,
    replay_clock: str,
    transport_attempt_id: str | None = None,
) -> _TrustedReceiptContextV1:
    """Bind exact replay bytes before decode; this cannot issue production trust."""
    if not isinstance(raw_bytes, bytes):
        raise ContractError("raw_bytes_required", "replay receipt requires exact bytes")
    if len(raw_bytes) > MAX_DOCUMENT_BYTES:
        raise ContractError("raw_document_too_large", f"maximum is {MAX_DOCUMENT_BYTES} bytes")
    raw_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    if not _RECEIPT_ID.fullmatch(receipt_id):
        raise ContractError("trusted_receipt_id", "invalid receipt_id")
    for name, value in {
        "transport_identity": transport_identity,
        "source_adapter_identity": source_adapter_identity,
        "immutable_raw_reference": immutable_raw_reference,
    }.items():
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ContractError("trusted_receipt_identity", f"invalid {name}")
    received = _utc(received_at, "$.trusted_receipt.received_at")
    canonicalized = _utc(canonicalized_at, "$.trusted_receipt.canonicalized_at")
    if canonicalized < received:
        raise ContractError("canonicalized_before_received", "canonicalized_at precedes received_at")
    _utc(replay_clock, "$.trusted_receipt.replay_clock")
    if transport_attempt_id is not None and not _SAFE_ID.fullmatch(transport_attempt_id):
        raise ContractError("trusted_receipt_identity", "invalid transport_attempt_id")
    return _TrustedReceiptContextV1(
        receipt_id=receipt_id,
        received_at=received_at,
        transport_identity=transport_identity,
        source_adapter_identity=source_adapter_identity,
        receipt_provenance="TRUSTED_INGRESS",
        raw_content_hash=raw_hash,
        immutable_raw_reference=immutable_raw_reference,
        canonicalized_at=canonicalized_at,
        replay_clock=replay_clock,
        transport_attempt_id=transport_attempt_id,
    )


__all__: list[str] = []
