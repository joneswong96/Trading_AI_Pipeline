"""Transactional story memory, durable jobs, results, and audit operations."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from contracts import PROJECT_A_GRADE_SCHEMA_V1, canonical_json, validate_contract
from ingest.project_a.database import ProjectADatabase

from .schema import ensure_schema


def utc_z(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _digest(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def _sha(document: Any) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _audit(conn: sqlite3.Connection, *, at: str, action: str, document: dict,
           story_id: str | None = None, job_id: str | None = None) -> str:
    row = conn.execute(
        "SELECT record_hash FROM project_a_analysis_audit ORDER BY audit_id DESC LIMIT 1"
    ).fetchone()
    previous = row["record_hash"] if row else "0" * 64
    envelope = {
        "recorded_at": at,
        "story_id": story_id,
        "job_id": job_id,
        "action": action,
        "document": document,
        "previous_hash": previous,
    }
    record_hash = _sha(envelope)
    conn.execute(
        "INSERT INTO project_a_analysis_audit(recorded_at,story_id,job_id,action,"
        "document_json,previous_hash,record_hash) VALUES (?,?,?,?,?,?,?)",
        (at, story_id, job_id, action, canonical_json(document), previous, record_hash),
    )
    return record_hash


def _active_story(conn: sqlite3.Connection, *, before_source_time: str | None = None) -> sqlite3.Row | None:
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_a_producer_events'"
    ).fetchone() is None:
        return None
    parameters: tuple[str, ...] = ()
    time_clause = ""
    if before_source_time is not None:
        time_clause = "AND e.source_bar_time < ? "
        parameters = (before_source_time,)
    row = conn.execute(
        "SELECT s.* FROM project_a_analysis_stories s "
        "JOIN project_a_producer_events e ON e.canonical_event_id=s.liquidity_event_id "
        "WHERE 1=1 " + time_clause +
        "ORDER BY e.source_bar_time DESC,s.created_at DESC,s.story_id DESC LIMIT 1",
        parameters,
    ).fetchone()
    if row is None:
        return None
    closed = conn.execute(
        "SELECT 1 FROM project_a_story_state_history WHERE story_id=? AND status='CLOSED' LIMIT 1",
        (row["story_id"],),
    ).fetchone()
    return None if closed else row


def _latest_result(conn: sqlite3.Connection, story_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT r.* FROM project_a_analysis_results r "
        "JOIN project_a_analysis_jobs j ON j.analysis_id=r.analysis_id "
        "WHERE r.story_id=? ORDER BY j.e1_count DESC,r.completed_at DESC LIMIT 1",
        (story_id,),
    ).fetchone()


def _bounded_story_context(conn: sqlite3.Connection, story_id: str) -> dict:
    story = conn.execute(
        "SELECT * FROM project_a_analysis_stories WHERE story_id=?", (story_id,)
    ).fetchone()
    state = conn.execute(
        "SELECT * FROM project_a_story_state_history WHERE story_id=? "
        "ORDER BY state_id DESC LIMIT 1", (story_id,),
    ).fetchone()
    analyses = conn.execute(
        "SELECT r.analysis_id,r.parent_analysis_id,r.completed_at,r.grade_json,j.stage,j.e1_count "
        "FROM project_a_analysis_results r JOIN project_a_analysis_jobs j "
        "ON j.analysis_id=r.analysis_id WHERE r.story_id=? "
        "ORDER BY j.e1_count DESC,r.completed_at DESC LIMIT 6", (story_id,),
    ).fetchall()
    return {
        "story": dict(story) if story else None,
        "latest_materialised_state": (
            {
                "status": state["status"],
                "e1_count": state["e1_count"],
                "big_picture": json.loads(state["big_picture_json"]),
                "liquidity_baseline_analysis_id": state["liquidity_baseline_analysis_id"],
                "latest_analysis_id": state["latest_analysis_id"],
                "latest_grade": json.loads(state["latest_grade_json"]) if state["latest_grade_json"] else None,
            } if state else None
        ),
        "prior_analysis_summaries": [
            {
                "analysis_id": row["analysis_id"],
                "parent_analysis_id": row["parent_analysis_id"],
                "stage": row["stage"],
                "e1_count": row["e1_count"],
                "completed_at": row["completed_at"],
                "grade": json.loads(row["grade_json"]),
            }
            for row in reversed(analyses)
        ],
    }


def _e1_delta_evidence_request(conn: sqlite3.Connection, story_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT request_context_json FROM project_a_analysis_jobs WHERE story_id=? "
        "AND stage='LIQ_BASELINE' ORDER BY requested_at LIMIT 1", (story_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("E1 requires a durable LIQ baseline capture request")
    baseline = json.loads(row["request_context_json"])["capture"]["accepted_request"]
    read_ids = {
        "read_9333_xau_current", "read_9333_xau_closed_ohlc_5m",
        "read_9333_xau_macd_5m", "read_9333_renko_5s",
        "read_9333_xau_5s_price_action",
    }
    screenshot_ids = {"screenshot_9333_xau_intraday", "screenshot_9333_renko"}
    reads = [item for item in baseline.get("structured_reads", []) if item.get("request_id") in read_ids]
    screenshots = [
        item for item in baseline.get("screenshot_requests", [])
        if item.get("request_id") in screenshot_ids
    ]
    if {item.get("request_id") for item in reads} != read_ids:
        raise RuntimeError("baseline request cannot provide the bounded E1 read set")
    if {item.get("request_id") for item in screenshots} != screenshot_ids:
        raise RuntimeError("baseline request cannot provide the bounded E1 screenshot set")
    return {
        "schema_version": "project_a.e1_delta_capture/1.0",
        "structured_reads": reads,
        "screenshot_requests": screenshots,
        "source_identities": baseline.get("source_identities", []),
    }


def enqueue_analysis_trigger(
    conn: sqlite3.Connection,
    *,
    canonical_event: Mapping[str, Any],
    recorded_at: datetime,
    evidence_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialise a LIQ/E1 trigger inside the ingest transaction.

    The function is deliberately side-effect free outside SQLite. Provider and
    capture work are owned by the persistent worker after commit.
    """

    event_name = str(canonical_event.get("event"))
    event_id = str(canonical_event["canonical_event_id"])
    at = utc_z(recorded_at)
    if event_name not in {"LIQ_TOUCH", "RENKO_E1"}:
        return {"queued": False, "reason": "NOT_ANALYSIS_TRIGGER"}

    if event_name == "RENKO_E1":
        story = _active_story(conn, before_source_time=str(canonical_event["source_bar_time"]))
        if story is None:
            conn.execute(
                "INSERT OR IGNORE INTO project_a_orphan_e1_telemetry("
                "canonical_event_id,recorded_at,reason,provider_called) VALUES (?,?,?,0)",
                (event_id, at, "NO_PRIOR_ACTIVE_LIQ_STORY"),
            )
            _audit(conn, at=at, action="ORPHAN_E1_RECORDED", document={"canonical_event_id": event_id})
            return {"queued": False, "orphan": True, "reason": "NO_PRIOR_ACTIVE_LIQ_STORY"}
        story_id = story["story_id"]
        row = conn.execute(
            "SELECT COALESCE(MAX(e1_count),0) AS count FROM project_a_analysis_jobs "
            "WHERE story_id=? AND stage='E1_DELTA'", (story_id,),
        ).fetchone()
        e1_count = int(row["count"]) + 1
        stage = "E1_DELTA"
        capture_scope = "BOUNDED_DELTA"
        latest = _latest_result(conn, story_id)
        parent_analysis_id = latest["analysis_id"] if latest else None
        context = _bounded_story_context(conn, story_id)
        effective_evidence_request = _e1_delta_evidence_request(conn, story_id)
    else:
        story_id = _digest("story_", event_id, at)
        conn.execute(
            "INSERT INTO project_a_analysis_stories(story_id,liquidity_event_id,symbol,feed,"
            "created_at,mode,execution_environment,live_execution,order_placement) "
            "VALUES (?,?,?,?,?,'SHADOW','MT5_DEMO',0,0)",
            (story_id, event_id, "XAUUSD", "ICMARKETS", at),
        )
        stage = "LIQ_BASELINE"
        capture_scope = "FULL_BASELINE"
        e1_count = 0
        parent_analysis_id = None
        context = {
            "story": {"story_id": story_id, "symbol": "XAUUSD", "feed": "ICMARKETS"},
            "latest_materialised_state": None,
            "prior_analysis_summaries": [],
            "big_picture": {"symbol": "XAUUSD", "feed": "ICMARKETS", "status": "TO_BE_CAPTURED"},
        }
        effective_evidence_request = dict(evidence_request or {})
        _audit(
            conn, at=at, action="STORY_CREATED", story_id=story_id,
            document={"liquidity_event_id": event_id, "e1_count": 0},
        )

    analysis_id = _digest("analysis_", story_id, event_id, stage, str(e1_count))
    job_id = _digest("job_", analysis_id)
    request_context = {
        "schema_version": "project_a.analysis_job/1.0",
        "story_id": story_id,
        "analysis_id": analysis_id,
        "parent_analysis_id": parent_analysis_id,
        "stage": stage,
        "e1_count": e1_count,
        "canonical_event": dict(canonical_event),
        "story_memory": context,
        "capture": {
            "scope": capture_scope,
            "mode": "MCP_STRUCTURED_READS_AND_SCREENSHOTS",
            "accepted_request": effective_evidence_request,
        },
        "safety": {
            "symbol": "XAUUSD", "mode": "SHADOW", "execution_environment": "MT5_DEMO",
            "live_execution": False, "order_placement": False, "broker": False,
            "mt5_connection": False, "writers": False,
        },
    }
    context_json = canonical_json(request_context)
    conn.execute(
        "INSERT INTO project_a_analysis_jobs(job_id,analysis_id,story_id,canonical_event_id,"
        "parent_analysis_id,stage,e1_count,requested_at,capture_scope,evidence_acquisition_mode,"
        "request_context_json,request_context_sha256,provider_tools_enabled,writer_enabled,"
        "broker_enabled,order_enabled) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0)",
        (job_id, analysis_id, story_id, event_id, parent_analysis_id, stage, e1_count, at,
         capture_scope, "MCP_STRUCTURED_READS_AND_SCREENSHOTS", context_json,
         hashlib.sha256(context_json.encode("utf-8")).hexdigest()),
    )
    conn.execute(
        "INSERT INTO project_a_analysis_job_status_history(job_id,status,recorded_at) "
        "VALUES (?,'PENDING_CAPTURE',?)", (job_id, at),
    )
    _audit(
        conn, at=at, action="ANALYSIS_JOB_QUEUED", story_id=story_id, job_id=job_id,
        document={"analysis_id": analysis_id, "stage": stage, "e1_count": e1_count,
                  "parent_analysis_id": parent_analysis_id, "capture_scope": capture_scope},
    )
    return {"queued": True, "story_id": story_id, "job_id": job_id,
            "analysis_id": analysis_id, "stage": stage, "e1_count": e1_count}


