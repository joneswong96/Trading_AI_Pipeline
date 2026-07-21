"""Offline acceptance for the strict Project A raw-producer `/alert` bridge."""
from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ingest.project_a.config import ProjectAConfig
from ingest.project_a.raw_producer_adapter import (
    ProjectARawProducerAdapter,
    detect_raw_producer,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "project_a" / "section2_producer_events_v1.json"
COMPAT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "project_a" / "analysis_compatibility_events_v1.json"
)
SCANNER_COMPAT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "project_a" / "scanner_compatibility_event_v1.json"
)


def _events() -> list[dict]:
    active = json.loads(FIXTURE.read_text(encoding="utf-8"))["events"]
    compatibility = json.loads(COMPAT_FIXTURE.read_text(encoding="utf-8"))["events"]
    return [compatibility[0], active[0], *compatibility[1:]]


def _scanner_event() -> dict:
    fixture = json.loads(SCANNER_COMPAT_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["disposition"] == "DORMANT_COMPATIBILITY_ONLY"
    return fixture["event"]


def _raw(event: dict, *, pretty: bool = False) -> bytes:
    return json.dumps(
        event,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    ).encode("utf-8")


def _config(path: Path, **changes) -> ProjectAConfig:
    values = {"database_path": path}
    values.update(changes)
    return ProjectAConfig(**values)


def _adapter(path: Path) -> ProjectARawProducerAdapter:
    return ProjectARawProducerAdapter(
        _config(path),
        clock=lambda: datetime(2026, 7, 20, 1, 2, 5, tzinfo=timezone.utc),
    )


def _rows(path: Path, table: str) -> list[sqlite3.Row]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()


@pytest.mark.parametrize("event", [_events()[1], _events()[0], _events()[2], _scanner_event()])
def test_sole_active_liq_and_compatibility_inputs_precede_legacy_parser(
    tmp_path, monkeypatch, event,
):
    from ingest import webhook_server as server

    path = tmp_path / f"producer-{event['producer_id']}.db"
    server.configure_raw_producer_adapter(_adapter(path))
    monkeypatch.setattr(
        server, "parse",
        lambda _body: (_ for _ in ()).throw(AssertionError("legacy parser called")),
    )
    monkeypatch.setattr(
        server, "_fanout",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fanout called")),
    )
    response = TestClient(server.app).post("/alert", content=_raw(event))
    body = response.json()
    assert response.status_code == 200
    assert body["accepted"] is True and body["deduped"] is False
    assert body["producer"] == event["producer_id"]
    assert body["event"] == event["event"]
    expected_wake = event["producer_id"] == "LIQ_V2" and event["event"] == "LIQ_TOUCH"
    assert body["wake"] is expected_wake
    assert body["wake_scope"] == ("PROJECT_A_RESEARCH" if expected_wake else "NONE")
    assert body["evidence_acquisition_requested"] is expected_wake
    assert body["provider_called"] is False
    assert body["writer_called"] is False
    assert body["order_placed"] is False
    assert len(_rows(path, "project_a_producer_events")) == 1
    assert _rows(path, "project_a_producer_receipts")[0]["legacy_wake_eligible"] == 0
    assert len(_rows(path, "project_a_liq_research_requests")) == (1 if expected_wake else 0)
    if expected_wake:
        queued = _rows(path, "project_a_liq_research_requests")[0]
        request = json.loads(queued["evidence_request_json"])
        assert request["trigger"]["level"] == "LIQ_RESEARCH_CAPTURE"
        assert {item["read_kind"] for item in request["structured_reads"]} >= {
            "CURRENT_FORMING_PRICE", "EXPANSION_CONTEXT", "SNR_HPA_CONTEXT",
            "STANDARD_MACD", "RENKO_STATE", "SHORT_TERM_PRICE_ACTION",
        }
        assert len(request["screenshot_requests"]) == 5
        assert queued["target_binding_status"] == "UNBOUND_REQUIRES_PREFLIGHT"
        assert _rows(path, "project_a_liq_research_status_history")[0]["status"] == "PENDING"
    server.configure_raw_producer_adapter(None)


def test_unknown_and_legacy_inputs_preserve_the_legacy_route(tmp_path, monkeypatch):
    from ingest import webhook_server as server

    calls = []
    original = server.parse

    def observed(body):
        calls.append(body)
        return original(body)

    monkeypatch.setattr(server, "parse", observed)
    client = TestClient(server.app)
    legacy = "EXP DOWN | XAUUSD | TF 1 | Price 3990.66"
    response = client.post("/alert", content=legacy)
    assert response.status_code == 200
    assert response.json()["reason"] == "compatibility adapter telemetry-only → 只 log、永不 wake"
    unknown = json.dumps({"producer_id": "UNAPPROVED", "event": "NOT_PROJECT_A"})
    response = client.post("/alert", content=unknown)
    assert response.status_code == 200
    assert calls == [legacy, unknown]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"producer_id": "OTHER"}, "UNSUPPORTED_PRODUCER"),
        ({"producer_revision": "999"}, "UNSUPPORTED_PRODUCER_REVISION"),
        ({"schema": "project_a.renko_event/1.0"}, "UNSUPPORTED_PRODUCER"),
        ({"price": "3400"}, "AMBIGUOUS_OR_ACTION_FIELD"),
        ({"source_bar_time": "not-a-time"}, "INVALID_TIMESTAMP"),
        ({"direction": "LONG"}, "INVALID_MOVEMENT_DIRECTION"),
    ],
)
def test_recognized_invalid_payload_fails_closed_without_partial_state(
    tmp_path, monkeypatch, change, code,
):
    from ingest import webhook_server as server

    payload = {**_events()[0], **change}
    path = tmp_path / "invalid.db"
    server.configure_raw_producer_adapter(_adapter(path))
    monkeypatch.setattr(
        server, "parse",
        lambda _body: (_ for _ in ()).throw(AssertionError("legacy parser called")),
    )
    response = TestClient(server.app).post("/alert", content=_raw(payload))
    assert response.status_code == 422
    assert response.json()["error_code"] == code
    assert response.json()["wake"] is False
    assert len(_rows(path, "project_a_producer_receipts")) == 1
    assert _rows(path, "project_a_producer_receipts")[0]["status"] == "REJECTED"
    assert _rows(path, "project_a_producer_events") == []
    assert _rows(path, "project_a_producer_state_history") == []
    server.configure_raw_producer_adapter(None)


