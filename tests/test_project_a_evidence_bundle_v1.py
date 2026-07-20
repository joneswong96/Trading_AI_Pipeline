from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from project_a.evidence_bundle import (
    ApprovedScreenshotRequestAdapter,
    EvidenceBundleError,
    FreshnessRecord,
    FreshnessStatus,
    Port9222RequestAdapter,
    Port9333RequestAdapter,
    RequestLevel,
    ScreenshotRequest,
    SourceIdentity,
    StructuredReadRequest,
    TriggerDecision,
    UnavailableEvidence,
    build_evidence_bundle_request,
    canonical_sha256,
)


NOW = datetime(2026, 7, 20, 3, 4, 5, tzinfo=timezone.utc)


@pytest.fixture
def sources():
    def source(role, port, layout, target, symbol, feed, timeframes):
        return SourceIdentity(role, port, layout, target, symbol, feed, timeframes)

    return {
        "xau_intraday": source("xau_intraday", 9333, "cpPWuLlN", "target-xau-intraday", "XAUUSD", "ICMARKETS", ("1m", "5m", "15m", "30m")),
        "xau_30m_15m": source("xau_30m_15m", 9333, "avpCVaw2", "target-xau-30m-15m", "XAUUSD", "ICMARKETS", ("15m", "30m")),
        "xau_htf": source("xau_htf", 9333, "pNqcbOmu", "target-xau-htf", "XAUUSD", "ICMARKETS", ("4H", "D", "W")),
        "dxy_15m": source("dxy_15m", 9333, "n9qjfufV", "target-dxy-15m", "DXY", "TVC", ("15m",)),
        "dxy_1m": source("dxy_1m", 9222, "ocVwlz2C", "target-dxy-1m", "DXY", "TVC", ("1m",)),
        "renko": source("renko", 9333, "YclFo8Ax", "target-renko", "XAUUSD", "ICMARKETS", ("5s",)),
    }


def build(sources, event="EXP_UP", active=False, **kwargs):
    return build_evidence_bundle_request(
        request_id="evidence_request_001",
        requested_at=NOW,
        triggering_events=({"event": event, "event_id": "event-001", "confirmed": True},),
        event_history=({"event": "EXP_UP", "market_price": "2400.10"},),
        numeric_market_state={"price_path": ["2400.00", "2400.10"], "trade_direction": None},
        sources=sources,
        active_liquidity_expansion_story=active,
        **kwargs,
    )


def test_expansion_alone_is_telemetry_and_requests_no_capture(sources):
    request = build(sources)
    assert request.trigger.level is RequestLevel.TELEMETRY_ONLY
    assert not request.structured_reads
    assert not request.screenshot_requests
    assert request.trigger.provider_call_permitted is False
    assert request.trigger.order_permitted is False


def test_liq_touch_starts_research_and_compiles_numeric_snapshot_only(sources):
    request = build(sources, "LIQ_TOUCH")
    assert request.trigger.level is RequestLevel.NUMERIC_RESEARCH
    assert request.trigger.research_started is True
    assert {item.read_kind for item in request.structured_reads} == {
        "CURRENT_FORMING_PRICE", "CLOSED_OHLC", "STANDARD_MACD",
    }
    assert request.screenshot_requests == ()
    macd = [item for item in request.structured_reads if item.read_kind == "STANDARD_MACD"]
    assert len(macd) == 2
    assert all(item.indicator_parameters == (12, 26, 9) for item in macd)
    assert all(item.closed_bars_only is True for item in macd)


def test_intraday_timeframes_are_split_across_exact_9333_layout_identities(sources):
    request = build(sources, "LIQ_TOUCH")
    numeric = [
        item for item in request.structured_reads
        if item.read_kind in {"CLOSED_OHLC", "STANDARD_MACD"}
    ]
    observed = {
        (item.read_kind, item.timeframes): (item.source.role, item.source.layout_id)
        for item in numeric
    }
    assert observed == {
        ("CLOSED_OHLC", ("1m", "5m")): ("xau_intraday", "cpPWuLlN"),
        ("STANDARD_MACD", ("1m", "5m")): ("xau_intraday", "cpPWuLlN"),
        ("CLOSED_OHLC", ("15m", "30m")): ("xau_30m_15m", "avpCVaw2"),
        ("STANDARD_MACD", ("15m", "30m")): ("xau_30m_15m", "avpCVaw2"),
    }


@pytest.mark.parametrize("event", ["RENKO_E1", "RENKO_E2"])
def test_e1_and_uncorroborated_e2_are_prewarm_only(sources, event):
    request = build(sources, event)
    assert request.trigger.level is RequestLevel.PREWARM_ONLY
    assert request.trigger.prewarm_only is True
    assert not request.structured_reads
    assert not request.screenshot_requests


