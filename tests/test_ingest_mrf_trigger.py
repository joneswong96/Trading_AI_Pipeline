"""Phase 1 ingest — MRF (Mean-Reversion Fade) trigger tests。

規則：30 分鐘窗內同 fade 方向 EXP(UP/DOWN) + LIQ(TOUCH/SWEEP) → wake（strategy=MRF）。
fade：EXP_UP→short、EXP_DOWN→long；LIQ ASK→short、BID→long。
MACD FLOW_FLIP 同向 = strengthener（macd_confirm=true）。TOO_LONG = veto。WMA5S 永不 wake。
"""
import json
from datetime import datetime, timedelta, timezone

from ingest.parser import parse
from ingest import trigger


def _ev(payload: dict):
    return parse(json.dumps(payload))


def _row(payload: dict, minutes_ago: float = 1.0, rid: int = 1) -> dict:
    """砌一行 alert_events dict（畀 recent）。ts = 現時 - minutes_ago。"""
    ev = _ev(payload)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"id": rid, "ts": ts, "engine": ev.engine, "event": ev.event,
            "dir": ev.dir, "grade": ev.grade, "tf": ev.tf, "price": ev.price,
            "raw": json.dumps(ev.raw, ensure_ascii=False)}


# ---- 基礎 payload ----
EXP_UP = {"engine": "EXP", "event": "EXP_UP", "dir": "LONG", "grade": "CLEAN",
          "tf": "1", "price": 4179.6, "rangeHi": 4185.2, "rangeLo": 4162.8}
EXP_DOWN = {"engine": "EXP", "event": "EXP_DOWN", "dir": "SHORT", "grade": "CLEAN",
            "tf": "1", "price": 4160.0, "rangeHi": 4185.0, "rangeLo": 4158.0}
LIQ_ASK = {"engine": "LIQ", "event": "TOUCH", "side": "ASK", "dir": "SHORT",
           "tf": "1", "price": 4179.6, "level": 4180.1, "touches": 2}
LIQ_BID = {"engine": "LIQ", "event": "TOUCH", "side": "BID", "dir": "LONG",
           "tf": "1", "price": 4160.0, "level": 4159.0, "touches": 2}
LIQ_ASK_SWEEP = {"engine": "LIQ", "event": "SWEEP", "side": "ASK", "dir": "SHORT",
                 "tf": "1", "price": 4179.6, "level": 4180.1, "sweeps": 3}
MACD_SHORT = {"engine": "MACD", "event": "FLOW_FLIP", "dir": "SHORT",
              "tf": "1", "price": 4179.6, "exec": 3, "htf": 4}
# WEAKEN：dir 已係 fade 方向（Bull Weakening→SHORT），直接用、唔反
MACD_WEAKEN_SHORT = {"engine": "MACD", "event": "WEAKEN", "dir": "SHORT",
                     "tf": "1", "price": 4179.6, "exec": 2, "htf": 3}
MACD_WEAKEN_LONG = {"engine": "MACD", "event": "WEAKEN", "dir": "LONG",
                    "tf": "5", "price": 4160.0, "exec": 2, "htf": 3}
TOO_LONG_UP = {"engine": "EXP", "event": "TOO_LONG", "dir": "LONG", "tf": "1", "price": 4179.6}
WMA5S = {"engine": "WMA5S", "event": "FLIP_GREEN", "dir": "LONG", "tf": "5S", "price": 4179.6}


def test_exp_plus_liq_same_fade_wakes():
    # LIQ ASK（fade short）已喺窗內；current EXP_UP（fade short）→ wake
    d = trigger.evaluate(_ev(EXP_UP), [_row(LIQ_ASK, minutes_ago=5)])
    assert d.wake is True
    assert "strategy=MRF" in d.reason
    assert "fade=short" in d.reason
    assert "macd_confirm=true" not in d.reason


def test_exp_down_plus_liq_bid_wakes_long():
    d = trigger.evaluate(_ev(EXP_DOWN), [_row(LIQ_BID, minutes_ago=3)])
    assert d.wake is True and "fade=long" in d.reason


def test_opposite_fade_no_wake():
    # current EXP_UP（fade short）但窗內只有 LIQ BID（fade long）→ 唔夠對
    d = trigger.evaluate(_ev(EXP_UP), [_row(LIQ_BID, minutes_ago=2)])
    assert d.wake is False


def test_single_exp_no_wake():
    d = trigger.evaluate(_ev(EXP_UP), [])
    assert d.wake is False and "只 log" in d.reason


