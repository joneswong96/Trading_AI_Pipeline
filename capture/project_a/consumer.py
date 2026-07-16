"""At-least-once Session 2 handoff interface without database coupling."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from contracts import canonical_json

from .errors import Session3Error
from .input_boundary import parse_utc, utc_z, validate_analysis_ready


@dataclass(frozen=True)
class DispatchEnvelope:
    dispatch_id: str
    canonical_event: dict
    analysis_adapter: dict
    retry_count: int
    requested_at: str

    def validate(self) -> None:
        if not self.dispatch_id or len(self.dispatch_id) > 128:
            raise Session3Error("SOURCE_INVALID", "dispatch_id is required and limited to 128 characters")
        if self.retry_count < 0:
            raise Session3Error("RETRY_SEQUENCE_INVALID", "retry_count cannot be negative")
        parse_utc(self.requested_at, "requested_at")
        validate_analysis_ready(
            self.canonical_event,
            self.analysis_adapter,
            require_compiler_fields=True,
        )


class FileDispatchLedger:
    """Small replace-atomically ledger; Session 2 may provide another implementation."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, dispatch_id: str) -> Path:
        digest = hashlib.sha256(dispatch_id.encode("utf-8")).hexdigest()
        return self.root / f"dispatch_{digest}.json"

    def load(self, dispatch_id: str) -> dict | None:
        path = self._path(dispatch_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def save(self, record: dict) -> None:
        path = self._path(record["dispatch_id"])
        data = (canonical_json(record) + "\n").encode("utf-8")
        temp = path.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()


def consume_dispatch(envelope: DispatchEnvelope, ledger: FileDispatchLedger,
                     handler: Callable[[DispatchEnvelope, str], dict]) -> dict:
    envelope.validate()
    authority = validate_analysis_ready(
        envelope.canonical_event,
        envelope.analysis_adapter,
        require_compiler_fields=True,
    )
    requested_at = parse_utc(envelope.requested_at, "requested_at")
    fingerprint = hashlib.sha256(canonical_json({
        "canonical_event": envelope.canonical_event,
        "analysis_adapter": envelope.analysis_adapter,
    }).encode("utf-8")).hexdigest()
    record = ledger.load(envelope.dispatch_id)
    if record and record["event_sha256"] != fingerprint:
        raise Session3Error("DISPATCH_CONFLICT", "same dispatch_id carried a different canonical event")
    if record and record["status"] == "COMPLETED":
        return {**record["result"], "idempotent": True}
    if record:
        same_retry = next((attempt for attempt in record["attempts"]
                           if attempt["retry_count"] == envelope.retry_count), None)
        if same_retry:
            return {**same_retry["result"], "idempotent": True}
        maximum = max(attempt["retry_count"] for attempt in record["attempts"])
        if envelope.retry_count <= maximum:
            raise Session3Error("RETRY_SEQUENCE_INVALID", "retry_count must increase after a failed attempt")
    else:
        record = {
            "dispatch_id": envelope.dispatch_id,
            "event_sha256": fingerprint,
            "source_event_id": authority.event_id,
            "producer_event_id": authority.producer_event_id,
            "canonical_event_id": authority.canonical_event_id,
            "canonical_content_hash": authority.canonical_content_hash,
            "semantic_evidence_hash": authority.semantic_evidence_hash,
            "receipt_id": authority.receipt_id,
            "raw_content_hash": authority.raw_content_hash,
            "analysis_adapter_hash": authority.adapter_output_hash,
            "setup_id": authority.setup_id,
            "correlation_id": authority.correlation_id,
            "status": "PENDING",
            "attempts": [],
            "result": None,
        }
    seed = canonical_json({
        "dispatch_id": envelope.dispatch_id,
        "event_sha256": fingerprint,
        "retry_count": envelope.retry_count,
        "requested_at": envelope.requested_at,
    }).encode("utf-8")
    attempt_id = "attempt_" + hashlib.sha256(seed).hexdigest()[:32]
    try:
        authority.ensure_unexpired(requested_at)
        result = handler(envelope, attempt_id)
        attempt_result = {
            "status": "COMPLETED",
            "attempt_id": attempt_id,
            "request_id": result["request_id"],
            "bundle_path": result.get("bundle_path"),
            "release_to_session_4": result.get("release_to_session_4", False),
            "error": None,
        }
        record["status"] = "COMPLETED"
        record["result"] = attempt_result
    except Session3Error as exc:
        attempt_result = {
            "status": "FAILED",
            "attempt_id": attempt_id,
            "request_id": None,
            "bundle_path": None,
            "release_to_session_4": False,
            "error": exc.as_dict(),
        }
        record["status"] = "FAILED"
        record["result"] = None
    record["attempts"].append({
        "retry_count": envelope.retry_count,
        "requested_at": utc_z(requested_at),
        "result": attempt_result,
    })
    ledger.save(record)
    return {**attempt_result, "idempotent": False}
