"""Test-only in-memory transport and explicit Session 4 adapter."""
from __future__ import annotations

from dataclasses import dataclass

from contracts import canonical_json
from project_a_ai_review.direct_provider import (
    DirectProviderRuntimePolicy,
    ReviewTransport,
    ReviewTransportRequest,
    ReviewTransportResult,
    RuntimePolicyStatus,
)
from project_a_ai_review.errors import FailureCode, TechnicalFailure
from project_a_ai_review.hashing import sha256_text
from project_a_ai_review.models import DispatchEnvelope, ModelIdentity
from project_a_ai_review.prompt import PROMPT_VERSION, prompt_hash

_TEST_ONLY_CAPABILITY = object()


def get_test_only_transport_capability() -> object:
    """Return the package-local capability required by the fake transport."""

    return _TEST_ONLY_CAPABILITY


def synthetic_runtime_policy() -> DirectProviderRuntimePolicy:
    return DirectProviderRuntimePolicy(
        status=RuntimePolicyStatus.SYNTHETIC_TEST_ONLY,
        policy_identity="SYNTHETIC_TEST_ONLY:direct-provider-policy-v1",
        provider_policy_identity="SYNTHETIC_TEST_ONLY:provider-policy-v1",
        model_policy_identity="SYNTHETIC_TEST_ONLY:model-policy-v1",
        timeout_policy_identity="SYNTHETIC_TEST_ONLY:timeout-policy-v1",
        provider="synthetic-provider",
        https_origin="https://review.synthetic.invalid",
        endpoint_path="/v1/review",
        model="synthetic-model",
        api_version="synthetic-api-v1",
        request_format_version="synthetic-request-v1",
        response_format_version="synthetic-response-v1",
        timeout_seconds=5,
        maximum_request_bytes=65_536,
        maximum_response_bytes=65_536,
        redirects_enabled=False,
        fallback_models=(),
        environment_proxy_enabled=False,
        tools_enabled=False,
        authentication_method="synthetic-none-test-only",
        credential_reference_type="synthetic-none-test-only",
        credential_ref=None,
        cost_ceiling_minor_units=0,
        audit_identity="SYNTHETIC_TEST_ONLY:audit-policy-v1",
    )


@dataclass(frozen=True)
class RecordedTransportInvocation:
    request_id: str
    setup_id: str
    canonical_event_id: str
    canonical_content_hash: str
    analysis_request_hash: str
    prompt_hash: str
    payload_hash: str


class FakeInMemoryReviewTransport:
    """Deterministic fake with no production selector, files, or network."""

    def __init__(
        self,
        *,
        capability: object,
        raw_response: str | None = None,
        failure_code: FailureCode | None = None,
        retryable: bool = False,
    ):
        if capability is not _TEST_ONLY_CAPABILITY:
            raise TechnicalFailure(
                FailureCode.DIRECT_PROVIDER_FAKE_FORBIDDEN,
                "fake review transport requires the test-only capability",
            )
        if raw_response is not None and failure_code is not None:
            raise ValueError("fake transport must select raw response or failure")
        self.raw_response = raw_response
        self.failure_code = failure_code
        self.retryable = retryable
        self.invocations: tuple[RecordedTransportInvocation, ...] = ()

    @property
    def calls(self) -> int:
        return len(self.invocations)

    def invoke(self, request: ReviewTransportRequest) -> ReviewTransportResult:
        self.invocations = (
            *self.invocations,
            RecordedTransportInvocation(
                request_id=request.request_id,
                setup_id=request.setup_id,
                canonical_event_id=request.canonical_event_id,
                canonical_content_hash=request.canonical_content_hash,
                analysis_request_hash=request.analysis_request_hash,
                prompt_hash=request.prompt_hash,
                payload_hash=sha256_text(request.payload_bytes.decode("utf-8")),
            ),
        )
        if self.failure_code is not None:
            return ReviewTransportResult.failure(
                self.failure_code,
                invoked=True,
                retryable=self.retryable,
            )
        if self.raw_response is None:
            return ReviewTransportResult.failure(
                FailureCode.MODEL_UNAVAILABLE,
                invoked=True,
                retryable=True,
            )
        return ReviewTransportResult.raw(
            self.raw_response,
            maximum_response_bytes=request.maximum_response_bytes,
        )


class SyntheticTransportModelClient:
    """Test adapter that routes real ReviewService parsing through the fake."""

    def __init__(
        self,
        *,
        dispatch: DispatchEnvelope,
        transport: ReviewTransport,
        policy: DirectProviderRuntimePolicy,
    ):
        if policy.status is not RuntimePolicyStatus.SYNTHETIC_TEST_ONLY:
            raise TechnicalFailure(
                FailureCode.DIRECT_PROVIDER_FAKE_FORBIDDEN,
                "test adapter requires a synthetic test-only policy",
            )
        self.dispatch = dispatch
        self.transport = transport
        self.policy = policy
        self.identity = ModelIdentity(
            policy.provider,
            policy.model,
            policy.authentication_method,
        )

    def invoke(self, *, session_key, message, artifact_paths, timeout_seconds) -> str:
        del session_key, artifact_paths
        if timeout_seconds != self.policy.timeout_seconds:
            raise TechnicalFailure(
                FailureCode.DIRECT_PROVIDER_IDENTITY_MISMATCH,
                "test timeout does not match synthetic policy",
            )
        request = ReviewTransportRequest(
            request_id=self.dispatch.request["request_id"],
            setup_id=self.dispatch.request["setup_id"],
            canonical_event_id=self.dispatch.request["source_event_ids"][0],
            canonical_content_hash=self.dispatch.bundle_hash,
            analysis_request_hash=sha256_text(canonical_json(self.dispatch.request)),
            prompt_identity=PROMPT_VERSION,
            prompt_hash=prompt_hash(),
            provider_policy_identity=self.policy.provider_policy_identity,
            model_policy_identity=self.policy.model_policy_identity,
            payload_bytes=message.encode("utf-8"),
            timeout_policy_identity=self.policy.timeout_policy_identity,
            maximum_request_bytes=self.policy.maximum_request_bytes,
            maximum_response_bytes=self.policy.maximum_response_bytes,
        )
        result = self.transport.invoke(request)
        if not result.succeeded:
            raise TechnicalFailure(
                result.failure_code or FailureCode.SESSION_FAILURE,
                "provider-neutral test transport failed",
                result.retryable,
            )
        return result.raw_response or ""
