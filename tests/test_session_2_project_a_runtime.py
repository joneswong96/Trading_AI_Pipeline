from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlite3

from ingest.project_a.config import ProjectAConfig
from ingest.project_a.replay import run as replay_run
from ingest.project_a.service import ProjectAIngestService

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def load_case(name="accepted_alert"):
    cases = json.loads((ROOT / "fixtures/project_a/event_cases.json").read_text(encoding="utf-8"))
    return deepcopy(cases[name]["payload"])


def wire(event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()


def ready(*, event_id="evt_xau_runtime_0001", setup_id="setup_xau_runtime_0001",
          occurred="2026-07-16T00:00:00Z", event_type="SNR_REJECTION_READY"):
    event = load_case()
    event.update({
        "event_id": event_id,
        "setup_id": setup_id,
        "correlation_id": "corr_xau_runtime_0001",
        "occurred_at": occurred,
        "received_at": occurred,
        "event_type": event_type,
        "path": "SNR_REJECTION" if event_type == "SNR_REJECTION_READY" else "SNR_STRONG_BREAK",
    })
    event["payload"]["spread_points"] = 5
    return event


def candidate(*, event_id="evt_xau_candidate_0001", setup_id="setup_xau_runtime_0001",
              occurred="2026-07-15T23:59:00Z"):
    event = ready(event_id=event_id, setup_id=setup_id, occurred=occurred)
    event.update({"event_class": "SETUP_CANDIDATE", "event_type": "SETUP_CANDIDATE"})
    event["payload"].pop("spread_points")
    return event


def lifecycle(event_type, *, event_id, setup_id="setup_xau_runtime_0001",
              occurred="2026-07-16T00:01:00Z"):
    event = ready(event_id=event_id, setup_id=setup_id, occurred=occurred)
    event.update({"event_class": "LIFECYCLE", "event_type": event_type})
    event["disposition"] = {
        "status": "EXPIRED" if event_type == "SETUP_EXPIRED" else "STRUCTURAL_BREAK",
        "reason_code": "LIFECYCLE_TEST", "detail": "Lifecycle test event.",
    }
    return event


@pytest.fixture
def runtime(tmp_path):
    clock = Clock(datetime(2026, 7, 16, 0, 0, 5, tzinfo=timezone.utc))
    config = ProjectAConfig(database_path=tmp_path / "project_a.db")
    return ProjectAIngestService(config, clock=clock), clock, config


def scalar(service, query, params=()):
    with service.db.connect() as conn:
        return conn.execute(query, params).fetchone()[0]


def test_valid_xauusd_v02_is_accepted_and_atomically_dispatches(runtime):
    service, _, _ = runtime
    result = service.receive(wire(ready()))
    assert (result.result_code, result.transition_code) == ("ACCEPTED", "DIRECT_ANALYSIS_READY")
    assert result.dispatch_key.startswith("sha256:")
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_setup_state") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1


def test_outbox_insert_failure_rolls_back_event_and_state_but_keeps_receipt(runtime):
    service, _, _ = runtime
    with service.db.transaction(immediate=True) as conn:
        conn.execute(
            "CREATE TRIGGER fail_test_outbox BEFORE INSERT ON project_a_outbox "
            "BEGIN SELECT RAISE(ABORT, 'failure injection'); END")
    result = service.receive(wire(ready()))
    assert result.result_code == "PERSISTENCE_FAILURE" and result.http_status == 503
    assert scalar(service, "SELECT COUNT(*) FROM project_a_raw_receipts") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 0
    assert scalar(service, "SELECT COUNT(*) FROM project_a_setup_state") == 0
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 0


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda e: e.update(schema_version="9.9"), "SCHEMA_VERSION_UNSUPPORTED"),
        (lambda e: e.pop("schema_version"), "SCHEMA_VERSION_MISSING"),
        (lambda e: e["instrument"].update(symbol="EURUSD"), "WRONG_SYMBOL"),
        (lambda e: (e["payload"].pop("spread_points"), e["payload"].update(spread=0.5)),
         "SPREAD_FORMAT_AMBIGUOUS"),
        (lambda e: e.update(timeframe="5m"), "WRONG_TIMEFRAME"),
        (lambda e: e["payload"].update(snr_low=3000, snr_high=2000), "MALFORMED_SNR"),
        (lambda e: e["payload"].update(live_execution=True), "CLIENT_AUTHORITY_PROHIBITED"),
    ],
)
def test_fail_closed_gates_are_traceable(runtime, mutate, code):
    service, _, _ = runtime
    event = ready()
    mutate(event)
    result = service.receive(wire(event))
    assert result.result_code == code
    assert scalar(service, "SELECT COUNT(*) FROM project_a_dead_letters WHERE error_code=?", (code,)) == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 0