def test_outside_window_no_wake():
    # LIQ ASK 喺 40 分鐘前（超出 30 分窗）→ 唔夠對
    d = trigger.evaluate(_ev(EXP_UP), [_row(LIQ_ASK, minutes_ago=40)])
    assert d.wake is False


def test_too_long_veto_suppresses_wake():
    recent = [_row(LIQ_ASK, minutes_ago=5, rid=1),
              _row(TOO_LONG_UP, minutes_ago=3, rid=2)]   # veto fade=short
    d = trigger.evaluate(_ev(EXP_UP), recent)
    assert d.wake is False and "veto" in d.reason


def test_too_long_dir_long_vetoes_fade_short_pair():
    # TOO_LONG 帶 EXPANSION 方向：dir=LONG（升方向過長）→ 必須 veto fade-SHORT。
    # 之後 EXP_UP(fade short) + LIQ ASK(fade short) 湊成對，但被 veto → NO wake。
    recent = [_row(TOO_LONG_UP, minutes_ago=8, rid=1),   # dir=LONG → veto fade=short
              _row(LIQ_ASK, minutes_ago=5, rid=2)]        # fade=short
    d = trigger.evaluate(_ev(EXP_UP), recent)             # current EXP_UP → fade=short
    assert d.wake is False and "veto" in d.reason


def test_too_long_event_itself_no_wake():
    d = trigger.evaluate(_ev(TOO_LONG_UP), [])
    assert d.wake is False and "TOO_LONG" in d.reason


def test_wma5s_never_wakes():
    # 就算窗內有齊 EXP+LIQ，WMA5S 都唔 wake、唔計
    recent = [_row(EXP_UP, minutes_ago=4), _row(LIQ_ASK, minutes_ago=3)]
    d = trigger.evaluate(_ev(WMA5S), recent)
    assert d.wake is False and "WMA5S" in d.reason


def test_cooldown_dedupe():
    # 第一對 EXP+LIQ 已喺 cooldown 窗內（代表已 wake）；current 再嚟一個 LIQ SWEEP（fade short）→ 抑制。
    # 時間由 MRF_CONFIG cooldown_min 推，唔 hardcode（config 一改測試自動跟）。
    cd = trigger.MRF_CONFIG["cooldown_min"]
    recent = [_row(EXP_UP, minutes_ago=cd * 0.6, rid=1),
              _row(LIQ_ASK, minutes_ago=cd * 0.4, rid=2)]
    d = trigger.evaluate(_ev(LIQ_ASK_SWEEP), recent)
    assert d.wake is False and "cooldown" in d.reason


def test_consecutive_liq_same_fade_only_first_wakes():
    # 連續同 fade LIQ（TOUCH→SWEEP，實戰靠價位微調避 10s dedupe）：只有第一個 wake。
    cd = trigger.MRF_CONFIG["cooldown_min"]
    # 第一個 LIQ：recent 只有 EXP（pair 喺 recent 未完成）→ wake
    d1 = trigger.evaluate(_ev(LIQ_ASK), [_row(EXP_UP, minutes_ago=cd * 0.5)])
    assert d1.wake is True and "strategy=MRF" in d1.reason
    # 第二個 LIQ：recent 已有 EXP + 第一個 LIQ（上次 wake）→ cooldown block
    recent2 = [_row(EXP_UP, minutes_ago=cd * 0.6, rid=1),
               _row(LIQ_ASK, minutes_ago=cd * 0.3, rid=2)]
    d2 = trigger.evaluate(_ev(LIQ_ASK_SWEEP), recent2)
    assert d2.wake is False and "cooldown" in d2.reason


def test_exp_triggered_blocked_after_liq_triggered_wake():
    # 上次 wake 由 LIQ 觸發（EXP@T0 + LIQ@T1=wake）；current 由 EXP 觸發、同 fade、cooldown 內 → block。
    cd = trigger.MRF_CONFIG["cooldown_min"]
    recent = [_row(EXP_UP, minutes_ago=cd * 0.8, rid=1),     # 原本嗰隻 EXP
              _row(LIQ_ASK, minutes_ago=cd * 0.3, rid=2)]     # LIQ-triggered 上次 wake
    d = trigger.evaluate(_ev(EXP_UP), recent)                 # EXP-triggered
    assert d.wake is False and "cooldown" in d.reason


