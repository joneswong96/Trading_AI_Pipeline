from __future__ import annotations

import json
import asyncio
import hashlib
import socket
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
from pydantic import ValidationError

from contracts import canonical_json
from project_a_capture_service.audit import AuditStore
from project_a_capture_service.capture import CaptureEngine
from project_a_capture_service.cdp import (
    ALLOWED_CDP_METHODS,
    CaptureFailure,
    Target,
    _TargetSession,
    select_targets,
    validate_view,
)
from project_a_capture_service.plans import PLAN_SHA256S, VIEWS, plan_for_stage, plan_sha256
from project_a_capture_service.schemas import (
    CAPTURE_INPUT_SCHEMA,
    CAPTURE_PLAN_VERSION,
    CaptureToolRequest,
)
from project_a_capture_service.service import ServiceConfig, create_app, run_serialized_capture
from project_a_analysis.store import _validate_capture_results
from project_a_analysis.worker import McpToolCapture


NOW = datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc)
TOKEN = "t" * 48


def png() -> bytes:
    out = BytesIO()
    Image.new("RGB", (640, 400), "black").save(out, format="PNG")
    return out.getvalue()


def study(name, values=(1.0, 0.5, 0.5)):
    return {
        "description": name, "short_description": name,
        "plots": [{"id": key, "type": "line"} for key in ("macd", "signal", "histogram")],
        "current": [NOW.timestamp(), *values],
        "closed": [(NOW - timedelta(minutes=1)).timestamp(), *values],
        "previous_closed": [(NOW - timedelta(minutes=2)).timestamp(), *(v - 0.1 for v in values)],
    }


def chart(interval: str, symbol: str, seconds: int):
    current_time = (NOW - timedelta(seconds=1)).timestamp()
    closed_time = (NOW - timedelta(seconds=seconds + 1)).timestamp()
    previous_time = (NOW - timedelta(seconds=seconds * 2 + 1)).timestamp()
    base = 3400.0 if "XAUUSD" in symbol else 100.0
    recent = [
        {"time": closed_time - offset * seconds, "open": base - 0.2, "high": base + 0.5,
         "low": base - 0.5, "close": base + offset * 0.01}
        for offset in range(25)
    ]
    studies = []
    if interval in {"1", "5", "15", "30"} and "XAUUSD" in symbol:
        studies.extend([study("MACD 12 26 close 9"), study("Average True Range", (2.0, 2.0, 2.0))])
    if interval in {"1", "5"}:
        studies.extend([study("Liquidity V2", (3398.0, 3402.0, 3400.0)), study("SNR HPA", (3395.0, 3405.0, 1.0))])
    if interval == "5S":
        studies.append(study("Synthetic Renko Sniper E1", (7.0, 3.0, 1.0)))
    return {
        "index": 0, "interval": interval, "symbol": symbol, "chart_type": 1,
        "last_index": 100, "quote": {
            "price": base, "bid": base - 0.05, "ask": base + 0.05,
            "source_time": current_time, "symbol": symbol,
            "feed": symbol.split(":", 1)[0],
            "provider_id": "icmarkets" if symbol.startswith("ICMARKETS:") else "tvc",
            "source": "TradingViewApi.mainSeries.quotes",
        },
        "current_bar": {"time": current_time, "open": base - 0.1, "high": base + 0.2,
                        "low": base - 0.2, "close": base},
        "closed_bar": {"time": closed_time, "open": base - 0.2, "high": base + 0.4,
                       "low": base - 0.4, "close": base + 0.1},
        "previous_closed_bar": {"time": previous_time, "open": base - 0.3,
                                "high": base + 0.1, "low": base - 0.5, "close": base - 0.1},
        "recent_closed_bars": recent, "studies": studies,
    }


INTERVALS = {
    "xau_intraday": (("1", 60), ("5", 300)),
    "xau_30m_15m": (("15", 900), ("30", 1800)),
    "xau_htf": (("240", 14400), ("D", 86400), ("W", 604800)),
    "dxy_15m": (("15", 900),),
    "renko": (("5S", 5),),
}


