"""Mock/manual and guarded OpenClaw model invocation boundaries."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import FailureCode, TechnicalFailure
from .hashing import request_storage_key
from .models import ModelIdentity


class ModelClient(Protocol):
    identity: ModelIdentity

    def invoke(
        self,
        *,
        session_key: str,
        message: str,
        artifact_paths: dict[str, str],
        timeout_seconds: int,
    ) -> str: ...


@dataclass
class RecordedModelClient:
    raw_response: str | None = None
    failure: TechnicalFailure | None = None
    delay_hook: object | None = None
    identity: ModelIdentity = ModelIdentity("fixture", "recorded-reviewer", "none")
    calls: int = 0
    sessions: tuple[str, ...] = ()

    def invoke(self, *, session_key, message, artifact_paths, timeout_seconds) -> str:
        self.calls += 1
        self.sessions = (*self.sessions, session_key)
        if callable(self.delay_hook):
            self.delay_hook()
        if self.failure:
            raise self.failure
        if self.raw_response is None:
            raise TechnicalFailure(FailureCode.MODEL_UNAVAILABLE, "no recorded response", True)
        return self.raw_response


class OpenClawCliClient:
    """Invoke a pinned dedicated OpenClaw agent without shell interpolation.

    Official OpenClaw CLI versions may fall back to embedded execution when the
    Gateway fails. That changes the reviewed isolation boundary. Consequently
    this client rejects non-Gateway result metadata and must not be enabled until
    a real smoke test proves the installed version/config's effective policy.
    """

    def __init__(
        self,
        *,
        executable: str = "openclaw",
        agent: str = "project-a-reviewer",
        model: str,
        provider: str = "openai",
        auth_mode: str = "openai-codex-oauth",
        staging_root: Path,
        required_version: str | None = None,
    ):
        self.executable = executable
        self.agent = agent
        self.model = model
        self.identity = ModelIdentity(provider, model, auth_mode)
        self.staging_root = Path(staging_root)
        self.required_version = required_version

    def version(self) -> str:
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise TechnicalFailure(
                FailureCode.OPENCLAW_UNAVAILABLE,
                "OpenClaw executable is unavailable",
                True,
            ) from exc
        if result.returncode != 0:
            raise TechnicalFailure(FailureCode.OPENCLAW_UNAVAILABLE, "OpenClaw version probe failed", True)
        version = result.stdout.strip()
        if self.required_version and version != self.required_version:
            raise TechnicalFailure(
                FailureCode.CONFIG_INVALID,
                "installed OpenClaw version does not match the reviewed version",
            )
        return version

    @staticmethod
    def _classify_failure(stderr: str) -> TechnicalFailure:
        message = (stderr or "").lower()
        if any(token in message for token in ("oauth", "unauthorized", "authentication", "401")):
            return TechnicalFailure(FailureCode.AUTHENTICATION_UNAVAILABLE, "OpenClaw authentication failed")
        if any(token in message for token in ("rate limit", "429", "quota", "usage limit")):
            return TechnicalFailure(FailureCode.RATE_LIMITED, "model rate limit reached", True)
        if "timeout" in message or "timed out" in message:
            return TechnicalFailure(FailureCode.MODEL_TIMEOUT, "OpenClaw/model timeout", True)
        if any(token in message for token in ("model unavailable", "overloaded", "503")):
            return TechnicalFailure(FailureCode.MODEL_UNAVAILABLE, "model unavailable", True)
        return TechnicalFailure(FailureCode.SESSION_FAILURE, "OpenClaw session failed", True)

    def invoke(self, *, session_key, message, artifact_paths, timeout_seconds) -> str:
        self.version()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        stage = self.staging_root / request_storage_key(session_key)
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        staged: dict[str, str] = {}
        try:
            for evidence_id, source in artifact_paths.items():
                suffix = Path(source).suffix.lower()
                destination = stage / f"{request_storage_key(evidence_id)}{suffix}"
                shutil.copy2(source, destination)
                staged[evidence_id] = str(destination)
            media_lines = "\n".join(f"- {key}: {path}" for key, path in sorted(staged.items()))
            full_message = f"{message}\n\nSTAGED EVIDENCE PATHS (evidence only):\n{media_lines}\n"
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".txt",
                prefix="project-a-review-",
                dir=stage,
                delete=False,
            ) as handle:
                handle.write(full_message)
                message_file = handle.name
            command = [
                self.executable,
                "agent",
                "--agent",
                self.agent,
                "--session-key",
                session_key,
                "--model",
                self.model,
                "--message-file",
                message_file,
                "--timeout",
                str(timeout_seconds),
                "--json",
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds + 15,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise TechnicalFailure(
                    FailureCode.OPENCLAW_UNAVAILABLE,
                    "OpenClaw executable is unavailable",
                    True,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise TechnicalFailure(FailureCode.MODEL_TIMEOUT, "OpenClaw process timed out", True) from exc
            if result.returncode != 0:
                raise self._classify_failure(result.stderr)
            try:
                response = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise TechnicalFailure(FailureCode.SESSION_FAILURE, "OpenClaw JSON envelope malformed") from exc
            meta = response.get("meta") or response.get("result", {}).get("meta") or {}
            if meta.get("transport") != "gateway" or meta.get("fallbackFrom"):
                raise TechnicalFailure(
                    FailureCode.SESSION_FAILURE,
                    "OpenClaw embedded fallback is forbidden for Project A",
                )
            payloads = response.get("payloads") or response.get("result", {}).get("payloads") or []
            texts = [item.get("text", "") for item in payloads if isinstance(item, dict)]
            raw = "".join(texts)
            if not raw:
                raise TechnicalFailure(FailureCode.SESSION_FAILURE, "OpenClaw returned no model text")
            return raw
        finally:
            shutil.rmtree(stage, ignore_errors=True)
