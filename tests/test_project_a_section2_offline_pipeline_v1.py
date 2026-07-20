from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from project_a.evidence_bundle import RequestLevel, SourceIdentity
from project_a.make_sense import StoryState
from project_a.numeric_state import (
    EXPANSION_EVENT_SCHEMA,
    LIQUIDITY_EVENT_SCHEMA,
    RENKO_EVENT_SCHEMA,
    parse_numeric_event,
)
from project_a.section2_pipeline import OfflineSection2Pipeline, Section2PipelineError


def _sources():
    def item(role, port, layout, frames, symbol="XAUUSD", feed="ICMARKETS"):
        return SourceIdentity(role, port, layout, f"target-{role}", symbol, feed, frames)

    return {
        "xau_intraday": item("xau_intraday", 9333, "cpPWuLlN", ("1m", "5m")),
        "xau_30m_15m": item("xau_30m_15m", 9333, "avpCVaw2", ("15m", "30m")),
        "xau_htf": item("xau_htf", 9333, "pNqcbOmu", ("4H", "D", "W")),
        "dxy_15m": item("dxy_15m", 9333, "n9qjfufV", ("15m",), "DXY", "TVC"),
        "dxy_1m": item("dxy_1m", 9222, "ocVwlz2C", ("1m",), "DXY", "TVC"),
        "renko": item("renko", 9222, "paH6jur7", ("RENKO",)),
    }


def _exp():
    return {
        "schema": EXPANSION_EVENT_SCHEMA,
        "producer_id": "EXP_V3_SCANNER",
        "producer_revision": "5+6",
        "event_id": "exp-1",
        "event": "EXP_UP",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "timeframe": "1m",
        "source_bar_time": "2026-07-20T01:01:00Z",
        "confirmed": True,
        "freshness_status": "FRESH",
        "direction": "UP",
        "start_price": "3398.00",
        "market_price": "3400.00",
        "displacement": "2.00",
        "atr": "4.00",
        "atr_multiple": "0.50",
        "path_efficiency": "0.80",
        "body_quality": "0.75",
        "opposing_bars": 1,
        "age_bars": 2,
        "quality": "CLEAN",
        "too_extended": False,
    }


def _liq(event="LIQ_TOUCH", event_id="liq-touch-1", lifecycle="HIT"):
    return {
        "schema": LIQUIDITY_EVENT_SCHEMA,
        "producer_id": "LIQ_V2",
        "producer_revision": "9",
        "event_id": event_id,
        "event": event,
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "anchor_timeframe": "5m",
        "source_bar_time": "2026-07-20T01:02:00Z",
        "confirmed": True,
        "freshness_status": "FRESH",
        "side": "ASK",
        "source_creation_identity": "pivot-20260720-001",
        "created_at_source": "2026-07-20T00:30:00Z",
        "level_version": "1",
        "level_price": "3401.00",
        "market_price": "3400.50",
        "tick_size": "0.01",
        "grade": "PRIME",
        "lifecycle": lifecycle,
        "mtf_confluence": 4,
        "touch_count": 1,
        "level_freshness_status": "FRESH",
        "market_price_freshness_status": "FRESH",
        "confirmed_5m_atr14": "4.00",
        "atr_confirmed": True,
        "atr_freshness_status": "FRESH",
    }


def _renko(stage, event_id=None, at="2026-07-20T01:03:00Z"):
    return {
        "schema": RENKO_EVENT_SCHEMA,
        "producer_id": "RENKO_V3_SNIPER",
        "producer_revision": "1",
        "event_id": event_id or f"renko-{stage.lower()}-1",
        "event": f"RENKO_{stage}",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "timeframe": "5s",
        "source_bar_time": at,
        "confirmed": True,
        "freshness_status": "FRESH",
        "stage": stage,
        "direction": "DOWN",
        "signal_price": "3400.25",
        "cycle_id": "cycle-1",
        "event_sequence": {"E1": 1, "E2": 2, "MAIN": 3, "FIRE": 4}[stage],
        "e1_age_bars": 1,
        "e2_age_bars": 0,
        "main_age_bars": 0,
        **(
            {"score": 88, "power": "STRONG", "mode": "RUNNER", "transfer": "15s PUSH", "fire_reason_components": ["score", "power"]}
            if stage == "FIRE" else {}
        ),
    }


def _fresh():
    return {
        "xau": "FRESH",
        "atr_5m": "FRESH",
        "liquidity": "FRESH",
        "macd_1m": "FRESH",
        "macd_5m": "FRESH",
        "renko": "FRESH",
        "renko_fire": "FRESH",
    }


def _compile(events, trigger, **changes):
    values = {
        "producer_events": events,
        "trigger_event_id": trigger,
        "requested_at": datetime(2026, 7, 20, 1, 4, tzinfo=timezone.utc),
        "macd": {"1m": {"confirmed": True}, "5m": {"confirmed": True}},
        "dxy": {"15m": {"confirmed": True}},
        "htf_context": {"4H": {"confirmed": True}},
        "freshness": _fresh(),
    }
    values.update(changes)
    return OfflineSection2Pipeline(_sources()).compile(**values)