def raw_state(role: str):
    view = VIEWS[role]
    symbol = f"{view.feed}:{view.symbol}"
    return {
        "script_id": "tradingview_read_state", "script_version": "1.1",
        "page_ready": True, "location_url": f"https://www.tradingview.com/chart/{view.layout_id}/",
        "title": "TradingView", "observed_epoch_ms": int(NOW.timestamp() * 1000),
        "account_markers": [{"href": "/u/Jonesy_Wong/", "username": "",
                             "aria_label": "", "title": "", "text": ""}],
        "charts": [
            {**chart(interval, symbol, seconds),
             "chart_type": 19 if chart_type == "volume_candles" else 1}
            for (interval, seconds), chart_type in zip(INTERVALS[role], view.chart_types)
        ],
        "alert_inventory_count": 7,
    }


class FakeBackend:
    def __init__(self):
        self.targets = [Target(
            f"target-{role}", f"https://www.tradingview.com/chart/{view.layout_id}/", "TV",
            f"ws://127.0.0.1:9333/devtools/page/target-{role}", view.layout_id,
        ) for role, view in VIEWS.items()]
        self.states = {role: raw_state(role) for role in VIEWS}
        self.read_calls = 0
        self.screenshot_calls = 0

    def discover(self):
        return list(self.targets)

    def read(self, target):
        self.read_calls += 1
        role = next(role for role, view in VIEWS.items() if view.layout_id == target.layout_id)
        return deepcopy(self.states[role])

    def screenshot(self, target):
        self.screenshot_calls += 1
        return png()


def request(stage="LIQ_BASELINE"):
    return CaptureToolRequest(
        request_id="job_" + "a" * 32, story_id="story_" + "b" * 32,
        analysis_id="analysis_" + "c" * 32, stage=stage,
        capture_scope="FULL_BASELINE" if stage == "LIQ_BASELINE" else "BOUNDED_DELTA",
        canonical_event_id="evt_project_a", event_timestamp="2026-07-22T02:59:00.000Z",
        liquidity_event_facts={
            "producer_id": "LIQ_V2", "producer_revision": "9", "event": "LIQ_TOUCH",
            "level_id": "liq1_" + "1" * 64, "level_version": "1", "side": "ASK",
            "level_price": "3401.00", "touch_count": 1,
            "source_bar_time": "2026-07-22T02:59:00.000Z",
            "symbol": "XAUUSD", "feed": "ICMARKETS", "anchor_timeframe": "5m",
        },
        expected_account="Jonesy_Wong", expected_symbol="ICMARKETS:XAUUSD",
        required_capture_plan_version=CAPTURE_PLAN_VERSION,
        capture_plan_sha256=PLAN_SHA256S[stage],
        capture_request_sha256="d" * 64,
    )


def engine(tmp_path, backend=None):
    backend = backend or FakeBackend()
    return CaptureEngine(
        artifact_root=tmp_path / "artifacts", audit_store=AuditStore(tmp_path / "audit.db"),
        backend=backend, clock=lambda: NOW,
    ), backend


