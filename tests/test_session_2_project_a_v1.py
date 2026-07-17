from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest.project_a.config import ProjectAConfig
from ingest.project_a.database import (
    MIGRATION_1,
    MIGRATION_1_CHECKSUM,
    MIGRATION_2_CHECKSUM,
    ProjectADatabase,
)
from ingest.project_a.replay import run as replay_run
from ingest.project_a.service import ProjectAIngestService

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads(
    (ROOT / "fixtures/project_a/event_v1_known_vectors.json").read_text(encoding="utf-8")
)["documents"]


class Clock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def raw(name: str) -> bytes:
    return json.dumps(VECTORS[name], ensure_ascii=False, separators=(",", ":")).encode()


def service(tmp_path, *, enabled=True, fail_at=None, at=None):
    clock = Clock(at or datetime(2026, 7, 16, 1, 1, 2, tzinfo=timezone.utc))
    config = ProjectAConfig(
        database_path=tmp_path / "project_a.db", v1_ingest_enabled=enabled
    )
    return (
        ProjectAIngestService(config, clock=clock, v1_fail_at=fail_at),
        clock,
        config,
    )


def scalar(runtime, query, params=()):
    conn = runtime.db.connect()
    try:
        return conn.execute(query, params).fetchone()[0]
    finally:
        conn.close()


def rows(runtime, query, params=()):
    conn = runtime.db.connect()
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def test_v1_is_disabled_by_default_without_activating_receipt_storage(tmp_path):
    runtime, _, _ = service(tmp_path, enabled=False)
    body = raw("rejection_ready")
    result = runtime.receive_v1(body)
    assert result.result_code == "V1_INGEST_DISABLED"
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_raw_receipts") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_receipt_transactions") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_canonical_events") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_outbox") == 0


def test_v1_trusted_ingress_owns_received_at_and_releases_atomic_outbox(tmp_path):
    runtime, _, _ = service(tmp_path)
    result = runtime.receive_v1(raw("rejection_ready"))
    assert (result.result_code, result.http_status) == ("ACCEPTED", 202)
    assert result.event_id.startswith("cevt_")
    assert result.setup_id.startswith("setup_")
    assert result.dispatch_key.startswith("sha256:")
    canonical = json.loads(
        rows(runtime, "SELECT canonical_json FROM project_a_canonical_events")[0][
            "canonical_json"
        ]
    )
    assert canonical["receipt"]["received_at"] == "2026-07-16T01:01:02Z"
    assert "received_at" not in canonical["wire_event"]
    assert canonical["receipt"]["raw_content_hash"] == rows(
        runtime, "SELECT body_hash FROM project_a_raw_receipts"
    )[0]["body_hash"]
    assert canonical["semantic_evidence_hash"].startswith("sha256:")
    claim = rows(
        runtime,
        "SELECT status,dispatch_allowed FROM project_a_receipt_transactions",
    )[0]
    assert claim == {"status": "CONFIRMED", "dispatch_allowed": 1}
    outbox = rows(
        runtime, "SELECT status,release_authorized,payload_json FROM project_a_outbox"
    )[0]
    assert (outbox["status"], outbox["release_authorized"]) == ("PENDING", 1)
    assert "canonical_event" in json.loads(outbox["payload_json"])
    assert runtime.claim_outbox("offline-worker") is not None


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b'{"contract_family":', "WIRE_JSON_INVALID"),
        (b"\xff", "WIRE_NOT_UTF8"),
        (b"[]", "WIRE_JSON_OBJECT_REQUIRED"),
    ],
)
def test_v1_parse_and_shape_rejection_precede_durable_dedupe(tmp_path, body, code):
    runtime, _, _ = service(tmp_path)
    result = runtime.receive_v1(body)
    assert result.result_code == code
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_raw_receipts") == 1
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_receipt_transactions") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_exact_dedupe") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_semantic_dedupe") == 0


