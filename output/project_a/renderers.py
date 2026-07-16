"""Four independent renderers over one immutable canonical Thesis."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol

from contracts import THESIS_SCHEMA_V1, canonical_json, validate_contract

from .config import OutputConfig
from .fakes import (
    FakeMT5Transport,
    FakeNotionTransport,
    FakeTelegramTransport,
    FakeTradingViewTransport,
    FakeTransportError,
)
from .models import (
    DeliveryContext,
    RendererResult,
    RendererType,
    ResultStatus,
    Session5Error,
    document_hash,
    parse_utc,
    result,
)


class Renderer(Protocol):
    renderer_type: RendererType

    def render(self, context: DeliveryContext, attempt_id: str,
               now: datetime) -> RendererResult: ...

    def reconcile_reference(self, context: DeliveryContext) -> str | None: ...


def _base_gate(context: DeliveryContext, expected: RendererType) -> None:
    validate_contract(THESIS_SCHEMA_V1, context.thesis)
    if context.delivery["renderer_type"] != expected.value:
        raise Session5Error("renderer_mismatch", expected.value)
    if context.delivery["thesis_hash"] != document_hash(context.thesis):
        raise Session5Error("thesis_hash_mismatch", context.delivery["delivery_id"])
    if context.thesis["setup_id"] != context.delivery["setup_id"]:
        raise Session5Error("setup_identity_mismatch", context.delivery["delivery_id"])
    if (context.thesis["mode"] != "SHADOW" or context.thesis["live_execution"] is not False
            or context.thesis["execution_environment"] != "MT5_DEMO"):
        raise Session5Error("unsafe_thesis_environment", context.thesis["thesis_id"])


def _actionable_expired(context: DeliveryContext, now: datetime) -> bool:
    return (context.thesis["decision"] in {"APPROVE", "MODIFY"}
            and parse_utc(context.thesis["valid_until"]) <= now)


def _transport_result(context, attempt_id, now, exc: FakeTransportError):
    if exc.uncertain:
        status = ResultStatus.UNCERTAIN
    elif exc.retryable:
        status = ResultStatus.RETRYABLE_FAILURE
    else:
        status = ResultStatus.TERMINAL_FAILURE
    return result(context, attempt_id, status, now, error_code=exc.code)


class TradingViewRenderer:
    renderer_type = RendererType.TRADINGVIEW

    def __init__(self, config: OutputConfig, transport: FakeTradingViewTransport):
        self.config, self.transport = config, transport

    def reconcile_reference(self, context: DeliveryContext) -> str | None:
        return self.transport.lookup_bundle(
            context.delivery["idempotency_key"], context.delivery["thesis_hash"])

    def render(self, context: DeliveryContext, attempt_id: str, now: datetime) -> RendererResult:
        _base_gate(context, self.renderer_type)
        if context.thesis["decision"] not in {"APPROVE", "MODIFY"}:
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="tv_non_actionable")
        if _actionable_expired(context, now):
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="thesis_expired_before_drawing")
        identity_error = self._identity_error(self.transport.inspect())
        if identity_error:
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code=identity_error)
        try:
            existing = self.reconcile_reference(context)
        except FakeTransportError as exc:
            return _transport_result(context, attempt_id, now, exc)
        if existing:
            return result(context, attempt_id, ResultStatus.ALREADY_COMPLETED, now,
                          external_reference=existing)

        specs = tradingview_specs(context)
        created: list[str] = []
        references: list[str] = []
        try:
            for spec in specs:
                reference, was_created = self.transport.upsert(spec["object_id"], spec)
                references.append(reference)
                if was_created:
                    created.append(reference)
            if not self.transport.verify(specs):
                raise FakeTransportError("tv_post_draw_verification", retryable=True)
            external = self.transport.commit_bundle(
                context.delivery["idempotency_key"], context.delivery["thesis_hash"], references)
            return result(context, attempt_id, ResultStatus.DRY_RUN_SUCCESS, now,
                          external_reference=external,
                          detail={"objects": references, "object_count": len(references)})
        except FakeTransportError as exc:
            try:
                self.transport.cleanup(created)
            except FakeTransportError:
                return result(context, attempt_id, ResultStatus.TERMINAL_FAILURE, now,
                              error_code="tv_cleanup_failed", detail={"created": created})
            code = "tv_partial_create_cleaned" if created else exc.code
            return result(context, attempt_id,
                          ResultStatus.RETRYABLE_FAILURE if exc.retryable else ResultStatus.TERMINAL_FAILURE,
                          now, error_code=code, detail={"cleaned": created})

    def _identity_error(self, actual: dict[str, Any]) -> str | None:
        expected = self.config.tradingview
        checks = [
            (actual.get("port") == 4999 == expected.port, "tv_wrong_port"),
            (actual.get("process_identity") == expected.expected_process_identity, "tv_wrong_process"),
            (actual.get("tab_count") == 1, "tv_wrong_tab_count"),
            (actual.get("selected_tab_id") == expected.expected_tab_id, "tv_wrong_tab"),
            (actual.get("symbol") == "XAUUSD" == expected.expected_symbol, "tv_wrong_symbol"),
            (actual.get("feed") in expected.feed_allowlist, "tv_wrong_feed"),
            (actual.get("timeframe") == "1m" == expected.expected_timeframe, "tv_wrong_timeframe"),
            (actual.get("layout_id") == expected.expected_layout_id, "tv_wrong_layout"),
        ]
        return next((code for ok, code in checks if not ok), None)


def tradingview_specs(context: DeliveryContext) -> list[dict[str, Any]]:
    t, r = context.thesis, context.request
    prefix = f"project-a:{t['thesis_id']}"
    common = {"setup_id": t["setup_id"], "thesis_id": t["thesis_id"]}
    return [
        {"object_id": f"{prefix}:aoi", "kind": "AOI", "low": r["snr"]["low"],
         "high": r["snr"]["high"], "snr_type": r["snr"]["type"], **common},
        {"object_id": f"{prefix}:entry", "kind": "ENTRY", "price": t["entry"], **common},
        {"object_id": f"{prefix}:sl", "kind": "SL", "price": t["sl"], **common},
        {"object_id": f"{prefix}:tp", "kind": "TP", "price": t["tp"], "rr": 1.0, **common},
        {"object_id": f"{prefix}:label", "kind": "LABEL", "direction": t["direction"],
         "verdict": t["decision"], "path": t["path"], "expiry": t["valid_until"], **common},
    ]


def _safe_plain(value: Any, limit: int = 300) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))
    return text.replace("\r\n", "\n").replace("\r", "\n")[:limit]


def telegram_message(context: DeliveryContext, max_length: int = 1500) -> str:
    t, r, v = context.thesis, context.request, context.verdict
    trace = _safe_plain(t["setup_id"], 80)
    if t["decision"] in {"APPROVE", "MODIFY"}:
        lines = [
            f"[SHADOW / DRY-RUN] XAUUSD {t['direction']}",
            f"Verdict: {t['decision']} | Path: {t['path']}",
            f"Entry {t['entry']} | SL {t['sl']} | TP {t['tp']} | RR 1:1 | Spread {r['spread_points']} points",
            f"Invalidation {t['invalidation']} | Valid until {t['valid_until']}",
            f"Trace: {trace}",
        ]
    else:
        reason = ",".join(v["reason_codes"])
        status = "Expired" if t["decision"] == "EXPIRED" else "Rejected"
        lines = [
            "[SHADOW] XAUUSD",
            f"Verdict: {t['decision']}",
            f"Reason: {_safe_plain(reason, 256)}",
            f"Status: {status}; audit retained | Request expiry {r['expires_at']}",
            f"Trace: {trace}",
        ]
    message = "\n".join(lines)
    if len(message) > max_length:
        message = message[:max_length - 1] + "…"
    return message


class TelegramRenderer:
    renderer_type = RendererType.TELEGRAM

    def __init__(self, config: OutputConfig, transport: FakeTelegramTransport):
        self.config, self.transport = config, transport

    def reconcile_reference(self, context: DeliveryContext) -> str | None:
        message = telegram_message(context, self.config.telegram.max_message_length)
        return self.transport.lookup(context.delivery["idempotency_key"],
                                     document_hash({"message": message}))

    def render(self, context: DeliveryContext, attempt_id: str, now: datetime) -> RendererResult:
        _base_gate(context, self.renderer_type)
        cfg = self.config.telegram
        if not (cfg.destination_id.isdigit() and cfg.owner_user_id == cfg.destination_id
                and cfg.direct_message_only):
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="telegram_allowlist")
        if _actionable_expired(context, now):
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="thesis_expired_before_notification")
        message = telegram_message(context, cfg.max_message_length)
        content_hash = document_hash({"message": message})
        try:
            existing = self.transport.lookup(context.delivery["idempotency_key"], content_hash)
            if existing:
                return result(context, attempt_id, ResultStatus.ALREADY_COMPLETED, now,
                              external_reference=existing, detail={"message": message})
            message_id = self.transport.send(
                destination_id=cfg.destination_id, message=message,
                idempotency_key=context.delivery["idempotency_key"], content_hash=content_hash)
            return result(context, attempt_id, ResultStatus.DRY_RUN_SUCCESS, now,
                          external_reference=message_id, detail={"message": message})
        except FakeTransportError as exc:
            return _transport_result(context, attempt_id, now, exc)


class NotionRenderer:
    renderer_type = RendererType.NOTION
    REQUIRED_FIELDS = {"setup_id", "content_hash", "thesis_id", "renderer_statuses"}

    def __init__(self, config: OutputConfig, transport: FakeNotionTransport, store):
        self.config, self.transport, self.store = config, transport, store

    def _core(self, context: DeliveryContext) -> dict[str, Any]:
        return {
            "setup_id": context.thesis["setup_id"],
            "thesis_id": context.thesis["thesis_id"],
            "request": context.request,
            "verdict": context.verdict,
            "thesis": context.thesis,
            "audit_ref": context.audit_ref,
            "hashes": {
                "request": document_hash(context.request),
                "verdict": document_hash(context.verdict),
                "thesis": document_hash(context.thesis),
            },
        }

    def reconcile_reference(self, context: DeliveryContext) -> str | None:
        core = self._core(context)
        return self.transport.lookup(context.thesis["setup_id"], document_hash(core))

    def render(self, context: DeliveryContext, attempt_id: str, now: datetime) -> RendererResult:
        _base_gate(context, self.renderer_type)
        if not self.REQUIRED_FIELDS <= set(self.config.notion.schema_fields):
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="notion_schema_incompatible")
        core = self._core(context)
        core_hash = document_hash(core)
        statuses = {item["renderer_type"]: item["status"]
                    for item in self.store.deliveries_for_setup(context.thesis["setup_id"])}
        record = {**core, "content_hash": core_hash,
                  "renderer_statuses": dict(sorted(statuses.items())),
                  "mt5_outcomes": self.store.outcomes(context.thesis["thesis_id"])}
        try:
            existing = self.transport.lookup(context.thesis["setup_id"], core_hash)
            page_id = self.transport.upsert(context.thesis["setup_id"], core_hash, record)
            return result(context, attempt_id,
                          ResultStatus.ALREADY_COMPLETED if existing else ResultStatus.DRY_RUN_SUCCESS,
                          now, external_reference=page_id,
                          detail={"core_hash": core_hash, "record": record})
        except FakeTransportError as exc:
            return _transport_result(context, attempt_id, now, exc)

    def sync_statuses(self, setup_id: str) -> bool:
        statuses = {item["renderer_type"]: item["status"]
                    for item in self.store.deliveries_for_setup(setup_id)}
        return self.transport.update_statuses(setup_id, statuses)

    def sync_outcomes(self, setup_id: str, thesis_id: str) -> bool:
        return self.transport.append_outcomes(setup_id, self.store.outcomes(thesis_id))


def _mt5_attestation_error(config: OutputConfig, actual: dict[str, Any]) -> str | None:
    cfg = config.mt5
    checks = [
        (actual.get("connected") is True, "mt5_not_connected"),
        (actual.get("environment") == "MT5_DEMO", "mt5_unknown_environment"),
        (actual.get("trade_mode") == "DEMO", "mt5_live_or_unknown_account"),
        (str(actual.get("account_id")) in cfg.account_allowlist, "mt5_account_not_allowlisted"),
        (actual.get("server") in cfg.server_allowlist, "mt5_server_not_allowlisted"),
        (actual.get("terminal_path") in cfg.terminal_path_allowlist, "mt5_terminal_not_allowlisted"),
        (actual.get("symbol") == cfg.symbol_mapping, "mt5_symbol_mapping"),
        (actual.get("precision") == cfg.precision, "mt5_precision"),
        (isinstance(actual.get("spread_points"), (int, float)), "mt5_spread_missing"),
    ]
    return next((code for ok, code in checks if not ok), None)


class MT5DemoRenderer:
    renderer_type = RendererType.MT5_DEMO

    def __init__(self, config: OutputConfig, transport: FakeMT5Transport):
        self.config, self.transport = config, transport

    def _request(self, context: DeliveryContext, attestation: dict[str, Any]) -> dict[str, Any]:
        t = context.thesis
        return {
            "client_order_id": context.delivery["idempotency_key"],
            "setup_id": t["setup_id"], "thesis_id": t["thesis_id"],
            "symbol": self.config.mt5.symbol_mapping,
            "side": "BUY" if t["direction"] == "LONG" else "SELL",
            "entry": t["entry"], "sl": t["sl"], "tp": t["tp"], "rr": 1.0,
            "spread_points": attestation["spread_points"],
            "environment": "MT5_DEMO", "dry_run": True, "order_placed": False,
            "demo_mirror_enabled": self.config.mt5.demo_mirror_enabled,
        }

    def reconcile_reference(self, context: DeliveryContext) -> str | None:
        attestation = self.transport.attest()
        request = self._request(context, attestation)
        return self.transport.lookup(context.delivery["idempotency_key"], document_hash(request))

    def render(self, context: DeliveryContext, attempt_id: str, now: datetime) -> RendererResult:
        _base_gate(context, self.renderer_type)
        t = context.thesis
        if t["decision"] not in {"APPROVE", "MODIFY"}:
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="mt5_non_actionable")
        if _actionable_expired(context, now):
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="thesis_expired_before_mt5")
        attestation = self.transport.attest()
        error = _mt5_attestation_error(self.config, attestation)
        if error:
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code=error)
        if context.request["spread_points"] > 10 or attestation["spread_points"] > 10:
            return result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                          error_code="mt5_spread_gate")
        request = self._request(context, attestation)
        request_hash = document_hash(request)
        try:
            existing = self.transport.lookup(context.delivery["idempotency_key"], request_hash)
            if existing:
                return result(context, attempt_id, ResultStatus.ALREADY_COMPLETED, now,
                              external_reference=existing, detail={"request": request})
            ticket = self.transport.simulate(request, context.delivery["idempotency_key"])
            return result(context, attempt_id, ResultStatus.DRY_RUN_SUCCESS, now,
                          external_reference=ticket, detail={"request": request})
        except FakeTransportError as exc:
            return _transport_result(context, attempt_id, now, exc)
