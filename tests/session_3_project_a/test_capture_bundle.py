from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts import (
    ANALYSIS_REQUEST_SCHEMA_V1,
    InMemoryDedupeAuthority,
    canonical_json,
    canonical_json_bytes,
    process_wire_event_v1_receipt,
    validate_contract,
)
from contracts._trusted_ingress import issue_replay_receipt_context
from capture.project_a.artifacts import ArtifactStore, sha256_bytes, verify_manifest
from capture.project_a.cdp import WindowsCdpProbe
from capture.project_a.compiler import compile_analysis_request
from capture.project_a.consumer import DispatchEnvelope, FileDispatchLedger, consume_dispatch
from capture.project_a.coordinator import capture_event
from capture.project_a.errors import Session3Error
from capture.project_a.input_boundary import (
    ADAPTER_FAMILY,
    ADAPTER_STATUS,
    ADAPTER_VERSION,
    bind_disabled_analysis_adapter,
    utc_z,
    validate_analysis_ready,
)
from capture.project_a.preflight import (
    ChartState,
    EndpointInfo,
    TargetInfo,
    select_pinned_target,
    verify_chart_state,
    verify_endpoint,
    verify_preflight,
)
from capture.project_a.profile import CaptureProfile, REQUIRED_TIMEFRAMES, TabPin
from capture.project_a.replay import release_decision, replay_bundle, write_bundle

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
EVENT_TIME = datetime(2026, 7, 16, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 7, 16, 1, 2, tzinfo=UTC)
EXPIRES = datetime(2026, 7, 16, 1, 10, tzinfo=UTC)


def wire_event() -> dict:
    vectors = json.loads(
        (ROOT / "fixtures/project_a/event_v1_known_vectors.json").read_text(encoding="utf-8")
    )
    wire = deepcopy(vectors["documents"]["rejection_ready"])
    wire["extensions"]["observed_spread_points"] = 8
    return wire


def canonical_event() -> dict:
    raw = canonical_json_bytes(wire_event())
    context = issue_replay_receipt_context(
        raw,
        receipt_id="rcpt_session3_test_0001",
        received_at="2026-07-16T01:01:01.250Z",
        transport_identity="recorded_session3_test_0001",
        source_adapter_identity="session3_test_fixture_v1",
        immutable_raw_reference="recorded_session3_test_wire_0001",
        canonicalized_at="2026-07-16T01:01:01.300Z",
        replay_clock="2026-07-16T01:01:01.300Z",
    )
    result = process_wire_event_v1_receipt(raw, context, InMemoryDedupeAuthority())
    assert result.processing_status == "ACCEPTED"
    return result.canonical_document.document


def adapter_fixture() -> dict:
    return json.loads(
        (ROOT / "samples/session_3_project_a/analysis_adapter.fixture.json").read_text(
            encoding="utf-8"
        )
    )


def analysis_adapter(canonical: dict | None = None) -> dict:
    return bind_disabled_analysis_adapter(canonical or canonical_event(), adapter_fixture())


def source_pair() -> tuple[dict, dict]:
    canonical = canonical_event()
    return canonical, analysis_adapter(canonical)


def profile_dict(**updates) -> dict:
    data = {
        "symbol": "XAUUSD",
        "enabled": True,
        "real_browser_enabled": False,
        "aliases": ["ICMARKETS:XAUUSD"],
        "broker_feed": "ICMARKETS",
        "host": "127.0.0.1",
        "port": 4999,
        "base_timeframe": "1m",
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "expected_layout_id": "ProjectAXAU1",
        "expected_chart_url": "https://www.tradingview.com/chart/ProjectAXAU1/",
        "expected_chart_count": 1,
        "process_names": ["chrome.exe"],
        "profile_marker": "ProjectA-XAUUSD-4999",
    }
    data.update(updates)
    return data


@pytest.fixture
def profile() -> CaptureProfile:
    return CaptureProfile.from_dict(profile_dict())


@pytest.fixture
def pin(profile) -> TabPin:
    return TabPin.from_dict(
        {
            "target_id": "TARGET_PROJECT_A_XAUUSD",
            "chart_url": profile.expected_chart_url,
            "layout_id": profile.expected_layout_id,
        }
    )


