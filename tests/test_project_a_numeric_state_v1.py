"""Offline contract tests for Project A Numeric Market State V1."""
from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from project_a.numeric_state import (
    EXPANSION_EVENT_SCHEMA,
    LIQUIDITY_EVENT_SCHEMA,
    RENKO_EVENT_SCHEMA,
    NumericMarketState,
    NumericStateError,
    canonical_json_bytes,
    liquidity_distance,
    liquidity_identity_preimage,
    liquidity_level_id,
    parse_numeric_event,
)


def _exp(
    *,
    event_id: str = "exp-1",
    event: str = "EXP_UP",
    direction: str = "UP",
    at: str = "2026-07-20T01:01:00Z",
    market_price: str = "3400.00",
    confirmed: bool = True,
    freshness: str = "FRESH",
) -> dict:
    return {
        "schema": EXPANSION_EVENT_SCHEMA,
        "producer_id": "EXP_V3",
        "producer_revision": "5",
        "event_id": event_id,
        "event": event,
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "timeframe": "1m",
        "source_bar_time": at,
        "confirmed": confirmed,
        "freshness_status": freshness,
        "direction": direction,
        "start_price": "3398.00",
        "market_price": market_price,
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


def _liq(
    *,
    event_id: str = "liq-1",
    event: str = "LIQ_APPROACH",
    side: str = "ASK",
    at: str = "2026-07-20T01:02:00Z",
    created: str = "2026-07-20T00:30:00Z",
    creation_id: str = "pivot-1",
    level_price: str = "3401.00",
    market_price: str = "3400.00",
    atr: str | None = "4.00",
    grade: str = "VALID",
    confluence: int = 2,
    touches: int = 1,
    confirmed: bool = True,
    freshness: str = "FRESH",
    lifecycle: str = "APPROACH",
    level_version: str = "1",
) -> dict:
    payload = {
        "schema": LIQUIDITY_EVENT_SCHEMA,
        "producer_id": "LIQ_V2",
        "producer_revision": "9",
        "event_id": event_id,
        "event": event,
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "anchor_timeframe": "5m",
        "source_bar_time": at,
        "confirmed": confirmed,
        "freshness_status": freshness,
        "side": side,
        "source_creation_identity": creation_id,
        "created_at_source": created,
        "level_version": level_version,
        "level_price": level_price,
        "market_price": market_price,
        "tick_size": "0.01",
        "grade": grade,
        "lifecycle": lifecycle,
        "mtf_confluence": confluence,
        "touch_count": touches,
        "level_freshness_status": freshness,
        "market_price_freshness_status": freshness,
    }
    if atr is not None:
        payload.update(
            {
                "confirmed_5m_atr14": atr,
                "atr_confirmed": confirmed,
                "atr_freshness_status": freshness,
            }
        )
    return payload


def _renko(
    stage: str,
    *,
    event_id: str | None = None,
    at: str = "2026-07-20T01:03:00Z",
    cycle: str | None = "cycle-1",
    confirmed: bool = True,
    freshness: str = "FRESH",
) -> dict:
    event = f"RENKO_{stage}" if stage not in {"RESET", "INVALIDATED"} else f"RENKO_{stage}"
    rendered_stage = "NONE" if stage in {"RESET", "INVALIDATED"} else stage
    payload = {
        "schema": RENKO_EVENT_SCHEMA,
        "producer_id": "RENKO_V3_SNIPER",
        "producer_revision": "1",
        "event_id": event_id or f"renko-{stage.lower()}",
        "event": event,
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "timeframe": "5s",
        "source_bar_time": at,
        "confirmed": confirmed,
        "freshness_status": freshness,
        "stage": rendered_stage,
        "direction": "NONE" if rendered_stage == "NONE" else "DOWN",
        "signal_price": None if rendered_stage == "NONE" else "3400.25",
        "cycle_id": cycle,
        "event_sequence": {"E1": 1, "E2": 2, "MAIN": 3, "FIRE": 4, "RESET": 5, "INVALIDATED": 5}[stage],
        "e1_age_bars": 1,
        "e2_age_bars": 0,
        "main_age_bars": 0,
    }
    if stage == "FIRE":
        payload.update(
            {
                "score": 88,
                "power": "STRONG",
                "mode": "RUNNER",
                "transfer": "15s PUSH",
                "fire_reason_components": ["score", "power", "transfer"],
            }
        )
    return payload


def test_normative_liquidity_level_id_vector_pins_bytes_and_hash():
    components = {
        "producer_id": "LIQ_V2",
        "producer_revision": "9",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "anchor_timeframe": "5m",
        "side": "ASK",
        "source_creation_identity": {
            "source_pivot_time": "2026-07-20T01:02:03Z",
            "source_sequence": 17,
        },
        "level_price": "3401.25",
        "tick_size": "0.01",
    }
    expected_bytes = (
        b'{"anchor_timeframe":"5m","feed":"ICMARKETS","level_price_ticks":340125,'
        b'"producer_id":"LIQ_V2","producer_revision":"9","schema":'
        b'"project_a.liquidity_level_identity/1.0","side":"ASK",'
        b'"source_creation_identity":{"source_pivot_time":"2026-07-20T01:02:03Z",'
        b'"source_sequence":17},"symbol":"XAUUSD","tick_size":"0.01"}'
    )
    assert canonical_json_bytes(liquidity_identity_preimage(**components)) == expected_bytes
    assert liquidity_level_id(**components) == "liq1_0422cb47086147bd4f921f4e897b03883c2a55009e50f1c57d800558ad999d1b"


def test_level_id_normalizes_decimal_scale_but_not_source_identity():
    base = {
        "producer_id": "LIQ_V2",
        "producer_revision": "9",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "anchor_timeframe": "5",
        "side": "bid",
        "source_creation_identity": "pivot-a",
        "level_price": Decimal("3399.500"),
        "tick_size": Decimal("0.010"),
    }
    assert liquidity_level_id(**base) == liquidity_level_id(**{**base, "level_price": "3399.50", "tick_size": "0.01"})
    assert liquidity_level_id(**base) != liquidity_level_id(**{**base, "source_creation_identity": "pivot-b"})


def test_level_id_is_independent_of_ambient_decimal_precision():
    values = {
        "producer_id": "LIQ_V2",
        "producer_revision": "9",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "anchor_timeframe": "5m",
        "side": "ASK",
        "source_creation_identity": "pivot-large",
        "level_price": "12345678901234567890.12345",
        "tick_size": "0.00001",
    }
    expected = liquidity_level_id(**values)
    with localcontext() as context:
        context.prec = 4
        assert liquidity_level_id(**values) == expected


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"level_price": 3401.25}, "BINARY_FLOAT_FORBIDDEN"),
        ({"level_price": "3401.255"}, "PRICE_NOT_ON_TICK_GRID"),
        ({"tick_size": "0"}, "NUMBER_OUT_OF_RANGE"),
        ({"source_creation_identity": ""}, "MISSING_IDENTITY"),
        ({"level_price": "NaN"}, "NON_FINITE_NUMBER"),
    ],
)
def test_negative_level_id_vectors_fail_closed(change, code):
    values = {
        "producer_id": "LIQ_V2",
        "producer_revision": "9",
        "symbol": "XAUUSD",
        "feed": "ICMARKETS",
        "anchor_timeframe": "5m",
        "side": "ASK",
        "source_creation_identity": "pivot-a",
        "level_price": "3401.25",
        "tick_size": "0.01",
    }
    with pytest.raises(NumericStateError) as error:
        liquidity_level_id(**{**values, **change})
    assert error.value.code == code


