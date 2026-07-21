from __future__ import annotations

import dataclasses

import pytest

from project_a.make_sense import (
    CompileError,
    MakeSenseCompiler,
    MakeSenseInput,
    StoryState,
    disabled_dash_request,
    disabled_final_review_request,
)


T0 = "2026-07-20T01:00:00Z"
T1 = "2026-07-20T01:01:00Z"


def _event(name: str, **changes):
    value = {
        "schema": "project_a.producer_event.v1",
        "event_id": "event-trigger-1",
        "event": name,
        "source_bar_time": T1,
        "confirmed": True,
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
    }
    value.update(changes)
    return value


def _liquidity(**changes):
    value = {
        "level_id": "liq1_" + "a" * 64,
        "level_version": 1,
        "side": "ASK",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "lifecycle": "HIT",
        "confirmed": True,
        "reaction_confirmed": True,
    }
    value.update(changes)
    return value


def _expansion(**changes):
    value = {
        "event_id": "exp-prior-1",
        "event": "EXP_UP",
        "direction": "UP",
        "source_bar_time": T0,
        "confirmed": True,
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
    }
    value.update(changes)
    return value


def _fresh(**changes):
    value = {
        "xau": "FRESH",
        "atr_5m": "FRESH",
        "liquidity": "FRESH",
        "macd_1m": "FRESH",
        "macd_5m": "FRESH",
        "renko": "FRESH",
        "renko_fire": "FRESH",
    }
    value.update(changes)
    return value


def _input(name: str, **changes):
    value = {
        "trigger_event": _event(name),
        "liquidity": _liquidity(),
        "expansion_history": (_expansion(),),
        "macd": {"1m": {"confirmed": True}, "5m": {"confirmed": True}},
        "freshness": _fresh(),
        "evidence_references": ("event-trigger-1", "exp-prior-1"),
    }
    value.update(changes)
    return MakeSenseInput(**value)


def test_expansion_alone_is_telemetry_only_and_never_assigns_trade_direction():
    result = MakeSenseCompiler().compile(
        MakeSenseInput(trigger_event=_event("EXP_UP"), freshness=_fresh())
    )
    assert result.state is StoryState.NO_STORY
    assert result.research_started is False
    assert result.numeric_snapshot_requested is False
    assert result.full_capture_requested is False
    assert result.final_trade_direction is None
    assert result.order_placed is False
    assert result.reasons == ("COMPATIBILITY_EVIDENCE_ONLY",)


def test_liq_touch_begins_research_retrieves_prior_relevant_expansion_and_requests_snapshot():
    history = (
        _expansion(event_id="future", source_bar_time="2026-07-20T01:02:00Z"),
        _expansion(event_id="wrong", direction="DOWN"),
        _expansion(event_id="selected"),
    )
    result = MakeSenseCompiler().compile(_input("LIQ_TOUCH", expansion_history=history))
    assert result.state is StoryState.B_BUILDING
    assert result.research_started is True
    assert result.numeric_snapshot_requested is True
    assert result.full_capture_requested is False
    assert result.selected_expansion_event_id == "selected"
    assert result.hypotheses == ("POSSIBLE_BEARISH_REVERSAL",)
    assert result.final_trade_direction is None


def test_liq_touch_records_missing_expansion_without_guessing():
    result = MakeSenseCompiler().compile(_input("LIQ_TOUCH", expansion_history=()))
    assert result.state is StoryState.C_INSUFFICIENT
    assert result.research_started is True
    assert "prior_confirmed_expansion_toward_level" in result.missing_evidence


def test_down_expansion_toward_bid_is_only_a_bullish_reversal_hypothesis():
    result = MakeSenseCompiler().compile(
        _input(
            "LIQ_TOUCH",
            liquidity=_liquidity(side="BID"),
            expansion_history=(_expansion(event="EXP_DOWN", direction="DOWN"),),
        )
    )
    assert result.hypotheses == ("POSSIBLE_BULLISH_REVERSAL",)
    assert result.final_trade_direction is None


def test_e1_is_compatibility_evidence_only():
    result = MakeSenseCompiler().compile(_input("RENKO_E1"))
    assert result.state is StoryState.NO_STORY
    assert result.prewarm_requested is False
    assert result.full_capture_requested is False
    assert result.reasons == ("COMPATIBILITY_EVIDENCE_ONLY",)


