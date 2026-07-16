"""Pure deterministic compiler for frozen ANALYSIS_REQUEST_SCHEMA_V1."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone

from contracts import ANALYSIS_REQUEST_SCHEMA_V1, ContractError, canonical_json, validate_contract

from .artifacts import verify_manifest
from .errors import Session3Error
from .input_boundary import AnalysisAuthority, parse_utc, utc_z, validate_analysis_ready
from .profile import CaptureProfile

COMPILER_NAME = "project-a-session-3"
COMPILER_VERSION = "1.0.0"


def _capture_mode(value: str) -> str:
    mapping = {
        "FIXTURE": "FIXTURE",
        "TRADINGVIEW_MCP": "TRADINGVIEW_MCP",
        "SCREENSHOT": "SCREENSHOT",
        "PROJECT_A_CDP": "TRADINGVIEW_MCP",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", f"unsupported capture method {value!r}") from exc


def _validated_artifacts(manifest: dict, profile: CaptureProfile) -> list[dict]:
    if manifest.get("status") != "COMPLETE" or manifest.get("failure") is not None:
        raise Session3Error("PARTIAL_CAPTURE", "only a complete, failure-free manifest can compile")
    if manifest.get("port") != 4999 or manifest.get("symbol") != profile.symbol:
        raise Session3Error("PORT_MISMATCH", "manifest route identity differs from profile")
    if manifest.get("broker_feed") != profile.broker_feed:
        raise Session3Error("WRONG_FEED", "manifest feed differs from profile")
    if manifest.get("restored_base_timeframe") is not True:
        raise Session3Error("WRONG_TIMEFRAME", "manifest does not prove 1m restoration")
    by_tf: dict[str, dict] = {}
    for record in manifest.get("artifacts", []):
        tf = record.get("requested_timeframe")
        if tf in by_tf:
            raise Session3Error("PARTIAL_CAPTURE", f"duplicate artifact for {tf}")
        if record.get("observed_timeframe") != tf or not all(record.get("verification", {}).values()):
            raise Session3Error("WRONG_TIMEFRAME", f"unverified artifact for {tf}")
        by_tf[tf] = record
    missing = [tf for tf in profile.required_timeframes if tf not in by_tf]
    if missing:
        raise Session3Error("MISSING_TIMEFRAME", "manifest missing: " + ", ".join(missing))
    return [by_tf[tf] for tf in profile.required_timeframes]


def _request_id(authority: AnalysisAuthority, manifest: dict,
                profile: CaptureProfile, created_at: datetime) -> str:
    del created_at  # clock is already frozen in manifest.started_at
    seed = canonical_json({
        "dispatch_id": manifest["dispatch_id"],
        "event_id": authority.event_id,
        "retry_count": manifest["retry_count"],
        "started_at": manifest["started_at"],
        "profile": profile.identity_dict(),
    }).encode("utf-8")
    expected = "req_" + hashlib.sha256(b"request\0" + seed).hexdigest()[:40]
    if manifest.get("request_id") != expected:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "manifest request_id is not deterministic for its stable inputs")
    return expected


def compile_analysis_request(event: dict, manifest: dict, profile: CaptureProfile,
                             *, created_at: datetime) -> dict:
    profile.validate()
    authority = validate_analysis_ready(event, require_compiler_fields=True)
    created_at = created_at.astimezone(timezone.utc)
    authority.ensure_unexpired(created_at)
    analysis = authority.require_compiler_fields()
    if manifest.get("source_event_id") != authority.event_id or manifest.get("setup_id") != authority.setup_id:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "manifest/source stable identifiers do not match")
    if manifest.get("finished_at") and parse_utc(manifest["finished_at"], "manifest.finished_at") >= authority.expires_at:
        raise Session3Error("SOURCE_EXPIRED", "capture finished at or after the original expiry")
    records = _validated_artifacts(manifest, profile)
    source_ids = sorted(set(analysis["source_event_ids"]) | {authority.event_id})
    screenshot_refs = [f"{record['requested_timeframe']}:sha256:{record['sha256']}" for record in records]
    request = {
        "schema_version": "1.0",
        "request_id": _request_id(authority, manifest, profile, created_at),
        "setup_id": authority.setup_id,
        "correlation_id": authority.correlation_id,
        "causation_id": authority.event_id,
        "created_at": utc_z(created_at),
        "expires_at": analysis["expires_at"],
        "instrument": deepcopy(event["instrument"]),
        "hypothesis": event["hypothesis"],
        "path": event["path"],
        "base_timeframe": event["timeframe"],
        "session": analysis["session"],
        "snr": deepcopy(analysis["snr"]),
        "hpa": deepcopy(analysis["hpa"]),
        "momentum": deepcopy(analysis["momentum"]),
        "trigger_price": analysis["trigger_price"],
        "spread_points": analysis["spread_points"],
        "entry_candidate": analysis["entry_candidate"],
        "sl_candidate": analysis["sl_candidate"],
        "tp_candidate": analysis["tp_candidate"],
        "risk": {
            "max_spread_points": 10,
            "rr": 1.0,
            "mode": "SHADOW",
            "execution_environment": "MT5_DEMO",
            "live_execution": False,
        },
        "screenshots_required": screenshot_refs,
        "source_event_ids": source_ids,
        "provenance": {
            "compiler": COMPILER_NAME,
            "compiler_version": COMPILER_VERSION,
            "capture_mode": _capture_mode(manifest["capture_method"]),
            "port": 4999,
            "symbol_verified": True,
            "timeframe_verified": True,
        },
    }
    try:
        validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
    except ContractError as exc:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", str(exc)) from exc
    return request


def compile_from_manifest_path(event: dict, manifest_path, profile: CaptureProfile,
                               *, created_at: datetime) -> dict:
    manifest = verify_manifest(manifest_path)
    return compile_analysis_request(event, manifest, profile, created_at=created_at)
