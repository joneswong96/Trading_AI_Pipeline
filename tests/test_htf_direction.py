"""tests/test_htf_direction.py — HTF 方向純函數（P1 producer 層，唔喺 gates/）。

驗 close vs SMA(N) ± deadband 規則 + edge：死區 / history 不足 / gap / off1 選位 / None。
"""
from analyze.htf_direction import compute_direction, summarize


# ── 主規則（sma_len=5 手算清楚）────────────────────────────────────────────
def test_bullish_above_sma_plus_band():
    # window=[110,100,100,100,100] sma=102；C=110 > 102×1.001 → BULLISH
    assert compute_direction([110, 100, 100, 100, 100], sma_len=5, band=0.001) == "BULLISH"


def test_bearish_below_sma_minus_band():
    # window=[90,100,100,100,100] sma=98；C=90 < 98×0.999 → BEARISH
    assert compute_direction([90, 100, 100, 100, 100], sma_len=5, band=0.001) == "BEARISH"


def test_neutral_inside_deadband():
    # 全平 → C==SMA，落 ±band 死區 → NEUTRAL
    assert compute_direction([100, 100, 100, 100, 100], sma_len=5, band=0.001) == "NEUTRAL"


def test_neutral_just_inside_band_edge():
    # C 僅僅高於 SMA 但未過 +band → 仍 NEUTRAL（死區有效）
    # window=[100.02,100,100,100,100] sma=100.004；+band 線=100.004×1.001≈100.104 → 100.02 未過
    assert compute_direction([100.02, 100, 100, 100, 100], sma_len=5, band=0.001) == "NEUTRAL"


# ── edge cases ──────────────────────────────────────────────────────────────
def test_history_insufficient_returns_neutral():
    assert compute_direction([100, 100, 100], sma_len=5, band=0.001) == "NEUTRAL"
    assert compute_direction([], sma_len=5) == "NEUTRAL"
    assert compute_direction(None, sma_len=5) == "NEUTRAL"


def test_gap_does_not_crash_and_computes():
    # 跳空 20（週末/session gap）→ 照算唔爆，C=120 高出 → BULLISH
    assert compute_direction([120, 100, 100, 100, 100], sma_len=5, band=0.001) == "BULLISH"


def test_off1_is_first_element_not_last():
    # window=[90,110,110,110,110] sma=102；C=closes[0]=90 < −band → BEARISH。
    # 若誤用 closes[-1]=110 會出 BULLISH → 呢個 assert 證 off1=closes[0]。
    assert compute_direction([90, 110, 110, 110, 110], sma_len=5, band=0.001) == "BEARISH"


def test_none_in_window_returns_neutral():
    assert compute_direction([110, 100, None, 100, 100], sma_len=5, band=0.001) == "NEUTRAL"


def test_default_knobs_n20_band_0p1pct():
    # 預設 N=20 / band=0.1%：off1=105 + 19×100 → sma=100.25；105 > 100.25×1.001 → BULLISH
    assert compute_direction([105] + [100] * 19) == "BULLISH"


# ── summarize（寫入 htf_closed.json 嘅 auditable record）──────────────────────
def test_summarize_fields_when_enough_history():
    s = summarize([110, 100, 100, 100, 100], sma_len=5, band=0.001)
    assert s["direction"] == "BULLISH"
    assert s["close"] == 110
    assert s["sma"] == 102.0
    assert s["bars_loaded"] == 5
    assert s["sma_len"] == 5
    assert s["band"] == 0.001


def test_summarize_sma_none_when_insufficient():
    s = summarize([100, 100, 100], sma_len=5, band=0.001)
    assert s["direction"] == "NEUTRAL"
    assert s["sma"] is None          # 不足 history → sma 唔靜靜當 0，留 None auditable
    assert s["bars_loaded"] == 3
