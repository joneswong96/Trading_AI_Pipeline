"""tests/test_trigger_thesis.py — Phase 1.5 should_wake thesis-aware gate（純函數）。

table-driven：active thesis 抑制普通 wake / invalidation（event + 價穿）bypass / 過期 / 非 active
status / 無 thesis 委派 evaluate（零 regress 等價）。construct AlertEvent 直接。
"""
from datetime import datetime, timedelta, timezone

from ingest.parser import AlertEvent
from ingest.trigger import evaluate, should_wake

_NOW = datetime(2026, 7, 4, 3, 0, 0, tzinfo=timezone.utc)


def _ev(engine="SNR", event="FIRE", dir=None, price=None, raw=None):
    return AlertEvent(engine=engine, event=event, dir=dir, grade=None, tf=None,
                      time=None, price=price, raw=raw or {})


def _thesis(status="ARMED", dir="Long", invalidation=None, valid_until=None,
            thesis_id="thesis-x", invalidated=False):
    vu = valid_until if valid_until is not None else (_NOW + timedelta(hours=2)).isoformat()
    return {"thesis_id": thesis_id, "status": status, "dir": dir,
            "invalidation": invalidation, "valid_until": vu, "invalidated": invalidated}


# ── active thesis 抑制普通 engine wake ───────────────────────────────────────────
def test_active_thesis_suppresses_snr_fire():
    wake, reason = should_wake([], _thesis(status="ARMED"), _ev("SNR", "FIRE", "long"), _NOW)
    assert wake is False and "active thesis" in reason and "只 log" in reason


def test_active_in_trade_suppresses():
    wake, _ = should_wake([], _thesis(status="IN_TRADE"), _ev("SNR", "PRIMED"), _NOW)
    assert wake is False


# ── invalidation bypass ──────────────────────────────────────────────────────────
def test_explicit_invalidation_event_wakes():
    wake, reason = should_wake([], _thesis(status="IN_TRADE"),
                               _ev("SNR", "INVALIDATED", "long"), _NOW)
    assert wake is True and "bypass" in reason


def test_price_break_invalidation_long_wakes():
    # long thesis invalidation=4100；價跌到 4095 → 穿 → wake
    wake, _ = should_wake([], _thesis(dir="Long", invalidation=4100),
                          _ev("MACD", "WEAKEN", "long", price=4095), _NOW)
    assert wake is True


def test_price_break_invalidation_short_wakes():
    wake, _ = should_wake([], _thesis(dir="Short", invalidation=4200),
                          _ev("SR", "GRADE_A", "short", price=4205), _NOW)
    assert wake is True


def test_price_above_invalidation_long_no_bypass():
    # long thesis invalidation=4100，價 4150 未穿 → 普通 alert 被抑制
    wake, _ = should_wake([], _thesis(dir="Long", invalidation=4100),
                          _ev("SNR", "FIRE", "long", price=4150), _NOW)
    assert wake is False


# ── 非 active thesis → 委派 evaluate ─────────────────────────────────────────────
def test_expired_thesis_falls_through():
    past = (_NOW - timedelta(hours=1)).isoformat()
    wake, _ = should_wake([], _thesis(status="ARMED", valid_until=past),
                          _ev("SNR", "FIRE", "long"), _NOW)
    assert wake is True                        # 過期 → 落 SNR FIRE 規則 → wake


def test_wait_status_not_active_falls_through():
    wake, _ = should_wake([], _thesis(status="WAIT"), _ev("SNR", "FIRE", "long"), _NOW)
    assert wake is True                        # WAIT thesis 唔 gate → 照 SNR FIRE wake


def test_invalidated_flag_falls_through():
    wake, _ = should_wake([], _thesis(status="ARMED", invalidated=True),
                          _ev("SNR", "FIRE", "long"), _NOW)
    assert wake is True


# ── 無 thesis → should_wake == evaluate（零 regress 等價）─────────────────────────
def _cases():
    return [
        _ev("SNR", "FIRE", "long"),                       # wake
        _ev("SNR", "SCANNING", "long"),                   # noise no-wake
        _ev("UNKNOWN", "FOO", None),                      # noise
        _ev("EXP", "EXP_UP", "short"),                    # MRF path（未夠對）
    ]


def test_no_thesis_matches_evaluate():
    for ev in _cases():
        d = evaluate(ev, [])
        assert should_wake([], None, ev, _NOW) == (d.wake, d.reason)