def test_liquidity_event_parses_canonical_identity_and_preserves_raw_immutably():
    payload = _liq()
    source = json.dumps(payload, indent=2).encode()
    event = parse_numeric_event(source)
    assert event.family == "LIQUIDITY"
    assert event.event == "LIQ_APPROACH"
    assert event.data["level_id"].startswith("liq1_") and len(event.data["level_id"]) == 69
    assert event.data["level_price"] == Decimal("3401")
    assert event.raw_payload == source
    with pytest.raises(TypeError):
        event.data["level_price"] = Decimal("1")


def test_mapping_mutation_after_parse_cannot_change_event_or_raw_payload():
    payload = _exp()
    event = parse_numeric_event(payload)
    raw_before = event.raw_payload
    payload["market_price"] = "1"
    assert event.data["market_price"] == Decimal("3400")
    assert event.raw_payload == raw_before


@pytest.mark.parametrize(
    ("factory", "family", "event"),
    [
        (_exp, "EXPANSION", "EXP_UP"),
        (lambda: _renko("E1"), "RENKO", "RENKO_E1"),
        (lambda: _renko("E2"), "RENKO", "RENKO_E2"),
        (lambda: _renko("MAIN"), "RENKO", "RENKO_MAIN"),
        (lambda: _renko("FIRE"), "RENKO", "RENKO_FIRE"),
    ],
)
def test_versioned_expansion_and_renko_events_parse(factory, family, event):
    parsed = parse_numeric_event(factory())
    assert (parsed.family, parsed.event) == (family, event)
    assert parsed.confirmed is True and parsed.freshness_status == "FRESH"


