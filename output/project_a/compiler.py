"""Strict Session 4 handoff and deterministic frozen-schema Thesis compiler."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from contracts import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    THESIS_SCHEMA_V1,
    validate_contract,
)

from .config import OutputConfig
from .models import RendererType, Session5Error, document_hash, parse_utc, stable_id


@dataclass(frozen=True)
class InputAttestation:
    """Narrow Session 4 boundary; no queue/table/filesystem assumption is embedded."""

    post_gates_passed: bool
    audit_persisted: bool
    audit_ref: str

    def validate(self) -> None:
        if not self.post_gates_passed:
            raise Session5Error("post_gates_required", "Session 4 deterministic post-gates did not pass")
        if not self.audit_persisted or not self.audit_ref.strip():
            raise Session5Error("audit_reference_required", "a persisted verdict audit reference is required")
        if len(self.audit_ref) > 500:
            raise Session5Error("audit_reference_invalid", "audit reference is too long")


class ThesisCompiler:
    def __init__(self, store, config: OutputConfig):
        self.store = store
        self.config = config

    def compile(
        self,
        request: dict,
        verdict: dict,
        attestation: InputAttestation,
        *,
        now: datetime,
    ) -> dict:
        attestation.validate()
        validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
        validate_contract(AI_VERDICT_SCHEMA_V1, verdict)
        self._validate_pair(request, verdict, now)

        request_hash = document_hash(request)
        verdict_hash = document_hash(verdict)
        thesis_id = stable_id("thesis", request["setup_id"], request_hash, verdict_hash)
        actionable = verdict["verdict"] in {"APPROVE", "MODIFY"}
        thesis = {
            "schema_version": "1.0",
            "thesis_id": thesis_id,
            "version": 1,
            "request_id": request["request_id"],
            "verdict_id": verdict["verdict_id"],
            "setup_id": request["setup_id"],
            "correlation_id": request["correlation_id"],
            "causation_id": verdict["verdict_id"],
            "created_at": verdict["generated_at"],
            "valid_until": verdict["valid_until"] if actionable else None,
            "decision": verdict["verdict"],
            "state": ({"APPROVE": "ARMED", "MODIFY": "ARMED", "REJECT": "WAIT",
                       "EXPIRED": "EXPIRED"})[verdict["verdict"]],
            "instrument": request["instrument"],
            "direction": verdict["hypothesis"],
            "path": verdict["path"],
            "entry": verdict["entry"] if actionable else None,
            "sl": verdict["sl"] if actionable else None,
            "tp": verdict["tp"] if actionable else None,
            "invalidation": verdict["sl"] if actionable else None,
            "rr": 1.0,
            "mode": "SHADOW",
            "execution_environment": "MT5_DEMO",
            "live_execution": False,
            "rationale": verdict["rationale"],
            "provenance": {
                "compiler": "project-a-session-5",
                "contract": "THESIS_SCHEMA_V1",
                "source_verdict_id": verdict["verdict_id"],
            },
        }
        validate_contract(THESIS_SCHEMA_V1, thesis)

        renderers = [RendererType.TELEGRAM.value, RendererType.NOTION.value]
        if actionable:
            renderers = [RendererType.TRADINGVIEW.value, *renderers, RendererType.MT5_DEMO.value]
        renderers = [name for name in renderers if name in self.config.enabled_renderers]
        return self.store.create_thesis_and_deliveries(
            thesis=thesis,
            request=request,
            verdict=verdict,
            audit_ref=attestation.audit_ref,
            renderer_types=renderers,
            now=now,
        )

    @staticmethod
    def _validate_pair(request: dict, verdict: dict, now: datetime) -> None:
        checks = {
            "request_id": verdict["request_id"] == request["request_id"],
            "setup_id": verdict["setup_id"] == request["setup_id"],
            "correlation_id": verdict["correlation_id"] == request["correlation_id"],
            "causation_id": verdict["causation_id"] == request["request_id"],
            "hypothesis": verdict["hypothesis"] == request["hypothesis"],
            "path": verdict["path"] == request["path"],
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise Session5Error("identity_mismatch", ", ".join(failed))
        if request["causation_id"] not in request["source_event_ids"]:
            raise Session5Error("source_identity_mismatch", "request causation event is not in source_event_ids")
        if parse_utc(request["expires_at"]) <= now:
            raise Session5Error("request_expired", "analysis request has expired")
        generated = parse_utc(verdict["generated_at"])
        if generated < parse_utc(request["created_at"]) or generated > parse_utc(request["expires_at"]):
            raise Session5Error("verdict_time_invalid", "verdict is outside the request lifetime")
        if verdict["valid_until"] is not None:
            valid_until = parse_utc(verdict["valid_until"])
            if valid_until <= now:
                raise Session5Error("verdict_expired", "verdict has expired")
            if valid_until > parse_utc(request["expires_at"]):
                raise Session5Error("verdict_expiry_widened", "verdict cannot outlive the request")
