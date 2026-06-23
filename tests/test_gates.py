"""gates/ deterministic 單元測試（M1 phase 1）。

table-driven：用 3 個**真 bundle**（已 crop-read 對住 captured PNG 核實，replayable）做
fixture，assert gate 確定性（同 input → 同 output）。再加邊界 case（NEUTRAL / BEAR 主向 /
讀唔到 / grade 封頂 / range）。純函數，冇 I/O、冇 network、冇 vision。
"""
import pytest

from gates.confluence import grade_from_layers
from gates.day_type import compute_day_type
from gates.expansion_leg import evaluate_expansion_leg
from gates.htf_override import compute_htf_override
from gates.macd_gate import classify_tf, compute_macd_gate
from gates.range_gate import compute_range_gate
from gates.signal_tier import evaluate_signal_tier
from gates.two_strike import evaluate_two_strike

# ── 3 個真 bundle（MACD label 數 = 對住 captured PNG crop-read 核實）─────────────
BUNDLES = [
    {
        "id": "20260614-201320",        # golden（locked）→ RANGE、gate 2/4、pass false
        "macd": {
            "m1":  {"hist": 0.36, "macd": 1.14, "signal": 0.78},
            "m5":  {"hist": 1.09, "macd": -0.07, "signal": -1.16},
            "m15": {"hist": -0.87, "macd": 1.27, "signal": 2.14},
            "m30": {"hist": -0.90, "macd": 5.75, "signal": 6.64},
        },
        "gate": {
            "m1": "BULL", "m5": "BULL", "m15": "BEAR", "m30": "BEAR",
            "direction": "BULL", "score": 2, "gate_pass": False,
            "display": "M1✓ / 5m✓ / 15m✗ / 30m✗ = 2/4",
        },
    },
    {
        "id": "20260615-114512",        # gate 4/4、pass true
        "macd": {
            "m1":  {"hist": 0.78, "macd": 4.76, "signal": 3.97},
            "m5":  {"hist": 0.61, "macd": 6.70, "signal": 6.09},
            "m15": {"hist": 1.49, "macd": 22.04, "signal": 20.55},
            "m30": {"hist": 7.41, "macd": 27.69, "signal": 20.28},
        },
        "gate": {
            "m1": "BULL", "m5": "BULL", "m15": "BULL", "m30": "BULL",
            "direction": "BULL", "score": 4, "gate_pass": True,
            "display": "M1✓ / 5m✓ / 15m✓ / 30m✓ = 4/4",
        },
    },
    {
        "id": "20260615-134424",        # gate 2/4、pass false（M1✓ 5m✗ 15m✗ 30m✓）
        "macd": {
            "m1":  {"hist": 0.21, "macd": -0.11, "signal": -0.32},
            "m5":  {"hist": -1.71, "macd": 4.23, "signal": 5.94},
            "m15": {"hist": -1.02, "macd": 21.57, "signal": 22.59},
            "m30": {"hist": 4.91, "macd": 31.92, "signal": 27.01},
        },
        "gate": {
            "m1": "BULL", "m5": "BEAR", "m15": "BEAR", "m30": "BULL",
            "direction": "BULL", "score": 2, "gate_pass": False,
            "display": "M1✓ / 5m✗ / 15m✗ / 30m✓ = 2/4",
        },
    },
]
_BY_ID = {b["id"]: b for b in BUNDLES}


@pytest.mark.parametrize("bundle", BUNDLES, ids=[b["id"] for b in BUNDLES])
def test_macd_gate_real_bundles(bundle):
    out = compute_macd_gate(bundle["macd"])
    exp = bundle["gate"]
    for k, v in exp.items():
        assert out[k] == v, f"{bundle['id']} {k}: {out[k]!r} != {v!r}"


