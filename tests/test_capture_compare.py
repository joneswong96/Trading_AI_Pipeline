"""Step 1 offline tests：對比 harness 嘅統計/報告邏輯（唔使 TV 登入）。"""
from collections import Counter

from capture.base import (
    CycleResult, ShotResult, detect_login_wall, load_asset, shot_url,
)
from capture.compare import run_trials, summarize, write_report


class FakeAdapter:
    """照 script 出結果嘅假 adapter，用嚟測 harness 本身。"""
    route = "fake"

    def __init__(self, script):
        self.script = list(script)  # [(ok, seconds, error)]
        self.calls = []

    def capture_bundle(self, cycle_id):
        self.calls.append(cycle_id)
        ok, secs, err = self.script.pop(0)
        shots = [ShotResult("g1_4h_1h", ok, "x.png" if ok else None, secs / 5,
                            None if ok else "TimeoutError: goto")]
        return CycleResult(self.route, cycle_id, ok, secs, shots, err)


def test_run_trials_counts_and_ids():
    fake = FakeAdapter([(True, 5.0, None)] * 3)
    results = run_trials(fake, n=3, pause_s=0)
    assert len(results) == 3
    assert len(set(fake.calls)) == 3  # cycle_id 唔重複


def test_summarize_stats():
    fake = FakeAdapter([
        (True, 4.0, None),
        (True, 6.0, None),
        (False, 30.0, "TimeoutError: navigation"),
        (True, 5.0, None),
    ])
    s = summarize(run_trials(fake, n=4, pause_s=0))
    assert s["success_rate"] == "3/4"
    assert abs(s["avg_s"] - 5.0) < 1e-9     # 平均淨計成功嗰啲
    assert s["worst_s"] == 6.0
    assert isinstance(s["errors"], Counter) and len(s["errors"]) >= 1


def test_write_report_has_both_routes(tmp_path):
    a = FakeAdapter([(True, 5.0, None)] * 2)
    b = FakeAdapter([(False, 9.0, "RuntimeError: 冇 tab")] * 2)
    ra, rb = run_trials(a, 2, 0), run_trials(b, 2, 0)
    out = write_report(
        {"playwright": summarize(ra), "tv_mcp_cdp": summarize(rb)},
        {"playwright": ra, "tv_mcp_cdp": rb},
        path=tmp_path / "report.md")
    text = out.read_text(encoding="utf-8")
    assert "| playwright | 2/2 |" in text
    assert "| tv_mcp_cdp | 0/2 |" in text
    assert "唔落結論" in text  # Jones 拍板，報告唔代揀


def test_shot_url_fallback():
    cfg = {"tv_layout": "https://tv/chart/AAA/"}
    assert shot_url({"id": "g1", "url": ""}, cfg) == "https://tv/chart/AAA/"
    assert shot_url({"id": "g1", "url": "https://tv/chart/BBB/"}, cfg) == "https://tv/chart/BBB/"
    assert shot_url({"id": "g1"}, {}) is None


def test_assets_yaml_has_url_field_per_shot():
    cfg = load_asset("xauusd")
    assert all("url" in s for s in cfg["screenshots"])


class FakePage:
    """模擬 Playwright page.inner_text（guard 測試用，唔使真 browser）。"""
    def __init__(self, body_text, *, boom=False):
        self._text = body_text
        self._boom = boom

    def inner_text(self, selector, timeout=None):
        if self._boom:
            raise RuntimeError("Execution context was destroyed")
        return self._text


def test_detect_login_wall_flags_logged_out():
    wall = ("We can't open this chart layout for you. If you're the owner of "
            "this chart layout, then you need to log in to see it.")
    assert detect_login_wall(FakePage(wall)) == "not_logged_in (TV login wall)"


def test_detect_login_wall_passes_real_layout():
    real = "XAUUSD Gold Spot / U.S. Dollar 4H MACD close 12 26 9 4,218.50"
    assert detect_login_wall(FakePage(real)) is None


def test_detect_login_wall_fail_open_on_error():
    # 攞唔到 body（page detached 等）→ 唔誤殺正常截圖
    assert detect_login_wall(FakePage("", boom=True)) is None


class FakeTab:
    def __init__(self, url):
        self.url = url


def test_find_page_url_match_is_strict():
    """fix ①：URL 有設但配唔到 → None（loud fail），唔好靜靜 fallback 去 index 截錯 tab。"""
    from capture.tv_mcp import CdpCapture
    cap = CdpCapture()
    tabs = [FakeTab("https://www.tradingview.com/chart/AAA/?symbol=ICMARKETS:XAUUSD"),
            FakeTab("https://www.tradingview.com/chart/BBB/")]

    # URL 配到（忽略 ?query 同尾 slash）→ 返對應 tab
    assert cap._find_page(tabs, {"id": "g", "url": "https://www.tradingview.com/chart/AAA/"}, 0) is tabs[0]
    # URL 有設但配唔到 → None（唔 fallback 去 pages[index]）
    assert cap._find_page(tabs, {"id": "g", "url": "https://www.tradingview.com/chart/ZZZ/"}, 0) is None
    # 冇設 URL（want 變 None）→ 保留 index fallback（runbook ①→⑤ 模式）
    assert cap._find_page(tabs, {"id": "g", "url": ""}, 1) is tabs[1]
    assert cap._find_page(tabs, {"id": "g", "url": ""}, 5) is None
