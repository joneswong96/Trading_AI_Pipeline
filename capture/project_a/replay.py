"""Offline deterministic replay and release gate for stored bundles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from contracts import ANALYSIS_REQUEST_SCHEMA_V1, EVENT_SCHEMA_V0_2, canonical_json, validate_contract

from .artifacts import verify_manifest, write_json_immutable
from .compiler import compile_analysis_request
from .errors import Session3Error
from .input_boundary import parse_utc, utc_z
from .profile import CaptureProfile


def release_decision(request: dict, *, at: datetime) -> dict:
    at = at.astimezone(timezone.utc)
    expires = parse_utc(request["expires_at"], "expires_at")
    if at >= expires:
        return {
            "status": "EXPIRED_RETAINED",
            "release_to_session_4": False,
            "checked_at": utc_z(at),
            "reason": "original request authority expired",
        }
    return {
        "status": "READY",
        "release_to_session_4": True,
        "checked_at": utc_z(at),
        "reason": "contract, integrity and expiry gates passed",
    }


def write_bundle(bundle_dir: str | Path, *, event: dict, manifest: dict,
                 request: dict, release_at: datetime) -> Path:
    root = Path(bundle_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    write_json_immutable(root / "source_event.json", event)
    write_json_immutable(root / "manifest.json", manifest)
    write_json_immutable(root / "analysis_request.json", request)
    write_json_immutable(root / "release.json", release_decision(request, at=release_at))
    return root


def replay_bundle(bundle_dir: str | Path, profile: CaptureProfile, *, replay_at: datetime | None = None) -> dict:
    root = Path(bundle_dir).resolve()
    event = json.loads((root / "source_event.json").read_text(encoding="utf-8"))
    request = json.loads((root / "analysis_request.json").read_text(encoding="utf-8"))
    manifest = verify_manifest(root / "manifest.json")
    validate_contract(EVENT_SCHEMA_V0_2, event)
    validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
    created = parse_utc(request["created_at"], "created_at")
    rebuilt = compile_analysis_request(event, manifest, profile, created_at=created)
    if canonical_json(rebuilt) != canonical_json(request):
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "offline recompilation differs from stored request")
    at = replay_at or created
    return {
        "ok": True,
        "request_id": request["request_id"],
        "canonical_request": canonical_json(request),
        "artifact_count": len(manifest["artifacts"]),
        "release": release_decision(request, at=at),
        "network_used": False,
        "browser_used": False,
        "ai_used": False,
    }