def endpoint(**updates) -> EndpointInfo:
    data = dict(
        available=True,
        host="127.0.0.1",
        port=4999,
        local_addresses=("127.0.0.1",),
        pid=1234,
        process_name="chrome.exe",
        command_line=(
            "chrome.exe --remote-debugging-port=4999 "
            "--user-data-dir=C:\\Profiles\\ProjectA-XAUUSD-4999"
        ),
        browser="Chrome/149.0",
        protocol_version="1.3",
    )
    data.update(updates)
    return EndpointInfo(**data)


def targets(profile, pin) -> list[TargetInfo]:
    return [TargetInfo(pin.target_id, "page", profile.expected_chart_url, "Project A")]


def chart_state(profile, timeframe="1m", **updates) -> ChartState:
    data = dict(
        page_ready=True,
        authenticated=True,
        url=profile.expected_chart_url,
        layout_id=profile.expected_layout_id,
        chart_count=1,
        structured_symbol="ICMARKETS:XAUUSD",
        canonical_symbol="XAUUSD",
        header_symbol="XAUUSD",
        broker_feed="ICMARKETS",
        header_feed="ICMARKETS",
        timeframe=timeframe,
        header_timeframe=timeframe,
        available_timeframes=REQUIRED_TIMEFRAMES,
        data_status="streaming",
        last_bar_at=EVENT_TIME,
        last_update_at=NOW,
        modal_blocking=False,
        disconnected=False,
        loading=False,
    )
    data.update(updates)
    return ChartState(**data)


def complete_attempt(tmp_path, profile, canonical=None, adapter=None):
    canonical = canonical or canonical_event()
    adapter = adapter or analysis_adapter(canonical)
    authority = validate_analysis_ready(canonical, adapter, require_compiler_fields=True)
    store = ArtifactStore(tmp_path)
    attempt_dir, manifest = store.begin(
        authority,
        profile,
        dispatch_id="dispatch-fixture-0001",
        retry_count=0,
        started_at=NOW - timedelta(seconds=30),
        capture_method="FIXTURE",
        tool_version="pytest/1.1",
    )
    verification = {
        "page_ready": True,
        "authenticated": True,
        "tab_url_verified": True,
        "layout_verified": True,
        "symbol_verified": True,
        "feed_verified": True,
        "timeframe_verified": True,
        "required_timeframes_available": True,
        "streaming_verified": True,
        "source_bar_covered": True,
    }
    for timeframe in REQUIRED_TIMEFRAMES:
        data = ("synthetic-png-" + timeframe).encode()
        store.add_artifact(
            attempt_dir,
            manifest,
            timeframe=timeframe,
            observed_timeframe=timeframe,
            captured_at=NOW,
            data=data,
            mime_type="image/png",
            capture_method="FIXTURE",
            chart_bar_at=EVENT_TIME,
            verification=verification,
        )
    path = store.finalize(
        attempt_dir,
        manifest,
        finished_at=NOW + timedelta(seconds=10),
        preflight={
            "synthetic_fixture": True,
            "real_endpoint_inspected": False,
            "real_browser_used": False,
            "runtime_compatibility_claim": "NONE",
        },
        restored_base_timeframe=True,
    )
    return canonical, adapter, attempt_dir, manifest, path


def assert_code(code, func):
    with pytest.raises(Session3Error) as caught:
        func()
    assert caught.value.code == code
    return caught.value


def test_canonical_v1_and_disabled_adapter_are_capture_input():
    canonical, adapter = source_pair()
    authority = validate_analysis_ready(canonical, adapter, require_compiler_fields=True)
    assert authority.canonical_event_id == canonical["canonical_event_id"]
    assert authority.setup_id == canonical["setup_id"]
    assert authority.receipt_id == canonical["receipt"]["receipt_id"]
    assert authority.adapter_output_hash.startswith("sha256:")


def test_canonical_v1_without_versioned_adapter_cannot_compile():
    canonical = canonical_event()
    authority = validate_analysis_ready(canonical)
    assert authority.analysis is None
    assert_code(
        "COMPILATION_INPUT_MISSING",
        lambda: validate_analysis_ready(canonical, require_compiler_fields=True),
    )


