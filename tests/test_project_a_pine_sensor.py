from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from contracts import EVENT_SCHEMA_V0_2, ContractError, validate_contract
from indicators.validation.project_a_sensor_reference import (
    Evidence,
    ProjectASensor,
    sample_sequence,
)
from indicators.validation.validate_session_1_artifacts import validate_file

ROOT = Path(__file__).resolve().parents[1]
PINE = ROOT / "indicators" / "pine" / "snr_dashboard_project_a_v1.pine"
PAYLOADS = ROOT / "docs" / "project_a" / "session_1" / "artifacts" / "candidate_payloads.json"
RANGE_MIDDLE_EVIDENCE = (
    ROOT / "docs" / "project_a" / "session_1" / "artifacts"
    / "range_middle_negative_evidence.json"
)
SESSION_B_SHA256 = "4840f60cb1b4b034304e23d92ba3c40df4e45fbf2abc4b6f51adc2a250b1ca78"


def _candidate(**changes) -> Evidence:
    base = Evidence(
        bar_time="2026-07-16T01:00:00Z",
        created_time="2026-07-16T01:00:01Z",
        setup_started_at="2026-07-16T01:00:00Z",
        close=2420.1,
        snr_low=2419.5,
        snr_high=2420.0,
        target_side="SUPPORT",
        expansion="DOWN",
        momentum_1m="DOWN",
        momentum_5m="DOWN",
    )
    return replace(base, **changes)


def test_six_candidates_validate_against_frozen_event_contract():
    samples = sample_sequence()
    assert set(samples) == {
        "telemetry", "setup_candidate", "snr_rejection_ready",
        "snr_strong_break_ready", "invalidated_lifecycle", "expired_lifecycle",
    }
    for document in samples.values():
        assert validate_contract(EVENT_SCHEMA_V0_2, document) is document


def test_committed_candidate_artifact_is_generated_and_hash_verified():
    committed = __import__("json").loads(PAYLOADS.read_text(encoding="utf-8"))
    assert committed == sample_sequence()
    result = validate_file(PAYLOADS)
    assert result["count"] == 6
    assert {item["status"] for item in result["results"]} == {"PASS"}


def test_malformed_candidate_is_rejected_without_weakening_schema():
    malformed = sample_sequence()["snr_rejection_ready"] | {"schema_version": "0.1"}
    with pytest.raises(ContractError, match="schema_const"):
        validate_contract(EVENT_SCHEMA_V0_2, malformed)


def test_range_middle_never_becomes_analysis_ready():
    sensor = ProjectASensor()
    event = sensor.observe(_candidate(range_middle=True, reaction="SWEEP_RECLAIM"))
    assert event is not None
    assert event["event_class"] == "TELEMETRY"
    assert event["disposition"]["reason_code"] == "RANGE_MIDDLE"
    assert event["setup_id"] is None


def test_committed_range_middle_evidence_records_the_negative_outcome():
    artifact = __import__("json").loads(RANGE_MIDDLE_EVIDENCE.read_text(encoding="utf-8"))
    assert artifact["expected_analysis_ready"] is False
    assert set(artifact["assertions"].values()) == {True}
    observed = artifact["observed_event"]
    assert observed["event_class"] == "TELEMETRY"
    assert validate_contract(EVENT_SCHEMA_V0_2, observed) is observed


def test_same_bar_same_semantic_evidence_is_deduplicated():
    sensor = ProjectASensor()
    evidence = _candidate()
    assert sensor.observe(evidence) is not None
    assert sensor.observe(evidence) is None


def test_new_reaction_can_emit_immediately_without_cooldown():
    sensor = ProjectASensor()
    evidence = _candidate()
    candidate = sensor.observe(evidence)
    ready = sensor.observe(replace(evidence, reaction="SWEEP_RECLAIM", close=2420.3))
    assert candidate and ready
    assert ready["event_type"] == "SNR_REJECTION_READY"
    assert ready["setup_id"] == candidate["setup_id"]


def test_new_strong_break_can_emit_immediately_without_arrow_gate():
    sensor = ProjectASensor()
    evidence = _candidate(
        target_side="RESISTANCE", snr_low=2424.5, snr_high=2425.0,
        close=2424.8, expansion="UP", momentum_1m="UP", momentum_5m="UP",
        hpa_1m="PREMIUM", hpa_5m="PREMIUM",
    )
    candidate = sensor.observe(evidence)
    ready = sensor.observe(replace(evidence, strong_break=True, close=2425.4, arrow_5s=None))
    assert candidate and ready
    assert ready["event_type"] == "SNR_BREAK_READY"
    assert ready["payload"]["optional_5s_arrow"] is None


