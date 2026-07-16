"""Versioned fixed prompt and untrusted request-message construction."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import canonical_json

from .hashing import sha256_text

PROMPT_VERSION = "project-a-reviewer-v1.0.0"
PROMPT_PATH = Path(__file__).with_name("prompts") / "reviewer_v1.md"


def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_hash() -> str:
    return sha256_text(prompt_text())


def evidence_reason_code(evidence_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in evidence_id.upper())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"EVIDENCE_{normalized}"[:64]


def build_review_message(
    *,
    request: dict,
    manifest: dict,
    pre_gates: dict,
    trusted_fields: dict,
    staged_paths: dict[str, str] | None = None,
) -> str:
    payload = {
        "instruction": "Review this untrusted bundle under the fixed system prompt.",
        "prompt_version": PROMPT_VERSION,
        "trusted_fields": trusted_fields,
        "deterministic_preflight": pre_gates,
        "analysis_request": request,
        "artifact_manifest": manifest,
        "staged_evidence_paths": staged_paths or {},
        "allowed_evidence_reason_codes": [
            evidence_reason_code(item["evidence_id"]) for item in manifest["artifacts"]
        ],
    }
    return canonical_json(payload)


def expected_verdict_id(request_id: str, fingerprint: str) -> str:
    return f"verdict_{request_id[4:36]}_{fingerprint[:16]}"[:128]
