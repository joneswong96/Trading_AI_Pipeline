"""Strict telemetry-only bridge from raw Project A Pine JSON to Section 2.

The bridge owns no market interpretation.  It reuses the accepted numeric-state
and offline Section-2 compilers, persists exact receipt bytes in the existing
Project A database, and exposes no provider, writer, broker, or order action.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from project_a.numeric_state import (
    EXPANSION_EVENT_SCHEMA,
    LIQUIDITY_EVENT_SCHEMA,
    RENKO_EVENT_SCHEMA,
    RAW_PRODUCER_ALLOWLIST,
    NumericStateError,
    canonical_json_bytes,
    parse_numeric_event,
)
from project_a.section2_pipeline import OfflineSection2Pipeline, Section2PipelineError

from .config import ProjectAConfig
from .database import ProjectADatabase


Clock = Callable[[], datetime]
RAW_ADAPTER_SCHEMA_VERSION = 1
APPROVED_SCHEMAS = frozenset((
    LIQUIDITY_EVENT_SCHEMA,
    EXPANSION_EVENT_SCHEMA,
    RENKO_EVENT_SCHEMA,
))
APPROVED_PRODUCERS = frozenset(producer for _, producer in RAW_PRODUCER_ALLOWLIST)


RAW_ADAPTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_a_producer_adapter_meta (
  version INTEGER PRIMARY KEY,
  checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_a_producer_receipts (
  ingest_id TEXT PRIMARY KEY,
  raw_body BLOB NOT NULL,
  raw_sha256 TEXT NOT NULL,
  body_bytes INTEGER NOT NULL,
  received_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACCEPTED','DUPLICATE','REJECTED','CONFLICT')),
  schema_name TEXT,
  producer_id TEXT,
  producer_revision TEXT,
  event_name TEXT,
  canonical_event_id TEXT,
  error_code TEXT,
  detail TEXT,
  project_a_raw_producer INTEGER NOT NULL CHECK(project_a_raw_producer=1),
  legacy_wake_eligible INTEGER NOT NULL CHECK(legacy_wake_eligible=0),
  provider_eligible INTEGER NOT NULL CHECK(provider_eligible=0),
  writer_eligible INTEGER NOT NULL CHECK(writer_eligible=0),
  order_eligible INTEGER NOT NULL CHECK(order_eligible=0)
);
CREATE INDEX IF NOT EXISTS project_a_producer_receipts_hash_idx
  ON project_a_producer_receipts(raw_sha256);
CREATE TRIGGER IF NOT EXISTS project_a_producer_receipts_no_update
  BEFORE UPDATE ON project_a_producer_receipts
  BEGIN SELECT RAISE(ABORT, 'project_a_producer_receipts is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_producer_receipts_no_delete
  BEFORE DELETE ON project_a_producer_receipts
  BEGIN SELECT RAISE(ABORT, 'project_a_producer_receipts is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_producer_events (
  canonical_event_id TEXT PRIMARY KEY,
  first_ingest_id TEXT NOT NULL UNIQUE REFERENCES project_a_producer_receipts(ingest_id),
  schema_name TEXT NOT NULL,
  producer_id TEXT NOT NULL,
  producer_revision TEXT NOT NULL,
  producer_event_id TEXT NOT NULL,
  canonical_payload_sha256 TEXT NOT NULL,
  canonical_json TEXT NOT NULL,
  source_bar_time TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(producer_id, producer_revision, producer_event_id)
);
CREATE INDEX IF NOT EXISTS project_a_producer_events_time_idx
  ON project_a_producer_events(source_bar_time, canonical_event_id);
CREATE TRIGGER IF NOT EXISTS project_a_producer_events_no_update
  BEFORE UPDATE ON project_a_producer_events
  BEGIN SELECT RAISE(ABORT, 'project_a_producer_events is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_producer_events_no_delete
  BEFORE DELETE ON project_a_producer_events
  BEGIN SELECT RAISE(ABORT, 'project_a_producer_events is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_producer_state_history (
  state_version INTEGER PRIMARY KEY AUTOINCREMENT,
  ingest_id TEXT NOT NULL UNIQUE REFERENCES project_a_producer_receipts(ingest_id),
  canonical_event_id TEXT NOT NULL REFERENCES project_a_producer_events(canonical_event_id),
  recorded_at TEXT NOT NULL,
  state_snapshot_json TEXT NOT NULL,
  state_snapshot_sha256 TEXT NOT NULL,
  compiler_state TEXT NOT NULL,
  compiler_sha256 TEXT NOT NULL,
  evidence_bundle_sha256 TEXT NOT NULL,
  telemetry_status TEXT NOT NULL,
  correlation_status TEXT NOT NULL,
  full_capture_requested INTEGER NOT NULL CHECK(full_capture_requested=0),
  provider_called INTEGER NOT NULL CHECK(provider_called=0),
  writer_called INTEGER NOT NULL CHECK(writer_called=0),
  order_placed INTEGER NOT NULL CHECK(order_placed=0)
);
CREATE TRIGGER IF NOT EXISTS project_a_producer_state_no_update
  BEFORE UPDATE ON project_a_producer_state_history
  BEGIN SELECT RAISE(ABORT, 'project_a_producer_state_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_producer_state_no_delete
  BEFORE DELETE ON project_a_producer_state_history
  BEGIN SELECT RAISE(ABORT, 'project_a_producer_state_history is append-only'); END;
"""
RAW_ADAPTER_SCHEMA_CHECKSUM = "sha256:" + hashlib.sha256(
    RAW_ADAPTER_SCHEMA.encode("utf-8")
).hexdigest()


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _PairsObject(dict):
    def __init__(self, pairs: list[tuple[str, Any]]):
        super().__init__(pairs)
        self.pairs = tuple(pairs)