def test_malformed_json_is_retained_as_failed_immutable_receipt(runtime):
    service, _, _ = runtime
    raw = b'{"schema_version":"0.2",broken'
    result = service.receive(raw)
    assert result.result_code == "MALFORMED_JSON"
    with service.db.connect() as conn:
        receipt = conn.execute("SELECT raw_body,raw_complete FROM project_a_raw_receipts").fetchone()
    assert bytes(receipt["raw_body"]) == raw and receipt["raw_complete"] == 1


def test_future_and_stale_timestamp_are_rejected(runtime):
    service, _, _ = runtime
    future = ready(event_id="evt_xau_future_0001", occurred="2026-07-16T00:00:11Z")
    stale = ready(event_id="evt_xau_stale_0001", occurred="2026-07-15T23:29:00Z")
    assert service.receive(wire(future)).result_code == "FUTURE_TIMESTAMP"
    assert service.receive(wire(stale)).result_code == "STALE_TIMESTAMP"


def test_same_event_same_content_and_body_are_idempotent_receipts(runtime):
    service, _, _ = runtime
    raw = wire(ready())
    first, second = service.receive(raw), service.receive(raw)
    assert first.result_code == "ACCEPTED"
    assert second.result_code == "IDEMPOTENT_DUPLICATE"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_raw_receipts") == 2
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1


def test_same_event_id_conflicting_content_fails_closed(runtime):
    service, _, _ = runtime
    assert service.receive(wire(ready())).result_code == "ACCEPTED"
    conflict = ready()
    conflict["payload"]["trigger_price"] = 9999
    assert service.receive(wire(conflict)).result_code == "EVENT_ID_CONFLICT"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1


def test_different_event_same_bar_same_evidence_does_not_redispatch(runtime):
    service, _, _ = runtime
    assert service.receive(wire(ready())).result_code == "ACCEPTED"
    same = ready(event_id="evt_xau_runtime_0002")
    result = service.receive(wire(same))
    assert result.result_code == "DUPLICATE_EVIDENCE"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 2
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1

    # Producer timestamps within the same 1m bar are normalized for semantic evidence.
    same_later = ready(event_id="evt_xau_runtime_0004", occurred="2026-07-16T00:00:04Z")
    assert service.receive(wire(same_later)).result_code == "DUPLICATE_EVIDENCE"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1


def test_new_reaction_evidence_dispatches_immediately_without_cooldown(runtime):
    service, clock, _ = runtime
    service.receive(wire(ready()))
    clock.value += timedelta(seconds=10)
    changed = ready(event_id="evt_xau_runtime_0003", occurred="2026-07-16T00:00:10Z")
    changed["payload"]["reaction_grade"] = "STRONG"
    result = service.receive(wire(changed))
    assert result.result_code == "ACCEPTED"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 2


def test_candidate_to_rejection_ready_and_strong_break_ready(runtime):
    service, clock, _ = runtime
    assert service.receive(wire(candidate())).transition_code == "CANDIDATE_CREATED"
    rejection = ready(occurred="2026-07-16T00:00:00Z")
    assert service.receive(wire(rejection)).transition_code == "ANALYSIS_READY"
    clock.value += timedelta(seconds=15)
    break_ready = ready(event_id="evt_xau_break_0001", occurred="2026-07-16T00:00:15Z",
                        event_type="SNR_BREAK_READY")
    break_ready["payload"]["break_close_confirmed"] = True
    assert service.receive(wire(break_ready)).result_code == "ACCEPTED"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 2


@pytest.mark.parametrize("event_type", ["SETUP_INVALIDATED", "SETUP_EXPIRED"])
def test_invalidation_and_expiry_are_immediate_and_terminal(runtime, event_type):
    service, clock, _ = runtime
    service.receive(wire(ready()))
    clock.value += timedelta(minutes=1)
    event = lifecycle(event_type, event_id=f"evt_xau_{event_type.lower()}_0001")
    result = service.receive(wire(event))
    assert result.result_code == "ACCEPTED"
    assert scalar(service, "SELECT lifecycle_state FROM project_a_setup_state") == event_type


@pytest.mark.parametrize(
    ("event_type", "wrong_status"),
    [("SETUP_INVALIDATED", "EXPIRED"), ("SETUP_EXPIRED", "STRUCTURAL_BREAK")],
)
def test_supported_v02_lifecycle_requires_its_exact_disposition(
        runtime, event_type, wrong_status):
    service, clock, _ = runtime
    service.receive(wire(ready()))
    clock.value += timedelta(minutes=1)
    event = lifecycle(event_type, event_id=f"evt_xau_wrong_{event_type.lower()}_0001")
    event["disposition"]["status"] = wrong_status
    result = service.receive(wire(event))
    assert result.result_code == "UNSUPPORTED_LIFECYCLE_V02"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_raw_receipts") == 2
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1


