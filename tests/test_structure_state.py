"""tests/test_structure_state.py — P3 HL/LH 結構 primitive 純函數（唔喺 gates/）。

合成（ATR / zigzag significance / UPTREND HH+HL / DOWNTREND LH+LL / UNCLEAR 不足+mixed）
+ 真 bundle fixture（tests/fixtures/structure_ohlc_sample.json）deterministic。
"""
import json
import os

from analyze.structure_state import (atr, classify_hl_lh, classify_structure,
                                      min_swing_threshold, _zigzag)


def _bar(t, v):
    return [t, v, v, v, v]            # [t,O,H,L,C]；H=L=C=v（pivot 用 H/L 同值，清楚分上下）


def _bars(vals):
    return [_bar(i, v) for i, v in enumerate(vals)]


# ── ATR ─────────────────────────────────────────────────────────────────────────
def test_atr_simple_mean():
    bars = [[i, 10, 10, 8, 9] for i in range(15)]   # 每 bar TR = max(2,|10-9|,|8-9|) = 2
    assert atr(bars, 14) == 2.0


def test_atr_insufficient_none():
    assert atr([[i, 10, 10, 8, 9] for i in range(10)], 14) is None


def test_min_swing_threshold_methods():
    bars = [[i, 10, 10, 8, 9] for i in range(15)]   # ATR14 = 2
    assert min_swing_threshold(bars, 9, {"method": "atr", "atr_period": 14, "atr_mult": 1.0}) == 2.0
    assert min_swing_threshold(bars, 9, {"method": "atr", "atr_period": 14, "atr_mult": 2.0}) == 4.0
    assert min_swing_threshold(bars, 100, {"method": "fixed", "value": 5}) == 5.0
    assert min_swing_threshold(bars, 100, {"method": "pct_price", "pct": 0.01}) == 1.0


# ── _zigzag significance ──────────────────────────────────────────────────────────
def test_zigzag_filters_insignificant_and_collapses():
    piv = [{"idx": 0, "kind": "L", "price": 100, "time": 0},
           {"idx": 5, "kind": "H", "price": 110, "time": 5},
           {"idx": 10, "kind": "L", "price": 108, "time": 10},   # 反轉 2 < min_swing 5 → 忽略
           {"idx": 15, "kind": "H", "price": 130, "time": 15}]   # 同型 collapse → 取 130
    zz = _zigzag(piv, 5)
    assert [(s["kind"], s["price"]) for s in zz] == [("L", 100), ("H", 130)]


# ── classify_hl_lh ────────────────────────────────────────────────────────────────
_UP = [130, 115, 100, 110, 120, 130, 140, 132.5, 125, 117.5, 110, 120, 130, 140, 150,
       142.5, 135, 127.5, 120, 130, 140, 150, 160, 150, 140]      # L100→H140→L110→H150→L120→H160
_DN = [130, 145, 160, 150, 140, 130, 120, 127.5, 135, 142.5, 150, 140, 130, 120, 110,
       117.5, 125, 132.5, 140, 130, 120, 110, 100, 110, 120]      # H160→L120→H150→L110→H140→L100
_MIX = [140, 125, 110, 120, 130, 135, 140, 130, 120, 110, 100, 113, 127, 140, 150,
        135, 120, 105, 90, 107, 125, 142, 160, 150, 140]          # HH(140,150,160) + LL(110,100,90)


def test_classify_uptrend_hh_hl():
    r = classify_hl_lh(_bars(_UP), k=2, strict=True, min_swing=5)
    assert r["state"] == "UPTREND" and r["reason"] == "HH+HL"
    assert r["sig_highs"][-2:] == [150, 160] and r["sig_lows"][-2:] == [110, 120]


def test_classify_downtrend_lh_ll():
    r = classify_hl_lh(_bars(_DN), k=2, strict=True, min_swing=5)
    assert r["state"] == "DOWNTREND" and r["reason"] == "LH+LL"
    assert r["sig_highs"][-2:] == [150, 140] and r["sig_lows"][-2:] == [110, 100]


def test_classify_unclear_mixed():
    r = classify_hl_lh(_bars(_MIX), k=2, strict=True, min_swing=5)
    assert r["state"] == "UNCLEAR" and "mixed" in r["reason"]


def test_classify_unclear_insufficient():
    r = classify_hl_lh(_bars([100, 101, 100, 101, 100]), k=2, strict=True, min_swing=5)
    assert r["state"] == "UNCLEAR" and "不足" in r["reason"]


def test_classify_no_min_swing_unclear():
    r = classify_hl_lh(_bars(_UP), k=2, strict=True, min_swing=None)
    assert r["state"] == "UNCLEAR"


# ── 真 bundle fixture：deterministic + valid states ────────────────────────────────
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "structure_ohlc_sample.json")


def _load_fixture_bars():
    return json.load(open(_FIXTURE, encoding="utf-8"))["bars"]


def test_real_fixture_deterministic_and_valid():
    bars = _load_fixture_bars()
    scfg = {"min_swing": {"method": "atr", "atr_period": 14, "atr_mult": 1.0}}
    wcfg = {"k": 2, "strict_pivot": True}
    a = classify_structure(bars, structure_cfg=scfg, swing_cfg=wcfg)
    b = classify_structure(bars, structure_cfg=scfg, swing_cfg=wcfg)
    assert a == b                                          # deterministic（同 input 同 output）
    assert set(a) == {"m5", "m15", "h4", "d", "w"}         # 5 TF
    for tf, r in a.items():
        assert r["state"] in {"UPTREND", "DOWNTREND", "UNCLEAR"}
        assert r["bars"] > 0
