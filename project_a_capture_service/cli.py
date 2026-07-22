"""Operator commands for the Project A read-only capture service."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .audit import AuditStore
from .capture import CaptureEngine
from .local_identity import attest_capture_listener
from .schemas import CAPTURE_INPUT_SCHEMA, CAPTURE_OUTPUT_SCHEMA, TOOL_NAME
from .service import ServiceConfig, create_app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    commands.add_parser("health")
    commands.add_parser("mcp-ready")
    commands.add_parser("preflight")
    audit = commands.add_parser("audit")
    audit.add_argument("--limit", type=int, default=50)
    return parser


def _client(config: ServiceConfig) -> httpx.Client:
    _attest_configured_service(config)
    return httpx.Client(
        headers={"Authorization": "Bearer " + config.token}, timeout=5,
        follow_redirects=False, trust_env=False,
    )


async def _mcp_ready(config: ServiceConfig) -> dict:
    identity = _attest_configured_service(config)
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + config.token}, timeout=10,
        follow_redirects=False, trust_env=False,
    ) as http_client:
        async with streamable_http_client(config.mcp_url, http_client=http_client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()
    if len(tools.tools) != 1 or tools.tools[0].name != TOOL_NAME:
        raise RuntimeError("MCP tool inventory is not exactly the frozen capture tool")
    tool = tools.tools[0]
    if tool.inputSchema != CAPTURE_INPUT_SCHEMA or tool.outputSchema != CAPTURE_OUTPUT_SCHEMA:
        raise RuntimeError("MCP tool schema drift")
    return {"ok": True, "url": config.mcp_url, "tool": TOOL_NAME,
            "listener_pid": identity["pid"],
            "tool_count": 1, "schema_exact": True, "capture_invoked": False}


def _attest_configured_service(config: ServiceConfig) -> dict[str, object]:
    value = os.getenv("PROJECT_A_CAPTURE_SERVER_PID", "").strip()
    try:
        expected_pid = int(value)
    except ValueError as exc:
        raise ValueError("PROJECT_A_CAPTURE_SERVER_PID must be a positive integer") from exc
    return attest_capture_listener(port=config.port, expected_pid=expected_pid)


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = ServiceConfig.from_env()
        if args.command == "serve":
            uvicorn.run(
                create_app(config), host=config.host, port=config.port,
                log_level="info", access_log=False,
            )
            return 0
        if args.command == "health":
            with _client(config) as client:
                response = client.get(f"http://127.0.0.1:{config.port}/health")
                response.raise_for_status()
                value = response.json()
        elif args.command == "mcp-ready":
            value = asyncio.run(_mcp_ready(config))
        elif args.command == "preflight":
            value = CaptureEngine(
                artifact_root=config.artifact_root,
                audit_store=AuditStore(config.database_path),
            ).preflight()
        elif args.command == "audit":
            value = AuditStore(config.database_path).audit(limit=args.limit)
        else:  # pragma: no cover
            raise RuntimeError("unknown command")
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300]},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
