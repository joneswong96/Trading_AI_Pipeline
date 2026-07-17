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
COMPILER_VERSION = "1.1.0"


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
    if manifest.get("runtime_compatibility_claim") != "NONE" or manifest.get("release_enabled") is not False:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "offline manifest cannot claim runtime compatibility or release")
    by_tf: dict[str, dict] = {}
    for record in manifest.get("artifacts", []):
        tf = record.get("requested_timeframe")
        if tf in by_tf:
            raise Session3Error("PARTIAL_CAPTURE", f"duplicate artifact for {tf}")
        if record.get("observed_timeframe") != tf or not all(record.get("verification", {}).values()):
            raise Session3Error("WRONG_TIMEFRAME", f"unverified artifact for {tf}")
        if record.get("synthetic") is not manifest.get("synthetic"):
            raise Session3Error("CONTRACT_COMPILATION_FAILURE", f"artifact evidence label differs for {tf}")
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
        "source_event_id": authority.event_id,
        "producer_event_id": authority.producer_event_id,
        "canonical_event_id": authority.canonical_event_id,
        "canonical_content_hash": authority.canonical_content_hash,
        "semantic_evidence_hash": authority.semantic_evidence_hash,
        "receipt_id": authority.receipt_id,
        "raw_content_hash": authority.raw_content_hash,
        "analysis_adapter_hash": authority.adapter_output_hash,
        "retry_count": manifest["retry_count"],
        "started_at": manifest["started_at"],
        "profile": profile.identity_dict(),
    }).encode("utf-8")
    expected = "req_" + hashlib.sha256(b"request\0" + seed).hexdigest()[:40]
    if manifest.get("request_id") != expected:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "manifest request_id is not deterministic for its stable inputs")
    return expected


def compile_analysis_request(canonical_event: dict, analysis_adapter: dict, manifest: dict,
                             profile: CaptureProfile, *, created_at: datetime) -> dict:
    profile.validate()
    authority = validate_analysis_ready(
        canonical_event,
        analysis_adapter,
        require_compiler_fields=True,
    )
    created_at = created_at.astimezone(timezone.utc)
    authority.ensure_unexpired(created_at)
    analysis = authority.require_compiler_fields()
    expected_lineage = {
        "source_event_id": authority.event_id,
        "producer_event_id": authority.producer_event_id,
        "canonical_event_id": authority.canonical_event_id,
        "canonical_content_hash": authority.canonical_content_hash,
        "semantic_evidence_hash": authority.semantic_evidence_hash,
        "setup_id": authority.setup_id,
        "receipt_id": authority.receipt_id,
        "raw_content_hash": authority.raw_content_hash,
        "immutable_raw_reference": authority.immutable_raw_reference,
        "analysis_adapter_hash": authority.adapter_output_hash,
    }
    if any(manifest.get(key) != value for key, value in expected_lineage.items()):
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "manifest canonical/receipt lineage does not match")
    records = _validated_artifacts(manifest, profile)
    finished_at = parse_utc(manifest["finished_at"], "manifest.finished_at") if manifest.get("finished_at") else None
    if finished_at and finished_at >= authority.expires_at:
        raise Session3Error("SOURCE_EXPIRED", "capture finished at or after the original expiry")
    if finished_at and created_at < finished_at:
        raise Session3Error("CONTRACT_COMPILATION_FAILURE", "request creation precedes capture completion")
    source_ids = [authority.event_id]
    screenshot_refs = [f"{record['requested_timeframe']}:sha256:{record['sha256']}" for record in records]
    request = {
        "schema_version": "1.0",
        "request_id": _request_id(authority, manifest, profile, created_at),
        "setup_id": authority.setup_id,
        "correlation_id": authority.correlation_id,
        "causation_id": authority.event_id,
        "created_at": utc_z(created_at),
        "expires_at": analysis["expires_at"],
        "instrument": deepcopy(analysis["instrument"]),
        "hypothesis": authority.wire_event["hypothesis"],
        "path": authority.wire_event["path"],
        "base_timeframe": authority.wire_event["base_tf"],
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


def compile_from_manifest_path(canonical_event: dict, analysis_adapter: dict,
                               manifest_path, profile: CaptureProfile,
                               *, created_at: datetime) -> dict:
    manifest = verify_manifest(manifest_path)
    return compile_analysis_request(
        canonical_event,
        analysis_adapter,
        manifest,
        profile,
        created_at=created_at,
    )
