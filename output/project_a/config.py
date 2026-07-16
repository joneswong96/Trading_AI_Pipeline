"""Secret-free, fail-closed Session 5 output configuration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import RendererType, Session5Error


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or []))


def _no_wildcards(values: tuple[str, ...], field: str) -> None:
    if any(not item or item.strip() in {"*", "ANY"} for item in values):
        raise Session5Error("config_wildcard", f"{field} cannot contain blank or wildcard values")


@dataclass(frozen=True)
class TradingViewConfig:
    port: int
    expected_process_identity: str
    expected_symbol: str
    feed_allowlist: tuple[str, ...]
    expected_timeframe: str
    expected_layout_id: str
    expected_tab_id: str


@dataclass(frozen=True)
class TelegramConfig:
    destination_id: str
    owner_user_id: str
    direct_message_only: bool
    max_message_length: int = 1500


@dataclass(frozen=True)
class NotionConfig:
    database_id: str
    schema_fields: tuple[str, ...]


@dataclass(frozen=True)
class MT5Config:
    demo_mirror_enabled: bool
    account_allowlist: tuple[str, ...]
    server_allowlist: tuple[str, ...]
    terminal_path_allowlist: tuple[str, ...]
    symbol_mapping: str
    precision: int


@dataclass(frozen=True)
class OutputConfig:
    shadow: bool
    dry_run: bool
    enabled_renderers: tuple[str, ...]
    retry_limit: int
    retry_seconds: int
    claim_timeout_seconds: int
    storage_path: str
    audit_output_path: str
    tradingview: TradingViewConfig
    telegram: TelegramConfig
    notion: NotionConfig
    mt5: MT5Config

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "OutputConfig":
        if "live_execution" in raw or "order_placement" in raw:
            raise Session5Error("live_route_forbidden", "live/order configuration is not accepted")
        if raw.get("shadow") is not True:
            raise Session5Error("shadow_required", "shadow must be true")
        if raw.get("dry_run") is not True:
            raise Session5Error("dry_run_required", "this branch exposes fake/dry-run mode only")
        enabled = _tuple(raw.get("enabled_renderers"))
        allowed = {item.value for item in RendererType}
        if set(enabled) - allowed:
            raise Session5Error("renderer_config", "enabled_renderers must use the pinned renderer names")

        tv = raw.get("tradingview") or {}
        feeds = _tuple(tv.get("feed_allowlist"))
        _no_wildcards(feeds, "tradingview.feed_allowlist")
        if (tv.get("port") != 4999 or tv.get("expected_symbol") != "XAUUSD"
                or tv.get("expected_timeframe") != "1m"):
            raise Session5Error("tradingview_identity", "XAUUSD/4999/1m is mandatory")
        for key in ("expected_process_identity", "expected_layout_id", "expected_tab_id"):
            if not str(tv.get(key) or "").strip():
                raise Session5Error("tradingview_identity", f"{key} is required")

        tg = raw.get("telegram") or {}
        destination = str(tg.get("destination_id") or "")
        owner = str(tg.get("owner_user_id") or "")
        if not (destination.isdigit() and owner.isdigit() and destination == owner):
            raise Session5Error("telegram_allowlist", "numeric Jones destination and owner IDs must match")
        if tg.get("direct_message_only") is not True:
            raise Session5Error("telegram_direct_only", "Telegram must be direct-message only")

        notion = raw.get("notion") or {}
        if not str(notion.get("database_id") or "").strip():
            raise Session5Error("notion_destination", "Notion database ID is required")

        mt5 = raw.get("mt5") or {}
        accounts = _tuple(mt5.get("account_allowlist"))
        servers = _tuple(mt5.get("server_allowlist"))
        paths = _tuple(mt5.get("terminal_path_allowlist"))
        _no_wildcards(accounts, "mt5.account_allowlist")
        _no_wildcards(servers, "mt5.server_allowlist")
        _no_wildcards(paths, "mt5.terminal_path_allowlist")
        if not accounts or not servers or not paths:
            raise Session5Error("mt5_allowlist", "positive Demo account/server/path allowlists are required")
        if not str(mt5.get("symbol_mapping") or "").strip():
            raise Session5Error("mt5_symbol_mapping", "an exact symbol mapping is required")

        return cls(
            shadow=True,
            dry_run=True,
            enabled_renderers=enabled,
            retry_limit=int(raw.get("retry_limit", 3)),
            retry_seconds=int(raw.get("retry_seconds", 5)),
            claim_timeout_seconds=int(raw.get("claim_timeout_seconds", 60)),
            storage_path=str(raw.get("storage_path") or "storage/project_a_outputs.db"),
            audit_output_path=str(raw.get("audit_output_path") or "storage/project_a_audit"),
            tradingview=TradingViewConfig(
                port=4999,
                expected_process_identity=str(tv["expected_process_identity"]),
                expected_symbol="XAUUSD",
                feed_allowlist=feeds,
                expected_timeframe="1m",
                expected_layout_id=str(tv["expected_layout_id"]),
                expected_tab_id=str(tv["expected_tab_id"]),
            ),
            telegram=TelegramConfig(
                destination_id=destination,
                owner_user_id=owner,
                direct_message_only=True,
                max_message_length=int(tg.get("max_message_length", 1500)),
            ),
            notion=NotionConfig(
                database_id=str(notion["database_id"]),
                schema_fields=_tuple(notion.get("schema_fields")),
            ),
            mt5=MT5Config(
                demo_mirror_enabled=bool(mt5.get("demo_mirror_enabled", False)),
                account_allowlist=accounts,
                server_allowlist=servers,
                terminal_path_allowlist=paths,
                symbol_mapping=str(mt5["symbol_mapping"]),
                precision=int(mt5.get("precision", 2)),
            ),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "OutputConfig":
        return cls.from_mapping(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def fake_output_config(**overrides: Any) -> OutputConfig:
    raw: dict[str, Any] = {
        "shadow": True,
        "dry_run": True,
        "enabled_renderers": [item.value for item in RendererType],
        "retry_limit": 3,
        "retry_seconds": 0,
        "claim_timeout_seconds": 30,
        "storage_path": "storage/project_a_outputs.db",
        "audit_output_path": "storage/project_a_audit",
        "tradingview": {
            "port": 4999,
            "expected_process_identity": "FAKE_TRADINGVIEW_MCP",
            "expected_symbol": "XAUUSD",
            "feed_allowlist": ["ICMARKETS"],
            "expected_timeframe": "1m",
            "expected_layout_id": "PROJECT_A_XAUUSD_1M",
            "expected_tab_id": "tv-tab-xauusd",
        },
        "telegram": {
            "destination_id": "100000001",
            "owner_user_id": "100000001",
            "direct_message_only": True,
            "max_message_length": 1500,
        },
        "notion": {
            "database_id": "fake-project-a-call-log",
            "schema_fields": ["setup_id", "content_hash", "thesis_id", "renderer_statuses"],
        },
        "mt5": {
            "demo_mirror_enabled": False,
            "account_allowlist": ["FAKE-DEMO-1001"],
            "server_allowlist": ["FAKE-BROKER-DEMO"],
            "terminal_path_allowlist": ["C:\\FAKE\\MT5-DEMO\\terminal64.exe"],
            "symbol_mapping": "XAUUSD",
            "precision": 2,
        },
    }
    raw.update(overrides)
    return OutputConfig.from_mapping(raw)
