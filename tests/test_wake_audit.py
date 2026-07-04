"""tests/test_wake_audit.py — wake 質素審計（read-only）純函數 + fixture jsonl 報表。"""
import os

from scripts import wake_audit as wa

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "wake_audit")


def _bundle(captured, closes):
    # bars = [t,O,H,L,C]；H=C+1, L=C-1 造 range
    bars = [[i, c, c + 1, c - 1, c] for i, c in enumerate(closes)]
    return {"captured_utc": captured, "bars": bars}


# ── session_of（Sydney 分區）────────────────────────────────────────────────────
def test_session_of_partitions():
    assert wa.session_of("2026-07-03T22:00:00+00:00") == "Asian"          # 08:00 Syd
    assert wa.session_of("2026-07-03T08:00:00+00:00") == "London"         # 18:00 Syd
    assert wa.session_of("2026-07-03T13:00:00+00:00") == "London/NY overlap"  # 23:00 Syd
    assert wa.session_of("2026-07-03T18:00:00+00:00") == "NY"             # 04:00 Syd
    assert wa.session_of("bad") == "unknown"


# ── categorize_reason ──────────────────────────────────────────────────────────
def test_categorize_reason():
    assert wa.categorize_reason("SNR FIRE → 即刻 wake") == "SNR FIRE"
    assert wa.categorize_reason("SNR PRIMED → 即刻 wake") == "SNR PRIMED"
    assert wa.categorize_reason("strategy=MRF｜EXP+LIQ 同 fade=short") == "MRF fade"
    assert wa.categorize_reason("5 分鐘內 SR(grade)+Renko 同向 共振 → wake") == "共振"
    assert wa.categorize_reason("… invalidation 被破 → bypass") == "INVALIDATION"
    assert wa.categorize_reason("咩都唔係") == "其他"


# ── range_position ──────────────────────────────────────────────────────────────
def test_range_position_midband_vs_edge():
    bars = [[i, 100 + i, 100 + i, 100 + i, 100 + i] for i in range(50)]  # C 由 100→149
    mid = wa.range_position(125, bars, lookback=50, midband_pct=0.60)
    assert mid["low"] == 100 and mid["high"] == 149 and mid["midband"] is True
    edge = wa.range_position(101, bars, lookback=50, midband_pct=0.60)
    assert edge["midband"] is False and edge["dist_to_boundary"] == 1.0


def test_range_position_none_when_no_price_or_bars():
    assert wa.range_position(None, [[0, 1, 1, 1, 1]]) is None
    assert wa.range_position(100, []) is None


# ── nearest_ohlc ─────────────────────────────────────────────────────────────────
def test_nearest_ohlc_picks_closest_time():
    bundles = [_bundle("2026-07-03T10:00:00+00:00", [1]), _bundle("2026-07-03T14:00:00+00:00", [2])]
    got = wa.nearest_ohlc("2026-07-03T13:30:00+00:00", bundles)
    assert got["captured_utc"] == "2026-07-03T14:00:00+00:00"


# ── build_report（fixture jsonl）──────────────────────────────────────────────────
def test_build_report_full():
    wakes = wa.load_jsonl(os.path.join(_FIX, "wake_log.jsonl"))
    queue = wa.load_jsonl(os.path.join(_FIX, "wake_queue.jsonl"))
    theses = [{"thesis_id": "thesis-armed", "status": "ARMED", "dir": "Long"},
              {"thesis_id": "thesis-wait", "status": "WAIT", "dir": ""}]
    bundles = [_bundle("2026-07-03T12:30:00+00:00", list(range(4100, 4200)))]
    md = wa.build_report(wakes, queue, theses, bundles, since=None)

    assert "SNR FIRE" in md and "MRF fade" in md and "INVALIDATION" in md and "共振" in md
    # ③ consumed linkage：1 白叫(WAIT) + 1 有效(ARMED) + 1 未 consumed
    assert "白叫(WAIT/NO_TRADE) 1" in md and "有效(ARMED/IN_TRADE) 1" in md
    assert "未 consumed" in md and "fatigue rate" in md
    # ④ 有 mid-band 佔比行
    assert "mid-band" in md


def test_build_report_since_filter_and_empty_queue():
    wakes = wa.load_jsonl(os.path.join(_FIX, "wake_log.jsonl"))
    md = wa.build_report(wakes, [], [], [], since="2026-07-03T20:00:00+00:00")
    # since 濾走 12:00/13:30/14:00，只剩 22:10 一筆
    assert "wake_log 1 筆" in md
    assert "wake_queue 空" in md            # queue 空 → 補充路徑