@pytest.fixture
def live_service(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = ServiceConfig(
        "127.0.0.1", port, TOKEN, tmp_path / "service.db", tmp_path / "service-artifacts"
    )
    server = uvicorn.Server(uvicorn.Config(
        create_app(config, backend=FakeBackend(), clock=lambda: NOW), host=config.host, port=config.port,
        log_level="error", access_log=False,
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/health",
                headers={"Authorization": "Bearer " + TOKEN}, timeout=0.5,
            )
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("test capture service did not start")
    yield config
    server.should_exit = True
    thread.join(timeout=10)


def test_frozen_plans_and_schema_are_exact():
    baseline = plan_for_stage("LIQ_BASELINE")
    delta = plan_for_stage("E1_DELTA")
    assert (len(baseline.structured_reads), len(baseline.screenshots)) == (11, 5)
    assert (len(delta.structured_reads), len(delta.screenshots)) == (5, 2)
    assert plan_sha256(baseline) == PLAN_SHA256S["LIQ_BASELINE"]
    assert plan_sha256(delta) == PLAN_SHA256S["E1_DELTA"]
    assert CAPTURE_INPUT_SCHEMA["additionalProperties"] is False
    with pytest.raises(ValidationError):
        CaptureToolRequest.model_validate({**request().model_dump(), "url": "https://example.com"})
    invalid_touch = request().model_dump(mode="json")
    invalid_touch["liquidity_event_facts"]["touch_count"] = True
    with pytest.raises(ValidationError):
        CaptureToolRequest.model_validate(invalid_touch)


def test_service_config_refuses_non_loopback_or_reserved_port(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_A_CAPTURE_TOKEN", TOKEN)
    monkeypatch.setenv("PROJECT_A_CAPTURE_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="127.0.0.1"):
        ServiceConfig.from_env()
    monkeypatch.setenv("PROJECT_A_CAPTURE_HOST", "127.0.0.1")
    monkeypatch.setenv("PROJECT_A_CAPTURE_PORT", "9333")
    with pytest.raises(ValueError, match="outside"):
        ServiceConfig.from_env()


def test_http_security_requires_token_host_origin_and_loopback(live_service):
    url = f"http://127.0.0.1:{live_service.port}/health"
    assert httpx.get(url).status_code == 401
    assert httpx.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert httpx.get(url, headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    assert httpx.get(url, headers={"Authorization": "Bearer " + TOKEN,
                                   "Host": "localhost"}).status_code == 400
    assert httpx.get(url, headers={"Authorization": "Bearer " + TOKEN,
                                   "Origin": "https://evil.example"}).status_code == 403
    assert httpx.get(url, headers={"Authorization": "Bearer " + TOKEN,
                                   "X-Forwarded-For": "127.0.0.1"}).status_code == 403


def test_mcp_inventory_unknown_tool_and_unknown_field_are_rejected(live_service):
    async def run():
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + TOKEN}, trust_env=False,
            follow_redirects=False, timeout=10,
        ) as client:
            async with streamable_http_client(live_service.mcp_url, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert [tool.name for tool in tools.tools] == ["project_a_capture_snapshot"]
                    unknown = await session.call_tool("generic_browser", arguments={})
                    assert unknown.isError is True
                    arguments = request().model_dump(mode="json")
                    arguments["url"] = "https://example.com"
                    invalid = await session.call_tool("project_a_capture_snapshot", arguments=arguments)
                    assert invalid.isError is True
    asyncio.run(run())


def test_live_service_result_crosses_worker_and_store_validation(live_service, tmp_path, monkeypatch):
    plan = plan_for_stage("LIQ_BASELINE")
    capture_request = json.loads(canonical_json({
        "scope": "FULL_BASELINE",
        "mode": "MCP_STRUCTURED_READS_AND_SCREENSHOTS",
        "accepted_request": {
            "structured_reads": list(plan.structured_reads),
            "screenshot_requests": list(plan.screenshots),
        },
        "liquidity_event_facts": request().liquidity_event_facts.model_dump(mode="json"),
    }))
    job = {
        "job_id": "job_" + "a" * 32,
        "story_id": "story_" + "b" * 32,
        "analysis_id": "analysis_" + "c" * 32,
        "stage": "LIQ_BASELINE", "capture_scope": "FULL_BASELINE",
        "canonical_event_id": "evt_project_a",
        "request_context_json": canonical_json({
            "capture": capture_request,
            "canonical_event": {"source_bar_time": "2026-07-22T02:59:00.000Z"},
        }),
    }
    client = McpToolCapture(
        server_url=live_service.mcp_url, tool_name="project_a_capture_snapshot",
        token=TOKEN, artifact_root=tmp_path / "worker-artifacts",
    )
    monkeypatch.setattr(client, "_attest_server_listener", lambda: None)
    raw_result = asyncio.run(client._call(job))
    assert client._attribute(raw_result, "isError", "is_error", default=False) is False, raw_result
    evidence = client.capture(job)
    _validate_capture_results(evidence, capture_request, NOW)


@pytest.mark.parametrize("field", [
    "request_id", "story_id", "analysis_id", "event_timestamp", "script_id", "script_version",
])
def test_worker_rejects_mcp_result_identity_mutation(
    live_service, tmp_path, field,
):
    plan = plan_for_stage("LIQ_BASELINE")
    capture_request = json.loads(canonical_json({
        "scope": "FULL_BASELINE",
        "mode": "MCP_STRUCTURED_READS_AND_SCREENSHOTS",
        "accepted_request": {
            "structured_reads": list(plan.structured_reads),
            "screenshot_requests": list(plan.screenshots),
        },
        "liquidity_event_facts": request().liquidity_event_facts.model_dump(mode="json"),
    }))
    job = {
        "job_id": "job_" + "e" * 32,
        "story_id": "story_" + "f" * 32,
        "analysis_id": "analysis_" + "1" * 32,
        "stage": "LIQ_BASELINE",
        "capture_scope": "FULL_BASELINE",
        "canonical_event_id": "evt_project_a_identity",
        "request_context_json": canonical_json({
            "capture": capture_request,
            "canonical_event": {"source_bar_time": "2026-07-22T02:59:00.000Z"},
        }),
    }

    class MutatingMcp(McpToolCapture):
        async def _call(self, job):
            result = await super()._call(job)
            structured = self._attribute(
                result, "structuredContent", "structured_content"
            )
            structured[field] = "mismatched"
            return result

    client = MutatingMcp(
        server_url=live_service.mcp_url,
        tool_name="project_a_capture_snapshot",
        token=TOKEN,
        artifact_root=tmp_path / "worker-artifacts",
    )
    client._attest_server_listener = lambda: None
    with pytest.raises(ValueError, match="requested capture binding"):
        client.capture(job)


def test_cdp_method_allowlist_has_no_mutation_capability():
    assert ALLOWED_CDP_METHODS == {"Runtime.evaluate", "Page.captureScreenshot"}
    session = object.__new__(_TargetSession)
    with pytest.raises(CaptureFailure, match="CDP_METHOD_FORBIDDEN"):
        session._send("Page.navigate", {"url": "https://example.com"})
    invalid_target = Target(
        "target-x", "https://www.tradingview.com/chart/cpPWuLlN/", "TV",
        "ws://127.0.0.1:4999/devtools/page/target-x", "cpPWuLlN",
    )
    with pytest.raises(CaptureFailure, match="CDP_ENDPOINT_IDENTITY_MISMATCH"):
        _TargetSession(invalid_target)


def test_fixed_script_contains_no_mutation_or_external_io_primitive():
    script = (Path(__file__).parents[1] / "project_a_capture_service" / "scripts" /
              "tradingview_read_state_v1.js").read_text(encoding="utf-8")
    forbidden = (
        "Input.dispatch", "Page.navigate", "setResolution", "setSymbol", "setChartType",
        ".click(", ".focus(", "bringToFront", "localStorage", "sessionStorage",
        "document.cookie", "fetch(", "XMLHttpRequest", "WebSocket(", "createElement(",
    )
    assert all(value not in script for value in forbidden)
    normalized = script.replace("\r\n", "\n").encode("utf-8")
    assert hashlib.sha256(normalized).hexdigest() == (
        "226390af9f21c728b19a73fabcdb7edb9cdf0e5b3d0d24bf223bb5e29297aadd"
    )


def test_duplicate_and_missing_targets_fail_closed():
    plan = plan_for_stage("E1_DELTA")
    backend = FakeBackend()
    with pytest.raises(CaptureFailure, match="TARGET_MISSING"):
        select_targets(plan, backend.targets[1:])
    with pytest.raises(CaptureFailure, match="TARGET_AMBIGUOUS"):
        select_targets(plan, backend.targets + [backend.targets[0]])


@pytest.mark.parametrize("url", [
    "https://user:pass@www.tradingview.com/chart/cpPWuLlN/",
    "https://www.tradingview.com:444/chart/cpPWuLlN/",
])
def test_target_url_rejects_non_exact_tradingview_authority(url):
    from project_a_capture_service.cdp import _layout_id
    with pytest.raises(CaptureFailure, match="LAYOUT_MISMATCH"):
        _layout_id(url)


@pytest.mark.parametrize("mutation,code", [
    (lambda raw: raw.update(account_markers=[]), "ACCOUNT_MISMATCH"),
    (lambda raw: raw["charts"][0].update(symbol="OTHER:XAUUSD"), "SYMBOL_MISMATCH"),
    (lambda raw: raw["charts"][0].update(interval="99"), "TIMEFRAME_MISMATCH"),
    (lambda raw: raw["charts"][0].update(chart_type=1), "CHART_TYPE_MISMATCH"),
    (lambda raw: raw["charts"][1]["current_bar"].update(time=(NOW - timedelta(hours=2)).timestamp()), "SOURCE_STALE"),
])
def test_view_identity_mutations_fail_closed(mutation, code):
    view = VIEWS["xau_intraday"]
    target = FakeBackend().targets[0]
    raw = raw_state("xau_intraday")
    mutation(raw)
    with pytest.raises(CaptureFailure, match=code):
        validate_view(view, target, raw, now=NOW)


def test_visual_context_only_volume_bar_age_does_not_claim_numeric_staleness():
    view = VIEWS["xau_intraday"]
    target = FakeBackend().targets[0]
    raw = raw_state("xau_intraday")
    raw["charts"][0]["current_bar"]["time"] = (NOW - timedelta(hours=2)).timestamp()
    snapshot = validate_view(view, target, raw, now=NOW)
    assert snapshot.charts[0]["chart_type_name"] == "volume_candles"


def test_visual_context_only_volume_future_time_fails_closed():
    view = VIEWS["xau_intraday"]
    target = FakeBackend().targets[0]
    raw = raw_state("xau_intraday")
    raw["charts"][0]["current_bar"]["time"] = (NOW + timedelta(minutes=1)).timestamp()
    with pytest.raises(CaptureFailure, match="future-dated"):
        validate_view(view, target, raw, now=NOW)


def test_current_quote_persists_exact_bid_ask_spread_and_provenance(tmp_path):
    capture, _ = engine(tmp_path)
    result = capture.capture(request())
    current = next(
        item for item in result.structured["structured_evidence"]["structured_read_results"]
        if item["request_id"] == "read_9333_xau_current"
    )
    fields = current["fields"]
    assert fields["bid"] == 3399.95
    assert fields["ask"] == 3400.05
    assert fields["spread"] == pytest.approx(fields["ask"] - fields["bid"])
    assert fields["source_time"] == "2026-07-22T02:59:59.000Z"
    assert fields["quote_source"] == "TradingViewApi.mainSeries.quotes"
    assert fields["quote_provider_id"] == "icmarkets"
    assert fields["quote_source_symbol"] == "ICMARKETS:XAUUSD"
    assert fields["quote_source_feed"] == "ICMARKETS"
    assert fields["atr"] == 1.0
    assert fields["atr_period"] == 14
    assert fields["atr_method"] == "SMA_TRUE_RANGE_14_CONFIRMED_5M_BARS"
    assert fields["normalized_spread"] == pytest.approx(
        (fields["ask"] - fields["bid"]) / fields["atr"]
    )
    assert fields["liquidity_level_id"] == "liq1_" + "1" * 64
    assert fields["liquidity_level_price"] == 3401.0
    assert fields["liquidity_touch_count"] == 1
    assert fields["distance_reference_price"] == fields["ask"]
    assert fields["distance_to_level"] == pytest.approx(3401.0 - fields["ask"])
    assert fields["distance_atr"] == pytest.approx(fields["distance_to_level"])


def test_current_liq_and_atr_do_not_require_indicator_plot_series(tmp_path):
    backend = FakeBackend()
    chart_5m = backend.states["xau_intraday"]["charts"][1]
    chart_5m["studies"] = [
        item for item in chart_5m["studies"]
        if "Liquidity" not in item["description"] and "Average True Range" not in item["description"]
    ]
    capture, _ = engine(tmp_path, backend)
    result = capture.capture(request())
    current = next(
        item for item in result.structured["structured_evidence"]["structured_read_results"]
        if item["request_id"] == "read_9333_xau_current"
    )
    assert current["fields"]["liquidity_level_id"] == "liq1_" + "1" * 64
    assert current["fields"]["atr"] == 1.0


def test_bid_level_distance_uses_validated_bid_quote(tmp_path):
    capture_request = request()
    bid_facts = capture_request.liquidity_event_facts.model_copy(update={
        "side": "BID", "level_price": "3399.00",
    })
    capture_request = capture_request.model_copy(update={"liquidity_event_facts": bid_facts})
    capture, _ = engine(tmp_path)
    result = capture.capture(capture_request)
    current = next(
        item for item in result.structured["structured_evidence"]["structured_read_results"]
        if item["request_id"] == "read_9333_xau_current"
    )
    fields = current["fields"]
    assert fields["distance_reference_price"] == fields["bid"]
    assert fields["distance_to_level"] == pytest.approx(fields["bid"] - 3399.0)


def test_atr14_rejects_incomplete_confirmed_bar_inputs(tmp_path):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["recent_closed_bars"] = (
        backend.states["xau_intraday"]["charts"][1]["recent_closed_bars"][:14]
    )
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="ATR14 requires fifteen confirmed 5m bars"):
        capture.capture(request())


@pytest.mark.parametrize("field,value", [
    ("bid", None),
    ("bid", ""),
    ("bid", "3399.95"),
    ("bid", float("nan")),
    ("ask", float("inf")),
    ("price", float("-inf")),
])
def test_current_quote_rejects_missing_non_numeric_and_non_finite_values(tmp_path, field, value):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["quote"][field] = value
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="is not a finite number"):
        capture.capture(request())


def test_current_quote_rejects_crossed_market(tmp_path):
    backend = FakeBackend()
    quote = backend.states["xau_intraday"]["charts"][1]["quote"]
    quote["ask"] = quote["bid"] - 0.01
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="quote ask is below bid"):
        capture.capture(request())


@pytest.mark.parametrize("field,value", [
    ("price", 0),
    ("bid", 0),
    ("ask", -1),
])
def test_current_quote_rejects_non_positive_values(tmp_path, field, value):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["quote"][field] = value
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="must be positive"):
        capture.capture(request())


