"""tests/test_adjudicate_guide.py — P3 點核導讀 generator（verbose_zigzag / tf_guide / fidelity guard）。

table-driven 合成 bars；fidelity guard = re-walk surviving == structure_read.read_tf 官方 sequence。
"""
from scripts.adjudicate_guide import tf_guide, verbose_zigzag

_FIXED = {"min_swing": {"method": "fixed", "value": 10.0}}
_SWING = {"k": 2, "strict_pivot": True}


def _bar(t, v):
    return [t, v, v, v, v]


def _bars(vals):
    return [_bar(i, v) for i, v in enumerate(vals)]


def _piv(*items):
    return [{"idx": i, "kind": k, "price": p} for i, k, p in items]


# ── verbose_zigzag 決定 log ───────────────────────────────────────────────────────
def test_verbose_zigzag_confirm_and_collapse():
    pts = _piv((0, "L", 100), (5, "H", 110), (10, "H", 130), (15, "L", 128))
    swings, log = verbose_zigzag(pts, 10.0)
    whys = [w for _, w, _ in log]
    assert whys == ["seed", "confirm", "collapse_replace", "drop_insignificant"]
    assert [(s["kind"], s["price"]) for s in swings] == [("L", 100), ("H", 130)]


def test_verbose_zigzag_drop_just_under():
    pts = _piv((0, "L", 100), (5, "H", 109.9))       # Δ=9.9 < 10 → drop
    _, log = verbose_zigzag(pts, 10.0)
    assert log[1][1] == "drop_insignificant"


# ── tf_guide + fidelity guard ─────────────────────────────────────────────────────
_TWO = [105, 104, 100, 104, 105, 106, 110, 106, 105]     # low@2=100, high@6=110（Δ=10）


def test_tf_guide_fidelity_ok_and_shape():
    g = tf_guide(_bars(_TWO), structure_cfg=_FIXED, swing_cfg=_SWING)
    assert g["fidelity"] == "OK"                          # re-walk == read_tf 官方
    assert [(s["kind"], s["price"]) for s in g["surviving"]] == [("L", 100), ("H", 110)]
    assert g["min_swing"] == 10.0 and g["bars"] == len(_TWO)


def test_tf_guide_reports_filtered_and_borderline():
    # min_swing=10.5 → Δ10 反轉 drop（啱啱唔過，貼邊界）
    g = tf_guide(_bars(_TWO), structure_cfg={"min_swing": {"method": "fixed", "value": 10.5}},
                 swing_cfg=_SWING)
    assert any("啱啱唔過" in b for b in g["borderline"])
    assert any(f["reason"].startswith("反轉") for f in g["filtered"])


def test_tf_guide_consecutive_direction():
    # 清晰 uptrend 序列
    up = [130, 115, 100, 110, 120, 130, 140, 132.5, 125, 117.5, 110, 120, 130, 140, 150,
          142.5, 135, 127.5, 120, 130, 140, 150, 160, 150, 140]
    g = tf_guide(_bars(up), structure_cfg={"min_swing": {"method": "fixed", "value": 5}},
                 swing_cfg=_SWING)
    assert g["fidelity"] == "OK" and g["consecutive"]["direction"] == "up"