def test_exact_pine_epoch_milliseconds_and_source_specific_expansion_nulls_parse():
    v3 = _exp()
    v3.update(
        source_bar_time=1752973260000,
        emitted_at=1752973260123,
        producer_id="EXP_V3",
        body_quality=None,
        opposing_bars=None,
        quality=None,
        too_extended=None,
    )
    scanner = _exp(event_id="scanner-quality", event="EXP_QUALITY_UPDATE")
    scanner.update(
        source_bar_time=1752973260000,
        emitted_at=1752973260123,
        producer_id="EXP_SCANNER",
        producer_revision="6",
        path_efficiency=None,
    )
    parsed_v3 = parse_numeric_event(v3)
    parsed_scanner = parse_numeric_event(scanner)
    assert parsed_v3.source_bar_time.isoformat() == "2025-07-20T01:01:00+00:00"
    assert parsed_v3.data["body_quality"] is None
    assert parsed_scanner.data["path_efficiency"] is None


def test_exact_pine_renko_numeric_power_cycle_alias_and_reset_semantics_parse():
    fire = _renko("FIRE")
    fire.pop("cycle_id")
    fire.update(cycle_identity="RENKO|XAUUSD|5S|DOWN|1752973260000", power=Decimal("0.875"))
    parsed_fire = parse_numeric_event(fire)
    assert parsed_fire.data["cycle_id"] == fire["cycle_identity"]
    assert parsed_fire.data["power"] == Decimal("0.875")

    reset = _renko("RESET")
    reset.update(stage="RESET", direction="DOWN", signal_price="3400.25")
    parsed_reset = parse_numeric_event(reset)
    assert parsed_reset.data["stage"] == "RESET"
    assert parsed_reset.data["direction"] == "DOWN"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda item: item.pop("event_id"), "MISSING_REQUIRED_FIELD"),
        (lambda item: item.pop("source_bar_time"), "MISSING_REQUIRED_FIELD"),
        (lambda item: item.pop("producer_id"), "MISSING_REQUIRED_FIELD"),
        (lambda item: item.update(market_price=None), "MISSING_REQUIRED_FIELD"),
        (lambda item: item.update(direction="LONG"), "INVALID_MOVEMENT_DIRECTION"),
        (lambda item: item.update(price="3400"), "AMBIGUOUS_OR_ACTION_FIELD"),
        (lambda item: item.update(schema="project_a.expansion_event"), "UNSUPPORTED_SCHEMA"),
    ],
)
def test_missing_ambiguous_or_trade_semantics_fail_closed(mutation, code):
    payload = _exp()
    mutation(payload)
    with pytest.raises(NumericStateError) as error:
        parse_numeric_event(payload)
    assert error.value.code == code


def test_liquidity_supplied_id_must_match_python_identity():
    with pytest.raises(NumericStateError) as error:
        parse_numeric_event({**_liq(), "level_id": "liq1_" + "0" * 64})
    assert error.value.code == "LEVEL_ID_MISMATCH"


