"""Deterministic reference for the default-off Project A Pine Wire V1 surface.

This is a test/fixture utility only. It mirrors the corrected Session 1
producer boundary: telemetry and evidence-supported Setup Candidate events are
allowed, while trusted receipt data, hashes, dedupe, lifecycle authority, and
Analysis Ready semantics remain outside Pine.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

Direction = Literal["UP", "DOWN", "NEUTRAL"]
TargetSide = Literal["SUPPORT", "RESISTANCE"]

SOURCE_COMMIT = "2389d4cf29701bf79a1c349a872988bf3216a3d7"
SOURCE_BLOB = "02f5ac79b22af8819e27b8d5b0924d748ea69ad8"
SOURCE_LEGACY_SHA256 = "4840f60cb1b4b034304e23d92ba3c40df4e45fbf2abc4b6f51adc2a250b1ca78"


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or not value.endswith("Z"):
        raise ValueError("timestamps must be ISO 8601 UTC ending in Z")
    return value


def _compact_time(value: str) -> str:
    parsed = datetime.fromisoformat(_utc(value).replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _price_ticks(price: float, point_size: float) -> int:
    return round(price / point_size)


@dataclass(frozen=True)
class Evidence:
    occurred_at: str
    emitted_at: str
    close: float
    expansion_new_up: bool = False
    expansion_new_down: bool = False
    snr_low: float | None = None
    snr_high: float | None = None
    target_side: TargetSide | None = None
    level_eligible: bool = False
    level_changed: bool = False
    symbol: str = "XAUUSD"
    timeframe: str = "1m"
    point_size: float = 0.01

    def validate(self) -> None:
        occurred = datetime.fromisoformat(_utc(self.occurred_at).replace("Z", "+00:00"))
        emitted = datetime.fromisoformat(_utc(self.emitted_at).replace("Z", "+00:00"))
        if emitted < occurred:
            raise ValueError("emitted_at cannot precede occurred_at")
        if self.symbol != "XAUUSD" or self.timeframe != "1m":
            raise ValueError("Project A Wire V1 is pinned to XAUUSD/1m")
        if (self.snr_low is None) != (self.snr_high is None):
            raise ValueError("SNR bounds must both be present or both be absent")
        if self.snr_low is not None and self.snr_low > self.snr_high:
            raise ValueError("snr_low must be <= snr_high")


class ProjectASensor:
    """Default-off, fact-only Session 1 producer reference."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._last_fingerprint: tuple[Any, ...] | None = None

    @staticmethod
    def _candidate_side(evidence: Evidence) -> TargetSide | None:
        unambiguous_down = evidence.expansion_new_down and not evidence.expansion_new_up
        unambiguous_up = evidence.expansion_new_up and not evidence.expansion_new_down
        if (
            evidence.level_eligible
            and evidence.target_side == "SUPPORT"
            and unambiguous_down
            and evidence.snr_low is not None
        ):
            return "SUPPORT"
        if (
            evidence.level_eligible
            and evidence.target_side == "RESISTANCE"
            and unambiguous_up
            and evidence.snr_low is not None
        ):
            return "RESISTANCE"
        return None

    @staticmethod
    def _empty_evidence(snr: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "snr": snr,
            "hpa": [],
            "momentum": [],
            "trigger": None,
            "rejection": None,
            "break": None,
            "invalidation": None,
            "expiry": None,
            "entry_window": None,
            "geometry": None,
        }

    def observe(self, evidence: Evidence) -> dict[str, Any] | None:
        evidence.validate()
        if not self.enabled:
            return None

        side = self._candidate_side(evidence)
        is_candidate = side is not None
        has_event = (
            is_candidate
            or evidence.expansion_new_up
            or evidence.expansion_new_down
            or evidence.level_changed
        )
        if not has_event:
            return None

        event_class = "SETUP_CANDIDATE" if is_candidate else "TELEMETRY"
        event_type = (
            "SETUP_CANDIDATE"
            if is_candidate
            else "EXPANSION_UPDATE"
            if evidence.expansion_new_up or evidence.expansion_new_down
            else "SNR_UPDATE"
        )
        bounds = (
            evidence.snr_low,
            evidence.snr_high,
        ) if is_candidate else (None, None)
        fingerprint = (event_type, evidence.occurred_at, side, *bounds)
        if fingerprint == self._last_fingerprint:
            return None
        self._last_fingerprint = fingerprint

        setup_origin = None
        snr = None
        correlation_id = None
        if is_candidate:
            assert side is not None
            assert evidence.snr_low is not None and evidence.snr_high is not None
            code = "S" if side == "SUPPORT" else "R"
            suffix = (
                f"XAUUSD_1m_{code}_"
                f"{_price_ticks(evidence.snr_low, evidence.point_size)}_"
                f"{_price_ticks(evidence.snr_high, evidence.point_size)}"
            )
            snr = {
                "identity": f"snr_{suffix}",
                "type": "LEVEL_ENGINE",
                "low": evidence.snr_low,
                "high": evidence.snr_high,
                "side": side,
            }
            setup_origin = {
                "origin_id": f"origin_{suffix}",
                "aoi_id": f"aoi_{suffix}",
            }
            correlation_id = f"corr_{suffix}"

        return {
            "contract_family": "PROJECT_A_WIRE_EVENT",
            "schema_version": "1.0",
            "producer_event_id": (
                f"wevt_XAUUSD_1m_{_compact_time(evidence.occurred_at)}_{event_type}"
            ),
            "correlation_id": correlation_id,
            "causation_id": None,
            "occurred_at": evidence.occurred_at,
            "emitted_at": evidence.emitted_at,
            "source": {
                "producer": "snr-dashboard-project-a-v1",
                "profile": "project-a-shadow",
                "version": "1.0.0",
                "producer_checksum": None,
                "diagnostics": {"build_note": "immutable-export-2389d4c"},
            },
            "symbol": "XAUUSD",
            "base_tf": "1m",
            "mode": "SHADOW",
            "execution_environment": "MT5_DEMO",
            "live_execution": False,
            "event_class": event_class,
            "event_type": event_type,
            "hypothesis": None,
            "path": None,
            "setup_origin": setup_origin,
            "evidence": self._empty_evidence(snr),
            "extensions": {},
        }


