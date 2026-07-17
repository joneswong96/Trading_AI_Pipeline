from __future__ import annotations

from dataclasses import replace
from hashlib import sha1, sha256
import json
from pathlib import Path
import subprocess

from contracts import validate_wire_event_v1_shape
from indicators.validation.project_a_sensor_reference import (
    Evidence,
    ProjectASensor,
    SOURCE_BLOB,
    SOURCE_COMMIT,
    SOURCE_LEGACY_SHA256,
    sample_sequence,
)
from indicators.validation.validate_session_1_artifacts import validate_file

ROOT = Path(__file__).resolve().parents[1]
PINE = ROOT / "indicators" / "pine" / "snr_dashboard_project_a_v1.pine"
PAYLOADS = ROOT / "docs" / "project_a" / "session_1" / "artifacts" / "candidate_payloads.json"
PINE_PATH = "indicators/pine/snr_dashboard_project_a_v1.pine"


def _evidence(**changes) -> Evidence:
    base = Evidence(
        occurred_at="2026-07-16T01:00:00Z",
        emitted_at="2026-07-16T01:00:01Z",
        close=2420.1,
        expansion_new_down=True,
        snr_low=2419.5,
        snr_high=2420.0,
        target_side="SUPPORT",
        level_eligible=True,
    )
    return replace(base, **changes)


def _strip_project_a(source: str, *, corrected: bool) -> str:
    source = source.replace("\r\n", "\n")
    if corrected:
        source = source.replace(
            "//  Version: v1.0.0-project-a-wire-shadow",
            "//  Version: v0.3.0",
        )
        source = source.replace(
            "//  Legacy Phase 2/3 behavior remains alert-silent. The isolated Project A\n"
            "//  Wire Event V1 surface added below can call alert() only when its default-off\n"
            "//  shadow feature flag is explicitly enabled on XAUUSD 1m.",
            "//  Phase 2/3 ALERT-SILENT: table and telemetry variables only. This script has\n"
            "//  no alert(), alertcondition(), webhook call, strategy order, or active\n"
            "//  VERDICT JSON serialization. Phase 4 is the first activation point.",
        )
        marker = "//  RETIRED PROJECT A EVENT 0.2 MODEL"
    else:
        source = source.replace(
            "//  Version: v0.4.0-project-a-shadow",
            "//  Version: v0.3.0",
        )
        source = source.replace(
            "//  Legacy Phase 2/3 behavior remains alert-silent. The isolated Project A\n"
            "//  Event 0.2 surface added below can call alert() only when its default-off\n"
            "//  shadow feature flag is explicitly enabled on XAUUSD 1m.",
            "//  Phase 2/3 ALERT-SILENT: table and telemetry variables only. This script has\n"
            "//  no alert(), alertcondition(), webhook call, strategy order, or active\n"
            "//  VERDICT JSON serialization. Phase 4 is the first activation point.",
        )
        marker = "//  PROJECT A EVENT 0.2"

    input_start = source.index("// Project A does not alter any legacy plot")
    l1_marker = source.index("//  L1", input_start)
    input_end = source.rfind("// ", input_start, l1_marker)
    source = source[:input_start] + source[input_end:]

    project_marker = source.index(marker)
    block_start = source.rfind("// ", 0, project_marker)
    block_end = source.index("// ─── Diagnostic rendering", block_start)
    return source[:block_start] + source[block_end:]


def _git_blob_sha(data: bytes) -> str:
    return sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def test_immutable_export_provenance_is_a_real_committed_git_blob():
    original = subprocess.check_output(
        ["git", "show", f"{SOURCE_COMMIT}:{PINE_PATH}"],
        cwd=ROOT,
    )
    assert _git_blob_sha(original) == SOURCE_BLOB
    legacy = _strip_project_a(original.decode("utf-8"), corrected=False)
    assert sha256(legacy.encode("utf-8")).hexdigest() == SOURCE_LEGACY_SHA256


def test_corrected_source_preserves_the_same_immutable_legacy_surface():
    legacy = _strip_project_a(PINE.read_text(encoding="utf-8"), corrected=True)
    assert sha256(legacy.encode("utf-8")).hexdigest() == SOURCE_LEGACY_SHA256


def test_committed_wire_v1_artifacts_are_generated_and_shape_valid():
    committed = json.loads(PAYLOADS.read_text(encoding="utf-8"))
    assert committed == sample_sequence()
    result = validate_file(PAYLOADS)
    assert result["count"] == 4
    assert {item["status"] for item in result["results"]} == {"PASS"}
    for document in committed.values():
        assert validate_wire_event_v1_shape(document) is document


def test_default_off_emits_nothing_and_does_not_build_hidden_lifecycle():
    sensor = ProjectASensor()
    assert sensor.observe(_evidence()) is None
    assert sensor.observe(
        replace(
            _evidence(),
            occurred_at="2026-07-16T01:01:00Z",
            emitted_at="2026-07-16T01:01:01Z",
        )
    ) is None


def test_unambiguous_new_expansion_can_emit_only_setup_candidate():
    event = ProjectASensor(enabled=True).observe(_evidence())
    assert event is not None
    assert event["event_class"] == "SETUP_CANDIDATE"
    assert event["event_type"] == "SETUP_CANDIDATE"
    assert event["hypothesis"] is None
    assert event["path"] is None
    assert event["setup_origin"] is not None
    assert event["evidence"]["snr"]["side"] == "SUPPORT"
    assert event["evidence"]["hpa"] == []
    assert event["evidence"]["momentum"] == []
    assert event["evidence"]["rejection"] is None
    assert event["evidence"]["break"] is None
    assert event["evidence"]["expiry"] is None