@pytest.mark.parametrize("field,value,code", [
    ("source", "TradingViewApi.mainSeries.lastValueData", "STRUCTURED_READ_INCOMPLETE"),
    ("symbol", "ICMARKETS:XAGUSD", "SYMBOL_MISMATCH"),
    ("feed", "OANDA", "SYMBOL_MISMATCH"),
    ("provider_id", "other", "SYMBOL_MISMATCH"),
    ("source_time", (NOW - timedelta(hours=1)).timestamp(), "SOURCE_STALE"),
    ("source_time", (NOW + timedelta(minutes=1)).timestamp(), "SOURCE_STALE"),
])
def test_current_quote_rejects_unapproved_identity_and_stale_time(tmp_path, field, value, code):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["quote"][field] = value
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match=code):
        capture.capture(request())


def test_current_quote_accepts_240_second_freshness_boundary(tmp_path):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["quote"]["source_time"] = (
        NOW - timedelta(seconds=240)
    ).timestamp()
    capture, _ = engine(tmp_path, backend)
    assert capture.capture(request()).structured["status"] == "COMPLETED"


def test_current_quote_rejects_beyond_240_second_freshness_boundary(tmp_path):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["quote"]["source_time"] = (
        NOW - timedelta(seconds=241)
    ).timestamp()
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="quote timestamp is stale"):
        capture.capture(request())


