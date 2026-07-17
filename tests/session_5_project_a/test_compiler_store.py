from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from contracts import ContractError
from output.project_a.compiler import InputAttestation
from output.project_a.config import fake_output_config
from output.project_a.compiler import ThesisCompiler
from output.project_a.models import Session5Error, document_hash, utc_z
from output.project_a.store import (
    MIGRATION_CHECKSUM,
    ConflictError,
    OutboxStore,
)

from .conftest import NOW, compile_input, delivery, non_actionable


def test_approve_creates_one_valid_canonical_thesis_and_four_tasks(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    thesis = made["thesis"]
    assert made["created"] is True
    assert thesis["decision"] == "APPROVE" and thesis["state"] == "ARMED"
    assert thesis["entry"] == 2416.5 and thesis["sl"] == 2414.5 and thesis["tp"] == 2418.5
    assert {item["renderer_type"] for item in made["deliveries"]} == {
        "TRADINGVIEW", "TELEGRAM", "NOTION", "MT5_DEMO"}


def test_modify_uses_only_validated_modified_geometry(runtime, request_doc, verdict_doc):
    verdict_doc.update(verdict="MODIFY", verdict_id="verdict_xau_modify_00000001",
                       entry=2416.25, sl=2414.25, tp=2418.25)
    made = compile_input(runtime, request_doc, verdict_doc)
    assert made["thesis"]["decision"] == "MODIFY"
    assert (made["thesis"]["entry"], made["thesis"]["sl"], made["thesis"]["tp"]) == (
        2416.25, 2414.25, 2418.25)


@pytest.mark.parametrize("decision,state", [("REJECT", "WAIT"), ("EXPIRED", "EXPIRED")])
def test_non_actionable_thesis_has_only_telegram_and_notion(runtime, request_doc, verdict_doc,
                                                            decision, state):
    made = compile_input(runtime, request_doc, non_actionable(verdict_doc, decision))
    assert made["thesis"]["state"] == state
    assert all(made["thesis"][key] is None for key in ("entry", "sl", "tp"))
    assert {item["renderer_type"] for item in made["deliveries"]} == {"TELEGRAM", "NOTION"}


@pytest.mark.parametrize("field", ["request_id", "setup_id", "correlation_id", "causation_id"])
def test_mismatched_request_verdict_identity_fails_closed(runtime, request_doc, verdict_doc, field):
    verdict_doc[field] = ("req_" if field in {"request_id", "causation_id"} else
                          "setup_" if field == "setup_id" else "corr_") + "mismatch_00000001"
    with pytest.raises(Session5Error, match="identity_mismatch"):
        compile_input(runtime, request_doc, verdict_doc)
    assert runtime["store"].all_deliveries() == []


def test_invalid_verdict_never_creates_thesis(runtime, request_doc, verdict_doc):
    verdict_doc["verdict"] = "YES"
    with pytest.raises(ContractError):
        compile_input(runtime, request_doc, verdict_doc)
    assert runtime["store"].get_thesis(request_doc["setup_id"]) is None


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda a: replace(a, audit_ref=""), "audit_reference_required"),
        (lambda a: replace(a, request_hash="0" * 64), "attestation_hash_mismatch"),
        (
            lambda a: replace(
                a,
                final_audit_envelope={
                    **a.final_audit_envelope,
                    "record_hash": "0" * 64,
                },
            ),
            "audit_hash_invalid",
        ),
        (
            lambda a: replace(
                a,
                completed_result={
                    **a.completed_result,
                    "audit_record_hash": "0" * 64,
                },
            ),
            "completed_result_mismatch",
        ),
    ],
)
def test_session4_handoff_is_hash_and_audit_bound(
    runtime, request_doc, verdict_doc, mutate, code
):
    attestation = InputAttestation.recorded_fixture(
        request_doc, verdict_doc, "fixture://audit"
    )
    with pytest.raises(Session5Error, match=code):
        compile_input(
            runtime,
            request_doc,
            verdict_doc,
            attestation=mutate(attestation),
        )


