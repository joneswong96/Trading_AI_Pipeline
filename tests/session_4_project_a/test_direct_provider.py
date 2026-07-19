from __future__ import annotations

import ast
import json
import socket
import subprocess
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from contracts import canonical_json
from project_a_ai_review.audit import ShadowAuditStore
from project_a_ai_review.direct_provider import (
    DirectProviderConfig,
    DisabledReviewTransport,
    ReviewTransportRequest,
    create_review_transport,
    validate_direct_provider_config,
)
from project_a_ai_review.errors import FailureCode, TechnicalFailure
from project_a_ai_review.hashing import sha256_text
from project_a_ai_review.models import RuntimePolicy
from project_a_ai_review.prompt import PROMPT_VERSION, prompt_hash
from project_a_ai_review.service import ReviewService

from .conftest import MutableClock, candidate_raw, make_dispatch
from .fake_direct_provider import (
    FakeInMemoryReviewTransport,
    SyntheticTransportModelClient,
    get_test_only_transport_capability,
    synthetic_runtime_policy,
)

ROOT = Path(__file__).resolve().parents[2]


def transport_request(raw: bytes = b"{}") -> ReviewTransportRequest:
    policy = synthetic_runtime_policy()
    return ReviewTransportRequest(
        request_id="req_synthetic_test_0001",
        setup_id="setup_synthetic_test_0001",
        canonical_event_id="evt_synthetic_test_0001",
        canonical_content_hash=sha256_text("synthetic canonical content"),
        analysis_request_hash=sha256_text("synthetic analysis request"),
        prompt_identity=PROMPT_VERSION,
        prompt_hash=prompt_hash(),
        provider_policy_identity=policy.provider_policy_identity,
        model_policy_identity=policy.model_policy_identity,
        payload_bytes=raw,
        timeout_policy_identity=policy.timeout_policy_identity,
        maximum_request_bytes=1024,
        maximum_response_bytes=1024,
    )


def synthetic_candidate_raw(name="approve", mutate=None):
    def apply(value):
        value["model"]["provider"] = "synthetic-provider"
        value["model"]["name"] = "synthetic-model"
        if mutate:
            mutate(value)

    return candidate_raw(name, mutate=apply)


def fake_service(tmp_path, dispatch, transport, clock, *, store=None):
    policy = synthetic_runtime_policy()
    client = SyntheticTransportModelClient(
        dispatch=dispatch,
        transport=transport,
        policy=policy,
    )
    service = ReviewService(
        audit_store=store or ShadowAuditStore(tmp_path / "audit"),
        client=client,
        policy=RuntimePolicy(model_timeout_seconds=policy.timeout_seconds),
        clock=clock,
    )
    return service, client


def test_default_configuration_is_immutable_disabled_and_null():
    config = validate_direct_provider_config(None)
    assert config == DirectProviderConfig()
    assert config.enabled is False
    assert config.provider is config.model is config.endpoint is None
    assert config.credential_ref is None
    with pytest.raises(AttributeError):
        config.enabled = True
    with pytest.raises(TechnicalFailure) as error:
        DirectProviderConfig(fallback_models=[])
    assert error.value.code == FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN


def test_disabled_example_is_the_only_selectable_posture():
    path = (
        ROOT
        / "config_templates"
        / "project_a_reviewer"
        / "direct_provider.disabled.yaml"
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))["direct_provider"]
    assert validate_direct_provider_config(document) == DirectProviderConfig()


def test_missing_config_constructs_only_disabled_technical_transport():
    transport = create_review_transport()
    assert isinstance(transport, DisabledReviewTransport)
    result = transport.invoke(transport_request())
    assert result.succeeded is False
    assert result.invoked is False
    assert result.failure_code == FailureCode.DIRECT_PROVIDER_DISABLED
    assert result.raw_response is None


