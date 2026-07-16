"""Explicit transition table using only Event 0.2 lifecycle values."""
from __future__ import annotations

from dataclasses import dataclass


TERMINAL_STATES = {
    "SETUP_INVALIDATED", "SETUP_EXPIRED", "ENTRY_WINDOW_CLOSED", "THESIS_INVALIDATED",
}
READY_STATES = {"SNR_REJECTION_READY", "SNR_BREAK_READY"}


@dataclass(frozen=True)
class Transition:
    allowed: bool
    next_state: str | None
    persist_state: bool
    create_outbox: bool
    reason_code: str


def transition(current: str | None, event_class: str, event_type: str) -> Transition:
    if event_class == "TELEMETRY":
        return Transition(True, current, current is not None, False,
                          "TELEMETRY_RECORDED" if current is None else "EVIDENCE_UPDATED")

    if current in TERMINAL_STATES:
        return Transition(False, current, False, False, "TERMINAL_SETUP_REOPEN")

    if event_type == "SETUP_CANDIDATE":
        if current in (None, "SETUP_CANDIDATE"):
            return Transition(True, "SETUP_CANDIDATE", True, False,
                              "CANDIDATE_CREATED" if current is None else "CANDIDATE_UPDATED")
        return Transition(False, current, False, False, "CANDIDATE_AFTER_READINESS")

    if event_type in READY_STATES:
        if current in (None, "SETUP_CANDIDATE", *READY_STATES):
            return Transition(True, event_type, True, True,
                              "DIRECT_ANALYSIS_READY" if current is None else "ANALYSIS_READY")
        return Transition(False, current, False, False, "READY_FROM_ILLEGAL_STATE")

    if event_type == "ENTRY_WINDOW_OPEN":
        if current in READY_STATES or current == "ENTRY_WINDOW_OPEN":
            return Transition(True, "ENTRY_WINDOW_OPEN", True, False, "ENTRY_WINDOW_OPENED")
        return Transition(False, current, False, False, "ENTRY_WINDOW_WITHOUT_READY")

    if event_type in {"SETUP_INVALIDATED", "SETUP_EXPIRED"}:
        if current is not None:
            return Transition(True, event_type, True, False,
                              "SETUP_INVALIDATED" if event_type.endswith("INVALIDATED")
                              else "SETUP_EXPIRED")
        return Transition(False, current, False, False, "LIFECYCLE_WITHOUT_SETUP")

    if event_type == "ENTRY_WINDOW_CLOSED":
        if current in READY_STATES or current == "ENTRY_WINDOW_OPEN":
            return Transition(True, event_type, True, False, "ENTRY_WINDOW_CLOSED")
        return Transition(False, current, False, False, "CLOSE_WITHOUT_READY")

    if event_type == "THESIS_INVALIDATED":
        if current in READY_STATES or current == "ENTRY_WINDOW_OPEN":
            return Transition(True, event_type, True, False, "THESIS_INVALIDATED")
        return Transition(False, current, False, False, "THESIS_WITHOUT_READY")

    return Transition(False, current, False, False, "EVENT_TYPE_CLASS_MISMATCH")
