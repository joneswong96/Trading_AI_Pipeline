"""Idempotent MT5 Demo outcome history and same-record Notion synchronization."""
from __future__ import annotations

from .fakes import FakeTransportError
from .renderers import NotionRenderer


class OutcomeReconciler:
    def __init__(self, store, notion: NotionRenderer | None = None):
        self.store, self.notion = store, notion

    def update(self, payload: dict) -> bool:
        created = self.store.append_outcome(payload)
        if self.notion is not None:
            try:
                self.notion.sync_outcomes(payload["setup_id"], payload["thesis_id"])
            except FakeTransportError:
                # Outcome history is durable locally. The same Notion record can be
                # reconciled later without mutating the original Thesis or verdict.
                pass
        return created
