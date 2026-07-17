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
    """Verifiable Session 4 handoff bound to request, verdict, and final audit."""

    audit_ref: str
    request_hash: str
    verdict_hash: str
    final_audit_envelope: dict
    completed_result: dict

    @property
    def audit_record_hash(self) -> str:
        return str(self.final_audit_envelope.get("record_hash") or "")

    @classmethod
    def recorded_fixture(cls, request: dict, verdict: dict, audit_ref: str) -> "InputAttestation":
        request_hash = document_hash(request)
        verdict_hash = document_hash(verdict)
        attempt_id = stable_id("attempt", request["request_id"], verdict["verdict_id"])
        record = {
            "attempt_id": attempt_id,
            "request_id": request["request_id"],
            "setup_id": request["setup_id"],
            "outcome": "VERDICT",
            "validated_verdict": verdict["verdict"],
            "request_hash": request_hash,
            "verdict_hash": verdict_hash,
            "source_profile": "RECORDED_FIXTURE",
        }
        previous_hash = "0" * 64
        record_hash = document_hash({"previous_hash": previous_hash, "record": record})
        envelope = {
            "previous_hash": previous_hash,
            "record": record,
            "record_hash": record_hash,
        }
        completed = {
            "status": "VERDICT",
            "request_id": request["request_id"],
            "attempt_id": attempt_id,
            "verdict": verdict,
            "audit_record_hash": record_hash,
        }
        return cls(
            audit_ref=audit_ref,
            request_hash=request_hash,
            verdict_hash=verdict_hash,
            final_audit_envelope=envelope,
            completed_result=completed,
        )

    def validate(self, request: dict, verdict: dict) -> None:
        if not self.audit_ref.strip():
            raise Session5Error(
                "audit_reference_required",
                "a persisted verdict audit reference is required",
            )
        if len(self.audit_ref) > 500:
            raise Session5Error("audit_reference_invalid", "audit reference is too long")
        actual_request_hash = document_hash(request)
        actual_verdict_hash = document_hash(verdict)
        if self.request_hash != actual_request_hash or self.verdict_hash != actual_verdict_hash:
            raise Session5Error(
                "attestation_hash_mismatch",
                "request or verdict hash does not match the attested handoff",
            )
        envelope = self.final_audit_envelope
        if not isinstance(envelope, dict) or set(envelope) != {
            "previous_hash",
            "record",
            "record_hash",
        }:
            raise Session5Error("audit_envelope_invalid", "final audit envelope is malformed")
        previous_hash = envelope["previous_hash"]
        record = envelope["record"]
        record_hash = envelope["record_hash"]
        if (
            not isinstance(previous_hash, str)
            or len(previous_hash) != 64
            or not isinstance(record_hash, str)
            or len(record_hash) != 64
            or not isinstance(record, dict)
            or document_hash({"previous_hash": previous_hash, "record": record}) != record_hash
        ):
            raise Session5Error("audit_hash_invalid", "final audit envelope hash is invalid")
        expected_record = {
            "request_id": request["request_id"],
            "setup_id": request["setup_id"],
            "outcome": "VERDICT",
            "validated_verdict": verdict["verdict"],
            "request_hash": actual_request_hash,
            "verdict_hash": actual_verdict_hash,
        }
        failed = [
            field for field, expected in expected_record.items()
            if record.get(field) != expected
        ]
        if failed or not isinstance(record.get("attempt_id"), str):
            raise Session5Error(
                "audit_identity_mismatch",
                "final audit record mismatch: " + ", ".join(failed or ["attempt_id"]),
            )
        completed = self.completed_result
        if (
            not isinstance(completed, dict)
            or completed.get("status") != "VERDICT"
            or completed.get("request_id") != request["request_id"]
            or completed.get("attempt_id") != record["attempt_id"]
            or completed.get("verdict") != verdict
            or completed.get("audit_record_hash") != record_hash
        ):
            raise Session5Error(
                "completed_result_mismatch",
                "completed verdict does not bind to the final audit record",
            )


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
        validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
        validate_contract(AI_VERDICT_SCHEMA_V1, verdict)
        attestation.validate(request, verdict)
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
            audit_record_hash=attestation.audit_record_hash,
            audit_envelope=attestation.final_audit_envelope,
            completed_result=attestation.completed_result,
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