def test_illegal_reopen_and_out_of_order_are_dead_lettered(runtime):
    service, clock, _ = runtime
    service.receive(wire(ready()))
    clock.value += timedelta(minutes=1)
    service.receive(wire(lifecycle("SETUP_INVALIDATED", event_id="evt_xau_invalid_0001")))
    clock.value += timedelta(minutes=1)
    reopen = ready(event_id="evt_xau_reopen_0001", occurred="2026-07-16T00:02:00Z")
    assert service.receive(wire(reopen)).result_code == "ILLEGAL_LIFECYCLE_TRANSITION"

    second_setup = "setup_xau_order_0001"
    current = ready(event_id="evt_xau_order_0002", setup_id=second_setup,
                    occurred="2026-07-16T00:02:00Z")
    service.receive(wire(current))
    older = ready(event_id="evt_xau_order_0001", setup_id=second_setup,
                  occurred="2026-07-16T00:01:00Z")
    assert service.receive(wire(older)).result_code == "OUT_OF_ORDER_EVENT"


def test_restart_preserves_state_and_does_not_duplicate_outbox(runtime):
    service, clock, config = runtime
    raw = wire(ready())
    service.receive(raw)
    restarted = ProjectAIngestService(config, clock=clock, initialize=False)
    assert scalar(restarted, "SELECT lifecycle_state FROM project_a_setup_state") == "SNR_REJECTION_READY"
    assert restarted.receive(raw).result_code == "IDEMPOTENT_DUPLICATE"
    assert scalar(restarted, "SELECT COUNT(*) FROM project_a_outbox") == 1


def test_outbox_failure_retry_delivery_and_abandoned_claim_recovery(runtime):
    service, clock, _ = runtime
    service.receive(wire(ready()))
    first = service.claim_outbox("worker-a")
    assert first["status"] == "PROCESSING"
    assert service.fail_outbox(first["outbox_id"], "worker-a", "temporary", retry_delay_seconds=0) == "FAILED"
    second = service.claim_outbox("worker-b")
    clock.value += timedelta(seconds=service.config.claim_timeout_seconds + 1)
    assert service.recover_abandoned_claims() == 1
    third = service.claim_outbox("worker-c")
    assert third["outbox_id"] == second["outbox_id"]
    assert service.deliver_outbox(third["outbox_id"], "worker-c") is True
    assert scalar(service, "SELECT status FROM project_a_outbox") == "DELIVERED"


def test_replay_dry_run_has_no_effect_and_commit_is_idempotent(runtime):
    service, _, config = runtime
    accepted = service.receive(wire(ready()))
    before = service.metrics().copy()
    dry = replay_run(config, selector="receipt", value=accepted.ingest_id)
    assert dry["mode"] == "DRY_RUN" and dry["committed_effects"] is False
    assert service.metrics() == before
    committed = replay_run(config, selector="receipt", value=accepted.ingest_id, commit=True)
    assert committed["results"][0]["result_code"] == "IDEMPOTENT_DUPLICATE"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_replay_operations") == 1


def test_health_and_metrics_report_schema_and_shadow_safety(runtime):
    service, _, _ = runtime
    health = service.health()
    assert health["ok"] is True and health["schema_version"] == 2
    assert health["reserved_capture_port"] == 4999 and health["ingest_port"] == 8000
    assert health["v1_ingest_enabled"] is False
    assert health["live_execution"] is False and health["order_placement"] is False
    assert service.metrics()["receipts_total"] == 0


def test_structural_semantic_and_missing_spread_fail_closed(runtime):
    service, _, _ = runtime
    structural = ready(event_id="evt_xau_structural_0001")
    structural["unknown_envelope_field"] = True
    semantic = ready(event_id="evt_xau_semantic_0001")
    semantic["payload"]["token"] = "fixture-value"
    missing_spread = ready(event_id="evt_xau_spread_0001")
    missing_spread["payload"].pop("spread_points")
    assert service.receive(wire(structural)).result_code == "STRUCTURAL_VALIDATION_FAILED"
    assert service.receive(wire(semantic)).result_code == "SEMANTIC_VALIDATION_FAILED"
    assert service.receive(wire(missing_spread)).result_code == "SPREAD_POINTS_REQUIRED"
    metrics = service.metrics()
    assert metrics["rejected_by_reason"]["SPREAD_POINTS_REQUIRED"] == 1