def test_disabled_transport_creates_no_verdict_or_model_invocation_audit(
    request_doc, artifact_root, trusted_now, tmp_path
):
    dispatch = make_dispatch(request_doc, artifact_root)
    store = ShadowAuditStore(tmp_path / "audit")
    service, _ = fake_service(
        tmp_path,
        dispatch,
        DisabledReviewTransport(),
        lambda: trusted_now,
        store=store,
    )
    result = service.review(dispatch)
    assert result.status == "TECHNICAL_FAILURE"
    assert result.failure["code"] == FailureCode.DIRECT_PROVIDER_DISABLED.value
    assert result.verdict is None
    assert store.load_completed(request_doc["request_id"]) is None
    attempt = store.final_attempt(request_doc["request_id"])["record"]
    assert "raw_model_response_hash" not in attempt
    assert "model_invoked" not in attempt


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"enabled": True}, FailureCode.DIRECT_PROVIDER_RUNTIME_NOT_APPROVED),
        (
            {"enabled": True, "provider": "openai", "model": "real-model"},
            FailureCode.DIRECT_PROVIDER_RUNTIME_NOT_APPROVED,
        ),
        ({"enabled": "false"}, FailureCode.DIRECT_PROVIDER_CONFIG_INVALID),
        ({"provider": "openai"}, FailureCode.DIRECT_PROVIDER_POLICY_REQUIRED),
        ({"model": "real-model"}, FailureCode.DIRECT_PROVIDER_POLICY_REQUIRED),
        ({"endpoint": "https://provider.example/v1"}, FailureCode.DIRECT_PROVIDER_POLICY_REQUIRED),
        ({"api_version": "v1"}, FailureCode.DIRECT_PROVIDER_POLICY_REQUIRED),
        ({"credential_ref": "metadata-only"}, FailureCode.DIRECT_PROVIDER_POLICY_REQUIRED),
        ({"endpoint": "http://provider.example/v1"}, FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED),
        (
            {"endpoint": "https://" + "synthetic-user:synthetic-password@" + "provider.example/v1"},
            FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED,
        ),
        ({"endpoint": "https://provider.example/v1?q=1"}, FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED),
        ({"endpoint": "https://provider.example/v1#fragment"}, FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED),
        ({"fallback_enabled": True}, FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN),
        ({"fallback_models": ["other"]}, FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN),
        ({"redirects_enabled": True}, FailureCode.DIRECT_PROVIDER_REDIRECT_FORBIDDEN),
        ({"environment_proxy_enabled": True}, FailureCode.DIRECT_PROVIDER_PROXY_FORBIDDEN),
        ({"tools_enabled": True}, FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN),
        ({"tool_declarations": ["search"]}, FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN),
        ({"browser_enabled": True}, FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN),
        ({"exec_enabled": True}, FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN),
        ({"streaming_enabled": True}, FailureCode.DIRECT_PROVIDER_CONFIG_INVALID),
        ({"external_outputs_enabled": True}, FailureCode.DIRECT_PROVIDER_CONFIG_INVALID),
        ({"external_output_channels": []}, FailureCode.DIRECT_PROVIDER_CONFIG_INVALID),
        ({"unknown": False}, FailureCode.DIRECT_PROVIDER_CONFIG_INVALID),
        ({"provider": ""}, FailureCode.DIRECT_PROVIDER_CONFIG_INVALID),
        ({"api_key": "forbidden"}, FailureCode.DIRECT_PROVIDER_CREDENTIAL_VALUE_FORBIDDEN),
        ({"credential_value": "forbidden"}, FailureCode.DIRECT_PROVIDER_CREDENTIAL_VALUE_FORBIDDEN),
        ({"transport": "fake"}, FailureCode.DIRECT_PROVIDER_FAKE_FORBIDDEN),
    ],
)
def test_invalid_or_unapproved_settings_fail_before_factory(document, code):
    with pytest.raises(TechnicalFailure) as error:
        create_review_transport(document)
    assert error.value.code == code


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"provider": "wrong-provider"}, FailureCode.DIRECT_PROVIDER_IDENTITY_MISMATCH),
        ({"model": "wrong-model"}, FailureCode.DIRECT_PROVIDER_IDENTITY_MISMATCH),
        ({"endpoint": "https://wrong.synthetic.invalid/v1/review"}, FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED),
        ({"api_version": "wrong-version"}, FailureCode.DIRECT_PROVIDER_IDENTITY_MISMATCH),
    ],
)
def test_wrong_selection_rejects_against_synthetic_policy_before_construction(document, code):
    with pytest.raises(TechnicalFailure) as error:
        create_review_transport(document, policy_lock=synthetic_runtime_policy())
    assert error.value.code == code


def test_matching_synthetic_policy_still_constructs_only_disabled_transport():
    policy = synthetic_runtime_policy()
    transport = create_review_transport(
        {
            "provider": policy.provider,
            "model": policy.model,
            "endpoint": policy.endpoint,
            "api_version": policy.api_version,
        },
        policy_lock=policy,
    )
    assert isinstance(transport, DisabledReviewTransport)


def test_fake_requires_explicit_test_only_capability():
    with pytest.raises(TechnicalFailure) as error:
        FakeInMemoryReviewTransport(capability=object(), raw_response="{}")
    assert error.value.code == FailureCode.DIRECT_PROVIDER_FAKE_FORBIDDEN


def test_fake_is_bounded_deterministic_and_performs_zero_network_or_process_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        raw_response="{}",
    )
    request = transport_request()
    one = fake.invoke(request)
    two = fake.invoke(request)
    assert one.succeeded is two.succeeded is True
    assert fake.calls == 2
    assert fake.invocations[0] == fake.invocations[1]
    assert fake.invocations[0].request_id == request.request_id
    assert fake.invocations[0].canonical_content_hash == request.canonical_content_hash


def test_oversized_fake_raw_response_is_technical_failure():
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        raw_response="x" * 1025,
    )
    result = fake.invoke(transport_request())
    assert result.succeeded is False
    assert result.failure_code == FailureCode.SESSION_FAILURE
    assert result.raw_response is None