@dataclass(frozen=True)
class CapturedEvidence:
    manifest: dict[str, Any]
    structured_evidence: dict[str, Any]
    images: tuple[dict[str, Any], ...] = ()

    def validate(self) -> None:
        required = {
            "status": "COMPLETED", "symbol": "XAUUSD", "feed": "ICMARKETS",
            "evidence_freshness": "FRESH", "structured_reads_complete": True,
            "screenshots_complete": True, "capture_method": "MCP",
        }
        if any(self.manifest.get(key) != value for key, value in required.items()):
            raise ValueError("capture manifest is incomplete or outside approved authority")
        for key in ("job_id", "stage", "capture_scope", "source_event_id", "captured_at"):
            if not isinstance(self.manifest.get(key), str) or not self.manifest[key]:
                raise ValueError(f"capture manifest {key} binding is required")
        request_hash = self.manifest.get("capture_request_sha256")
        if (
            not isinstance(request_hash, str) or len(request_hash) != 64
            or any(character not in "0123456789abcdef" for character in request_hash)
        ):
            raise ValueError("capture request SHA-256 binding is required")
        try:
            captured_at = self.manifest["captured_at"]
            if not captured_at.endswith("Z"):
                raise ValueError
            datetime.fromisoformat(captured_at[:-1] + "+00:00")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("capture timestamp must be RFC3339 UTC") from exc
        if not isinstance(self.structured_evidence, dict) or not self.structured_evidence:
            raise ValueError("structured MCP evidence is required")
        if not self.images:
            raise ValueError("at least one MCP screenshot is required")
        for image in self.images:
            if set(image) != {"evidence_id", "path", "media_type", "sha256"}:
                raise ValueError("image manifest fields are invalid")
            path = Path(image["path"])
            if image["media_type"] not in {"image/png", "image/jpeg", "image/webp"}:
                raise ValueError("image media type is not approved")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != image["sha256"]:
                raise ValueError("image evidence hash mismatch")
            data = path.read_bytes()
            signature_valid = (
                image["media_type"] == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")
                or image["media_type"] == "image/jpeg" and data.startswith(b"\xff\xd8\xff")
                or image["media_type"] == "image/webp"
                and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
            )
            if not signature_valid:
                raise ValueError("image bytes do not match the declared media type")