@pytest.mark.parametrize(
    ("side", "level", "market", "atr", "zone", "status", "ratio"),
    [
        ("ASK", "3402", "3400", "4", "APPROACH", "AVAILABLE", "0.5"),
        ("ASK", "3401", "3400", "4", "NEAR_TOUCH", "AVAILABLE", "0.25"),
        ("ASK", "3402.01", "3400", "4", "FAR", "AVAILABLE", "0.5025"),
        ("BID", "3399", "3400", "4", "NEAR_TOUCH", "AVAILABLE", "0.25"),
        ("ASK", "3400", "3400", "4", None, "HIT_INTERSECTION_EVALUATION_REQUIRED", "0"),
        ("ASK", "3399", "3400", "4", None, "CROSSED_PENDING_CLASSIFICATION", "0.25"),
    ],
)
def test_liquidity_distance_exact_side_and_zone_boundaries(side, level, market, atr, zone, status, ratio):
    result = liquidity_distance(
        side=side,
        level_price=Decimal(level),
        market_price=Decimal(market),
        confirmed_5m_atr14=Decimal(atr),
        inputs_fresh=True,
    )
    assert (result.distance_zone, result.status, result.distance_atr) == (zone, status, Decimal(ratio))


def test_missing_or_stale_atr_records_unavailable_without_guessing():
    missing = NumericMarketState([_liq(atr=None)])
    stale = NumericMarketState([_liq(freshness="STALE")])
    assert next(iter(missing.liquidity_levels.values())).distance.status == "UNAVAILABLE"
    assert next(iter(stale.liquidity_levels.values())).distance.status == "UNAVAILABLE"
    assert missing.tracked_level is None and stale.tracked_level is None


def test_previous_current_observations_and_numeric_price_path_are_exact():
    state = NumericMarketState()
    state.ingest(_exp(event_id="exp-a", at="2026-07-20T01:00:00Z", market_price="3400.00"))
    state.ingest(_exp(event_id="exp-b", at="2026-07-20T01:01:00Z", market_price="3401.25"))
    assert state.previous_observations["EXPANSION"].producer_event_id == "exp-a"
    assert state.current_observations["EXPANSION"].producer_event_id == "exp-b"
    point = state.price_path[-1]
    assert point.delta == Decimal("1.25")
    assert point.delta_pct == Decimal("0.036764705882352941176470588235294117647058823529412")
    assert point.movement_direction == "UP"
    assert state.snapshot()["trade_direction"] is None


def test_expansion_history_lookup_uses_source_time_not_receipt_order():
    later = _exp(event_id="later", at="2026-07-20T01:04:00Z", market_price="3402")
    earlier = _exp(event_id="earlier", at="2026-07-20T01:00:00Z", market_price="3400")
    state = NumericMarketState([later, earlier])
    assert [item.producer_event_id for item in state.expansion_history] == ["earlier", "later"]
    assert state.expansion_before("2026-07-20T01:02:00Z").producer_event_id == "earlier"
    assert state.latest_expansion_story.producer_event_id == "later"


def test_multiple_level_selection_uses_exact_tuple_and_locks_without_silent_switch():
    # Both levels exist before the story begins, so the first selection sees the
    # complete candidate set.  PRIME wins before distance is considered.
    valid_nearer = _liq(
        event_id="valid-nearer",
        at="2026-07-20T01:00:00Z",
        creation_id="valid-nearer",
        level_price="3400.40",
        grade="VALID",
        confluence=4,
        touches=0,
    )
    prime = _liq(
        event_id="prime",
        at="2026-07-20T01:00:01Z",
        creation_id="prime",
        level_price="3400.80",
        grade="PRIME",
        confluence=1,
        touches=4,
    )
    state = NumericMarketState([valid_nearer, prime, _exp(at="2026-07-20T01:01:00Z")])
    prime_id = parse_numeric_event(prime).data["level_id"]
    assert state.tracked_level.level_id == prime_id
    # A later and otherwise superior PRIME level remains secondary; lock holds.
    state.ingest(
        _liq(
            event_id="later-superior",
            at="2026-07-20T01:02:00Z",
            creation_id="later-superior",
            level_price="3400.20",
            grade="PRIME",
            confluence=9,
            touches=0,
        )
    )
    assert state.tracked_level.level_id == prime_id


