"""Step 4 tests：價→像素換算 + 畫線（超界要 graceful，唔 crash）。"""
import pytest
from PIL import Image

from publish.marker import (
    Level, PriceRange, levels_from_call, mark_chart, mark_legend_box, price_to_y,
)


def test_price_to_y_linear():
    pr = PriceRange(top_price=100.0, bottom_price=0.0, top_y=0, bottom_y=100)
    assert price_to_y(100.0, pr) == 0
    assert price_to_y(0.0, pr) == 100
    assert price_to_y(50.0, pr) == 50


def test_price_to_y_zero_span_raises():
    with pytest.raises(ValueError):
        price_to_y(50, PriceRange(50, 50, 0, 100))


def test_levels_from_call_skips_none_and_tags_tp():
    call = {"levels": {"snr": 4057.05, "entry": 4073.5, "sl": 4078.5,
                       "tp1": 4066, "tp2": None}}
    lvs = levels_from_call(call)
    kinds = {lv.kind for lv in lvs}
    assert {"snr", "entry", "sl", "tp"} <= kinds
    assert not any("TP2" in lv.label for lv in lvs)   # None 跳過


def test_mark_chart_in_and_out_of_range(tmp_path):
    src = tmp_path / "in.png"
    Image.new("RGB", (200, 100), (0, 0, 0)).save(src)
    pr = PriceRange(top_price=4080.0, bottom_price=4040.0, top_y=0, bottom_y=100)
    levels = [
        Level("Entry 4060", 4060.0, "entry"),   # 範圍內
        Level("TP 4100", 4100.0, "tp"),          # 超界（上）→ 箭咀，唔 crash
        Level("SL 4000", 4000.0, "sl"),          # 超界（下）→ 箭咀
    ]
    out = tmp_path / "out.png"
    res = mark_chart(str(src), str(out), levels, pr)
    assert res == str(out) and out.exists()


def test_mark_legend_box_keeps_size_and_draws(tmp_path):
    src = tmp_path / "in.png"
    Image.new("RGB", (300, 200), (0, 0, 0)).save(src)
    levels = levels_from_call({"levels": {"snr": 4073.77, "entry": 4073.5,
                                          "sl": 4078.5, "tp1": 4066}})
    out = tmp_path / "marked.png"
    assert mark_legend_box(str(src), str(out), levels, title="Levels") == str(out)
    assert out.exists() and Image.open(out).size == (300, 200)   # 尺寸不變


def test_mark_legend_box_empty_levels_ok(tmp_path):
    src = tmp_path / "in.png"
    Image.new("RGB", (50, 50)).save(src)
    out = tmp_path / "m.png"
    mark_legend_box(str(src), str(out), [], title="Levels")
    assert out.exists()
