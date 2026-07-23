"""Persistent Project A analysis worker.

The worker owns durable trigger consumption. It accepts only completed evidence
from the MCP evidence capture boundary and calls no provider unless the explicit
one-request SHADOW activation gate is satisfied.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from capture.base import ROOT
from contracts import canonical_json
from project_a_capture_service.cdp import SCRIPT_ID, SCRIPT_SHA256, SCRIPT_VERSION
from project_a_capture_service.schemas import (
    CAPTURE_INPUT_SCHEMA, CAPTURE_OUTPUT_SCHEMA, CAPTURE_PLAN_VERSION, CDP_ENDPOINT, TOOL_NAME,
)
from project_a_capture_service.local_identity import attest_capture_listener

from .provider import (
    OpenAIProviderConfig,
    OpenAIResponsesProvider,
    ProviderFailure,
    request_manifest_sha256,
)
from .store import AnalysisStore, CapturedEvidence


class EvidenceCapture(Protocol):
    def capture(self, job: dict[str, Any]) -> CapturedEvidence | None: ...


class Provider(Protocol):
    enabled: bool
    model: str

    def invoke(self, *, job: dict, evidence: CapturedEvidence,
               client_request_id: str, idempotency_key: str): ...


class DisabledEvidenceCapture:
    def capture(self, job: dict[str, Any]) -> CapturedEvidence | None:
        del job
        return None


class McpToolCapture:
    """Invoke one configured, loopback MCP capture tool from the worker."""

    def __init__(self, *, server_url: str, tool_name: str, token: str,
                 artifact_root: str | Path, expected_server_pid: int | None = None):
        parsed = urlsplit(server_url)
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.path != "/mcp" or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.port
        ):
            raise ValueError("PROJECT_A_MCP_SERVER_URL must be exact loopback HTTP /mcp")
        if tool_name != TOOL_NAME:
            raise ValueError(f"PROJECT_A_MCP_CAPTURE_TOOL must be {TOOL_NAME}")
        if len(token.encode("utf-8")) < 32 or len(token.encode("utf-8")) > 256:
            raise ValueError("PROJECT_A_CAPTURE_TOKEN must contain 32..256 UTF-8 bytes")
        self.server_url = server_url
        self.tool_name = tool_name
        self.token = token
        self.artifact_root = Path(artifact_root)
        self.server_port = int(parsed.port)
        self.expected_server_pid = expected_server_pid

    def _attest_server_listener(self) -> None:
        if not isinstance(self.expected_server_pid, int):
            raise ValueError("PROJECT_A_CAPTURE_SERVER_PID must be configured")
        attest_capture_listener(port=self.server_port, expected_pid=self.expected_server_pid)

    @staticmethod
    def _attribute(value: Any, *names: str, default=None):
        for name in names:
            if isinstance(value, dict) and name in value:
                return value[name]
            if hasattr(value, name):
                return getattr(value, name)
        return default

    async def _call(self, job: dict[str, Any]):
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise ValueError("official MCP client package is unavailable") from exc
        context = json.loads(job["request_context_json"])
        capture_request = context["capture"]
        accepted = capture_request.get("accepted_request", {})
        capture_plan_sha256 = hashlib.sha256(canonical_json({
            "structured_reads": accepted.get("structured_reads", []),
            "screenshot_requests": accepted.get("screenshot_requests", []),
        }).encode("utf-8")).hexdigest()
        canonical_event = context["canonical_event"]
        arguments = {
            "request_id": job["job_id"], "story_id": job["story_id"],
            "analysis_id": job["analysis_id"], "stage": job["stage"],
            "capture_scope": job["capture_scope"],
            "canonical_event_id": job["canonical_event_id"],
            "event_timestamp": canonical_event["source_bar_time"],
            "liquidity_event_facts": capture_request["liquidity_event_facts"],
            "expected_account": "Jonesy_Wong", "expected_symbol": "ICMARKETS:XAUUSD",
            "required_capture_plan_version": CAPTURE_PLAN_VERSION,
            "capture_plan_sha256": capture_plan_sha256,
            "capture_request_sha256": hashlib.sha256(
                canonical_json(capture_request).encode("utf-8")
            ).hexdigest(),
        }
        self._attest_server_listener()
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + self.token},
            timeout=httpx.Timeout(60, connect=3), follow_redirects=False, trust_env=False,
        ) as http_client:
            async with streamable_http_client(self.server_url, http_client=http_client) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    if (
                        len(tools.tools) != 1 or tools.tools[0].name != self.tool_name
                        or tools.tools[0].inputSchema != CAPTURE_INPUT_SCHEMA
                        or tools.tools[0].outputSchema != CAPTURE_OUTPUT_SCHEMA
                    ):
                        raise ValueError("MCP tool inventory differs from the fixed capture boundary")
                    return await session.call_tool(self.tool_name, arguments=arguments)

    @staticmethod
    def _atomic_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("MCP artifact identity conflict")
            return
        temp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def capture(self, job: dict[str, Any]) -> CapturedEvidence | None:
        result = asyncio.run(self._call(job))
        if self._attribute(result, "isError", "is_error", default=False):
            raise ValueError("MCP capture tool returned an error")
        structured = self._attribute(result, "structuredContent", "structured_content")
        if not isinstance(structured, dict):
            raise ValueError("MCP capture tool omitted structuredContent")
        capture_request = json.loads(job["request_context_json"])["capture"]
        required = {
            "status": "COMPLETED",
            "request_id": job["job_id"],
            "job_id": job["job_id"],
            "story_id": job["story_id"],
            "analysis_id": job["analysis_id"],
            "event_timestamp": json.loads(job["request_context_json"])[
                "canonical_event"
            ]["source_bar_time"],
            "script_id": SCRIPT_ID,
            "script_version": SCRIPT_VERSION,
            "stage": job["stage"],
            "capture_scope": job["capture_scope"], "source_event_id": job["canonical_event_id"],
            "symbol": "XAUUSD", "feed": "ICMARKETS", "evidence_freshness": "FRESH",
            "capture_request_sha256": hashlib.sha256(
                canonical_json(capture_request).encode("utf-8")
            ).hexdigest(),
            "structured_reads_complete": True, "screenshots_complete": True,
            "account": "Jonesy_Wong", "capture_plan_version": CAPTURE_PLAN_VERSION,
            "cdp_endpoint": CDP_ENDPOINT, "script_sha256": SCRIPT_SHA256,
            "capture_plan_sha256": hashlib.sha256(canonical_json({
                "structured_reads": capture_request.get("accepted_request", {}).get("structured_reads", []),
                "screenshot_requests": capture_request.get("accepted_request", {}).get("screenshot_requests", []),
            }).encode("utf-8")).hexdigest(),
        }
        if any(structured.get(key) != value for key, value in required.items()):
            raise ValueError("MCP result does not attest the requested capture binding")
        evidence_document = structured.get("structured_evidence")
        evidence_ids = structured.get("image_evidence_ids")
        if not isinstance(evidence_document, dict) or not evidence_document:
            raise ValueError("MCP structured evidence is absent")
        content = self._attribute(result, "content", default=[]) or []
        image_blocks = [item for item in content if self._attribute(item, "type") == "image"]
        expected_images = 5 if job["stage"] == "LIQ_BASELINE" else 2
        if (
            not isinstance(evidence_ids, list) or len(evidence_ids) != len(image_blocks)
            or len(evidence_ids) != expected_images or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ValueError("MCP image evidence identities do not match image blocks")
        directory = (self.artifact_root / job["job_id"]).resolve()
        images = []
        dimensions = {}
        image_payloads: list[tuple[Path, bytes]] = []
        total_bytes = 0
        for index, (evidence_id, block) in enumerate(zip(evidence_ids, image_blocks)):
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError("MCP image evidence ID is invalid")
            media_type = self._attribute(block, "mimeType", "mime_type")
            encoded = self._attribute(block, "data")
            if media_type != "image/png" or not isinstance(encoded, str) or len(encoded) > 5_592_424:
                raise ValueError("MCP image block is invalid")
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("MCP image block is not valid base64") from exc
            from project_a_capture_service.cdp import CaptureFailure, validate_png
            try:
                dimensions[evidence_id] = validate_png(data)
            except CaptureFailure as exc:
                raise ValueError("MCP PNG evidence failed size/dimension validation") from exc
            total_bytes += len(data)
            suffix = ".png"
            content_hash = hashlib.sha256(data).hexdigest()
            path = directory / (
                f"{index:02d}_{hashlib.sha256(evidence_id.encode()).hexdigest()[:16]}_"
                f"{content_hash[:16]}{suffix}"
            )
            image_payloads.append((path, data))
            images.append({
                "evidence_id": evidence_id, "path": str(path), "media_type": media_type,
                "sha256": content_hash,
            })
        if total_bytes > (20 * 1024 * 1024 if job["stage"] == "LIQ_BASELINE" else 8 * 1024 * 1024):
            raise ValueError("MCP stage image budget exceeded")
        artifacts = structured.get("screenshot_artifacts")
        if not isinstance(artifacts, list) or [item.get("evidence_id") for item in artifacts] != evidence_ids:
            raise ValueError("MCP screenshot artifact manifest order is invalid")
        by_id = {item["evidence_id"]: item for item in images}
        if any(
            artifact.get("sha256") != by_id[artifact["evidence_id"]]["sha256"]
            or artifact.get("mime_type") != "image/png"
            or (artifact.get("width"), artifact.get("height")) != dimensions[artifact["evidence_id"]]
            for artifact in artifacts
        ):
            raise ValueError("MCP screenshot artifact manifest does not bind returned bytes")
        immutable_manifest_sha = structured.get("immutable_evidence_manifest_sha256")
        if (
            not isinstance(immutable_manifest_sha, str) or len(immutable_manifest_sha) != 64
            or any(character not in "0123456789abcdef" for character in immutable_manifest_sha)
        ):
            raise ValueError("MCP immutable evidence manifest hash is invalid")
        for path, data in image_payloads:
            self._atomic_bytes(path, data)
        manifest = {
            **required,
            "capture_method": "MCP",
            "captured_at": structured.get("captured_at"),
            "mcp_tool": self.tool_name,
            "image_count": len(images),
            "capture_plan_version": structured.get("capture_plan_version"),
            "immutable_evidence_manifest_sha256": structured.get(
                "immutable_evidence_manifest_sha256"
            ),
        }
        captured = CapturedEvidence(manifest, evidence_document, tuple(images))
        captured.validate()
        return captured


class AnalysisWorker:
    def __init__(self, *, store: AnalysisStore, capture: EvidenceCapture, provider: Provider,
                 worker_id: str, clock: Callable[[], datetime] | None = None,
                 after_provider_hook: Callable[[], None] | None = None,
                 approved_job_id: str | None = None,
                 approved_request_sha256: str | None = None):
        self.store = store
        self.capture = capture
        self.provider = provider
        self.worker_id = worker_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.after_provider_hook = after_provider_hook
        self.approved_job_id = approved_job_id
        self.approved_request_sha256 = approved_request_sha256

    def tick(self) -> dict[str, Any]:
        now = self.clock()
        self.store.heartbeat(worker_id=self.worker_id, provider_enabled=self.provider.enabled, at=now)
        captures = 0
        pending = self.store.claim_capture_job(worker_id=self.worker_id, at=self.clock())
        for pending in (() if pending is None else (pending,)):
            try:
                evidence = self.capture.capture(pending)
                if evidence is None:
                    raise ValueError("capture boundary returned no completed evidence")
                self.store.record_capture(
                    pending["job_id"], evidence, at=self.clock(), worker_id=self.worker_id,
                    lease_token=pending["capture_lease_token"],
                )
                captures += 1
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                try:
                    retry = self.store.capture_failure(
                        pending["job_id"], at=self.clock(), worker_id=self.worker_id,
                        lease_token=pending["capture_lease_token"],
                        code="CAPTURE_INTEGRITY_FAILURE", detail=str(exc),
                    )
                except RuntimeError:
                    retry = {"status": "PENDING_CAPTURE", "failure_code": "CAPTURE_LEASE_LOST"}
                self.store.heartbeat(
                    worker_id=self.worker_id, provider_enabled=self.provider.enabled,
                    at=self.clock(), error_code="CAPTURE_INTEGRITY_FAILURE",
                )
                return {"ok": False, "provider_enabled": self.provider.enabled,
                        "captured": 0, "processed": 0,
                        "status": retry["status"], "failure_code": retry["failure_code"]}
        if not self.provider.enabled:
            return {"ok": True, "provider_enabled": False, "captured": captures, "processed": 0}
        job = self.store.claim_next(
            worker_id=self.worker_id, at=self.clock(), job_id=self.approved_job_id,
        )
        if job is None:
            return {"ok": True, "provider_enabled": True, "captured": captures, "processed": 0}
        try:
            job, evidence = self.store.load_job_bundle(job["job_id"])
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            self.store.technical_failure(
                job, code="CAPTURE_INTEGRITY_FAILURE", detail=str(exc), at=self.clock(),
                model=self.provider.model,
            )
            return {"ok": False, "provider_enabled": True, "captured": captures,
                    "processed": 0, "status": "TECHNICAL_FAILURE",
                    "failure_code": "CAPTURE_INTEGRITY_FAILURE"}
        try:
            manifest_sha = request_manifest_sha256(job, evidence, self.provider.model)
            if self.approved_request_sha256 is not None and manifest_sha != self.approved_request_sha256:
                raise ProviderFailure(
                    "APPROVAL_IDENTITY_MISMATCH",
                    "captured request no longer matches the Jones-approved request SHA-256",
                )
            client_request_id = "pa-client-" + job["analysis_id"].split("_", 1)[1]
            self.store.begin_provider_attempt(
                job, model=self.provider.model, request_manifest_sha256=manifest_sha,
                client_request_id=client_request_id, at=self.clock(),
            )
            idempotency_key = "project-a-" + job["analysis_id"]
            response = self.provider.invoke(
                job=job, evidence=evidence, client_request_id=client_request_id,
                idempotency_key=idempotency_key,
            )
            if self.after_provider_hook:
                self.after_provider_hook()
            self.store.complete(
                job=job, grade=response.grade, model=response.model,
                client_request_id=response.client_request_id,
                response_id=response.response_id,
                provider_request_id=response.provider_request_id,
                raw_response_sha256=response.raw_response_sha256,
                request_manifest_sha256=manifest_sha,
                at=self.clock(),
            )
            return {"ok": True, "provider_enabled": True, "captured": captures,
                    "processed": 1, "status": "COMPLETED", "analysis_id": job["analysis_id"]}
        except ProviderFailure as exc:
            self.store.technical_failure(
                job, code=exc.code, detail=exc.detail, at=self.clock(), model=self.provider.model,
            )
            self.store.heartbeat(worker_id=self.worker_id, provider_enabled=True,
                                 at=self.clock(), error_code=exc.code)
            return {"ok": False, "provider_enabled": True, "captured": captures,
                    "processed": 1, "status": "TECHNICAL_FAILURE", "failure_code": exc.code}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("PROJECT_A_DB", str(ROOT / "storage" / "project_a.db")))
    parser.add_argument("--evidence-root", default=os.getenv(
        "PROJECT_A_MCP_EVIDENCE_ROOT", str(ROOT / "storage" / "project_a_mcp_evidence")))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--approve-one-shadow-request", action="store_true")
    parser.add_argument("--approved-job-id")
    parser.add_argument("--approved-request-sha256")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.approve_one_shadow_request and (
        not args.once or not args.approved_job_id or not args.approved_request_sha256
    ):
        raise SystemExit(
            "--approve-one-shadow-request requires --once, --approved-job-id, and --approved-request-sha256"
        )
    if args.approved_request_sha256 and (
        len(args.approved_request_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in args.approved_request_sha256)
    ):
        raise SystemExit("--approved-request-sha256 must be lowercase 64-hex")
    config = OpenAIProviderConfig.from_env(
        approve_one_shadow_request=args.approve_one_shadow_request,
    )
    provider = OpenAIResponsesProvider(config)
    store = AnalysisStore(args.db)
    mcp_url = os.getenv("PROJECT_A_MCP_SERVER_URL", "").strip()
    mcp_tool = os.getenv("PROJECT_A_MCP_CAPTURE_TOOL", "").strip()
    capture_token = os.getenv("PROJECT_A_CAPTURE_TOKEN", "")
    capture_server_pid_text = os.getenv("PROJECT_A_CAPTURE_SERVER_PID", "").strip()
    configured = [bool(mcp_url), bool(mcp_tool), bool(capture_token), bool(capture_server_pid_text)]
    if any(configured) and not all(configured):
        raise SystemExit(
            "PROJECT_A_MCP_SERVER_URL, PROJECT_A_MCP_CAPTURE_TOOL, PROJECT_A_CAPTURE_TOKEN, "
            "and PROJECT_A_CAPTURE_SERVER_PID "
            "must be configured together"
        )
    try:
        capture_server_pid = int(capture_server_pid_text) if capture_server_pid_text else None
    except ValueError as exc:
        raise SystemExit("PROJECT_A_CAPTURE_SERVER_PID must be a positive integer") from exc
    capture: EvidenceCapture = (
        McpToolCapture(server_url=mcp_url, tool_name=mcp_tool, token=capture_token,
                       artifact_root=args.evidence_root, expected_server_pid=capture_server_pid)
        if all(configured) else DisabledEvidenceCapture()
    )
    worker = AnalysisWorker(
        store=store,
        capture=capture,
        provider=provider,
        worker_id=f"analysis-worker-{os.getpid()}-{uuid4().hex[:8]}",
        approved_job_id=args.approved_job_id,
        approved_request_sha256=args.approved_request_sha256,
    )
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            result = worker.tick()
            print(canonical_json(result), flush=True)
            if args.once:
                return 0 if result.get("ok") else 2
            time.sleep(max(0.2, args.poll_seconds))
    except (KeyboardInterrupt, OSError, RuntimeError, ValueError) as exc:
        print(canonical_json({"ok": False, "error": type(exc).__name__, "detail": str(exc)[:240]}),
              file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