def test_exact_and_semantic_duplicates_keep_every_receipt_but_suppress_dispatch(tmp_path):
    runtime, _, _ = service(tmp_path)
    first = runtime.receive_v1(raw("rejection_ready"))
    exact = runtime.receive_v1(raw("rejection_ready"))
    semantic = runtime.receive_v1(raw("rejection_metadata_changed"))
    assert first.result_code == "ACCEPTED"
    assert (exact.result_code, exact.transition_code, exact.duplicate) == (
        "DUPLICATE",
        "EXACT_RECEIPT_DUPLICATE",
        True,
    )
    assert (semantic.result_code, semantic.transition_code, semantic.duplicate) == (
        "DUPLICATE",
        "SEMANTIC_EVIDENCE_DUPLICATE",
        True,
    )
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_raw_receipts") == 3
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_receipt_processing") == 3
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_canonical_events") == 2
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_outbox") == 1


@pytest.mark.parametrize("stage", ["persist", "commit"])
def test_v1_precommit_failure_rolls_back_decision_state_and_outbox(tmp_path, stage):
    runtime, _, _ = service(tmp_path, fail_at=stage)
    result = runtime.receive_v1(raw("rejection_ready"))
    assert result.result_code == "DEDUPE_TRANSACTION_FAILED"
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_raw_receipts") == 1
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_canonical_events") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_setup_state_v1") == 0
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_outbox") == 0
    assert rows(
        runtime, "SELECT status FROM project_a_receipt_transactions"
    ) == [{"status": "ROLLED_BACK"}]


@pytest.mark.parametrize("stage", ["commit_unknown", "confirm"])
def test_v1_commit_unknown_holds_outbox_and_is_never_claimable(tmp_path, stage):
    runtime, _, _ = service(tmp_path, fail_at=stage)
    result = runtime.receive_v1(raw("rejection_ready"))
    assert result.result_code == "DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN"
    assert rows(
        runtime, "SELECT status FROM project_a_receipt_transactions"
    ) == [{"status": "COMMIT_UNKNOWN"}]
    assert rows(
        runtime, "SELECT status,release_authorized FROM project_a_outbox"
    ) == [{"status": "PENDING", "release_authorized": 0}]
    assert runtime.claim_outbox("must-not-release") is None


def test_v1_restart_and_concurrent_receipts_share_durable_dedupe(tmp_path):
    runtime, clock, config = service(tmp_path)
    body = raw("rejection_ready")
    outcomes = []
    barrier = threading.Barrier(2)

    def submit():
        barrier.wait()
        outcomes.append(runtime.receive_v1(body).result_code)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ACCEPTED", "DUPLICATE"]
    restarted = ProjectAIngestService(config, clock=clock, initialize=False)
    assert restarted.receive_v1(body).transition_code == "EXACT_RECEIPT_DUPLICATE"
    assert scalar(restarted, "SELECT COUNT(*) FROM project_a_raw_receipts") == 3
    assert scalar(restarted, "SELECT COUNT(*) FROM project_a_outbox") == 1


@pytest.mark.parametrize(
    ("name", "expected_state"),
    [("setup_invalidation", "SETUP_INVALIDATED"), ("setup_expiry", "SETUP_EXPIRED")],
)
def test_v1_lifecycle_state_is_visible_only_after_confirmed_transaction(
        tmp_path, name, expected_state):
    at = datetime(2026, 7, 16, 1, 31, 2, tzinfo=timezone.utc)
    runtime, _, _ = service(tmp_path, at=at)
    result = runtime.receive_v1(raw(name))
    assert result.result_code == "ACCEPTED"
    assert result.transition_code == expected_state
    assert rows(
        runtime,
        "SELECT s.lifecycle_state,t.status FROM project_a_setup_state_v1 s "
        "JOIN project_a_receipt_transactions t ON t.transaction_id=s.transaction_id",
    ) == [{"lifecycle_state": expected_state, "status": "CONFIRMED"}]
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_outbox") == 0


