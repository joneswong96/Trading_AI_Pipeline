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

from capture.base import ROOT
from contracts import canonical_json

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

    def __init__(self, *, server_url: str, tool_name: str, artifact_root: str | Path):
        parsed = urlsplit(server_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1", "localhost", "::1"
        }:
            raise ValueError("PROJECT_A_MCP_SERVER_URL must be loopback HTTP(S)")
        if not tool_name or tool_name.strip() != tool_name:
            raise ValueError("PROJECT_A_MCP_CAPTURE_TOOL must be an exact tool name")
        self.server_url = server_url
        self.tool_name = tool_name
        self.artifact_root = Path(artifact_root)

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
        async with streamable_http_client(self.server_url) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                capture_request = json.loads(job["request_context_json"])["capture"]
                return await session.call_tool(
                    self.tool_name,
                    arguments={
                        "schema_version": "project_a.mcp_capture_request/1.0",
                        "job_id": job["job_id"],
                        "stage": job["stage"],
                        "capture_scope": job["capture_scope"],
                        "source_event_id": job["canonical_event_id"],
                        "symbol": "XAUUSD", "feed": "ICMARKETS",
                        "capture_request_sha256": hashlib.sha256(
                            canonical_json(capture_request).encode("utf-8")
                        ).hexdigest(),
                        "request": capture_request,
                    },
                )

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
            "status": "COMPLETED", "job_id": job["job_id"], "stage": job["stage"],
            "capture_scope": job["capture_scope"], "source_event_id": job["canonical_event_id"],
            "symbol": "XAUUSD", "feed": "ICMARKETS", "evidence_freshness": "FRESH",
            "capture_request_sha256": hashlib.sha256(
                canonical_json(capture_request).encode("utf-8")
            ).hexdigest(),
            "structured_reads_complete": True, "screenshots_complete": True,
        }
        if any(structured.get(key) != value for key, value in required.items()):
            raise ValueError("MCP result does not attest the requested capture binding")
        evidence_document = structured.get("structured_evidence")
        evidence_ids = structured.get("image_evidence_ids")
        if not isinstance(evidence_document, dict) or not evidence_document:
            raise ValueError("MCP structured evidence is absent")
        content = self._attribute(result, "content", default=[]) or []
        image_blocks = [item for item in content if self._attribute(item, "type") == "image"]
        if not isinstance(evidence_ids, list) or len(evidence_ids) != len(image_blocks):
            raise ValueError("MCP image evidence identities do not match image blocks")
        directory = (self.artifact_root / job["job_id"]).resolve()
        images = []
        for index, (evidence_id, block) in enumerate(zip(evidence_ids, image_blocks)):
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError("MCP image evidence ID is invalid")
            media_type = self._attribute(block, "mimeType", "mime_type")
            encoded = self._attribute(block, "data")
            if media_type not in {"image/png", "image/jpeg", "image/webp"} or not isinstance(encoded, str):
                raise ValueError("MCP image block is invalid")
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("MCP image block is not valid base64") from exc
            signature_valid = (
                media_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")
                or media_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff")
                or media_type == "image/webp" and len(data) >= 12
                and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
            )
            if not signature_valid:
                raise ValueError("MCP image bytes do not match the declared media type")
            suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[media_type]
            content_hash = hashlib.sha256(data).hexdigest()
            path = directory / (
                f"{index:02d}_{hashlib.sha256(evidence_id.encode()).hexdigest()[:16]}_"
                f"{content_hash[:16]}{suffix}"
            )
            self._atomic_bytes(path, data)
            images.append({
                "evidence_id": evidence_id, "path": str(path), "media_type": media_type,
                "sha256": content_hash,
            })
        manifest = {
            **required,
            "capture_method": "MCP",
            "captured_at": structured.get("captured_at"),
            "mcp_tool": self.tool_name,
            "image_count": len(images),
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
        for pending in self.store.pending_capture_jobs()[:1]:
            try:
                evidence = self.capture.capture(pending)
                if evidence is not None:
                    self.store.record_capture(pending["job_id"], evidence, at=self.clock())
                    captures += 1
            except (OSError, ValueError, KeyError, TypeError):
                self.store.heartbeat(
                    worker_id=self.worker_id, provider_enabled=self.provider.enabled,
                    at=self.clock(), error_code="CAPTURE_INTEGRITY_FAILURE",
                )
                return {"ok": False, "provider_enabled": self.provider.enabled,
                        "captured": 0, "processed": 0,
                        "status": "PENDING_CAPTURE", "failure_code": "CAPTURE_INTEGRITY_FAILURE"}
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
    capture: EvidenceCapture = (
        McpToolCapture(server_url=mcp_url, tool_name=mcp_tool, artifact_root=args.evidence_root)
        if mcp_url and mcp_tool else DisabledEvidenceCapture()
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