def _parse_capture_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be RFC3339 UTC") from exc
    return parsed.astimezone(timezone.utc)


def _validate_source_time_field(value: Any, field: str, timeframes: list[str]) -> None:
    if isinstance(value, dict):
        if set(value) != set(timeframes):
            raise ValueError(f"{field} must contain the exact requested timeframe keys")
        for timeframe in timeframes:
            _parse_capture_time(value[timeframe], f"{field}.{timeframe}")
        return
    if len(timeframes) != 1:
        raise ValueError(f"{field} must contain the exact requested timeframe keys")
    _parse_capture_time(value, field)


def _validate_capture_results(evidence: CapturedEvidence, capture_request: dict, at: datetime) -> None:
    def verified_source(requested: Any, actual: Any) -> bool:
        if not isinstance(requested, dict) or not isinstance(actual, dict):
            return False
        policy_fields = (
            "role", "port", "layout_id", "symbol", "feed", "timeframes", "chart_types"
        )
        target = actual.get("target_id")
        return (
            set(actual) == set(requested)
            and all(actual.get(key) == requested.get(key) for key in policy_fields)
            and isinstance(target, str) and target
            and not target.startswith("UNBOUND_REQUIRES_PREFLIGHT:")
        )

    if set(evidence.structured_evidence) != {"structured_read_results", "screenshot_results"}:
        raise ValueError("structured evidence contains unrequested top-level fields")
    captured_at = _parse_capture_time(evidence.manifest["captured_at"], "captured_at")
    age = at.astimezone(timezone.utc) - captured_at
    if not timedelta(seconds=-5) <= age <= timedelta(minutes=5):
        raise ValueError("capture timestamp is outside the five-minute completion window")
    requested_reads = {
        item["request_id"]: item for item in capture_request.get("accepted_request", {}).get(
            "structured_reads", []
        )
    }
    results = evidence.structured_evidence.get("structured_read_results")
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise ValueError("structured_read_results must be a list of objects")
    result_by_id = {item.get("request_id"): item for item in results}
    if len(result_by_id) != len(results) or set(result_by_id) != set(requested_reads):
        raise ValueError("structured read result IDs do not match the accepted request")
    for request_id, request in requested_reads.items():
        result = result_by_id[request_id]
        status = result.get("status")
        if status == "UNAVAILABLE" and request.get("required") is False:
            if set(result) != {"request_id", "status", "reason"}:
                raise ValueError(f"optional read {request_id} unavailable result has extra fields")
            continue
        expected_result_fields = {
            "request_id", "status", "source", "read_kind", "timeframes",
            "closed_bars_only", "indicator_parameters", "fields", "observed_at",
            "closed_bars_only_verified", "target_binding_verified",
        }
        if set(result) != expected_result_fields:
            raise ValueError(f"structured read {request_id} result fields are not exact")
        if status != "COMPLETED":
            raise ValueError(f"required structured read {request_id} is incomplete")
        exact_fields = {
            "read_kind": request.get("read_kind"),
            "timeframes": request.get("timeframes"),
            "closed_bars_only": request.get("closed_bars_only"),
            "indicator_parameters": request.get("indicator_parameters"),
        }
        if any(result.get(key) != value for key, value in exact_fields.items()):
            raise ValueError(f"structured read {request_id} source policy mismatch")
        if not verified_source(request.get("source"), result.get("source")):
            raise ValueError(f"structured read {request_id} live target binding mismatch")
        if result.get("target_binding_verified") is not True:
            raise ValueError(f"structured read {request_id} target binding is unverified")
        fields = result.get("fields")
        if not isinstance(fields, dict) or set(request.get("fields", [])) != set(fields):
            raise ValueError(f"structured read {request_id} omitted required fields")
        observed_at = _parse_capture_time(result.get("observed_at"), f"{request_id}.observed_at")
        observed_age = captured_at - observed_at
        if not timedelta(seconds=-5) <= observed_age <= timedelta(minutes=5):
            raise ValueError(f"structured read {request_id} observation is stale")
        for time_field in ("source_time", "source_bar_time"):
            if time_field in request.get("fields", []):
                _validate_source_time_field(
                    fields.get(time_field), f"{request_id}.{time_field}",
                    list(request.get("timeframes", [])),
                )
        if "confirmed" in request.get("fields", []) and fields.get("confirmed") is not True:
            raise ValueError(f"structured read {request_id} is not confirmed")
        if "symbol" in request.get("fields", []) and fields.get("symbol") != request["source"]["symbol"]:
            raise ValueError(f"structured read {request_id} symbol mismatch")
        if "feed" in request.get("fields", []) and fields.get("feed") != request["source"]["feed"]:
            raise ValueError(f"structured read {request_id} feed mismatch")
        if request.get("closed_bars_only") and result.get("closed_bars_only_verified") is not True:
            raise ValueError(f"structured read {request_id} did not attest closed bars")
    screenshot_requests = capture_request.get("accepted_request", {}).get("screenshot_requests", [])
    screenshot_by_id = {item["request_id"]: item for item in screenshot_requests}
    required_ids = {item["request_id"] for item in screenshot_requests if item.get("required", True)}
    optional_ids = {item["request_id"] for item in screenshot_requests if not item.get("required", True)}
    actual_ids = {item["evidence_id"] for item in evidence.images}
    if not required_ids <= actual_ids or not actual_ids <= required_ids | optional_ids:
        raise ValueError("MCP screenshot evidence IDs do not match the accepted request")
    screenshot_results = evidence.structured_evidence.get("screenshot_results")
    if not isinstance(screenshot_results, list) or any(
        not isinstance(item, dict) for item in screenshot_results
    ):
        raise ValueError("screenshot_results must be a list of objects")
    screenshot_result_by_id = {item.get("request_id"): item for item in screenshot_results}
    if len(screenshot_result_by_id) != len(screenshot_results) or set(screenshot_result_by_id) != actual_ids:
        raise ValueError("screenshot result IDs do not match returned image evidence")
    for request_id, result in screenshot_result_by_id.items():
        request = screenshot_by_id[request_id]
        if set(result) != {
            "request_id", "status", "source", "observed_at", "target_binding_verified"
        }:
            raise ValueError(f"screenshot {request_id} result fields are not exact")
        if (
            result.get("status") != "COMPLETED"
            or result.get("target_binding_verified") is not True
            or not verified_source(request.get("source"), result.get("source"))
        ):
            raise ValueError(f"screenshot {request_id} source binding is unverified")
        observed_at = _parse_capture_time(result.get("observed_at"), f"{request_id}.observed_at")
        observed_age = captured_at - observed_at
        if not timedelta(seconds=-5) <= observed_age <= timedelta(minutes=5):
            raise ValueError(f"screenshot {request_id} is stale")


