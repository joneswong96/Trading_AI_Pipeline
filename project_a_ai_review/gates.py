"""Deterministic request preflight and verdict post-validation."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from contracts import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    ContractError,
    validate_contract,
)

from .errors import FailureCode, InputRejected, TechnicalFailure
from .hashing import bundle_hash, manifest_hash, sha256_file
from .models import DispatchEnvelope, ModelIdentity, RuntimePolicy
from .prompt import PROMPT_VERSION, evidence_reason_code


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TechnicalFailure(FailureCode.RR_FAILURE, f"{field} must be a finite number")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise TechnicalFailure(FailureCode.RR_FAILURE, f"{field} is not decimal-safe") from exc


def recompute_rr(direction: str, entry: Any, sl: Any, tp: Any, point_size: Any) -> dict:
    e, s, t, point = (
        _decimal(entry, "entry"),
        _decimal(sl, "sl"),
        _decimal(tp, "tp"),
        _decimal(point_size, "point_size"),
    )
    if point <= 0:
        raise TechnicalFailure(FailureCode.RR_FAILURE, "point_size must be positive")
    for name, value in (("entry", e), ("sl", s), ("tp", t)):
        if value <= 0 or value % point != 0:
            raise TechnicalFailure(
                FailureCode.RR_FAILURE,
                f"{name} is not aligned to authoritative point size {point}",
            )
    if direction == "LONG" and not (s < e < t):
        raise TechnicalFailure(FailureCode.RR_FAILURE, "LONG requires sl < entry < tp")
    if direction == "SHORT" and not (t < e < s):
        raise TechnicalFailure(FailureCode.RR_FAILURE, "SHORT requires tp < entry < sl")
    risk, reward = abs(e - s), abs(t - e)
    if risk <= 0 or reward <= 0 or risk != reward:
        raise TechnicalFailure(FailureCode.RR_FAILURE, "RR must be exactly 1:1")
    return {
        "entry": str(e),
        "risk_distance": str(risk),
        "reward_distance": str(reward),
        "ratio": "1:1",
        "point_size": str(point),
    }


def _resolve_artifact(root: Path, relative_path: str) -> Path:
    candidate_relative = Path(relative_path)
    if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
        raise InputRejected(FailureCode.ARTIFACT_PATH_REJECTED, "artifact path must be relative")
    root_resolved = root.resolve(strict=True)
    candidate = (root_resolved / candidate_relative).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise InputRejected(FailureCode.ARTIFACT_PATH_REJECTED, "artifact escapes trusted root") from exc
    return candidate


def preflight(dispatch: DispatchEnvelope, now: datetime, policy: RuntimePolicy) -> dict:
    request = dispatch.request
    try:
        validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
    except ContractError as exc:
        raise InputRejected(FailureCode.INPUT_SCHEMA_REJECTED, f"{exc.code} at {exc.path}") from exc
    if now.tzinfo is None:
        raise ValueError("trusted clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    created, expires = parse_utc(request["created_at"]), parse_utc(request["expires_at"])
    if (created - now).total_seconds() > policy.max_future_skew_seconds:
        raise InputRejected(FailureCode.INPUT_FUTURE_DATED, "request creation time is in the future")
    if now >= expires:
        raise InputRejected(FailureCode.INPUT_EXPIRED, "request expired before model invocation")
    if (now - created).total_seconds() > policy.max_request_age_seconds:
        raise InputRejected(FailureCode.INPUT_STALE, "request exceeded freshness limit")
    if request["instrument"]["venue"] != policy.expected_venue:
        raise InputRejected(FailureCode.INPUT_SCHEMA_REJECTED, "broker feed identity mismatch")

    manifest_doc = dispatch.manifest_document()
    calculated_manifest_hash = manifest_hash(manifest_doc)
    if calculated_manifest_hash != dispatch.artifact_manifest_hash:
        raise InputRejected(FailureCode.MANIFEST_HASH_MISMATCH, "artifact manifest hash mismatch")
    if bundle_hash(request, calculated_manifest_hash) != dispatch.bundle_hash:
        raise InputRejected(FailureCode.BUNDLE_HASH_MISMATCH, "bundle hash mismatch")

    ids = [artifact.evidence_id for artifact in dispatch.artifact_manifest]
    if len(ids) != len(set(ids)):
        raise InputRejected(FailureCode.REQUIRED_EVIDENCE_MISSING, "duplicate evidence ID")
    evidence_codes = [evidence_reason_code(evidence_id) for evidence_id in ids]
    if len(evidence_codes) != len(set(evidence_codes)):
        raise InputRejected(
            FailureCode.REQUIRED_EVIDENCE_MISSING,
            "evidence IDs collide after reason-code normalization",
        )
    if set(ids) != set(request["screenshots_required"]):
        raise InputRejected(
            FailureCode.REQUIRED_EVIDENCE_MISSING,
            "manifest evidence IDs must exactly match screenshots_required",
        )
    verified_paths: dict[str, str] = {}
    for artifact in dispatch.artifact_manifest:
        path = _resolve_artifact(dispatch.artifact_root, artifact.relative_path)
        if not path.is_file():
            raise InputRejected(FailureCode.ARTIFACT_MISSING, f"missing artifact {artifact.evidence_id}")
        stat = path.stat()
        if stat.st_size != artifact.size_bytes:
            raise InputRejected(
                FailureCode.ARTIFACT_SIZE_MISMATCH,
                f"artifact size mismatch for {artifact.evidence_id}",
            )
        if sha256_file(path) != artifact.sha256:
            raise InputRejected(
                FailureCode.ARTIFACT_HASH_MISMATCH,
                f"artifact hash mismatch for {artifact.evidence_id}",
            )
        verified_paths[artifact.evidence_id] = str(path)

    rr = recompute_rr(
        request["hypothesis"],
        request["entry_candidate"],
        request["sl_candidate"],
        request["tp_candidate"],
        request["instrument"]["point_size"],
    )
    return {
        "schema_valid": True,
        "symbol_valid": request["instrument"]["symbol"] == "XAUUSD",
        "feed_valid": True,
        "timeframe_valid": request["base_timeframe"] == "1m",
        "freshness_valid": True,
        "expiry_valid": True,
        "artifact_integrity_valid": True,
        "spread_valid": request["spread_points"] <= 10,
        "rr_valid": True,
        "environment_valid": request["risk"] == {
            "max_spread_points": 10,
            "rr": 1.0,
            "mode": "SHADOW",
            "execution_environment": "MT5_DEMO",
            "live_execution": False,
        },
        "rr_recomputation": rr,
        "verified_paths": verified_paths,
    }


def post_validate(
    candidate: dict,
    *,
    request: dict,
    manifest: dict,
    trusted_fields: dict,
    now: datetime,
    model: ModelIdentity,
) -> tuple[dict, dict]:
    try:
        validate_contract(AI_VERDICT_SCHEMA_V1, candidate)
    except ContractError as exc:
        raise TechnicalFailure(
            FailureCode.OUTPUT_SCHEMA_FAILURE,
            f"{exc.code} at {exc.path}",
        ) from exc

    repeated_identity_fields = (
        "request_id",
        "setup_id",
        "correlation_id",
        "causation_id",
    )
    for field in repeated_identity_fields:
        if candidate.get(field) != trusted_fields[field]:
            raise TechnicalFailure(FailureCode.IDENTIFIER_MISMATCH, f"{field} mismatch")
    if candidate["hypothesis"] != request["hypothesis"] or candidate["path"] != request["path"]:
        raise TechnicalFailure(FailureCode.IDENTIFIER_MISMATCH, "hypothesis or path mismatch")
    expected_model = {
        "provider": model.provider,
        "name": model.name,
        "prompt_version": PROMPT_VERSION,
        "mode": "SHADOW",
        "untrusted_input_handled": True,
    }
    if candidate["model"] != expected_model:
        raise TechnicalFailure(FailureCode.IDENTIFIER_MISMATCH, "model attribution mismatch")

    allowed_evidence = {
        evidence_reason_code(item["evidence_id"]) for item in manifest["artifacts"]
    }
    cited = {code for code in candidate["reason_codes"] if code.startswith("EVIDENCE_")}
    if not cited or not cited <= allowed_evidence:
        raise TechnicalFailure(
            FailureCode.EVIDENCE_REFERENCE_MISMATCH,
            "evidence references are missing or not present in the manifest",
        )

    expires = parse_utc(request["expires_at"])
    now = now.astimezone(timezone.utc)
    if candidate["verdict"] == "EXPIRED" and now < expires:
        raise TechnicalFailure(
            FailureCode.EXPIRY_FAILURE,
            "model cannot declare expiry before the trusted request deadline",
        )
    if now >= expires and candidate["verdict"] != "EXPIRED":
        raise TechnicalFailure(FailureCode.EXPIRY_FAILURE, "request expired during model review")
    if request["spread_points"] > 10:
        raise TechnicalFailure(FailureCode.SPREAD_FAILURE, "spread failed deterministic recheck")

    rr: dict | None = None
    if candidate["verdict"] in {"APPROVE", "MODIFY"}:
        valid_until = parse_utc(candidate["valid_until"])
        if valid_until > expires or valid_until <= now:
            raise TechnicalFailure(
                FailureCode.EXPIRY_FAILURE,
                "actionable validity must be active and cannot extend request expiry",
            )
        rr = recompute_rr(
            request["hypothesis"],
            candidate["entry"],
            candidate["sl"],
            candidate["tp"],
            request["instrument"]["point_size"],
        )
        if candidate["verdict"] == "APPROVE":
            original = (
                Decimal(str(request["entry_candidate"])),
                Decimal(str(request["sl_candidate"])),
                Decimal(str(request["tp_candidate"])),
            )
            approved = tuple(Decimal(str(candidate[key])) for key in ("entry", "sl", "tp"))
            if approved != original or candidate["valid_until"] != request["expires_at"]:
                raise TechnicalFailure(
                    FailureCode.MODIFY_SCOPE_FAILURE,
                    "APPROVE cannot alter geometry or validity",
                )

    trusted = dict(candidate)
    for field in ("verdict_id", *repeated_identity_fields, "generated_at"):
        trusted[field] = trusted_fields[field]
    trusted["hypothesis"] = request["hypothesis"]
    trusted["path"] = request["path"]
    trusted["model"] = expected_model
    gates = {
        "schema_valid": True,
        "identifiers_valid": True,
        "evidence_references_valid": True,
        "expiry_valid": now < expires or candidate["verdict"] == "EXPIRED",
        "spread_valid": True,
        "symbol_valid": request["instrument"]["symbol"] == "XAUUSD",
        "timeframe_valid": request["base_timeframe"] == "1m",
        "environment_valid": request["risk"]["mode"] == "SHADOW"
        and request["risk"]["execution_environment"] == "MT5_DEMO"
        and request["risk"]["live_execution"] is False,
        "rr_recomputation": rr,
        "modify_scope_valid": True,
    }
    return trusted, gates