@dataclass(frozen=True)
class RawProducerDetection:
    candidate: bool
    schema: str | None = None
    producer: str | None = None
    revision: str | None = None
    event: str | None = None
    duplicate_keys: bool = False


def _contains_duplicate_keys(value: Any) -> bool:
    if isinstance(value, _PairsObject):
        keys = [key for key, _ in value.pairs]
        return len(keys) != len(set(keys)) or any(
            _contains_duplicate_keys(item) for _, item in value.pairs
        )
    if isinstance(value, list):
        return any(_contains_duplicate_keys(item) for item in value)
    return False


def detect_raw_producer(raw: bytes) -> RawProducerDetection:
    """Detect only exact allowlisted schema/producer identities.

    Duplicate top-level keys are retained for detection and rejected later by
    ``parse_numeric_event``; detection never relies on substring matching.
    """

    try:
        document = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_PairsObject,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return RawProducerDetection(False)
    if not isinstance(document, _PairsObject):
        return RawProducerDetection(False)
    schema_values = [value for key, value in document.pairs if key == "schema"]
    producer_values = [value for key, value in document.pairs if key == "producer_id"]
    candidate = any(value in APPROVED_SCHEMAS for value in schema_values) or any(
        value in APPROVED_PRODUCERS for value in producer_values
    )
    if not candidate:
        return RawProducerDetection(False)
    schema = document.get("schema")
    producer = document.get("producer_id")
    revision = document.get("producer_revision")
    event = document.get("event")
    return RawProducerDetection(
        True,
        schema if isinstance(schema, str) else None,
        producer if isinstance(producer, str) else None,
        str(revision) if isinstance(revision, (str, int)) and not isinstance(revision, bool) else None,
        event if isinstance(event, str) else None,
        _contains_duplicate_keys(document),
    )


@dataclass(frozen=True)
class RawProducerResult:
    http_status: int
    accepted: bool
    deduped: bool
    producer: str | None
    event: str | None
    telemetry_status: str
    state_status: str
    error_code: str | None = None

    def response(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": self.http_status < 400,
            "accepted": self.accepted,
            "deduped": self.deduped,
            "producer": self.producer,
            "event": self.event,
            "telemetry_status": self.telemetry_status,
            "state_status": self.state_status,
            "wake": False,
            "provider_called": False,
            "writer_called": False,
            "order_placed": False,
        }
        if self.error_code is not None:
            body["error_code"] = self.error_code
        return body


class _NoExternalRequestAdapter:
    def compile_requests(self, _sources: Mapping[str, Any], _level: Any) -> tuple[Any, ...]:
        return ()


class _NoScreenshotRequestAdapter:
    def compile_requests(self, _sources: Mapping[str, Any], _level: Any) -> tuple[Any, ...]:
        return ()