@pytest.mark.parametrize(
    ("left_changes", "right_changes", "winner"),
    [
        # Zone outranks grade and every later key.
        ({"level_price": "3400.40", "grade": "VALID"}, {"level_price": "3401.20", "grade": "PRIME"}, "left"),
        # Higher MTF confluence is the third key.
        ({"confluence": 4}, {"confluence": 3}, "left"),
        # Lower ATR distance is the fourth key.
        ({"level_price": "3400.40"}, {"level_price": "3400.80"}, "left"),
        # Fewer confirmed touches is the fifth key.
        ({"touches": 1}, {"touches": 2}, "left"),
        # Newer confirmed creation time is the sixth key.
        ({"created": "2026-07-20T00:31:00Z"}, {"created": "2026-07-20T00:30:00Z"}, "left"),
    ],
)
def test_selection_tuple_precedence_is_exact(left_changes, right_changes, winner):
    common = {"grade": "VALID", "confluence": 2, "touches": 1, "level_price": "3401.00"}
    left = _liq(event_id="tuple-left", creation_id="tuple-left", **{**common, **left_changes})
    right = _liq(event_id="tuple-right", creation_id="tuple-right", **{**common, **right_changes})
    state = NumericMarketState([left, right, _exp(at="2026-07-20T01:05:00Z")])
    expected = parse_numeric_event(left if winner == "left" else right).data["level_id"]
    assert state.tracked_level.level_id == expected
    assert len(state.snapshot()["tracked_selection_tuple"]) == 7


def test_lexical_level_id_is_deterministic_final_tie_break():
    left = _liq(event_id="left", creation_id="left")
    right = _liq(event_id="right", creation_id="right")
    left_id = parse_numeric_event(left).data["level_id"]
    right_id = parse_numeric_event(right).data["level_id"]
    state = NumericMarketState([left, right, _exp(at="2026-07-20T01:05:00Z")])
    assert state.tracked_level.level_id == min(left_id, right_id)


def test_directional_selection_is_up_to_ask_down_to_bid_without_trade_inference():
    ask = _liq(event_id="ask", creation_id="ask", side="ASK", level_price="3401")
    bid = _liq(event_id="bid", creation_id="bid", side="BID", level_price="3399")
    up = NumericMarketState([ask, bid, _exp(direction="UP", event="EXP_UP")])
    down = NumericMarketState([ask, bid, _exp(direction="DOWN", event="EXP_DOWN")])
    assert up.tracked_level.side == "ASK"
    assert down.tracked_level.side == "BID"
    assert up.snapshot()["trade_direction"] is None and down.snapshot()["trade_direction"] is None


def test_far_only_is_context_and_does_not_lock_tracked_level():
    state = NumericMarketState([_liq(level_price="3403"), _exp(at="2026-07-20T01:05:00Z")])
    assert next(iter(state.liquidity_levels.values())).distance.distance_zone == "FAR"
    assert state.tracked_level is None


def test_lifecycle_is_isolated_by_level_identity_and_terminal_release_is_explicit():
    first = _liq(event_id="a-approach", creation_id="a")
    second_touch = _liq(
        event_id="b-touch",
        event="LIQ_TOUCH",
        lifecycle="HIT",
        creation_id="b",
        at="2026-07-20T01:02:30Z",
    )
    state = NumericMarketState([first, _exp(at="2026-07-20T01:02:00Z"), second_touch])
    first_id = parse_numeric_event(first).data["level_id"]
    assert state.liquidity_levels[(first_id, "1")].lifecycle == "APPROACH"
    assert state.tracked_level.level_id == first_id
    first_break = _liq(
        event_id="a-break",
        event="LIQ_BREAK",
        lifecycle="BREAK",
        creation_id="a",
        at="2026-07-20T01:03:00Z",
    )
    state.ingest(first_break)
    assert state.liquidity_levels[(first_id, "1")].lifecycle == "BREAK"
    assert state.tracked_level.level_id != first_id
    assert [item["event"] for item in state.tracked_level_history[-2:]] == [
        "TRACKED_LEVEL_RELEASED",
        "TRACKED_LEVEL_SELECTED",
    ]
    assert state.tracked_level_history[-2]["reason"] == "LEVEL_BREAK"