def test_legacy_v02_event_is_not_session3_authority():
    cases = json.loads((ROOT / "fixtures/project_a/event_cases.json").read_text(encoding="utf-8"))
    assert_code(
        "SOURCE_INVALID",
        lambda: validate_analysis_ready(cases["accepted_alert"]["payload"]),
    )


@pytest.mark.parametrize(
    "path,value",
    [
        (("canonical_content_hash",), "sha256:" + "0" * 64),
        (("canonical_event_id",), "cevt_" + "0" * 64),
        (("semantic_evidence_hash",), "sha256:" + "0" * 64),
        (("setup_id",), "setup_" + "0" * 32),
    ],
)
def test_canonical_lineage_tamper_fails(path, value):
    canonical = canonical_event()
    canonical[path[0]] = value
    assert_code(
        "CANONICAL_LINEAGE_INVALID",
        lambda: validate_analysis_ready(canonical, analysis_adapter()),
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda adapter: adapter.update(runtime_enabled=True),
        lambda adapter: adapter.update(status="ENABLED"),
        lambda adapter: adapter["source"].update(receipt_id="rcpt_other_00000001"),
        lambda adapter: adapter["source"].update(raw_content_hash="sha256:" + "0" * 64),
        lambda adapter: adapter["payload"]["analysis"].update(trigger_price=2417.0),
        lambda adapter: adapter["payload"]["analysis"].update(spread_points=9),
    ],
)
def test_adapter_identity_and_lineage_tamper_fails(mutator):
    canonical, adapter = source_pair()
    mutator(adapter)
    assert_code(
        "ADAPTER_LINEAGE_INVALID",
        lambda: validate_analysis_ready(canonical, adapter, require_compiler_fields=True),
    )


def test_adapter_convention_is_explicit_and_disabled():
    canonical, adapter = source_pair()
    assert adapter["adapter_family"] == ADAPTER_FAMILY
    assert adapter["adapter_version"] == ADAPTER_VERSION
    assert adapter["status"] == ADAPTER_STATUS
    assert adapter["runtime_enabled"] is False
    assert "analysis" not in canonical["wire_event"].get("extensions", {})


@pytest.mark.parametrize("bad", [9222, 9333, 5000])
def test_port_other_than_4999_is_rejected(bad):
    assert_code("PORT_MISMATCH", lambda: CaptureProfile.from_dict(profile_dict(port=bad)))


def test_real_browser_is_disabled_before_any_probe_io(profile, monkeypatch):
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr("capture.project_a.cdp.subprocess.run", forbidden)
    assert_code("RUNTIME_ACTIVATION_DISABLED", lambda: WindowsCdpProbe().inspect(profile))
    assert called is False


def test_unavailable_exact_port_fails_closed(profile):
    assert_code("PORT_UNAVAILABLE", lambda: verify_endpoint(profile, endpoint(available=False)))


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"process_name": "python.exe"}, "WRONG_PROCESS"),
        ({"command_line": "chrome.exe --remote-debugging-port=4999"}, "WRONG_PROCESS"),
        ({"local_addresses": ("0.0.0.0",)}, "UNSAFE_BINDING"),
        ({"browser": "", "protocol_version": ""}, "MCP_UNAVAILABLE"),
    ],
)
def test_wrong_process_binding_or_invalid_cdp_fails(profile, changes, code):
    assert_code(code, lambda: verify_endpoint(profile, endpoint(**changes)))


def test_no_matching_pinned_tab_fails(profile, pin):
    assert_code("TAB_NOT_FOUND", lambda: select_pinned_target(profile, pin, []))


def test_multiple_matching_tabs_fail(profile, pin):
    duplicate = [
        TargetInfo(pin.target_id, "page", profile.expected_chart_url),
        TargetInfo("OTHER", "page", profile.expected_chart_url),
    ]
    assert_code("TAB_AMBIGUOUS", lambda: select_pinned_target(profile, pin, duplicate))