def test_macd_gate_summary():
    """三個 bundle 嘅 score/pass 一覽（spec Verify gate 報告用）。"""
    assert compute_macd_gate(_BY_ID["20260614-201320"]["macd"])["score"] == 2
    assert compute_macd_gate(_BY_ID["20260615-114512"]["macd"])["gate_pass"] is True
    assert compute_macd_gate(_BY_ID["20260615-134424"]["macd"])["gate_pass"] is False


@pytest.mark.parametrize("bundle", BUNDLES, ids=[b["id"] for b in BUNDLES])
def test_macd_gate_deterministic(bundle):
    """同 input → 同 output（行兩次必一致）。"""
    assert compute_macd_gate(bundle["macd"]) == compute_macd_gate(bundle["macd"])


# ── 單格三態分類 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("reading,expect", [
    ({"hist": 0.21, "macd": -0.11, "signal": -0.32}, "BULL"),    # hist>0 且 macd>signal
    ({"hist": -1.71, "macd": 4.23, "signal": 5.94}, "BEAR"),     # hist<0 且 macd<signal
    ({"hist": 0.5, "macd": -0.1, "signal": 0.2}, "NEUTRAL"),     # hist>0 但 macd<signal
    ({"hist": -0.5, "macd": 0.3, "signal": 0.1}, "NEUTRAL"),     # hist<0 但 macd>signal
    ({"hist": 0.0, "macd": 1.0, "signal": 0.5}, "NEUTRAL"),      # hist=0
    ({"hist": 1.0, "macd": 0.5, "signal": 0.5}, "NEUTRAL"),      # macd==signal
    (None, "NEUTRAL"),                                            # 讀唔到 → 唔估
    ({"hist": None, "macd": 1.0, "signal": 0.5}, "NEUTRAL"),     # 缺欄位 → 唔估
])
def test_classify_tf(reading, expect):
    assert classify_tf(reading) == expect


def test_macd_gate_bear_dominant_symmetric():
    """主方向 = BEAR 都計得 score（唔係淨數 BULL）。3 BEAR + 1 BULL → 3/4 pass。"""
    out = compute_macd_gate({
        "m1":  {"hist": -1.0, "macd": -2.0, "signal": -1.0},   # BEAR
        "m5":  {"hist": -1.0, "macd": -3.0, "signal": -2.0},   # BEAR
        "m15": {"hist": -1.0, "macd": -4.0, "signal": -3.0},   # BEAR
        "m30": {"hist": 1.0, "macd": 2.0, "signal": 1.0},      # BULL
    })
    assert out["direction"] == "BEAR" and out["score"] == 3 and out["gate_pass"] is True
    assert out["display"] == "M1✓ / 5m✓ / 15m✓ / 30m✗ = 3/4"


def test_macd_gate_neutral_does_not_vote():
    """NEUTRAL 唔投票：2 BULL + 2 NEUTRAL → score 2、唔過。"""
    out = compute_macd_gate({
        "m1":  {"hist": 1.0, "macd": 2.0, "signal": 1.0},      # BULL
        "m5":  {"hist": 1.0, "macd": 2.0, "signal": 1.0},      # BULL
        "m15": {"hist": 0.5, "macd": -0.1, "signal": 0.2},     # NEUTRAL
        "m30": None,                                            # NEUTRAL（讀唔到）
    })
    assert out["score"] == 2 and out["gate_pass"] is False
    assert out["m15"] == "NEUTRAL" and out["m30"] == "NEUTRAL"


def test_macd_gate_missing_input_safe():
    """完全冇 input → 全 NEUTRAL、score 0、唔 crash。"""
    out = compute_macd_gate(None)
    assert out["score"] == 0 and out["gate_pass"] is False
    assert all(out[tf] == "NEUTRAL" for tf in ("m1", "m5", "m15", "m30"))


