"""Internal fixed capture plans; callers cannot select targets or operations."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from contracts import canonical_json

from project_a.evidence_bundle import (
    ApprovedScreenshotRequestAdapter,
    Port9222RequestAdapter,
    Port9333RequestAdapter,
    RequestLevel,
    approved_source_identities,
)

from .schemas import CAPTURE_PLAN_VERSION


@dataclass(frozen=True)
class ViewPlan:
    role: str
    layout_id: str
    symbol: str
    feed: str
    timeframes: tuple[str, ...]
    chart_types: tuple[str, ...]


@dataclass(frozen=True)
class CapturePlan:
    version: str
    stage: str
    capture_scope: str
    views: tuple[ViewPlan, ...]
    structured_reads: tuple[dict[str, Any], ...]
    screenshots: tuple[dict[str, Any], ...]


VIEWS = {
    "xau_intraday": ViewPlan("xau_intraday", "cpPWuLlN", "XAUUSD", "ICMARKETS", ("1m", "5m"), ("volume_candles", "standard_candles")),
    "xau_30m_15m": ViewPlan("xau_30m_15m", "avpCVaw2", "XAUUSD", "ICMARKETS", ("15m", "30m"), ("standard_candles", "standard_candles")),
    "xau_htf": ViewPlan("xau_htf", "pNqcbOmu", "XAUUSD", "ICMARKETS", ("4H", "D", "W"), ("volume_candles", "volume_candles", "volume_candles")),
    "dxy_15m": ViewPlan("dxy_15m", "n9qjfufV", "DXY", "TVC", ("15m",), ("standard_candles",)),
    "renko": ViewPlan("renko", "YclFo8Ax", "XAUUSD", "ICMARKETS", ("5s",), ("standard_candles",)),
}

E1_READ_IDS = frozenset({
    "read_9333_xau_current",
    "read_9333_xau_closed_ohlc_5m",
    "read_9333_xau_macd_5m",
    "read_9333_renko_5s",
    "read_9333_xau_5s_price_action",
})
E1_SCREENSHOT_IDS = frozenset({"screenshot_9333_xau_intraday", "screenshot_9333_renko"})
PLAN_SHA256S = {
    "LIQ_BASELINE": "d75e2f5da1b833fd542a4be9ddf4a75e2b69a1cb87c599928dd2d88af7e7fb88",
    "E1_DELTA": "270a938a5b09a5d3e36ef28e40593d1f4530045fbec94b1a6178ce154612fad5",
}


def _canonical(item: Any) -> dict[str, Any]:
    return dict(item.canonical())


def _baseline_parts() -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    sources = approved_source_identities()
    level = RequestLevel.LIQ_RESEARCH_CAPTURE
    reads = (
        Port9333RequestAdapter().compile_requests(sources, level)
        + Port9222RequestAdapter().compile_requests(sources, level)
    )
    screenshots = ApprovedScreenshotRequestAdapter().compile_requests(sources, level)
    return tuple(_canonical(item) for item in reads), tuple(_canonical(item) for item in screenshots)


def plan_for_stage(stage: str) -> CapturePlan:
    reads, screenshots = _baseline_parts()
    if stage == "LIQ_BASELINE":
        selected_reads = reads
        selected_screenshots = screenshots
        scope = "FULL_BASELINE"
    elif stage == "E1_DELTA":
        selected_reads = tuple(item for item in reads if item["request_id"] in E1_READ_IDS)
        selected_screenshots = tuple(
            item for item in screenshots if item["request_id"] in E1_SCREENSHOT_IDS
        )
        scope = "BOUNDED_DELTA"
    else:
        raise ValueError("CAPTURE_STAGE_UNSUPPORTED")
    roles = {
        item["source"]["role"] for item in (*selected_reads, *selected_screenshots)
        if item["source"]["port"] == 9333
    }
    return CapturePlan(
        version=CAPTURE_PLAN_VERSION,
        stage=stage,
        capture_scope=scope,
        views=tuple(VIEWS[role] for role in VIEWS if role in roles),
        structured_reads=selected_reads,
        screenshots=selected_screenshots,
    )


def plan_sha256(plan: CapturePlan) -> str:
    document = {
        "structured_reads": plan.structured_reads,
        "screenshot_requests": plan.screenshots,
    }
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def validate_frozen_plans() -> None:
    baseline = plan_for_stage("LIQ_BASELINE")
    delta = plan_for_stage("E1_DELTA")
    if len(baseline.screenshots) != 5 or len(delta.screenshots) != 2:
        raise RuntimeError("frozen screenshot cardinality drift")
    if {item["request_id"] for item in delta.structured_reads} != E1_READ_IDS:
        raise RuntimeError("frozen E1 structured-read plan drift")
    for plan in (baseline, delta):
        if plan_sha256(plan) != PLAN_SHA256S[plan.stage]:
            raise RuntimeError(f"frozen {plan.stage} capture plan hash drift")
        for view in plan.views:
            if view.layout_id not in {item.layout_id for item in VIEWS.values()}:
                raise RuntimeError("unapproved layout in capture plan")
            if len(view.timeframes) != len(view.chart_types):
                raise RuntimeError("chart-type allowlist is not aligned with timeframes")


validate_frozen_plans()