def test_duplicate_json_key_and_oversized_body_fail_closed(tmp_path):
    event = _events()[0]
    raw = _raw(event)
    duplicate = raw[:-1] + b',"producer_id":"EXP_V3"}'
    detection = detect_raw_producer(duplicate)
    assert detection.candidate and detection.duplicate_keys
    first = _adapter(tmp_path / "duplicate.db").receive(duplicate, detection=detection)
    assert first.http_status == 422 and first.error_code == "DUPLICATE_JSON_KEY"

    oversized = _raw({**event, "producer_note": "x" * 100})
    limited = ProjectARawProducerAdapter(
        _config(tmp_path / "oversized.db", max_body_bytes=len(oversized) - 1),
        clock=lambda: datetime(2026, 7, 20, 2, tzinfo=timezone.utc),
    )
    second = limited.receive(oversized)
    assert second.http_status == 413 and second.error_code == "BODY_TOO_LARGE"
    assert _rows(tmp_path / "oversized.db", "project_a_producer_events") == []


def test_liquidity_and_expansion_preserve_dimensions_without_trade_inference(tmp_path):
    path = tmp_path / "semantics.db"
    adapter = _adapter(path)
    liquidity = _events()[1]
    expansion = _events()[0]
    assert adapter.receive(_raw(liquidity)).accepted
    assert adapter.receive(_raw(expansion)).accepted
    documents = {
        row["producer_id"]: json.loads(row["canonical_json"])
        for row in _rows(path, "project_a_producer_events")
    }
    assert documents["LIQ_V2"]["level_price"] == "3401"
    assert documents["LIQ_V2"]["market_price"] == "3400.5"
    assert documents["LIQ_V2"]["side"] == "ASK"
    assert documents["EXP_V3"]["direction"] == "UP"
    assert all("trade_direction" not in item for item in documents.values())
    snapshot = json.loads(_rows(path, "project_a_producer_state_history")[-1]["state_snapshot_json"])
    assert snapshot["trade_direction"] is None
    assert not {"entry", "stop_loss", "take_profit", "grade"} & snapshot.keys()