# ── confluence grade（contract §F）─────────────────────────────────────────
@pytest.mark.parametrize("layers,anchor,dxy,grade,capped", [
    (0, False, "NEUTRAL", "C",  False),   # 0 layer → C
    (2, True,  "CONFIRM", "C",  False),   # 1–2 → C
    (3, True,  "CONFIRM", "B+", False),   # 3 → B+
    (4, True,  "CONFIRM", "A",  False),   # 4 → A
    (5, True,  "CONFIRM", "A+", False),   # 5+ → A+
    (6, True,  "CONFIRM", "A+", False),
    (4, True,  "NEUTRAL", "B+", True),    # DXY 橫行 → 封頂 B+
    (4, True,  "ADVERSE", "B+", True),    # DXY 同向 → 封頂 B+
    (5, False, "CONFIRM", "B+", True),    # 冇 5m/15m anchor → 封頂 B+
    (3, False, "NEUTRAL", "B+", False),   # 已經 B+，封頂唔再拉低
])
def test_grade_from_layers(layers, anchor, dxy, grade, capped):
    out = grade_from_layers(layers, anchor, dxy)
    assert out["grade"] == grade and out["capped"] is capped


def test_grade_golden_bundle():
    """golden：0 layer + DXY NEUTRAL → grade C（對齊 golden/expected.md）。"""
    assert grade_from_layers(0, has_5m_or_15m_anchor=False, dxy_state="NEUTRAL")["grade"] == "C"


def test_grade_deterministic():
    assert grade_from_layers(4, True, "CONFIRM") == grade_from_layers(4, True, "CONFIRM")


# ── range gate（contract §B）───────────────────────────────────────────────
def test_range_golden_bundle():
    """golden：RANGE 確認、price 喺 mid-band、唔畀方向（對齊 golden/expected.md）。"""
    out = compute_range_gate(
        boundary_touches=3, fivemin_close_broke=False, minutes_since_break=45,
        bounds=[4183, 4240], price=4211,
    )
    assert out["range_confirmed"] is True
    assert out["allow_direction"] is False
    assert out["price_in_midband"] is True


def test_range_5m_close_break_allows_direction():
    out = compute_range_gate(fivemin_close_broke=True, bounds=[4183, 4240], price=4245)
    assert out["range_confirmed"] is False
    assert out["allow_direction"] is True
    assert out["reason"] == "5m_close_break"


@pytest.mark.parametrize("touches,minutes,confirmed,reason", [
    (3, 0,  True,  "touch"),         # 3 次掂邊界
    (4, 0,  True,  "touch"),
    (0, 30, True,  "time"),          # 30 分鐘冇破
    (0, 45, True,  "time"),
    (3, 30, True,  "touch+time"),
    (2, 20, False, "undecided"),     # 唔夠 → 未確認
])
def test_range_confirm_thresholds(touches, minutes, confirmed, reason):
    out = compute_range_gate(boundary_touches=touches, minutes_since_break=minutes)
    assert out["range_confirmed"] is confirmed and out["reason"] == reason


@pytest.mark.parametrize("price,expect", [
    (4211, True),     # 正中
    (4200, True),     # 中段 60% 內（4194.4–4228.6）
    (4190, False),    # 下緣 20% 帶
    (4235, False),    # 上緣 20% 帶
])
def test_range_midband(price, expect):
    out = compute_range_gate(boundary_touches=3, bounds=[4183, 4240], price=price)
    assert out["price_in_midband"] is expect


def test_range_midband_none_without_price():
    out = compute_range_gate(boundary_touches=3, bounds=[4183, 4240])
    assert out["price_in_midband"] is None


def test_range_deterministic():
    kw = dict(boundary_touches=3, minutes_since_break=45, bounds=[4183, 4240], price=4211)
    assert compute_range_gate(**kw) == compute_range_gate(**kw)


