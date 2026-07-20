"""Bounded Expansion V3 / Liquidity V2 legacy-ingest compatibility tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ingest import trigger
from ingest.alert_log import AlertLog
from ingest.parser import parse


EXP_DOWN = "EXP DOWN | XAUUSD | TF 1 | Price 3990.66"
EXP_UP = "EXP UP | XAUUSD | TF 1 | Price 3990.66"


def _liq(**overrides):
    payload = {
        "engine": "LIQ_V2",
        "event": "TOUCH",
        "side": "ASK",
        "tf": "5",
        "price": 3995.25,
        "mtf": "3/4",
        "touches": 2,
    }
    payload.update(overrides)
    return payload


def _row(event, minutes_ago=1):
    return {
        "id": 1,
        "ts": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
        "engine": event.engine,
        "event": event.event,
        "dir": event.dir,
        "grade": event.grade,
        "tf": event.tf,
        "price": event.price,
        "raw": json.dumps(event.raw),
    }


@pytest.mark.parametrize(
    ("payload", "event", "move_dir", "symbol", "price"),
    [
        (EXP_DOWN, "EXP_DOWN", "DOWN", "XAUUSD", 3990.66),
        (EXP_UP, "EXP_UP", "UP", "XAUUSD", 3990.66),
        ("EXP UP | ICMARKETS:XAUUSD | TF 1 | Price 3990.66",
         "EXP_UP", "UP", "ICMARKETS:XAUUSD", 3990.66),
        ("EXP DOWN | XAUUSD | TF 1 | Price 3990", "EXP_DOWN", "DOWN", "XAUUSD", 3990.0),
        ("  EXP   DOWN  |  XAUUSD  |  TF   1  |  Price   3990.66  ",
         "EXP_DOWN", "DOWN", "XAUUSD", 3990.66),
    ],
)
def test_expansion_v3_bounded_grammar(payload, event, move_dir, symbol, price):
    ev = parse(payload)
    assert (ev.engine, ev.event, ev.move_dir, ev.symbol) == ("EXP", event, move_dir, symbol)
    assert ev.market_price == ev.price == price
    assert ev.tf == "1"
    assert ev.trade_dir is None and ev.dir is None
    assert ev.raw["_source_payload"] == payload
    assert ev.raw["text"] == payload


@pytest.mark.parametrize(
    "payload",
    [
        "EXP LEFT | XAUUSD | TF 1 | Price 3990.66",
        "EXP DOWN | | TF 1 | Price 3990.66",
        "EXP DOWN | XAUUSD | Price 3990.66",
        "EXP DOWN | XAUUSD | TF 1",
        "EXP DOWN | XAUUSD | TF 1 | Price nope",
        "EXP DOWN | XAUUSD | TF 0 | Price 3990.66",
        "EXP DOWN | XAUUSD | TF 1 | Price NaN",
        "EXP DOWN | XAUUSD | TF 1 | Price 3990.66 | Entry 3991",
    ],
)
def test_malformed_expansion_fails_closed(payload):
    ev = parse(payload)
    assert (ev.engine, ev.event, ev.dir, ev.price) == ("UNKNOWN", "UNKNOWN", None, None)
    assert trigger.evaluate(ev, []).wake is False


def test_expansion_preserves_only_source_semantics_and_never_invents_trade_fields():
    ev = parse(EXP_DOWN)
    canonical = ev.raw["_canonical"]
    assert canonical["move_dir"] == "DOWN"
    assert canonical["trade_dir"] is None
    assert canonical["market_price"] == 3990.66
    assert canonical["level_price"] is None
    assert canonical["signal_price"] is None
    assert ev.grade is None and ev.time is None
    assert not {"entry", "sl", "tp", "grade", "confirmation_status", "source_timestamp"} & canonical.keys()


def test_expansion_is_telemetry_only_even_when_an_active_thesis_price_is_crossed():
    active = {
        "thesis_id": "thesis-test",
        "status": "ARMED",
        "dir": "LONG",
        "invalidation": 4000.0,
        "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    wake, reason = trigger.should_wake([], active, parse(EXP_DOWN))
    assert wake is False
    assert "telemetry-only" in reason


def test_expansion_telemetry_cannot_pair_with_legacy_liquidity_mrf():
    legacy_liq = parse(json.dumps({
        "engine": "LIQ", "event": "TOUCH", "side": "BID", "dir": "LONG",
        "tf": "1", "price": 3990.66, "level": 3989.0, "touches": 2,
    }))
    expansion = parse(EXP_DOWN)
    assert trigger.evaluate(expansion, [_row(legacy_liq)]).wake is False
    assert trigger.evaluate(legacy_liq, [_row(expansion)]).wake is False


@pytest.mark.parametrize(
    ("side", "role"),
    [("ASK", "RESISTANCE"), ("BID", "SUPPORT")],
)
def test_liquidity_v2_maps_bare_price_to_level_only(side, role):
    payload = _liq(side=side)
    body = json.dumps(payload, separators=(",", ":"))
    ev = parse(body)
    assert (ev.engine, ev.event, ev.tf) == ("LIQ_V2", "TOUCH", "5")
    assert ev.level_price == ev.price == 3995.25
    assert ev.market_price is None and ev.signal_price is None
    assert ev.trade_dir is None and ev.dir is None
    assert ev.raw["_canonical"]["liquidity_role"] == role
    assert ev.raw["_canonical"]["side"] == side
    assert ev.raw["_canonical"]["mtf"] == "3/4"
    assert ev.raw["_canonical"]["touches"] == 2
    assert ev.raw["_source_payload"] == payload
    assert ev.raw["_source_text"] == body


@pytest.mark.parametrize(
    "payload",
    [
        _liq(side="MID"),
        _liq(price="not-a-number"),
        _liq(price="NaN"),
        _liq(price=0),
        _liq(event=""),
        _liq(mtf="5/4"),
        _liq(touches=-1),
    ],
)
def test_malformed_liquidity_v2_fails_closed(payload):
    ev = parse(json.dumps(payload))
    assert (ev.engine, ev.event, ev.dir, ev.price) == ("UNKNOWN", "UNKNOWN", None, None)
    assert ev.raw["_source_payload"] == payload
    assert trigger.evaluate(ev, []).wake is False


def test_liquidity_v2_is_always_telemetry_only():
    ev = parse(json.dumps(_liq()))
    decision = trigger.evaluate(ev, [])
    assert decision.wake is False
    assert "telemetry-only" in decision.reason


@pytest.mark.parametrize(
    "payload",
    ["arbitrary unknown text", "please buy gold now", "buy box: 3990"],
)
def test_unknown_text_never_masquerades_as_renko(payload):
    ev = parse(payload)
    assert (ev.engine, ev.event, ev.dir) == ("UNKNOWN", "UNKNOWN", None)
    assert ev.raw["text"] == payload
    assert trigger.evaluate(ev, []).wake is False


@pytest.mark.parametrize(
    ("payload", "event", "direction", "price"),
    [
        ("Renko BUY | box: 2415.0 | score: 8 | tf: 1", "BUY", "long", 2415.0),
        ("SELL | box: 2410.0 | score: 7 | tf: 1", "SELL", "short", 2410.0),
    ],
)
def test_genuine_legacy_renko_text_is_preserved(payload, event, direction, price):
    ev = parse(payload)
    assert (ev.engine, ev.event, ev.dir, ev.price) == ("Renko", event, direction, price)


@pytest.mark.parametrize(
    ("payload", "engine", "event", "direction", "grade"),
    [
        ({"engine": "Renko", "event": "buy", "dir": "buy", "tf": "1", "price": 2415.0},
         "Renko", "BUY", "long", None),
        ({"engine": "Renko", "event": "sell", "dir": "sell", "tf": "1", "price": 2410.0},
         "Renko", "SELL", "short", None),
        ({"type": "FIRE", "dir": "LONG", "tf": "1", "entry": 3990.0},
         "SNR", "FIRE", "long", None),
        ({"type": "ENTRY_PIPELINE", "stage": "PRIMED", "tf": "1"},
         "SNR", "PRIMED", None, None),
        ({"engine": "SR", "event": "GRADE_A_LONG", "tf": "5", "price": 3990.0},
         "SR", "GRADE_A_LONG", "long", "A"),
    ],
)
def test_legacy_json_parser_regressions(payload, engine, event, direction, grade):
    ev = parse(json.dumps(payload))
    assert (ev.engine, ev.event, ev.dir, ev.grade) == (engine, event, direction, grade)


def test_exact_duplicate_behavior_is_unchanged_and_uses_temporary_storage(tmp_path):
    log = AlertLog(tmp_path / "trading.db")
    event = parse(EXP_DOWN)
    assert log.is_duplicate(event) is False
    log.insert_alert(event)
    assert log.is_duplicate(event) is True


def test_endpoint_keeps_existing_accepted_response_contract():
    from ingest import webhook_server as server

    response = TestClient(server.app).post("/alert", content=EXP_DOWN)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "deduped": False,
        "wake": False,
        "reason": "compatibility adapter telemetry-only → 只 log、永不 wake",
        "wake_id": None,
    }


def test_endpoint_parser_exception_remains_fail_closed(monkeypatch):
    from ingest import webhook_server as server

    def fail(_body):
        raise ValueError("test parser failure")

    monkeypatch.setattr(server, "parse", fail)
    response = TestClient(server.app).post("/alert", content="bad")
    assert response.status_code == 200
    assert response.json() == {"ok": False, "stage": "parse"}
