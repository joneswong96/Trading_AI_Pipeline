from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts import ANALYSIS_REQUEST_SCHEMA_V1, canonical_json, validate_contract
from capture.project_a.artifacts import ArtifactStore, sha256_bytes, verify_manifest
from capture.project_a.compiler import compile_analysis_request
from capture.project_a.consumer import DispatchEnvelope, FileDispatchLedger, consume_dispatch
from capture.project_a.coordinator import capture_event
from capture.project_a.errors import Session3Error
from capture.project_a.input_boundary import utc_z, validate_analysis_ready
from capture.project_a.preflight import (
    ChartState, EndpointInfo, TargetInfo, select_pinned_target, verify_chart_state,
    verify_endpoint, verify_preflight,
)
from capture.project_a.profile import CaptureProfile, REQUIRED_TIMEFRAMES, TabPin
from capture.project_a.replay import release_decision, replay_bundle, write_bundle

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
EVENT_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 16, 0, 2, tzinfo=UTC)
EXPIRES = datetime(2026, 7, 16, 0, 10, tzinfo=UTC)


def frozen_event() -> dict:
    cases = json.loads((ROOT / "fixtures/project_a/event_cases.json").read_text(encoding="utf-8"))
    return deepcopy(cases["accepted_alert"]["payload"])


def enriched_event() -> dict:
    event = frozen_event()
    event["payload"]["analysis"] = {
        "expires_at": utc_z(EXPIRES),
        "bar_time": utc_z(EVENT_TIME),
        "session": "ASIAN",
        "snr": {"low": 2415.0, "high": 2416.0, "type": "CLASSIC"},
        "hpa": ["M15_DISCOUNT", "M5_DISCOUNT"],
        "momentum": {
            "5s": {"classification": "UNAVAILABLE", "direction": None, "source": "FIXTURE"},
            "1m": {"classification": "EXHAUSTING", "direction": "SHORT", "source": "FIXTURE"},
            "5m": {"classification": "WEAK_PUSH", "direction": "SHORT", "source": "FIXTURE"},
            "15m": {"classification": "WEAK_PUSH", "direction": "SHORT", "source": "FIXTURE"},
            "30m": {"classification": "RANGE_DRIFT", "direction": "NEUTRAL", "source": "FIXTURE"},
        },
        "trigger_price": 2416.5,
        "spread_points": 8,
        "entry_candidate": 2416.5,
        "sl_candidate": 2414.5,
        "tp_candidate": 2418.5,
        "source_event_ids": [event["event_id"]],
        "snr_evidence": "fixture reaction",
        "hpa_evidence": "M15 and M5 discount",
        "trigger_reason": "M1 reaction confirmed",
    }
    return event


