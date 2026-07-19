"""Disabled provider-neutral Session 4 review transport boundary.

This module deliberately contains no provider implementation, credential
resolution, or network operation.  A later reviewed runtime lock may reuse the
immutable boundary types, but this skeleton's production factory can only
return :class:`DisabledReviewTransport`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol
from urllib.parse import urlsplit

from .errors import FailureCode, TechnicalFailure

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFIG_FIELDS = frozenset(
    {
        "enabled",
        "provider",
        "model",
        "endpoint",
        "api_version",
        "credential_ref",
        "fallback_enabled",
        "fallback_models",
        "redirects_enabled",
        "environment_proxy_enabled",
        "tools_enabled",
        "tool_declarations",
        "browser_enabled",
        "exec_enabled",
        "streaming_enabled",
        "external_outputs_enabled",
    }
)
_BOOLEAN_FIELDS = (
    "enabled",
    "fallback_enabled",
    "redirects_enabled",
    "environment_proxy_enabled",
    "tools_enabled",
    "browser_enabled",
    "exec_enabled",
    "streaming_enabled",
    "external_outputs_enabled",
)
_TEXT_FIELDS = (
    "provider",
    "model",
    "endpoint",
    "api_version",
    "credential_ref",
)
_CREDENTIAL_VALUE_FIELDS = frozenset(
    {
        "api_key",
        "api_token",
        "authorization",
        "bearer",
        "credential",
        "credential_value",
        "password",
        "secret",
        "token",
    }
)
_FAKE_SELECTOR_FIELDS = frozenset(
    {"fake_transport", "test_transport", "transport", "transport_type"}
)


def _failure(code: FailureCode, message: str) -> TechnicalFailure:
    """Create a bounded failure that does not echo rejected configuration."""

    return TechnicalFailure(code, message, False)


def _require_text(name: str, value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
            f"{name} must be null or a non-empty exact string",
        )
    return value


def _validate_endpoint(endpoint: str) -> None:
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED,
            "provider endpoint is structurally invalid",
        ) from exc
    if parsed.username is not None or parsed.password is not None:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED,
            "embedded endpoint credentials are forbidden",
        )
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        raise _failure(
            FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED,
            "provider endpoint must be an exact HTTPS URL without query or fragment",
        )


def _validate_origin(origin: str) -> None:
    _validate_endpoint(origin)
    parsed = urlsplit(origin)
    if parsed.path not in {"", "/"} or origin.endswith("/"):
        raise _failure(
            FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED,
            "provider origin must not contain a path",
        )


@dataclass(frozen=True)
class DirectProviderConfig:
    """Secret-free, immutable direct-provider configuration."""

    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    endpoint: str | None = None
    api_version: str | None = None
    credential_ref: str | None = None
    fallback_enabled: bool = False
    fallback_models: tuple[str, ...] = ()
    redirects_enabled: bool = False
    environment_proxy_enabled: bool = False
    tools_enabled: bool = False
    tool_declarations: tuple[str, ...] = ()
    browser_enabled: bool = False
    exec_enabled: bool = False
    streaming_enabled: bool = False
    external_outputs_enabled: bool = False

    def __post_init__(self) -> None:
        for name in _BOOLEAN_FIELDS:
            if type(getattr(self, name)) is not bool:
                raise _failure(
                    FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                    f"{name} must be a boolean",
                )
        for name in _TEXT_FIELDS:
            _require_text(name, getattr(self, name))
        if type(self.fallback_models) is not tuple or self.fallback_models:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN,
                "provider fallback models must be an immutable empty tuple",
            )
        if type(self.tool_declarations) is not tuple or self.tool_declarations:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN,
                "provider tool declarations must be an immutable empty tuple",
            )
        if self.endpoint is not None:
            _validate_endpoint(self.endpoint)
        if self.fallback_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN,
                "provider fallback is forbidden",
            )
        if self.redirects_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_REDIRECT_FORBIDDEN,
                "provider redirects are forbidden",
            )
        if self.environment_proxy_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_PROXY_FORBIDDEN,
                "ambient proxy inheritance is forbidden",
            )
        if self.tools_enabled or self.browser_enabled or self.exec_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN,
                "provider tools, browser, and exec are forbidden",
            )
        if self.streaming_enabled or self.external_outputs_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "streaming and external provider outputs are not approved",
            )
        if self.enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_RUNTIME_NOT_APPROVED,
                "no direct provider runtime is approved",
            )


class RuntimePolicyStatus(str, Enum):
    """No production-approved status exists in the V1 skeleton."""

    UNAPPROVED_CANDIDATE = "UNAPPROVED_CANDIDATE"
    SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"


@dataclass(frozen=True)
class DirectProviderRuntimePolicy:
    """Immutable shape for a future exact provider runtime lock.

    Instances are candidates or unmistakably synthetic test policies.  The
    absence of an ``APPROVED`` status is intentional and is enforced again by
    the production factory.
    """

    status: RuntimePolicyStatus
    policy_identity: str
    provider_policy_identity: str
    model_policy_identity: str
    timeout_policy_identity: str
    provider: str
    https_origin: str
    endpoint_path: str
    model: str
    api_version: str
    request_format_version: str
    response_format_version: str
    timeout_seconds: int
    maximum_request_bytes: int
    maximum_response_bytes: int
    redirects_enabled: bool
    fallback_models: tuple[str, ...]
    environment_proxy_enabled: bool
    tools_enabled: bool
    authentication_method: str
    credential_reference_type: str
    credential_ref: str | None
    cost_ceiling_minor_units: int
    audit_identity: str

    def __post_init__(self) -> None:
        if type(self.status) is not RuntimePolicyStatus:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "runtime policy status is invalid",
            )
        text_fields = (
            self.policy_identity,
            self.provider_policy_identity,
            self.model_policy_identity,
            self.timeout_policy_identity,
            self.provider,
            self.https_origin,
            self.endpoint_path,
            self.model,
            self.api_version,
            self.request_format_version,
            self.response_format_version,
            self.authentication_method,
            self.credential_reference_type,
            self.audit_identity,
        )
        if any(type(value) is not str or not value or value != value.strip() for value in text_fields):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "runtime policy identities must be exact non-empty strings",
            )
        _validate_origin(self.https_origin)
        if (
            not self.endpoint_path.startswith("/")
            or "?" in self.endpoint_path
            or "#" in self.endpoint_path
            or self.endpoint_path.startswith("//")
        ):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED,
                "runtime policy endpoint path is invalid",
            )
        if type(self.timeout_seconds) is not int or self.timeout_seconds <= 0:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "runtime policy timeout must be a positive integer",
            )
        if (
            type(self.maximum_request_bytes) is not int
            or self.maximum_request_bytes <= 0
            or type(self.maximum_response_bytes) is not int
            or self.maximum_response_bytes <= 0
        ):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "runtime policy byte limits must be positive integers",
            )
        if type(self.cost_ceiling_minor_units) is not int or self.cost_ceiling_minor_units < 0:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "runtime policy cost ceiling must be a non-negative integer",
            )
        if type(self.credential_ref) is not str and self.credential_ref is not None:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "credential reference must be null or an exact metadata string",
            )
        if isinstance(self.credential_ref, str) and (
            not self.credential_ref or self.credential_ref != self.credential_ref.strip()
        ):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "credential reference must be null or an exact metadata string",
            )
        if any(
            type(value) is not bool
            for value in (
                self.redirects_enabled,
                self.environment_proxy_enabled,
                self.tools_enabled,
            )
        ):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "runtime policy booleans must be strict booleans",
            )
        if type(self.fallback_models) is not tuple:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN,
                "runtime fallback models must be an immutable tuple",
            )
        if self.redirects_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_REDIRECT_FORBIDDEN,
                "provider redirects are forbidden",
            )
        if self.fallback_models:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN,
                "provider fallback models are forbidden",
            )
        if self.environment_proxy_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_PROXY_FORBIDDEN,
                "ambient proxy inheritance is forbidden",
            )
        if self.tools_enabled:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN,
                "provider tools are forbidden",
            )
        if self.status is RuntimePolicyStatus.SYNTHETIC_TEST_ONLY:
            synthetic = "SYNTHETIC_TEST_ONLY"
            host = urlsplit(self.https_origin).hostname or ""
            if (
                not self.policy_identity.startswith(synthetic)
                or not self.audit_identity.startswith(synthetic)
                or not self.provider.startswith("synthetic-")
                or not self.model.startswith("synthetic-")
                or not host.endswith(".invalid")
            ):
                raise _failure(
                    FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                    "synthetic policy is not unmistakably test-only",
                )

    @property
    def endpoint(self) -> str:
        return self.https_origin + self.endpoint_path


@dataclass(frozen=True)
class ReviewTransportRequest:
    """Bounded immutable payload supplied to a provider-neutral transport."""

    request_id: str
    setup_id: str
    canonical_event_id: str
    canonical_content_hash: str
    analysis_request_hash: str
    prompt_identity: str
    prompt_hash: str
    provider_policy_identity: str
    model_policy_identity: str
    payload_bytes: bytes
    timeout_policy_identity: str
    maximum_request_bytes: int
    maximum_response_bytes: int

    def __post_init__(self) -> None:
        identities = (
            self.request_id,
            self.setup_id,
            self.canonical_event_id,
            self.prompt_identity,
            self.provider_policy_identity,
            self.model_policy_identity,
            self.timeout_policy_identity,
        )
        if any(type(value) is not str or not value or value != value.strip() for value in identities):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "transport request identities must be exact non-empty strings",
            )
        if any(
            not _SHA256.fullmatch(value)
            for value in (
                self.canonical_content_hash,
                self.analysis_request_hash,
                self.prompt_hash,
            )
        ):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_IDENTITY_MISMATCH,
                "transport request hash identity is invalid",
            )
        if type(self.payload_bytes) is not bytes:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "transport request payload must be immutable bytes",
            )
        if (
            type(self.maximum_request_bytes) is not int
            or self.maximum_request_bytes <= 0
            or len(self.payload_bytes) > self.maximum_request_bytes
            or type(self.maximum_response_bytes) is not int
            or self.maximum_response_bytes <= 0
        ):
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                "transport request exceeds its immutable byte policy",
            )


@dataclass(frozen=True)
class ReviewTransportResult:
    """Raw technical response or failure; never a Session 4 verdict."""

    succeeded: bool
    invoked: bool
    raw_response: str | None
    failure_code: FailureCode | None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.succeeded:
            if type(self.raw_response) is not str or self.failure_code is not None or not self.invoked:
                raise ValueError("successful transport result is inconsistent")
        elif self.raw_response is not None or self.failure_code is None:
            raise ValueError("failed transport result is inconsistent")

    @classmethod
    def raw(cls, value: str, *, maximum_response_bytes: int) -> "ReviewTransportResult":
        if type(value) is not str or type(maximum_response_bytes) is not int:
            raise ValueError("raw transport response is invalid")
        if maximum_response_bytes <= 0 or len(value.encode("utf-8")) > maximum_response_bytes:
            return cls.failure(FailureCode.SESSION_FAILURE, invoked=True)
        return cls(True, True, value, None, False)

    @classmethod
    def failure(
        cls,
        code: FailureCode,
        *,
        invoked: bool,
        retryable: bool = False,
    ) -> "ReviewTransportResult":
        return cls(False, invoked, None, code, retryable)


class ReviewTransport(Protocol):
    def invoke(self, request: ReviewTransportRequest) -> ReviewTransportResult: ...


@dataclass(frozen=True)
class DisabledReviewTransport:
    """The only transport constructible by the production factory."""

    def invoke(self, request: ReviewTransportRequest) -> ReviewTransportResult:
        del request
        return ReviewTransportResult.failure(
            FailureCode.DIRECT_PROVIDER_DISABLED,
            invoked=False,
        )


def validate_direct_provider_config(
    document: Mapping[str, object] | None,
    *,
    policy_lock: DirectProviderRuntimePolicy | None = None,
) -> DirectProviderConfig:
    """Strictly validate config before any transport construction."""

    if document is None:
        document = {}
    if not isinstance(document, Mapping):
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
            "direct provider configuration must be an object",
        )
    if any(type(key) is not str for key in document):
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
            "direct provider configuration keys must be strings",
        )
    keys = set(document)
    if keys & _CREDENTIAL_VALUE_FIELDS:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CREDENTIAL_VALUE_FORBIDDEN,
            "credential values are forbidden in direct provider configuration",
        )
    if keys & _FAKE_SELECTOR_FIELDS:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_FAKE_FORBIDDEN,
            "test transports cannot be selected by production configuration",
        )
    unknown = keys - _CONFIG_FIELDS
    if unknown:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
            "unknown direct provider configuration fields are forbidden",
        )

    values: dict[str, object] = {
        "enabled": False,
        "provider": None,
        "model": None,
        "endpoint": None,
        "api_version": None,
        "credential_ref": None,
        "fallback_enabled": False,
        "fallback_models": [],
        "redirects_enabled": False,
        "environment_proxy_enabled": False,
        "tools_enabled": False,
        "tool_declarations": [],
        "browser_enabled": False,
        "exec_enabled": False,
        "streaming_enabled": False,
        "external_outputs_enabled": False,
    }
    values.update(document)
    for name in _BOOLEAN_FIELDS:
        if type(values[name]) is not bool:
            raise _failure(
                FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
                f"{name} must be a boolean",
            )
    for name in _TEXT_FIELDS:
        values[name] = _require_text(name, values[name])

    fallback_models = values["fallback_models"]
    if type(fallback_models) is not list or fallback_models:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN,
            "provider fallback models must be an empty list",
        )
    tool_declarations = values["tool_declarations"]
    if type(tool_declarations) is not list or tool_declarations:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN,
            "provider tool declarations must be an empty list",
        )
    endpoint = values["endpoint"]
    if endpoint is not None:
        _validate_endpoint(endpoint)
    if values["fallback_enabled"]:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_FALLBACK_FORBIDDEN,
            "provider fallback is forbidden",
        )
    if values["redirects_enabled"]:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_REDIRECT_FORBIDDEN,
            "provider redirects are forbidden",
        )
    if values["environment_proxy_enabled"]:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_PROXY_FORBIDDEN,
            "ambient proxy inheritance is forbidden",
        )
    if values["tools_enabled"] or values["browser_enabled"] or values["exec_enabled"]:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_TOOLS_FORBIDDEN,
            "provider tools, browser, and exec are forbidden",
        )
    if values["streaming_enabled"]:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
            "provider streaming is not approved",
        )
    if values["external_outputs_enabled"]:
        raise _failure(
            FailureCode.DIRECT_PROVIDER_CONFIG_INVALID,
            "external provider outputs are forbidden",
        )

    config = DirectProviderConfig(
        **{
            **values,
            "fallback_models": tuple(fallback_models),
            "tool_declarations": tuple(tool_declarations),
        }
    )
    selected = {
        "provider": config.provider,
        "model": config.model,
        "endpoint": config.endpoint,
        "api_version": config.api_version,
        "credential_ref": config.credential_ref,
    }
    if policy_lock is None and any(value is not None for value in selected.values()):
        raise _failure(
            FailureCode.DIRECT_PROVIDER_POLICY_REQUIRED,
            "provider identity settings require an exact runtime policy lock",
        )
    if policy_lock is not None:
        expected = {
            "provider": policy_lock.provider,
            "model": policy_lock.model,
            "endpoint": policy_lock.endpoint,
            "api_version": policy_lock.api_version,
            "credential_ref": policy_lock.credential_ref,
        }
        for name, value in selected.items():
            if value is not None and value != expected[name]:
                code = (
                    FailureCode.DIRECT_PROVIDER_ENDPOINT_REJECTED
                    if name == "endpoint"
                    else FailureCode.DIRECT_PROVIDER_IDENTITY_MISMATCH
                )
                raise _failure(code, "direct provider selection does not match policy")
    return config


def create_review_transport(
    document: Mapping[str, object] | None = None,
    *,
    policy_lock: DirectProviderRuntimePolicy | None = None,
) -> ReviewTransport:
    """Fail closed: V1 can construct only a disabled transport."""

    validate_direct_provider_config(document, policy_lock=policy_lock)
    return DisabledReviewTransport()