def test_fake_raw_response_runs_real_parser_postgates_audit_and_cache(
    request_doc, artifact_root, trusted_now, tmp_path
):
    dispatch = make_dispatch(request_doc, artifact_root)
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        raw_response=synthetic_candidate_raw(),
    )
    service, _ = fake_service(tmp_path, dispatch, fake, lambda: trusted_now)
    first = service.review(dispatch)
    second = service.review(dispatch)
    assert first.status == second.status == "VERDICT"
    assert second.cached is True
    assert second.verdict == first.verdict
    assert fake.calls == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a":1,"a":2}', {FailureCode.MALFORMED_MODEL_OUTPUT}),
        ('{"a":NaN}', {FailureCode.MALFORMED_MODEL_OUTPUT}),
        (
            synthetic_candidate_raw(mutate=lambda value: value.update(extra=True)),
            {FailureCode.OUTPUT_SCHEMA_FAILURE},
        ),
        (
            synthetic_candidate_raw(mutate=lambda value: value.update(request_id="req_wrong_0001")),
            {FailureCode.IDENTIFIER_MISMATCH},
        ),
        (
            synthetic_candidate_raw(mutate=lambda value: value.update(tp=2419.5)),
            {FailureCode.OUTPUT_SCHEMA_FAILURE, FailureCode.RR_FAILURE},
        ),
        (synthetic_candidate_raw("expired"), {FailureCode.EXPIRY_FAILURE}),
    ],
)
def test_fake_output_cannot_bypass_parser_schema_identity_expiry_or_geometry(
    request_doc, artifact_root, trusted_now, tmp_path, raw, expected
):
    dispatch = make_dispatch(request_doc, artifact_root)
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        raw_response=raw,
    )
    service, _ = fake_service(tmp_path, dispatch, fake, lambda: trusted_now)
    result = service.review(dispatch)
    assert result.status == "TECHNICAL_FAILURE"
    assert FailureCode(result.failure["code"]) in expected
    assert result.verdict is None


def test_fake_timeout_remains_technical_failure(
    request_doc, artifact_root, trusted_now, tmp_path
):
    dispatch = make_dispatch(request_doc, artifact_root)
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        failure_code=FailureCode.MODEL_TIMEOUT,
        retryable=True,
    )
    service, _ = fake_service(tmp_path, dispatch, fake, lambda: trusted_now)
    result = service.review(dispatch)
    assert result.status == "TECHNICAL_FAILURE"
    assert result.failure["code"] == FailureCode.MODEL_TIMEOUT.value
    assert result.verdict is None
    assert fake.calls == 1


class BrokenAuditStore(ShadowAuditStore):
    def append_attempt(self, request_id, record):
        raise OSError("synthetic test failure")


def test_fake_audit_persistence_failure_withholds_release(
    request_doc, artifact_root, trusted_now, tmp_path
):
    dispatch = make_dispatch(request_doc, artifact_root)
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        raw_response=synthetic_candidate_raw(),
    )
    service, _ = fake_service(
        tmp_path,
        dispatch,
        fake,
        lambda: trusted_now,
        store=BrokenAuditStore(tmp_path / "broken-audit"),
    )
    result = service.review(dispatch)
    assert result.status == "TECHNICAL_FAILURE"
    assert result.failure["code"] == FailureCode.AUDIT_PERSISTENCE_FAILURE.value
    assert result.verdict is None


def test_fake_cached_release_rechecks_expiry_without_second_invocation(
    request_doc, artifact_root, trusted_now, tmp_path
):
    clock = MutableClock(trusted_now)
    dispatch = make_dispatch(request_doc, artifact_root)
    fake = FakeInMemoryReviewTransport(
        capability=get_test_only_transport_capability(),
        raw_response=synthetic_candidate_raw(),
    )
    service, _ = fake_service(tmp_path, dispatch, fake, clock)
    assert service.review(dispatch).status == "VERDICT"
    clock.value = trusted_now + timedelta(minutes=6)
    result = service.review(dispatch)
    assert result.status == "INPUT_REJECTION"
    assert result.failure["code"] == FailureCode.INPUT_EXPIRED.value
    assert result.verdict is None
    assert fake.calls == 1


def test_new_production_module_has_no_provider_sdk_network_secret_or_process_import():
    module_path = ROOT / "project_a_ai_review" / "direct_provider.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "aiohttp",
        "anthropic",
        "httpx",
        "keyring",
        "openai",
        "openclaw",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    assert not any(
        name == blocked or name.startswith(blocked + ".")
        for name in imported
        for blocked in forbidden
    )


def test_new_production_module_contains_no_dispatch_or_verdict_authority():
    source = (ROOT / "project_a_ai_review" / "direct_provider.py").read_text(
        encoding="utf-8"
    )
    for verdict in ("APPROVE", "REJECT", "MODIFY", "EXPIRED"):
        assert f'"{verdict}"' not in source
    assert "urlopen(" not in source
    assert "socket(" not in source
    assert "subprocess." not in source
