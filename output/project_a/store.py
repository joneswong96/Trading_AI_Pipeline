"""Durable SQLite canonical Thesis store, renderer outbox, attempts, and outcomes."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from contracts import canonical_json

from .models import (
    COMPLETED_DELIVERY_STATUSES,
    DeliveryContext,
    RendererResult,
    ResultStatus,
    Session5Error,
    document_hash,
    parse_utc,
    stable_id,
    utc_z,
)


class ConflictError(Session5Error):
    pass


MIGRATION_VERSION = 1
MIGRATION_NAME = "session5_outputs_v1"
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS canonical_theses (
  setup_id TEXT PRIMARY KEY,
  thesis_id TEXT NOT NULL UNIQUE,
  thesis_hash TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  verdict_hash TEXT NOT NULL,
  request_json TEXT NOT NULL,
  verdict_json TEXT NOT NULL,
  thesis_json TEXT NOT NULL,
  audit_ref TEXT NOT NULL,
  audit_record_hash TEXT NOT NULL,
  audit_envelope_json TEXT NOT NULL,
  completed_result_json TEXT NOT NULL,
  finalized_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS canonical_theses_immutable_update
BEFORE UPDATE ON canonical_theses BEGIN SELECT RAISE(ABORT, 'canonical thesis is immutable'); END;
CREATE TRIGGER IF NOT EXISTS canonical_theses_immutable_delete
BEFORE DELETE ON canonical_theses BEGIN SELECT RAISE(ABORT, 'canonical thesis is immutable'); END;

CREATE TABLE IF NOT EXISTS renderer_deliveries (
  delivery_id TEXT PRIMARY KEY,
  thesis_id TEXT NOT NULL REFERENCES canonical_theses(thesis_id),
  setup_id TEXT NOT NULL,
  renderer_type TEXT NOT NULL,
  thesis_hash TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  first_attempt_at TEXT,
  latest_attempt_at TEXT,
  next_retry_at TEXT,
  last_error_code TEXT,
  external_reference TEXT,
  completion_at TEXT,
  replay_parent_delivery_id TEXT,
  shadow INTEGER NOT NULL CHECK(shadow = 1),
  dry_run INTEGER NOT NULL CHECK(dry_run = 1),
  claim_owner TEXT,
  claim_token TEXT,
  claimed_at TEXT,
  result_json TEXT,
  UNIQUE(renderer_type, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_renderer_deliveries_status
ON renderer_deliveries(status, next_retry_at, renderer_type);

CREATE TABLE IF NOT EXISTS renderer_attempts (
  attempt_id TEXT PRIMARY KEY,
  delivery_id TEXT NOT NULL REFERENCES renderer_deliveries(delivery_id),
  attempt_number INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  error_code TEXT,
  external_reference TEXT,
  result_json TEXT,
  UNIQUE(delivery_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS audit_operations (
  operation_id TEXT PRIMARY KEY,
  operation_type TEXT NOT NULL,
  delivery_id TEXT,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  detail_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mt5_outcome_history (
  event_id TEXT PRIMARY KEY,
  event_hash TEXT NOT NULL,
  setup_id TEXT NOT NULL,
  thesis_id TEXT NOT NULL REFERENCES canonical_theses(thesis_id),
  recorded_at TEXT NOT NULL,
  final_status TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mt5_outcome_thesis
ON mt5_outcome_history(thesis_id, recorded_at);
"""
MIGRATION_CHECKSUM = hashlib.sha256(MIGRATION_SQL.encode("utf-8")).hexdigest()
SCHEMA = MIGRATION_SQL
EXPECTED_OBJECTS = {
    ("table", "schema_migrations"),
    ("table", "canonical_theses"),
    ("trigger", "canonical_theses_immutable_update"),
    ("trigger", "canonical_theses_immutable_delete"),
    ("table", "renderer_deliveries"),
    ("index", "idx_renderer_deliveries_status"),
    ("table", "renderer_attempts"),
    ("table", "audit_operations"),
    ("table", "mt5_outcome_history"),
    ("index", "idx_mt5_outcome_thesis"),
}
EXPECTED_COLUMNS = {
    "schema_migrations": {
        "version",
        "name",
        "checksum",
        "applied_at",
    },
    "canonical_theses": {
        "setup_id",
        "thesis_id",
        "thesis_hash",
        "request_hash",
        "verdict_hash",
        "request_json",
        "verdict_json",
        "thesis_json",
        "audit_ref",
        "audit_record_hash",
        "audit_envelope_json",
        "completed_result_json",
        "finalized_at",
    },
    "renderer_deliveries": {
        "delivery_id",
        "thesis_id",
        "setup_id",
        "renderer_type",
        "thesis_hash",
        "idempotency_key",
        "status",
        "attempt_count",
        "first_attempt_at",
        "latest_attempt_at",
        "next_retry_at",
        "last_error_code",
        "external_reference",
        "completion_at",
        "replay_parent_delivery_id",
        "shadow",
        "dry_run",
        "claim_owner",
        "claim_token",
        "claimed_at",
        "result_json",
    },
    "renderer_attempts": {
        "attempt_id",
        "delivery_id",
        "attempt_number",
        "started_at",
        "finished_at",
        "status",
        "error_code",
        "external_reference",
        "result_json",
    },
    "audit_operations": {
        "operation_id",
        "operation_type",
        "delivery_id",
        "actor",
        "reason",
        "created_at",
        "detail_json",
    },
    "mt5_outcome_history": {
        "event_id",
        "event_hash",
        "setup_id",
        "thesis_id",
        "recorded_at",
        "final_status",
        "payload_json",
    },
}
OUTCOME_FIELDS = {
    "event_id",
    "setup_id",
    "thesis_id",
    "recorded_at",
    "final_status",
    "ticket_ref",
    "requested_price",
    "fill_price",
    "spread_points",
    "slippage",
    "open_time",
    "close_time",
    "exit_price",
    "exit_reason",
    "initial_risk",
    "mae",
    "mfe",
    "realised_pl",
    "realised_r",
}
OUTCOME_NUMERIC_FIELDS = {
    "requested_price",
    "fill_price",
    "spread_points",
    "slippage",
    "exit_price",
    "initial_risk",
    "mae",
    "mfe",
    "realised_pl",
    "realised_r",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,119}$")


class OutboxStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn:
            self._initialize_schema(conn)

    @staticmethod
    def _schema_objects(conn: sqlite3.Connection) -> set[tuple[str, str]]:
        return {
            (row["type"], row["name"])
            for row in conn.execute(
                """SELECT type,name FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','index','trigger')"""
            ).fetchall()
        }

    @classmethod
    def _initialize_schema(cls, conn: sqlite3.Connection) -> None:
        objects = cls._schema_objects(conn)
        if not objects:
            checksum = MIGRATION_CHECKSUM.replace("'", "''")
            name = MIGRATION_NAME.replace("'", "''")
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                "CREATE TABLE schema_migrations ("
                "version INTEGER PRIMARY KEY,name TEXT NOT NULL,"
                "checksum TEXT NOT NULL,applied_at TEXT NOT NULL);\n"
                + MIGRATION_SQL
                + "\nINSERT INTO schema_migrations(version,name,checksum,applied_at) "
                f"VALUES ({MIGRATION_VERSION},'{name}','{checksum}',"
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'));\nCOMMIT;"
            )
            objects = cls._schema_objects(conn)
        if objects != EXPECTED_OBJECTS:
            missing = sorted(EXPECTED_OBJECTS - objects)
            unknown = sorted(objects - EXPECTED_OBJECTS)
            raise Session5Error(
                "schema_state_unknown",
                f"missing={missing}; unknown={unknown}",
            )
        migrations = conn.execute(
            "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        expected = [(MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM)]
        actual = [(row["version"], row["name"], row["checksum"]) for row in migrations]
        if actual != expected:
            raise Session5Error(
                "migration_checksum_mismatch",
                f"expected={expected}; actual={actual}",
            )
        for table, expected_columns in EXPECTED_COLUMNS.items():
            actual_columns = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if actual_columns != expected_columns:
                raise Session5Error(
                    "schema_columns_mismatch",
                    f"{table}: expected={sorted(expected_columns)}; actual={sorted(actual_columns)}",
                )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_thesis_and_deliveries(
        self, *, thesis: dict, request: dict, verdict: dict, audit_ref: str,
        audit_record_hash: str, audit_envelope: dict, completed_result: dict,
        renderer_types: list[str], now: datetime,
    ) -> dict[str, Any]:
        thesis_hash = document_hash(thesis)
        request_hash = document_hash(request)
        verdict_hash = document_hash(verdict)
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM canonical_theses WHERE setup_id = ?", (thesis["setup_id"],)
            ).fetchone()
            if existing:
                same = (existing["thesis_hash"] == thesis_hash
                        and existing["request_hash"] == request_hash
                        and existing["verdict_hash"] == verdict_hash
                        and existing["audit_ref"] == audit_ref
                        and existing["audit_record_hash"] == audit_record_hash
                        and json.loads(existing["audit_envelope_json"]) == audit_envelope
                        and json.loads(existing["completed_result_json"]) == completed_result)
                if not same:
                    raise ConflictError("canonical_conflict", "same setup_id has conflicting content")
                deliveries = self._deliveries_for_setup_conn(conn, thesis["setup_id"])
                conn.commit()
                return {"created": False, "thesis": json.loads(existing["thesis_json"]),
                        "thesis_hash": thesis_hash, "deliveries": deliveries}

            conn.execute(
                "INSERT INTO canonical_theses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (thesis["setup_id"], thesis["thesis_id"], thesis_hash, request_hash,
                 verdict_hash, canonical_json(request), canonical_json(verdict),
                 canonical_json(thesis), audit_ref, audit_record_hash,
                 canonical_json(audit_envelope), canonical_json(completed_result),
                 utc_z(now)),
            )
            for renderer_type in renderer_types:
                delivery_id = stable_id("delivery", thesis["thesis_id"], renderer_type)
                idempotency_key = stable_id("idem", renderer_type, thesis_hash, length=40)
                conn.execute(
                    """INSERT INTO renderer_deliveries
                    (delivery_id,thesis_id,setup_id,renderer_type,thesis_hash,
                     idempotency_key,status,shadow,dry_run)
                    VALUES (?,?,?,?,?,?,'PENDING',1,1)""",
                    (delivery_id, thesis["thesis_id"], thesis["setup_id"], renderer_type,
                     thesis_hash, idempotency_key),
                )
            conn.commit()
            return {"created": True, "thesis": thesis, "thesis_hash": thesis_hash,
                    "deliveries": self.deliveries_for_setup(thesis["setup_id"])}

    def get_context(self, delivery_id: str) -> DeliveryContext:
        with closing(self._conn()) as conn:
            row = conn.execute(
                """SELECT d.*, t.request_json, t.verdict_json, t.thesis_json, t.audit_ref
                , t.audit_record_hash, t.audit_envelope_json, t.completed_result_json
                FROM renderer_deliveries d JOIN canonical_theses t ON t.thesis_id=d.thesis_id
                WHERE d.delivery_id=?""", (delivery_id,),
            ).fetchone()
        if not row:
            raise Session5Error("delivery_missing", delivery_id)
        return DeliveryContext(
            thesis=json.loads(row["thesis_json"]), request=json.loads(row["request_json"]),
            verdict=json.loads(row["verdict_json"]), delivery=dict(row), audit_ref=row["audit_ref"],
            audit_record_hash=row["audit_record_hash"],
            audit_envelope=json.loads(row["audit_envelope_json"]),
            completed_result=json.loads(row["completed_result_json"]),
        )

    def get_thesis(self, setup_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT thesis_json FROM canonical_theses WHERE setup_id=?", (setup_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def deliveries_for_setup(self, setup_id: str) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            return self._deliveries_for_setup_conn(conn, setup_id)

    @staticmethod
    def _deliveries_for_setup_conn(conn, setup_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM renderer_deliveries WHERE setup_id=? ORDER BY renderer_type",
            (setup_id,),
        ).fetchall()]

    def all_deliveries(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM renderer_deliveries ORDER BY setup_id,renderer_type"
            ).fetchall()]

    def claim(self, delivery_id: str, worker: str, now: datetime, retry_limit: int) -> tuple[str, str] | None:
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM renderer_deliveries WHERE delivery_id=?",
                               (delivery_id,)).fetchone()
            if not row:
                raise Session5Error("delivery_missing", delivery_id)
            if row["status"] in COMPLETED_DELIVERY_STATUSES:
                conn.commit()
                return None
            if row["status"] in {"TERMINAL_FAILED", "BLOCKED_SAFETY", "UNCERTAIN", "CLAIMED"}:
                conn.commit()
                return None
            if row["attempt_count"] >= retry_limit:
                conn.execute(
                    "UPDATE renderer_deliveries SET status='TERMINAL_FAILED',last_error_code='retry_limit' WHERE delivery_id=?",
                    (delivery_id,),
                )
                conn.commit()
                return None
            if row["next_retry_at"] and row["next_retry_at"] > utc_z(now):
                conn.commit()
                return None
            window_number = row["attempt_count"] + 1
            lifetime_number = conn.execute(
                """SELECT COALESCE(MAX(attempt_number),0)+1
                FROM renderer_attempts WHERE delivery_id=?""",
                (delivery_id,),
            ).fetchone()[0]
            attempt_id = stable_id("attempt", delivery_id, str(lifetime_number))
            claim_token = stable_id(
                "claim", delivery_id, str(lifetime_number), worker, utc_z(now)
            )
            stamp = utc_z(now)
            conn.execute(
                """UPDATE renderer_deliveries SET status='CLAIMED',attempt_count=?,
                first_attempt_at=COALESCE(first_attempt_at,?),latest_attempt_at=?,next_retry_at=NULL,
                claim_owner=?,claim_token=?,claimed_at=? WHERE delivery_id=?""",
                (window_number, stamp, stamp, worker, claim_token, stamp, delivery_id),
            )
            conn.execute(
                "INSERT INTO renderer_attempts(attempt_id,delivery_id,attempt_number,started_at,status) VALUES (?,?,?,?,?)",
                (attempt_id, delivery_id, lifetime_number, stamp, "CLAIMED"),
            )
            conn.commit()
            return attempt_id, claim_token

    def finish(self, result: RendererResult, claim_token: str, *, retry_seconds: int) -> None:
        mapping = {
            ResultStatus.SUCCESS: "SUCCEEDED",
            ResultStatus.ALREADY_COMPLETED: "SUCCEEDED",
            ResultStatus.DRY_RUN_SUCCESS: "DRY_RUN_SUCCEEDED",
            ResultStatus.RETRYABLE_FAILURE: "RETRYABLE_FAILED",
            ResultStatus.TERMINAL_FAILURE: "TERMINAL_FAILED",
            ResultStatus.BLOCKED_SAFETY: "BLOCKED_SAFETY",
            ResultStatus.UNCERTAIN: "UNCERTAIN",
        }
        status = mapping[result.status]
        completed = status in COMPLETED_DELIVERY_STATUSES
        next_retry = None
        if status == "RETRYABLE_FAILED":
            next_retry = utc_z(
                datetime.fromisoformat(result.timestamp.replace("Z", "+00:00"))
                + timedelta(seconds=retry_seconds)
            )
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT claim_token,status FROM renderer_deliveries WHERE delivery_id=?",
                               (result.delivery_id,)).fetchone()
            if not row or row["claim_token"] != claim_token or row["status"] != "CLAIMED":
                raise Session5Error("claim_lost", result.delivery_id)
            payload = canonical_json(result.as_dict())
            conn.execute(
                """UPDATE renderer_deliveries SET status=?,next_retry_at=?,last_error_code=?,
                external_reference=COALESCE(?,external_reference),completion_at=?,claim_owner=NULL,
                claim_token=NULL,claimed_at=NULL,result_json=? WHERE delivery_id=?""",
                (status, next_retry, result.error_code, result.external_reference,
                 result.timestamp if completed else None, payload, result.delivery_id),
            )
            conn.execute(
                """UPDATE renderer_attempts SET finished_at=?,status=?,error_code=?,
                external_reference=?,result_json=? WHERE attempt_id=?""",
                (result.timestamp, result.status.value, result.error_code,
                 result.external_reference, payload, result.attempt_id),
            )
            conn.commit()

    def recover_abandoned(self, now: datetime, claim_timeout_seconds: int) -> int:
        cutoff = utc_z(now - timedelta(seconds=claim_timeout_seconds))
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT delivery_id FROM renderer_deliveries WHERE status='CLAIMED' AND claimed_at<=?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE renderer_deliveries SET status='RETRYABLE_FAILED',
                    last_error_code='abandoned_claim',next_retry_at=?,claim_owner=NULL,
                    claim_token=NULL,claimed_at=NULL WHERE delivery_id=?""",
                    (utc_z(now), row["delivery_id"]),
                )
                conn.execute(
                    """UPDATE renderer_attempts SET finished_at=?,status='ABANDONED',
                    error_code='abandoned_claim' WHERE delivery_id=? AND status='CLAIMED'""",
                    (utc_z(now), row["delivery_id"]),
                )
            conn.commit()
        return len(rows)

    def manual_reset(self, delivery_id: str, *, actor: str, reason: str, now: datetime) -> None:
        if not actor.strip() or not reason.strip():
            raise Session5Error("audit_required", "manual reset needs actor and reason")
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status,attempt_count FROM renderer_deliveries WHERE delivery_id=?",
                               (delivery_id,)).fetchone()
            if not row:
                raise Session5Error("delivery_missing", delivery_id)
            if row["status"] in COMPLETED_DELIVERY_STATUSES:
                raise Session5Error("completed_reset_forbidden", "completed side effects cannot be reset")
            conn.execute(
                """UPDATE renderer_deliveries SET status='PENDING',attempt_count=0,
                next_retry_at=NULL,
                last_error_code=NULL,claim_owner=NULL,claim_token=NULL,claimed_at=NULL
                WHERE delivery_id=?""", (delivery_id,),
            )
            op_id = stable_id("operation", delivery_id, actor, reason, utc_z(now))
            detail = canonical_json(
                {"previous_status": row["status"], "previous_attempt_count": row["attempt_count"]}
            )
            conn.execute(
                "INSERT INTO audit_operations VALUES (?,?,?,?,?,?,?)",
                (op_id, "MANUAL_RESET", delivery_id, actor, reason, utc_z(now), detail),
            )
            conn.commit()

    def resolve_uncertain(self, delivery_id: str, *, found: bool,
                          external_reference: str | None, actor: str,
                          reason: str, now: datetime) -> None:
        """Audited reconciliation: complete a found side effect or make a missing one retryable."""
        if not actor.strip() or not reason.strip():
            raise Session5Error("audit_required", "uncertain reconciliation needs actor and reason")
        if found and not external_reference:
            raise Session5Error("external_reference_required", "found side effect needs a reference")
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM renderer_deliveries WHERE delivery_id=?",
                               (delivery_id,)).fetchone()
            if not row:
                raise Session5Error("delivery_missing", delivery_id)
            if row["status"] != "UNCERTAIN":
                raise Session5Error("not_uncertain", delivery_id)
            status = "SUCCEEDED" if found else "RETRYABLE_FAILED"
            conn.execute(
                """UPDATE renderer_deliveries SET status=?,external_reference=COALESCE(?,external_reference),
                completion_at=?,next_retry_at=?,last_error_code=?,claim_owner=NULL,claim_token=NULL,
                claimed_at=NULL WHERE delivery_id=?""",
                (status, external_reference, utc_z(now) if found else None,
                 None if found else utc_z(now), None if found else "reconciled_not_found",
                 delivery_id),
            )
            op_id = stable_id("operation", delivery_id, actor, reason, utc_z(now), "reconcile")
            detail = canonical_json({"found": found, "external_reference": external_reference})
            conn.execute(
                "INSERT INTO audit_operations VALUES (?,?,?,?,?,?,?)",
                (op_id, "RECONCILE_UNCERTAIN", delivery_id, actor, reason, utc_z(now), detail),
            )
            conn.commit()

    def record_operation(self, operation_type: str, *, actor: str, reason: str,
                         now: datetime, delivery_id: str | None = None,
                         detail: dict[str, Any] | None = None) -> str:
        if not operation_type.strip() or not actor.strip() or not reason.strip():
            raise Session5Error(
                "audit_required",
                "operation type, actor, and reason are required",
            )
        op_id = stable_id("operation", operation_type, actor, reason, utc_z(now), delivery_id or "")
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO audit_operations VALUES (?,?,?,?,?,?,?)",
                (op_id, operation_type, delivery_id, actor, reason, utc_z(now),
                 canonical_json(detail or {})),
            )
            conn.commit()
        return op_id

    def append_outcome(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            raise Session5Error("outcome_type", "outcome payload must be an object")
        missing = sorted(OUTCOME_FIELDS - payload.keys())
        if missing:
            raise Session5Error("outcome_fields_missing", ", ".join(missing))
        unknown = sorted(payload.keys() - OUTCOME_FIELDS)
        if unknown:
            raise Session5Error("outcome_fields_unknown", ", ".join(unknown))
        for field in ("event_id", "setup_id", "thesis_id"):
            if not isinstance(payload[field], str) or not SAFE_ID.fullmatch(payload[field]):
                raise Session5Error("outcome_identity_type", field)
        for field in ("ticket_ref", "exit_reason"):
            if payload[field] is not None and not isinstance(payload[field], str):
                raise Session5Error("outcome_field_type", field)
        for field in OUTCOME_NUMERIC_FIELDS:
            value = payload[field]
            if (
                value is not None
                and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                )
            ):
                raise Session5Error("outcome_numeric_invalid", field)
        if payload["spread_points"] is not None and payload["spread_points"] < 0:
            raise Session5Error("outcome_spread_negative", "spread_points")
        allowed = {"PARTIAL", "CLOSED", "CANCELLED", "REJECTED", "UNKNOWN"}
        if not isinstance(payload["final_status"], str) or payload["final_status"] not in allowed:
            raise Session5Error("outcome_status", str(payload["final_status"]))
        recorded_at = parse_utc(payload["recorded_at"])
        open_at = parse_utc(payload["open_time"]) if payload["open_time"] is not None else None
        close_at = parse_utc(payload["close_time"]) if payload["close_time"] is not None else None
        if close_at is not None and open_at is None:
            raise Session5Error("outcome_chronology", "close_time requires open_time")
        if open_at is not None and close_at is not None and close_at < open_at:
            raise Session5Error("outcome_chronology", "close_time precedes open_time")
        if open_at is not None and open_at > recorded_at:
            raise Session5Error("outcome_chronology", "open_time follows recorded_at")
        if close_at is not None and close_at > recorded_at:
            raise Session5Error("outcome_chronology", "close_time follows recorded_at")
        event_hash = document_hash(payload)
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            thesis = conn.execute(
                "SELECT setup_id,thesis_json FROM canonical_theses WHERE thesis_id=?",
                (payload["thesis_id"],),
            ).fetchone()
            if not thesis or thesis["setup_id"] != payload["setup_id"]:
                raise Session5Error("outcome_identity_mismatch", "setup/thesis does not match")
            thesis_document = json.loads(thesis["thesis_json"])
            if recorded_at < parse_utc(thesis_document["created_at"]):
                raise Session5Error(
                    "outcome_chronology",
                    "recorded_at precedes canonical Thesis creation",
                )
            existing = conn.execute(
                "SELECT event_hash FROM mt5_outcome_history WHERE event_id=?", (payload["event_id"],)
            ).fetchone()
            if existing:
                if existing["event_hash"] != event_hash:
                    raise ConflictError("outcome_conflict", "same event_id has conflicting content")
                conn.commit()
                return False
            latest = conn.execute(
                """SELECT recorded_at FROM mt5_outcome_history
                WHERE thesis_id=? ORDER BY recorded_at DESC,event_id DESC LIMIT 1""",
                (payload["thesis_id"],),
            ).fetchone()
            if latest and recorded_at < parse_utc(latest["recorded_at"]):
                raise Session5Error(
                    "outcome_out_of_order",
                    "recorded_at precedes the latest persisted outcome",
                )
            conn.execute(
                "INSERT INTO mt5_outcome_history VALUES (?,?,?,?,?,?,?)",
                (payload["event_id"], event_hash, payload["setup_id"], payload["thesis_id"],
                 payload["recorded_at"], payload["final_status"], canonical_json(payload)),
            )
            conn.commit()
        return True

    def outcomes(self, thesis_id: str) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM mt5_outcome_history WHERE thesis_id=? ORDER BY recorded_at,event_id",
                (thesis_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def integrity_check(self) -> str:
        with closing(self._conn()) as conn:
            return conn.execute("PRAGMA integrity_check").fetchone()[0]

    def migration_status(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]
