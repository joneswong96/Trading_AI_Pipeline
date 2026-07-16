"""Stable fail-closed failure model for Project A capture."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailurePolicy:
    retryable: bool
    next_action: str


FAILURE_POLICIES = {
    "PORT_MISMATCH": FailurePolicy(False, "Configure the dedicated route on 127.0.0.1:4999."),
    "PORT_UNAVAILABLE": FailurePolicy(True, "Start the approved isolated browser on port 4999, then rerun preflight."),
    "WRONG_PROCESS": FailurePolicy(False, "Stop the conflicting listener and start the approved browser profile."),
    "UNSAFE_BINDING": FailurePolicy(False, "Bind CDP only to a loopback interface."),
    "MCP_UNAVAILABLE": FailurePolicy(True, "Restore the local CDP/MCP boundary and rerun preflight."),
    "TAB_NOT_FOUND": FailurePolicy(True, "Open and explicitly pin the approved TradingView chart tab."),
    "TAB_AMBIGUOUS": FailurePolicy(True, "Close duplicate matching tabs and pin exactly one target ID."),
    "WRONG_TAB": FailurePolicy(True, "Pin the exact approved target ID and chart URL."),
    "PAGE_NOT_READY": FailurePolicy(True, "Clear loading/disconnected state and wait for structured chart readiness."),
    "AUTH_UNUSABLE": FailurePolicy(True, "Sign in within the isolated profile without exporting credentials."),
    "WRONG_SYMBOL": FailurePolicy(True, "Correct the pinned tab manually; do not switch tabs automatically."),
    "WRONG_FEED": FailurePolicy(True, "Correct the broker feed manually; similar feeds are not accepted."),
    "WRONG_TIMEFRAME": FailurePolicy(True, "Restore the configured timeframe and rerun verification."),
    "WRONG_LAYOUT": FailurePolicy(True, "Load the exact allowlisted layout in the pinned tab."),
    "MISSING_TIMEFRAME": FailurePolicy(True, "Make every required timeframe available in the pinned chart."),
    "CHART_NOT_READY": FailurePolicy(True, "Wait for the deterministic chart-ready condition, then retry before expiry."),
    "STALE_CHART": FailurePolicy(True, "Restore a streaming chart whose update covers the source bar, then retry before expiry."),
    "MODAL_BLOCKING": FailurePolicy(True, "Dismiss the modal/login/loading overlay manually and retry."),
    "DESTINATION_UNWRITABLE": FailurePolicy(True, "Restore write access to the configured artifact root."),
    "SCREENSHOT_FAILURE": FailurePolicy(True, "Retry the same pinned tab before the original expiry."),
    "ARTIFACT_WRITE_FAILURE": FailurePolicy(True, "Repair storage while retaining the failed attempt, then retry."),
    "ARTIFACT_HASH_MISMATCH": FailurePolicy(False, "Quarantine the attempt and preserve all failed evidence."),
    "ARTIFACT_MISSING": FailurePolicy(False, "Quarantine the incomplete bundle; never release it downstream."),
    "SOURCE_EXPIRED": FailurePolicy(False, "Retain the attempt; only a new valid source event can authorize capture."),
    "SOURCE_INVALID": FailurePolicy(False, "Reject or quarantine the source event at the producer boundary."),
    "COMPILATION_INPUT_MISSING": FailurePolicy(False, "Provide the documented Event 0.2 payload extension from the producer."),
    "CONTRACT_COMPILATION_FAILURE": FailurePolicy(False, "Retain inputs and request Session 0 review if an adapter cannot solve it."),
    "PARTIAL_CAPTURE": FailurePolicy(True, "Retry the same dispatch before expiry; do not compile the partial attempt."),
    "DISPATCH_CONFLICT": FailurePolicy(False, "Quarantine the conflicting payload for the reused dispatch ID."),
    "RETRY_SEQUENCE_INVALID": FailurePolicy(False, "Use a strictly increasing retry count for the same dispatch."),
    "PATH_TRAVERSAL": FailurePolicy(False, "Quarantine the manifest and use only store-generated relative paths."),
}


class Session3Error(RuntimeError):
    """Bounded operational failure with stable retry semantics."""

    def __init__(self, code: str, detail: str, *, attempt_id: str | None = None):
        if code not in FAILURE_POLICIES:
            raise ValueError(f"unknown Session 3 error code: {code}")
        self.code = code
        self.detail = str(detail)[:500]
        self.attempt_id = attempt_id
        policy = FAILURE_POLICIES[code]
        self.retryable = policy.retryable
        self.next_action = policy.next_action
        super().__init__(f"{code}: {self.detail}")

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "detail": self.detail,
            "retryable": self.retryable,
            "next_action": self.next_action,
            "attempt_id": self.attempt_id,
        }