# ── signal tier（SPEC B L83，持倉管理）──────────────────────────────────────
@pytest.mark.parametrize("signals,tier,action", [
    ({}, "NONE", "hold"),                                          # 冇訊號 → 正常持有
    # 🟡 YELLOW ×4
    ({"single_wick": True}, "YELLOW", "hold"),                     # single wick against
    ({"m1_hist_flip": True}, "YELLOW", "hold"),                    # M1 hist flip alone
    ({"single_counter_candle": True}, "YELLOW", "hold"),           # single counter candle
    ({"spread_widening_brief": True}, "YELLOW", "hold"),           # spread widening briefly
    # 🟠 ORANGE ×5
    ({"m5_close_against": True}, "ORANGE", "tighten"),             # M5 close against
    ({"reversal_candles_2plus": True}, "ORANGE", "tighten"),       # 2+ counter candle
    ({"m5_macd_hist_flip": True}, "ORANGE", "tighten"),            # M5 MACD hist clear flip
    ({"near_key_snr": True}, "ORANGE", "tighten"),                 # approaching key SNR
    ({"dxy_sharp_adverse": True}, "ORANGE", "tighten"),            # DXY 急轉不利
    # 🔴 RED ×4
    ({"m5_close_struct_flip": True}, "RED", "cut"),                # M5 close + structural shift
    ({"htf_macd_flip": True}, "RED", "cut"),                       # HTF MACD flip (15m+)
    ({"major_snr_break": True}, "RED", "cut"),                     # major SNR break
    ({"thesis_invalidated": True}, "RED", "cut"),                  # thesis invalidated
])
def test_signal_tier_single(signals, tier, action):
    out = evaluate_signal_tier(signals)
    assert out["tier"] == tier and out["action"] == action


def test_signal_tier_full_spec_coverage():
    """收齊 SPEC「Warning Signal Tiering」全表 4/5/4 = 13 個觸發，唔可少。"""
    from gates.signal_tier import ALL_SIGNALS, TIER_RULES
    counts = {tier: len(keys) for tier, _, _, keys in TIER_RULES}
    assert counts == {"RED": 4, "ORANGE": 5, "YELLOW": 4}
    assert len(ALL_SIGNALS) == 13 and len(set(ALL_SIGNALS)) == 13


def test_signal_tier_escalation():
    """升級制：同時有 YELLOW+ORANGE+RED → 取最重 RED。"""
    out = evaluate_signal_tier({
        "single_wick": True, "near_key_snr": True, "major_snr_break": True,
    })
    assert out["tier"] == "RED" and out["color"] == "🔴"
    assert "major_snr_break" in out["reasons"]


def test_signal_tier_orange_over_yellow():
    out = evaluate_signal_tier({"single_wick": True, "m5_close_against": True})
    assert out["tier"] == "ORANGE"
    assert out["reasons"] == ["m5_close_against"]      # 只列命中 tier 嘅原因


def test_signal_tier_deterministic_and_safe():
    assert evaluate_signal_tier({"htf_macd_flip": True}) == evaluate_signal_tier({"htf_macd_flip": True})
    assert evaluate_signal_tier(None)["tier"] == "NONE"


# ── two-strike 斷路器（SPEC B L79）─────────────────────────────────────────
def test_two_strike_trips_on_two_invalidated():
    calls = [
        {"band": "R1", "direction": "Long", "invalidated": True},
        {"band": "R1", "direction": "Short", "invalidated": True},
    ]
    out = evaluate_two_strike(calls)
    assert out["chop"] is True and out["stop_direction"] is True
    assert out["strikes"] == 2 and out["band"] == "R1"


def test_two_strike_not_tripped_on_one():
    calls = [{"band": "R1", "direction": "Long", "invalidated": True}]
    out = evaluate_two_strike(calls)
    assert out["chop"] is False and out["strikes"] == 1


def test_two_strike_success_breaks_streak():
    """中間有冇被 invalidate（成功/未失效）→ 連續中斷，唔 trip。"""
    calls = [
        {"band": "R1", "direction": "Long", "invalidated": True},
        {"band": "R1", "direction": "Short", "invalidated": False},   # 中斷
        {"band": "R1", "direction": "Long", "invalidated": True},
    ]
    out = evaluate_two_strike(calls)
    assert out["chop"] is False and out["strikes"] == 1


