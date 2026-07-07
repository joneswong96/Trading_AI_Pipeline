"""tests/test_trigger_cooldown.py — cooldown 改「真 wake 錨定」（Jones 2026-07-07 拍板）。

cooldown 唔再用「同 engine 15 分鐘內有無較早 alert」proxy（會被 log-only SCANNING/APPROACHING/
BLOCKED 續命，2026-07-06 live bug），改為只由上次**真 wake**（wake_log，wake=True）計 15 分鐘。
evaluate 收多一個 recent_wakes（真 wake 記錄，engine/dir/ts）。cooldown key = engine+dir 不變。
"""
from datetime import datetime, timedelta, timezone

from ingest import trigger
from ingest.parser import AlertEvent

_COOLDOWN = trigger.COOLDOWN_MIN


def _ago(mins):
    return (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()


def _snr(event="FIRE", dir="long"):
    return AlertEvent("SNR", event, dir, None, None, None, None, {})


def _wake(engine="SNR", dir="long", mins=5, line=None):
    r = {"ts": _ago(mins), "engine": engine, "dir": dir, "event": "FIRE"}
    if line is not None:
        r["line"] = line
    return r


def _alert(event, dir=None, mins=5):
    return {"id": 1, "ts": _ago(mins), "engine": "SNR", "event": event, "dir": dir,
            "grade": None, "tf": None, "price": None, "raw": "{}"}


# ① FIRE wake 後 10 分鐘再 FIRE → 照擋（原有抑制保留）
def test_fire_within_15_of_real_wake_blocked():
    d = trigger.evaluate(_snr("FIRE", "long"), [], recent_wakes=[_wake(mins=10)])
    assert d.wake is False and "cooldown" in d.reason


# ② FIRE wake 後 2h，中間連串 log-only → PRIMED 應該 wake（重現並修正 live bug）
def test_primed_wakes_2h_after_wake_despite_logonly():
    recent = [_alert("APPROACHING", dir=None, mins=10), _alert("SCANNING", dir=None, mins=5),
              _alert("BLOCKED", dir=None, mins=2)]
    d = trigger.evaluate(_snr("PRIMED", None), recent, recent_wakes=[_wake(mins=120)])
    assert d.wake is True


# ③ 被 cooldown 擋嘅 event（wake=False）唔會續命 cooldown
def test_blocked_event_does_not_extend_cooldown():
    # 上次真 wake 20 分鐘前（已出 15 分窗）；5 分鐘前有個「被擋」PRIMED alert（唔係 wake）
    recent = [_alert("PRIMED", dir=None, mins=5)]
    d = trigger.evaluate(_snr("FIRE", "long"), recent, recent_wakes=[_wake(mins=20)])
    assert d.wake is True and "cooldown" not in d.reason


# 補：真 wake 出咗 15 分窗 → 唔再 cooldown
def test_real_wake_outside_window_no_cooldown():
    d = trigger.evaluate(_snr("FIRE", "long"), [], recent_wakes=[_wake(mins=_COOLDOWN + 1)])
    assert d.wake is True


# 補：cooldown key = engine+dir；唔同 engine 嘅 wake 唔擋
def test_cooldown_key_engine_dir():
    # 唔同 dir → 唔擋
    d = trigger.evaluate(_snr("FIRE", "long"), [], recent_wakes=[_wake(dir="short", mins=5)])
    assert d.wake is True
    # 同 engine+dir → 擋
    d2 = trigger.evaluate(_snr("FIRE", "long"), [], recent_wakes=[_wake(dir="long", mins=5)])
    assert d2.wake is False


# 補：invalidation 照舊 bypass cooldown
def test_invalidation_bypasses_cooldown():
    ev = AlertEvent("SNR", "INVALIDATED", "long", None, None, None, None, {})
    d = trigger.evaluate(ev, [], recent_wakes=[_wake(mins=5)])
    assert d.wake is True and "invalidation" in d.reason
