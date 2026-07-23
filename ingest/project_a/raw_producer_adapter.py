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
from datetime import datetime, timedelta, timezone
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
from project_a.evidence_bundle import approved_source_identities
from project_a.section2_pipeline import OfflineSection2Pipeline, Section2PipelineError
from project_a_analysis.schema import ensure_schema as ensure_analysis_schema
from project_a_analysis.store import enqueue_analysis_trigger

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

LIQ_RESEARCH_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_a_liq_research_meta (
  version INTEGER PRIMARY KEY,
  checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_a_liq_research_requests (
  canonical_event_id TEXT PRIMARY KEY REFERENCES project_a_producer_events(canonical_event_id),
  ingest_id TEXT NOT NULL UNIQUE REFERENCES project_a_producer_receipts(ingest_id),
  evidence_key TEXT NOT NULL UNIQUE,
  touch_fingerprint_sha256 TEXT NOT NULL,
  level_id TEXT NOT NULL,
  touch_count INTEGER NOT NULL CHECK(touch_count >= 1),
  requested_at TEXT NOT NULL,
  evidence_acquisition_mode TEXT NOT NULL
    CHECK(evidence_acquisition_mode='MCP_STRUCTURED_READS_AND_SCREENSHOTS'),
  evidence_request_json TEXT NOT NULL,
  evidence_request_sha256 TEXT NOT NULL,
  target_binding_status TEXT NOT NULL CHECK(target_binding_status='UNBOUND_REQUIRES_PREFLIGHT'),
  request_status TEXT NOT NULL CHECK(request_status='PENDING'),
  legacy_wake_eligible INTEGER NOT NULL CHECK(legacy_wake_eligible=0),
  provider_eligible INTEGER NOT NULL CHECK(provider_eligible=0),
  writer_eligible INTEGER NOT NULL CHECK(writer_eligible=0),
  order_eligible INTEGER NOT NULL CHECK(order_eligible=0)
);
CREATE TRIGGER IF NOT EXISTS project_a_liq_research_requests_no_update
  BEFORE UPDATE ON project_a_liq_research_requests
  BEGIN SELECT RAISE(ABORT, 'project_a_liq_research_requests is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_liq_research_requests_no_delete
  BEFORE DELETE ON project_a_liq_research_requests
  BEGIN SELECT RAISE(ABORT, 'project_a_liq_research_requests is append-only'); END;
CREATE TABLE IF NOT EXISTS project_a_liq_research_status_history (
  status_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_event_id TEXT NOT NULL REFERENCES project_a_liq_research_requests(canonical_event_id),
  status TEXT NOT NULL CHECK(status IN ('PENDING','CLAIMED','COMPLETED','FAILED')),
  recorded_at TEXT NOT NULL,
  worker_id TEXT,
  result_manifest_sha256 TEXT,
  detail TEXT
);
CREATE TRIGGER IF NOT EXISTS project_a_liq_research_status_no_update
  BEFORE UPDATE ON project_a_liq_research_status_history
  BEGIN SELECT RAISE(ABORT, 'project_a_liq_research_status_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_liq_research_status_no_delete
  BEFORE DELETE ON project_a_liq_research_status_history
  BEGIN SELECT RAISE(ABORT, 'project_a_liq_research_status_history is append-only'); END;
"""
LIQ_RESEARCH_QUEUE_SCHEMA_VERSION = 1
LIQ_RESEARCH_QUEUE_SCHEMA_CHECKSUM = "sha256:" + hashlib.sha256(
    LIQ_RESEARCH_QUEUE_SCHEMA.encode("utf-8")
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
    research_wake: bool = False
    evidence_acquisition_requested: bool = False

    def response(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": self.http_status < 400,
            "accepted": self.accepted,
            "deduped": self.deduped,
            "producer": self.producer,
            "event": self.event,
            "telemetry_status": self.telemetry_status,
            "state_status": self.state_status,
            "wake": self.research_wake,
            "wake_scope": "PROJECT_A_RESEARCH" if self.research_wake else "NONE",
            "evidence_acquisition_requested": self.evidence_acquisition_requested,
            "provider_called": False,
            "writer_called": False,
            "order_placed": False,
        }
        if self.error_code is not None:
            body["error_code"] = self.error_code
        return body


class ProjectARawProducerStore:
    """Append-only raw receipts plus deterministic Section-2 state snapshots."""

    def __init__(self, path: str | Path, *, applied_at: str):
        self.database = ProjectADatabase(path)
        self.database.migrate(applied_at)
        conn = self.database.connect()
        try:
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + RAW_ADAPTER_SCHEMA
                + "\n"
                + LIQ_RESEARCH_QUEUE_SCHEMA
                + "\nCOMMIT;"
            )
            ensure_analysis_schema(conn, applied_at)
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
            conn.execute(
                "INSERT OR IGNORE INTO project_a_liq_research_meta(version,checksum) VALUES (?,?)",
                (LIQ_RESEARCH_QUEUE_SCHEMA_VERSION, LIQ_RESEARCH_QUEUE_SCHEMA_CHECKSUM),
            )
            research_rows = conn.execute(
                "SELECT version,checksum FROM project_a_liq_research_meta ORDER BY version"
            ).fetchall()
            if [(row["version"], row["checksum"]) for row in research_rows] != [
                (LIQ_RESEARCH_QUEUE_SCHEMA_VERSION, LIQ_RESEARCH_QUEUE_SCHEMA_CHECKSUM)
            ]:
                raise RuntimeError("LIQ research queue schema mismatch")
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

    def pending_research_requests(self) -> tuple[sqlite3.Row, ...]:
        conn = self.database.connect()
        try:
            return tuple(conn.execute(
                "SELECT q.* FROM project_a_liq_research_requests q "
                "JOIN project_a_liq_research_status_history s ON s.status_id=("
                "SELECT MAX(s2.status_id) FROM project_a_liq_research_status_history s2 "
                "WHERE s2.canonical_event_id=q.canonical_event_id) "
                "WHERE s.status='PENDING' ORDER BY q.requested_at,q.canonical_event_id"
            ).fetchall())
        finally:
            conn.close()

    def claim_research_request(
        self, canonical_event_id: str, *, worker_id: str, claimed_at: datetime,
    ) -> sqlite3.Row | None:
        if not worker_id:
            raise ValueError("worker_id is required")
        with self.database.transaction(immediate=True) as conn:
            request = conn.execute(
                "SELECT * FROM project_a_liq_research_requests WHERE canonical_event_id=?",
                (canonical_event_id,),
            ).fetchone()
            if request is None:
                return None
            latest = conn.execute(
                "SELECT status FROM project_a_liq_research_status_history "
                "WHERE canonical_event_id=? ORDER BY status_id DESC LIMIT 1",
                (canonical_event_id,),
            ).fetchone()
            if latest is None or latest["status"] != "PENDING":
                return None
            conn.execute(
                "INSERT INTO project_a_liq_research_status_history("
                "canonical_event_id,status,recorded_at,worker_id"
                ") VALUES (?,?,?,?)",
                (canonical_event_id, "CLAIMED", _iso(claimed_at), worker_id),
            )
            return request

    def record_research_result(
        self,
        canonical_event_id: str,
        *,
        status: str,
        recorded_at: datetime,
        worker_id: str,
        result_manifest_sha256: str | None = None,
        detail: str | None = None,
    ) -> None:
        if status not in {"COMPLETED", "FAILED"}:
            raise ValueError("research result status must be COMPLETED or FAILED")
        if not worker_id:
            raise ValueError("worker_id is required")
        if status == "COMPLETED":
            if (
                not isinstance(result_manifest_sha256, str)
                or len(result_manifest_sha256) != 64
                or any(character not in "0123456789abcdef" for character in result_manifest_sha256)
            ):
                raise ValueError("COMPLETED research requires a lowercase 64-hex manifest SHA-256")
        elif result_manifest_sha256 is not None:
            raise ValueError("FAILED research cannot claim a completed result manifest")
        with self.database.transaction(immediate=True) as conn:
            latest = conn.execute(
                "SELECT status,worker_id FROM project_a_liq_research_status_history "
                "WHERE canonical_event_id=? ORDER BY status_id DESC LIMIT 1",
                (canonical_event_id,),
            ).fetchone()
            if latest is None or latest["status"] != "CLAIMED" or latest["worker_id"] != worker_id:
                raise RuntimeError("research request must be claimed by the same worker")
            conn.execute(
                "INSERT INTO project_a_liq_research_status_history("
                "canonical_event_id,status,recorded_at,worker_id,result_manifest_sha256,detail"
                ") VALUES (?,?,?,?,?,?)",
                (
                    canonical_event_id,
                    status,
                    _iso(recorded_at),
                    worker_id,
                    result_manifest_sha256,
                    None if detail is None else detail[:240],
                ),
            )

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

    @staticmethod
    def _validate_source_authority(event: Any) -> None:
        data = event.data
        producer = str(data.get("producer_id"))
        timeframe_field = "anchor_timeframe" if producer == "LIQ_V2" else "timeframe"
        expected_timeframe = {
            "LIQ_V2": "5m",
            "EXP_V3": "1m",
            "EXP_SCANNER": "1m",
            "RENKO_V3_SNIPER": "5s",
        }.get(producer)
        if (
            data.get("symbol") != "XAUUSD"
            or data.get("feed") != "ICMARKETS"
            or expected_timeframe is None
            or data.get(timeframe_field) != expected_timeframe
        ):
            raise NumericStateError(
                "SOURCE_AUTHORITY_MISMATCH",
                timeframe_field,
                "producer source must match approved XAUUSD/feed/timeframe authority",
            )
        if producer == "LIQ_V2" and event.event == "LIQ_TOUCH" and int(data.get("touch_count", 0)) < 1:
            raise NumericStateError(
                "INVALID_TOUCH_COUNT",
                "touch_count",
                "LIQ_TOUCH requires touch_count of at least one",
            )

    @staticmethod
    def _is_active_liq_touch(event: Any, observed_at: datetime) -> bool:
        data = event.data
        age = observed_at - event.source_bar_time
        return (
            data.get("producer_id") == "LIQ_V2"
            and str(data.get("producer_revision")) == "9"
            and event.event == "LIQ_TOUCH"
            and data.get("confirmed") is True
            and data.get("symbol") == "XAUUSD"
            and data.get("feed") == "ICMARKETS"
            and data.get("anchor_timeframe") == "5m"
            and data.get("freshness_status") == "FRESH"
            and data.get("level_freshness_status") == "FRESH"
            and data.get("market_price_freshness_status") == "FRESH"
            and int(data.get("touch_count", 0)) >= 1
            and timedelta(0) <= age <= timedelta(minutes=15)
        )

    @staticmethod
    def _liq_research_evidence_key(event: Any) -> str:
        data = event.data
        identity = {
            "level_id": data["level_id"],
            "touch_count": data["touch_count"],
            "source_bar_time": data["source_bar_time"],
        }
        return "sha256:" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()

    @staticmethod
    def _liq_touch_fingerprint(event: Any) -> str:
        evidence = dict(event.data)
        evidence.pop("event_id", None)
        evidence.pop("emitted_at", None)
        return "sha256:" + hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()

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
        observed_at = self.clock()
        received_at = _iso(observed_at)
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
            self._validate_source_authority(event)
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
                pipeline = OfflineSection2Pipeline(approved_source_identities()).compile(
                    producer_events=payloads,
                    trigger_event_id=event.producer_event_id,
                    requested_at=observed_at,
                    macd={}, dxy={}, htf_context={},
                    freshness=self._missing_freshness(),
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
                research_wake = self._is_active_liq_touch(event, observed_at)
                analysis_evidence_request = None
                evidence_key = self._liq_research_evidence_key(event) if research_wake else None
                touch_fingerprint = self._liq_touch_fingerprint(event) if research_wake else None
                same_evidence_suppressed = False
                if evidence_key is not None:
                    existing_touch = conn.execute(
                        "SELECT touch_fingerprint_sha256 FROM project_a_liq_research_requests "
                        "WHERE evidence_key=?",
                        (evidence_key,),
                    ).fetchone()
                    if existing_touch is not None:
                        if existing_touch["touch_fingerprint_sha256"] != touch_fingerprint:
                            raise NumericStateError(
                                "LIQ_TOUCH_EVIDENCE_CONFLICT",
                                "touch_identity",
                                "same level/touch/source time has different evidence",
                            )
                        same_evidence_suppressed = True
                        research_wake = False
                    else:
                        latest_touch = conn.execute(
                            "SELECT touch_count,requested_at,canonical_event_id FROM "
                            "project_a_liq_research_requests WHERE level_id=? "
                            "ORDER BY touch_count DESC,requested_at DESC LIMIT 1",
                            (str(event.data["level_id"]),),
                        ).fetchone()
                        if latest_touch is not None:
                            latest_event = conn.execute(
                                "SELECT source_bar_time FROM project_a_producer_events "
                                "WHERE canonical_event_id=?",
                                (latest_touch["canonical_event_id"],),
                            ).fetchone()
                            if (
                                int(event.data["touch_count"]) <= int(latest_touch["touch_count"])
                                or latest_event is None
                                or str(event.data["source_bar_time"]) <= str(latest_event["source_bar_time"])
                            ):
                                raise NumericStateError(
                                    "NON_MONOTONIC_LIQ_RETOUCH",
                                    "touch_count",
                                    "re-touch must advance both touch count and source time",
                                )
                if research_wake:
                    request_document = pipeline.evidence_bundle_request.document()
                    analysis_evidence_request = request_document
                    request_bytes = canonical_json_bytes(request_document)
                    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
                    conn.execute(
                        "INSERT INTO project_a_liq_research_requests("
                        "canonical_event_id,ingest_id,evidence_key,touch_fingerprint_sha256,"
                        "level_id,touch_count,requested_at,evidence_acquisition_mode,"
                        "evidence_request_json,evidence_request_sha256,target_binding_status,"
                        "request_status,legacy_wake_eligible,"
                        "provider_eligible,writer_eligible,order_eligible"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            event.canonical_event_id,
                            ingest_id,
                            evidence_key,
                            touch_fingerprint,
                            str(event.data["level_id"]),
                            int(event.data["touch_count"]),
                            received_at,
                            "MCP_STRUCTURED_READS_AND_SCREENSHOTS",
                            request_bytes.decode("utf-8"),
                            request_sha256,
                            "UNBOUND_REQUIRES_PREFLIGHT",
                            "PENDING",
                            0,
                            0,
                            0,
                            0,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO project_a_liq_research_status_history("
                        "canonical_event_id,status,recorded_at"
                        ") VALUES (?,?,?)",
                        (event.canonical_event_id, "PENDING", received_at),
                    )
                if research_wake or event.event == "RENKO_E1":
                    enqueue_analysis_trigger(
                        conn,
                        canonical_event=canonical_document,
                        recorded_at=observed_at,
                        evidence_request=analysis_evidence_request,
                    )
                return RawProducerResult(
                    200, True, same_evidence_suppressed,
                    str(event.data["producer_id"]), event.event,
                    (
                        "LIQ_RESEARCH_WAKE_REQUESTED"
                        if research_wake
                        else "LIQ_RESEARCH_DUPLICATE_EVIDENCE_SUPPRESSED"
                        if same_evidence_suppressed
                        else "LIQ_RESEARCH_FAILED_CLOSED"
                        if event.data["producer_id"] == "LIQ_V2" and event.event == "LIQ_TOUCH"
                        else telemetry
                    ),
                    pipeline.make_sense_request.state.value,
                    research_wake=research_wake,
                    evidence_acquisition_requested=research_wake,
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
    "ProjectARawProducerStore", "RAW_ADAPTER_SCHEMA_CHECKSUM",
    "LIQ_RESEARCH_QUEUE_SCHEMA_CHECKSUM", "RawProducerDetection",
    "RawProducerResult", "detect_raw_producer",
]
