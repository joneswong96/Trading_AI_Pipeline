"""Append-only request/result ledger with chained audit records."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from contracts import canonical_json

from .cdp import CaptureFailure


SCHEMA = """
CREATE TABLE IF NOT EXISTS capture_service_meta (
  version INTEGER PRIMARY KEY,
  checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_requests (
  request_id TEXT PRIMARY KEY,
  request_sha256 TEXT NOT NULL,
  request_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_results (
  request_id TEXT PRIMARY KEY REFERENCES capture_requests(request_id),
  result_sha256 TEXT NOT NULL,
  result_relative_path TEXT NOT NULL,
  result_json TEXT NOT NULL,
  completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_audit (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  recorded_at TEXT NOT NULL,
  request_id TEXT,
  action TEXT NOT NULL,
  detail_sha256 TEXT NOT NULL,
  previous_hash TEXT,
  record_hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS capture_requests_no_update BEFORE UPDATE ON capture_requests
BEGIN SELECT RAISE(ABORT, 'capture_requests is immutable'); END;
CREATE TRIGGER IF NOT EXISTS capture_requests_no_delete BEFORE DELETE ON capture_requests
BEGIN SELECT RAISE(ABORT, 'capture_requests is immutable'); END;
CREATE TRIGGER IF NOT EXISTS capture_results_no_update BEFORE UPDATE ON capture_results
BEGIN SELECT RAISE(ABORT, 'capture_results is immutable'); END;
CREATE TRIGGER IF NOT EXISTS capture_results_no_delete BEFORE DELETE ON capture_results
BEGIN SELECT RAISE(ABORT, 'capture_results is immutable'); END;
CREATE TRIGGER IF NOT EXISTS capture_audit_no_update BEFORE UPDATE ON capture_audit
BEGIN SELECT RAISE(ABORT, 'capture_audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS capture_audit_no_delete BEFORE DELETE ON capture_audit
BEGIN SELECT RAISE(ABORT, 'capture_audit is append-only'); END;
"""
SCHEMA_SHA256 = hashlib.sha256(SCHEMA.encode("utf-8")).hexdigest()


class AuditStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO capture_service_meta(version,checksum) VALUES (1,?)",
                (SCHEMA_SHA256,),
            )
            row = conn.execute("SELECT checksum FROM capture_service_meta WHERE version=1").fetchone()
            if row is None or row[0] != SCHEMA_SHA256:
                raise RuntimeError("capture service schema checksum mismatch")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _append(conn: sqlite3.Connection, *, at: str, request_id: str | None,
                action: str, detail: dict[str, Any]) -> None:
        detail_sha = hashlib.sha256(canonical_json(detail).encode("utf-8")).hexdigest()
        row = conn.execute("SELECT record_hash FROM capture_audit ORDER BY audit_id DESC LIMIT 1").fetchone()
        previous = row[0] if row else None
        body = canonical_json({
            "recorded_at": at, "request_id": request_id, "action": action,
            "detail_sha256": detail_sha, "previous_hash": previous,
        })
        record_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO capture_audit(recorded_at,request_id,action,detail_sha256,previous_hash,record_hash) "
            "VALUES (?,?,?,?,?,?)",
            (at, request_id, action, detail_sha, previous, record_hash),
        )

    def begin_request(self, request_id: str, request: dict[str, Any], *, at: str) -> tuple[str, dict[str, str] | None]:
        request_json = canonical_json(request)
        digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        conflict = False
        result_record = None
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_sha256 FROM capture_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row and row[0] != digest:
                self._append(conn, at=at, request_id=request_id, action="REQUEST_REPLAY_CONFLICT",
                             detail={"request_sha256": digest})
                conflict = True
            elif row is None:
                conn.execute(
                    "INSERT INTO capture_requests(request_id,request_sha256,request_json,first_seen_at) VALUES (?,?,?,?)",
                    (request_id, digest, request_json, at),
                )
                self._append(conn, at=at, request_id=request_id, action="REQUEST_ACCEPTED",
                             detail={"request_sha256": digest})
            if not conflict:
                result = conn.execute(
                    "SELECT result_sha256,result_relative_path,result_json FROM capture_results WHERE request_id=?", (request_id,)
                ).fetchone()
                result_record = ({"sha256": result[0], "relative_path": result[1],
                                  "result_json": result[2]} if result else None)
        if conflict:
            raise CaptureFailure("REQUEST_REPLAY_CONFLICT", "request ID was reused with different content", retryable=False)
        return digest, result_record

    def record_result(self, request_id: str, *, result_sha256: str,
                      relative_path: str, result_json: str, completed_at: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT result_sha256,result_relative_path,result_json FROM capture_results WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing:
                if existing[0] != result_sha256 or existing[1] != relative_path or existing[2] != result_json:
                    raise CaptureFailure("REQUEST_REPLAY_CONFLICT", "immutable result identity conflict", retryable=False)
                return
            conn.execute(
                "INSERT INTO capture_results(request_id,result_sha256,result_relative_path,result_json,completed_at) "
                "VALUES (?,?,?,?,?)",
                (request_id, result_sha256, relative_path, result_json, completed_at),
            )
            self._append(conn, at=completed_at, request_id=request_id, action="CAPTURE_COMPLETED",
                         detail={"result_sha256": result_sha256, "relative_path": relative_path})

    def record_failure(self, request_id: str | None, *, code: str, at: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._append(conn, at=at, request_id=request_id, action="CAPTURE_FAILED", detail={"code": code})

    def record_preflight(self, *, manifest_sha256: str, at: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._append(conn, at=at, request_id=None, action="READ_ONLY_PREFLIGHT_COMPLETED",
                         detail={"manifest_sha256": manifest_sha256})

    def audit(self, *, limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("audit limit must be 1..500")
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM capture_audit ORDER BY audit_id")]
        previous = None
        valid = True
        for row in rows:
            body = canonical_json({
                "recorded_at": row["recorded_at"], "request_id": row["request_id"],
                "action": row["action"], "detail_sha256": row["detail_sha256"],
                "previous_hash": row["previous_hash"],
            })
            expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if row["previous_hash"] != previous or row["record_hash"] != expected:
                valid = False
                break
            previous = row["record_hash"]
        return {"chain_valid": valid, "record_count": len(rows), "records": rows[-limit:]}
