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
    SOURCE_AUTHORITY,
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
        return SourceIdentity(
            role, port, layout, target, symbol, feed, timeframes,
            chart_types=SOURCE_AUTHORITY[role][5],
        )

    return {
        "xau_intraday": source("xau_intraday", 9333, "cpPWuLlN", "target-xau-intraday", "XAUUSD", "ICMARKETS", ("1m", "5m")),
        "xau_30m_15m": source("xau_30m_15m", 9333, "avpCVaw2", "target-xau-30m-15m", "XAUUSD", "ICMARKETS", ("15m", "30m")),
        "xau_htf": source("xau_htf", 9333, "pNqcbOmu", "target-xau-htf", "XAUUSD", "ICMARKETS", ("4H", "D", "W")),
        "dxy_15m": source("dxy_15m", 9333, "n9qjfufV", "target-dxy-15m", "DXY", "TVC", ("15m",)),
        "dxy_1m": source("dxy_1m", 9222, "ocVwlz2C", "target-dxy-1m", "DXY", "TVC", ("1m",)),
        "renko": source("renko", 9333, "YclFo8Ax", "target-renko", "XAUUSD", "ICMARKETS", ("5s",)),
    }


def build(sources, event="EXP_UP", active=False, trigger_changes=None, **kwargs):
    trigger = {
        "event": event,
        "event_id": "event-001",
        "source_bar_time": "2026-07-20T03:04:00Z",
        "confirmed": True,
    }
    if event == "LIQ_TOUCH":
        trigger.update(
            producer_id="LIQ_V2",
            producer_revision="9",
            symbol="XAUUSD",
            feed="ICMARKETS",
            anchor_timeframe="5m",
            freshness_status="FRESH",
            level_freshness_status="FRESH",
            market_price_freshness_status="FRESH",
            atr_freshness_status="FRESH",
            atr_confirmed=True,
            touch_count=1,
        )
    if trigger_changes:
        trigger.update(trigger_changes)
    return build_evidence_bundle_request(
        request_id="evidence_request_001",
        requested_at=NOW,
        triggering_events=(trigger,),
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


def test_liq_touch_starts_research_and_compiles_complete_capture(sources):
    request = build(sources, "LIQ_TOUCH")
    assert request.trigger.level is RequestLevel.LIQ_RESEARCH_CAPTURE
    assert request.trigger.research_started is True
    assert request.trigger.full_capture_requested is True
    assert {item.read_kind for item in request.structured_reads} == {
        "CURRENT_FORMING_PRICE", "CLOSED_OHLC", "STANDARD_MACD",
        "EXPANSION_CONTEXT", "SNR_HPA_CONTEXT",
        "DXY_CONTEXT", "DXY_SUPPLEMENTAL", "RENKO_STATE", "SHORT_TERM_PRICE_ACTION",
    }
    assert len(request.screenshot_requests) == 5
    macd = [item for item in request.structured_reads if item.read_kind == "STANDARD_MACD"]
    assert len(macd) == 2
    assert all(item.indicator_parameters == (12, 26, 9) for item in macd)
    assert all(item.closed_bars_only is True for item in macd)


@pytest.mark.parametrize(
    "change",
    [
        {"producer_id": "EXP_V3"},
        {"producer_revision": "8"},
        {"symbol": "EURUSD"},
        {"feed": "OANDA"},
        {"anchor_timeframe": "1m"},
        {"confirmed": False},
        {"touch_count": 0},
        {"freshness_status": "STALE"},
        {"source_bar_time": "2026-07-20T02:00:00Z"},
        {"source_bar_time": "2026-07-20T03:05:00Z"},
    ],
)
def test_invalid_liq_trigger_cannot_compile_capture_or_grading_preparation(sources, change):
    request = build(sources, "LIQ_TOUCH", trigger_changes=change)
    assert request.trigger.level is RequestLevel.TELEMETRY_ONLY
    assert request.trigger.research_started is False
    assert request.trigger.full_capture_requested is False
    assert request.structured_reads == ()
    assert request.screenshot_requests == ()


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
        ("CLOSED_OHLC", ("5m",)): ("xau_intraday", "cpPWuLlN"),
        ("STANDARD_MACD", ("5m",)): ("xau_intraday", "cpPWuLlN"),
        ("CLOSED_OHLC", ("15m", "30m")): ("xau_30m_15m", "avpCVaw2"),
        ("STANDARD_MACD", ("15m", "30m")): ("xau_30m_15m", "avpCVaw2"),
    }