def test_ambiguous_expansion_fails_closed_to_telemetry_without_setup_origin():
    event = ProjectASensor(enabled=True).observe(
        _evidence(expansion_new_up=True, expansion_new_down=True)
    )
    assert event is not None
    assert event["event_class"] == "TELEMETRY"
    assert event["event_type"] == "EXPANSION_UPDATE"
    assert event["setup_origin"] is None
    assert event["evidence"]["snr"] is None


def test_no_fabricated_analysis_ready_or_lifecycle_path_exists():
    sensor = ProjectASensor(enabled=True)
    cases = [
        _evidence(),
        _evidence(
            occurred_at="2026-07-16T01:01:00Z",
            emitted_at="2026-07-16T01:01:01Z",
            expansion_new_up=True,
            expansion_new_down=True,
        ),
        _evidence(
            occurred_at="2026-07-16T01:02:00Z",
            emitted_at="2026-07-16T01:02:01Z",
            expansion_new_up=False,
            expansion_new_down=False,
            level_changed=True,
        ),
    ]
    events = [sensor.observe(case) for case in cases]
    assert all(event is not None for event in events)
    assert {event["event_class"] for event in events if event} <= {
        "TELEMETRY",
        "SETUP_CANDIDATE",
    }


def test_wire_producer_owns_no_receipt_or_canonical_hash_fields():
    event = ProjectASensor(enabled=True).observe(_evidence())
    assert event is not None
    assert "received_at" not in event
    assert "canonical_content_hash" not in event
    assert "raw_bytes_hash" not in event
    assert "receipt_id" not in event
    assert event["source"]["producer_checksum"] is None
    assert event["emitted_at"] == "2026-07-16T01:00:01Z"


def test_same_closed_bar_and_evidence_is_suppressed_without_cooldown():
    sensor = ProjectASensor(enabled=True)
    evidence = _evidence()
    assert sensor.observe(evidence) is not None
    assert sensor.observe(evidence) is None
    assert sensor.observe(
        replace(
            evidence,
            occurred_at="2026-07-16T01:01:00Z",
            emitted_at="2026-07-16T01:01:01Z",
        )
    ) is not None


def test_pine_active_surface_is_wire_v1_default_off_and_fact_only():
    source = PINE.read_text(encoding="utf-8")
    active = source[source.index("//  ACTIVE PROJECT A WIRE EVENT V1"):]
    active = active[:active.index("// ─── Diagnostic rendering")]

    assert 'input.bool(false, "Enable Project A shadow alerts"' in source
    assert (
        "projectAEnabled and paSafetyOk and barstate.isconfirmed and "
        "barstate.isrealtime"
    ) in active
    assert 'syminfo.ticker == "XAUUSD"' in source
    assert 'timeframe.period == "1"' in source
    assert '\\"contract_family\\":\\"PROJECT_A_WIRE_EVENT\\"' in active
    assert '\\"schema_version\\":\\"1.0\\"' in active
    assert '\\"mode\\":\\"SHADOW\\"' in active
    assert '\\"execution_environment\\":\\"MT5_DEMO\\"' in active
    assert '\\"live_execution\\":false' in active
    assert "alert(paV1WireEvent, alert.freq_once_per_bar_close)" in active
    assert "alert(paEnvelope" not in source


def test_pine_active_surface_excludes_unowned_and_unratified_semantics():
    source = PINE.read_text(encoding="utf-8")
    active = source[source.index("//  ACTIVE PROJECT A WIRE EVENT V1"):]
    active = active[:active.index("// ─── Diagnostic rendering")]

    for forbidden in (
        "received_at",
        "canonical_content_hash",
        "raw_bytes_hash",
        "payload_hash",
        "f_paSha256",
        "request.security",
        "ANALYSIS_READY",
        "SNR_REJECTION_READY",
        "SNR_BREAK_READY",
        "SETUP_EXPIRED",
        "projectAExpiryBars",
        "paNearTarget",
        "paBreakBuffer",
        "paBody",
        "paWick",
        "paValidHpa",
    ):
        assert forbidden not in active
    assert '\\"hpa\\":[]' in active
    assert '\\"momentum\\":[]' in active
    assert '\\"hypothesis\\":null' in active
    assert '\\"path\\":null' in active


def test_retired_v02_semantics_and_output_are_explicitly_disabled():
    source = PINE.read_text(encoding="utf-8")
    retired = source[source.index("//  RETIRED PROJECT A EVENT 0.2 MODEL"):]
    retired = retired[:retired.index("//  ACTIVE PROJECT A WIRE EVENT V1")]
    assert "bool paValidHpa = false" in retired
    assert 'string paHpa5m = "UNAVAILABLE"' in retired
    assert 'string paHpa15m = "UNAVAILABLE"' in retired
    assert 'string paHpa30m = "UNAVAILABLE"' in retired
    assert retired.count("f_paHpa()") == 1
    assert retired.count("f_paMomentum()") == 1
    assert "bool paNewEncounter = false" in retired
    assert "bool paNearTarget = false" in retired
    assert "bool paContextValid = false" in retired
    assert "bool paReactionReady = false" in retired
    assert "float paBreakBuffer = na" in retired
    assert "bool paStrongBreakUp = false" in retired
    assert "bool paStrongBreakDown = false" in retired
    assert "bool paBreakReady = false" in retired
    assert "bool paInvalidated = false" in retired
    assert "bool paExpired = false" in retired
    assert "bool paShouldEmit = false" in retired
    assert "f_paSha256(paPayload)" not in retired
    assert "alert(paEnvelope" not in retired