def test_e2_with_active_story_requests_full_primary_and_supplemental_bundle(sources):
    request = build(sources, "RENKO_E2", active=True)
    assert request.trigger.level is RequestLevel.FULL_B_TO_A_CAPTURE
    assert request.trigger.b_to_a_candidate is True
    assert request.trigger.full_capture_requested is True
    assert {read.source.port for read in request.structured_reads} == {9222, 9333}
    assert {read.read_kind for read in request.structured_reads} == {
        "CURRENT_FORMING_PRICE", "CLOSED_OHLC", "STANDARD_MACD",
        "CLOSED_OHLC_AND_STRUCTURE", "DXY_CONTEXT", "DXY_SUPPLEMENTAL", "RENKO_STATE",
    }
    assert len(request.screenshot_requests) == 5
    assert {shot.source.role for shot in request.screenshot_requests} == {
        "xau_intraday", "xau_30m_15m", "xau_htf", "dxy_15m", "renko",
    }
    assert request.promotion_allowed is False
    assert request.runtime_execution_enabled is False
    assert request.writer_enablement == "DISABLED"
    renko = next(read for read in request.structured_reads if read.read_kind == "RENKO_STATE")
    assert renko.source.layout_id == "YclFo8Ax"
    assert renko.source.timeframes == ("5s",)
    assert renko.source.chart_type == "standard_candles"
    assert renko.timeframes == ("5s",)


def test_main_is_confirmation_and_fire_is_timing_only_never_an_order(sources):
    main = build(sources, "RENKO_MAIN", active=True)
    fire = build(sources, "RENKO_FIRE", active=True)
    assert main.trigger.level is RequestLevel.DIRECTION_CONFIRMATION
    assert main.trigger.direction_confirmation is True
    assert fire.trigger.level is RequestLevel.ENTRY_TIMING_ONLY
    assert fire.trigger.entry_timing_only is True
    for request in (main, fire):
        assert request.trigger.order_permitted is False
        assert request.trigger.provider_call_permitted is False
        assert not request.screenshot_requests


def test_screenshots_are_visual_only_and_cannot_override_or_confirm(sources):
    request = build(sources, "RENKO_E2", active=True)
    for screenshot in request.screenshot_requests:
        assert screenshot.authority == "VISUAL_ONLY"
        assert screenshot.may_override_numeric is False
        assert screenshot.may_upgrade_confirmation is False
    with pytest.raises(EvidenceBundleError, match="visual-only"):
        ScreenshotRequest(
            "unsafe", sources["renko"], "unsafe.png", may_override_numeric=True,
        )


def test_supplemental_dxy_visual_requires_explicit_adapter_opt_in(sources):
    default = build(sources, "RENKO_E2", active=True)
    approved = build(
        sources, "RENKO_E2", active=True,
        screenshot_adapter=ApprovedScreenshotRequestAdapter(
            include_approved_dxy_1m_visual=True,
        ),
    )
    assert all(shot.source.role != "dxy_1m" for shot in default.screenshot_requests)
    dxy = [shot for shot in approved.screenshot_requests if shot.source.role == "dxy_1m"]
    assert len(dxy) == 1
    assert dxy[0].required is False
    assert dxy[0].authority == "VISUAL_ONLY"


def test_primary_and_supplemental_adapters_are_request_only_and_port_pinned(sources):
    assert not hasattr(Port9333RequestAdapter(), "execute")
    assert not hasattr(Port9222RequestAdapter(), "execute")
    assert not hasattr(ApprovedScreenshotRequestAdapter(), "execute")
    wrong = dict(sources)
    wrong["renko"] = SourceIdentity(
        "renko", 9222, "YclFo8Ax", "target-renko", "XAUUSD", "ICMARKETS", ("5s",),
    )
    with pytest.raises(EvidenceBundleError, match="port 9333"):
        build(wrong, "RENKO_E2", active=True)


def test_native_renko_chart_type_is_rejected():
    with pytest.raises(EvidenceBundleError, match="standard-candle"):
        SourceIdentity(
            "renko", 9333, "YclFo8Ax", "target-renko", "XAUUSD", "ICMARKETS",
            ("5s",), chart_type="renko",
        )


