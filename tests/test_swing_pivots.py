"""tests/test_swing_pivots.py — 自動 swing-pivot 純函數（P2c Tier 3a，唔喺 gates/）。

known fixture / no-repaint 邊界 / tie-skip / strict 對照 / k=2 vs k=3 / tier / surface per_side +
tie-break / assemble_swing / assemble_snr swing dedup + None-regression / 跨 TF dedup。
"""
from analyze.snr_levels import assemble_snr
from analyze.swing_pivots import (assemble_swing, classify_tier, detect_pivots,
                                   surface_nearest)


def _bar(i, h, lo):
    return [i, h, h, lo, lo]            # [t,O,H,L,C]；只 H(idx2)/L(idx3) 有意義


# ── detect_pivots：known fixture ───────────────────────────────────────────────────
def test_detect_swing_high_known():
    highs = [1, 2, 3, 4, 9, 4, 3, 2, 1]            # peak @ i=4
    lows = [1, 2, 3, 4, 5, 6, 7, 8, 9]            # 單調，無 swing low
    bars = [_bar(i, highs[i], lows[i]) for i in range(9)]
    r = detect_pivots(bars, k=2, strict=True)
    assert [(h["idx"], h["price"]) for h in r["highs"]] == [(4, 9)]
    assert r["lows"] == []


def test_detect_swing_low_known():
    lows = [9, 8, 7, 6, 1, 6, 7, 8, 9]            # trough @ i=4
    highs = [9] * 9                                # 全等高 → strict 無 swing high
    bars = [_bar(i, highs[i], lows[i]) for i in range(9)]
    r = detect_pivots(bars, k=2, strict=True)
    assert [(low["idx"], low["price"]) for low in r["lows"]] == [(4, 1)]
    assert r["highs"] == []


# ── no-repaint 邊界：最後 k 條（+forming 唔喺 bars）唔 host pivot ─────────────────────
def test_no_repaint_last_k_not_pivot():
    highs = [1, 2, 3, 4, 5, 6, 7, 99, 8]          # 大峰 @ i=7（喺最後 k=2 內）
    lows = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    bars = [_bar(i, highs[i], lows[i]) for i in range(9)]   # n=9, scan i∈[2,6]
    r = detect_pivots(bars, k=2, strict=True)
    assert all(h["idx"] != 7 for h in r["highs"])           # i=7 > n-1-k=6 → 唔當 pivot
    assert r["highs"] == []                                  # 單調上升段內無確認 pivot


# ── tie-skip + strict 對照 ─────────────────────────────────────────────────────────
def test_tie_flat_top_strict_skips():
    highs = [1, 2, 5, 5, 2, 1, 0]                  # 平頂兩條等高 @ i=2,3
    lows = [0] * 7
    bars = [_bar(i, highs[i], lows[i]) for i in range(7)]
    assert detect_pivots(bars, k=2, strict=True)["highs"] == []      # 嚴格 → 平頂唔當 pivot
    assert len(detect_pivots(bars, k=2, strict=False)["highs"]) >= 1  # 非嚴格 >= → 有


def test_k_strength_higher_fewer():
    highs = [1, 10, 2, 3, 9, 3, 2, 10, 1]          # i=4 峰但 i±3=10 更高
    lows = [0] * 9
    bars = [_bar(i, highs[i], lows[i]) for i in range(9)]
    k2 = detect_pivots(bars, k=2, strict=True)["highs"]
    k3 = detect_pivots(bars, k=3, strict=True)["highs"]
    assert any(h["idx"] == 4 for h in k2)          # k=2 收 i=4
    assert all(h["idx"] != 4 for h in k3)          # k=3 唔收（i±3 更高）
    assert len(k3) <= len(k2)


# ── classify_tier ──────────────────────────────────────────────────────────────────
def test_classify_tier():
    assert classify_tier("w") == "major" and classify_tier("d") == "major"
    assert classify_tier("h4") == "intermediate"
    assert classify_tier("m15") == "minor" and classify_tier("m5") == "minor"
    assert classify_tier("zz") == "minor"


