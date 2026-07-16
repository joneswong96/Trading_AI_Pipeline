"""Pinned names and files for the frozen Project A contracts."""
from __future__ import annotations

from pathlib import Path

EVENT_SCHEMA_V0_2 = "EVENT_SCHEMA_V0_2"
ANALYSIS_REQUEST_SCHEMA_V1 = "ANALYSIS_REQUEST_SCHEMA_V1"
AI_VERDICT_SCHEMA_V1 = "AI_VERDICT_SCHEMA_V1"
THESIS_SCHEMA_V1 = "THESIS_SCHEMA_V1"

SCHEMA_DIR = Path(__file__).with_name("schemas")
SCHEMA_FILES = {
    EVENT_SCHEMA_V0_2: SCHEMA_DIR / "event_schema_v0_2.json",
    ANALYSIS_REQUEST_SCHEMA_V1: SCHEMA_DIR / "analysis_request_schema_v1.json",
    AI_VERDICT_SCHEMA_V1: SCHEMA_DIR / "ai_verdict_schema_v1.json",
    THESIS_SCHEMA_V1: SCHEMA_DIR / "thesis_schema_v1.json",
}


def schema_path(contract: str) -> Path:
    try:
        return SCHEMA_FILES[contract]
    except KeyError as exc:
        raise KeyError(f"unsupported contract: {contract}") from exc