def test_two_strike_scoped_to_band():
    """只計同一 band；其他 band 嘅 invalidate 唔算入。"""
    calls = [
        {"band": "R1", "direction": "Long", "invalidated": True},
        {"band": "R2", "direction": "Short", "invalidated": True},
        {"band": "R1", "direction": "Short", "invalidated": True},
    ]
    out = evaluate_two_strike(calls, band_key="R1")
    assert out["chop"] is True and out["strikes"] == 2
    out2 = evaluate_two_strike(calls, band_key="R2")
    assert out2["chop"] is False and out2["strikes"] == 1


def test_two_strike_ignores_wait_calls():
    """WAIT/SKIP（冇 direction）唔當方向 call。"""
    calls = [
        {"band": "R1", "direction": "Long", "invalidated": True},
        {"band": "R1", "direction": None, "invalidated": False},      # WAIT，唔計
        {"band": "R1", "direction": "Short", "invalidated": True},
    ]
    out = evaluate_two_strike(calls)
    assert out["chop"] is True and out["strikes"] == 2


def test_two_strike_empty_safe():
    out = evaluate_two_strike([])
    assert out["chop"] is False and out["band"] is None and out["strikes"] == 0
    assert evaluate_two_strike(None)["chop"] is False


def test_two_strike_deterministic():
    calls = [
        {"band": "R1", "direction": "Long", "invalidated": True},
        {"band": "R1", "direction": "Short", "invalidated": True},
    ]
    assert evaluate_two_strike(calls) == evaluate_two_strike(calls)


# ── day-type gate（contract §A / SOP STEP 1）────────────────────────────────
def test_day_type_trend_confirmed():
    out = compute_day_type(
        fivemin_move_pts=60, consecutive_hl_lh=True, breakout_with_followthrough=True,
    )
    assert out["day_type"] == "TREND" and out["trend_confirmed"] is True


@pytest.mark.parametrize("move,hl,follow", [
    (30, True, True),     # 移動唔夠 50pt
    (60, False, True),    # 冇連續 HL/LH
    (60, True, False),    # 突破冇跟進
])
def test_day_type_trend_needs_all_three(move, hl, follow):
    out = compute_day_type(
        fivemin_move_pts=move, consecutive_hl_lh=hl, breakout_with_followthrough=follow,
    )
    assert out["trend_confirmed"] is False
    assert out["day_type"] == "NEITHER"     # range 未確認時 → NEITHER


@pytest.mark.parametrize("touches,minutes", [(3, 0), (0, 30)])
def test_day_type_range_confirmed(touches, minutes):
    out = compute_day_type(boundary_touches=touches, minutes_since_break=minutes)
    assert out["day_type"] == "RANGE" and out["range_confirmed"] is True


def test_day_type_neither_on_fresh_breakdown():
    """155739-like：5m 收破細區間但 <50pt、range 又破 → NEITHER（唔追、唔當 range）。"""
    out = compute_day_type(
        fivemin_move_pts=22, consecutive_hl_lh=True, breakout_with_followthrough=False,
        boundary_touches=2, fivemin_close_broke=True, minutes_since_break=0,
    )
    assert out["day_type"] == "NEITHER"


def test_day_type_trend_priority_over_range():
    out = compute_day_type(
        fivemin_move_pts=60, consecutive_hl_lh=True, breakout_with_followthrough=True,
        boundary_touches=3,
    )
    assert out["day_type"] == "TREND"       # 同時成立 → TREND 優先


def test_day_type_deterministic():
    kw = dict(fivemin_move_pts=60, consecutive_hl_lh=True, breakout_with_followthrough=True)
    assert compute_day_type(**kw) == compute_day_type(**kw)