def test_rejected_candidate_and_telemetry_are_retained_without_dispatch(runtime):
    service, _, _ = runtime
    rejected = load_case("rejected_alert")
    rejected["occurred_at"] = "2026-07-16T00:00:00Z"
    rejected["received_at"] = "2026-07-16T00:00:00Z"
    rejected["payload"].update(snr_low=2418, snr_high=2420)
    assert service.receive(wire(rejected)).result_code == "RECORDED_REJECTED"
    telemetry = ready(event_id="evt_xau_telemetry_0001", setup_id=None)
    telemetry.update({
        "event_class": "TELEMETRY", "event_type": "SNR_UPDATE",
        "setup_id": None, "hypothesis": None, "path": None,
    })
    telemetry["payload"].pop("spread_points")
    assert service.receive(wire(telemetry)).transition_code == "TELEMETRY_RECORDED"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == 0


@pytest.mark.parametrize(
    "event_type", ["ENTRY_WINDOW_OPEN", "ENTRY_WINDOW_CLOSED", "THESIS_INVALIDATED"]
)
def test_unsupported_v02_lifecycle_is_retained_without_mutation_or_dispatch(
        runtime, event_type):
    service, clock, _ = runtime
    service.receive(wire(ready()))
    clock.value += timedelta(seconds=10)
    before_state = scalar(service, "SELECT COUNT(*) FROM project_a_setup_state_history")
    before_outbox = scalar(service, "SELECT COUNT(*) FROM project_a_outbox")
    unsupported = lifecycle(
        event_type,
        event_id=f"evt_xau_{event_type.lower()}_0001",
        occurred="2026-07-16T00:00:10Z",
    )
    result = service.receive(wire(unsupported))
    assert result.result_code == "UNSUPPORTED_LIFECYCLE_V02"
    assert scalar(service, "SELECT COUNT(*) FROM project_a_raw_receipts") == 2
    assert scalar(service, "SELECT COUNT(*) FROM project_a_canonical_events") == 1
    assert scalar(service, "SELECT COUNT(*) FROM project_a_setup_state_history") == before_state
    assert scalar(service, "SELECT COUNT(*) FROM project_a_outbox") == before_outbox


def test_raw_and_canonical_audit_rows_are_database_immutable(runtime):
    service, _, _ = runtime
    result = service.receive(wire(ready()))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with service.db.transaction(immediate=True) as conn:
            conn.execute("UPDATE project_a_raw_receipts SET body_bytes=0 WHERE ingest_id=?",
                         (result.ingest_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with service.db.transaction(immediate=True) as conn:
            conn.execute("DELETE FROM project_a_canonical_events WHERE event_id=?",
                         (result.event_id,))


def test_outbox_claim_is_exclusive_and_retry_limit_dead_letters(tmp_path):
    clock = Clock(datetime(2026, 7, 16, 0, 0, 5, tzinfo=timezone.utc))
    config = ProjectAConfig(database_path=tmp_path / "project_a.db", max_outbox_attempts=1)
    first_service = ProjectAIngestService(config, clock=clock)
    second_service = ProjectAIngestService(config, clock=clock, initialize=False)
    first_service.receive(wire(ready()))
    claim = first_service.claim_outbox("worker-a")
    assert second_service.claim_outbox("worker-b") is None
    assert first_service.fail_outbox(claim["outbox_id"], "worker-a", "permanent") == "DEAD_LETTER"
    assert scalar(first_service, "SELECT status FROM project_a_outbox") == "DEAD_LETTER"
    assert scalar(first_service,
                  "SELECT COUNT(*) FROM project_a_dead_letters WHERE error_code='OUTBOX_UNRECOVERABLE'") == 1


def test_startup_rejects_unknown_or_partial_schema(runtime):
    service, clock, config = runtime
    with service.db.transaction(immediate=True) as conn:
        conn.execute(
            "INSERT INTO project_a_schema_migrations(version,name,applied_at,checksum) "
            "VALUES(3,'unapproved','2026-07-16T00:00:00Z','bad')")
    with pytest.raises(RuntimeError, match="unsupported or partial"):
        ProjectAIngestService(config, clock=clock, initialize=False)
    with service.db.transaction(immediate=True) as conn:
        conn.execute("DELETE FROM project_a_schema_migrations WHERE version=3")
        conn.execute("DROP TABLE project_a_semantic_dedupe")
    with pytest.raises(RuntimeError, match="partial Project A schema objects"):
        ProjectAIngestService(config, clock=clock, initialize=False)


def test_port_4999_is_rejected_by_configuration(tmp_path):
    config = ProjectAConfig(database_path=tmp_path / "x.db", ingest_port=4999)
    with pytest.raises(RuntimeError, match="capture_port_reserved"):
        ProjectAIngestService(config)
