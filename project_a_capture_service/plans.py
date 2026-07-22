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


@dataclass(frozen=True)
class CapturePlan:
    version: str
    stage: str
    capture_scope: str
    views: tuple[ViewPlan, ...]
    structured_reads: tuple[dict[str, Any], ...]
    screenshots: tuple[dict[str, Any], ...]


VIEWS = {
    "xau_intraday": ViewPlan("xau_intraday", "cpPWuLlN", "XAUUSD", "ICMARKETS", ("1m", "5m")),
    "xau_30m_15m": ViewPlan("xau_30m_15m", "avpCVaw2", "XAUUSD", "ICMARKETS", ("15m", "30m")),
    "xau_htf": ViewPlan("xau_htf", "pNqcbOmu", "XAUUSD", "ICMARKETS", ("4H", "D", "W")),
    "dxy_15m": ViewPlan("dxy_15m", "n9qjfufV", "DXY", "TVC", ("15m",)),
    "renko": ViewPlan("renko", "YclFo8Ax", "XAUUSD", "ICMARKETS", ("5s",)),
}

E1_READ_IDS = frozenset({
    "read_9333_xau_current",
    "read_9333_xau_closed_ohlc_1m_5m",
    "read_9333_xau_macd_1m_5m",
    "read_9333_renko_5s",
    "read_9333_xau_5s_price_action",
})
E1_SCREENSHOT_IDS = frozenset({"screenshot_9333_xau_intraday", "screenshot_9333_renko"})
PLAN_SHA256S = {
    "LIQ_BASELINE": "aae83eeb026a108506ed0778d9a5520c364733ccc1b96272850c7b98fdc8a856",
    "E1_DELTA": "66db257d9055950113f71172d184dd5f2f855d079d9723ba728ad8d953963852",
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


validate_frozen_plans()