def test_v1_rejected_terminal_transition_records_no_state_or_dispatch_eligibility(tmp_path):
    at = datetime(2026, 7, 16, 1, 31, 2, tzinfo=timezone.utc)
    runtime, _, _ = service(tmp_path, at=at)
    assert runtime.receive_v1(raw("setup_invalidation")).result_code == "ACCEPTED"

    second = json.loads(raw("setup_invalidation"))
    second["producer_event_id"] = "wevt_xau_20260716_1021"
    second["emitted_at"] = "2026-07-16T01:20:02Z"
    second["evidence"]["invalidation"]["reason_code"] = "M1_STRUCTURE_BROKEN_AGAIN"
    result = runtime.receive_v1(
        json.dumps(second, ensure_ascii=False, separators=(",", ":")).encode()
    )

    assert result.result_code == "ILLEGAL_LIFECYCLE_TRANSITION"
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_setup_state_v1") == 1
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_outbox") == 0
    assert rows(
        runtime,
        "SELECT processing_status,state_mutation_allowed,dispatch_allowed "
        "FROM project_a_receipt_transactions WHERE processing_status='REJECTED'",
    ) == [{
        "processing_status": "REJECTED",
        "state_mutation_allowed": 0,
        "dispatch_allowed": 0,
    }]


def test_stale_ingress_claim_recovery_is_fail_closed(tmp_path):
    runtime, clock, _ = service(tmp_path)
    body = raw("rejection_ready")
    receipt_id = "rcpt_recovery_00000001"
    runtime._store_raw(
        receipt_id,
        body,
        "sha256:" + hashlib.sha256(body).hexdigest(),
        "2026-07-16T01:00:00Z",
        "POST",
        "application/json",
        {},
        True,
    )
    with runtime.db.transaction(immediate=True) as conn:
        conn.execute(
            "INSERT INTO project_a_receipt_transactions("
            "transaction_id,ingest_id,receipt_id,generation,status,claimed_at"
            ") VALUES('tx_recovery_0001',?,?,1,'CLAIMED','2026-07-16T01:00:00Z')",
            (receipt_id, receipt_id),
        )
    clock.value += timedelta(seconds=runtime.config.claim_timeout_seconds + 1)
    assert runtime.recover_abandoned_claims() == 1
    assert rows(
        runtime, "SELECT status,last_error FROM project_a_receipt_transactions"
    ) == [{"status": "ABANDONED", "last_error": "ABANDONED_INGRESS_CLAIM"}]


def test_v1_dry_run_and_commit_replay_are_durable_and_idempotent(tmp_path):
    runtime, _, config = service(tmp_path)
    accepted = runtime.receive_v1(raw("rejection_ready"))
    before = runtime.metrics()
    dry = replay_run(config, selector="receipt", value=accepted.ingest_id)
    assert dry["mode"] == "DRY_RUN"
    assert dry["results"][0]["duplicate"] is True
    assert runtime.metrics() == before
    committed = replay_run(
        config, selector="receipt", value=accepted.ingest_id, commit=True
    )
    assert committed["mode"] == "COMMIT"
    assert committed["results"][0]["duplicate"] is True
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_outbox") == 1
    assert scalar(runtime, "SELECT COUNT(*) FROM project_a_replay_operations") == 1


def test_fresh_and_version_one_migration_record_checksums_and_integrity(tmp_path):
    fresh = ProjectADatabase(tmp_path / "fresh.db")
    fresh.migrate("2026-07-16T01:00:00Z")
    fresh_rows = rows(
        ProjectAIngestService(
            ProjectAConfig(database_path=fresh.path),
            clock=lambda: datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc),
            initialize=False,
        ),
        "SELECT version,checksum FROM project_a_schema_migrations ORDER BY version",
    )
    assert fresh_rows == [
        {"version": 1, "checksum": MIGRATION_1_CHECKSUM},
        {"version": 2, "checksum": MIGRATION_2_CHECKSUM},
    ]

    upgraded_path = tmp_path / "upgraded.db"
    conn = sqlite3.connect(upgraded_path, isolation_level=None)
    try:
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + MIGRATION_1
            + "\nINSERT INTO project_a_schema_migrations"
            "(version,name,applied_at,checksum) VALUES"
            f"(1,'initial_project_a_runtime','2026-07-16T01:00:00Z',"
            f"'{MIGRATION_1_CHECKSUM}');\nCOMMIT;"
        )
    finally:
        conn.close()
    upgraded = ProjectADatabase(upgraded_path)
    upgraded.migrate("2026-07-16T01:01:00Z")
    upgraded.assert_ready()
    conn = upgraded.connect()
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute(
            "SELECT checksum FROM project_a_schema_migrations WHERE version=2"
        ).fetchone()[0] == MIGRATION_2_CHECKSUM
    finally:
        conn.close()