def test_preflight_requires_structured_quote_and_screenshot_success_cannot_bypass_it(tmp_path):
    backend = FakeBackend()
    backend.states["xau_intraday"]["charts"][1]["quote"]["bid"] = None
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="quote.bid is not a finite number"):
        capture.preflight()
    assert backend.screenshot_calls == 0


def test_preflight_records_quote_fields_and_fixed_source_hash(tmp_path):
    capture, backend = engine(tmp_path)
    result = capture.preflight()
    assert len(result["structured_reads"]) == 1
    current = next(
        item for item in result["structured_reads"]
        if item["request_id"] == "read_9333_xau_current"
    )
    assert current["fields"]["bid"] == 3399.95
    assert current["fields"]["ask"] == 3400.05
    assert len(current["sha256"]) == 64
    assert result["script_version"] == "1.1"
    assert result["script_sha256"] == (
        "226390af9f21c728b19a73fabcdb7edb9cdf0e5b3d0d24bf223bb5e29297aadd"
    )
    assert backend.screenshot_calls == 5


@pytest.mark.parametrize("seconds,detail", [
    (-3600, "ATR14 source is stale"),
    (600, "ATR14 source is future-dated"),
])
def test_preflight_rejects_stale_or_future_atr_bar_inputs(tmp_path, seconds, detail):
    backend = FakeBackend()
    chart_5m = backend.states["xau_intraday"]["charts"][1]
    chart_5m["closed_bar"]["time"] += seconds
    for bar in chart_5m["recent_closed_bars"]:
        bar["time"] += seconds
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match=detail):
        capture.preflight()
    assert backend.screenshot_calls == 0