def test_expired_request_pair_fails_before_persistence(runtime, request_doc, verdict_doc):
    with pytest.raises(Session5Error, match="request_expired"):
        compile_input(runtime, request_doc, verdict_doc,
                      now=NOW + timedelta(minutes=10))
    assert runtime["store"].all_deliveries() == []


def test_same_input_replay_is_idempotent(runtime, request_doc, verdict_doc):
    first = compile_input(runtime, request_doc, verdict_doc)
    second = compile_input(runtime, request_doc, verdict_doc)
    assert first["created"] is True and second["created"] is False
    assert first["thesis"] == second["thesis"] and len(second["deliveries"]) == 4


def test_conflicting_same_setup_fails_closed(runtime, request_doc, verdict_doc):
    compile_input(runtime, request_doc, verdict_doc)
    other = deepcopy(verdict_doc)
    other.update(verdict_id="verdict_xau_conflict_000001", rationale="Conflicting content")
    with pytest.raises(ConflictError, match="canonical_conflict"):
        compile_input(runtime, request_doc, other)


def test_all_tasks_share_setup_thesis_and_hash(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    assert {item["setup_id"] for item in made["deliveries"]} == {made["thesis"]["setup_id"]}
    assert {item["thesis_id"] for item in made["deliveries"]} == {made["thesis"]["thesis_id"]}
    assert {item["thesis_hash"] for item in made["deliveries"]} == {document_hash(made["thesis"])}


def test_thesis_and_tasks_roll_back_atomically_on_delivery_conflict(runtime, request_doc, verdict_doc):
    compiler = compile_input(runtime, request_doc, verdict_doc)
    # A fresh store is used to directly inject a duplicate renderer list into one transaction.
    store = OutboxStore(runtime["store"].path + ".atomic")
    attestation = InputAttestation.recorded_fixture(
        request_doc, verdict_doc, "fixture://audit"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_thesis_and_deliveries(
            thesis=compiler["thesis"], request=request_doc, verdict=verdict_doc,
            audit_ref=attestation.audit_ref,
            audit_record_hash=attestation.audit_record_hash,
            audit_envelope=attestation.final_audit_envelope,
            completed_result=attestation.completed_result,
            renderer_types=["TELEGRAM", "TELEGRAM"],
            now=NOW,
        )
    assert store.get_thesis(request_doc["setup_id"]) is None and store.all_deliveries() == []


def test_canonical_thesis_sql_row_is_immutable(runtime, request_doc, verdict_doc):
    compile_input(runtime, request_doc, verdict_doc)
    conn = sqlite3.connect(runtime["store"].path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE canonical_theses SET audit_ref='changed'")
    finally:
        conn.close()


def test_request_causation_must_be_in_source_event_ids(runtime, request_doc, verdict_doc):
    request_doc["source_event_ids"] = ["evt_other_valid_00000001"]
    with pytest.raises(Session5Error, match="source_identity_mismatch"):
        compile_input(runtime, request_doc, verdict_doc)


def test_verdict_cannot_widen_request_expiry(runtime, request_doc, verdict_doc):
    verdict_doc["valid_until"] = "2026-07-16T00:06:02Z"
    with pytest.raises(Session5Error, match="verdict_expiry_widened"):
        compile_input(runtime, request_doc, verdict_doc)


def test_abandoned_claim_recovers_safely(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")
    assert runtime["store"].claim(item["delivery_id"], "dead", NOW, 3)
    assert runtime["store"].recover_abandoned(NOW + timedelta(seconds=31), 30) == 1
    assert delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")["status"] == "RETRYABLE_FAILED"


def test_terminal_manual_reset_starts_a_new_retry_window_without_attempt_collision(
    runtime, request_doc, verdict_doc
):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")
    config = replace(runtime["config"], retry_limit=2)
    from output.project_a.dispatcher import Dispatcher

    dispatcher = Dispatcher(
        runtime["store"],
        config,
        list(runtime["dispatcher"].renderers.values()),
    )
    transport = runtime["transports"]["telegram"]
    transport.failure_mode = "retryable_before"
    dispatcher.dispatch(item["delivery_id"], now=NOW)
    transport.failure_mode = "retryable_before"
    dispatcher.dispatch(item["delivery_id"], now=NOW)
    assert dispatcher.dispatch(item["delivery_id"], now=NOW) is None
    assert delivery(
        runtime["store"], made["thesis"]["setup_id"], "TELEGRAM"
    )["status"] == "TERMINAL_FAILED"

    runtime["store"].manual_reset(
        item["delivery_id"], actor="ops", reason="approved retry window", now=NOW
    )
    rendered = dispatcher.dispatch(item["delivery_id"], now=NOW)
    assert rendered.status.value == "DRY_RUN_SUCCESS"
    refreshed = delivery(
        runtime["store"], made["thesis"]["setup_id"], "TELEGRAM"
    )
    assert refreshed["attempt_count"] == 1
    with sqlite3.connect(runtime["store"].path) as conn:
        numbers = [
            row[0]
            for row in conn.execute(
                """SELECT attempt_number FROM renderer_attempts
                WHERE delivery_id=? ORDER BY attempt_number""",
                (item["delivery_id"],),
            )
        ]
    assert numbers == [1, 2, 3]


def test_completed_delivery_cannot_be_manually_reset(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")
    runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    with pytest.raises(Session5Error, match="completed_reset_forbidden"):
        runtime["store"].manual_reset(item["delivery_id"], actor="ops", reason="bad idea", now=NOW)


def test_outcome_history_is_idempotent_and_conflict_safe(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    payload = {
        "event_id": "outcome_evt_test_0001", "setup_id": made["thesis"]["setup_id"],
        "thesis_id": made["thesis"]["thesis_id"], "recorded_at": utc_z(NOW),
        "final_status": "UNKNOWN", "ticket_ref": None, "requested_price": 2416.5,
        "fill_price": None, "spread_points": 8, "slippage": None, "open_time": None,
        "close_time": None, "exit_price": None, "exit_reason": "TIMEOUT",
        "initial_risk": 2.0, "mae": None, "mfe": None, "realised_pl": None,
        "realised_r": None,
    }
    assert runtime["store"].append_outcome(payload) is True
    assert runtime["store"].append_outcome(payload) is False
    payload["exit_reason"] = "CONFLICT"
    with pytest.raises(ConflictError, match="outcome_conflict"):
        runtime["store"].append_outcome(payload)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("spread_points", -1, "outcome_spread_negative"),
        ("fill_price", float("nan"), "outcome_numeric_invalid"),
        ("requested_price", "2416.5", "outcome_numeric_invalid"),
        ("ticket_ref", 123, "outcome_field_type"),
        ("event_id", "", "outcome_identity_type"),
    ],
)
def test_outcome_values_are_strictly_typed_and_finite(
    runtime, request_doc, verdict_doc, field, value, code
):
    made = compile_input(runtime, request_doc, verdict_doc)
    payload = outcome_payload(made["thesis"])
    payload[field] = value
    with pytest.raises(Session5Error, match=code):
        runtime["store"].append_outcome(payload)


def test_outcome_chronology_and_ordering_fail_closed(
    runtime, request_doc, verdict_doc
):
    made = compile_input(runtime, request_doc, verdict_doc)
    first = outcome_payload(made["thesis"])
    first.update(
        event_id="outcome_evt_order_0001",
        open_time="2026-07-16T00:00:05Z",
        close_time="2026-07-16T00:00:06Z",
        recorded_at="2026-07-16T00:00:07Z",
    )
    assert runtime["store"].append_outcome(first)
    invalid = outcome_payload(made["thesis"])
    invalid.update(
        event_id="outcome_evt_order_0002",
        recorded_at="2026-07-16T00:00:06Z",
    )
    with pytest.raises(Session5Error, match="outcome_out_of_order"):
        runtime["store"].append_outcome(invalid)
    invalid = outcome_payload(made["thesis"])
    invalid.update(
        event_id="outcome_evt_order_0003",
        open_time="2026-07-16T00:00:08Z",
        close_time="2026-07-16T00:00:07Z",
        recorded_at="2026-07-16T00:00:09Z",
    )
    with pytest.raises(Session5Error, match="outcome_chronology"):
        runtime["store"].append_outcome(invalid)


def test_outcome_wrong_setup_is_rejected(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    payload = {
        "event_id": "outcome_evt_test_0002", "setup_id": "setup_wrong_00000001",
        "thesis_id": made["thesis"]["thesis_id"], "recorded_at": utc_z(NOW),
        "final_status": "UNKNOWN", "ticket_ref": None, "requested_price": None,
        "fill_price": None, "spread_points": None, "slippage": None, "open_time": None,
        "close_time": None, "exit_price": None, "exit_reason": None, "initial_risk": None,
        "mae": None, "mfe": None, "realised_pl": None, "realised_r": None,
    }
    with pytest.raises(Session5Error, match="outcome_identity_mismatch"):
        runtime["store"].append_outcome(payload)


def test_sqlite_integrity_check_is_clean(runtime):
    assert runtime["store"].integrity_check() == "ok"


def test_migration_ledger_and_checksum_survive_restart(runtime):
    ledger = runtime["store"].migration_status()
    assert len(ledger) == 1
    assert ledger[0]["version"] == 1
    assert ledger[0]["checksum"] == MIGRATION_CHECKSUM
    reopened = OutboxStore(runtime["store"].path)
    assert reopened.migration_status()[0]["checksum"] == MIGRATION_CHECKSUM


def test_tampered_migration_checksum_is_rejected(runtime):
    with sqlite3.connect(runtime["store"].path) as conn:
        conn.execute("UPDATE schema_migrations SET checksum='tampered'")
        conn.commit()
    with pytest.raises(Session5Error, match="migration_checksum_mismatch"):
        OutboxStore(runtime["store"].path)


def test_unknown_or_partial_sqlite_state_is_rejected(tmp_path):
    path = tmp_path / "partial.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE canonical_theses(setup_id TEXT PRIMARY KEY)")
        conn.commit()
    with pytest.raises(Session5Error, match="schema_state_unknown"):
        OutboxStore(path)


def test_record_operation_is_committed_and_survives_reopen(runtime):
    operation_id = runtime["store"].record_operation(
        "FIXTURE_CHECK",
        actor="session0",
        reason="persistence regression",
        now=NOW,
        detail={"safe": True},
    )
    with sqlite3.connect(runtime["store"].path) as conn:
        stored = conn.execute(
            "SELECT operation_type,actor,reason FROM audit_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    assert stored == ("FIXTURE_CHECK", "session0", "persistence regression")


def test_empty_renderer_allowlist_disables_all_outputs_but_keeps_thesis(runtime, request_doc,
                                                                        verdict_doc):
    config = fake_output_config(enabled_renderers=[])
    made = ThesisCompiler(runtime["store"], config).compile(
        request_doc,
        verdict_doc,
        InputAttestation.recorded_fixture(
            request_doc, verdict_doc, "fixture://audit"
        ),
        now=NOW,
    )
    assert made["thesis"]["setup_id"] == request_doc["setup_id"]
    assert made["deliveries"] == []


def test_no_live_configuration_key_is_accepted():
    with pytest.raises(Session5Error, match="live_route_forbidden"):
        fake_output_config(live_execution=False)


def outcome_payload(thesis):
    return {
        "event_id": "outcome_evt_test_base",
        "setup_id": thesis["setup_id"],
        "thesis_id": thesis["thesis_id"],
        "recorded_at": "2026-07-16T00:00:08Z",
        "final_status": "UNKNOWN",
        "ticket_ref": None,
        "requested_price": 2416.5,
        "fill_price": None,
        "spread_points": 8,
        "slippage": None,
        "open_time": None,
        "close_time": None,
        "exit_price": None,
        "exit_reason": "TIMEOUT",
        "initial_risk": 2.0,
        "mae": None,
        "mfe": None,
        "realised_pl": None,
        "realised_r": None,
    }