# ── surface_nearest：per_side 截斷 + tie-break ───────────────────────────────────────
def test_surface_nearest_per_side():
    items = [{"price": p, "tf": "d"} for p in [4100, 4150, 4200, 4250, 4300]]
    out = surface_nearest(items, 4175, per_side=3)
    prices = [it["price"] for it in out]
    assert prices == [4200, 4250, 4300, 4150, 4100]   # 上 3（近→遠）+ 下 2


def test_surface_nearest_tie_break_deterministic():
    items = [{"price": 4200, "tf": "w"}, {"price": 4200, "tf": "d"}]   # 同價同側
    out = surface_nearest(items, 4175, per_side=3)
    assert [it["tf"] for it in out] == ["d", "w"]      # 等距 → (price, tf) 排序 → d 先


# ── assemble_swing e2e ─────────────────────────────────────────────────────────────
def test_assemble_swing_tags_tier_tf_kind():
    bars_d = [_bar(i, h, 0) for i, h in enumerate([1, 2, 3, 4, 9, 4, 3, 2, 1])]   # d swing_high 9
    bars_w = [_bar(i, 99, low) for i, low in enumerate([9, 8, 7, 6, 1, 6, 7, 8, 9])]  # w swing_low 1
    out = assemble_swing({"d": bars_d, "w": bars_w}, 5, k=2, strict=True, per_side=3)
    by = {(o["kind"], o["tf"]): o for o in out}
    assert by[("swing_high", "d")]["price"] == 9 and by[("swing_high", "d")]["tier"] == "major"
    assert by[("swing_low", "w")]["price"] == 1 and by[("swing_low", "w")]["tier"] == "major"


# ── 接入 assemble_snr ───────────────────────────────────────────────────────────────
HTF = {"d": {"high": 4256.6, "low": 4201.63}, "w": {"high": 4363.59, "low": 4023.92}}


def test_assemble_snr_folds_swing_source():
    swing = [{"price": 4189.0, "kind": "swing_high", "tf": "h4", "tier": "intermediate"}]
    s = assemble_snr(HTF, [4057.05], 4190.0, swing_levels=swing)
    srcs = {x for lv in s["levels"] for x in lv["sources"]}
    assert any("swing_high(H4,intermediate)" == x for x in srcs)


def test_assemble_snr_swing_dedup_same_price_one_layer():
    # swing 4256.7 撞 PDH 4256.6（dedup_tol=1.0 內）→ 合併 1 層、sources 併列
    swing = [{"price": 4256.7, "kind": "swing_high", "tf": "d", "tier": "major"}]
    s = assemble_snr(HTF, [], 4250.0, dedup_tol=1.0, swing_levels=swing)
    near = [lv for lv in s["levels"] if abs(lv["price"] - 4256.6) <= 1.0]
    assert len(near) == 1
    assert "PDH" in near[0]["sources"] and any("swing_high" in x for x in near[0]["sources"])


def test_assemble_snr_none_regression_byte_identical():
    # swing_levels=None / 不傳 → output 同 P2b 逐項一致（鎖 backward-compat）
    a = assemble_snr(HTF, [4057.05], 4190.0)
    b = assemble_snr(HTF, [4057.05], 4190.0, swing_levels=None)
    assert a == b
    assert not any("swing" in x for lv in a["levels"] for x in lv["sources"])


def test_assemble_snr_cross_tf_swing_dedup():
    # d swing 4313 撞 w swing 4313.2（同價，非 round-grid 位以隔離）→ 1 層、兩 swing source 併列
    swing = [{"price": 4313.0, "kind": "swing_high", "tf": "d", "tier": "major"},
             {"price": 4313.2, "kind": "swing_high", "tf": "w", "tier": "major"}]
    s = assemble_snr({}, [], 4280.0, dedup_tol=1.0, swing_levels=swing)
    near = [lv for lv in s["levels"] if abs(lv["price"] - 4313) <= 1.0]
    assert len(near) == 1
    assert sum("swing_high" in x for x in near[0]["sources"]) == 2   # d + w 併入同一層