def test_baseline_capture_exact_manifest_audit_and_idempotent_replay(tmp_path):
    capture, backend = engine(tmp_path)
    first = capture.capture(request())
    assert len(first.images) == 5
    reads = first.structured["structured_evidence"]["structured_read_results"]
    assert len(reads) == 11
    assert [item for item in reads if item["request_id"] == "read_9222_dxy_1m"] == [{
        "request_id": "read_9222_dxy_1m", "status": "UNAVAILABLE",
        "reason": "SOURCE_PORT_NOT_AUTHORIZED",
    }]
    assert first.structured["image_evidence_ids"] == [
        "screenshot_9333_xau_intraday", "screenshot_9333_xau_30m_15m",
        "screenshot_9333_xau_htf", "screenshot_9333_dxy_15m", "screenshot_9333_renko",
    ]
    calls = (backend.read_calls, backend.screenshot_calls)
    replay = capture.capture(request())
    assert replay.structured == first.structured and replay.images == first.images
    assert (backend.read_calls, backend.screenshot_calls) == calls
    assert capture.audit_store.audit()["chain_valid"] is True


def test_retry_restores_ledger_committed_result_after_file_write_crash(tmp_path):
    backend = FakeBackend()
    audit_path = tmp_path / "audit.db"
    artifact_root = tmp_path / "artifacts"
    first_store = AuditStore(audit_path)
    capture = CaptureEngine(
        artifact_root=artifact_root, audit_store=first_store,
        backend=backend, clock=lambda: NOW,
    )

    original_write = capture._write_immutable

    def fail_result_write(path, data):
        if path.name == "result.json":
            path.write_bytes(data[:len(data) // 2])
            raise OSError("simulated crash after partial file write")
        original_write(path, data)

    capture._write_immutable = fail_result_write
    with pytest.raises(OSError, match="simulated crash after partial file write"):
        capture.capture(request())
    calls = (backend.read_calls, backend.screenshot_calls)

    retry_store = AuditStore(audit_path)
    retry = CaptureEngine(
        artifact_root=artifact_root, audit_store=retry_store,
        backend=backend, clock=lambda: NOW + timedelta(seconds=1),
    )
    recovered = retry.capture(request())
    assert recovered.structured["request_id"] == request().request_id
    assert (backend.read_calls, backend.screenshot_calls) == calls
    audit = retry_store.audit()
    assert audit["chain_valid"] is True
    assert [record["action"] for record in audit["records"]].count("CAPTURE_COMPLETED") == 1


def test_uncommitted_orphan_result_is_rejected_before_browser_access(tmp_path):
    capture, backend = engine(tmp_path)
    orphan = capture._attempt_dir(request().request_id) / "result.json"
    orphan.write_text('{"structured":{}}\n', encoding="utf-8")
    with pytest.raises(CaptureFailure, match="ARTIFACT_IDENTITY_CONFLICT"):
        capture.capture(request())
    assert backend.read_calls == 0 and backend.screenshot_calls == 0
    assert capture.audit_store.audit()["records"][-1]["action"] == "CAPTURE_FAILED"


def test_capture_timeout_is_audited_and_never_releases_to_parallel_capture(tmp_path):
    backend = FakeBackend()
    ticks = iter((0.0, 0.0, 46.0))
    capture = CaptureEngine(
        artifact_root=tmp_path / "artifacts",
        audit_store=AuditStore(tmp_path / "audit.db"),
        backend=backend,
        clock=lambda: NOW,
        timeout_seconds=45,
        monotonic=lambda: next(ticks),
    )
    with pytest.raises(CaptureFailure, match="CAPTURE_TIMEOUT"):
        capture.capture(request())
    records = capture.audit_store.audit()["records"]
    assert records[-1]["action"] == "CAPTURE_FAILED"
    assert backend.read_calls == 0 and backend.screenshot_calls == 0


def test_request_cancellation_holds_capture_lock_until_thread_finishes():
    started = threading.Event()
    release = threading.Event()

    class BlockingEngine:
        def capture(self, _request):
            started.set()
            release.wait(timeout=5)
            return "done"

    async def probe():
        lock = asyncio.Semaphore(1)
        first = asyncio.create_task(run_serialized_capture(BlockingEngine(), request(), lock))
        assert await asyncio.to_thread(started.wait, 2)
        first.cancel()
        await asyncio.sleep(0)
        second_acquire = asyncio.create_task(lock.acquire())
        await asyncio.sleep(0.05)
        assert second_acquire.done() is False
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(second_acquire, timeout=2)
        lock.release()

    asyncio.run(probe())


def test_e1_capture_is_bounded_delta(tmp_path):
    capture, _ = engine(tmp_path)
    package = capture.capture(request("E1_DELTA"))
    assert len(package.images) == 2
    assert {item["request_id"] for item in package.structured["structured_evidence"]["structured_read_results"]} == {
        "read_9333_xau_current", "read_9333_xau_closed_ohlc_5m",
        "read_9333_xau_macd_5m", "read_9333_renko_5s",
        "read_9333_xau_5s_price_action",
    }


def test_request_id_replay_conflict_is_terminal(tmp_path):
    capture, _ = engine(tmp_path)
    capture.capture(request())
    changed = request().model_copy(update={"canonical_event_id": "different-event"})
    with pytest.raises(CaptureFailure, match="REQUEST_REPLAY_CONFLICT"):
        capture.capture(changed)


def test_capture_plan_hash_mismatch_is_terminal(tmp_path):
    capture, backend = engine(tmp_path)
    changed = request().model_copy(update={"capture_plan_sha256": "0" * 64})
    with pytest.raises(CaptureFailure, match="CAPTURE_PLAN_MISMATCH"):
        capture.capture(changed)
    assert backend.read_calls == 0 and backend.screenshot_calls == 0


def test_preflight_compares_browser_state_without_mutation(tmp_path):
    capture, backend = engine(tmp_path)
    result = capture.preflight()
    assert result["status"] == "PASS" and result["mutation_detected"] is False
    assert result["browser_state_before_sha256"] == result["browser_state_after_sha256"]
    assert len(result["views"]) == 5 and backend.screenshot_calls == 5
    identities = {item["role"]: item for item in result["views"]}
    assert identities["xau_intraday"]["chart_types"] == [
        "volume_candles", "standard_candles",
    ]
    assert identities["xau_htf"]["chart_types"] == [
        "volume_candles", "volume_candles", "volume_candles",
    ]


def test_wrong_target_state_after_screenshot_fails_mutation_guard(tmp_path):
    backend = FakeBackend()
    original = backend.read

    def drifting(target):
        value = original(target)
        if backend.read_calls > 5 and target.layout_id == "cpPWuLlN":
            value["alert_inventory_count"] += 1
        return value

    backend.read = drifting
    capture, _ = engine(tmp_path, backend)
    with pytest.raises(CaptureFailure, match="BROWSER_STATE_CHANGED"):
        capture.preflight()