def test_volume_panes_are_visual_context_only(sources):
    request = build(sources, "LIQ_TOUCH")
    for item in request.structured_reads:
        chart_types = dict(zip(item.source.timeframes, item.source.chart_types))
        assert all(chart_types[timeframe] == "standard_candles" for timeframe in item.timeframes)
    visual_roles = {item.source.role for item in request.screenshot_requests}
    assert {"xau_intraday", "xau_htf"} <= visual_roles
    assert sources["xau_intraday"].chart_types == ("volume_candles", "standard_candles")
    assert sources["xau_htf"].chart_types == (
        "volume_candles", "volume_candles", "volume_candles",
    )


@pytest.mark.parametrize("event", ["EXP_UP", "RENKO_E1", "RENKO_E2", "RENKO_MAIN", "RENKO_FIRE"])
def test_compatibility_events_are_telemetry_only(sources, event):
    request = build(sources, event)
    assert request.trigger.level is RequestLevel.TELEMETRY_ONLY
    assert request.trigger.research_started is False
    assert request.trigger.full_capture_requested is False
    assert not request.structured_reads
    assert not request.screenshot_requests


def test_e2_with_active_story_cannot_request_or_promote(sources):
    request = build(sources, "RENKO_E2", active=True)
    assert request.trigger.level is RequestLevel.TELEMETRY_ONLY
    assert request.structured_reads == ()
    assert request.screenshot_requests == ()
    assert request.promotion_allowed is False
    assert request.runtime_execution_enabled is False
    assert request.writer_enablement == "DISABLED"


def test_main_and_fire_are_context_only_never_an_order(sources):
    main = build(sources, "RENKO_MAIN", active=True)
    fire = build(sources, "RENKO_FIRE", active=True)
    assert main.trigger.level is RequestLevel.TELEMETRY_ONLY
    assert fire.trigger.level is RequestLevel.TELEMETRY_ONLY
    for request in (main, fire):
        assert request.trigger.order_permitted is False
        assert request.trigger.provider_call_permitted is False
        assert not request.screenshot_requests


def test_screenshots_are_visual_only_and_cannot_override_or_confirm(sources):
    request = build(sources, "LIQ_TOUCH")
    for screenshot in request.screenshot_requests:
        assert screenshot.authority == "VISUAL_ONLY"
        assert screenshot.may_override_numeric is False
        assert screenshot.may_upgrade_confirmation is False
    with pytest.raises(EvidenceBundleError, match="visual-only"):
        ScreenshotRequest(
            "unsafe", sources["renko"], "unsafe.png", may_override_numeric=True,
        )


def test_supplemental_dxy_visual_requires_explicit_adapter_opt_in(sources):
    default = build(sources, "LIQ_TOUCH")
    approved = build(
        sources, "LIQ_TOUCH",
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
    with pytest.raises(EvidenceBundleError, match="approved port/layout"):
        build(wrong, "LIQ_TOUCH")


def test_unapproved_chart_type_is_rejected():
    with pytest.raises(EvidenceBundleError, match="approved candle allowlist"):
        SourceIdentity(
            "renko", 9333, "YclFo8Ax", "target-renko", "XAUUSD", "ICMARKETS",
            ("5s",), chart_types=("renko",),
        )


@pytest.mark.parametrize(
    "replacement",
    [
        SourceIdentity("xau_intraday", 9333, "wrong", "target", "XAUUSD", "ICMARKETS", ("1m", "5m")),
        SourceIdentity("xau_intraday", 9333, "cpPWuLlN", "target", "EURUSD", "ICMARKETS", ("1m", "5m")),
        SourceIdentity("xau_intraday", 9333, "cpPWuLlN", "target", "XAUUSD", "OANDA", ("1m", "5m")),
        SourceIdentity("xau_intraday", 9333, "cpPWuLlN", "target", "XAUUSD", "ICMARKETS", ("1m",)),
    ],
)
def test_wrong_primary_source_identity_fails_closed(sources, replacement):
    wrong = dict(sources)
    wrong["xau_intraday"] = replacement
    with pytest.raises(EvidenceBundleError, match="approved port/layout"):
        build(wrong, "LIQ_TOUCH")


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
        sources, "LIQ_TOUCH",
        primary_adapter=FakeStructured("primary"),
        supplemental_adapter=FakeStructured("supplemental"),
        screenshot_adapter=FakeScreenshots(),
    )
    assert [item[0] for item in calls] == ["primary", "supplemental", "visual"]
    assert all(item[2] is RequestLevel.LIQ_RESEARCH_CAPTURE for item in calls)
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
        sources, "LIQ_TOUCH",
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
