"""Project A receipt, validation, idempotency, state, outbox, and recovery service."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from contracts import EVENT_SCHEMA_V0_2, ContractError, canonical_json, validate_contract

from .config import ProjectAConfig
from .database import ProjectADatabase, SCHEMA_VERSION
from .state import transition

Clock = Callable[[], datetime]
SUPPORTED_SCHEMA_VERSION = "0.2"
DESTINATION = "SESSION_3_PHASE_1_8"
PURPOSE = "COMPILE_ANALYSIS_REQUEST"
_PROHIBITED_AUTHORITY_FIELDS = {
    "execution_environment", "live_execution", "mode", "order_placement",
}
_AMBIGUOUS_SPREAD_FIELDS = {"spread", "spread_pips", "spread_ticks", "spread_usd"}
_CLASS_TYPES = {
    "TELEMETRY": {"SNR_UPDATE", "EXPANSION_UPDATE"},
    "SETUP_CANDIDATE": {"SETUP_CANDIDATE"},
    "ANALYSIS_READY": {"SNR_REJECTION_READY", "SNR_BREAK_READY"},
    "LIFECYCLE": {
        "SETUP_INVALIDATED", "SETUP_EXPIRED", "ENTRY_WINDOW_OPEN",
        "ENTRY_WINDOW_CLOSED", "THESIS_INVALIDATED",
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def bounded(value: str | None, limit: int = 500) -> str:
    text = (value or "").replace("\x00", "")
    return text[:limit]


@dataclass(frozen=True)
class IngestResult:
    ingest_id: str
    result_code: str
    http_status: int
    event_id: str | None = None
    setup_id: str | None = None
    duplicate: bool = False
    dispatch_key: str | None = None
    transition_code: str | None = None
    detail: str | None = None

    def response(self) -> dict[str, Any]:
        return {
            "ok": self.http_status < 400,
            "ingest_id": self.ingest_id,
            "result_code": self.result_code,
            "event_id": self.event_id,
            "setup_id": self.setup_id,
            "duplicate": self.duplicate,
            "dispatch_key": self.dispatch_key,
            "transition_code": self.transition_code,
        }


class RuntimeReject(ValueError):
    def __init__(self, code: str, detail: str, *, status: int = 422,
                 replay_eligible: bool = True):
        super().__init__(detail)
        self.code = code
        self.detail = bounded(detail)
        self.status = status
        self.replay_eligible = replay_eligible


class ProjectAIngestService:
    def __init__(self, config: ProjectAConfig, *, clock: Clock = utc_now,
                 initialize: bool = True):
        config.assert_safe()
        self.config = config
        self.clock = clock
        self.db = ProjectADatabase(config.database_path)
        if initialize:
            self.db.migrate(iso(self._now()))
        else:
            self.db.assert_ready()

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise RuntimeError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def receive(self, raw_body: bytes, *, content_type: str | None = "application/json",
                method: str = "POST", source_metadata: dict[str, Any] | None = None,
                raw_complete: bool = True, pre_error: RuntimeReject | None = None,
                replay_operation_id: str | None = None) -> IngestResult:
        now = self._now()
        now_text = iso(now)
        ingest_id = "ing_" + uuid.uuid4().hex
        body_hash = digest(raw_body)
        safe_source = self._safe_source_metadata(source_metadata or {})
        self._store_raw(ingest_id, raw_body, body_hash, now_text, method,
                        content_type, safe_source, raw_complete)

        try:
            if pre_error:
                raise pre_error
            if method != "POST":
                raise RuntimeReject("METHOD_NOT_ALLOWED", "Project A accepts POST only", status=405,
                                    replay_eligible=False)
            media_type = (content_type or "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                raise RuntimeReject("CONTENT_TYPE_UNSUPPORTED", "Content-Type must be application/json",
                                    status=415)
            if len(raw_body) > self.config.max_body_bytes:
                raise RuntimeReject("BODY_TOO_LARGE", "request body exceeds configured maximum",
                                    status=413, replay_eligible=False)
            try:
                text = raw_body.decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise RuntimeReject("BODY_ENCODING_INVALID", "request body must be UTF-8") from exc
            try:
                document = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeReject("MALFORMED_JSON", f"malformed JSON at byte {exc.pos}") from exc
            if not isinstance(document, dict):
                raise RuntimeReject("DOCUMENT_TYPE", "document must be a JSON object")
            version = document.get("schema_version")
            if version is None:
                raise RuntimeReject("SCHEMA_VERSION_MISSING", "schema_version is required")
            if version != SUPPORTED_SCHEMA_VERSION:
                raise RuntimeReject("SCHEMA_VERSION_UNSUPPORTED",
                                    f"unsupported schema_version {bounded(str(version), 40)}")
            try:
                validate_contract(EVENT_SCHEMA_V0_2, document)
            except ContractError as exc:
                category = "STRUCTURAL_VALIDATION_FAILED" if exc.code.startswith("schema_") \
                    else "SEMANTIC_VALIDATION_FAILED"
                raise RuntimeReject(category, f"{exc.code}: {bounded(str(exc), 420)}") from exc
            self._runtime_validate(document, now)
            return self._commit_validated(
                ingest_id, body_hash, document, now_text, replay_operation_id)
        except RuntimeReject as exc:
            event_id, setup_id = self._safe_ids_from_body(raw_body)
            self._record_rejection(
                ingest_id, now_text, exc, version=self._detect_version(raw_body),
                event_id=event_id, setup_id=setup_id, replay_operation_id=replay_operation_id,
            )
            return IngestResult(
                ingest_id, exc.code, exc.status, event_id=event_id, setup_id=setup_id,
                detail=exc.detail,
            )
        except sqlite3.Error:
            reject = RuntimeReject("PERSISTENCE_FAILURE", "database transaction failed", status=503)
            event_id, setup_id = self._safe_ids_from_body(raw_body)
            self._record_rejection(
                ingest_id, now_text, reject, version=self._detect_version(raw_body),
                event_id=event_id, setup_id=setup_id, replay_operation_id=replay_operation_id,
            )
            return IngestResult(
                ingest_id, reject.code, reject.status, event_id=event_id, setup_id=setup_id,
                detail=reject.detail,
            )

    def _runtime_validate(self, event: dict, now: datetime) -> None:
        if event["instrument"]["symbol"] != self.config.enabled_symbol:
            raise RuntimeReject("WRONG_SYMBOL", "only XAUUSD is enabled", replay_eligible=False)
        if event["event_class"] != "TELEMETRY" and event["timeframe"] != self.config.base_timeframe:
            raise RuntimeReject("WRONG_TIMEFRAME", "stateful Project A events require 1m timeframe",
                                replay_eligible=False)
        if event["event_type"] not in _CLASS_TYPES[event["event_class"]]:
            raise RuntimeReject("EVENT_TYPE_CLASS_MISMATCH", "event_type does not match event_class")
        payload = event["payload"]
        if "bar_time" in payload:
            bar_time = payload["bar_time"]
            if not isinstance(bar_time, str) or not bar_time.endswith("Z"):
                raise RuntimeReject("BAR_TIME_INVALID", "payload.bar_time must be UTC ending in Z")
            try:
                parse_utc(bar_time)
            except ValueError as exc:
                raise RuntimeReject("BAR_TIME_INVALID", "payload.bar_time is not a valid timestamp") from exc
        authority = sorted(_PROHIBITED_AUTHORITY_FIELDS.intersection(payload))
        if authority:
            raise RuntimeReject("CLIENT_AUTHORITY_PROHIBITED",
                                "client execution-authority fields are prohibited: " + ",".join(authority),
                                replay_eligible=False)
        occurred = parse_utc(event["occurred_at"])
        if occurred > now + timedelta(seconds=self.config.future_tolerance_seconds):
            raise RuntimeReject("FUTURE_TIMESTAMP", "occurred_at exceeds the configured future tolerance")
        age = (now - occurred).total_seconds()
        if age > self.config.stale_after_seconds and event["event_type"] != "SETUP_EXPIRED":
            raise RuntimeReject("STALE_TIMESTAMP", "event exceeds the configured lifecycle threshold")
        if event["event_class"] in {"SETUP_CANDIDATE", "ANALYSIS_READY"}:
            self._validate_snr(payload)
        if event["event_class"] == "ANALYSIS_READY":
            ambiguous = sorted(_AMBIGUOUS_SPREAD_FIELDS.intersection(payload))
            if ambiguous:
                raise RuntimeReject("SPREAD_FORMAT_AMBIGUOUS",
                                    "use normalized payload.spread_points only")
            spread = payload.get("spread_points")
            if isinstance(spread, bool) or not isinstance(spread, (int, float)) \
                    or not math.isfinite(spread) or spread < 0:
                raise RuntimeReject("SPREAD_POINTS_REQUIRED",
                                    "Analysis Ready requires finite normalized spread_points")
            if spread > self.config.max_spread_points:
                raise RuntimeReject("SPREAD_GATE_FAILED", "spread_points exceeds 10",
                                    replay_eligible=False)
            if event["disposition"]["status"] != "ACCEPTED":
                raise RuntimeReject("ANALYSIS_READY_NOT_ACCEPTED",
                                    "Analysis Ready must have ACCEPTED disposition")

    @staticmethod
    def _validate_snr(payload: dict) -> None:
        present = {key for key in ("snr_low", "snr_high") if key in payload}
        if present != {"snr_low", "snr_high"}:
            raise RuntimeReject("MALFORMED_SNR", "candidate/ready event requires both SNR bounds")
        low, high = payload["snr_low"], payload["snr_high"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (low, high)) or low > high:
            raise RuntimeReject("MALFORMED_SNR", "SNR bounds must be finite and ordered")

    def _commit_validated(self, ingest_id: str, body_hash: str, event: dict,
                          now_text: str, replay_operation_id: str | None) -> IngestResult:
        event_id = event["event_id"]
        setup_id = event.get("setup_id")
        canonical = canonical_json(event)
        canonical_hash = digest(canonical.encode("utf-8"))
        evidence = canonical_json({
            "setup_id": setup_id, "bar_time": self._semantic_bar_time(event),
            "event_class": event["event_class"], "event_type": event["event_type"],
            "hypothesis": event.get("hypothesis"), "path": event.get("path"),
            "payload": event["payload"],
        })
        evidence_fingerprint = digest(evidence.encode("utf-8"))
        dispatch_key = None

        with self.db.transaction(immediate=True) as conn:
            existing = conn.execute(
                "SELECT canonical_hash, ingest_id FROM project_a_canonical_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if existing:
                if existing["canonical_hash"] == canonical_hash:
                    self._processing(conn, ingest_id, now_text, "IDEMPOTENT_DUPLICATE", event,
                                     "EVENT_ID_SAME_CONTENT", "same event_id and canonical content",
                                     duplicate_of=existing["ingest_id"], replay_id=replay_operation_id)
                    return IngestResult(ingest_id, "IDEMPOTENT_DUPLICATE", 200, event_id,
                                        setup_id, True, transition_code="EVENT_ID_SAME_CONTENT")
                reject = RuntimeReject("EVENT_ID_CONFLICT",
                                       "same event_id has conflicting canonical content",
                                       status=409, replay_eligible=False)
                self._dead_letter(conn, ingest_id, now_text, reject, event_id, setup_id)
                self._processing(conn, ingest_id, now_text, "CONFLICT", event,
                                 reject.code, reject.detail, replay_id=replay_operation_id)
                return IngestResult(ingest_id, reject.code, reject.status, event_id, setup_id,
                                    detail=reject.detail)

            duplicate_body = conn.execute(
                "SELECT r.ingest_id FROM project_a_raw_receipts r "
                "JOIN project_a_receipt_processing p ON p.ingest_id=r.ingest_id "
                "WHERE r.body_hash=? AND r.ingest_id<>? AND p.status IN "
                "('ACCEPTED','RECORDED_REJECTED','IDEMPOTENT_DUPLICATE','DUPLICATE_EVIDENCE') "
                "ORDER BY p.id LIMIT 1", (body_hash, ingest_id),
            ).fetchone()
            same_evidence = conn.execute(
                "SELECT event_id, ingest_id FROM project_a_canonical_events "
                "WHERE evidence_fingerprint=? ORDER BY created_at LIMIT 1",
                (evidence_fingerprint,),
            ).fetchone()

            conn.execute(
                "INSERT INTO project_a_canonical_events(event_id,ingest_id,setup_id,correlation_id,"
                "causation_id,event_class,event_type,occurred_at,canonical_hash,evidence_fingerprint,"
                "canonical_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, ingest_id, setup_id, event["correlation_id"], event["causation_id"],
                 event["event_class"], event["event_type"], event["occurred_at"], canonical_hash,
                 evidence_fingerprint, canonical, now_text),
            )

            if duplicate_body or same_evidence:
                original_ingest = (duplicate_body or same_evidence)["ingest_id"]
                code = "DUPLICATE_BODY" if duplicate_body else "DUPLICATE_EVIDENCE"
                self._processing(conn, ingest_id, now_text, code, event, code,
                                 "delivery/evidence already recorded", duplicate_of=original_ingest,
                                 replay_id=replay_operation_id)
                return IngestResult(ingest_id, code, 200, event_id, setup_id, True,
                                    transition_code=code)

            if event["disposition"]["status"] == "REJECTED":
                self._processing(conn, ingest_id, now_text, "RECORDED_REJECTED", event,
                                 event["disposition"]["reason_code"],
                                 event["disposition"]["detail"], replay_id=replay_operation_id)
                return IngestResult(ingest_id, "RECORDED_REJECTED", 202, event_id, setup_id)

            current = None
            if setup_id:
                current = conn.execute(
                    "SELECT * FROM project_a_setup_state WHERE setup_id=?", (setup_id,),
                ).fetchone()
                if current and event["occurred_at"] < current["latest_occurred_at"]:
                    reject = RuntimeReject("OUT_OF_ORDER_EVENT",
                                           "event occurred before the latest committed setup event",
                                           status=409)
                    self._dead_letter(conn, ingest_id, now_text, reject, event_id, setup_id)
                    self._processing(conn, ingest_id, now_text, "REJECTED", event,
                                     reject.code, reject.detail, replay_id=replay_operation_id)
                    return IngestResult(ingest_id, reject.code, reject.status, event_id, setup_id,
                                        detail=reject.detail)

            decision = transition(current["lifecycle_state"] if current else None,
                                  event["event_class"], event["event_type"])
            if not decision.allowed:
                reject = RuntimeReject("ILLEGAL_LIFECYCLE_TRANSITION", decision.reason_code,
                                       status=409)
                self._dead_letter(conn, ingest_id, now_text, reject, event_id, setup_id)
                self._processing(conn, ingest_id, now_text, "REJECTED", event,
                                 reject.code, reject.detail, replay_id=replay_operation_id)
                return IngestResult(ingest_id, reject.code, reject.status, event_id, setup_id,
                                    transition_code=decision.reason_code, detail=reject.detail)

            if decision.persist_state and setup_id:
                version = (current["version"] + 1) if current else 1
                conn.execute(
                    "INSERT INTO project_a_setup_state(setup_id,symbol,lifecycle_state,hypothesis,path,"
                    "latest_event_id,latest_occurred_at,latest_evidence_fingerprint,version,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(setup_id) DO UPDATE SET "
                    "lifecycle_state=excluded.lifecycle_state,hypothesis=excluded.hypothesis,"
                    "path=excluded.path,latest_event_id=excluded.latest_event_id,"
                    "latest_occurred_at=excluded.latest_occurred_at,"
                    "latest_evidence_fingerprint=excluded.latest_evidence_fingerprint,"
                    "version=excluded.version,updated_at=excluded.updated_at",
                    (setup_id, event["instrument"]["symbol"], decision.next_state,
                     event.get("hypothesis"), event.get("path"), event_id, event["occurred_at"],
                     evidence_fingerprint, version, now_text),
                )
                conn.execute(
                    "INSERT INTO project_a_setup_state_history(setup_id,event_id,previous_state,"
                    "next_state,transition_code,evidence_fingerprint,occurred_at,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (setup_id, event_id, current["lifecycle_state"] if current else None,
                     decision.next_state, decision.reason_code, evidence_fingerprint,
                     event["occurred_at"], now_text),
                )

            if decision.create_outbox:
                dispatch_key = digest(canonical_json({
                    "destination": DESTINATION, "purpose": PURPOSE, "setup_id": setup_id,
                    "evidence_fingerprint": evidence_fingerprint,
                }).encode("utf-8"))
                payload = canonical_json({
                    "outbox_schema_version": "1.0", "destination": DESTINATION,
                    "purpose": PURPOSE, "dispatch_key": dispatch_key, "event": event,
                })
                conn.execute(
                    "INSERT INTO project_a_outbox(outbox_id,dispatch_key,destination,purpose,event_id,"
                    "setup_id,payload_json,status,available_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?)",
                    ("out_" + uuid.uuid4().hex, dispatch_key, DESTINATION, PURPOSE, event_id,
                     setup_id, payload, now_text, now_text, now_text),
                )
            self._processing(conn, ingest_id, now_text, "ACCEPTED", event,
                             decision.reason_code, "validated and committed",
                             replay_id=replay_operation_id)
            return IngestResult(ingest_id, "ACCEPTED", 202, event_id, setup_id, False,
                                dispatch_key, decision.reason_code)

    def _store_raw(self, ingest_id: str, raw: bytes, body_hash: str, now_text: str,
                   method: str, content_type: str | None, source: dict, complete: bool) -> None:
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO project_a_raw_receipts(ingest_id,raw_body,body_hash,body_bytes,"
                "raw_complete,received_at,method,content_type,source_metadata_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (ingest_id, sqlite3.Binary(raw), body_hash, len(raw), int(complete), now_text,
                 bounded(method, 12), bounded(content_type, 100), canonical_json(source)),
            )

    def _record_rejection(self, ingest_id: str, now_text: str, reject: RuntimeReject,
                          *, version: str | None, event_id: str | None, setup_id: str | None,
                          replay_operation_id: str | None) -> None:
        with self.db.transaction(immediate=True) as conn:
            self._dead_letter(conn, ingest_id, now_text, reject, event_id, setup_id)
            self._processing(conn, ingest_id, now_text, "REJECTED", None, reject.code,
                             reject.detail, version=version, event_id=event_id, setup_id=setup_id,
                             replay_id=replay_operation_id)

    @staticmethod
    def _processing(conn, ingest_id: str, now_text: str, status: str,
                    event: dict | None, code: str, detail: str, *, version: str | None = None,
                    event_id: str | None = None, setup_id: str | None = None,
                    duplicate_of: str | None = None, replay_id: str | None = None) -> None:
        conn.execute(
            "INSERT INTO project_a_receipt_processing(ingest_id,recorded_at,status,schema_version,"
            "event_id,setup_id,error_code,detail,duplicate_of_ingest_id,replay_operation_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ingest_id, now_text, status, version or (event or {}).get("schema_version"),
             event_id or (event or {}).get("event_id"), setup_id or (event or {}).get("setup_id"),
             code, bounded(detail), duplicate_of, replay_id),
        )

    @staticmethod
    def _dead_letter(conn, ingest_id: str, now_text: str, reject: RuntimeReject,
                     event_id: str | None, setup_id: str | None, attempt_count: int = 0) -> None:
        dedupe_key = digest(canonical_json({
            "error_code": reject.code, "event_id": event_id, "setup_id": setup_id,
        }).encode("utf-8"))
        conn.execute(
            "INSERT INTO project_a_dead_letters(dead_letter_id,dedupe_key,error_code,ingest_id,"
            "event_id,setup_id,first_seen_at,latest_seen_at,occurrence_count,attempt_count,detail,"
            "replay_eligible,status) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,'OPEN') "
            "ON CONFLICT(dedupe_key) DO UPDATE SET ingest_id=excluded.ingest_id,"
            "latest_seen_at=excluded.latest_seen_at,"
            "occurrence_count=occurrence_count+1,attempt_count=MAX(attempt_count,excluded.attempt_count),"
            "detail=excluded.detail",
            ("dlq_" + uuid.uuid4().hex, dedupe_key, reject.code, ingest_id, event_id, setup_id,
             now_text, now_text, attempt_count, reject.detail, int(reject.replay_eligible)),
        )

    @staticmethod
    def _safe_source_metadata(source: dict[str, Any]) -> dict[str, str]:
        allowed = {"client", "forwarded_for", "user_agent", "transport", "replay_source"}
        return {key: bounded(str(value), 120) for key, value in source.items()
                if key in allowed and value is not None}

    @staticmethod
    def _semantic_bar_time(event: dict) -> str:
        explicit = event["payload"].get("bar_time")
        if isinstance(explicit, str):
            return explicit
        occurred = parse_utc(event["occurred_at"])
        if event["timeframe"] == "1m":
            occurred = occurred.replace(second=0, microsecond=0)
        return iso(occurred)

    @staticmethod
    def _safe_ids_from_body(raw: bytes) -> tuple[str | None, str | None]:
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                return None, None
            event_id = value.get("event_id") if isinstance(value.get("event_id"), str) else None
            setup_id = value.get("setup_id") if isinstance(value.get("setup_id"), str) else None
            return bounded(event_id, 128) if event_id else None, bounded(setup_id, 128) if setup_id else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, None

    @staticmethod
    def _detect_version(raw: bytes) -> str | None:
        try:
            value = json.loads(raw.decode("utf-8"))
            version = value.get("schema_version") if isinstance(value, dict) else None
            return bounded(str(version), 40) if version is not None else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def claim_outbox(self, worker_id: str) -> dict | None:
        now_text = iso(self._now())
        with self.db.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM project_a_outbox WHERE status IN ('PENDING','FAILED') "
                "AND available_at<=? ORDER BY created_at,outbox_id LIMIT 1", (now_text,),
            ).fetchone()
            if row is None:
                return None
            updated = conn.execute(
                "UPDATE project_a_outbox SET status='PROCESSING',claimed_at=?,claimed_by=?,"
                "attempt_count=attempt_count+1,updated_at=? WHERE outbox_id=? "
                "AND status IN ('PENDING','FAILED')",
                (now_text, bounded(worker_id, 100), now_text, row["outbox_id"]),
            ).rowcount
            if updated != 1:
                return None
            conn.execute(
                "INSERT INTO project_a_outbox_attempts(outbox_id,attempted_at,worker_id,outcome,detail) "
                "VALUES(?,?,?,'CLAIMED',NULL)", (row["outbox_id"], now_text, bounded(worker_id, 100)),
            )
            claimed = conn.execute(
                "SELECT * FROM project_a_outbox WHERE outbox_id=?", (row["outbox_id"],),
            ).fetchone()
            result = dict(claimed)
            result["payload"] = json.loads(result.pop("payload_json"))
            return result

    def deliver_outbox(self, outbox_id: str, worker_id: str) -> bool:
        now_text = iso(self._now())
        with self.db.transaction(immediate=True) as conn:
            count = conn.execute(
                "UPDATE project_a_outbox SET status='DELIVERED',delivered_at=?,claimed_at=NULL,"
                "claimed_by=NULL,last_error=NULL,updated_at=? WHERE outbox_id=? "
                "AND status='PROCESSING' AND claimed_by=?",
                (now_text, now_text, outbox_id, bounded(worker_id, 100)),
            ).rowcount
            if count:
                conn.execute(
                    "INSERT INTO project_a_outbox_attempts(outbox_id,attempted_at,worker_id,outcome,detail) "
                    "VALUES(?,?,?,'DELIVERED',NULL)", (outbox_id, now_text, bounded(worker_id, 100)),
                )
            return count == 1

    def fail_outbox(self, outbox_id: str, worker_id: str, detail: str,
                    *, retry_delay_seconds: int = 30) -> str | None:
        now = self._now()
        now_text = iso(now)
        with self.db.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM project_a_outbox WHERE outbox_id=? AND status='PROCESSING' "
                "AND claimed_by=?", (outbox_id, bounded(worker_id, 100)),
            ).fetchone()
            if row is None:
                return None
            terminal = row["attempt_count"] >= self.config.max_outbox_attempts
            status = "DEAD_LETTER" if terminal else "FAILED"
            available = iso(now + timedelta(seconds=max(0, retry_delay_seconds)))
            conn.execute(
                "UPDATE project_a_outbox SET status=?,available_at=?,claimed_at=NULL,claimed_by=NULL,"
                "last_error=?,updated_at=? WHERE outbox_id=?",
                (status, available, bounded(detail), now_text, outbox_id),
            )
            conn.execute(
                "INSERT INTO project_a_outbox_attempts(outbox_id,attempted_at,worker_id,outcome,detail) "
                "VALUES(?,?,?,?,?)", (outbox_id, now_text, bounded(worker_id, 100), status,
                                      bounded(detail)),
            )
            if terminal:
                reject = RuntimeReject("OUTBOX_UNRECOVERABLE", "outbox retry limit reached")
                source = conn.execute(
                    "SELECT ingest_id FROM project_a_canonical_events WHERE event_id=?",
                    (row["event_id"],),
                ).fetchone()
                self._dead_letter(conn, source["ingest_id"], now_text, reject,
                                  row["event_id"], row["setup_id"], row["attempt_count"])
            return status

    def recover_abandoned_claims(self) -> int:
        now = self._now()
        cutoff = iso(now - timedelta(seconds=self.config.claim_timeout_seconds))
        now_text = iso(now)
        with self.db.transaction(immediate=True) as conn:
            rows = conn.execute(
                "SELECT outbox_id,claimed_by FROM project_a_outbox "
                "WHERE status='PROCESSING' AND claimed_at<?", (cutoff,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE project_a_outbox SET status='FAILED',available_at=?,claimed_at=NULL,"
                    "claimed_by=NULL,last_error='ABANDONED_CLAIM',updated_at=? WHERE outbox_id=?",
                    (now_text, now_text, row["outbox_id"]),
                )
                conn.execute(
                    "INSERT INTO project_a_outbox_attempts(outbox_id,attempted_at,worker_id,outcome,detail) "
                    "VALUES(?,?,?,'RECOVERED','ABANDONED_CLAIM')",
                    (row["outbox_id"], now_text, row["claimed_by"]),
                )
            return len(rows)

    def retry_outbox(self, outbox_id: str) -> bool:
        now_text = iso(self._now())
        with self.db.transaction(immediate=True) as conn:
            return conn.execute(
                "UPDATE project_a_outbox SET status='PENDING',available_at=?,last_error=NULL,"
                "updated_at=? WHERE outbox_id=? AND status='FAILED'",
                (now_text, now_text, outbox_id),
            ).rowcount == 1

    def health(self) -> dict[str, Any]:
        errors = self.config.safety_errors()
        database_ready = schema_ready = outbox_ready = False
        detail = None
        try:
            self.db.assert_ready()
            database_ready = schema_ready = True
            with closing(self.db.connect()) as conn:
                conn.execute("SELECT 1 FROM project_a_outbox LIMIT 1").fetchall()
            outbox_ready = True
        except (RuntimeError, sqlite3.Error) as exc:
            detail = bounded(str(exc))
        ready = database_ready and schema_ready and outbox_ready and not errors
        return {
            "ok": ready, "database_ready": database_ready, "schema_ready": schema_ready,
            "schema_version": SCHEMA_VERSION if schema_ready else None,
            "outbox_ready": outbox_ready, "configuration_ready": not errors,
            "shadow_mode": self.config.mode == "SHADOW", "live_execution": False,
            "order_placement": False, "enabled_symbol": self.config.enabled_symbol,
            "ingest_port": self.config.ingest_port, "reserved_capture_port": 4999,
            "errors": errors, "detail": detail,
        }

    def metrics(self) -> dict[str, Any]:
        with closing(self.db.connect()) as conn:
            def scalar(query: str) -> int:
                return int(conn.execute(query).fetchone()[0])
            reasons = {
                row["error_code"]: int(row["count"])
                for row in conn.execute(
                    "SELECT error_code,COUNT(*) AS count FROM project_a_receipt_processing "
                    "WHERE status IN ('REJECTED','CONFLICT') GROUP BY error_code"
                ).fetchall()
            }
            return {
                "receipts_total": scalar("SELECT COUNT(*) FROM project_a_raw_receipts"),
                "accepted_events_total": scalar(
                    "SELECT COUNT(*) FROM project_a_receipt_processing WHERE status='ACCEPTED'"),
                "rejected_events_total": scalar(
                    "SELECT COUNT(*) FROM project_a_receipt_processing WHERE status='REJECTED'"),
                "duplicate_events_total": scalar(
                    "SELECT COUNT(*) FROM project_a_receipt_processing WHERE status IN "
                    "('IDEMPOTENT_DUPLICATE','DUPLICATE_BODY','DUPLICATE_EVIDENCE')"),
                "conflicting_events_total": scalar(
                    "SELECT COUNT(*) FROM project_a_receipt_processing WHERE status='CONFLICT'"),
                "state_transitions_total": scalar("SELECT COUNT(*) FROM project_a_setup_state_history"),
                "analysis_ready_transitions_total": scalar(
                    "SELECT COUNT(*) FROM project_a_setup_state_history WHERE next_state IN "
                    "('SNR_REJECTION_READY','SNR_BREAK_READY')"),
                "outbox_pending": scalar(
                    "SELECT COUNT(*) FROM project_a_outbox WHERE status IN ('PENDING','FAILED','PROCESSING')"),
                "outbox_delivered_total": scalar(
                    "SELECT COUNT(*) FROM project_a_outbox WHERE status='DELIVERED'"),
                "dead_letters_open": scalar(
                    "SELECT COUNT(*) FROM project_a_dead_letters WHERE status='OPEN'"),
                "dead_letters_total": scalar("SELECT COUNT(*) FROM project_a_dead_letters"),
                "rejected_by_reason": reasons,
                "replay_operations_total": scalar("SELECT COUNT(*) FROM project_a_replay_operations"),
            }
