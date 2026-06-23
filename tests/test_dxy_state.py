"""tests/test_dxy_state.py — DXY modifier 純函數（P2a producer 層，唔喺 gates/）。

方向 reuse htf compute_direction（已測），呢度重點驗 trade-relative 嘅 CONFIRM/NEUTRAL/ADVERSE
truth-table + WAIT/無方向 → NEUTRAL（寫死）+ history 不足 → NEUTRAL。
"""
from analyze.dxy_state import compute_dxy_direction, map_dxy_state


# ── 方向（reuse compute_direction；確認 wrapper 接通）────────────────────────────
def test_direction_bullish_bearish_neutral():
    assert compute_dxy_direction([105] + [100] * 19) == "BULLISH"   # off1>SMA → DXY 升
    assert compute_dxy_direction([95] + [100] * 19) == "BEARISH"    # off1<SMA → DXY 跌
    assert compute_dxy_direction([100] * 20) == "NEUTRAL"           # 死區


def test_direction_history_insufficient_neutral():
    assert compute_dxy_direction([100] * 19) == "NEUTRAL"           # < sma_len(20)


# ── map truth-table（DXY 同金 inverse）──────────────────────────────────────────
def test_map_long_confirm_when_dxy_falling():
    assert map_dxy_state("BEARISH", "Long") == "CONFIRM"


def test_map_long_adverse_when_dxy_rising():
    assert map_dxy_state("BULLISH", "Long") == "ADVERSE"


def test_map_short_confirm_when_dxy_rising():
    assert map_dxy_state("BULLISH", "Short") == "CONFIRM"


def test_map_short_adverse_when_dxy_falling():
    assert map_dxy_state("BEARISH", "Short") == "ADVERSE"


def test_map_neutral_direction_is_neutral_both_sides():
    assert map_dxy_state("NEUTRAL", "Long") == "NEUTRAL"
    assert map_dxy_state("NEUTRAL", "Short") == "NEUTRAL"


# ── WAIT / 無方向 → NEUTRAL（寫死）────────────────────────────────────────────────
def test_map_no_trade_direction_defaults_neutral():
    assert map_dxy_state("BULLISH", None) == "NEUTRAL"
    assert map_dxy_state("BEARISH", "") == "NEUTRAL"
    assert map_dxy_state("BULLISH", "WAIT") == "NEUTRAL"


# ── 大小寫 + Buy/Sell alias ──────────────────────────────────────────────────────
def test_map_case_insensitive_and_aliases():
    assert map_dxy_state("bearish", "long") == "CONFIRM"
    assert map_dxy_state("BULLISH", "buy") == "ADVERSE"
    assert map_dxy_state("bullish", "Sell") == "CONFIRM"
    assert map_dxy_state("BEARISH", "SELL") == "ADVERSE"


def test_map_unknown_direction_is_neutral():
    assert map_dxy_state("SOMETHING", "Long") == "NEUTRAL"
    assert map_dxy_state(None, "Short") == "NEUTRAL"