@pytest.mark.parametrize(
    ("change", "event_type"),
    [(dict(invalidated=True), "SETUP_INVALIDATED"), (dict(expired=True), "SETUP_EXPIRED")],
)
def test_lifecycle_changes_emit_immediately_and_keep_setup_id(change, event_type):
    sensor = ProjectASensor()
    candidate = sensor.observe(_candidate())
    lifecycle = sensor.observe(replace(_candidate(), **change))
    assert candidate and lifecycle
    assert lifecycle["event_type"] == event_type
    assert lifecycle["setup_id"] == candidate["setup_id"]
    assert lifecycle["causation_id"] == candidate["event_id"]


def test_fingerprint_uses_semantics_not_json_member_order():
    sensor = ProjectASensor()
    event = sensor.observe(_candidate())
    assert event is not None
    assert event["source"]["payload_hash"].startswith("sha256:")
    assert len(event["source"]["payload_hash"]) == 71


def test_project_a_source_preserves_legacy_session_b_bytes_outside_owned_blocks():
    source = PINE.read_text(encoding="utf-8").replace("\r\n", "\n")
    source = source.replace("//  Version: v0.4.0-project-a-shadow", "//  Version: v0.3.0")
    source = source.replace(
        "//  Legacy Phase 2/3 behavior remains alert-silent. The isolated Project A\n"
        "//  Event 0.2 surface added below can call alert() only when its default-off\n"
        "//  shadow feature flag is explicitly enabled on XAUUSD 1m.",
        "//  Phase 2/3 ALERT-SILENT: table and telemetry variables only. This script has\n"
        "//  no alert(), alertcondition(), webhook call, strategy order, or active\n"
        "//  VERDICT JSON serialization. Phase 4 is the first activation point.",
    )
    input_start = source.index("// Project A does not alter any legacy plot")
    l1_marker = source.index("//  L1", input_start)
    input_end = source.rfind("// ", input_start, l1_marker)
    source = source[:input_start] + source[input_end:]
    project_marker = source.index("//  PROJECT A EVENT 0.2")
    block_start = source.rfind("// ", 0, project_marker)
    block_end = source.index("// ─── Diagnostic rendering", block_start)
    source = source[:block_start] + source[block_end:]
    assert sha256(source.encode("utf-8")).hexdigest() == SESSION_B_SHA256


def test_pine_surface_is_default_off_shadow_safe_and_state_change_driven():
    source = PINE.read_text(encoding="utf-8")
    assert 'input.bool(false, "Enable Project A shadow alerts"' in source
    assert "projectAEnabled and paSafetyOk and barstate.isconfirmed and barstate.isrealtime" in source
    assert 'syminfo.ticker == "XAUUSD"' in source
    assert 'timeframe.period == "1"' in source
    assert '\\"live_execution\\":false' in source
    assert '\\"environment\\":\\"MT5_DEMO\\"' in source
    assert '\\"mode\\":\\"SHADOW\\"' in source
    assert "paSemanticFingerprint != paLastFingerprint" in source
    assert "cooldown" not in source.lower()


def test_pine_ready_paths_do_not_gate_on_optional_5s_arrow():
    source = PINE.read_text(encoding="utf-8")
    ready_start = source.index("bool paReactionReady")
    ready_end = source.index("bool paInvalidated", ready_start)
    ready_logic = source[ready_start:ready_end]
    assert "rekoState" not in ready_logic
    assert "arrow" not in ready_logic.lower()
    assert 'string paArrowJson = "null"' in source
    assert 'paEventType := "SNR_REJECTION_READY"' in source
    assert 'paEventType := "SNR_BREAK_READY"' in source


def test_pine_uses_exact_frozen_lifecycle_values_and_real_sha256_shape():
    source = PINE.read_text(encoding="utf-8")
    assert 'paEventType := "SETUP_INVALIDATED"' in source
    assert 'paDisposition := "STRUCTURAL_BREAK"' in source
    assert 'paEventType := "SETUP_EXPIRED"' in source
    assert 'paDisposition := "EXPIRED"' in source
    assert '"sha256:" + paPayloadHash' in source
    assert "f_paSha256(paPayload)" in source