def test_injectable_adapters_are_used_without_live_calls(sources):
    calls = []

    class FakeStructured:
        def __init__(self, name):
            self.name = name

        def compile_requests(self, supplied, level):
            calls.append((self.name, tuple(sorted(supplied)), level))
            return ()

    class FakeScreenshots:
        def compile_requests(self, supplied, level):
            calls.append(("visual", tuple(sorted(supplied)), level))
            return ()

    request = build(
        sources, "RENKO_E2", active=True,
        primary_adapter=FakeStructured("primary"),
        supplemental_adapter=FakeStructured("supplemental"),
        screenshot_adapter=FakeScreenshots(),
    )
    assert [item[0] for item in calls] == ["primary", "supplemental", "visual"]
    assert all(item[2] is RequestLevel.FULL_B_TO_A_CAPTURE for item in calls)
    assert request.structured_reads == ()


def test_request_deep_freezes_input_and_pins_canonical_hashes(sources):
    event = {"event": "LIQ_TOUCH", "nested": {"values": [1, 2]}}
    state = {"levels": [{"level_id": "liq1_" + "a" * 64}]}
    request = build_evidence_bundle_request(
        request_id="immutable", requested_at=NOW,
        triggering_events=(event,), event_history=(event,),
        numeric_market_state=state, sources=sources,
    )
    event["nested"]["values"].append(3)
    state["levels"].clear()
    assert request.triggering_events[0]["nested"]["values"] == (1, 2)
    assert len(request.numeric_market_state["levels"]) == 1
    with pytest.raises(TypeError):
        request.numeric_market_state["new"] = True
    with pytest.raises(FrozenInstanceError):
        request.request_id = "changed"
    assert len(request.hashes["bundle_request_sha256"]) == 64
    assert request.hashes["numeric_market_state_sha256"] == canonical_sha256(
        {"levels": [{"level_id": "liq1_" + "a" * 64}]},
    )


def test_direct_model_construction_cannot_enable_provider_order_or_runtime(sources):
    from project_a.evidence_bundle import EVIDENCE_BUNDLE_SCHEMA_V1, EvidenceBundleRequest

    with pytest.raises(EvidenceBundleError, match="providers or place orders"):
        EvidenceBundleRequest(
            schema=EVIDENCE_BUNDLE_SCHEMA_V1,
            request_id="unsafe",
            requested_at="2026-07-20T03:04:05Z",
            trigger=TriggerDecision(
                RequestLevel.TELEMETRY_ONLY, provider_call_permitted=True,
            ),
            triggering_events=({"event": "EXP_UP"},),
            event_history=(),
            numeric_market_state={},
            structured_reads=(),
            screenshot_requests=(),
            source_identities=tuple(sources.values()),
            freshness=(),
            missing_evidence=(),
            unavailable_evidence=(),
            hashes={},
        )


def test_freshness_missing_and_unavailable_evidence_are_auditable(sources):
    request = build(
        sources, "RENKO_E2", active=True,
        freshness=(FreshnessRecord(
            "xau_1m", FreshnessStatus.PROVISIONAL,
            "2026-07-20T03:04:00Z", "2026-07-20T03:04:05Z", False,
        ),),
        missing_evidence=("bid_ask_spread", "bid_ask_spread"),
        unavailable_evidence=(UnavailableEvidence(
            "dxy_1m", "SOURCE_UNAVAILABLE", False,
        ),),
    )
    assert request.freshness[0].confirmed is False
    assert request.freshness[0].status is FreshnessStatus.PROVISIONAL
    assert request.missing_evidence == ("bid_ask_spread",)
    assert request.unavailable_evidence[0].required is False
    assert request.promotion_allowed is False


@pytest.mark.parametrize("unsafe", [float("nan"), float("inf")])
def test_non_finite_evidence_fails_closed(sources, unsafe):
    with pytest.raises(EvidenceBundleError, match="non-finite"):
        build_evidence_bundle_request(
            request_id="unsafe", requested_at=NOW,
            triggering_events=({"event": "EXP_UP", "market_price": unsafe},),
            event_history=(), numeric_market_state={}, sources=sources,
        )


def test_naive_timestamps_and_unapproved_ports_fail_closed(sources):
    with pytest.raises(EvidenceBundleError, match="timezone-aware"):
        build_evidence_bundle_request(
            request_id="naive", requested_at=datetime(2026, 7, 20),
            triggering_events=({"event": "EXP_UP"},), event_history=(),
            numeric_market_state={}, sources=sources,
        )
    with pytest.raises(EvidenceBundleError, match="9222/9333"):
        SourceIdentity("bad", 4999, "layout", "target", "XAUUSD", "ICMARKETS", ("1m",))


def test_default_module_contains_no_network_or_capture_execution_surface():
    import project_a.evidence_bundle as module

    forbidden = {"socket", "requests", "urllib", "playwright", "selenium"}
    assert forbidden.isdisjoint(module.__dict__)
    assert not hasattr(module, "capture")
    assert not hasattr(module, "connect")
    assert not hasattr(module, "send")