def profile_dict(**updates) -> dict:
    data = {
        "symbol": "XAUUSD",
        "enabled": True,
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
    return TabPin.from_dict({
        "target_id": "TARGET_PROJECT_A_XAUUSD",
        "chart_url": profile.expected_chart_url,
        "layout_id": profile.expected_layout_id,
    })


def endpoint(**updates) -> EndpointInfo:
    data = dict(
        available=True, host="127.0.0.1", port=4999,
        local_addresses=("127.0.0.1",), pid=1234,
        process_name="chrome.exe",
        command_line=("chrome.exe --remote-debugging-port=4999 "
                      "--user-data-dir=C:\\Profiles\\ProjectA-XAUUSD-4999"),
        browser="Chrome/149.0", protocol_version="1.3",
    )
    data.update(updates)
    return EndpointInfo(**data)


def targets(profile, pin) -> list[TargetInfo]:
    return [TargetInfo(pin.target_id, "page", profile.expected_chart_url, "Project A")]


def chart_state(profile, timeframe="1m", **updates) -> ChartState:
    data = dict(
        page_ready=True, authenticated=True, url=profile.expected_chart_url,
        layout_id=profile.expected_layout_id, chart_count=1,
        structured_symbol="ICMARKETS:XAUUSD", canonical_symbol="XAUUSD",
        header_symbol="XAUUSD", broker_feed="ICMARKETS", header_feed="ICMARKETS",
        timeframe=timeframe, header_timeframe=timeframe,
        available_timeframes=REQUIRED_TIMEFRAMES, data_status="streaming",
        last_bar_at=EVENT_TIME, last_update_at=NOW,
        modal_blocking=False, disconnected=False, loading=False,
    )
    data.update(updates)
    return ChartState(**data)


def complete_attempt(tmp_path, profile, event=None):
    event = event or enriched_event()
    authority = validate_analysis_ready(event, require_compiler_fields=True)
    store = ArtifactStore(tmp_path)
    attempt_dir, manifest = store.begin(
        authority, profile, dispatch_id="dispatch-fixture-0001", retry_count=0,
        started_at=NOW - timedelta(seconds=30), capture_method="FIXTURE",
        tool_version="pytest/1",
    )
    verification = {
        "page_ready": True, "authenticated": True, "tab_url_verified": True,
        "layout_verified": True, "symbol_verified": True, "feed_verified": True,
        "timeframe_verified": True, "required_timeframes_available": True,
        "streaming_verified": True, "source_bar_covered": True,
    }
    for tf in REQUIRED_TIMEFRAMES:
        data = ("fake-png-" + tf).encode()
        store.add_artifact(
            attempt_dir, manifest, timeframe=tf, observed_timeframe=tf,
            captured_at=NOW, data=data, mime_type="image/png", capture_method="FIXTURE",
            chart_bar_at=EVENT_TIME, verification=verification,
        )
    path = store.finalize(
        attempt_dir, manifest, finished_at=NOW + timedelta(seconds=10),
        preflight={"endpoint_verified": True}, restored_base_timeframe=True,
    )
    return attempt_dir, manifest, path


def assert_code(code, func):
    with pytest.raises(Session3Error) as caught:
        func()
    assert caught.value.code == code
    return caught.value


def test_valid_frozen_analysis_ready_fixture_is_capture_input():
    authority = validate_analysis_ready(frozen_event())
    assert authority.event_id == "evt_xau_20260716_0001"
    assert authority.analysis is None


def test_frozen_fixture_without_compiler_extension_fails_closed():
    assert_code("COMPILATION_INPUT_MISSING", lambda: validate_analysis_ready(
        frozen_event(), require_compiler_fields=True))


def test_telemetry_is_rejected_as_capture_authority():
    event = frozen_event()
    event.update(event_class="TELEMETRY", event_type="SNR_UPDATE", setup_id=None,
                 hypothesis=None, path=None)
    assert_code("SOURCE_INVALID", lambda: validate_analysis_ready(event))


def test_setup_candidate_is_rejected_as_capture_authority():
    cases = json.loads((ROOT / "fixtures/project_a/event_cases.json").read_text())
    candidate = cases["rejected_alert"]["payload"]
    assert_code("SOURCE_INVALID", lambda: validate_analysis_ready(candidate))


def test_wrong_schema_version_is_rejected():
    event = enriched_event()
    event["schema_version"] = "0.1"
    assert_code("SOURCE_INVALID", lambda: validate_analysis_ready(event))


@pytest.mark.parametrize("bad", [9222, 9333, 5000])
def test_port_other_than_4999_is_rejected(bad):
    assert_code("PORT_MISMATCH", lambda: CaptureProfile.from_dict(profile_dict(port=bad)))


def test_unavailable_port_fails_closed(profile):
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
    wrong = [TargetInfo(pin.target_id, "page", "https://www.tradingview.com/chart/WrongLayout/")]
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
        ({"last_bar_at": EVENT_TIME - timedelta(minutes=2),
          "last_update_at": EVENT_TIME - timedelta(minutes=2)}, "STALE_CHART"),
        ({"modal_blocking": True}, "MODAL_BLOCKING"),
    ],
)
def test_chart_identity_and_freshness_fail_closed(profile, changes, code):
    authority = validate_analysis_ready(enriched_event(), require_compiler_fields=True)
    state = chart_state(profile, **changes)
    assert_code(code, lambda: verify_chart_state(
        profile, authority, state, expected_timeframe="1m", observed_at=NOW))


def test_complete_preflight_uses_exact_target_and_two_identity_signals(profile, pin):
    authority = validate_analysis_ready(enriched_event(), require_compiler_fields=True)
    result = verify_preflight(
        profile, pin, endpoint(), targets(profile, pin), chart_state(profile), authority,
        observed_at=NOW, destination_writable=True,
    )
    assert result["target_id"] == pin.target_id
    assert result["symbol_verified"] and result["feed_verified"]


def test_expired_source_event_fails_closed():
    event = enriched_event()
    authority = validate_analysis_ready(event, require_compiler_fields=True)
    assert_code("SOURCE_EXPIRED", lambda: authority.ensure_unexpired(EXPIRES))


def test_partial_capture_never_compiles(tmp_path, profile):
    _, manifest, _ = complete_attempt(tmp_path, profile)
    manifest["status"] = "FAILED"
    manifest["failure"] = {"code": "SCREENSHOT_FAILURE"}
    assert_code("PARTIAL_CAPTURE", lambda: compile_analysis_request(
        enriched_event(), manifest, profile, created_at=NOW))


def test_artifact_bytes_are_hashed_correctly(tmp_path, profile):
    _, manifest, path = complete_attempt(tmp_path, profile)
    verified = verify_manifest(path)
    first = verified["artifacts"][0]
    assert first["sha256"] == sha256_bytes(b"fake-png-5s")


