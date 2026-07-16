"""Bounded strict model-output parsing with no prose or duplicate keys."""
from __future__ import annotations

import json
from typing import Any

from .errors import FailureCode, TechnicalFailure


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise TechnicalFailure(
                FailureCode.MALFORMED_MODEL_OUTPUT,
                f"duplicate JSON key rejected: {key}",
            )
        out[key] = value
    return out


def parse_model_json(raw: str, *, max_bytes: int = 65_536) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise TechnicalFailure(FailureCode.MALFORMED_MODEL_OUTPUT, "model output is not text")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise TechnicalFailure(FailureCode.MALFORMED_MODEL_OUTPUT, "invalid UTF-8 output") from exc
    if not raw.strip():
        raise TechnicalFailure(FailureCode.MALFORMED_MODEL_OUTPUT, "model output is empty")
    if size > max_bytes:
        raise TechnicalFailure(
            FailureCode.MALFORMED_MODEL_OUTPUT,
            f"model output exceeds {max_bytes} bytes",
        )
    stripped = raw.strip()
    if stripped.startswith("```") or "```" in stripped:
        raise TechnicalFailure(FailureCode.MALFORMED_MODEL_OUTPUT, "code fences are forbidden")
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise TechnicalFailure(
            FailureCode.MALFORMED_MODEL_OUTPUT,
            "exactly one JSON object with no surrounding prose is required",
        )
    try:
        value = json.loads(
            stripped,
            object_pairs_hook=_no_duplicate_object,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except TechnicalFailure:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise TechnicalFailure(FailureCode.MALFORMED_MODEL_OUTPUT, "invalid JSON object") from exc
    if not isinstance(value, dict):
        raise TechnicalFailure(FailureCode.MALFORMED_MODEL_OUTPUT, "top-level JSON must be object")
    return value