def _paired_events() -> tuple[dict, dict]:
    expansion = deepcopy(_events()[0])
    scanner = deepcopy(_scanner_event())
    scanner["source_bar_time"] = expansion["source_bar_time"]
    scanner["market_price"] = expansion["market_price"]
    return expansion, scanner


def test_scanner_correlation_is_quality_only_and_receipt_order_independent(tmp_path):
    expansion, scanner = _paired_events()
    snapshots = []
    for name, events in (("forward", (expansion, scanner)), ("reverse", (scanner, expansion))):
        path = tmp_path / f"{name}.db"
        adapter = _adapter(path)
        results = [adapter.receive(_raw(event)) for event in events]
        assert all(result.accepted for result in results)
        snapshot = json.loads(_rows(path, "project_a_producer_state_history")[-1]["state_snapshot_json"])
        quality = snapshot["scanner_quality_evidence"]
        assert len(quality) == 1
        assert quality[0]["status"] == "PAIRED_QUALITY_EVIDENCE"
        assert quality[0]["promoting"] is False
        assert quality[0]["trade_direction"] is None
        assert snapshot["latest_expansion_story"] is not None
        assert len(snapshot["expansion_history"]) == 1
        snapshots.append(snapshot)
    assert snapshots[0] == snapshots[1]


def test_unpaired_scanner_is_nonpromoting_and_exact_retry_is_idempotent(tmp_path):
    path = tmp_path / "scanner.db"
    adapter = _adapter(path)
    raw = _raw(_scanner_event())
    first = adapter.receive(raw)
    retry = adapter.receive(raw)
    assert first.telemetry_status == "UNPAIRED_QUALITY_EVIDENCE"
    assert retry.accepted and retry.deduped
    assert len(_rows(path, "project_a_producer_events")) == 1
    assert len(_rows(path, "project_a_producer_state_history")) == 1
    snapshot = json.loads(_rows(path, "project_a_producer_state_history")[0]["state_snapshot_json"])
    assert snapshot["latest_expansion_story"] is None
    assert snapshot["expansion_history"] == []
    assert snapshot["scanner_quality_evidence"][0]["promoting"] is False
    assert first.state_status == "NO_STORY"


def test_conflicting_scanner_facts_are_audited_and_fail_closed(tmp_path):
    path = tmp_path / "conflict.db"
    adapter = _adapter(path)
    expansion, scanner = _paired_events()
    conflicting = {**scanner, "event_id": "fixture-exp-quality-conflict", "quality": "WEAK"}
    assert adapter.receive(_raw(expansion)).accepted
    assert adapter.receive(_raw(scanner)).accepted
    result = adapter.receive(_raw(conflicting))
    assert result.http_status == 409
    assert result.error_code == "SCANNER_EVIDENCE_CONFLICT"
    assert len(_rows(path, "project_a_producer_events")) == 2
    assert _rows(path, "project_a_producer_receipts")[-1]["status"] == "CONFLICT"