class ProjectARawProducerStore:
    """Append-only raw receipts plus deterministic Section-2 state snapshots."""

    def __init__(self, path: str | Path, *, applied_at: str):
        self.database = ProjectADatabase(path)
        self.database.migrate(applied_at)
        conn = self.database.connect()
        try:
            conn.executescript("BEGIN IMMEDIATE;\n" + RAW_ADAPTER_SCHEMA + "\nCOMMIT;")
            conn.execute(
                "INSERT OR IGNORE INTO project_a_producer_adapter_meta(version,checksum) VALUES (?,?)",
                (RAW_ADAPTER_SCHEMA_VERSION, RAW_ADAPTER_SCHEMA_CHECKSUM),
            )
            rows = conn.execute(
                "SELECT version,checksum FROM project_a_producer_adapter_meta ORDER BY version"
            ).fetchall()
            if [(row["version"], row["checksum"]) for row in rows] != [
                (RAW_ADAPTER_SCHEMA_VERSION, RAW_ADAPTER_SCHEMA_CHECKSUM)
            ]:
                raise RuntimeError("raw producer adapter schema mismatch")
        finally:
            conn.close()

    @staticmethod
    def _receipt_values(
        *, ingest_id: str, raw: bytes, received_at: str, status: str,
        detection: RawProducerDetection, canonical_event_id: str | None,
        error_code: str | None, detail: str | None,
    ) -> tuple[Any, ...]:
        return (
            ingest_id, sqlite3.Binary(raw), hashlib.sha256(raw).hexdigest(), len(raw), received_at,
            status, detection.schema, detection.producer, detection.revision, detection.event,
            canonical_event_id, error_code, None if detail is None else detail[:240],
            1, 0, 0, 0, 0,
        )

    @staticmethod
    def _insert_receipt(conn: sqlite3.Connection, values: tuple[Any, ...]) -> None:
        conn.execute(
            "INSERT INTO project_a_producer_receipts("
            "ingest_id,raw_body,raw_sha256,body_bytes,received_at,status,schema_name,producer_id,"
            "producer_revision,event_name,canonical_event_id,error_code,detail,"
            "project_a_raw_producer,legacy_wake_eligible,provider_eligible,writer_eligible,order_eligible"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )

    def existing_receipt(self, ingest_id: str) -> sqlite3.Row | None:
        conn = self.database.connect()
        try:
            return conn.execute(
                "SELECT * FROM project_a_producer_receipts WHERE ingest_id=?", (ingest_id,)
            ).fetchone()
        finally:
            conn.close()

    def record_rejection(
        self, *, ingest_id: str, raw: bytes, received_at: str,
        detection: RawProducerDetection, error_code: str, detail: str, conflict: bool = False,
    ) -> None:
        values = self._receipt_values(
            ingest_id=ingest_id, raw=raw, received_at=received_at,
            status="CONFLICT" if conflict else "REJECTED", detection=detection,
            canonical_event_id=None, error_code=error_code, detail=detail,
        )
        with self.database.transaction(immediate=True) as conn:
            if conn.execute(
                "SELECT 1 FROM project_a_producer_receipts WHERE ingest_id=?", (ingest_id,)
            ).fetchone() is None:
                self._insert_receipt(conn, values)


