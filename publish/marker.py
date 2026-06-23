"""Step 4：marked 截圖 —— 用 Pillow 喺主圖（g4 5m/1m）畫 SNR/Entry/SL/TP 水平線。

Pipeline 第 ④（Call 出咗）同第 ⑤（push）之間行。
輸入：call.json 嘅 levels + 主圖截圖 + chart 可視價格範圍（top/bottom 價 ↔ top/bottom 像素 y）。
價位→y 線性換算 → 畫水平線 + 價位 label。用 Pillow（畫線+文字夠晒，少一個重依賴）。

可視價格範圍（price_range）點嚟：理想係 Playwright 由 DOM 讀價軸頂底（Step 4 verify 人眼核）。
TV 價軸係 canvas，DOM 唔一定攞到——所以本模組將 price_range 做**參數**（純、可測），
真・讀價軸嗰部分留 TODO，唔阻 mapping/畫線邏輯落地同測試。
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

# 顏色（PLAN：SNR 黃 / Entry 藍 / SL 紅 / TP 綠）。key → RGB。
LEVEL_COLORS = {
    "snr": (240, 200, 0),
    "entry": (40, 130, 240),
    "sl": (230, 60, 60),
    "tp": (40, 190, 90),
}
DEFAULT_COLOR = (200, 200, 200)


@dataclass
class Level:
    label: str          # 顯示文字，例如 "Entry 4073.5"
    price: float
    kind: str           # snr / entry / sl / tp（揀色用）


@dataclass
class PriceRange:
    """chart 可視範圍：top_price 喺像素 y=top_y，bottom_price 喺 y=bottom_y。"""
    top_price: float
    bottom_price: float
    top_y: int
    bottom_y: int


def price_to_y(price: float, pr: PriceRange) -> float:
    """價位 → 像素 y（線性）。top_price 高、bottom_price 低；y 向下增。

    price 超出 [bottom, top] 都照線性外推（caller 決定點 graceful 處理）。
    """
    span = pr.top_price - pr.bottom_price
    if span == 0:
        raise ValueError("price_range span = 0（top == bottom）")
    frac = (pr.top_price - price) / span
    return pr.top_y + frac * (pr.bottom_y - pr.top_y)


def _color(kind: str):
    return LEVEL_COLORS.get(kind.lower(), DEFAULT_COLOR)


def _font(size: int = 14):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def mark_chart(img_path: str, out_path: str, levels: list[Level],
               pr: PriceRange) -> str:
    """喺截圖畫每條 level 嘅水平線 + label，存 out_path，回 out_path。

    level 超出可視範圍 → 唔畫穿界線，改喺對應上/下界畫箭咀 + label（graceful，唔 crash）。
    """
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _font()
    w = img.width

    lo_y, hi_y = min(pr.top_y, pr.bottom_y), max(pr.top_y, pr.bottom_y)
    for lv in levels:
        color = _color(lv.kind)
        y = price_to_y(lv.price, pr)
        if y < hi_y and y > lo_y:               # 喺可視範圍內 → 正常水平線
            yi = int(round(y))
            draw.line([(0, yi), (w, yi)], fill=color, width=2)
            _label(draw, font, w, yi, lv.label, color, above=False)
        else:                                   # 超界 → 邊緣箭咀（唔 crash）
            edge_y = lo_y + 2 if y <= lo_y else hi_y - 2
            arrow = "▲" if y <= lo_y else "▼"
            draw.line([(0, edge_y), (w, edge_y)], fill=color, width=1)
            _label(draw, font, w, edge_y, f"{arrow} {lv.label}（超界）", color,
                   above=(y <= lo_y))
    img.save(out_path)
    return out_path


def _label(draw, font, w, y, text, color, *, above: bool):
    """喺右邊畫一個有底色嘅價位 label。above=True 就擺喺線上面。"""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * 7, 14
    pad = 3
    x1 = w - tw - 2 * pad - 2
    ty = (y - th - 2 * pad) if above else (y + 1)
    draw.rectangle([x1, ty, x1 + tw + 2 * pad, ty + th + 2 * pad], fill=(20, 20, 20))
    draw.text((x1 + pad, ty + pad), text, fill=color, font=font)


def levels_from_call(call: dict) -> list[Level]:
    """由 call.json 嘅 levels dict 砌 Level list（缺嘅跳過）。

    認得嘅 key：snr/entry/sl/tp1/tp2/tp3（tp* 全部當 tp 色）。值係價（float）。
    """
    out: list[Level] = []
    levels = call.get("levels", {}) or {}
    for key, price in levels.items():
        if price is None:
            continue
        kind = "tp" if key.lower().startswith("tp") else key.lower()
        out.append(Level(label=f"{key.upper()} {price}", price=float(price), kind=kind))
    return out


def mark_legend_box(img_path: str, out_path: str, levels: list[Level], *,
                    title: str = "Levels", corner: str = "bottomright",
                    margin: int = 10) -> str:
    """M0 marked 圖：喺角落畫半透明 box 列 SNR/Entry/SL/TP + 顏色（**唔定位喺價軸**）。

    精準水平線需要 price↔pixel（TV 價軸全 canvas，DOM 攞唔到）→ defer 去 M2/M3
    TV MCP 精準 level（SSOT 邊界）。M0 用呢個 box 滿足 Q10=C「marked 截圖」。
    levels 空 → 原圖照存（唔畫）。
    """
    base = Image.open(img_path).convert("RGBA")
    if not levels:
        base.convert("RGB").save(out_path)
        return out_path

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font, title_font = _font(14), _font(15)
    pad, sw, line_h = 8, 12, 20

    def _tw(t, f):
        try:
            bb = draw.textbbox((0, 0), t, font=f)
            return bb[2] - bb[0]
        except Exception:
            return len(t) * 7

    rows = [(lv.label, _color(lv.kind)) for lv in levels]
    content_w = max([_tw(title, title_font)] + [sw + 6 + _tw(t, font) for t, _ in rows])
    box_w = content_w + 2 * pad
    box_h = (len(rows) + 1) * line_h + 2 * pad
    x0 = margin if "left" in corner else base.width - box_w - margin
    y0 = margin if "top" in corner else base.height - box_h - margin

    draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=(15, 15, 18, 210))
    draw.text((x0 + pad, y0 + pad), title, fill=(235, 235, 235), font=title_font)
    y = y0 + pad + line_h
    for text, color in rows:
        cy = y + line_h // 2
        draw.rectangle([x0 + pad, cy - sw // 2, x0 + pad + sw, cy + sw // 2], fill=color)
        draw.text((x0 + pad + sw + 6, y + 2), text, fill=color, font=font)
        y += line_h

    Image.alpha_composite(base, overlay).convert("RGB").save(out_path)
    return out_path


# TODO（M2/M3）：read_price_range(page) + mark_chart 精準水平線 —— TV 價軸係 canvas，
# DOM 攞唔到 price↔pixel（2026-06-14 兩次探測證實）。等 M2 TV MCP 精準 level 先做。
# price_to_y / mark_chart / PriceRange 已備好，到時直接用。