def test_semantic_duplicate_and_restart_replay_are_deterministic(tmp_path):
    path = tmp_path / "restart.db"
    payload = _events()[1]
    first_adapter = _adapter(path)
    first = first_adapter.receive(_raw(payload))
    semantic_retry = first_adapter.receive(_raw(payload, pretty=True))
    assert first.accepted and semantic_retry.deduped
    assert len(_rows(path, "project_a_producer_events")) == 1
    before = _rows(path, "project_a_producer_state_history")[-1]["state_snapshot_sha256"]
    restarted = _adapter(path)
    exact_retry = restarted.receive(_raw(payload))
    after = _rows(path, "project_a_producer_state_history")[-1]["state_snapshot_sha256"]
    assert exact_retry.deduped and before == after
    assert len(_rows(path, "project_a_producer_state_history")) == 1
    receipts = _rows(path, "project_a_producer_receipts")
    assert bytes(receipts[0]["raw_body"]) == _raw(payload)
    assert bytes(receipts[1]["raw_body"]) == _raw(payload, pretty=True)
    assert first.research_wake is True
    assert semantic_retry.research_wake is False
    assert exact_retry.research_wake is False
    assert len(_rows(path, "project_a_liq_research_requests")) == 1


def test_genuine_retouch_starts_a_new_cycle_without_cooldown(tmp_path):
    path = tmp_path / "retouch.db"
    now = [datetime(2026, 7, 20, 1, 2, 5, tzinfo=timezone.utc)]
    adapter = ProjectARawProducerAdapter(_config(path), clock=lambda: now[0])
    first = deepcopy(_events()[1])
    retouch = deepcopy(first)
    retouch.update(
        event_id="fixture-liq-retouch-2",
        source_bar_time="2026-07-20T01:07:00Z",
        touch_count=2,
        market_price="3400.75",
    )
    assert adapter.receive(_raw(first)).research_wake is True
    now[0] = datetime(2026, 7, 20, 1, 7, 5, tzinfo=timezone.utc)
    assert adapter.receive(_raw(retouch)).research_wake is True
    queued = _rows(path, "project_a_liq_research_requests")
    assert [row["touch_count"] for row in queued] == [1, 2]
    assert all(row["request_status"] == "PENDING" for row in queued)


def test_changed_event_id_with_identical_touch_evidence_is_suppressed(tmp_path):
    path = tmp_path / "same-evidence.db"
    adapter = _adapter(path)
    first = deepcopy(_events()[1])
    same_evidence = {**first, "event_id": "different-id-same-evidence"}
    assert adapter.receive(_raw(first)).research_wake is True
    duplicate = adapter.receive(_raw(same_evidence))
    assert duplicate.accepted is True
    assert duplicate.deduped is True
    assert duplicate.research_wake is False
    assert duplicate.telemetry_status == "LIQ_RESEARCH_DUPLICATE_EVIDENCE_SUPPRESSED"
    assert len(_rows(path, "project_a_liq_research_requests")) == 1


def test_same_touch_identity_with_changed_market_evidence_conflicts(tmp_path):
    path = tmp_path / "same-touch-conflict.db"
    adapter = _adapter(path)
    first = deepcopy(_events()[1])
    conflict = {**first, "event_id": "changed-id", "market_price": "3400.80"}
    assert adapter.receive(_raw(first)).research_wake is True
    result = adapter.receive(_raw(conflict))
    assert result.http_status == 409
    assert result.error_code == "LIQ_TOUCH_EVIDENCE_CONFLICT"
    assert result.research_wake is False
    assert len(_rows(path, "project_a_liq_research_requests")) == 1


def test_non_monotonic_later_touch_count_fails_closed(tmp_path):
    touch_count = 1
    path = tmp_path / "non-monotonic.db"
    now = [datetime(2026, 7, 20, 1, 2, 5, tzinfo=timezone.utc)]
    adapter = ProjectARawProducerAdapter(_config(path), clock=lambda: now[0])
    first = deepcopy(_events()[1])
    assert adapter.receive(_raw(first)).research_wake is True
    later = {
        **first,
        "event_id": f"later-{touch_count}",
        "source_bar_time": "2026-07-20T01:07:00Z",
        "touch_count": touch_count,
    }
    now[0] = datetime(2026, 7, 20, 1, 7, 5, tzinfo=timezone.utc)
    result = adapter.receive(_raw(later))
    assert result.http_status == 409
    assert result.error_code == "NON_MONOTONIC_LIQ_RETOUCH"
    assert len(_rows(path, "project_a_liq_research_requests")) == 1


