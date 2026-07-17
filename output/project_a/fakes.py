"""Deterministic fake transports. No class in this module performs network or broker I/O."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from contracts import canonical_json

from .models import document_hash, stable_id


class FakeTransportError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, uncertain: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.uncertain = uncertain


class FakeTradingViewTransport:
    def __init__(self, identity: dict[str, Any] | None = None):
        self.identity = identity or {
            "port": 4999,
            "process_identity": "FAKE_TRADINGVIEW_MCP",
            "tab_count": 1,
            "selected_tab_id": "tv-tab-xauusd",
            "symbol": "XAUUSD",
            "feed": "ICMARKETS",
            "timeframe": "1m",
            "layout_id": "PROJECT_A_XAUUSD_1M",
        }
        self.objects: dict[str, dict[str, Any]] = {}
        self.bundles: dict[str, dict[str, Any]] = {}
        self.fail_after: int | None = None
        self.cleanup_fails = False
        self.mutation_calls = 0
        self.deleted_refs: list[str] = []

    def inspect(self) -> dict[str, Any]:
        return deepcopy(self.identity)

    def lookup_bundle(self, idempotency_key: str, thesis_hash: str) -> str | None:
        item = self.bundles.get(idempotency_key)
        if not item:
            return None
        if item["thesis_hash"] != thesis_hash:
            raise FakeTransportError("tv_idempotency_conflict")
        return item["external_reference"]

    def upsert(self, object_id: str, spec: dict[str, Any]) -> tuple[str, bool]:
        existing = self.objects.get(object_id)
        if existing:
            if existing["hash"] != document_hash(spec):
                raise FakeTransportError("tv_object_conflict")
            return existing["reference"], False
        if self.fail_after is not None and self.mutation_calls >= self.fail_after:
            raise FakeTransportError("tv_partial_create", retryable=True)
        self.mutation_calls += 1
        reference = f"fake-tv://{object_id}"
        self.objects[object_id] = {
            "reference": reference, "hash": document_hash(spec), "spec": deepcopy(spec),
        }
        return reference, True

    def verify(self, specs: list[dict[str, Any]]) -> bool:
        return all(
            item["object_id"] in self.objects
            and self.objects[item["object_id"]]["hash"] == document_hash(item)
            for item in specs
        )

    def cleanup(self, references: list[str]) -> None:
        if self.cleanup_fails:
            raise FakeTransportError("tv_cleanup_failed")
        allowed = set(references)
        for object_id, item in list(self.objects.items()):
            if item["reference"] in allowed:
                self.deleted_refs.append(item["reference"])
                del self.objects[object_id]

    def commit_bundle(self, idempotency_key: str, thesis_hash: str,
                      references: list[str]) -> str:
        external = "fake-tv-bundle://" + stable_id("objects", *sorted(references), length=24)
        self.bundles[idempotency_key] = {
            "thesis_hash": thesis_hash, "external_reference": external,
            "references": list(references),
        }
        return external


class FakeTelegramTransport:
    def __init__(self):
        self.messages: dict[str, dict[str, Any]] = {}
        self.send_calls = 0
        self.failure_mode: str | None = None

    def lookup(self, idempotency_key: str, content_hash: str) -> str | None:
        existing = self.messages.get(idempotency_key)
        if not existing:
            return None
        if existing["content_hash"] != content_hash:
            raise FakeTransportError("telegram_idempotency_conflict")
        return existing["message_id"]

    def send(self, *, destination_id: str, message: str,
             idempotency_key: str, content_hash: str) -> str:
        existing = self.lookup(idempotency_key, content_hash)
        if existing:
            return existing
        self.send_calls += 1
        if self.failure_mode == "retryable_before":
            self.failure_mode = None
            raise FakeTransportError("telegram_unavailable", retryable=True)
        message_id = str(7000 + len(self.messages) + 1)
        self.messages[idempotency_key] = {
            "message_id": message_id, "destination_id": destination_id,
            "message": message, "content_hash": content_hash,
        }
        if self.failure_mode == "uncertain_after_success":
            self.failure_mode = None
            raise FakeTransportError("telegram_response_uncertain", uncertain=True)
        return message_id


class FakeNotionTransport:
    def __init__(self):
        self.records: dict[str, dict[str, Any]] = {}
        self.upsert_calls = 0
        self.failure_mode: str | None = None

    def lookup(self, setup_id: str, core_hash: str) -> str | None:
        existing = self.records.get(setup_id)
        if not existing:
            return None
        if existing["core_hash"] != core_hash:
            raise FakeTransportError("notion_setup_conflict")
        return existing["page_id"]

    def upsert(self, setup_id: str, core_hash: str, record: dict[str, Any]) -> str:
        page_id = self.lookup(setup_id, core_hash)
        self.upsert_calls += 1
        if self.failure_mode == "retryable_before":
            self.failure_mode = None
            raise FakeTransportError("notion_update_failed", retryable=True)
        if not page_id:
            page_id = "fake-notion://" + stable_id("page", setup_id, length=24)
        self.records[setup_id] = {
            "page_id": page_id, "core_hash": core_hash, "record": deepcopy(record),
        }
        return page_id

    def update_statuses(self, setup_id: str, statuses: dict[str, str]) -> bool:
        if setup_id not in self.records:
            return False
        if self.failure_mode == "status_update_failure":
            self.failure_mode = None
            raise FakeTransportError("notion_status_update_failed", retryable=True)
        self.records[setup_id]["record"]["renderer_statuses"] = dict(sorted(statuses.items()))
        return True

    def append_outcomes(self, setup_id: str, outcomes: list[dict[str, Any]]) -> bool:
        if setup_id not in self.records:
            return False
        self.records[setup_id]["record"]["mt5_outcomes"] = deepcopy(outcomes)
        return True


class FakeMT5Transport:
    def __init__(self, attestation: dict[str, Any] | None = None):
        self.attestation = attestation or {
            "connected": True,
            "environment": "MT5_DEMO",
            "account_id": "FAKE-DEMO-1001",
            "server": "FAKE-BROKER-DEMO",
            "trade_mode": "DEMO",
            "terminal_path": "C:\\FAKE\\MT5-DEMO\\terminal64.exe",
            "symbol": "XAUUSD",
            "precision": 2,
            "spread_points": 8,
        }
        self.orders: dict[str, dict[str, Any]] = {}
        self.submit_calls = 0
        self.failure_mode: str | None = None

    def attest(self) -> dict[str, Any]:
        return deepcopy(self.attestation)

    def lookup(self, idempotency_key: str, request_hash: str) -> str | None:
        existing = self.orders.get(idempotency_key)
        if not existing:
            return None
        if existing["request_hash"] != request_hash:
            raise FakeTransportError("mt5_idempotency_conflict")
        return existing["ticket_ref"]

    def simulate(self, request: dict[str, Any], idempotency_key: str) -> str:
        request_hash = document_hash(request)
        existing = self.lookup(idempotency_key, request_hash)
        if existing:
            return existing
        self.submit_calls += 1
        if self.failure_mode == "retryable_before":
            self.failure_mode = None
            raise FakeTransportError("mt5_demo_unavailable", retryable=True)
        ticket = "FAKE-DEMO-TICKET-" + str(9000 + len(self.orders) + 1)
        self.orders[idempotency_key] = {
            "ticket_ref": ticket, "request_hash": request_hash, "request": deepcopy(request),
        }
        if self.failure_mode == "uncertain_after_acceptance":
            self.failure_mode = None
            raise FakeTransportError("mt5_result_uncertain", uncertain=True)
        return ticket


def json_reference(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
