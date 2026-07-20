"""Fail-closed configuration for the isolated Project A webhook path."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from capture.base import ROOT


def _integer(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class ProjectAConfig:
    database_path: Path
    ingest_host: str = "0.0.0.0"
    ingest_port: int = 8000
    endpoint: str = "/project-a/v0.2/events"
    v1_endpoint: str = "/project-a/v1/events"
    v1_ingest_enabled: bool = False
    raw_producer_ingest_enabled: bool = True
    max_body_bytes: int = 262_144
    future_tolerance_seconds: int = 5
    stale_after_seconds: int = 1_800
    claim_timeout_seconds: int = 300
    max_outbox_attempts: int = 5
    enabled_symbol: str = "XAUUSD"
    base_timeframe: str = "1m"
    max_spread_points: float = 10.0
    mode: str = "SHADOW"
    execution_environment: str = "MT5_DEMO"
    live_execution: bool = False
    order_placement: bool = False

    @classmethod
    def from_env(cls) -> "ProjectAConfig":
        # 4999 is intentionally absent: it is the Session 3 TradingView CDP route.
        # Default to the existing safe listener while allowing an independent override.
        port_default = _integer("PORT", 8000, minimum=1)
        return cls(
            database_path=Path(os.getenv(
                "PROJECT_A_DB", str(ROOT / "storage" / "project_a.db"))),
            ingest_host=os.getenv("PROJECT_A_INGEST_HOST", "0.0.0.0"),
            ingest_port=_integer("PROJECT_A_INGEST_PORT", port_default, minimum=1),
            v1_ingest_enabled=_boolean("PROJECT_A_V1_INGEST_ENABLED", False),
            raw_producer_ingest_enabled=_boolean(
                "PROJECT_A_RAW_PRODUCER_INGEST_ENABLED", True),
            max_body_bytes=_integer("PROJECT_A_MAX_BODY_BYTES", 262_144, minimum=1),
            future_tolerance_seconds=_integer(
                "PROJECT_A_FUTURE_TOLERANCE_SECONDS", 5, minimum=0),
            stale_after_seconds=_integer(
                "PROJECT_A_STALE_AFTER_SECONDS", 1_800, minimum=1),
            claim_timeout_seconds=_integer(
                "PROJECT_A_CLAIM_TIMEOUT_SECONDS", 300, minimum=1),
            max_outbox_attempts=_integer(
                "PROJECT_A_MAX_OUTBOX_ATTEMPTS", 5, minimum=1),
        )

    def safety_errors(self) -> list[str]:
        checks = {
            "enabled_symbol": self.enabled_symbol == "XAUUSD",
            "base_timeframe": self.base_timeframe == "1m",
            "max_spread_points": self.max_spread_points == 10,
            "mode": self.mode == "SHADOW",
            "execution_environment": self.execution_environment == "MT5_DEMO",
            "live_execution": self.live_execution is False,
            "order_placement": self.order_placement is False,
            "capture_port_reserved": self.ingest_port != 4999,
        }
        return [name for name, safe in checks.items() if not safe]

    def assert_safe(self) -> None:
        errors = self.safety_errors()
        if errors:
            raise RuntimeError("unsafe Project A configuration: " + ", ".join(errors))
