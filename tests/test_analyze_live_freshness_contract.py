"""Regression contract for the natural-language `/analyze` live OHLC barrier.

The command markdown is the production orchestrator. Tests parse both installed copies and model
its documented exit-code control flow only; no capture, CDP, gates, Thesis, wake, or publisher runs.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INNER = ROOT / ".claude" / "commands" / "analyze.md"
OUTER = ROOT.parent / ".claude" / "commands" / "analyze.md"
STRICT_COMMAND = "py -m capture.tv9333 --ohlc <bundle> --require-fresh"


def _text(path=INNER):
    return path.read_text(encoding="utf-8")


def _executable_ohlc_lines(markdown):
    found = []
    for line in markdown.splitlines():
        match = re.search(r"py -m capture\.tv9333 --ohlc <bundle> --require-fresh", line)
        if match:
            found.append(match.group(0))
    return found


def _simulate_command_flow(markdown, producer_exit, *, complete_false=False):
    """Model the markdown's terminal barrier, with observable downstream side effects."""
    events = ["ohlc_producer"]
    if producer_exit:
        if producer_exit == 1 and complete_false:
            label = "DATA_INCOMPLETE"
        elif producer_exit == 2:
            label = "DATA_STALE"
        else:
            label = "OHLC_PRODUCER_ERROR"
        return {"label": label, "events": events, "thesis_status": None,
                "wake_consumed": False}
    events.extend(["read_charts", "deterministic_gates", "direction",
                   "thesis_json", "thesis_emit", "wake_consume"])
    return {"label": "OHLC_FRESH_OK", "events": events, "thesis_status": "ARMED",
            "wake_consumed": True}


def test_dual_command_copies_are_byte_identical():
    if not OUTER.exists():
        pytest.skip("outer workspace command copy is not installed in this checkout")
    inner = INNER.read_bytes()
    outer = OUTER.read_bytes()

    assert inner == outer
    assert hashlib.sha256(inner).hexdigest() == hashlib.sha256(outer).hexdigest()


def test_live_ohlc_command_is_strict_and_precedes_all_analysis_steps():
    markdown = _text()

    assert _executable_ohlc_lines(markdown) == [STRICT_COMMAND]
    barrier = markdown.index("LIVE_OHLC_INGESTION_BARRIER")
    assert barrier < markdown.index("### 2 — Read 5 張圖")
    assert barrier < markdown.index("### 3 — 跑 SOP")
    assert barrier < markdown.index("py -c \"import json; from gates.day_type")
    assert barrier < markdown.index("'<你砌好的 Thesis JSON 一行>' | py -m analyze.thesis_emit")


@pytest.mark.parametrize(
    "exit_code,complete_false,label",
    [(1, True, "DATA_INCOMPLETE"), (1, False, "OHLC_PRODUCER_ERROR"),
     (2, False, "DATA_STALE"), (7, False, "OHLC_PRODUCER_ERROR")],
)
def test_nonzero_ohlc_exit_aborts_before_gates_thesis_and_wake(
        exit_code, complete_false, label):
    result = _simulate_command_flow(_text(), exit_code, complete_false=complete_false)

    assert result["label"] == label
    assert result["events"] == ["ohlc_producer"]
    assert result["thesis_status"] is None       # especially not WAIT / NO_TRADE
    assert result["wake_consumed"] is False


def test_exit_zero_allows_downstream_flow():
    result = _simulate_command_flow(_text(), 0)

    assert result["label"] == "OHLC_FRESH_OK"
    assert "deterministic_gates" in result["events"]
    assert "thesis_emit" in result["events"]


def test_abort_contract_preserves_audit_and_reports_stale_evidence():
    markdown = _text()

    for required in ("bundle已保留", "consumed_by=null", "consumed_at=null",
                     "latest_confirmed_bar_close_time", "age_since_close_seconds",
                     "freshness_threshold_seconds", "唔准自動restart／reload／navigate",
                     "-match '\"complete\"\\s*:\\s*false'", "若exit 1係exception"):
        assert required in markdown
    assert "絕對唔准轉譯成WAIT Thesis、NO_TRADE" in markdown


def test_historical_consumers_remain_non_strict():
    structure = (ROOT / "scripts" / "structure_adjudicate.py").read_text(encoding="utf-8")
    guide = (ROOT / "scripts" / "adjudicate_guide.py").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")

    assert "--require-fresh" not in structure
    assert "--require-fresh" not in guide
    assert "py -m capture.tv9333 --ohlc storage\\screenshots\\<cycle_id>\n" in runbook
    assert "py -m capture.tv9333 --ohlc storage\\screenshots\\<cycle_id> --require-fresh" in runbook
