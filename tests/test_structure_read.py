"""tests/test_structure_read.py — P3 STEP 1 structure_read 純函數（唔喺 gates/）。

table-driven 合成 bars + 邊界（min_swing 啱啱過/唔過、equal highs strict 唔當 pivot、gap bar）
+ 真 bundle fixture deterministic。structure_read reuse structure_state 嘅 atr/_zigzag（Jones 拍板）。
"""
import json
import os

from analyze import structure_read as sr
from analyze.structure_state import atr as ss_atr


def _bar(t, v):
    return [t, v, v, v, v]            # [t,O,H,L,C]；H=L=C=v（pivot 用 H/L 同值，清楚分上下）


def _bars(vals):
    return [_bar(i, v) for i, v in enumerate(vals)]


_FIXED = {"min_swing": {"method": "fixed", "value": 10.0}}
_SWING = {"k": 2, "strict_pivot": True}


# ── atr14（reuse structure_state.atr，period 固定 14）─────────────────────────────
def test_atr14_matches_period14():
    bars = [[i, 10, 10, 8, 9] for i in range(15)]        # 每 bar TR=2
    assert sr.atr14(bars) == 2.0 == ss_atr(bars, 14)


def test_atr14_insufficient_none():
    assert sr.atr14([[i, 10, 10, 8, 9] for i in range(10)]) is None


def test_atr14_gap_bar_raises_tr():
    """gap bar：TR = max(H-L, |H-prevC|, |L-prevC|) 應反映跳空 → ATR 高過平常。"""
    bars = [[i, 10, 10, 8, 9] for i in range(14)]        # 前 14 條 TR=2
    bars.append([14, 20, 20, 18, 19])                    # gap up：TR = |20-9| = 11
    a = sr.atr14(bars)
    assert a == ss_atr(bars, 14) and a > 2.0             # gap 抬高 ATR（14 條窗含 gap）


# ── swing_sequence 顯著性邊界（食 detect_pivots-shaped 輸出）──────────────────────
def _piv(*items):
    highs = [{"idx": i, "time": i, "price": p} for i, k, p in items if k == "H"]
    lows = [{"idx": i, "time": i, "price": p} for i, k, p in items if k == "L"]
    return {"highs": highs, "lows": lows}


def test_swing_sequence_min_swing_just_passes():
    piv = _piv((0, "L", 100), (5, "H", 110))             # Δ=10；min_swing=10 → >= 確認
    seq = sr.swing_sequence(piv, 10.0)
    assert [(s["kind"], s["price"]) for s in seq] == [("L", 100), ("H", 110)]


def test_swing_sequence_min_swing_just_fails():
    piv = _piv((0, "L", 100), (5, "H", 110))             # Δ=10 < 10.5 → 忽略反轉
    seq = sr.swing_sequence(piv, 10.5)
    assert [(s["kind"], s["price"]) for s in seq] == [("L", 100)]


def test_swing_sequence_collapses_same_kind():
    piv = _piv((0, "L", 100), (5, "H", 110), (10, "H", 130))  # 同型 collapse → 取更高 H130
    seq = sr.swing_sequence(piv, 5.0)
    assert [(s["kind"], s["price"]) for s in seq] == [("L", 100), ("H", 130)]


def test_swing_sequence_no_min_swing_empty():
    piv = _piv((0, "L", 100), (5, "H", 110))
    assert sr.swing_sequence(piv, None) == []
    assert sr.swing_sequence(piv, 0) == []


# ── consecutive_hl_lh 計數 + 方向 ─────────────────────────────────────────────────
def _seq(*items):
    return [{"idx": i, "kind": k, "price": p, "time": i} for i, (k, p) in enumerate(items)]


def test_consecutive_uptrend_counts_all():
    s = _seq(("L", 100), ("H", 110), ("L", 105), ("H", 120), ("L", 112), ("H", 130))
    r = sr.consecutive_hl_lh(s)
    assert r["direction"] == "up" and r["count"] == 4
    assert r["labels"] == ["HL", "HH", "HL", "HH"]


def test_consecutive_downtrend_counts_all():
    s = _seq(("H", 130), ("L", 120), ("H", 125), ("L", 110), ("H", 115), ("L", 100))
    r = sr.consecutive_hl_lh(s)
    assert r["direction"] == "down" and r["count"] == 4
    assert r["labels"] == ["LH", "LL", "LH", "LL"]


def test_consecutive_tail_resets_on_flip():
    s = _seq(("L", 100), ("H", 120), ("L", 110), ("H", 115))   # tail LH（115<120）打斷 up run
    r = sr.consecutive_hl_lh(s)
    assert r["labels"] == ["HL", "LH"] and r["direction"] == "down" and r["count"] == 1


def test_consecutive_insufficient_none():
    r = sr.consecutive_hl_lh(_seq(("L", 100), ("H", 110)))     # 各型只 1 個 → 冇 label
    assert r == {"count": 0, "direction": "none", "labels": []}


def test_consecutive_empty():
    assert sr.consecutive_hl_lh([]) == {"count": 0, "direction": "none", "labels": []}


# ── read_tf 端到端（合成 bars → detect_pivots → sequence）───────────────────────
_TWO_PIV = [105, 104, 100, 104, 105, 106, 110, 106, 105]   # low@2=100, high@6=110（Δ=10）


def test_read_tf_min_swing_boundary_pass():
    r = sr.read_tf(_bars(_TWO_PIV), structure_cfg=_FIXED, swing_cfg=_SWING)  # min_swing=10 → 兩 swing
    assert [(s["kind"], s["price"]) for s in r["sequence"]] == [("L", 100), ("H", 110)]
    assert r["min_swing"] == 10.0


def test_read_tf_min_swing_boundary_fail():
    cfg = {"min_swing": {"method": "fixed", "value": 10.5}}
    r = sr.read_tf(_bars(_TWO_PIV), structure_cfg=cfg, swing_cfg=_SWING)     # Δ10 < 10.5 → 淨低 pivot
    assert [(s["kind"], s["price"]) for s in r["sequence"]] == [("L", 100)]


_EQUAL_HIGHS = [105, 104, 110, 110, 104, 105, 104]         # idx2/idx3 平頂
def test_read_tf_equal_highs_not_pivot():
    r = sr.read_tf(_bars(_EQUAL_HIGHS), structure_cfg=_FIXED, swing_cfg=_SWING)
    assert r["pivots"]["highs"] == 0                        # strict：平頂唔當 pivot


# ── 真 bundle fixture：deterministic + valid ──────────────────────────────────────
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "structure_ohlc_sample.json")


def test_real_fixture_deterministic_and_valid():
    bars = json.load(open(_FIXTURE, encoding="utf-8"))["bars"]
    a = sr.read_structure(bars, structure_cfg={"min_swing": {"method": "atr", "atr_period": 14,
                          "atr_mult": 1.0}}, swing_cfg=_SWING)
    b = sr.read_structure(bars, structure_cfg={"min_swing": {"method": "atr", "atr_period": 14,
                          "atr_mult": 1.0}}, swing_cfg=_SWING)
    assert a == b                                           # deterministic
    assert set(a) == {"m5", "m15", "h4", "d", "w"}
    for tf, r in a.items():
        assert r["bars"] > 0
        chl = r["consecutive_hl_lh"]
        assert chl["direction"] in {"up", "down", "none"}
        assert isinstance(chl["count"], int) and chl["count"] >= 0