def test_wrong_tab_url_fails(profile, pin):
    wrong = [
        TargetInfo(
            pin.target_id,
            "page",
            "https://www.tradingview.com/chart/WrongLayout/",
        )
    ]
    assert_code("WRONG_TAB", lambda: select_pinned_target(profile, pin, wrong))


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"structured_symbol": "ICMARKETS:XAGUSD", "canonical_symbol": "XAGUSD"}, "WRONG_SYMBOL"),
        ({"header_symbol": "XAGUSD"}, "WRONG_SYMBOL"),
        ({"broker_feed": "OANDA"}, "WRONG_FEED"),
        ({"header_feed": "OANDA"}, "WRONG_FEED"),
        ({"timeframe": "5m", "header_timeframe": "5m"}, "WRONG_TIMEFRAME"),
        ({"layout_id": "WrongLayout"}, "WRONG_LAYOUT"),
        ({"available_timeframes": ("1m", "5m")}, "MISSING_TIMEFRAME"),
        ({"data_status": "stale"}, "STALE_CHART"),
        (
            {
                "last_bar_at": EVENT_TIME - timedelta(minutes=2),
                "last_update_at": EVENT_TIME - timedelta(minutes=2),
            },
            "STALE_CHART",
        ),
        ({"modal_blocking": True}, "MODAL_BLOCKING"),
    ],
)
def test_chart_identity_and_freshness_fail_closed(profile, changes, code):
    canonical, adapter = source_pair()
    authority = validate_analysis_ready(canonical, adapter, require_compiler_fields=True)
    state = chart_state(profile, **changes)
    assert_code(
        code,
        lambda: verify_chart_state(
            profile,
            authority,
            state,
            expected_timeframe="1m",
            observed_at=NOW,
        ),
    )


def test_complete_preflight_uses_exact_target_and_identity_signals(profile, pin):
    canonical, adapter = source_pair()
    authority = validate_analysis_ready(canonical, adapter, require_compiler_fields=True)
    result = verify_preflight(
        profile,
        pin,
        endpoint(),
        targets(profile, pin),
        chart_state(profile),
        authority,
        observed_at=NOW,
        destination_writable=True,
    )
    assert result["target_id"] == pin.target_id
    assert result["symbol_verified"] and result["feed_verified"]


def test_expired_adapter_authority_fails_closed():
    canonical, adapter = source_pair()
    authority = validate_analysis_ready(canonical, adapter, require_compiler_fields=True)
    assert_code("SOURCE_EXPIRED", lambda: authority.ensure_unexpired(EXPIRES))


def test_capture_clock_before_canonicalization_fails_closed(tmp_path, profile):
    canonical, adapter = source_pair()
    authority = validate_analysis_ready(canonical, adapter, require_compiler_fields=True)
    store = ArtifactStore(tmp_path)
    assert_code(
        "SOURCE_INVALID",
        lambda: store.begin(
            authority,
            profile,
            dispatch_id="dispatch-chronology",
            retry_count=0,
            started_at=datetime(2026, 7, 16, 1, 1, 1, 200000, tzinfo=UTC),
            capture_method="FIXTURE",
            tool_version="pytest/1.1",
        ),
    )


def test_partial_capture_never_compiles(tmp_path, profile):
    canonical, adapter, _, manifest, _ = complete_attempt(tmp_path, profile)
    manifest["status"] = "FAILED"
    manifest["failure"] = {"code": "SCREENSHOT_FAILURE"}
    assert_code(
        "PARTIAL_CAPTURE",
        lambda: compile_analysis_request(canonical, adapter, manifest, profile, created_at=NOW),
    )


def test_artifact_bytes_are_hashed_and_labeled_synthetic(tmp_path, profile):
    _, _, _, manifest, path = complete_attempt(tmp_path, profile)
    verified = verify_manifest(path)
    first = verified["artifacts"][0]
    assert first["sha256"] == sha256_bytes(b"synthetic-png-5s")
    assert manifest["synthetic"] is True
    assert manifest["evidence_classification"] == "SYNTHETIC_FIXTURE"
    assert manifest["runtime_compatibility_claim"] == "NONE"
    assert first["synthetic"] is True


def test_modified_or_missing_artifact_fails_verification(tmp_path, profile):
    _, _, root, manifest, path = complete_attempt(tmp_path, profile)
    artifact = root / manifest["artifacts"][0]["artifact_path"]
    artifact.write_bytes(b"corrupt")
    assert_code("ARTIFACT_HASH_MISMATCH", lambda: verify_manifest(path))
    artifact.unlink()
    assert_code("ARTIFACT_MISSING", lambda: verify_manifest(path))


