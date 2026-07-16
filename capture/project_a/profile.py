"""Strict multi-symbol profile interface; V1 enables XAUUSD only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import Session3Error

REQUIRED_TIMEFRAMES = ("5s", "1m", "5m", "15m", "30m")


def normalized_chart_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.hostname not in {"tradingview.com", "www.tradingview.com"}:
        raise Session3Error("WRONG_TAB", "expected an https://www.tradingview.com/chart/... URL")
    path = parts.path.rstrip("/") + "/"
    if not path.startswith("/chart/") or len(path.split("/")) < 4:
        raise Session3Error("WRONG_TAB", "expected an exact TradingView chart layout URL")
    return urlunsplit(("https", "www.tradingview.com", path, "", ""))


@dataclass(frozen=True)
class CaptureProfile:
    symbol: str
    enabled: bool
    aliases: tuple[str, ...]
    broker_feed: str
    host: str
    port: int
    base_timeframe: str
    required_timeframes: tuple[str, ...]
    expected_layout_id: str
    expected_chart_url: str
    expected_chart_count: int
    process_names: tuple[str, ...]
    profile_marker: str

    @classmethod
    def from_dict(cls, data: dict) -> "CaptureProfile":
        profile = cls(
            symbol=str(data["symbol"]),
            enabled=data.get("enabled") is True,
            aliases=tuple(data.get("aliases") or ()),
            broker_feed=str(data["broker_feed"]),
            host=str(data["host"]),
            port=int(data["port"]),
            base_timeframe=str(data["base_timeframe"]),
            required_timeframes=tuple(data["required_timeframes"]),
            expected_layout_id=str(data["expected_layout_id"]),
            expected_chart_url=normalized_chart_url(str(data["expected_chart_url"])),
            expected_chart_count=int(data.get("expected_chart_count", 1)),
            process_names=tuple(name.lower() for name in data.get("process_names", ("chrome.exe",))),
            profile_marker=str(data["profile_marker"]),
        )
        profile.validate()
        return profile

    @classmethod
    def load(cls, path: str | Path) -> "CaptureProfile":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def validate(self) -> None:
        if self.symbol != "XAUUSD" or not self.enabled:
            raise Session3Error("WRONG_SYMBOL", "V1 enables only the exact XAUUSD profile")
        if self.host != "127.0.0.1" or self.port != 4999:
            raise Session3Error("PORT_MISMATCH", f"configured endpoint is {self.host}:{self.port}")
        if self.base_timeframe != "1m":
            raise Session3Error("WRONG_TIMEFRAME", f"base timeframe is {self.base_timeframe}")
        if self.required_timeframes != REQUIRED_TIMEFRAMES:
            raise Session3Error("MISSING_TIMEFRAME", "required sequence must be 5s,1m,5m,15m,30m")
        if not self.aliases or any(alias != alias.upper() or ":" not in alias for alias in self.aliases):
            raise Session3Error("WRONG_SYMBOL", "aliases must be explicit uppercase feed:symbol values")
        if any(alias.split(":", 1)[0] != self.broker_feed or alias.split(":", 1)[1] != self.symbol
               for alias in self.aliases):
            raise Session3Error("WRONG_FEED", "every alias must exactly match the configured feed and symbol")
        if self.expected_chart_count != 1 or not self.expected_layout_id or not self.profile_marker:
            raise Session3Error("WRONG_LAYOUT", "a named single-chart layout and isolated profile marker are required")

    def identity_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "aliases": list(self.aliases),
            "broker_feed": self.broker_feed,
            "host": self.host,
            "port": self.port,
            "base_timeframe": self.base_timeframe,
            "required_timeframes": list(self.required_timeframes),
            "expected_layout_id": self.expected_layout_id,
            "expected_chart_url": self.expected_chart_url,
            "expected_chart_count": self.expected_chart_count,
            "profile_marker": self.profile_marker,
        }


@dataclass(frozen=True)
class TabPin:
    target_id: str
    chart_url: str
    layout_id: str

    @classmethod
    def from_dict(cls, data: dict) -> "TabPin":
        target_id = str(data.get("target_id", ""))
        if not target_id or len(target_id) > 128:
            raise Session3Error("TAB_NOT_FOUND", "an explicit bounded CDP target_id is required")
        return cls(target_id, normalized_chart_url(str(data["chart_url"])), str(data["layout_id"]))

    @classmethod
    def load(cls, path: str | Path) -> "TabPin":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def as_dict(self) -> dict:
        return {"target_id": self.target_id, "chart_url": self.chart_url, "layout_id": self.layout_id}