def test_e2_composes_the_complete_offline_request_chain():
    result = _compile((_exp(), _liq(), _renko("E2")), "renko-e2-1")
    assert result.make_sense_request.state is StoryState.B_TO_A_CANDIDATE
    assert result.make_sense_request.full_capture_requested is True
    assert result.make_sense_request.final_trade_direction is None
    assert result.evidence_bundle_request.trigger.level is RequestLevel.FULL_B_TO_A_CAPTURE
    assert {request.source.layout_id for request in result.evidence_bundle_request.structured_reads} >= {
        "cpPWuLlN", "avpCVaw2", "pNqcbOmu", "n9qjfufV", "ocVwlz2C", "paH6jur7",
    }
    assert len(result.evidence_bundle_request.screenshot_requests) == 5
    assert result.final_review_request is not None
    assert result.final_review_request.dispatch_enabled is False
    assert result.final_review_request.network_enabled is False
    assert result.dash_request.dispatch_enabled is False
    assert result.order_placed is False
    assert result.numeric_state.snapshot()["trade_direction"] is None


def test_liq_touch_stops_at_numeric_research_request():
    result = _compile((_exp(), _liq()), "liq-touch-1")
    assert result.make_sense_request.state is StoryState.B_BUILDING
    assert result.make_sense_request.research_started is True
    assert result.make_sense_request.numeric_snapshot_requested is True
    assert result.evidence_bundle_request.trigger.level is RequestLevel.NUMERIC_RESEARCH
    assert result.evidence_bundle_request.screenshot_requests == ()
    assert result.final_review_request is None


def test_e1_is_prewarm_and_expansion_alone_is_telemetry():
    e1 = _compile((_exp(), _liq(), _renko("E1")), "renko-e1-1")
    assert e1.make_sense_request.state is StoryState.B_BUILDING
    assert e1.evidence_bundle_request.trigger.level is RequestLevel.PREWARM_ONLY
    assert e1.final_review_request is None

    exp = _compile((_exp(),), "exp-1")
    assert exp.make_sense_request.state is StoryState.NO_STORY
    assert exp.evidence_bundle_request.trigger.level is RequestLevel.TELEMETRY_ONLY
    assert exp.make_sense_request.final_trade_direction is None


def test_stale_or_market_closed_evidence_fails_closed_without_capture():
    stale = _fresh()
    stale["xau"] = "MARKET_CLOSED"
    result = _compile(
        (_exp(), _liq(), _renko("E2")), "renko-e2-1",
        prior_state=StoryState.B_BUILDING.value,
        freshness=stale,
    )
    assert result.make_sense_request.state is StoryState.EXPIRED
    assert result.make_sense_request.full_capture_requested is False
    assert result.evidence_bundle_request.trigger.level is RequestLevel.PREWARM_ONLY
    assert result.evidence_bundle_request.promotion_allowed is False
    assert result.final_review_request is None


def test_missing_trigger_or_naive_time_fails_closed():
    with pytest.raises(Section2PipelineError, match="not present"):
        _compile((_exp(),), "missing")
    with pytest.raises(Section2PipelineError, match="timezone-aware"):
        _compile((_exp(),), "exp-1", requested_at=datetime(2026, 7, 20, 1, 4))


def test_pipeline_models_expose_no_execution_methods():
    result = _compile((_exp(), _liq(), _renko("E2")), "renko-e2-1")
    for value in (
        result,
        result.make_sense_request,
        result.evidence_bundle_request,
        result.dash_request,
        result.final_review_request,
    ):
        assert not hasattr(value, "execute")
        assert not hasattr(value, "send")
        assert not hasattr(value, "connect")


def test_versioned_producer_contract_fixture_parses_without_ambiguous_price():
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "project_a" / "section2_producer_events_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["fixture_schema"] == "project_a.section2_producer_fixture/1.0"
    parsed = [parse_numeric_event(event) for event in fixture["events"]]
    assert [event.event for event in parsed] == [
        "EXP_UP", "EXP_QUALITY_UPDATE", "LIQ_TOUCH", "RENKO_E1", "RENKO_E2", "RENKO_MAIN", "RENKO_FIRE",
    ]
    assert [event["producer_id"] for event in fixture["events"][:2]] == ["EXP_V3", "EXP_SCANNER"]
    assert fixture["events"][0]["body_quality"] is None
    assert fixture["events"][1]["path_efficiency"] is None
    assert parsed[2].data["level_id"] == fixture["expected_liquidity_level_id"]
    assert all("price" not in event for event in fixture["events"])
    assert all("trade_direction" not in event for event in fixture["events"])
