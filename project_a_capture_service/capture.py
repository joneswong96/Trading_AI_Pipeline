"""Fixed-plan capture orchestration and immutable evidence materialisation."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from contracts import canonical_json

from .audit import AuditStore
from .cdp import (
    CDP_ENDPOINT,
    SCRIPT_ID,
    SCRIPT_SHA256,
    SCRIPT_VERSION,
    CaptureFailure,
    ProductionCdpBackend,
    ReadOnlyBackend,
    ViewSnapshot,
    select_targets,
    utc_z,
    validate_png,
    validate_view,
)
from .plans import CapturePlan, plan_for_stage, plan_sha256
from .schemas import (
    CAPTURE_PLAN_VERSION,
    CaptureToolRequest,
    CaptureToolResult,
    ConstituentStatus,
    ScreenshotArtifact,
    ViewIdentity,
)


MAX_STRUCTURED_BYTES = 262_144
IMAGE_BUDGETS = {"LIQ_BASELINE": 20 * 1024 * 1024, "E1_DELTA": 8 * 1024 * 1024}
QUOTE_SOURCE = "TradingViewApi.mainSeries.quotes"
QUOTE_PROVIDER_ID = "icmarkets"
QUOTE_MAX_AGE_SECONDS = 240


@dataclass(frozen=True)
class CapturedPackage:
    structured: dict[str, Any]
    images: tuple[bytes, ...]


def _finite(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", f"{field} is not a finite number")
    return float(value)


def _bar(chart: dict[str, Any], name: str) -> dict[str, Any]:
    value = chart.get(name)
    if not isinstance(value, dict):
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", f"{chart.get('timeframe')}.{name} is missing")
    return {
        "time": value.get("time"),
        "open": _finite(value.get("open"), f"{name}.open"),
        "high": _finite(value.get("high"), f"{name}.high"),
        "low": _finite(value.get("low"), f"{name}.low"),
        "close": _finite(value.get("close"), f"{name}.close"),
    }


def _chart(view: ViewSnapshot, timeframe: str) -> dict[str, Any]:
    matches = [item for item in view.charts if item.get("timeframe") == timeframe]
    if len(matches) != 1:
        raise CaptureFailure("TIMEFRAME_MISMATCH", f"{view.plan.role}/{timeframe} is not unique")
    return matches[0]


def _study(chart: dict[str, Any], pattern: str) -> dict[str, Any]:
    matches = [
        item for item in chart.get("studies", [])
        if isinstance(item, dict) and re.search(pattern, str(item.get("description", "")), re.IGNORECASE)
    ]
    if len(matches) != 1:
        raise CaptureFailure(
            "STRUCTURED_READ_INCOMPLETE",
            f"{chart.get('timeframe')} study /{pattern}/ match count is {len(matches)}",
        )
    return matches[0]


def _plot_values(study: dict[str, Any], sample: str) -> dict[str, float]:
    raw = study.get(sample)
    plots = study.get("plots")
    if not isinstance(raw, list) or not isinstance(plots, list):
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "study values or plot metadata are missing")
    offset = 1 if len(raw) >= len(plots) + 1 else 0
    values: dict[str, float] = {}
    for index, plot in enumerate(plots):
        if not isinstance(plot, dict) or index + offset >= len(raw):
            continue
        value = raw[index + offset]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            key = str(plot.get("id") or f"plot_{index}")
            values[key] = float(value)
    if not values:
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "study has no finite plot values")
    return values


def _named_value(values: dict[str, float], pattern: str, fallback: int) -> float:
    matches = [value for key, value in values.items() if re.search(pattern, key, re.IGNORECASE)]
    if len(matches) == 1:
        return matches[0]
    ordered = list(values.values())
    if fallback >= len(ordered):
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", f"study plot /{pattern}/ is unavailable")
    return ordered[fallback]


def _source_time(bar: dict[str, Any]) -> str:
    from .cdp import _epoch
    return utc_z(_epoch(bar["time"]))


def _source_result(request: dict[str, Any], view: ViewSnapshot) -> dict[str, Any]:
    source = dict(request["source"])
    source["target_id"] = view.target.target_id
    return source


def _confirmed_atr14(chart: dict[str, Any]) -> tuple[float, str]:
    from .cdp import _epoch

    raw_bars = chart.get("recent_closed_bars")
    if not isinstance(raw_bars, list) or len(raw_bars) < 15:
        raise CaptureFailure(
            "STRUCTURED_READ_INCOMPLETE",
            "ATR14 requires fifteen confirmed 5m bars",
        )
    bars = []
    for index, raw in enumerate(raw_bars[:15]):
        if not isinstance(raw, dict):
            raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "ATR14 bar is missing")
        high = _finite(raw.get("high"), f"atr_bar_{index}.high")
        low = _finite(raw.get("low"), f"atr_bar_{index}.low")
        close = _finite(raw.get("close"), f"atr_bar_{index}.close")
        if high < low or not low <= close <= high:
            raise CaptureFailure(
                "STRUCTURED_READ_INCOMPLETE",
                "ATR14 bar OHLC ordering is invalid",
            )
        bars.append({
            "time": _epoch(raw.get("time")),
            "high": high,
            "low": low,
            "close": close,
        })
    if any(
        newer["time"] <= older["time"]
        for newer, older in zip(bars, bars[1:])
    ):
        raise CaptureFailure(
            "STRUCTURED_READ_INCOMPLETE",
            "ATR14 bars are not strictly newest-to-oldest",
        )
    chronological = list(reversed(bars))
    true_ranges = []
    for previous, current in zip(chronological, chronological[1:]):
        true_ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        ))
    atr = sum(true_ranges) / 14.0
    if not math.isfinite(atr) or atr <= 0:
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "calculated ATR14 is not positive")
    return atr, utc_z(bars[0]["time"])


def _quote_and_atr_fields(
    view: ViewSnapshot, chart: dict[str, Any], observed_at: str,
) -> dict[str, Any]:
    quote = chart.get("quote") if isinstance(chart.get("quote"), dict) else {}
    if quote.get("source") != QUOTE_SOURCE:
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "quote source identity is not approved")
    expected_symbol = f"{view.plan.feed}:{view.plan.symbol}"
    if str(quote.get("symbol") or "").upper() != expected_symbol:
        raise CaptureFailure("SYMBOL_MISMATCH", "quote symbol identity does not match the view")
    if str(quote.get("feed") or "").upper() != view.plan.feed:
        raise CaptureFailure("SYMBOL_MISMATCH", "quote feed identity does not match the view")
    if str(quote.get("provider_id") or "").lower() != QUOTE_PROVIDER_ID:
        raise CaptureFailure("SYMBOL_MISMATCH", "quote provider identity is not approved")
    from .cdp import _epoch
    quote_at = _epoch(quote.get("source_time"))
    if quote_at > view.observed_at + timedelta(seconds=5):
        raise CaptureFailure("SOURCE_STALE", "quote timestamp is future-dated")
    if view.observed_at - quote_at > timedelta(seconds=QUOTE_MAX_AGE_SECONDS):
        raise CaptureFailure("SOURCE_STALE", "quote timestamp is stale")
    market_price = _finite(quote.get("price"), "quote.price")
    bid = _finite(quote.get("bid"), "quote.bid")
    ask = _finite(quote.get("ask"), "quote.ask")
    if market_price <= 0 or bid <= 0 or ask <= 0:
        raise CaptureFailure(
            "STRUCTURED_READ_INCOMPLETE",
            "quote price, bid, and ask must be positive",
        )
    if ask < bid:
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "quote ask is below bid")
    atr, atr_source_time = _confirmed_atr14(chart)
    atr_at = datetime.fromisoformat(atr_source_time[:-1] + "+00:00").astimezone(timezone.utc)
    closed_at = _epoch((chart.get("closed_bar") or {}).get("time"))
    if atr_at != closed_at:
        raise CaptureFailure(
            "STRUCTURED_READ_INCOMPLETE",
            "ATR14 newest input is not the confirmed 5m closed bar",
        )
    if atr_at > view.observed_at + timedelta(seconds=5):
        raise CaptureFailure("SOURCE_STALE", "ATR14 source is future-dated")
    if view.observed_at - atr_at > timedelta(minutes=15):
        raise CaptureFailure("SOURCE_STALE", "ATR14 source is stale")
    spread = ask - bid
    return {
        "market_price": market_price,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "normalized_spread": spread / atr,
        "symbol": view.plan.symbol,
        "feed": view.plan.feed,
        "timeframe": chart["timeframe"],
        "quote_source": QUOTE_SOURCE,
        "quote_provider_id": QUOTE_PROVIDER_ID,
        "quote_source_symbol": expected_symbol,
        "quote_source_feed": view.plan.feed,
        "source_time": utc_z(quote_at),
        "atr": atr,
        "atr_period": 14,
        "atr_method": "SMA_TRUE_RANGE_14_CONFIRMED_5M_BARS",
        "atr_source_time": atr_source_time,
        "observed_at": observed_at,
    }


def _fields_for(
    request: dict[str, Any],
    view: ViewSnapshot,
    observed_at: str,
    liquidity_event_facts: dict[str, Any],
) -> dict[str, Any]:
    kind = request["read_kind"]
    timeframes = list(request["timeframes"])
    charts = {timeframe: _chart(view, timeframe) for timeframe in timeframes}
    if any(chart.get("chart_type_name") != "standard_candles" for chart in charts.values()):
        raise CaptureFailure(
            "CAPTURE_PLAN_MISMATCH",
            f"{request['request_id']} attempted structured numeric extraction from a visual-context-only Volume pane",
            retryable=False,
        )
    fields: dict[str, Any]
    if kind == "CURRENT_FORMING_PRICE":
        chart = charts[timeframes[0]]
        fields = _quote_and_atr_fields(view, chart, observed_at)
        if (
            liquidity_event_facts.get("symbol") != view.plan.symbol
            or liquidity_event_facts.get("feed") != view.plan.feed
            or liquidity_event_facts.get("anchor_timeframe") != timeframes[0]
        ):
            raise CaptureFailure(
                "SYMBOL_MISMATCH",
                "LIQ event facts do not match the numeric chart authority",
            )
        level_price = _finite(
            float(liquidity_event_facts["level_price"]),
            "liquidity_event_facts.level_price",
        )
        side = liquidity_event_facts["side"]
        reference_price = fields["ask"] if side == "ASK" else fields["bid"]
        distance = (
            level_price - reference_price
            if side == "ASK"
            else reference_price - level_price
        )
        fields.update({
            "liquidity_level_id": liquidity_event_facts["level_id"],
            "liquidity_level_version": liquidity_event_facts["level_version"],
            "liquidity_level_side": side,
            "liquidity_level_price": level_price,
            "liquidity_touch_count": liquidity_event_facts["touch_count"],
            "liquidity_event_timestamp": liquidity_event_facts["source_bar_time"],
            "liquidity_producer_id": liquidity_event_facts["producer_id"],
            "liquidity_producer_revision": liquidity_event_facts["producer_revision"],
            "distance_reference_price": reference_price,
            "distance_reference_side": side,
            "distance_to_level": distance,
            "distance_atr": distance / fields["atr"],
        })
    elif kind in {"CLOSED_OHLC", "CLOSED_OHLC_AND_STRUCTURE", "SHORT_TERM_PRICE_ACTION"}:
        bars = {tf: _bar(chart, "closed_bar") for tf, chart in charts.items()}
        fields = {
            "open": {tf: bar["open"] for tf, bar in bars.items()},
            "high": {tf: bar["high"] for tf, bar in bars.items()},
            "low": {tf: bar["low"] for tf, bar in bars.items()},
            "close": {tf: bar["close"] for tf, bar in bars.items()},
            "source_bar_time": {tf: _source_time(bar) for tf, bar in bars.items()},
            "confirmed": True,
        }
        if "structure" in request["fields"]:
            fields["structure"] = {
                tf: "UP" if bar["close"] >= _bar(charts[tf], "previous_closed_bar")["close"] else "DOWN"
                for tf, bar in bars.items()
            }
        if "price_path" in request["fields"]:
            fields["price_path"] = {
                tf: [_finite(item.get("close"), f"{tf}.price_path") for item in charts[tf].get("recent_closed_bars", [])[:8]]
                for tf in timeframes
            }
            if any(len(values) < 3 for values in fields["price_path"].values()):
                raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "price path has fewer than three closed bars")
    elif kind == "STANDARD_MACD":
        macd: dict[str, float] = {}
        signal: dict[str, float] = {}
        histogram: dict[str, float] = {}
        previous_histogram: dict[str, float] = {}
        source_times: dict[str, str] = {}
        for tf, chart in charts.items():
            study = _study(chart, r"MACD|Convergence")
            closed = _plot_values(study, "closed")
            previous = _plot_values(study, "previous_closed")
            macd[tf] = _named_value(closed, r"macd", 0)
            signal[tf] = _named_value(closed, r"signal", 1)
            histogram[tf] = _named_value(closed, r"hist", 2)
            previous_histogram[tf] = _named_value(previous, r"hist", 2)
            source_times[tf] = _source_time(_bar(chart, "closed_bar"))
        fields = {"macd": macd, "signal": signal, "histogram": histogram,
                  "previous_histogram": previous_histogram,
                  "source_bar_time": source_times, "confirmed": True}
    elif kind == "EXPANSION_CONTEXT":
        fields = {key: {} for key in (
            "direction", "start_price", "market_price", "displacement", "atr",
            "atr_multiple", "path_efficiency", "body_quality", "opposing_bars", "source_bar_time"
        )}
        for tf, chart in charts.items():
            bar = _bar(chart, "closed_bar")
            previous = _bar(chart, "previous_closed_bar")
            atr, _ = _confirmed_atr14(chart)
            displacement = bar["close"] - previous["close"]
            span = max(bar["high"] - bar["low"], 1e-9)
            fields["direction"][tf] = "UP" if displacement >= 0 else "DOWN"
            fields["start_price"][tf] = previous["close"]
            fields["market_price"][tf] = bar["close"]
            fields["displacement"][tf] = displacement
            fields["atr"][tf] = atr
            fields["atr_multiple"][tf] = displacement / atr if atr else 0.0
            fields["path_efficiency"][tf] = abs(displacement) / span
            fields["body_quality"][tf] = abs(bar["close"] - bar["open"]) / span
            fields["opposing_bars"][tf] = int((bar["close"] - bar["open"]) * displacement < 0)
            fields["source_bar_time"][tf] = _source_time(bar)
        fields["confirmed"] = True
    elif kind == "SNR_HPA_CONTEXT":
        levels, structure, momentum, times = {}, {}, {}, {}
        for tf, chart in charts.items():
            snr = _study(chart, r"SNR|HPA|support|resistance")
            values = _plot_values(snr, "closed")
            bar = _bar(chart, "closed_bar")
            previous = _bar(chart, "previous_closed_bar")
            levels[tf] = values
            structure[tf] = "UP" if bar["close"] >= previous["close"] else "DOWN"
            momentum[tf] = bar["close"] - previous["close"]
            times[tf] = _source_time(bar)
        fields = {"levels": levels, "structure": structure, "momentum": momentum,
                  "source_bar_time": times, "confirmed": True}
    elif kind == "DXY_CONTEXT":
        chart = charts[timeframes[0]]
        current = _bar(chart, "current_bar")
        closed = _bar(chart, "closed_bar")
        previous = _bar(chart, "previous_closed_bar")
        closes = [_finite(item.get("close"), "dxy.close") for item in chart.get("recent_closed_bars", [])[:20]]
        if len(closes) != 20:
            raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "DXY SMA20 requires 20 closed bars")
        sma20 = sum(closes) / 20
        fields = {"current": current["close"], "close": closed["close"],
                  "change": closed["close"] - previous["close"], "sma20": sma20,
                  "distance": closed["close"] - sma20, "source_bar_time": _source_time(closed),
                  "confirmed": True}
    elif kind == "RENKO_STATE":
        chart = charts[timeframes[0]]
        bar = _bar(chart, "closed_bar")
        previous = _bar(chart, "previous_closed_bar")
        renko = _study(chart, r"renko|sniper|E1")
        values = _plot_values(renko, "closed")
        ordered = list(values.values())
        fields = {"stage": renko.get("description"),
                  "direction": "UP" if bar["close"] >= previous["close"] else "DOWN",
                  "signal_price": bar["close"], "source_bar_time": _source_time(bar),
                  "confirmed": True, "score": ordered[0],
                  "power": ordered[1] if len(ordered) > 1 else ordered[0],
                  "mode": renko.get("short_description") or renko.get("description"),
                  "transfer": values}
    else:
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", f"unsupported frozen read kind {kind}", retryable=False)
    if set(fields) != set(request["fields"]):
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", f"{request['request_id']} field contract drift", retryable=False)
    return fields


def _state_fingerprint(snapshots: dict[str, ViewSnapshot]) -> str:
    document = []
    for role in sorted(snapshots):
        snapshot = snapshots[role]
        document.append({
            "role": role, "target_id": snapshot.target.target_id,
            "url": snapshot.target.url, "layout_id": snapshot.target.layout_id,
            "account": snapshot.account,
            "symbol": snapshot.plan.symbol, "feed": snapshot.plan.feed,
            "timeframes": sorted(chart["timeframe"] for chart in snapshot.charts),
            "chart_types": [chart.get("chart_type") for chart in snapshot.charts],
            "indicator_names": list(snapshot.indicator_names),
            "alert_inventory_count": snapshot.alert_inventory_count,
        })
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


class CaptureEngine:
    def __init__(self, *, artifact_root: str | Path, audit_store: AuditStore,
                 backend: ReadOnlyBackend | None = None,
                 clock: Callable[[], datetime] | None = None,
                 timeout_seconds: float = 45,
                 monotonic: Callable[[], float] | None = None):
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.audit_store = audit_store
        self.backend = backend or ProductionCdpBackend()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("capture timeout must be in (0,120] seconds")
        self.timeout_seconds = timeout_seconds
        self.monotonic = monotonic or time.monotonic

    def _bounded(self, deadline: float, operation, *args):
        if self.monotonic() >= deadline:
            raise CaptureFailure("CAPTURE_TIMEOUT", "capture deadline elapsed")
        result = operation(*args)
        if self.monotonic() > deadline:
            raise CaptureFailure("CAPTURE_TIMEOUT", "capture operation exceeded deadline")
        return result

    def _snapshots(self, plan: CapturePlan, selected: dict[str, Any],
                   deadline: float) -> dict[str, ViewSnapshot]:
        now = self.clock().astimezone(timezone.utc)
        return {
            view.role: validate_view(
                view, selected[view.role],
                self._bounded(deadline, self.backend.read, selected[view.role]), now=now,
            )
            for view in plan.views
        }

    def _attempt_dir(self, request_id: str) -> Path:
        directory = (self.artifact_root / ("request_" + hashlib.sha256(request_id.encode()).hexdigest()[:32])).resolve()
        if directory.parent != self.artifact_root:
            raise CaptureFailure("ARTIFACT_PATH_INVALID", "attempt path escaped artifact root", retryable=False)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _write_immutable(path: Path, data: bytes) -> None:
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.read_bytes() != data:
                raise CaptureFailure("ARTIFACT_IDENTITY_CONFLICT", "immutable artifact differs", retryable=False)

    @staticmethod
    def _restore_ledger_pinned_result(path: Path, data: bytes) -> None:
        temp = path.with_name(f".result-recovery-{os.getpid()}-{secrets.token_hex(8)}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def _load_replay(self, record: dict[str, str]) -> CapturedPackage:
        relative = Path(record["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise CaptureFailure("ARTIFACT_PATH_INVALID", "stored result path is unsafe", retryable=False)
        path = (self.artifact_root / relative).resolve()
        if self.artifact_root not in path.parents:
            raise CaptureFailure("ARTIFACT_PATH_INVALID", "stored result escaped artifact root", retryable=False)
        pinned = record["result_json"].encode("utf-8")
        if hashlib.sha256(pinned).hexdigest() != record["sha256"]:
            raise CaptureFailure("ARTIFACT_IDENTITY_CONFLICT", "ledger result hash mismatch", retryable=False)
        raw = path.read_bytes() if path.exists() else b""
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            self._restore_ledger_pinned_result(path, pinned)
            raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise CaptureFailure("ARTIFACT_IDENTITY_CONFLICT", "stored result hash mismatch", retryable=False)
        document = json.loads(raw.decode("utf-8"))
        if not isinstance(document, dict) or set(document) != {"structured"}:
            raise CaptureFailure("ARTIFACT_IDENTITY_CONFLICT", "stored result envelope is invalid", retryable=False)
        structured = CaptureToolResult.model_validate(document["structured"]).model_dump(mode="json")
        images = []
        for artifact in structured["screenshot_artifacts"]:
            image_path = (self.artifact_root / artifact["relative_path"]).resolve()
            if self.artifact_root not in image_path.parents:
                raise CaptureFailure("ARTIFACT_PATH_INVALID", "stored image escaped artifact root", retryable=False)
            data = image_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise CaptureFailure("ARTIFACT_IDENTITY_CONFLICT", "stored image hash mismatch", retryable=False)
            validate_png(data)
            images.append(data)
        return CapturedPackage(structured, tuple(images))

    def capture(self, request: CaptureToolRequest) -> CapturedPackage:
        started = self.clock().astimezone(timezone.utc)
        deadline = self.monotonic() + self.timeout_seconds
        event_at = datetime.fromisoformat(request.event_timestamp[:-1] + "+00:00").astimezone(timezone.utc)
        liq_event_at = datetime.fromisoformat(
            request.liquidity_event_facts.source_bar_time[:-1] + "+00:00"
        ).astimezone(timezone.utc)
        if request.stage == "LIQ_BASELINE" and liq_event_at != event_at:
            raise CaptureFailure(
                "CAPTURE_PLAN_MISMATCH",
                "LIQ baseline timestamp does not match immutable event facts",
                retryable=False,
            )
        event_age = started - event_at
        if event_age < timedelta(seconds=-5) or event_age > timedelta(minutes=30):
            raise CaptureFailure("REQUEST_EXPIRED", "event timestamp is future-dated or older than 30 minutes", retryable=False)
        request_document = request.model_dump(mode="json")
        _, replay = self.audit_store.begin_request(request.request_id, request_document, at=utc_z(started))
        if replay:
            return self._load_replay(replay)
        plan = plan_for_stage(request.stage)
        if request.capture_scope != plan.capture_scope or request.required_capture_plan_version != plan.version:
            raise CaptureFailure("CAPTURE_PLAN_MISMATCH", "stage, scope, or plan version mismatch", retryable=False)
        if request.capture_plan_sha256 != plan_sha256(plan):
            raise CaptureFailure("CAPTURE_PLAN_MISMATCH", "accepted capture plan hash mismatch", retryable=False)
        try:
            attempt_dir = self._attempt_dir(request.request_id)
            if (attempt_dir / "result.json").exists():
                raise CaptureFailure(
                    "ARTIFACT_IDENTITY_CONFLICT",
                    "uncommitted result artifact exists without a ledger binding",
                    retryable=False,
                )
            targets = self._bounded(deadline, self.backend.discover)
            selected = select_targets(plan, targets)
            before = self._snapshots(plan, selected, deadline)
            before_hash = _state_fingerprint(before)
            image_bytes: list[bytes] = []
            artifacts: list[ScreenshotArtifact] = []
            screenshot_results = []
            constituent_statuses: list[ConstituentStatus] = []
            for screenshot in plan.screenshots:
                role = screenshot["source"]["role"]
                snapshot = before[role]
                data = self._bounded(deadline, self.backend.screenshot, snapshot.target)
                width, height = validate_png(data)
                captured_at = utc_z(self.clock())
                digest = hashlib.sha256(data).hexdigest()
                filename = f"{screenshot['request_id']}_{digest}.png"
                path = attempt_dir / filename
                self._write_immutable(path, data)
                relative = path.relative_to(self.artifact_root).as_posix()
                artifacts.append(ScreenshotArtifact(
                    evidence_id=screenshot["request_id"], relative_path=relative,
                    sha256=digest, mime_type="image/png", width=width, height=height,
                    captured_at=captured_at, role=role, target_id=snapshot.target.target_id,
                ))
                image_bytes.append(data)
                source = dict(screenshot["source"])
                source["target_id"] = snapshot.target.target_id
                screenshot_results.append({
                    "request_id": screenshot["request_id"], "status": "COMPLETED",
                    "source": source, "observed_at": captured_at,
                    "target_binding_verified": True,
                })
                constituent_statuses.append(ConstituentStatus(
                    constituent_id=screenshot["request_id"], kind="SCREENSHOT", status="COMPLETED"
                ))
            if sum(len(data) for data in image_bytes) > IMAGE_BUDGETS[request.stage]:
                raise CaptureFailure("SCREENSHOT_INVALID", "stage image budget exceeded")
            after = self._snapshots(plan, selected, deadline)
            if _state_fingerprint(after) != before_hash:
                raise CaptureFailure("BROWSER_STATE_CHANGED", "browser identity/configuration changed during capture")
            observed_at = utc_z(self.clock())
            read_results = []
            for read in plan.structured_reads:
                if read["source"]["port"] != 9333:
                    if read.get("required") is not False:
                        raise CaptureFailure("CAPTURE_PLAN_MISMATCH", "required non-9333 read is forbidden", retryable=False)
                    read_results.append({"request_id": read["request_id"], "status": "UNAVAILABLE",
                                         "reason": "SOURCE_PORT_NOT_AUTHORIZED"})
                    constituent_statuses.append(ConstituentStatus(
                        constituent_id=read["request_id"], kind="STRUCTURED_READ",
                        status="UNAVAILABLE", technical_failure_code="SOURCE_PORT_NOT_AUTHORIZED",
                    ))
                    continue
                view = before[read["source"]["role"]]
                fields = _fields_for(
                    read,
                    view,
                    observed_at,
                    request.liquidity_event_facts.model_dump(mode="json"),
                )
                read_results.append({
                    "request_id": read["request_id"], "status": "COMPLETED",
                    "source": _source_result(read, view), "read_kind": read["read_kind"],
                    "timeframes": read["timeframes"], "closed_bars_only": read["closed_bars_only"],
                    "indicator_parameters": read["indicator_parameters"], "fields": fields,
                    "observed_at": observed_at,
                    "closed_bars_only_verified": read["closed_bars_only"],
                    "target_binding_verified": True,
                })
                constituent_statuses.append(ConstituentStatus(
                    constituent_id=read["request_id"], kind="STRUCTURED_READ", status="COMPLETED"
                ))
            structured_evidence = {
                "structured_read_results": read_results, "screenshot_results": screenshot_results,
            }
            if len(canonical_json(structured_evidence).encode("utf-8")) > MAX_STRUCTURED_BYTES:
                raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "structured evidence exceeded size limit")
            completed = self.clock().astimezone(timezone.utc)
            views = [ViewIdentity(
                role=snapshot.plan.role, target_id=snapshot.target.target_id,
                layout_id=snapshot.target.layout_id, url=snapshot.target.url,
                account=snapshot.account, symbol=snapshot.plan.symbol, feed=snapshot.plan.feed,
                timeframes=[chart["timeframe"] for chart in snapshot.charts],
                chart_types=[chart["chart_type_name"] for chart in snapshot.charts],
                indicator_names=list(snapshot.indicator_names), observed_at=utc_z(snapshot.observed_at),
                last_bar_at=utc_z(snapshot.last_bar_at), status="COMPLETE",
            ) for snapshot in before.values()]
            manifest_document = {
                "request": request_document, "capture_started_at": utc_z(started),
                "capture_completed_at": utc_z(completed), "script_sha256": SCRIPT_SHA256,
                "browser_state_before_sha256": before_hash,
                "browser_state_after_sha256": _state_fingerprint(after),
                "views": [view.model_dump(mode="json") for view in views],
                "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
                "structured_evidence_sha256": hashlib.sha256(
                    canonical_json(structured_evidence).encode("utf-8")
                ).hexdigest(),
            }
            manifest_sha = hashlib.sha256(canonical_json(manifest_document).encode("utf-8")).hexdigest()
            result = CaptureToolResult(
                status="COMPLETED", request_id=request.request_id, job_id=request.request_id,
                story_id=request.story_id, analysis_id=request.analysis_id, stage=request.stage,
                capture_scope=request.capture_scope, source_event_id=request.canonical_event_id,
                event_timestamp=request.event_timestamp, capture_plan_version=CAPTURE_PLAN_VERSION,
                capture_started_at=utc_z(started), capture_completed_at=utc_z(completed),
                captured_at=utc_z(completed), account="Jonesy_Wong", symbol="XAUUSD", feed="ICMARKETS",
                cdp_endpoint=CDP_ENDPOINT, evidence_freshness="FRESH",
                structured_reads_complete=True, screenshots_complete=True,
                capture_request_sha256=request.capture_request_sha256,
                capture_plan_sha256=request.capture_plan_sha256,
                image_evidence_ids=[artifact.evidence_id for artifact in artifacts],
                immutable_evidence_manifest_sha256=manifest_sha,
                script_id=SCRIPT_ID, script_version=SCRIPT_VERSION, script_sha256=SCRIPT_SHA256,
                views=views, screenshot_artifacts=artifacts,
                constituent_statuses=constituent_statuses,
                structured_evidence=structured_evidence, technical_failure_code=None,
            ).model_dump(mode="json")
            result_document = canonical_json({"structured": result}) + "\n"
            result_path = attempt_dir / "result.json"
            result_sha = hashlib.sha256(result_document.encode("utf-8")).hexdigest()
            self.audit_store.record_result(
                request.request_id, result_sha256=result_sha,
                relative_path=result_path.relative_to(self.artifact_root).as_posix(),
                result_json=result_document,
                completed_at=utc_z(completed),
            )
            self._write_immutable(result_path, result_document.encode("utf-8"))
            return CapturedPackage(result, tuple(image_bytes))
        except CaptureFailure as exc:
            self.audit_store.record_failure(request.request_id, code=exc.code, at=utc_z(self.clock()))
            raise

    def preflight(self) -> dict[str, Any]:
        plan = plan_for_stage("LIQ_BASELINE")
        started = self.clock().astimezone(timezone.utc)
        deadline = self.monotonic() + self.timeout_seconds
        targets = self._bounded(deadline, self.backend.discover)
        selected = select_targets(plan, targets)
        before = self._snapshots(plan, selected, deadline)
        before_hash = _state_fingerprint(before)
        observed_at = utc_z(self.clock())
        quote_reads = [
            read for read in plan.structured_reads
            if read["request_id"] == "read_9333_xau_current"
        ]
        if len(quote_reads) != 1:
            raise CaptureFailure(
                "CAPTURE_PLAN_MISMATCH",
                "production quote preflight read is not unique",
                retryable=False,
            )
        structured_reads = []
        for read in quote_reads:
            view = before[read["source"]["role"]]
            chart = _chart(view, read["timeframes"][0])
            if chart.get("chart_type_name") != "standard_candles":
                raise CaptureFailure(
                    "CAPTURE_PLAN_MISMATCH",
                    "production quote preflight requires the standard-candle 5m pane",
                    retryable=False,
                )
            fields = _quote_and_atr_fields(view, chart, observed_at)
            result = {
                "request_id": read["request_id"],
                "status": "COMPLETED",
                "source": _source_result(read, view),
                "read_kind": read["read_kind"],
                "timeframes": read["timeframes"],
                "fields": fields,
                "observed_at": observed_at,
                "target_binding_verified": True,
            }
            result["sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
            structured_reads.append(result)
        preflight_dir = (self.artifact_root / "preflight").resolve()
        preflight_dir.mkdir(parents=True, exist_ok=True)
        screenshots = []
        for view in plan.views:
            data = self._bounded(deadline, self.backend.screenshot, selected[view.role])
            width, height = validate_png(data)
            digest = hashlib.sha256(data).hexdigest()
            image_path = preflight_dir / f"{view.role}_{digest}.png"
            self._write_immutable(image_path, data)
            screenshots.append({
                "role": view.role, "target_id": selected[view.role].target_id,
                "sha256": digest, "width": width, "height": height,
                "relative_path": image_path.relative_to(self.artifact_root).as_posix(),
            })
        after = self._snapshots(plan, selected, deadline)
        after_hash = _state_fingerprint(after)
        if before_hash != after_hash:
            raise CaptureFailure("BROWSER_STATE_CHANGED", "read-only preflight changed browser identity/configuration")
        completed = self.clock().astimezone(timezone.utc)
        manifest = {
            "status": "PASS", "capture_plan_version": CAPTURE_PLAN_VERSION,
            "cdp_endpoint": CDP_ENDPOINT, "started_at": utc_z(started), "completed_at": utc_z(completed),
            "browser_state_before_sha256": before_hash, "browser_state_after_sha256": after_hash,
            "views": [{"role": item.plan.role, "target_id": item.target.target_id,
                       "layout_id": item.target.layout_id, "account": item.account,
                       "symbol": item.plan.symbol, "feed": item.plan.feed,
                       "timeframes": sorted(chart["timeframe"] for chart in item.charts),
                       "chart_types": [chart["chart_type_name"] for chart in item.charts],
                       "indicator_names": list(item.indicator_names),
                       "alert_inventory_count": item.alert_inventory_count}
                      for item in before.values()],
            "structured_reads": structured_reads,
            "screenshots": screenshots, "mutation_detected": False,
            "script_id": SCRIPT_ID, "script_version": SCRIPT_VERSION, "script_sha256": SCRIPT_SHA256,
        }
        digest = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
        path = preflight_dir / f"preflight_{digest}.json"
        self._write_immutable(path, (canonical_json(manifest) + "\n").encode("utf-8"))
        self.audit_store.record_preflight(manifest_sha256=digest, at=utc_z(completed))
        return {**manifest, "immutable_manifest_sha256": digest,
                "manifest_path": path.relative_to(self.artifact_root).as_posix()}