def test_liq_triggered_wake_blocks_even_when_exp_aged_past_cooldown():
    # ROOT-CAUSE 回歸：EXP 已老出 cooldown 窗但仲喺 30m wake 窗，之後 LIQ 重複 → 一定要 block。
    # 舊 proxy（要求 EXP、LIQ 兩邊都喺 cooldown 窗）喺呢個 case 會漏 wake。
    cd = trigger.MRF_CONFIG["cooldown_min"]
    exp_age = cd + (trigger.MRF_WINDOW_MIN - cd) / 2          # 介乎 cooldown 同 wake 窗之間
    recent = [_row(EXP_UP, minutes_ago=exp_age, rid=1),       # EXP 老出 cooldown 窗
              _row(LIQ_ASK, minutes_ago=cd * 0.3, rid=2)]      # 較近 LIQ（上次 wake）
    d = trigger.evaluate(_ev(LIQ_ASK_SWEEP), recent)
    assert d.wake is False and "cooldown" in d.reason


def test_macd_strengthener_flag():
    recent = [_row(LIQ_ASK, minutes_ago=5, rid=1), _row(MACD_SHORT, minutes_ago=4, rid=2)]
    d = trigger.evaluate(_ev(EXP_UP), recent)
    assert d.wake is True and "macd_confirm=true" in d.reason


def test_macd_alone_no_wake():
    d = trigger.evaluate(_ev(MACD_SHORT), [])
    assert d.wake is False and "strengthener" in d.reason


def test_current_liq_with_recent_exp_wakes():
    # 對稱：current 係 LIQ、窗內有 EXP → 一樣 wake
    d = trigger.evaluate(_ev(LIQ_ASK), [_row(EXP_UP, minutes_ago=5)])
    assert d.wake is True and "fade=short" in d.reason


def test_wake_message_carries_exp_grade_and_liq_level():
    # current=LIQ SWEEP（帶 level），窗內 EXP_UP（帶 grade）→ reason 兩樣都要有
    d = trigger.evaluate(_ev(LIQ_ASK_SWEEP), [_row(EXP_UP, minutes_ago=5)])
    assert d.wake is True
    assert "exp_grade=CLEAN" in d.reason        # 由窗內 EXP 揾返
    assert "liq_level=4180.1" in d.reason        # 由當前 LIQ raw
    assert "fade=short" in d.reason


def test_wake_message_evidence_when_current_is_exp():
    # 對稱方向：current=EXP（帶 grade），窗內 LIQ（帶 level）
    d = trigger.evaluate(_ev(EXP_UP), [_row(LIQ_ASK, minutes_ago=4)])
    assert d.wake is True
    assert "exp_grade=CLEAN" in d.reason
    assert "liq_level=4180.1" in d.reason


# ---- MACD WEAKEN 作為 confirm/strengthener（同 FLOW_FLIP 一樣）----

def test_weaken_same_fade_confirms():
    # 窗內 LIQ ASK + MACD WEAKEN(dir SHORT=fade short)；current EXP_UP → wake + confirm
    recent = [_row(LIQ_ASK, minutes_ago=5, rid=1),
              _row(MACD_WEAKEN_SHORT, minutes_ago=4, rid=2)]
    d = trigger.evaluate(_ev(EXP_UP), recent)
    assert d.wake is True
    assert "macd_confirm=true" in d.reason
    assert "WEAKEN@1" in d.reason            # 顯示邊個 event confirm


def test_weaken_opposite_fade_no_confirm():
    # WEAKEN dir LONG 但 fade=short → 唔算 confirm；pair 仍成 → wake 但無 macd_confirm
    recent = [_row(LIQ_ASK, minutes_ago=5, rid=1),
              _row(MACD_WEAKEN_LONG, minutes_ago=4, rid=2)]
    d = trigger.evaluate(_ev(EXP_UP), recent)
    assert d.wake is True
    assert "macd_confirm" not in d.reason


def test_weaken_alone_never_wakes():
    # 淨 WEAKEN、無 EXP+LIQ pair → 永不 wake（strengthener only）
    d = trigger.evaluate(_ev(MACD_WEAKEN_SHORT), [])
    assert d.wake is False and "strengthener" in d.reason


def test_weaken_with_pair_but_no_exp_liq_still_no_wake():
    # 窗內只有 WEAKEN（無 LIQ）；current EXP_UP → pair 未成 → 無 wake
    d = trigger.evaluate(_ev(EXP_UP), [_row(MACD_WEAKEN_SHORT, minutes_ago=3)])
    assert d.wake is False and "只 log" in d.reason


def test_flow_flip_confirm_shows_event_label():
    # 回歸：FLOW_FLIP 亦要顯示 label，且保留 macd_confirm=true
    recent = [_row(LIQ_ASK, minutes_ago=5, rid=1), _row(MACD_SHORT, minutes_ago=4, rid=2)]
    d = trigger.evaluate(_ev(EXP_UP), recent)
    assert d.wake is True
    assert "macd_confirm=true" in d.reason and "FLOW_FLIP@1" in d.reason