def test_modified_artifact_fails_hash_verification(tmp_path, profile):
    root, manifest, path = complete_attempt(tmp_path, profile)
    artifact = root / manifest["artifacts"][0]["artifact_path"]
    artifact.write_bytes(b"corrupt")
    assert_code("ARTIFACT_HASH_MISMATCH", lambda: verify_manifest(path))


def test_missing_artifact_fails_replay(tmp_path, profile):
    root, manifest, path = complete_attempt(tmp_path, profile)
    (root / manifest["artifacts"][0]["artifact_path"]).unlink()
    assert_code("ARTIFACT_MISSING", lambda: verify_manifest(path))


def test_same_event_manifest_and_clock_reproduce_identical_request(tmp_path, profile):
    _, manifest, _ = complete_attempt(tmp_path, profile)
    first = compile_analysis_request(enriched_event(), manifest, profile, created_at=NOW)
    second = compile_analysis_request(enriched_event(), deepcopy(manifest), profile, created_at=NOW)
    assert canonical_json(first) == canonical_json(second)
    validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, first)


def test_stable_identifiers_propagate_and_hash_refs_cover_all_timeframes(tmp_path, profile):
    _, manifest, _ = complete_attempt(tmp_path, profile)
    event = enriched_event()
    request = compile_analysis_request(event, manifest, profile, created_at=NOW)
    assert manifest["request_id"] == request["request_id"]
    assert manifest["causation_id"] == event["event_id"]
    assert manifest["source_causation_id"] == event["causation_id"]
    assert request["setup_id"] == event["setup_id"]
    assert request["correlation_id"] == event["correlation_id"]
    assert request["causation_id"] == event["event_id"]
    assert request["source_event_ids"] == [event["event_id"]]
    assert [item.split(":", 1)[0] for item in request["screenshots_required"]] == list(REQUIRED_TIMEFRAMES)


def test_spread_and_rr_contract_failures_are_not_widened(tmp_path, profile):
    _, manifest, _ = complete_attempt(tmp_path, profile)
    event = enriched_event()
    event["payload"]["analysis"]["spread_points"] = 11
    assert_code("CONTRACT_COMPILATION_FAILURE", lambda: compile_analysis_request(
        event, manifest, profile, created_at=NOW))
    event = enriched_event()
    event["payload"]["analysis"]["tp_candidate"] = 2419.0
    assert_code("CONTRACT_COMPILATION_FAILURE", lambda: compile_analysis_request(
        event, manifest, profile, created_at=NOW))


def test_duplicate_completed_dispatch_is_idempotent(tmp_path):
    ledger = FileDispatchLedger(tmp_path / "ledger")
    envelope = DispatchEnvelope("dispatch-001", enriched_event(), 0, utc_z(NOW))
    calls = []

    def handler(_, attempt_id):
        calls.append(attempt_id)
        return {"request_id": "req_completed_00000001", "bundle_path": "bundle", "release_to_session_4": True}

    first = consume_dispatch(envelope, ledger, handler)
    second = consume_dispatch(envelope, FileDispatchLedger(tmp_path / "ledger"), handler)
    assert first["status"] == "COMPLETED" and not first["idempotent"]
    assert second["status"] == "COMPLETED" and second["idempotent"]
    assert len(calls) == 1


def test_conflicting_duplicate_dispatch_fails_closed(tmp_path):
    ledger = FileDispatchLedger(tmp_path / "ledger")
    first = DispatchEnvelope("dispatch-001", enriched_event(), 0, utc_z(NOW))
    consume_dispatch(first, ledger, lambda *_: {"request_id": "req_completed_00000001"})
    conflict_event = enriched_event()
    conflict_event["payload"]["analysis"]["trigger_price"] += 1
    conflict = DispatchEnvelope("dispatch-001", conflict_event, 1, utc_z(NOW))
    assert_code("DISPATCH_CONFLICT", lambda: consume_dispatch(conflict, ledger, lambda *_: {}))


