"""Offline deterministic replay and disabled release gate for stored bundles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from contracts import ANALYSIS_REQUEST_SCHEMA_V1, canonical_json, validate_contract

from .artifacts import verify_manifest, write_json_immutable
from .compiler import compile_analysis_request
from .errors import Session3Error
from .input_boundary import parse_utc, utc_z, validate_analysis_ready
from .profile import CaptureProfile


def release_decision(request: dict, manifest: dict, *, at: datetime) -> dict:
    at = at.astimezone(timezone.utc)
    expires = parse_utc(request["expires_at"], "expires_at")
    if at >= expires:
        return {
            "status": "EXPIRED_RETAINED",
            "release_to_session_4": False,
            "checked_at": utc_z(at),
            "reason": "original adapter authority expired",
            "runtime_activation_gate": "SESSION_3_REAL_4999_CAPTURE",
        }
    if manifest.get("synthetic") is True:
        return {
            "status": "SYNTHETIC_RETAINED",
            "release_to_session_4": False,
            "checked_at": utc_z(at),
            "reason": "synthetic fixture is replay evidence only",
            "runtime_activation_gate": "SESSION_3_REAL_4999_CAPTURE",
        }
    return {
        "status": "RUNTIME_ACTIVATION_PENDING",
        "release_to_session_4": False,
        "checked_at": utc_z(at),
        "reason": "real browser release remains disabled until Runtime Activation",
        "runtime_activation_gate": "SESSION_3_REAL_4999_CAPTURE",
    }


def write_bundle(bundle_dir: str | Path, *, canonical_event: dict,
                 analysis_adapter: dict, manifest: dict,
                 request: dict, release_at: datetime) -> Path:
    root = Path(bundle_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    write_json_immutable(root / "source_canonical_event.json", canonical_event)
    write_json_immutable(root / "source_adapter_output.json", analysis_adapter)
    write_json_immutable(root / "manifest.json", manifest)
    write_json_immutable(root / "analysis_request.json", request)
    write_json_immutable(root / "release.json", release_decision(request, manifest, at=release_at))
    return root


def replay_bundle(bundle_dir: str | Path, profile: CaptureProfile,
                  *, replay_at: datetime | None = None) -> dict:
    root = Path(bundle_dir).resolve()
    canonical_event = json.loads((root / "source_canonical_event.json").read_text(encoding="utf-8"))
    analysis_adapter = json.loads((root / "source_adapter_output.json").read_text(encoding="utf-8"))
    request = json.loads((root / "analysis_request.json").read_text(encoding="utf-8"))
    manifest = verify_manifest(root / "manifest.json")
    authority = validate_analysis_ready(
        canonical_event,
        analysis_adapter,
        require_compiler_fields=True,
    )
    validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
    if manifest["canonical_event_id"] != authority.canonical_event_id:
        raise Session3Error("CANONICAL_LINEAGE_INVALID", "bundle manifest canonical identity differs")
    created = parse_utc(request["created_at"], "created_at")
    rebuilt = compile_analysis_request(
        canonical_event,
        analysis_adapter,
        manifest,
        profile,
        created_at=created,
    )
    if canonical_json(rebuilt) != canonical_json(request):
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "offline recompilation differs from stored request")
    at = replay_at or created
    return {
        "ok": True,
        "request_id": request["request_id"],
        "canonical_event_id": authority.canonical_event_id,
        "canonical_content_hash": authority.canonical_content_hash,
        "semantic_evidence_hash": authority.semantic_evidence_hash,
        "receipt_id": authority.receipt_id,
        "raw_content_hash": authority.raw_content_hash,
        "analysis_adapter_hash": authority.adapter_output_hash,
        "canonical_request": canonical_json(request),
        "artifact_count": len(manifest["artifacts"]),
        "evidence_classification": manifest["evidence_classification"],
        "runtime_compatibility_claim": manifest["runtime_compatibility_claim"],
        "release": release_decision(request, manifest, at=at),
        "network_used": False,
        "browser_used": False,
        "ai_used": False,
    }