def test_zero_touch_count_is_rejected(tmp_path):
    event = {**deepcopy(_events()[1]), "touch_count": 0, "event_id": "zero-touch"}
    result = _adapter(tmp_path / "zero-touch.db").receive(_raw(event))
    assert result.http_status == 422
    assert result.error_code == "INVALID_TOUCH_COUNT"


def test_research_request_has_claim_and_terminal_result_path(tmp_path):
    path = tmp_path / "research-lifecycle.db"
    adapter = _adapter(path)
    assert adapter.receive(_raw(_events()[1])).research_wake is True
    pending = adapter.store.pending_research_requests()
    assert len(pending) == 1
    event_id = pending[0]["canonical_event_id"]
    claimed = adapter.store.claim_research_request(
        event_id,
        worker_id="approved-mcp-capture-worker",
        claimed_at=datetime(2026, 7, 20, 1, 2, 6, tzinfo=timezone.utc),
    )
    assert claimed is not None
    assert adapter.store.pending_research_requests() == ()
    assert adapter.store.claim_research_request(
        event_id,
        worker_id="other-worker",
        claimed_at=datetime(2026, 7, 20, 1, 2, 7, tzinfo=timezone.utc),
    ) is None
    adapter.store.record_research_result(
        event_id,
        status="FAILED",
        recorded_at=datetime(2026, 7, 20, 1, 2, 8, tzinfo=timezone.utc),
        worker_id="approved-mcp-capture-worker",
        detail="SOURCE_UNAVAILABLE",
    )
    assert [row["status"] for row in _rows(path, "project_a_liq_research_status_history")] == [
        "PENDING", "CLAIMED", "FAILED",
    ]


def test_completed_research_requires_integrity_bound_manifest(tmp_path):
    path = tmp_path / "research-completed.db"
    adapter = _adapter(path)
    assert adapter.receive(_raw(_events()[1])).research_wake is True
    event_id = adapter.store.pending_research_requests()[0]["canonical_event_id"]
    claimed_at = datetime(2026, 7, 20, 1, 2, 6, tzinfo=timezone.utc)
    assert adapter.store.claim_research_request(
        event_id, worker_id="worker", claimed_at=claimed_at,
    ) is not None
    with pytest.raises(ValueError, match="manifest SHA-256"):
        adapter.store.record_research_result(
            event_id,
            status="COMPLETED",
            recorded_at=claimed_at,
            worker_id="worker",
        )
    with pytest.raises(ValueError, match="manifest SHA-256"):
        adapter.store.record_research_result(
            event_id,
            status="COMPLETED",
            recorded_at=claimed_at,
            worker_id="worker",
            result_manifest_sha256="not-a-hash",
        )
    adapter.store.record_research_result(
        event_id,
        status="COMPLETED",
        recorded_at=datetime(2026, 7, 20, 1, 2, 7, tzinfo=timezone.utc),
        worker_id="worker",
        result_manifest_sha256="a" * 64,
    )
    assert _rows(path, "project_a_liq_research_status_history")[-1]["status"] == "COMPLETED"


@pytest.mark.parametrize(
    ("change", "observed_at"),
    [
        ({"confirmed": False}, datetime(2026, 7, 20, 1, 2, 5, tzinfo=timezone.utc)),
        ({"freshness_status": "STALE"}, datetime(2026, 7, 20, 1, 2, 5, tzinfo=timezone.utc)),
        ({}, datetime(2026, 7, 20, 2, 0, 0, tzinfo=timezone.utc)),
        ({}, datetime(2026, 7, 20, 1, 0, 0, tzinfo=timezone.utc)),
    ],
)
def test_unconfirmed_stale_and_future_liq_touches_fail_closed_without_wake(
    tmp_path, change, observed_at,
):
    path = tmp_path / f"not-wake-{observed_at.timestamp()}-{len(change)}.db"
    event = {**deepcopy(_events()[1]), **change}
    adapter = ProjectARawProducerAdapter(_config(path), clock=lambda: observed_at)
    result = adapter.receive(_raw(event))
    assert result.accepted is True
    assert result.research_wake is False
    assert result.evidence_acquisition_requested is False
    assert result.telemetry_status == "LIQ_RESEARCH_FAILED_CLOSED"
    assert _rows(path, "project_a_liq_research_requests") == []


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "EURUSD"},
        {"feed": "OANDA"},
        {"anchor_timeframe": "1m"},
    ],
)
def test_wrong_liq_source_authority_is_rejected(tmp_path, change):
    event = {**deepcopy(_events()[1]), **change}
    result = _adapter(tmp_path / f"wrong-{next(iter(change))}.db").receive(_raw(event))
    assert result.http_status == 422
    assert result.error_code == "SOURCE_AUTHORITY_MISMATCH"
    assert result.research_wake is False


