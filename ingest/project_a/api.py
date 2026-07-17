"""Strict FastAPI boundary for versioned Project A events."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .config import ProjectAConfig
from .service import ProjectAIngestService, RuntimeReject

log = logging.getLogger("ingest.project_a")
router = APIRouter(tags=["project-a"])
_service: ProjectAIngestService | None = None


def configure_service(service: ProjectAIngestService | None) -> None:
    """Test/operator injection point; production remains lazily initialized."""
    global _service
    _service = service


def get_service() -> ProjectAIngestService:
    global _service
    if _service is None:
        _service = ProjectAIngestService(ProjectAConfig.from_env())
    return _service


async def _bounded_body(request: Request, limit: int) -> tuple[bytes, bool]:
    body = bytearray()
    async for chunk in request.stream():
        remaining = limit + 1 - len(body)
        if remaining > 0:
            body.extend(chunk[:remaining])
        if len(body) > limit:
            return bytes(body), False
    return bytes(body), True


def _metadata(request: Request) -> dict:
    return {
        "client": request.client.host if request.client else None,
        "forwarded_for": request.headers.get("x-forwarded-for"),
        "user_agent": request.headers.get("user-agent"),
        "transport": "HTTP",
    }


@router.post("/project-a/v0.2/events")
async def project_a_event(request: Request):
    service = get_service()
    raw, complete = await _bounded_body(request, service.config.max_body_bytes)
    pre_error = None if complete else RuntimeReject(
        "BODY_TOO_LARGE", "request body exceeds configured maximum", status=413,
        replay_eligible=False)
    result = service.receive(
        raw, content_type=request.headers.get("content-type"), method=request.method,
        source_metadata=_metadata(request), raw_complete=complete, pre_error=pre_error,
    )
    log.info(json.dumps({
        "result_code": result.result_code, "ingest_id": result.ingest_id,
        "event_id": result.event_id, "setup_id": result.setup_id,
        "transition": result.transition_code, "dispatch_key": result.dispatch_key,
    }, separators=(",", ":")))
    return JSONResponse(result.response(), status_code=result.http_status)


@router.post("/project-a/v1/events")
async def project_a_event_v1(request: Request):
    service = get_service()
    raw, complete = await _bounded_body(request, service.config.max_body_bytes)
    pre_error = None if complete else RuntimeReject(
        "BODY_TOO_LARGE", "request body exceeds configured maximum", status=413,
        replay_eligible=False)
    result = service.receive_v1(
        raw, content_type=request.headers.get("content-type"), method=request.method,
        source_metadata=_metadata(request), raw_complete=complete, pre_error=pre_error,
    )
    log.info(json.dumps({
        "contract": "PROJECT_A_WIRE_EVENT_V1",
        "result_code": result.result_code, "ingest_id": result.ingest_id,
        "event_id": result.event_id, "setup_id": result.setup_id,
        "transition": result.transition_code, "dispatch_key": result.dispatch_key,
    }, separators=(",", ":")))
    return JSONResponse(result.response(), status_code=result.http_status)


@router.get("/project-a/v0.2/health/live")
def project_a_liveness():
    return {"ok": True, "service": "project-a-ingest", "live_execution": False}


@router.get("/project-a/v0.2/health/ready")
def project_a_readiness():
    try:
        report = get_service().health()
        return JSONResponse(report, status_code=200 if report["ok"] else 503)
    except Exception as exc:
        return JSONResponse({
            "ok": False, "database_ready": False, "schema_ready": False,
            "outbox_ready": False, "configuration_ready": False,
            "shadow_mode": True, "live_execution": False,
            "detail": str(exc)[:500],
        }, status_code=503)


@router.get("/project-a/v0.2/metrics")
def project_a_metrics():
    return get_service().metrics()