def test_e2_cannot_request_full_capture_or_promote_even_with_context():
    passing = MakeSenseCompiler().compile(_input("RENKO_E2"))
    assert passing.state is StoryState.NO_STORY
    assert passing.full_capture_requested is False

    failing = MakeSenseCompiler().compile(_input("RENKO_E2", macd={}))
    assert failing.state is StoryState.NO_STORY
    assert failing.full_capture_requested is False


def test_main_remains_compatibility_evidence_and_never_orders():
    result = MakeSenseCompiler().compile(_input("RENKO_MAIN"))
    assert result.state is StoryState.NO_STORY
    assert result.full_capture_requested is False
    assert result.provider_dispatch_enabled is False
    assert result.order_placed is False
    assert result.final_trade_direction is None


def test_fire_cannot_wake_or_act_with_or_without_prior_state():
    result = MakeSenseCompiler().compile(_input("RENKO_FIRE"))
    assert result.state is StoryState.NO_STORY
    assert result.order_placed is False

    valid = MakeSenseCompiler().compile(
        _input("RENKO_FIRE", prior_state=StoryState.WAITING_5S_ENTRY.value)
    )
    assert valid.state is StoryState.NO_STORY
    assert valid.order_placed is False


@pytest.mark.parametrize("status", ["STALE", "MISSING", "CLOCK_INVALID", "SOURCE_UNAVAILABLE", "MARKET_CLOSED"])
def test_hard_freshness_failures_expire_active_story(status):
    result = MakeSenseCompiler().compile(
        _input("REVIEW_STATE", prior_state=StoryState.B_BUILDING.value, freshness=_fresh(xau=status))
    )
    assert result.state is StoryState.EXPIRED
    assert result.full_capture_requested is False


def test_terminal_level_fails_closed_as_invalidated():
    result = MakeSenseCompiler().compile(
        _input("LIQ_TOUCH", liquidity=_liquidity(lifecycle="BREAK"))
    )
    assert result.state is StoryState.INVALIDATED


def test_approved_review_records_review_state_without_waiting_for_fire():
    result = MakeSenseCompiler().compile(
        _input("REVIEW_STATE", final_review={"verdict": "APPROVE", "grade": "A"})
    )
    assert result.state is StoryState.A_REVIEW_REQUIRED
    assert result.order_placed is False


def test_provider_neutral_boundaries_are_immutable_disabled_and_deterministic():
    result = MakeSenseCompiler().compile(_input("LIQ_TOUCH"))
    same = MakeSenseCompiler().compile(_input("LIQ_TOUCH"))
    assert result.sha256 == same.sha256
    dash = disabled_dash_request(result)
    final = disabled_final_review_request(result, evidence_bundle_sha256="B" * 64)
    assert dash.dispatch_enabled is dash.network_enabled is False
    assert final.dispatch_enabled is final.network_enabled is False
    assert final.evidence_bundle_sha256 == "b" * 64
    assert "provider" not in dash.document()
    with pytest.raises(TypeError):
        dash.body["state"] = "A_CONFIRMED"
    with pytest.raises(dataclasses.FrozenInstanceError):
        dash.dispatch_enabled = True


def test_invalid_timestamp_and_bundle_hash_fail_closed():
    with pytest.raises(CompileError, match="timezone"):
        MakeSenseCompiler().compile(_input("LIQ_TOUCH", trigger_event=_event("LIQ_TOUCH", source_bar_time="2026-07-20T01:00:00")))
    result = MakeSenseCompiler().compile(_input("LIQ_TOUCH"))
    with pytest.raises(CompileError, match="64 hexadecimal"):
        disabled_final_review_request(result, evidence_bundle_sha256="bad")


def test_input_and_output_facts_are_immutable_copies():
    liquidity = _liquidity()
    source = _input("LIQ_TOUCH", liquidity=liquidity)
    liquidity["side"] = "BID"
    result = MakeSenseCompiler().compile(source)
    assert result.facts["liquidity"]["side"] == "ASK"
    with pytest.raises(TypeError):
        result.facts["liquidity"]["side"] = "BID"
