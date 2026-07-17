"""Validated request -> isolated review -> post-gates -> persisted shadow result."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from contracts import canonical_json

from .audit import ShadowAuditStore
from .clients import ModelClient
from .errors import FailureCode, InputRejected, ReviewFailure, TechnicalFailure
from .gates import post_validate, preflight
from .hashing import sha256_text
from .models import DispatchEnvelope, ReviewResult, RuntimePolicy
from .parser import parse_model_json
from .prompt import (
    PROMPT_VERSION,
    build_review_message,
    expected_verdict_id,
    prompt_hash,
)


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ReviewService:
    def __init__(
        self,
        *,
        audit_store: ShadowAuditStore,
        client: ModelClient,
        policy: RuntimePolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.audit = audit_store
        self.client = client
        self.policy = policy or RuntimePolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _request_id(dispatch: DispatchEnvelope) -> str:
        value = dispatch.request.get("request_id")
        if isinstance(value, str) and value:
            return value
        return f"invalid_{sha256_text(canonical_json(dispatch.request))[:32]}"

    def _failure_result(
        self,
        *,
        failure: ReviewFailure,
        request_id: str,
        attempt_id: str,
        record: dict,
    ) -> ReviewResult:
        failure_data = {
            "code": failure.code.value,
            "message": failure.message,
            "retryable": failure.retryable,
        }
        record.update({"outcome": failure.category, "failure": failure_data})
        try:
            record_hash = self.audit.append_attempt(request_id, record)
        except Exception:
            return ReviewResult(
                status="TECHNICAL_FAILURE",
                request_id=request_id,
                attempt_id=attempt_id,
                failure={
                    "code": FailureCode.AUDIT_PERSISTENCE_FAILURE.value,
                    "message": "audit persistence failed; no verdict released",
                    "retryable": False,
                },
            )
        return ReviewResult(
            status=failure.category,
            request_id=request_id,
            attempt_id=attempt_id,
            failure=failure_data,
            audit_record_hash=record_hash,
        )

    @staticmethod
    def _audit_failure_result(request_id: str, attempt_id: str, message: str) -> ReviewResult:
        return ReviewResult(
            status="TECHNICAL_FAILURE",
            request_id=request_id,
            attempt_id=attempt_id,
            failure={
                "code": FailureCode.AUDIT_PERSISTENCE_FAILURE.value,
                "message": message,
                "retryable": False,
            },
        )

    def _validated_cached_result(
        self,
        *,
        completed: dict,
        dispatch: DispatchEnvelope,
        request_id: str,
        attempt_id: str,
        fingerprint: str,
    ) -> ReviewResult:
        try:
            result = ReviewResult(**completed)
        except (TypeError, ValueError) as exc:
            raise TechnicalFailure(
                FailureCode.AUDIT_PERSISTENCE_FAILURE,
                "completed verdict record is malformed",
            ) from exc
        if (
            result.status != "VERDICT"
            or not isinstance(result.verdict, dict)
            or not result.audit_record_hash
            or not result.attempt_id
        ):
            raise TechnicalFailure(
                FailureCode.AUDIT_PERSISTENCE_FAILURE,
                "completed verdict record is incomplete",
            )
        if result.request_id != request_id:
            raise TechnicalFailure(
                FailureCode.IDENTIFIER_MISMATCH,
                "cached result request_id mismatch",
            )
        expected_identity = {
            "verdict_id": expected_verdict_id(request_id, fingerprint),
            "request_id": request_id,
            "setup_id": dispatch.request["setup_id"],
            "correlation_id": dispatch.request["correlation_id"],
            "causation_id": request_id,
        }
        for field, expected in expected_identity.items():
            if result.verdict.get(field) != expected:
                raise TechnicalFailure(
                    FailureCode.IDENTIFIER_MISMATCH,
                    f"cached verdict {field} mismatch",
                )
        if not self.audit.verify_chain(request_id):
            raise TechnicalFailure(
                FailureCode.AUDIT_PERSISTENCE_FAILURE,
                "cached verdict audit chain failed verification",
            )
        final_attempt = self.audit.final_attempt(request_id)
        if final_attempt is None:
            raise TechnicalFailure(
                FailureCode.AUDIT_PERSISTENCE_FAILURE,
                "cached verdict has no audit attempt",
            )
        final_record = final_attempt.get("record")
        if (
            final_attempt.get("record_hash") != result.audit_record_hash
            or not isinstance(final_record, dict)
            or final_record.get("attempt_id") != result.attempt_id
            or final_record.get("request_id") != request_id
            or final_record.get("outcome") != "VERDICT"
            or final_record.get("validated_verdict") != result.verdict.get("verdict")
        ):
            raise TechnicalFailure(
                FailureCode.AUDIT_PERSISTENCE_FAILURE,
                "cached verdict does not match the final audit record",
            )
        trusted_fields = {
            **expected_identity,
            "generated_at": result.verdict.get("generated_at"),
        }
        validated, _ = post_validate(
            result.verdict,
            request=dispatch.request,
            manifest=dispatch.manifest_document(),
            trusted_fields=trusted_fields,
            now=self.clock(),
            model=self.client.identity,
        )
        if validated != result.verdict:
            raise TechnicalFailure(
                FailureCode.AUDIT_PERSISTENCE_FAILURE,
                "cached verdict is not the persisted validated verdict",
            )
        return ReviewResult(**{**result.as_dict(), "cached": True})

    def review(self, dispatch: DispatchEnvelope, *, retry_of: str | None = None) -> ReviewResult:
        request_id = self._request_id(dispatch)
        attempt_id = f"attempt_{uuid4().hex}"
        start = self.clock()
        model_key = f"{self.client.identity.provider}/{self.client.identity.name}/{self.client.identity.auth_mode}"
        fingerprint = sha256_text(
            "\n".join(
                (
                    dispatch.bundle_hash,
                    dispatch.artifact_manifest_hash,
                    prompt_hash(),
                    self.policy.adapter_version,
                    model_key,
                )
            )
        )
        record = {
            "attempt_id": attempt_id,
            "dispatch_id": dispatch.dispatch_id,
            "request_id": request_id,
            "setup_id": dispatch.request.get("setup_id"),
            "correlation_id": dispatch.request.get("correlation_id"),
            "causation_id": dispatch.request.get("causation_id"),
            "source_event_ids": dispatch.request.get("source_event_ids", []),
            "input_bundle_hash": dispatch.bundle_hash,
            "artifact_manifest_hash": dispatch.artifact_manifest_hash,
            "attempt_metadata_hash": sha256_text(canonical_json(dispatch.attempt_metadata)),
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": prompt_hash(),
            "adapter_version": self.policy.adapter_version,
            "openclaw_version": self.policy.openclaw_version,
            "provider": self.client.identity.provider,
            "model": self.client.identity.name,
            "auth_mode": self.client.identity.auth_mode,
            "session_id": f"agent:{self.policy.openclaw_agent}:review_{sha256_text(request_id)[:32]}",
            "started_at": utc_z(start),
            "retry_of": retry_of,
            "shadow_mode": True,
        }
        try:
            with self.audit.lock(request_id):
                try:
                    self.audit.ensure_request_metadata(
                        request_id,
                        fingerprint=fingerprint,
                        bundle_hash=dispatch.bundle_hash,
                        prompt_hash=prompt_hash(),
                        model_key=model_key,
                    )
                except InputRejected as failure:
                    record["ended_at"] = utc_z(self.clock())
                    return self._failure_result(
                        failure=failure,
                        request_id=request_id,
                        attempt_id=attempt_id,
                        record=record,
                    )

                try:
                    pre_gates = preflight(dispatch, self.clock(), self.policy)
                    record["pre_gates"] = {
                        k: v for k, v in pre_gates.items() if k != "verified_paths"
                    }
                except ReviewFailure as failure:
                    record["ended_at"] = utc_z(self.clock())
                    return self._failure_result(
                        failure=failure,
                        request_id=request_id,
                        attempt_id=attempt_id,
                        record=record,
                    )

                try:
                    completed = self.audit.load_completed(request_id)
                    if completed:
                        return self._validated_cached_result(
                            completed=completed,
                            dispatch=dispatch,
                            request_id=request_id,
                            attempt_id=attempt_id,
                            fingerprint=fingerprint,
                        )
                except TechnicalFailure as failure:
                    if failure.code == FailureCode.AUDIT_PERSISTENCE_FAILURE:
                        return self._audit_failure_result(
                            request_id,
                            attempt_id,
                            failure.message + "; no cached verdict released",
                        )
                    record["ended_at"] = utc_z(self.clock())
                    return self._failure_result(
                        failure=failure,
                        request_id=request_id,
                        attempt_id=attempt_id,
                        record=record,
                    )

                if self.audit.attempt_count(request_id) >= self.policy.max_attempts:
                    failure = TechnicalFailure(
                        FailureCode.SESSION_FAILURE,
                        "review retry limit exhausted",
                        False,
                    )
                    record["ended_at"] = utc_z(self.clock())
                    return self._failure_result(
                        failure=failure,
                        request_id=request_id,
                        attempt_id=attempt_id,
                        record=record,
                    )

                try:
                    generated_at = utc_z(self.clock())
                    trusted_fields = {
                        "verdict_id": expected_verdict_id(request_id, fingerprint),
                        "request_id": request_id,
                        "setup_id": dispatch.request["setup_id"],
                        "correlation_id": dispatch.request["correlation_id"],
                        "causation_id": request_id,
                        "generated_at": generated_at,
                    }
                    message = build_review_message(
                        request=dispatch.request,
                        manifest=dispatch.manifest_document(),
                        pre_gates={k: v for k, v in pre_gates.items() if k != "verified_paths"},
                        trusted_fields=trusted_fields,
                        staged_paths={key: Path(path).name for key, path in pre_gates["verified_paths"].items()},
                    )
                    raw = self.client.invoke(
                        session_key=record["session_id"],
                        message=message,
                        artifact_paths=pre_gates["verified_paths"],
                        timeout_seconds=self.policy.model_timeout_seconds,
                    )
                    raw_hash = self.audit.store_raw_response(request_id, attempt_id, raw)
                    record["raw_model_response_hash"] = raw_hash
                    candidate = parse_model_json(raw, max_bytes=self.policy.raw_response_max_bytes)
                    verdict, post_gates = post_validate(
                        candidate,
                        request=dispatch.request,
                        manifest=dispatch.manifest_document(),
                        trusted_fields=trusted_fields,
                        now=self.clock(),
                        model=self.client.identity,
                    )
                    record.update(
                        {
                            "ended_at": utc_z(self.clock()),
                            "outcome": "VERDICT",
                            "validated_verdict": verdict["verdict"],
                            "schema_validation": True,
                            "post_gates": post_gates,
                            "spread_recheck": {
                                "spread_points": dispatch.request["spread_points"],
                                "max_spread_points": 10,
                                "valid": True,
                            },
                            "expiry_recheck": {
                                "trusted_now": utc_z(self.clock()),
                                "request_expires_at": dispatch.request["expires_at"],
                                "valid": post_gates["expiry_valid"],
                            },
                            "release_requires_completed_record": True,
                        }
                    )
                    record_hash = self.audit.append_attempt(request_id, record)
                    result = ReviewResult(
                        status="VERDICT",
                        request_id=request_id,
                        attempt_id=attempt_id,
                        verdict=verdict,
                        audit_record_hash=record_hash,
                    )
                    self.audit.save_completed(request_id, result.as_dict())
                    return result
                except ReviewFailure as failure:
                    record["ended_at"] = utc_z(self.clock())
                    return self._failure_result(
                        failure=failure,
                        request_id=request_id,
                        attempt_id=attempt_id,
                        record=record,
                    )
                except OSError:
                    return ReviewResult(
                        status="TECHNICAL_FAILURE",
                        request_id=request_id,
                        attempt_id=attempt_id,
                        failure={
                            "code": FailureCode.AUDIT_PERSISTENCE_FAILURE.value,
                            "message": "audit persistence failed; no verdict released",
                            "retryable": False,
                        },
                    )
        except TechnicalFailure as failure:
            record["ended_at"] = utc_z(self.clock())
            return self._failure_result(
                failure=failure,
                request_id=request_id,
                attempt_id=attempt_id,
                record=record,
            )
        except OSError:
            return ReviewResult(
                status="TECHNICAL_FAILURE",
                request_id=request_id,
                attempt_id=attempt_id,
                failure={
                    "code": FailureCode.AUDIT_PERSISTENCE_FAILURE.value,
                    "message": "audit persistence failed; no verdict released",
                    "retryable": False,
                },
            )
