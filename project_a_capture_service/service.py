"""Authenticated loopback Streamable HTTP MCP service with one read-only tool."""
from __future__ import annotations

import asyncio
import base64
import hmac
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from capture.base import ROOT

from .audit import AuditStore
from .capture import CaptureEngine
from .cdp import CaptureFailure, ReadOnlyBackend
from .schemas import (
    CAPTURE_INPUT_SCHEMA,
    CAPTURE_OUTPUT_SCHEMA,
    CAPTURE_PLAN_VERSION,
    CDP_ENDPOINT,
    TOOL_NAME,
    CaptureToolRequest,
)


DEFAULT_PORT = 8765
MAX_REQUEST_BODY = 65_536
CAPTURE_RATE_LIMIT = 4
CAPTURE_RATE_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int
    token: str
    database_path: Path
    artifact_root: Path

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        host = os.getenv("PROJECT_A_CAPTURE_HOST", "127.0.0.1").strip()
        try:
            port = int(os.getenv("PROJECT_A_CAPTURE_PORT", str(DEFAULT_PORT)))
        except ValueError as exc:
            raise ValueError("PROJECT_A_CAPTURE_PORT must be an integer") from exc
        token = os.getenv("PROJECT_A_CAPTURE_TOKEN", "")
        if host != "127.0.0.1":
            raise ValueError("capture service must bind exactly 127.0.0.1")
        if not 1024 <= port <= 65535 or port in {4999, 8000, 9222, 9333}:
            raise ValueError("PROJECT_A_CAPTURE_PORT is outside the approved service range")
        if len(token.encode("utf-8")) < 32 or len(token.encode("utf-8")) > 256:
            raise ValueError("PROJECT_A_CAPTURE_TOKEN must contain 32..256 UTF-8 bytes")
        return cls(
            host=host, port=port, token=token,
            database_path=Path(os.getenv(
                "PROJECT_A_CAPTURE_DB", str(ROOT / "storage" / "project_a_capture_service.db")
            )).resolve(),
            artifact_root=Path(os.getenv(
                "PROJECT_A_CAPTURE_ARTIFACT_ROOT", str(ROOT / "storage" / "project_a_capture_evidence")
            )).resolve(),
        )

    @property
    def mcp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"


class CaptureRateLimiter:
    def __init__(self):
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        now = time.monotonic()
        async with self._lock:
            while self._calls and self._calls[0] <= now - CAPTURE_RATE_WINDOW_SECONDS:
                self._calls.popleft()
            if len(self._calls) >= CAPTURE_RATE_LIMIT:
                raise CaptureFailure("RATE_LIMITED", "capture rate limit exceeded")
            self._calls.append(now)


async def run_serialized_capture(engine: CaptureEngine, request: CaptureToolRequest,
                                 capture_lock: asyncio.Semaphore):
    async with capture_lock:
        worker = asyncio.create_task(asyncio.to_thread(engine.capture, request))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # A disconnected/cancelled caller must not release the global capture
            # lock while its read-only CDP thread is still running.
            try:
                await worker
            finally:
                raise


class LocalSecurityMiddleware:
    """Reject non-loopback, proxy-shaped, oversized, or unauthenticated requests."""

    def __init__(self, app, *, config: ServiceConfig):
        self.app = app
        self.config = config

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await Response(status_code=400)(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        client = scope.get("client") or ("", 0)
        host = headers.get("host", "")
        origin = headers.get("origin")
        forwarded = any(name in headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip"))
        expected_host = f"127.0.0.1:{self.config.port}"
        authorization = headers.get("authorization", "")
        expected_auth = "Bearer " + self.config.token
        try:
            length = int(headers.get("content-length", "0") or "0")
        except ValueError:
            length = MAX_REQUEST_BODY + 1
        if client[0] != "127.0.0.1" or forwarded:
            response = JSONResponse({"error": "LOOPBACK_CLIENT_REQUIRED"}, status_code=403)
        elif host != expected_host:
            response = JSONResponse({"error": "HOST_REJECTED"}, status_code=400)
        elif origin is not None and origin != f"http://{expected_host}":
            response = JSONResponse({"error": "ORIGIN_REJECTED"}, status_code=403)
        elif length > MAX_REQUEST_BODY:
            response = JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
        elif not hmac.compare_digest(authorization.encode("utf-8"), expected_auth.encode("utf-8")):
            response = JSONResponse({"error": "AUTH_INVALID"}, status_code=401)
        else:
            consumed = 0

            async def bounded_receive():
                nonlocal consumed
                message = await receive()
                if message.get("type") == "http.request":
                    consumed += len(message.get("body", b""))
                    if consumed > MAX_REQUEST_BODY:
                        raise RuntimeError("REQUEST_TOO_LARGE")
                return message

            try:
                await self.app(scope, bounded_receive, send)
            except RuntimeError as exc:
                if str(exc) != "REQUEST_TOO_LARGE":
                    raise
                await JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)(scope, receive, send)
            return
        await response(scope, receive, send)


def create_app(config: ServiceConfig, *, backend: ReadOnlyBackend | None = None,
               clock: Callable[[], datetime] | None = None) -> Starlette:
    audit = AuditStore(config.database_path)
    engine = CaptureEngine(
        artifact_root=config.artifact_root, audit_store=audit, backend=backend, clock=clock,
    )
    server = Server(
        "project-a-read-only-capture", version="1.0",
        instructions="One fixed read-only Project A capture tool. No browser mutation capability.",
    )
    limiter = CaptureRateLimiter()
    capture_lock = asyncio.Semaphore(1)

    @server.list_tools()
    async def list_tools():
        return [types.Tool(
            name=TOOL_NAME,
            title="Project A fixed read-only capture",
            description="Capture the frozen LIQ baseline or E1 delta plan from approved 9333 tabs.",
            inputSchema=CAPTURE_INPUT_SCHEMA,
            outputSchema=CAPTURE_OUTPUT_SCHEMA,
            annotations=types.ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
            ),
        )]

    @server.call_tool(validate_input=True)
    async def call_tool(name: str, arguments: dict[str, Any] | None):
        if name != TOOL_NAME:
            raise McpError(types.ErrorData(code=types.METHOD_NOT_FOUND, message="UNKNOWN_TOOL"))
        try:
            request = CaptureToolRequest.model_validate(arguments or {})
            await limiter.acquire()
            package = await run_serialized_capture(engine, request, capture_lock)
            content = [
                types.ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png")
                for data in package.images
            ]
            return content, package.structured
        except ValidationError as exc:
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="INPUT_SCHEMA_REJECTED")) from exc
        except CaptureFailure as exc:
            raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=exc.code)) from exc

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"127.0.0.1:{config.port}"],
        allowed_origins=[f"http://127.0.0.1:{config.port}"],
    )
    manager = StreamableHTTPSessionManager(
        app=server, json_response=True, stateless=True, security_settings=security,
    )

    class McpAsgiEndpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    async def health(_request: Request):
        chain = audit.audit(limit=1)
        return JSONResponse({
            "ok": chain["chain_valid"], "service": "project-a-read-only-capture",
            "bind": f"127.0.0.1:{config.port}", "mcp_path": "/mcp", "tool": TOOL_NAME,
            "capture_plan_version": CAPTURE_PLAN_VERSION, "cdp_endpoint": CDP_ENDPOINT,
            "audit_chain_valid": chain["chain_valid"],
        })

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    inner = Starlette(
        routes=[Route("/health", health, methods=["GET"]), Route("/mcp", McpAsgiEndpoint())],
        lifespan=lifespan,
    )
    return LocalSecurityMiddleware(inner, config=config)
