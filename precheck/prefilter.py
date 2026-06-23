"""Step 2：pre-check —— Playwright 由 TradingView DOM 讀現價（**唔用 OCR**）。

同上一 cycle 比：價郁超過 threshold、或者接近 key level → trigger（值得叫 AI）；
否則 skip（靜市慳 token，log 一行）。

設計：
- 決策邏輯 `decide()` 係純函數、deterministic、可離線測。
- DOM 讀價 `read_price()` 靠 TV legend 嘅 close 值（selector 喺 live DOM 實測過）。
- `Prefilter` 接 route 1b 同一個 CDP Chrome（揀咗做主力），讀 g4 5m tab 嘅現價。

prev_price 喺 instance 入面記住（scheduler 重用同一個 Prefilter 跨 cycle）。
跨重啟嘅持久化係 Step 6 storage 嘅事，M0 in-memory 夠。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from capture.base import load_asset

# TV legend 嘅 OHLC 值 div。class hash（-l31H9iuA）會隨 TV 更新變，但 prefix
# `valueValue-` 穩定。每個 chart 一組 O/H/L/C，close = 第 4 個 = 現價。
PRICE_VALUE_SELECTOR = '[class*="valueValue-"]'


@dataclass
class PrecheckDecision:
    triggered: bool          # True = 叫 AI；False = skip
    reason: str
    price: float | None
    prev_price: float | None
    nearest_level: float | None = None
    delta: float | None = None     # |price - prev_price|
    near_dist: float | None = None  # |price - nearest_level|


def _nearest_level(price: float | None, key_levels: list[float]):
    if price is None or not key_levels:
        return None, None
    nearest = min(key_levels, key=lambda lv: abs(lv - price))
    return nearest, abs(nearest - price)


def decide(price: float, prev_price: float | None, key_levels: list[float],
           move_threshold: float, near_level: float) -> PrecheckDecision:
    """純函數：現價 / 上一價 / key levels / 門檻 → trigger 定 skip。

    第一個 cycle（prev_price=None）一定 trigger（冇基準，唔好 skip 走第一個 call）。
    """
    nearest, near_dist = _nearest_level(price, key_levels)
    near_hit = near_dist is not None and near_dist <= near_level

    if prev_price is None:
        return PrecheckDecision(
            True, "first cycle（冇上一價基準）→ trigger", price, None,
            nearest, None, near_dist)

    delta = abs(price - prev_price)
    if delta >= move_threshold:
        return PrecheckDecision(
            True, f"價郁 Δ{delta:.2f} ≥ {move_threshold} → trigger",
            price, prev_price, nearest, delta, near_dist)
    if near_hit:
        return PrecheckDecision(
            True, f"近 key level {nearest}（Δ{near_dist:.2f} ≤ {near_level}）→ trigger",
            price, prev_price, nearest, delta, near_dist)
    return PrecheckDecision(
        False, f"靜市（Δ{delta:.2f} < {move_threshold}，又唔近 level）→ skip",
        price, prev_price, nearest, delta, near_dist)


def _to_float(text: str | None) -> float | None:
    try:
        return float(text.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def read_price(page) -> float:
    """由 TV chart tab 嘅 legend 讀現價：第一組 OHLC 嘅 close（第 4 個值）。

    MACD pane 嘅值（個位數）會被「似價錢」嘅篩走——其實唔篩，係靠次序：
    主圖 legend 排喺前，O/H/L/C 四個，close = index 3。讀唔到就 raise。
    """
    nodes = page.query_selector_all(PRICE_VALUE_SELECTOR)
    nums = [n for n in (_to_float(el.inner_text()) for el in nodes) if n is not None]
    if len(nums) >= 4:
        return nums[3]          # 第一組 OHLC 嘅 close
    if nums:
        return nums[-1]
    raise RuntimeError(
        f"讀唔到價（selector={PRICE_VALUE_SELECTOR}，揾到 {len(nodes)} 個 node，0 個似價錢）")


class Prefilter:
    """接 CDP Chrome（route 1b 主力），讀指定 layout tab 嘅現價，同上一 cycle 比。"""

    def __init__(self, asset: str = "xauusd", port: int | None = None,
                 read_shot: str = "g4_5m_1m"):
        self.cfg = load_asset(asset)
        self.port = port or int(os.environ.get("TV_CDP_PORT", "9222"))
        self.read_shot = read_shot   # 由邊個 layout tab 讀價（預設主圖 g4 5m）
        self._prev_price: float | None = None

    def _layout_url(self) -> str | None:
        for s in self.cfg["screenshots"]:
            if s["id"] == self.read_shot:
                return s.get("url")
        return None

    def read_current_price(self) -> float:
        from playwright.sync_api import sync_playwright
        want = (self._layout_url() or "").split("?")[0].rstrip("/")
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
            pg = None
            for ctx in b.contexts:
                for page in ctx.pages:
                    if want and page.url.split("?")[0].rstrip("/") == want:
                        pg = page
            if pg is None:
                raise RuntimeError(
                    f"搵唔到 {self.read_shot} tab（CDP {self.port}，要開齊 layout 並登入）")
            return read_price(pg)

    def check(self) -> PrecheckDecision:
        """讀現價 → decide()，更新 prev_price，回 PrecheckDecision。"""
        price = self.read_current_price()
        pc = self.cfg["precheck"]
        d = decide(price, self._prev_price, self.cfg.get("key_levels", []),
                   pc["move_threshold_usd"], pc["near_level_usd"])
        self._prev_price = price
        return d


if __name__ == "__main__":
    from capture.base import force_utf8_stdout
    force_utf8_stdout()
    d = Prefilter().check()
    print(f"price={d.price} prev={d.prev_price} "
          f"trigger={d.triggered}\n  → {d.reason}")
