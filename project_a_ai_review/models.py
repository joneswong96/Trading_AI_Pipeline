"""Narrow Session 3 handoff and Session 4 result types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from contracts import canonical_json


@dataclass(frozen=True)
class Artifact:
    evidence_id: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str = "image/png"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DispatchEnvelope:
    dispatch_id: str
    request: dict[str, Any]
    bundle_hash: str
    artifact_manifest: tuple[Artifact, ...]
    artifact_manifest_hash: str
    artifact_root: Path
    attempt_metadata: dict[str, Any] = field(default_factory=dict)

    def manifest_document(self) -> dict[str, Any]:
        return {"artifacts": [artifact.as_dict() for artifact in self.artifact_manifest]}


@dataclass(frozen=True)
class RuntimePolicy:
    adapter_version: str = "project-a-ai-review/1.0.0"
    expected_venue: str = "ICMARKETS"
    max_request_age_seconds: int = 300
    max_future_skew_seconds: int = 5
    model_timeout_seconds: int = 90
    max_attempts: int = 2
    raw_response_max_bytes: int = 65_536
    shadow_mode: bool = True
    openclaw_agent: str = "project-a-reviewer"
    openclaw_version: str = "UNAVAILABLE"
    auth_mode: str = "openai-codex-oauth"


@dataclass(frozen=True)
class ModelIdentity:
    provider: str
    name: str
    auth_mode: str


@dataclass(frozen=True)
class ReviewResult:
    status: str
    request_id: str | None
    attempt_id: str | None
    verdict: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    audit_record_hash: str | None = None
    cached: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical(self) -> str:
        return canonical_json(self.as_dict())