def test_retry_creates_traceable_attempt_history_without_extending_expiry(tmp_path):
    ledger = FileDispatchLedger(tmp_path / "ledger")
    calls = 0

    def handler(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Session3Error("SCREENSHOT_FAILURE", "fixture failure")
        return {"request_id": "req_completed_00000001", "release_to_session_4": True}

    first = consume_dispatch(DispatchEnvelope("dispatch-retry", enriched_event(), 0, utc_z(NOW)), ledger, handler)
    second = consume_dispatch(DispatchEnvelope(
        "dispatch-retry", enriched_event(), 1, utc_z(NOW + timedelta(minutes=1))), ledger, handler)
    stored = ledger.load("dispatch-retry")
    assert first["status"] == "FAILED" and second["status"] == "COMPLETED"
    assert [item["retry_count"] for item in stored["attempts"]] == [0, 1]
    assert stored["attempts"][0]["result"]["attempt_id"] != stored["attempts"][1]["result"]["attempt_id"]
    assert enriched_event()["payload"]["analysis"]["expires_at"] == utc_z(EXPIRES)


def test_retry_after_original_expiry_fails_without_calling_handler(tmp_path):
    ledger = FileDispatchLedger(tmp_path / "ledger")
    event = enriched_event()
    consume_dispatch(
        DispatchEnvelope("dispatch-expiry", event, 0, utc_z(NOW)), ledger,
        lambda *_: (_ for _ in ()).throw(Session3Error("SCREENSHOT_FAILURE", "first")),
    )
    called = False

    def handler(*_):
        nonlocal called
        called = True
        return {}

    result = consume_dispatch(
        DispatchEnvelope("dispatch-expiry", event, 1, utc_z(EXPIRES)), ledger, handler)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "SOURCE_EXPIRED"
    assert called is False


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
        return ("fake-png-" + self.current).encode()


def test_successful_capture_restores_and_verifies_1m(tmp_path, profile, pin):
    driver = FakeDriver(profile)
    manifest, path = capture_event(
        enriched_event(), profile, pin, ArtifactStore(tmp_path), FakeProbe(profile, pin),
        lambda _: driver, dispatch_id="dispatch-live-001", retry_count=0,
        now=lambda: NOW,
    )
    assert Path(path).exists()
    assert manifest["status"] == "COMPLETE"
    assert manifest["restored_base_timeframe"] is True
    assert driver.sequence == [*REQUIRED_TIMEFRAMES, "1m"]


def test_screenshot_failure_retains_partial_manifest_but_no_request(tmp_path, profile, pin):
    driver = FakeDriver(profile, fail_on="15m")
    error = assert_code("SCREENSHOT_FAILURE", lambda: capture_event(
        enriched_event(), profile, pin, ArtifactStore(tmp_path), FakeProbe(profile, pin),
        lambda _: driver, dispatch_id="dispatch-live-002", retry_count=0,
        now=lambda: NOW,
    ))
    attempt = tmp_path / error.attempt_id
    manifest = json.loads((attempt / "manifest.json").read_text())
    assert manifest["status"] == "FAILED"
    assert manifest["failure"]["code"] == "SCREENSHOT_FAILURE"
    assert not (attempt / "analysis_request.json").exists()
    assert manifest["restored_base_timeframe"] is True


def test_expired_request_is_retained_and_not_released_to_session4(tmp_path, profile):
    attempt_dir, manifest, _ = complete_attempt(tmp_path / "capture", profile)
    event = enriched_event()
    request = compile_analysis_request(event, manifest, profile, created_at=NOW)
    write_bundle(attempt_dir, event=event, manifest=manifest, request=request, release_at=NOW)
    replayed = replay_bundle(attempt_dir, profile, replay_at=EXPIRES)
    assert replayed["release"]["status"] == "EXPIRED_RETAINED"
    assert replayed["release"]["release_to_session_4"] is False


def test_offline_replay_detects_same_canonical_bundle_without_live_dependencies(tmp_path, profile):
    attempt_dir, manifest, _ = complete_attempt(tmp_path / "capture", profile)
    event = enriched_event()
    request = compile_analysis_request(event, manifest, profile, created_at=NOW)
    write_bundle(attempt_dir, event=event, manifest=manifest, request=request, release_at=NOW)
    result = replay_bundle(attempt_dir, profile)
    assert result["ok"] is True and result["artifact_count"] == 5
    assert not result["network_used"] and not result["browser_used"] and not result["ai_used"]


def test_multi_symbol_interface_exists_but_only_xauusd_can_be_enabled():
    profile = CaptureProfile.from_dict(profile_dict())
    assert profile.symbol == "XAUUSD"
    assert_code("WRONG_SYMBOL", lambda: CaptureProfile.from_dict(profile_dict(
        symbol="USTEC", aliases=["NASDAQ:USTEC"])))
    assert_code("WRONG_SYMBOL", lambda: CaptureProfile.from_dict(profile_dict(enabled=False)))


def test_profile_rejects_wildcard_or_partial_aliases():
    assert_code("WRONG_SYMBOL", lambda: CaptureProfile.from_dict(profile_dict(aliases=["XAU*"])))
    assert_code("WRONG_FEED", lambda: CaptureProfile.from_dict(profile_dict(aliases=["OANDA:XAUUSD"])))


def test_release_gate_is_ready_only_strictly_before_expiry(tmp_path, profile):
    _, manifest, _ = complete_attempt(tmp_path, profile)
    request = compile_analysis_request(enriched_event(), manifest, profile, created_at=NOW)
    assert release_decision(request, at=EXPIRES - timedelta(seconds=1))["release_to_session_4"] is True
    assert release_decision(request, at=EXPIRES)["release_to_session_4"] is False