class AnalysisStore:
    def __init__(self, path: str | Path, *, now: datetime | None = None):
        self.database = ProjectADatabase(path)
        applied = utc_z(now or datetime.now(timezone.utc))
        self.database.migrate(applied)
        conn = self.database.connect()
        try:
            ensure_schema(conn, applied)
        finally:
            conn.close()

    def pending_capture_jobs(self, *, at: datetime | None = None) -> tuple[dict[str, Any], ...]:
        at_text = utc_z(at or datetime.now(timezone.utc))
        conn = self.database.connect()
        try:
            rows = conn.execute(
                "SELECT j.* FROM project_a_analysis_jobs j JOIN project_a_analysis_job_status_history s "
                "ON s.status_id=(SELECT MAX(s2.status_id) FROM project_a_analysis_job_status_history s2 "
                "WHERE s2.job_id=j.job_id) WHERE s.status='PENDING_CAPTURE' "
                "AND (s.lease_expires_at IS NULL OR s.lease_expires_at<=?) "
                "AND NOT EXISTS (SELECT 1 FROM project_a_story_state_history h "
                "WHERE h.story_id=j.story_id AND h.status='CLOSED') "
                "ORDER BY j.requested_at,j.job_id", (at_text,)
            ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            conn.close()

    def claim_capture_job(self, *, worker_id: str, at: datetime,
                          lease_seconds: int = 90) -> dict[str, Any] | None:
        if not 10 <= lease_seconds <= 300:
            raise ValueError("capture lease must be 10..300 seconds")
        at_text = utc_z(at)
        with self.database.transaction(immediate=True) as conn:
            expired = conn.execute(
                "SELECT j.job_id,s.worker_id FROM project_a_analysis_jobs j "
                "JOIN project_a_analysis_job_status_history s ON s.status_id=("
                "SELECT MAX(s2.status_id) FROM project_a_analysis_job_status_history s2 "
                "WHERE s2.job_id=j.job_id) WHERE s.status='CLAIMED' "
                "AND s.worker_id LIKE 'capture:%' AND s.lease_expires_at<=? "
                "ORDER BY j.requested_at,j.job_id LIMIT 1", (at_text,),
            ).fetchone()
            if expired is not None:
                retry_at = utc_z(at + timedelta(seconds=30))
                conn.execute(
                    "INSERT INTO project_a_analysis_job_status_history("
                    "job_id,status,recorded_at,worker_id,lease_expires_at,failure_code,detail) "
                    "VALUES (?,'PENDING_CAPTURE',?,?,?,?,?)",
                    (expired["job_id"], at_text, worker_id, retry_at,
                     "CAPTURE_LEASE_EXPIRED", "capture owner exited before completing its lease"),
                )
                _audit(conn, at=at_text, action="MCP_CAPTURE_LEASE_EXPIRED",
                       job_id=expired["job_id"], document={"retry_at": retry_at})
                return None
            row = conn.execute(
                "SELECT j.* FROM project_a_analysis_jobs j "
                "JOIN project_a_analysis_job_status_history s ON s.status_id=("
                "SELECT MAX(s2.status_id) FROM project_a_analysis_job_status_history s2 "
                "WHERE s2.job_id=j.job_id) WHERE s.status='PENDING_CAPTURE' "
                "AND (s.lease_expires_at IS NULL OR s.lease_expires_at<=?) "
                "AND NOT EXISTS (SELECT 1 FROM project_a_story_state_history h "
                "WHERE h.story_id=j.story_id AND h.status='CLOSED') "
                "ORDER BY j.requested_at,j.job_id LIMIT 1", (at_text,),
            ).fetchone()
            if row is None:
                return None
            lease_token = hashlib.sha256(os.urandom(32)).hexdigest()
            owner = f"capture:{worker_id}:{lease_token}"
            expiry = utc_z(at + timedelta(seconds=lease_seconds))
            conn.execute(
                "INSERT INTO project_a_analysis_job_status_history("
                "job_id,status,recorded_at,worker_id,lease_expires_at) "
                "VALUES (?,'CLAIMED',?,?,?)",
                (row["job_id"], at_text, owner, expiry),
            )
            _audit(conn, at=at_text, action="MCP_CAPTURE_CLAIMED", job_id=row["job_id"],
                   document={"lease_expires_at": expiry})
            result = dict(row)
            result["capture_lease_token"] = lease_token
            return result

    def capture_failure(self, job_id: str, *, at: datetime, worker_id: str,
                        lease_token: str,
                        code: str, detail: str, maximum_attempts: int = 5) -> dict[str, str]:
        if not 1 <= maximum_attempts <= 10:
            raise ValueError("maximum capture attempts must be 1..10")
        at_text = utc_z(at)
        bounded_detail = str(detail)[:400]
        with self.database.transaction(immediate=True) as conn:
            latest = conn.execute(
                "SELECT status,worker_id,lease_expires_at FROM project_a_analysis_job_status_history WHERE job_id=? "
                "ORDER BY status_id DESC LIMIT 1", (job_id,),
            ).fetchone()
            if latest is None:
                raise KeyError(job_id)
            owner = f"capture:{worker_id}:{lease_token}"
            if (
                latest["status"] != "CLAIMED" or latest["worker_id"] != owner
                or latest["lease_expires_at"] < at_text
            ):
                raise RuntimeError("capture lease ownership mismatch or expired lease")
            attempts = int(conn.execute(
                "SELECT COUNT(*) FROM project_a_analysis_job_status_history "
                "WHERE job_id=? AND status='PENDING_CAPTURE' AND failure_code IS NOT NULL",
                (job_id,),
            ).fetchone()[0]) + 1
            if attempts >= maximum_attempts:
                failure_code = "CAPTURE_RETRY_EXHAUSTED"
                conn.execute(
                    "INSERT INTO project_a_analysis_job_status_history("
                    "job_id,status,recorded_at,worker_id,failure_code,detail) "
                    "VALUES (?,'TECHNICAL_FAILURE',?,?,?,?)",
                    (job_id, at_text, worker_id, failure_code, bounded_detail),
                )
                _audit(conn, at=at_text, action="MCP_CAPTURE_RETRY_EXHAUSTED", job_id=job_id,
                       document={"attempt": attempts, "failure_code": code})
                return {"status": "TECHNICAL_FAILURE", "failure_code": failure_code}
            delay_seconds = min(30 * (2 ** (attempts - 1)), 900)
            retry_at = utc_z(at + timedelta(seconds=delay_seconds))
            conn.execute(
                "INSERT INTO project_a_analysis_job_status_history("
                "job_id,status,recorded_at,worker_id,lease_expires_at,failure_code,detail) "
                "VALUES (?,'PENDING_CAPTURE',?,?,?,?,?)",
                (job_id, at_text, worker_id, retry_at, code, bounded_detail),
            )
            _audit(conn, at=at_text, action="MCP_CAPTURE_RETRY_SCHEDULED", job_id=job_id,
                   document={"attempt": attempts, "failure_code": code, "retry_at": retry_at})
            return {"status": "PENDING_CAPTURE", "failure_code": code}

    def record_capture(self, job_id: str, evidence: CapturedEvidence, *, at: datetime,
                       worker_id: str, lease_token: str) -> None:
        evidence.validate()
        at_text = utc_z(at)
        with self.database.transaction(immediate=True) as conn:
            job = conn.execute(
                "SELECT stage,capture_scope,canonical_event_id,request_context_json "
                "FROM project_a_analysis_jobs WHERE job_id=?",
                (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            bindings = {
                "job_id": job_id, "stage": job["stage"], "capture_scope": job["capture_scope"],
                "source_event_id": job["canonical_event_id"],
            }
            if any(evidence.manifest.get(key) != value for key, value in bindings.items()):
                raise ValueError("capture does not match its durable job binding")
            capture_request = json.loads(job["request_context_json"])["capture"]
            _validate_capture_results(evidence, capture_request, at)
            expected_capture_hash = _sha(capture_request)
            if evidence.manifest["capture_request_sha256"] != expected_capture_hash:
                raise ValueError("capture does not match the accepted MCP request")
            structured_json = canonical_json(evidence.structured_evidence)
            image_manifest = list(evidence.images)
            maximum_images = 5 if job["stage"] == "LIQ_BASELINE" else 2
            maximum_image_bytes = 20_000_000 if job["stage"] == "LIQ_BASELINE" else 8_000_000
            total_image_bytes = sum(Path(item["path"]).stat().st_size for item in evidence.images)
            if len(evidence.images) > maximum_images or total_image_bytes > maximum_image_bytes:
                raise ValueError("capture image evidence exceeds the stage budget")
            screenshot_requests = capture_request.get("accepted_request", {}).get(
                "screenshot_requests", []
            )
            minimum_images = sum(1 for item in screenshot_requests if item.get("required", True))
            if not minimum_images <= len(evidence.images) <= len(screenshot_requests):
                raise ValueError("capture screenshot count does not match the accepted request")
            if len(structured_json.encode("utf-8")) > 262_144:
                raise ValueError("structured evidence exceeds 262144 bytes")
            latest = conn.execute(
                "SELECT status,worker_id,lease_expires_at FROM project_a_analysis_job_status_history WHERE job_id=? "
                "ORDER BY status_id DESC LIMIT 1", (job_id,),
            ).fetchone()
            if latest is None:
                raise KeyError(job_id)
            owner = f"capture:{worker_id}:{lease_token}"
            if (
                latest["status"] != "CLAIMED" or latest["worker_id"] != owner
                or latest["lease_expires_at"] < at_text
            ):
                raise RuntimeError("capture lease ownership mismatch or expired lease")
            manifest_json = canonical_json(evidence.manifest)
            manifest_sha = _sha({
                "manifest": evidence.manifest,
                "structured_evidence_sha256": hashlib.sha256(
                    structured_json.encode("utf-8")
                ).hexdigest(),
                "images": [
                    {key: item[key] for key in ("evidence_id", "media_type", "sha256")}
                    for item in image_manifest
                ],
            })
            capture_id = _digest("capture_", job_id, manifest_sha)
            conn.execute(
                "INSERT INTO project_a_analysis_captures(capture_id,job_id,completed_at,manifest_json,"
                "manifest_sha256,structured_evidence_json,image_manifest_json,capture_complete) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (capture_id, job_id, at_text, manifest_json, manifest_sha,
                 structured_json, canonical_json(image_manifest)),
            )
            conn.execute(
                "INSERT INTO project_a_analysis_job_status_history(job_id,status,recorded_at) "
                "VALUES (?,'CAPTURED',?)", (job_id, at_text),
            )
            _audit(conn, at=at_text, action="MCP_CAPTURE_COMPLETED", job_id=job_id,
                   document={"capture_id": capture_id, "manifest_sha256": manifest_sha,
                             "image_count": len(evidence.images)})

    def claim_next(self, *, worker_id: str, at: datetime, lease_seconds: int = 180,
                   job_id: str | None = None) -> dict | None:
        at_text = utc_z(at)
        expiry = utc_z(at + timedelta(seconds=lease_seconds))
        with self.database.transaction(immediate=True) as conn:
            parameters = (at_text, job_id) if job_id else (at_text,)
            row = conn.execute(
                "SELECT j.*,s.status,s.lease_expires_at FROM project_a_analysis_jobs j "
                "JOIN project_a_analysis_job_status_history s ON s.status_id=(SELECT MAX(s2.status_id) "
                "FROM project_a_analysis_job_status_history s2 WHERE s2.job_id=j.job_id) "
                "WHERE (s.status='CAPTURED' OR (s.status='CLAIMED' AND s.lease_expires_at<?)) "
                "AND (s.status!='CLAIMED' OR s.worker_id NOT LIKE 'capture:%') "
                + ("AND j.job_id=? " if job_id else "") +
                "AND NOT EXISTS (SELECT 1 FROM project_a_story_state_history h "
                "WHERE h.story_id=j.story_id AND h.status='CLOSED') "
                "AND NOT EXISTS (SELECT 1 FROM project_a_analysis_jobs prior "
                "JOIN project_a_analysis_job_status_history ps ON ps.status_id=(SELECT MAX(ps2.status_id) "
                "FROM project_a_analysis_job_status_history ps2 WHERE ps2.job_id=prior.job_id) "
                "WHERE prior.story_id=j.story_id AND (prior.e1_count < j.e1_count "
                "OR (prior.e1_count=j.e1_count AND prior.requested_at<j.requested_at)) "
                "AND ps.status!='COMPLETED') "
                "ORDER BY j.requested_at,j.job_id LIMIT 1", parameters,
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "INSERT INTO project_a_analysis_job_status_history(job_id,status,recorded_at,worker_id,lease_expires_at) "
                "VALUES (?,'CLAIMED',?,?,?)", (row["job_id"], at_text, worker_id, expiry),
            )
            _audit(conn, at=at_text, action="JOB_CLAIMED", story_id=row["story_id"],
                   job_id=row["job_id"], document={"worker_id": worker_id, "lease_expires_at": expiry})
            return dict(row)

    def load_job_bundle(self, job_id: str) -> tuple[dict, CapturedEvidence]:
        conn = self.database.connect()
        try:
            job = conn.execute("SELECT * FROM project_a_analysis_jobs WHERE job_id=?", (job_id,)).fetchone()
            capture = conn.execute("SELECT * FROM project_a_analysis_captures WHERE job_id=?", (job_id,)).fetchone()
            if job is None or capture is None or capture["capture_complete"] != 1:
                raise RuntimeError("complete capture is required")
            evidence = CapturedEvidence(
                manifest=json.loads(capture["manifest_json"]),
                structured_evidence=json.loads(capture["structured_evidence_json"]),
                images=tuple(json.loads(capture["image_manifest_json"])),
            )
            evidence.validate()
            document = dict(job)
            document["request_context"] = json.loads(job["request_context_json"])
            if job["stage"] == "E1_DELTA":
                document["request_context"]["story_memory"] = _bounded_story_context(
                    conn, job["story_id"]
                )
            document["capture_manifest_sha256"] = capture["manifest_sha256"]
            return document, evidence
        finally:
            conn.close()

    def begin_provider_attempt(self, job: dict, *, model: str, request_manifest_sha256: str,
                               client_request_id: str, at: datetime) -> str:
        idempotency_key = "project-a-" + job["analysis_id"]
        at_text = utc_z(at)
        with self.database.transaction(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM project_a_provider_attempts WHERE job_id=? "
                "AND idempotency_key=? AND outcome='REQUESTED'", (job["job_id"], idempotency_key),
            ).fetchone()
            if existing:
                if (
                    existing["model"] != model
                    or existing["request_manifest_sha256"] != request_manifest_sha256
                    or existing["client_request_id"] != client_request_id
                ):
                    raise RuntimeError("provider retry identity conflicts with durable attempt")
                return existing["attempt_id"]
            attempt_id = _digest("provider_attempt_", job["job_id"], idempotency_key)
            conn.execute(
                "INSERT INTO project_a_provider_attempts(attempt_id,job_id,idempotency_key,client_request_id,"
                "model,started_at,outcome,request_manifest_sha256) VALUES (?,?,?,?,?,?,'REQUESTED',?)",
                (attempt_id, job["job_id"], idempotency_key, client_request_id, model, at_text,
                 request_manifest_sha256),
            )
            _audit(conn, at=at_text, action="PROVIDER_REQUEST_DURABLY_STARTED",
                   story_id=job["story_id"], job_id=job["job_id"],
                   document={"attempt_id": attempt_id, "client_request_id": client_request_id,
                             "idempotency_key": idempotency_key, "model": model,
                             "request_manifest_sha256": request_manifest_sha256})
            return attempt_id

    def complete(self, *, job: dict, grade: dict, model: str, client_request_id: str,
                 response_id: str, provider_request_id: str | None, raw_response_sha256: str,
                 request_manifest_sha256: str, at: datetime) -> None:
        at_text = utc_z(at)
        validate_contract(PROJECT_A_GRADE_SCHEMA_V1, grade)
        expected_identity = {
            "story_id": job["story_id"], "analysis_id": job["analysis_id"],
            "parent_analysis_id": job["parent_analysis_id"], "stage": job["stage"],
            "e1_count": job["e1_count"],
        }
        if any(grade.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError("validated Grade identity changed before persistence")
        confidence = grade["confidence"]
        expected_band = (
            "LOW" if confidence < 0.4 else "MEDIUM" if confidence < 0.6
            else "HIGH" if confidence < 0.8 else "VERY_HIGH"
        )
        if grade["probability_band"] != expected_band:
            raise RuntimeError("Grade probability band changed before persistence")
        if grade["recommendation"] != "WAIT" and (
            grade["grade"] == "UNGRADABLE" or grade["evidence_freshness"] == "STALE"
        ):
            raise RuntimeError("unsafe stale/ungradable recommendation rejected at persistence")
        grade_json = canonical_json(grade)
        with self.database.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM project_a_analysis_results WHERE analysis_id=?",
                            (job["analysis_id"],)).fetchone():
                return
            attempt = conn.execute(
                "SELECT * FROM project_a_provider_attempts WHERE job_id=? AND outcome='REQUESTED' "
                "ORDER BY started_at DESC LIMIT 1", (job["job_id"],),
            ).fetchone()
            if attempt is None:
                raise RuntimeError("durable provider attempt is missing")
            validated_attempt = _digest("provider_validated_", attempt["attempt_id"], response_id)
            conn.execute(
                "INSERT INTO project_a_provider_attempts(attempt_id,job_id,idempotency_key,client_request_id,"
                "provider_response_id,provider_request_id,model,started_at,ended_at,outcome,"
                "request_manifest_sha256,raw_response_sha256) VALUES (?,?,?,?,?,?,?,?,?,'VALIDATED',?,?)",
                (validated_attempt, job["job_id"], attempt["idempotency_key"], client_request_id,
                 response_id, provider_request_id, model, attempt["started_at"], at_text,
                 request_manifest_sha256, raw_response_sha256),
            )
            conn.execute(
                "INSERT INTO project_a_analysis_results(analysis_id,story_id,job_id,parent_analysis_id,"
                "completed_at,grade_json,grade_sha256,evidence_manifest_sha256,client_request_id,"
                "provider_response_id,provider_request_id,model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (job["analysis_id"], job["story_id"], job["job_id"], job["parent_analysis_id"],
                 at_text, grade_json, hashlib.sha256(grade_json.encode("utf-8")).hexdigest(),
                 job["capture_manifest_sha256"], client_request_id, response_id,
                 provider_request_id, model),
            )
            previous = conn.execute(
                "SELECT * FROM project_a_story_state_history WHERE story_id=? "
                "ORDER BY state_id DESC LIMIT 1", (job["story_id"],),
            ).fetchone()
            if previous and previous["status"] == "ACTIVE" and previous["e1_count"] > job["e1_count"]:
                raise RuntimeError("story state monotonicity violation")
            big_picture = (
                {
                    "symbol": "XAUUSD", "feed": "ICMARKETS",
                    "established_by": job["analysis_id"],
                    "expected_direction": grade["expected_direction"],
                    "inherited_thesis": grade["inherited_thesis"],
                    "invalidation": grade["invalidation"],
                }
                if job["stage"] == "LIQ_BASELINE" else
                json.loads(previous["big_picture_json"]) if previous else
                {"symbol": "XAUUSD", "feed": "ICMARKETS"}
            )
            baseline = (
                job["analysis_id"] if job["stage"] == "LIQ_BASELINE" else
                previous["liquidity_baseline_analysis_id"] if previous else None
            )
            closed = conn.execute(
                "SELECT 1 FROM project_a_story_state_history WHERE story_id=? AND status='CLOSED' LIMIT 1",
                (job["story_id"],),
            ).fetchone() is not None
            if not closed:
                conn.execute(
                    "INSERT INTO project_a_story_state_history(story_id,analysis_id,status,e1_count,"
                    "big_picture_json,liquidity_baseline_analysis_id,latest_analysis_id,latest_grade_json,"
                    "decision,recorded_at,actor) VALUES (?,?,'ACTIVE',?,?,?,?,?,NULL,?,'PROJECT_A_ANALYSIS_WORKER')",
                    (job["story_id"], job["analysis_id"], job["e1_count"], canonical_json(big_picture),
                     baseline, job["analysis_id"], grade_json, at_text),
                )
            conn.execute(
                "INSERT INTO project_a_analysis_job_status_history(job_id,status,recorded_at,worker_id) "
                "VALUES (?,'COMPLETED',?,?)", (job["job_id"], at_text, "PROJECT_A_ANALYSIS_WORKER"),
            )
            _audit(conn, at=at_text, action=(
                       "VALIDATED_GRADE_IGNORED_AFTER_CLOSURE" if closed
                       else "VALIDATED_GRADE_MATERIALISED"),
                   story_id=job["story_id"], job_id=job["job_id"],
                   document={"analysis_id": job["analysis_id"], "stage": job["stage"],
                             "e1_count": job["e1_count"], "response_id": response_id,
                             "provider_request_id": provider_request_id, "model": model,
                             "recommendation": grade["recommendation"]})

    def technical_failure(self, job: dict, *, code: str, detail: str, at: datetime,
                          model: str | None = None) -> None:
        at_text = utc_z(at)
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO project_a_analysis_job_status_history(job_id,status,recorded_at,worker_id,"
                "failure_code,detail) VALUES (?,'TECHNICAL_FAILURE',?,'PROJECT_A_ANALYSIS_WORKER',?,?)",
                (job["job_id"], at_text, code, detail[:240]),
            )
            attempt = conn.execute(
                "SELECT * FROM project_a_provider_attempts WHERE job_id=? AND outcome='REQUESTED' "
                "ORDER BY started_at DESC LIMIT 1", (job["job_id"],),
            ).fetchone()
            if attempt is not None:
                failed_id = _digest("provider_failed_", attempt["attempt_id"], code)
                conn.execute(
                    "INSERT OR IGNORE INTO project_a_provider_attempts(attempt_id,job_id,idempotency_key,"
                    "client_request_id,model,started_at,ended_at,outcome,failure_code,request_manifest_sha256) "
                    "VALUES (?,?,?,?,?,?,?,'TECHNICAL_FAILURE',?,?)",
                    (failed_id, job["job_id"], attempt["idempotency_key"], attempt["client_request_id"],
                     model or attempt["model"], attempt["started_at"], at_text, code,
                     attempt["request_manifest_sha256"]),
                )
            _audit(conn, at=at_text, action="TECHNICAL_FAILURE", story_id=job["story_id"],
                   job_id=job["job_id"], document={"code": code, "detail": detail[:240]})

    def close_story(self, story_id: str, *, decision: str, at: datetime, actor: str = "JONES") -> None:
        if decision not in {"ENTERED", "SKIPPED"} or actor != "JONES":
            raise ValueError("only Jones ENTERED or SKIPPED may close a story")
        at_text = utc_z(at)
        with self.database.transaction(immediate=True) as conn:
            story = conn.execute("SELECT * FROM project_a_analysis_stories WHERE story_id=?", (story_id,)).fetchone()
            if story is None:
                raise KeyError(story_id)
            previous = conn.execute(
                "SELECT * FROM project_a_story_state_history WHERE story_id=? ORDER BY state_id DESC LIMIT 1",
                (story_id,),
            ).fetchone()
            if previous and previous["status"] == "CLOSED":
                if previous["decision"] == decision:
                    return
                raise RuntimeError("story is already closed with another Jones decision")
            conn.execute(
                "INSERT INTO project_a_story_state_history(story_id,analysis_id,status,e1_count,"
                "big_picture_json,liquidity_baseline_analysis_id,latest_analysis_id,latest_grade_json,"
                "decision,recorded_at,actor) VALUES (?,NULL,'CLOSED',?,?,?,?,?,?,?,'JONES')",
                (story_id, previous["e1_count"] if previous else 0,
                 previous["big_picture_json"] if previous else canonical_json({"symbol": "XAUUSD"}),
                 previous["liquidity_baseline_analysis_id"] if previous else None,
                 previous["latest_analysis_id"] if previous else None,
                 previous["latest_grade_json"] if previous else None, decision, at_text),
            )
            _audit(conn, at=at_text, action="STORY_CLOSED_BY_JONES", story_id=story_id,
                   document={"decision": decision, "actor": "JONES"})

    def heartbeat(self, *, worker_id: str, provider_enabled: bool, at: datetime,
                  error_code: str | None = None) -> None:
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO project_a_analysis_worker_health(worker_id,pid,provider_enabled,last_heartbeat_at,last_error_code) "
                "VALUES (?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET pid=excluded.pid,"
                "provider_enabled=excluded.provider_enabled,last_heartbeat_at=excluded.last_heartbeat_at,"
                "last_error_code=excluded.last_error_code",
                (worker_id, os.getpid(), int(provider_enabled), utc_z(at), error_code),
            )

    def inspect_jobs(self, status: str | None = None) -> list[dict]:
        conn = self.database.connect()
        try:
            rows = conn.execute(
                "SELECT j.*,s.status,s.recorded_at AS status_recorded_at,s.failure_code,s.detail "
                "FROM project_a_analysis_jobs j JOIN project_a_analysis_job_status_history s "
                "ON s.status_id=(SELECT MAX(s2.status_id) FROM project_a_analysis_job_status_history s2 "
                "WHERE s2.job_id=j.job_id) " + ("WHERE s.status=? " if status else "") +
                "ORDER BY j.requested_at,j.job_id", ((status,) if status else ()),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def active_story(self) -> dict | None:
        conn = self.database.connect()
        try:
            story = _active_story(conn)
            return _bounded_story_context(conn, story["story_id"]) if story else None
        finally:
            conn.close()

    def health(self) -> list[dict]:
        conn = self.database.connect()
        try:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM project_a_analysis_worker_health ORDER BY worker_id"
            ).fetchall()]
        finally:
            conn.close()

    def audit(self, *, limit: int = 50) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("audit limit must be 1..500")
        conn = self.database.connect()
        try:
            all_rows = conn.execute(
                "SELECT * FROM project_a_analysis_audit ORDER BY audit_id"
            ).fetchall()
            previous = "0" * 64
            valid = True
            for row in all_rows:
                document = json.loads(row["document_json"])
                envelope = {
                    "recorded_at": row["recorded_at"], "story_id": row["story_id"],
                    "job_id": row["job_id"], "action": row["action"],
                    "document": document, "previous_hash": previous,
                }
                if row["previous_hash"] != previous or _sha(envelope) != row["record_hash"]:
                    valid = False
                    break
                previous = row["record_hash"]
            records = [
                {**dict(row), "document": json.loads(row["document_json"])}
                for row in all_rows[-limit:]
            ]
            for record in records:
                record.pop("document_json", None)
            return {"chain_valid": valid, "record_count": len(all_rows), "records": records}
        finally:
            conn.close()
