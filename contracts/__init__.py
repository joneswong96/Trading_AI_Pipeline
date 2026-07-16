"""Frozen Project A contract registry and validation helpers."""

from .registry import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    EVENT_SCHEMA_V0_2,
    THESIS_SCHEMA_V1,
)
from .validation import ContractError, canonical_json, validate_contract

__all__ = [
    "AI_VERDICT_SCHEMA_V1",
    "ANALYSIS_REQUEST_SCHEMA_V1",
    "ContractError",
    "EVENT_SCHEMA_V0_2",
    "THESIS_SCHEMA_V1",
    "canonical_json",
    "validate_contract",
]
