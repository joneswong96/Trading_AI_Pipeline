"""Independent outbox delivery, recovery, and explicit uncertain-result reconciliation."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .fakes import FakeTransportError
from .models import ResultStatus, Session5Error, result
from .renderers import NotionRenderer, Renderer


class Dispatcher:
    def __init__(self, store, config, renderers: Iterable[Renderer], *, worker: str = "session5"):
        self.store, self.config, self.worker = store, config, worker
        self.renderers = {renderer.renderer_type.value: renderer for renderer in renderers}

    def dispatch(self, delivery_id: str, *, now: datetime):
        claimed = self.store.claim(delivery_id, self.worker, now, self.config.retry_limit)
        if claimed is None:
            return None
        attempt_id, claim_token = claimed
        context = self.store.get_context(delivery_id)
        renderer = self.renderers.get(context.delivery["renderer_type"])
        if renderer is None:
            rendered = result(context, attempt_id, ResultStatus.TERMINAL_FAILURE, now,
                              error_code="renderer_not_registered")
        else:
            try:
                rendered = renderer.render(context, attempt_id, now)
            except Session5Error as exc:
                rendered = result(context, attempt_id, ResultStatus.BLOCKED_SAFETY, now,
                                  error_code=exc.code)
            except Exception:
                rendered = result(context, attempt_id, ResultStatus.RETRYABLE_FAILURE, now,
                                  error_code="renderer_exception")
        self.store.finish(rendered, claim_token, retry_seconds=self.config.retry_seconds)
        self._sync_notion_statuses(context.thesis["setup_id"])
        return rendered

    def dispatch_setup(self, setup_id: str, *, now: datetime,
                       renderer_type: str | None = None, failed_only: bool = False):
        order = {"TRADINGVIEW": 0, "TELEGRAM": 1, "NOTION": 2, "MT5_DEMO": 3}
        deliveries = sorted(self.store.deliveries_for_setup(setup_id),
                            key=lambda item: order.get(item["renderer_type"], 99))
        results = []
        for delivery in deliveries:
            if renderer_type and delivery["renderer_type"] != renderer_type:
                continue
            if failed_only and delivery["status"] not in {"RETRYABLE_FAILED", "TERMINAL_FAILED",
                                                           "BLOCKED_SAFETY", "UNCERTAIN"}:
                continue
            rendered = self.dispatch(delivery["delivery_id"], now=now)
            if rendered is not None:
                results.append(rendered)
        return results

    def recover_abandoned(self, *, now: datetime) -> int:
        return self.store.recover_abandoned(now, self.config.claim_timeout_seconds)

    def reconcile_uncertain(self, delivery_id: str, *, now: datetime,
                            actor: str, reason: str) -> bool:
        context = self.store.get_context(delivery_id)
        if context.delivery["status"] != "UNCERTAIN":
            raise Session5Error("not_uncertain", delivery_id)
        renderer = self.renderers.get(context.delivery["renderer_type"])
        if renderer is None:
            raise Session5Error("renderer_not_registered", context.delivery["renderer_type"])
        try:
            external_reference = renderer.reconcile_reference(context)
        except FakeTransportError as exc:
            raise Session5Error(exc.code, "reconciliation conflict") from exc
        found = external_reference is not None
        self.store.resolve_uncertain(
            delivery_id, found=found, external_reference=external_reference,
            actor=actor, reason=reason, now=now,
        )
        self._sync_notion_statuses(context.thesis["setup_id"])
        return found

    def _sync_notion_statuses(self, setup_id: str) -> None:
        renderer = self.renderers.get("NOTION")
        if isinstance(renderer, NotionRenderer):
            try:
                renderer.sync_statuses(setup_id)
            except FakeTransportError:
                # The durable Notion delivery remains the authority for retry. A failed
                # supplemental status sync never re-executes other completed renderers.
                pass