def test_same_lineage_manifest_and_clock_reproduce_identical_request(tmp_path, profile):
    canonical, adapter, _, manifest, _ = complete_attempt(tmp_path, profile)
    first = compile_analysis_request(canonical, adapter, manifest, profile, created_at=NOW + timedelta(seconds=10))
    second = compile_analysis_request(
        deepcopy(canonical),
        deepcopy(adapter),
        deepcopy(manifest),
        profile,
        created_at=NOW + timedelta(seconds=10),
    )
    assert canonical_json(first) == canonical_json(second)
    validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, first)


def test_request_manifest_setup_canonical_and_receipt_lineage_are_bound(tmp_path, profile):
    canonical, adapter, _, manifest, _ = complete_attempt(tmp_path, profile)
    request = compile_analysis_request(
        canonical,
        adapter,
        manifest,
        profile,
        created_at=NOW + timedelta(seconds=10),
    )
    expected_source = "evt_" + canonical["canonical_event_id"].removeprefix("cevt_")
    assert manifest["request_id"] == request["request_id"]
    assert request["setup_id"] == canonical["setup_id"]
    assert request["causation_id"] == expected_source
    assert request["source_event_ids"] == [expected_source]
    assert manifest["canonical_event_id"] == canonical["canonical_event_id"]
    assert manifest["canonical_content_hash"] == canonical["canonical_content_hash"]
    assert manifest["semantic_evidence_hash"] == canonical["semantic_evidence_hash"]
    assert manifest["receipt_id"] == canonical["receipt"]["receipt_id"]
    assert manifest["raw_content_hash"] == canonical["receipt"]["raw_content_hash"]
    assert manifest["analysis_adapter_hash"].startswith("sha256:")
    assert [item.split(":", 1)[0] for item in request["screenshots_required"]] == list(
        REQUIRED_TIMEFRAMES
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("canonical_content_hash", "sha256:" + "0" * 64),
        ("receipt_id", "rcpt_other_00000001"),
        ("raw_content_hash", "sha256:" + "0" * 64),
        ("analysis_adapter_hash", "sha256:" + "0" * 64),
    ],
)
def test_manifest_lineage_tamper_blocks_compilation(tmp_path, profile, field, value):
    canonical, adapter, _, manifest, _ = complete_attempt(tmp_path, profile)
    manifest[field] = value
    assert_code(
        "CONTRACT_COMPILATION_FAILURE",
        lambda: compile_analysis_request(
            canonical,
            adapter,
            manifest,
            profile,
            created_at=NOW + timedelta(seconds=10),
        ),
    )


def test_spread_and_rr_contract_failures_are_not_widened(tmp_path, profile):
    canonical, adapter, _, manifest, _ = complete_attempt(tmp_path, profile)
    bad_adapter = deepcopy(adapter)
    bad_adapter["payload"]["analysis"]["spread_points"] = 11
    assert_code(
        "ADAPTER_LINEAGE_INVALID",
        lambda: compile_analysis_request(
            canonical,
            bad_adapter,
            manifest,
            profile,
            created_at=NOW + timedelta(seconds=10),
        ),
    )
    bad_adapter = deepcopy(adapter)
    bad_adapter["payload"]["analysis"]["tp_candidate"] = 2419.0
    assert_code(
        "ADAPTER_LINEAGE_INVALID",
        lambda: compile_analysis_request(
            canonical,
            bad_adapter,
            manifest,
            profile,
            created_at=NOW + timedelta(seconds=10),
        ),
    )


def test_duplicate_completed_dispatch_is_idempotent(tmp_path):
    canonical, adapter = source_pair()
    ledger = FileDispatchLedger(tmp_path / "ledger")
    envelope = DispatchEnvelope("dispatch-001", canonical, adapter, 0, utc_z(NOW))
    calls = []

    def handler(_, attempt_id):
        calls.append(attempt_id)
        return {
            "request_id": "req_completed_00000001",
            "bundle_path": "bundle",
            "release_to_session_4": False,
        }

    first = consume_dispatch(envelope, ledger, handler)
    second = consume_dispatch(envelope, FileDispatchLedger(tmp_path / "ledger"), handler)
    assert first["status"] == "COMPLETED" and not first["idempotent"]
    assert second["status"] == "COMPLETED" and second["idempotent"]
    assert first["release_to_session_4"] is False
    assert len(calls) == 1