@pytest.mark.parametrize(
    ("event_name", "lifecycle"),
    [
        ("LIQ_APPROACH", "APPROACH"),
        ("LIQ_REJECT", "REJECT"),
        ("LIQ_BREAK", "BREAK"),
        ("LIQ_INVALIDATED", "INVALIDATED"),
    ],
)
def test_non_touch_liquidity_lifecycle_inputs_never_wake(tmp_path, event_name, lifecycle):
    event = deepcopy(_events()[1])
    event.update(event=event_name, lifecycle=lifecycle, event_id=f"fixture-{event_name.lower()}")
    result = _adapter(tmp_path / f"{event_name}.db").receive(_raw(event))
    assert result.accepted is True
    assert result.research_wake is False
    assert result.evidence_acquisition_requested is False


def test_renko_stages_remain_evidence_only(tmp_path):
    path = tmp_path / "renko.db"
    adapter = _adapter(path)
    for event in _events()[2:]:
        result = adapter.receive(_raw(event))
        assert result.accepted and result.telemetry_status == "TELEMETRY_STATE_ACCEPTED"
    documents = [json.loads(row["canonical_json"]) for row in _rows(path, "project_a_producer_events")]
    assert [document["stage"] for document in documents] == ["E1", "E2", "MAIN", "FIRE"]
    assert all("trade_direction" not in document for document in documents)
    states = _rows(path, "project_a_producer_state_history")
    assert all(row["full_capture_requested"] == 0 for row in states)
    assert all(row["provider_called"] == row["writer_called"] == row["order_placed"] == 0 for row in states)


def test_compatibility_inputs_after_liq_cannot_create_another_research_wake(tmp_path):
    path = tmp_path / "compat-after-liq.db"
    adapter = _adapter(path)
    liq = adapter.receive(_raw(_events()[1]))
    assert liq.research_wake is True
    compatibility = [_events()[0], *_events()[2:], _scanner_event()]
    results = [adapter.receive(_raw(event)) for event in compatibility]
    assert all(result.accepted and not result.research_wake for result in results)
    assert all(not result.evidence_acquisition_requested for result in results)
    assert len(_rows(path, "project_a_liq_research_requests")) == 1
    assert all(result.state_status == "NO_STORY" for result in results)


def test_config_default_enables_only_safe_raw_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_A_DB", str(tmp_path / "config.db"))
    monkeypatch.delenv("PROJECT_A_RAW_PRODUCER_INGEST_ENABLED", raising=False)
    config = ProjectAConfig.from_env()
    assert config.raw_producer_ingest_enabled is True
    assert config.v1_ingest_enabled is False
    assert config.mode == "SHADOW"
    assert config.execution_environment == "MT5_DEMO"
    assert config.live_execution is False and config.order_placement is False


def test_disabled_switch_fails_closed_without_event_state(tmp_path):
    path = tmp_path / "disabled.db"
    adapter = ProjectARawProducerAdapter(
        _config(path, raw_producer_ingest_enabled=False),
        clock=lambda: datetime(2026, 7, 20, 2, tzinfo=timezone.utc),
    )
    result = adapter.receive(_raw(_events()[0]))
    assert result.http_status == 503 and result.error_code == "RAW_PRODUCER_INGEST_DISABLED"
    assert _rows(path, "project_a_producer_events") == []
    assert _rows(path, "project_a_producer_state_history") == []