def test_day_type_neither_blocks_both_paths():
    """NEITHER downstream 保守：trend_confirmed 同 range_confirmed 都 False，
    所以 Armed Order（要 TREND）同 range mid-band 自動封方向（要 RANGE）兩條路都唔成立
    → /analyze default WAIT/觀望。"""
    out = compute_day_type(
        fivemin_move_pts=22, consecutive_hl_lh=True, breakout_with_followthrough=False,
        boundary_touches=2, fivemin_close_broke=True, minutes_since_break=0,
    )
    assert out["day_type"] == "NEITHER"
    assert out["trend_confirmed"] is False    # → 唔開 Armed Order、唔用 trend 4H/1H no-veto
    assert out["range_confirmed"] is False    # → 唔當 range mid-band 自動封方向


# ── HTF override（contract §G / SPEC A）─────────────────────────────────────
def test_htf_override_trips_counter_trend():
    out = compute_htf_override(
        htf_4h="BULL", htf_daily="BULL", htf_weekly="BULL",
        trade_direction="Short", tier="HIGH",
    )
    assert out["htf_override_triggered"] is True
    assert out["htf_aligned"] is True and out["counter_trend"] is True
    assert out["tier_out"] == "STAND"       # HIGH → STAND


def test_htf_override_not_triggered_trend_following():
    out = compute_htf_override(
        htf_4h="BULL", htf_daily="BULL", htf_weekly="BULL",
        trade_direction="Long", tier="HIGH",
    )
    assert out["htf_override_triggered"] is False and out["tier_out"] == "HIGH"


def test_htf_override_not_aligned_no_trigger():
    """155739-like：4H BULL 但 W BEAR → 唔齊同向 → 唔觸發。"""
    out = compute_htf_override(
        htf_4h="BULLISH", htf_daily="BULLISH", htf_weekly="BEARISH",
        trade_direction="Short", tier="STAND",
    )
    assert out["htf_aligned"] is False
    assert out["htf_override_triggered"] is False and out["tier_out"] == "STAND"


def test_htf_override_all_bear_counter_long():
    out = compute_htf_override(
        htf_4h="BEAR", htf_daily="BEAR", htf_weekly="BEAR",
        trade_direction="Long", tier="SNIPER",
    )
    assert out["htf_override_triggered"] is True and out["tier_out"] == "HIGH"


@pytest.mark.parametrize("tier_in,tier_out", [
    ("SNIPER", "HIGH"), ("HIGH", "STAND"), ("STAND", "WAIT"), ("WAIT", "WAIT"),
])
def test_htf_override_ladder_clamps(tier_in, tier_out):
    out = compute_htf_override(
        htf_4h="BULL", htf_daily="BULL", htf_weekly="BULL",
        trade_direction="Short", tier=tier_in,
    )
    assert out["tier_out"] == tier_out


def test_htf_override_deterministic():
    kw = dict(htf_4h="BULL", htf_daily="BULL", htf_weekly="BULL",
              trade_direction="Short", tier="HIGH")
    assert compute_htf_override(**kw) == compute_htf_override(**kw)


# ── expansion leg（contract §E / SOP STEP 5）────────────────────────────────
@pytest.mark.parametrize("quality,length,verdict,effect", [
    ("clean", "normal", "POSITIVE", "add_confidence"),
    ("choppy", "normal", "DOWNGRADE", "downgrade"),
    ("clean", "too_long", "DONT_FADE", "none"),
    ("choppy", "too_long", "DONT_FADE", "none"),     # length 優先
    ("clean", "too_short", "SKIP", "skip"),
    ("choppy", "too_short", "SKIP", "skip"),          # length 優先
])
def test_expansion_leg(quality, length, verdict, effect):
    out = evaluate_expansion_leg(quality=quality, length=length)
    assert out["verdict"] == verdict and out["grade_effect"] == effect


def test_expansion_leg_defaults_clean_normal():
    assert evaluate_expansion_leg()["verdict"] == "POSITIVE"


def test_expansion_leg_deterministic():
    assert evaluate_expansion_leg(quality="choppy", length="normal") == \
        evaluate_expansion_leg(quality="choppy", length="normal")
