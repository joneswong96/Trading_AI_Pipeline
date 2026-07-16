"""SQLite schema, transactional migration ledger, and low-level operations."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
EXPECTED_TABLES = {
    "project_a_schema_migrations", "project_a_raw_receipts",
    "project_a_receipt_processing", "project_a_canonical_events",
    "project_a_setup_state", "project_a_setup_state_history", "project_a_outbox",
    "project_a_outbox_attempts", "project_a_dead_letters", "project_a_replay_operations",
}
EXPECTED_TRIGGERS = {
    "project_a_raw_receipts_no_update", "project_a_raw_receipts_no_delete",
    "project_a_processing_no_update", "project_a_processing_no_delete",
    "project_a_canonical_no_update", "project_a_canonical_no_delete",
}

MIGRATION_1 = """
CREATE TABLE project_a_schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  checksum TEXT NOT NULL
);
CREATE TABLE project_a_raw_receipts (
  ingest_id TEXT PRIMARY KEY,
  raw_body BLOB NOT NULL,
  body_hash TEXT NOT NULL,
  body_bytes INTEGER NOT NULL,
  raw_complete INTEGER NOT NULL,
  received_at TEXT NOT NULL,
  method TEXT NOT NULL,
  content_type TEXT,
  source_metadata_json TEXT NOT NULL
);
CREATE INDEX project_a_receipts_body_hash_idx ON project_a_raw_receipts(body_hash);
CREATE TRIGGER project_a_raw_receipts_no_update BEFORE UPDATE ON project_a_raw_receipts
BEGIN SELECT RAISE(ABORT, 'project_a_raw_receipts is immutable'); END;
CREATE TRIGGER project_a_raw_receipts_no_delete BEFORE DELETE ON project_a_raw_receipts
BEGIN SELECT RAISE(ABORT, 'project_a_raw_receipts is immutable'); END;
CREATE TABLE project_a_receipt_processing (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ingest_id TEXT NOT NULL REFERENCES project_a_raw_receipts(ingest_id),
  recorded_at TEXT NOT NULL,
  status TEXT NOT NULL,
  schema_version TEXT,
  event_id TEXT,
  setup_id TEXT,
  error_code TEXT,
  detail TEXT,
  duplicate_of_ingest_id TEXT,
  replay_operation_id TEXT
);
CREATE INDEX project_a_processing_ingest_idx ON project_a_receipt_processing(ingest_id, id);
CREATE TRIGGER project_a_processing_no_update BEFORE UPDATE ON project_a_receipt_processing
BEGIN SELECT RAISE(ABORT, 'project_a_receipt_processing is append-only'); END;
CREATE TRIGGER project_a_processing_no_delete BEFORE DELETE ON project_a_receipt_processing
BEGIN SELECT RAISE(ABORT, 'project_a_receipt_processing is append-only'); END;
CREATE TABLE project_a_canonical_events (
  event_id TEXT PRIMARY KEY,
  ingest_id TEXT NOT NULL REFERENCES project_a_raw_receipts(ingest_id),
  setup_id TEXT,
  correlation_id TEXT NOT NULL,
  causation_id TEXT,
  event_class TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  canonical_hash TEXT NOT NULL,
  evidence_fingerprint TEXT NOT NULL,
  canonical_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX project_a_events_setup_idx ON project_a_canonical_events(setup_id, occurred_at);
CREATE INDEX project_a_events_evidence_idx ON project_a_canonical_events(evidence_fingerprint);
CREATE TRIGGER project_a_canonical_no_update BEFORE UPDATE ON project_a_canonical_events
BEGIN SELECT RAISE(ABORT, 'project_a_canonical_events is append-only'); END;
CREATE TRIGGER project_a_canonical_no_delete BEFORE DELETE ON project_a_canonical_events
BEGIN SELECT RAISE(ABORT, 'project_a_canonical_events is append-only'); END;
CREATE TABLE project_a_setup_state (
  setup_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  lifecycle_state TEXT NOT NULL,
  hypothesis TEXT,
  path TEXT,
  latest_event_id TEXT NOT NULL,
  latest_occurred_at TEXT NOT NULL,
  latest_evidence_fingerprint TEXT NOT NULL,
  version INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE project_a_setup_state_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  setup_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  previous_state TEXT,
  next_state TEXT,
  transition_code TEXT NOT NULL,
  evidence_fingerprint TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE project_a_outbox (
  outbox_id TEXT PRIMARY KEY,
  dispatch_key TEXT NOT NULL UNIQUE,
  destination TEXT NOT NULL,
  purpose TEXT NOT NULL,
  event_id TEXT NOT NULL REFERENCES project_a_canonical_events(event_id),
  setup_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING','PROCESSING','DELIVERED','FAILED','DEAD_LETTER')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL,
  claimed_at TEXT,
  claimed_by TEXT,
  delivered_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX project_a_outbox_claim_idx ON project_a_outbox(status, available_at, created_at);
CREATE TABLE project_a_outbox_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  outbox_id TEXT NOT NULL REFERENCES project_a_outbox(outbox_id),
  attempted_at TEXT NOT NULL,
  worker_id TEXT,
  outcome TEXT NOT NULL,
  detail TEXT
);
CREATE TABLE project_a_dead_letters (
  dead_letter_id TEXT PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,
  error_code TEXT NOT NULL,
  ingest_id TEXT NOT NULL,
  event_id TEXT,
  setup_id TEXT,
  first_seen_at TEXT NOT NULL,
  latest_seen_at TEXT NOT NULL,
  occurrence_count INTEGER NOT NULL,
  attempt_count INTEGER NOT NULL,
  detail TEXT NOT NULL,
  replay_eligible INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OPEN','RESOLVED'))
);
CREATE INDEX project_a_dead_letters_code_idx ON project_a_dead_letters(error_code, status);
CREATE TABLE project_a_replay_operations (
  replay_operation_id TEXT PRIMARY KEY,
  requested_at TEXT NOT NULL,
  selector_type TEXT NOT NULL,
  selector_value TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('COMMIT')),
  result_code TEXT NOT NULL,
  ingest_id TEXT
);
"""
MIGRATION_1_CHECKSUM = "sha256:" + hashlib.sha256(MIGRATION_1.encode("utf-8")).hexdigest()


class ProjectADatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def migrate(self, applied_at: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='project_a_schema_migrations'"
            ).fetchone()
        if tables is None:
            safe_applied_at = applied_at.replace("'", "''")
            safe_checksum = MIGRATION_1_CHECKSUM.replace("'", "''")
            conn = self.connect()
            try:
                conn.executescript(
                    "BEGIN IMMEDIATE;\n" + MIGRATION_1 +
                    "\nINSERT INTO project_a_schema_migrations"
                    "(version,name,applied_at,checksum) VALUES"
                    f"(1,'initial_project_a_runtime','{safe_applied_at}',"
                    f"'{safe_checksum}');\nCOMMIT;"
                )
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        self.assert_ready()

    def assert_ready(self) -> None:
        if not self.path.exists():
            raise RuntimeError("Project A database is not initialized")
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT version,name,checksum FROM project_a_schema_migrations ORDER BY version"
            ).fetchall()
            versions = [row["version"] for row in rows]
            if versions != list(range(1, SCHEMA_VERSION + 1)):
                raise RuntimeError(f"unsupported or partial Project A schema: {versions}")
            if (rows[0]["name"], rows[0]["checksum"]) != (
                    "initial_project_a_runtime", MIGRATION_1_CHECKSUM):
                raise RuntimeError("Project A migration ledger checksum mismatch")
            objects = conn.execute(
                "SELECT type,name FROM sqlite_master WHERE name LIKE 'project_a_%'"
            ).fetchall()
            tables = {row["name"] for row in objects if row["type"] == "table"}
            triggers = {row["name"] for row in objects if row["type"] == "trigger"}
            if not EXPECTED_TABLES.issubset(tables) or not EXPECTED_TRIGGERS.issubset(triggers):
                raise RuntimeError("partial Project A schema objects detected")
            integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Project A database integrity failure: {integrity}")