def test_invalid_lifecycle_regression_fails_closed_without_mutating_history():
    state = NumericMarketState([_liq(event_id="touch", event="LIQ_TOUCH", lifecycle="HIT")])
    before = state.canonical_snapshot()
    with pytest.raises(NumericStateError) as error:
        state.ingest(_liq(event_id="approach-late", event="LIQ_APPROACH", lifecycle="APPROACH", at="2026-07-20T01:03:00Z"))
    assert error.value.code == "INVALID_LIFECYCLE_TRANSITION"
    assert state.canonical_snapshot() == before


def test_renko_maturity_does_not_require_e1_and_provisional_does_not_upgrade():
    state = NumericMarketState([_renko("E2")])
    assert state.renko_state.maturity == "E2"
    state.ingest(_renko("MAIN", event_id="main-provisional", at="2026-07-20T01:04:00Z", confirmed=False, freshness="PROVISIONAL"))
    assert state.renko_state.maturity == "E2"
    assert state.renko_state.latest_stage == "MAIN"
    assert state.renko_state.latest_confirmed is False


def test_renko_main_fire_and_reset_are_evidence_only_and_never_order():
    state = NumericMarketState([_renko("MAIN"), _renko("FIRE", at="2026-07-20T01:04:00Z")])
    assert state.renko_state.maturity == "FIRE"
    assert state.snapshot()["trade_direction"] is None
    assert "order" not in state.snapshot()
    state.ingest(_renko("RESET", at="2026-07-20T01:05:00Z"))
    assert state.renko_state.maturity == "NONE"


def test_exact_event_dedupe_is_idempotent_and_conflict_fails_closed():
    payload = _exp()
    state = NumericMarketState()
    first = state.ingest(payload)
    duplicate = state.ingest(deepcopy(payload))
    assert first.accepted is True and duplicate.duplicate is True
    assert len(state.event_history) == 1
    with pytest.raises(NumericStateError) as error:
        state.ingest({**payload, "market_price": "3401"})
    assert error.value.code == "EVENT_ID_CONFLICT"
    assert len(state.event_history) == 1


def test_semantically_identical_json_with_different_whitespace_is_a_duplicate():
    payload = _exp()
    compact = json.dumps(payload, separators=(",", ":"))
    pretty = json.dumps(payload, indent=4)
    state = NumericMarketState([compact])
    duplicate = state.ingest(pretty)
    assert duplicate.duplicate is True
    assert len(state.event_history) == 1
    # The first immutable raw receipt remains authoritative.
    assert state.event_history[0].raw_payload == compact.encode()


def test_restart_replay_is_order_independent_and_uses_only_explicit_temp_storage(tmp_path):
    events = [
        _liq(event_id="ask", creation_id="ask", at="2026-07-20T01:01:00Z"),
        _exp(event_id="story", at="2026-07-20T01:02:00Z"),
        _renko("E2", at="2026-07-20T01:03:00Z"),
        _renko("FIRE", at="2026-07-20T01:04:00Z"),
    ]
    forward = NumericMarketState(events)
    reverse = NumericMarketState(reversed(events))
    assert forward.canonical_snapshot() == reverse.canonical_snapshot()
    path = tmp_path / "numeric-state-v1.jsonl"
    forward.save_history(path)
    restored = NumericMarketState.load_history(path)
    assert restored.canonical_snapshot() == forward.canonical_snapshot()
    assert [item.raw_payload for item in restored.event_history] == [item.raw_payload for item in forward.event_history]


def test_market_closed_or_provisional_story_cannot_select_a_level():
    level = _liq()
    market_closed = NumericMarketState([level, _exp(at="2026-07-20T01:05:00Z", freshness="MARKET_CLOSED")])
    provisional = NumericMarketState([level, _exp(at="2026-07-20T01:05:00Z", confirmed=False, freshness="PROVISIONAL")])
    assert market_closed.tracked_level is None
    assert provisional.tracked_level is None


def test_module_has_no_runtime_or_side_effect_dependencies():
    import project_a.numeric_state as module

    source_names = set(module.__dict__)
    assert not {"requests", "socket", "sqlite3", "fastapi", "playwright", "subprocess"} & source_names
    assert NumericMarketState().event_history == ()
