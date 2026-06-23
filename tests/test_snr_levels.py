"""tests/test_snr_levels.py — SNR 精確價純函數（P2b Tier 1，唔喺 gates/）。

round 粒度（$50 grid / $100 major）、assemble（PDH/PDL/PWH/PWL + key_levels + round）、
同價 dedup、缺 high/low 降級、額外 key downstream 唔 strict-fail。
"""
import json

from analyze.snr_levels import _menu_from_bundle, assemble_snr, round_levels


# ── round_levels（$50 grid，$100 major）────────────────────────────────────────────
def test_round_levels_50_grid_major_minor():
    out = round_levels(4150.0, step=50.0, span=75.0)
    prices = [r["price"] for r in out]
    assert prices == [4100.0, 4150.0, 4200.0]          # ±75 內 $50 grid
    wt = {r["price"]: r["weight"] for r in out}
    assert wt[4100.0] == "major" and wt[4200.0] == "major"   # $100 倍數
    assert wt[4150.0] == "minor"


def test_round_levels_no_x50_clutter():
    # $50 grid → 唔會出 x.50 一堆垃圾位（只係 50 倍數）
    assert all(r["price"] % 50 == 0 for r in round_levels(4163.0, step=50.0, span=75.0))


def test_round_levels_price_none():
    assert round_levels(None, step=50.0) == []


# ── assemble_snr ───────────────────────────────────────────────────────────────────
HTF = {"d": {"high": 4209.04, "low": 4180.0, "direction": "BEARISH"},
       "w": {"high": 4218.5, "low": 4023.92, "direction": "BEARISH"}}


def test_assemble_pulls_pdh_pdl_pwh_pwl():
    s = assemble_snr(HTF, [4057.05], 4150.0, round_step=50.0, round_span=75.0, dedup_tol=1.0)
    flat = {lv["price"]: lv["sources"] for lv in s["levels"]}
    assert 4209.04 in flat and "PDH" in flat[4209.04]
    assert 4180.0 in flat and "PDL" in flat[4180.0]
    assert 4218.5 in flat and "PWH" in flat[4218.5]
    assert 4023.92 in flat and "PWL" in flat[4023.92]
    assert 4057.05 in flat and "key_level" in flat[4057.05]


def test_assemble_levels_sorted_and_nearest():
    s = assemble_snr(HTF, [], 4150.0, round_step=50.0, round_span=75.0)
    prices = [lv["price"] for lv in s["levels"]]
    assert prices == sorted(prices)
    assert s["nearest"]["price"] == 4150.0 and s["nearest"]["dist"] == 0.0   # round 4150 最近


def test_assemble_dedup_same_price_one_layer():
    # PDH 4200.3 撞 round 4200 → dedup_tol 1.0 內合併做 1 層、併 sources
    htf = {"d": {"high": 4200.3, "low": 4180.0}, "w": {"high": 9999.0, "low": 1.0}}
    s = assemble_snr(htf, [], 4200.0, round_step=50.0, round_span=75.0, dedup_tol=1.0)
    near200 = [lv for lv in s["levels"] if abs(lv["price"] - 4200) <= 1.0]
    assert len(near200) == 1                                  # 唔雙計
    assert "PDH" in near200[0]["sources"] and any("round" in x for x in near200[0]["sources"])


def test_assemble_missing_high_low_skips_source_no_crash():
    # 舊 bundle htf 冇 high/low → PDH/PDL/PWH/PWL 自動跳過，round + key_levels 照出
    htf = {"d": {"direction": "BEARISH"}, "w": {"direction": "BEARISH"}}
    s = assemble_snr(htf, [4057.05], 4150.0, round_step=50.0, round_span=75.0)
    srcs = {x for lv in s["levels"] for x in lv["sources"]}
    assert "PDH" not in srcs and "PWL" not in srcs           # 缺 → 跳過
    assert "key_level" in srcs and any("round" in x for x in srcs)


def test_assemble_empty_everything():
    s = assemble_snr({}, [], None)
    assert s["levels"] == [] and s["nearest"] is None


# ── downstream：額外 high/low key 唔 strict-fail（htf direction 消費者）────────────────
def test_extra_high_low_keys_do_not_break_direction_consumer():
    from gates.htf_override import compute_htf_override
    reading = {"direction": "BEARISH", "close": 4209.0, "sma": 4374.0, "bars_loaded": 22,
               "sma_len": 20, "band": 0.001, "bar_time": 1,
               "high": 4329.8, "low": 4201.63}        # high/low = P2b 新增 key
    r = compute_htf_override(htf_4h=reading["direction"], htf_daily="BEARISH",
                             htf_weekly="BEARISH", trade_direction="Long", tier="STAND")
    assert r["htf_override_triggered"] is True         # 額外 key 唔影響 .direction 消費


# ── call-site（producer）end-to-end：證精確價真係到到 grading、唔 inert ───────────────────
def test_menu_from_bundle_reads_htf_and_config(tmp_path):
    # 砌一個 bundle/htf_closed.json（d/w 有 P2b high/low）→ _menu_from_bundle 讀返 + 真 config
    bundle = tmp_path / "20260620-snr-test"
    bundle.mkdir()
    (bundle / "htf_closed.json").write_text(json.dumps({
        "readings": {
            "h4": {"direction": "BEARISH", "close": 4151.0},
            "d": {"direction": "BEARISH", "close": 4209.0, "high": 4256.6, "low": 4201.63},
            "w": {"direction": "BEARISH", "close": 4218.5, "high": 4363.59, "low": 4023.92},
        }}, ensure_ascii=False), encoding="utf-8")
    menu = _menu_from_bundle(str(bundle), 4210.0)        # spot 現價
    srcs = {x for lv in menu["levels"] for x in lv["sources"]}
    assert {"PDH", "PDL", "PWH", "PWL"} <= srcs           # D/W high/low 真係入到 menu
    assert "key_level" in srcs                            # 真 config key_levels passthrough
    assert any("round" in x for x in srcs)                # round numbers 出到
    assert menu["nearest"] is not None                    # near boolean 參考備到