class ProjectARawProducerAdapter:
    def __init__(self, config: ProjectAConfig, *, clock: Clock | None = None):
        config.assert_safe()
        self.config = config
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = ProjectARawProducerStore(
            config.database_path, applied_at=_iso(self.clock()),
        )

    @staticmethod
    def _ingest_id(raw: bytes) -> str:
        return "pa_raw_" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _result_from_receipt(row: sqlite3.Row) -> RawProducerResult:
        status = row["status"]
        http = 409 if status == "CONFLICT" else 422 if status == "REJECTED" else 200
        return RawProducerResult(
            http, status in {"ACCEPTED", "DUPLICATE"}, True,
            row["producer_id"], row["event_name"],
            "DUPLICATE" if status in {"ACCEPTED", "DUPLICATE"} else status,
            "UNCHANGED", row["error_code"],
        )

    @staticmethod
    def _missing_freshness() -> dict[str, str]:
        return {
            key: "MISSING" for key in (
                "xau", "atr_5m", "liquidity", "macd_1m", "macd_5m",
                "renko", "renko_fire", "dxy_15m", "htf_context",
            )
        }

    @staticmethod
    def _correlation_status(state: Any, canonical_event_id: str, producer: str) -> str:
        if producer != "EXP_SCANNER":
            return "NOT_APPLICABLE"
        for item in state.scanner_quality_evidence:
            if item["scanner_event_id"] == canonical_event_id:
                return str(item["status"])
        return "UNPAIRED_QUALITY_EVIDENCE"

    def receive(
        self, raw: bytes, *, detection: RawProducerDetection | None = None,
    ) -> RawProducerResult:
        detected = detection or detect_raw_producer(raw)
        if not detected.candidate:
            raise ValueError("raw producer adapter requires a detected Project A candidate")
        if not self.config.raw_producer_ingest_enabled:
            return RawProducerResult(
                503, False, False, detected.producer, detected.event,
                "DISABLED", "UNCHANGED", "RAW_PRODUCER_INGEST_DISABLED",
            )
        received_at = _iso(self.clock())
        ingest_id = self._ingest_id(raw)
        existing = self.store.existing_receipt(ingest_id)
        if existing is not None:
            return self._result_from_receipt(existing)
        if len(raw) > self.config.max_body_bytes:
            self.store.record_rejection(
                ingest_id=ingest_id, raw=raw, received_at=received_at,
                detection=detected, error_code="BODY_TOO_LARGE",
                detail="BODY_TOO_LARGE:raw_body",
            )
            return RawProducerResult(
                413, False, False, detected.producer, detected.event,
                "REJECTED", "UNCHANGED", "BODY_TOO_LARGE",
            )
        if detected.duplicate_keys:
            self.store.record_rejection(
                ingest_id=ingest_id, raw=raw, received_at=received_at,
                detection=detected, error_code="DUPLICATE_JSON_KEY",
                detail="DUPLICATE_JSON_KEY:raw_body",
            )
            return RawProducerResult(
                422, False, False, detected.producer, detected.event,
                "REJECTED", "UNCHANGED", "DUPLICATE_JSON_KEY",
            )
        try:
            event = parse_numeric_event(raw)
        except NumericStateError as exc:
            self.store.record_rejection(
                ingest_id=ingest_id, raw=raw, received_at=received_at,
                detection=detected, error_code=exc.code,
                detail=f"{exc.code}:{exc.field}",
            )
            return RawProducerResult(
                422, False, False, detected.producer, detected.event,
                "REJECTED", "UNCHANGED", exc.code,
            )

        try:
            with self.store.database.transaction(immediate=True) as conn:
                exact = conn.execute(
                    "SELECT * FROM project_a_producer_receipts WHERE ingest_id=?", (ingest_id,)
                ).fetchone()
                if exact is not None:
                    return self._result_from_receipt(exact)
                semantic = conn.execute(
                    "SELECT * FROM project_a_producer_events WHERE producer_id=? "
                    "AND producer_revision=? AND producer_event_id=?",
                    event.producer_key,
                ).fetchone()
                if semantic is not None:
                    if semantic["canonical_payload_sha256"] != event.canonical_payload_sha256:
                        raise NumericStateError(
                            "EVENT_ID_CONFLICT", "event_id",
                            "same producer event identity has different semantic content",
                        )
                    values = self.store._receipt_values(
                        ingest_id=ingest_id, raw=raw, received_at=received_at,
                        status="DUPLICATE", detection=detected,
                        canonical_event_id=semantic["canonical_event_id"],
                        error_code=None, detail=None,
                    )
                    self.store._insert_receipt(conn, values)
                    return RawProducerResult(
                        200, True, True, event.data["producer_id"], event.event,
                        "DUPLICATE", "UNCHANGED",
                    )

                rows = conn.execute(
                    "SELECT r.raw_body FROM project_a_producer_events e "
                    "JOIN project_a_producer_receipts r ON r.ingest_id=e.first_ingest_id "
                    "ORDER BY e.source_bar_time,e.canonical_event_id"
                ).fetchall()
                payloads = [bytes(row["raw_body"]) for row in rows] + [raw]
                disabled_requests = _NoExternalRequestAdapter()
                pipeline = OfflineSection2Pipeline({}).compile(
                    producer_events=payloads,
                    trigger_event_id=event.producer_event_id,
                    requested_at=event.source_bar_time,
                    macd={}, dxy={}, htf_context={},
                    freshness=self._missing_freshness(),
                    primary_request_adapter=disabled_requests,
                    supplemental_request_adapter=disabled_requests,
                    screenshot_request_adapter=_NoScreenshotRequestAdapter(),
                )
                if pipeline.make_sense_request.full_capture_requested:
                    raise Section2PipelineError("raw producer ingress cannot request capture")
                if any((
                    pipeline.runtime_enabled, pipeline.provider_enabled,
                    pipeline.writer_enabled, pipeline.broker_enabled, pipeline.order_placed,
                    pipeline.dash_request.dispatch_enabled, pipeline.dash_request.network_enabled,
                )):
                    raise Section2PipelineError("raw producer ingress side-effect boundary violated")
                state_bytes = pipeline.numeric_state.canonical_snapshot()
                state_hash = hashlib.sha256(state_bytes).hexdigest()
                correlation = self._correlation_status(
                    pipeline.numeric_state, event.canonical_event_id,
                    str(event.data["producer_id"]),
                )
                telemetry = correlation if str(event.data["producer_id"]) == "EXP_SCANNER" else "TELEMETRY_STATE_ACCEPTED"
                values = self.store._receipt_values(
                    ingest_id=ingest_id, raw=raw, received_at=received_at,
                    status="ACCEPTED", detection=detected,
                    canonical_event_id=event.canonical_event_id,
                    error_code=None, detail=None,
                )
                self.store._insert_receipt(conn, values)
                canonical_document = dict(event.data)
                canonical_document["canonical_event_id"] = event.canonical_event_id
                conn.execute(
                    "INSERT INTO project_a_producer_events("
                    "canonical_event_id,first_ingest_id,schema_name,producer_id,producer_revision,"
                    "producer_event_id,canonical_payload_sha256,canonical_json,source_bar_time,created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        event.canonical_event_id, ingest_id, event.data["schema"],
                        event.data["producer_id"], event.data["producer_revision"],
                        event.producer_event_id, event.canonical_payload_sha256,
                        canonical_json_bytes(canonical_document).decode("utf-8"),
                        str(event.data["source_bar_time"]), received_at,
                    ),
                )
                conn.execute(
                    "INSERT INTO project_a_producer_state_history("
                    "ingest_id,canonical_event_id,recorded_at,state_snapshot_json,state_snapshot_sha256,"
                    "compiler_state,compiler_sha256,evidence_bundle_sha256,telemetry_status,"
                    "correlation_status,full_capture_requested,provider_called,writer_called,order_placed"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ingest_id, event.canonical_event_id, received_at,
                        state_bytes.decode("utf-8"), state_hash,
                        pipeline.make_sense_request.state.value,
                        pipeline.make_sense_request.sha256,
                        str(pipeline.evidence_bundle_request.hashes["bundle_request_sha256"]),
                        telemetry, correlation, 0, 0, 0, 0,
                    ),
                )
                return RawProducerResult(
                    200, True, False, str(event.data["producer_id"]), event.event,
                    telemetry, pipeline.make_sense_request.state.value,
                )
        except NumericStateError as exc:
            self.store.record_rejection(
                ingest_id=ingest_id, raw=raw, received_at=received_at,
                detection=detected, error_code=exc.code,
                detail=f"{exc.code}:{exc.field}", conflict=True,
            )
            return RawProducerResult(
                409, False, False, detected.producer, detected.event,
                "CONFLICT", "UNCHANGED", exc.code,
            )
        except (Section2PipelineError, sqlite3.Error, RuntimeError, ValueError):
            try:
                self.store.record_rejection(
                    ingest_id=ingest_id, raw=raw, received_at=received_at,
                    detection=detected, error_code="PRODUCER_ADAPTER_FAILURE",
                    detail="PRODUCER_ADAPTER_FAILURE:offline_pipeline",
                )
            except (sqlite3.Error, RuntimeError):
                pass
            return RawProducerResult(
                503, False, False, detected.producer, detected.event,
                "FAILED_CLOSED", "UNCHANGED", "PRODUCER_ADAPTER_FAILURE",
            )


__all__ = [
    "APPROVED_PRODUCERS", "APPROVED_SCHEMAS", "ProjectARawProducerAdapter",
    "ProjectARawProducerStore", "RAW_ADAPTER_SCHEMA_CHECKSUM", "RawProducerDetection",
    "RawProducerResult", "detect_raw_producer",
]
