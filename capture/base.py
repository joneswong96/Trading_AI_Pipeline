"""Capture adapter 共用介面（核心原則 #5：截圖方式要可 swap）。"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ShotResult:
    shot_id: str
    ok: bool
    path: str | None
    seconds: float
    error: str | None = None


@dataclass
class CycleResult:
    route: str
    cycle_id: str
    ok: bool                 # bundle 全部 shot 成功先算 ok
    seconds: float
    shots: list[ShotResult] = field(default_factory=list)
    error: str | None = None


def load_asset(asset: str = "xauusd") -> dict:
    with open(ROOT / "config" / "assets.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["assets"][asset]


def bundle_dir(cycle_id: str) -> Path:
    d = ROOT / "storage" / "screenshots" / cycle_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def shot_url(shot: dict, cfg: dict) -> str | None:
    return shot.get("url") or cfg.get("tv_layout") or None


# 私人 layout 喺登出時，TV 唔 raise，照出一版「冇權限睇」HTML —— 截到圖一樣係「成功」，
# 所以淨睇 screenshot 成唔成功會假陽性（會出靚靚 10/10 但全部係登入牆）。要靠頁面內容認登入牆。
LOGIN_WALL_MARKERS = (
    "open this chart layout for you",   # "We can't open this chart layout for you"（避開 apostrophe）
    "to log in to see it",              # "...you need to log in to see it"
)


def detect_login_wall(page) -> str | None:
    """Playwright page 係咪 TV 登入牆／冇權限版。係 → 回傳 error string；否則 None。

    攞唔到 body 內容時 fail-open（回 None），避免誤殺正常截圖。
    """
    try:
        text = page.inner_text("body", timeout=2000).lower()
    except Exception:
        return None
    if any(m in text for m in LOGIN_WALL_MARKERS):
        return "not_logged_in (TV login wall)"
    return None


def force_utf8_stdout() -> None:
    """Windows console / 重定向 stdout 預設 cp1252，print ✅/❌ emoji 會 UnicodeEncodeError。
    CLI entrypoint 開頭叫一次，等 piped output（Step 6 scheduler log）都唔會炒。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t0