def test_conflicting_duplicate_dispatch_fails_closed(tmp_path):
    canonical, adapter = source_pair()
    ledger = FileDispatchLedger(tmp_path / "ledger")
    first = DispatchEnvelope("dispatch-001", canonical, adapter, 0, utc_z(NOW))
    consume_dispatch(first, ledger, lambda *_: {"request_id": "req_completed_00000001"})
    conflict = deepcopy(adapter)
    conflict["payload"]["analysis"]["session"] = "LONDON"
    envelope = DispatchEnvelope("dispatch-001", canonical, conflict, 1, utc_z(NOW))
    assert_code(
        "DISPATCH_CONFLICT",
        lambda: consume_dispatch(envelope, ledger, lambda *_: {}),
    )


def test_retry_does_not_extend_expiry(tmp_path):
    canonical, adapter = source_pair()
    ledger = FileDispatchLedger(tmp_path / "ledger")
    calls = 0

    def handler(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Session3Error("SCREENSHOT_FAILURE", "synthetic failure")
        return {"request_id": "req_completed_00000001", "release_to_session_4": False}

    first = consume_dispatch(
        DispatchEnvelope("dispatch-retry", canonical, adapter, 0, utc_z(NOW)),
        ledger,
        handler,
    )
    second = consume_dispatch(
        DispatchEnvelope(
            "dispatch-retry",
            canonical,
            adapter,
            1,
            utc_z(NOW + timedelta(minutes=1)),
        ),
        ledger,
        handler,
    )
    stored = ledger.load("dispatch-retry")
    assert first["status"] == "FAILED" and second["status"] == "COMPLETED"
    assert [item["retry_count"] for item in stored["attempts"]] == [0, 1]
    assert stored["attempts"][0]["result"]["attempt_id"] != stored["attempts"][1]["result"]["attempt_id"]
    assert adapter["payload"]["analysis"]["expires_at"] == utc_z(EXPIRES)


class FakeProbe:
    def __init__(self, profile, pin):
        self.profile, self.pin = profile, pin

    def inspect(self, _):
        return endpoint(), targets(self.profile, self.pin)


class FakeDriver:
    def __init__(self, profile, *, fail_on=None):
        self.profile = profile
        self.fail_on = fail_on
        self.sequence = []
        self.current = "1m"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def inspect(self):
        return chart_state(self.profile, self.current)

    def switch_and_wait(self, timeframe):
        self.sequence.append(timeframe)
        self.current = timeframe
        return chart_state(self.profile, timeframe)

    def screenshot(self):
        if self.current == self.fail_on:
            raise Session3Error("SCREENSHOT_FAILURE", f"failed {self.current}")
        return ("synthetic-png-" + self.current).encode()


def test_synthetic_capture_restores_and_verifies_1m(tmp_path, profile, pin):
    canonical, adapter = source_pair()
    driver = FakeDriver(profile)
    manifest, path = capture_event(
        canonical,
        adapter,
        profile,
        pin,
        ArtifactStore(tmp_path),
        FakeProbe(profile, pin),
        lambda _: driver,
        dispatch_id="dispatch-fixture-001",
        retry_count=0,
        now=lambda: NOW,
        capture_method="FIXTURE",
    )
    assert Path(path).exists()
    assert manifest["status"] == "COMPLETE"
    assert manifest["restored_base_timeframe"] is True
    assert manifest["synthetic"] is True
    assert driver.sequence == [*REQUIRED_TIMEFRAMES, "1m"]


def test_real_capture_path_is_disabled_before_probe(tmp_path, profile, pin):
    canonical, adapter = source_pair()
    called = False

    class ForbiddenProbe:
        def inspect(self, _):
            nonlocal called
            called = True
            raise AssertionError("probe must not run")

    assert_code(
        "RUNTIME_ACTIVATION_DISABLED",
        lambda: capture_event(
            canonical,
            adapter,
            profile,
            pin,
            ArtifactStore(tmp_path),
            ForbiddenProbe(),
            lambda _: FakeDriver(profile),
            dispatch_id="dispatch-real-disabled",
            retry_count=0,
            now=lambda: NOW,
        ),
    )
    assert called is False


def test_screenshot_failure_retains_partial_synthetic_manifest(tmp_path, profile, pin):
    canonical, adapter = source_pair()
    driver = FakeDriver(profile, fail_on="15m")
    error = assert_code(
        "SCREENSHOT_FAILURE",
        lambda: capture_event(
            canonical,
            adapter,
            profile,
            pin,
            ArtifactStore(tmp_path),
            FakeProbe(profile, pin),
            lambda _: driver,
            dispatch_id="dispatch-fixture-002",
            retry_count=0,
            now=lambda: NOW,
            capture_method="FIXTURE",
        ),
    )
    attempt = tmp_path / error.attempt_id
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert manifest["failure"]["code"] == "SCREENSHOT_FAILURE"
    assert manifest["synthetic"] is True
    assert not (attempt / "analysis_request.json").exists()
    assert manifest["restored_base_timeframe"] is True


def test_synthetic_bundle_is_retained_and_never_released(tmp_path, profile):
    canonical, adapter, attempt_dir, manifest, _ = complete_attempt(
        tmp_path / "capture",
        profile,
    )
    request = compile_analysis_request(
        canonical,
        adapter,
        manifest,
        profile,
        created_at=NOW + timedelta(seconds=10),
    )
    decision = release_decision(request, manifest, at=NOW + timedelta(seconds=10))
    assert decision["status"] == "SYNTHETIC_RETAINED"
    assert decision["release_to_session_4"] is False
    write_bundle(
        attempt_dir,
        canonical_event=canonical,
        analysis_adapter=adapter,
        manifest=manifest,
        request=request,
        release_at=NOW + timedelta(seconds=10),
    )
    replayed = replay_bundle(attempt_dir, profile, replay_at=EXPIRES)
    assert replayed["release"]["status"] == "EXPIRED_RETAINED"
    assert replayed["release"]["release_to_session_4"] is False


def test_offline_replay_preserves_lineage_without_live_dependencies(tmp_path, profile):
    canonical, adapter, attempt_dir, manifest, _ = complete_attempt(
        tmp_path / "capture",
        profile,
    )
    request = compile_analysis_request(
        canonical,
        adapter,
        manifest,
        profile,
        created_at=NOW + timedelta(seconds=10),
    )
    write_bundle(
        attempt_dir,
        canonical_event=canonical,
        analysis_adapter=adapter,
        manifest=manifest,
        request=request,
        release_at=NOW + timedelta(seconds=10),
    )
    result = replay_bundle(attempt_dir, profile)
    assert result["ok"] is True and result["artifact_count"] == 5
    assert result["canonical_event_id"] == canonical["canonical_event_id"]
    assert result["receipt_id"] == canonical["receipt"]["receipt_id"]
    assert result["evidence_classification"] == "SYNTHETIC_FIXTURE"
    assert result["runtime_compatibility_claim"] == "NONE"
    assert result["release"]["release_to_session_4"] is False
    assert not result["network_used"] and not result["browser_used"] and not result["ai_used"]


def test_profile_is_exact_xauusd_icmarkets_1m_and_real_browser_default_off():
    profile = CaptureProfile.from_dict(profile_dict())
    assert profile.symbol == "XAUUSD"
    assert profile.broker_feed == "ICMARKETS"
    assert profile.base_timeframe == "1m"
    assert profile.real_browser_enabled is False
    assert_code(
        "WRONG_SYMBOL",
        lambda: CaptureProfile.from_dict(
            profile_dict(symbol="USTEC", aliases=["NASDAQ:USTEC"])
        ),
    )
    assert_code(
        "WRONG_FEED",
        lambda: CaptureProfile.from_dict(
            profile_dict(broker_feed="OANDA", aliases=["OANDA:XAUUSD"])
        ),
    )


def test_profile_rejects_wildcard_or_partial_aliases():
    assert_code(
        "WRONG_SYMBOL",
        lambda: CaptureProfile.from_dict(profile_dict(aliases=["XAU*"])),
    )
    assert_code(
        "WRONG_FEED",
        lambda: CaptureProfile.from_dict(profile_dict(aliases=["OANDA:XAUUSD"])),
    )