def sample_sequence() -> dict[str, dict[str, Any]]:
    """Return deterministic Wire V1 engineering fixtures."""
    base = Evidence(
        occurred_at="2026-07-16T00:00:00Z",
        emitted_at="2026-07-16T00:00:01Z",
        close=2420.0,
        level_changed=True,
    )
    telemetry = ProjectASensor(enabled=True).observe(base)
    support = ProjectASensor(enabled=True).observe(
        replace(
            base,
            occurred_at="2026-07-16T00:01:00Z",
            emitted_at="2026-07-16T00:01:01Z",
            close=2420.1,
            expansion_new_down=True,
            snr_low=2419.5,
            snr_high=2420.0,
            target_side="SUPPORT",
            level_eligible=True,
            level_changed=False,
        )
    )
    resistance = ProjectASensor(enabled=True).observe(
        replace(
            base,
            occurred_at="2026-07-16T00:02:00Z",
            emitted_at="2026-07-16T00:02:01Z",
            close=2424.8,
            expansion_new_up=True,
            snr_low=2424.5,
            snr_high=2425.0,
            target_side="RESISTANCE",
            level_eligible=True,
            level_changed=False,
        )
    )
    ambiguous = ProjectASensor(enabled=True).observe(
        replace(
            base,
            occurred_at="2026-07-16T00:03:00Z",
            emitted_at="2026-07-16T00:03:01Z",
            expansion_new_up=True,
            expansion_new_down=True,
            snr_low=2421.0,
            snr_high=2422.0,
            target_side="SUPPORT",
            level_eligible=True,
            level_changed=False,
        )
    )
    assert all(item is not None for item in (telemetry, support, resistance, ambiguous))
    return {
        "telemetry": telemetry,
        "support_setup_candidate": support,
        "resistance_setup_candidate": resistance,
        "ambiguous_expansion_telemetry": ambiguous,
    }
