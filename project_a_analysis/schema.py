"""Additive SQLite schema for durable Project A analysis stories."""
from __future__ import annotations

import hashlib


SCHEMA_VERSION = 1
SCHEMA = r"""
CREATE TABLE IF NOT EXISTS project_a_analysis_meta (
  version INTEGER PRIMARY KEY,
  checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_a_analysis_stories (
  story_id TEXT PRIMARY KEY,
  liquidity_event_id TEXT NOT NULL UNIQUE REFERENCES project_a_producer_events(canonical_event_id),
  symbol TEXT NOT NULL CHECK(symbol='XAUUSD'),
  feed TEXT NOT NULL CHECK(feed='ICMARKETS'),
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode='SHADOW'),
  execution_environment TEXT NOT NULL CHECK(execution_environment='MT5_DEMO'),
  live_execution INTEGER NOT NULL CHECK(live_execution=0),
  order_placement INTEGER NOT NULL CHECK(order_placement=0)
);
CREATE TRIGGER IF NOT EXISTS project_a_analysis_stories_no_update
  BEFORE UPDATE ON project_a_analysis_stories
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_stories is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_analysis_stories_no_delete
  BEFORE DELETE ON project_a_analysis_stories
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_stories is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_analysis_jobs (
  job_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL UNIQUE,
  story_id TEXT NOT NULL REFERENCES project_a_analysis_stories(story_id),
  canonical_event_id TEXT NOT NULL UNIQUE REFERENCES project_a_producer_events(canonical_event_id),
  parent_analysis_id TEXT,
  stage TEXT NOT NULL CHECK(stage IN ('LIQ_BASELINE','E1_DELTA')),
  e1_count INTEGER NOT NULL CHECK(e1_count >= 0),
  requested_at TEXT NOT NULL,
  capture_scope TEXT NOT NULL CHECK(capture_scope IN ('FULL_BASELINE','BOUNDED_DELTA')),
  evidence_acquisition_mode TEXT NOT NULL CHECK(evidence_acquisition_mode='MCP_STRUCTURED_READS_AND_SCREENSHOTS'),
  request_context_json TEXT NOT NULL,
  request_context_sha256 TEXT NOT NULL,
  provider_tools_enabled INTEGER NOT NULL CHECK(provider_tools_enabled=0),
  writer_enabled INTEGER NOT NULL CHECK(writer_enabled=0),
  broker_enabled INTEGER NOT NULL CHECK(broker_enabled=0),
  order_enabled INTEGER NOT NULL CHECK(order_enabled=0)
);
CREATE INDEX IF NOT EXISTS project_a_analysis_jobs_story_idx
  ON project_a_analysis_jobs(story_id,e1_count,requested_at);
CREATE TRIGGER IF NOT EXISTS project_a_analysis_jobs_no_update
  BEFORE UPDATE ON project_a_analysis_jobs
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_jobs is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_analysis_jobs_no_delete
  BEFORE DELETE ON project_a_analysis_jobs
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_jobs is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_analysis_job_status_history (
  status_id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES project_a_analysis_jobs(job_id),
  status TEXT NOT NULL CHECK(status IN ('PENDING_CAPTURE','CAPTURED','CLAIMED','COMPLETED','TECHNICAL_FAILURE')),
  recorded_at TEXT NOT NULL,
  worker_id TEXT,
  lease_expires_at TEXT,
  failure_code TEXT,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS project_a_analysis_job_status_idx
  ON project_a_analysis_job_status_history(job_id,status_id);
CREATE TRIGGER IF NOT EXISTS project_a_analysis_job_status_no_update
  BEFORE UPDATE ON project_a_analysis_job_status_history
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_job_status_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_analysis_job_status_no_delete
  BEFORE DELETE ON project_a_analysis_job_status_history
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_job_status_history is append-only'); END;
CREATE TABLE IF NOT EXISTS project_a_analysis_captures (
  capture_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES project_a_analysis_jobs(job_id),
  completed_at TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  structured_evidence_json TEXT NOT NULL,
  image_manifest_json TEXT NOT NULL,
  capture_complete INTEGER NOT NULL CHECK(capture_complete=1)
);
CREATE TRIGGER IF NOT EXISTS project_a_analysis_captures_no_update
  BEFORE UPDATE ON project_a_analysis_captures
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_captures is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_analysis_captures_no_delete
  BEFORE DELETE ON project_a_analysis_captures
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_captures is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_provider_attempts (
  attempt_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES project_a_analysis_jobs(job_id),
  idempotency_key TEXT NOT NULL,
  client_request_id TEXT NOT NULL,
  provider_response_id TEXT,
  provider_request_id TEXT,
  model TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  outcome TEXT NOT NULL CHECK(outcome IN ('REQUESTED','VALIDATED','TECHNICAL_FAILURE')),
  failure_code TEXT,
  request_manifest_sha256 TEXT NOT NULL,
  raw_response_sha256 TEXT,
  UNIQUE(job_id,idempotency_key,outcome)
);
CREATE TRIGGER IF NOT EXISTS project_a_provider_attempts_no_update
  BEFORE UPDATE ON project_a_provider_attempts
  BEGIN SELECT RAISE(ABORT, 'project_a_provider_attempts is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_provider_attempts_no_delete
  BEFORE DELETE ON project_a_provider_attempts
  BEGIN SELECT RAISE(ABORT, 'project_a_provider_attempts is append-only'); END;
CREATE TABLE IF NOT EXISTS project_a_analysis_results (
  analysis_id TEXT PRIMARY KEY REFERENCES project_a_analysis_jobs(analysis_id),
  story_id TEXT NOT NULL REFERENCES project_a_analysis_stories(story_id),
  job_id TEXT NOT NULL UNIQUE REFERENCES project_a_analysis_jobs(job_id),
  parent_analysis_id TEXT,
  completed_at TEXT NOT NULL,
  grade_json TEXT NOT NULL,
  grade_sha256 TEXT NOT NULL,
  evidence_manifest_sha256 TEXT NOT NULL,
  client_request_id TEXT NOT NULL,
  provider_response_id TEXT NOT NULL,
  provider_request_id TEXT,
  model TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS project_a_analysis_results_no_update
  BEFORE UPDATE ON project_a_analysis_results
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_results is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_analysis_results_no_delete
  BEFORE DELETE ON project_a_analysis_results
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_results is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_story_state_history (
  state_id INTEGER PRIMARY KEY AUTOINCREMENT,
  story_id TEXT NOT NULL REFERENCES project_a_analysis_stories(story_id),
  analysis_id TEXT REFERENCES project_a_analysis_results(analysis_id),
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','CLOSED')),
  e1_count INTEGER NOT NULL CHECK(e1_count >= 0),
  big_picture_json TEXT NOT NULL,
  liquidity_baseline_analysis_id TEXT,
  latest_analysis_id TEXT,
  latest_grade_json TEXT,
  decision TEXT CHECK(decision IN ('ENTERED','SKIPPED') OR decision IS NULL),
  recorded_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  UNIQUE(story_id,analysis_id),
  CHECK((status='ACTIVE' AND decision IS NULL) OR (status='CLOSED' AND decision IN ('ENTERED','SKIPPED')))
);
CREATE INDEX IF NOT EXISTS project_a_story_state_current_idx
  ON project_a_story_state_history(story_id,state_id);
CREATE TRIGGER IF NOT EXISTS project_a_story_state_no_update
  BEFORE UPDATE ON project_a_story_state_history
  BEGIN SELECT RAISE(ABORT, 'project_a_story_state_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_story_state_no_delete
  BEFORE DELETE ON project_a_story_state_history
  BEGIN SELECT RAISE(ABORT, 'project_a_story_state_history is append-only'); END;
CREATE TABLE IF NOT EXISTS project_a_orphan_e1_telemetry (
  canonical_event_id TEXT PRIMARY KEY REFERENCES project_a_producer_events(canonical_event_id),
  recorded_at TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(reason='NO_PRIOR_ACTIVE_LIQ_STORY'),
  provider_called INTEGER NOT NULL CHECK(provider_called=0)
);
CREATE TRIGGER IF NOT EXISTS project_a_orphan_e1_no_update
  BEFORE UPDATE ON project_a_orphan_e1_telemetry
  BEGIN SELECT RAISE(ABORT, 'project_a_orphan_e1_telemetry is immutable'); END;
CREATE TRIGGER IF NOT EXISTS project_a_orphan_e1_no_delete
  BEFORE DELETE ON project_a_orphan_e1_telemetry
  BEGIN SELECT RAISE(ABORT, 'project_a_orphan_e1_telemetry is immutable'); END;
CREATE TABLE IF NOT EXISTS project_a_analysis_audit (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  recorded_at TEXT NOT NULL,
  story_id TEXT,
  job_id TEXT,
  action TEXT NOT NULL,
  document_json TEXT NOT NULL,
  previous_hash TEXT NOT NULL,
  record_hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS project_a_analysis_audit_no_update
  BEFORE UPDATE ON project_a_analysis_audit
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS project_a_analysis_audit_no_delete
  BEFORE DELETE ON project_a_analysis_audit
  BEGIN SELECT RAISE(ABORT, 'project_a_analysis_audit is append-only'); END;
CREATE TABLE IF NOT EXISTS project_a_analysis_worker_health (
  worker_id TEXT PRIMARY KEY,
  pid INTEGER NOT NULL,
  provider_enabled INTEGER NOT NULL,
  last_heartbeat_at TEXT NOT NULL,
  last_error_code TEXT
);
"""
CHECKSUM = "sha256:" + hashlib.sha256(SCHEMA.encode("utf-8")).hexdigest()


def ensure_schema(conn, applied_at: str) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO project_a_analysis_meta(version,checksum) VALUES (?,?)",
        (SCHEMA_VERSION, CHECKSUM),
    )
    rows = conn.execute(
        "SELECT version,checksum FROM project_a_analysis_meta ORDER BY version"
    ).fetchall()
    if [(row["version"], row["checksum"]) for row in rows] != [(SCHEMA_VERSION, CHECKSUM)]:
        raise RuntimeError("Project A analysis schema mismatch")

