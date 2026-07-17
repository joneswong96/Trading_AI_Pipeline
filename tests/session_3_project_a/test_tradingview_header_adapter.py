from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path

import pytest

from capture.project_a.cdp import (
    normalize_header_feed,
    normalize_header_symbol,
    normalize_header_timeframe,
    resolve_header_identity,
)
from capture.project_a.cli import _configure_utf8_stream, _write_json

FIXTURE = Path(__file__).with_name("fixtures") / "tradingview_header_current.json"


def current_evidence() -> dict:
    return deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["header_identity"])


def test_current_accessible_header_fixture_resolves_independent_identity():
    symbol, feed, timeframe, audit = resolve_header_identity(current_evidence())
    assert (symbol, feed, timeframe) == ("XAUUSD", "ICMARKETS", "1m")
    assert audit["resolution_status"] == "OK"


def test_legacy_data_name_fallback_resolves_only_bounded_chart_legend():
    evidence = {
        "status": "OK",
        "strategy": "LEGACY_DATA_NAME",
        "chart_region_count": 1,
        "candidates": [{
            "kind": "combined",
            "channel": "legacy_data_name",
            "scope": "active_chart_legend",
            "raw": "ICMARKETS:XAUUSD · 1m",
            "visible": True,
        }],
    }
    assert resolve_header_identity(evidence)[:3] == ("XAUUSD", "ICMARKETS", "1m")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("XAUUSD", "XAUUSD"),
        ("ICMARKETS:XAUUSD", "XAUUSD"),
        ("Gold Spot / U.S. Dollar", "XAUUSD"),
        ("OANDA:XAGUSD", "XAGUSD"),
        ("Gold", ""),
    ],
)
def test_symbol_display_normalization(raw, expected):
    assert normalize_header_symbol(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("IC Markets", "ICMARKETS"), ("ICMARKETS", "ICMARKETS"),
     ("ICMARKETS:XAUUSD", "ICMARKETS"), ("OANDA:XAUUSD", "OANDA"), ("IC", "")],
)
def test_feed_display_normalization(raw, expected):
    assert normalize_header_feed(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5S", "5s"), ("1", "1m"), ("5m", "5m"), ("15 minutes", "15m"),
     ("30", "30m"), ("ICMARKETS:XAUUSD · 1 · IC Markets", "1m")],
)
def test_timeframe_display_normalization(raw, expected):
    assert normalize_header_timeframe(raw) == expected


def test_empty_header_evidence_fails_closed():
    symbol, feed, timeframe, audit = resolve_header_identity({})
    assert (symbol, feed, timeframe) == ("", "", "")
    assert audit["resolution_status"] == "MISSING"


def test_wrong_visible_header_symbol_is_preserved_for_rejection():
    evidence = current_evidence()
    evidence["candidates"][0]["raw"] = "OANDA:XAGUSD"
    assert resolve_header_identity(evidence)[:3] == ("XAGUSD", "ICMARKETS", "1m")


def test_wrong_visible_header_feed_is_preserved_for_rejection():
    evidence = current_evidence()
    evidence["candidates"][2]["raw"] = "OANDA"
    assert resolve_header_identity(evidence)[:3] == ("XAUUSD", "OANDA", "1m")


def test_conflicting_visible_symbol_candidates_are_ambiguous():
    evidence = current_evidence()
    evidence["candidates"].append({
        "kind": "symbol", "channel": "accessible_header_controls",
        "scope": "active_chart_header", "raw": "OANDA:XAGUSD", "visible": True,
    })
    symbol, _, _, audit = resolve_header_identity(evidence)
    assert symbol == ""
    assert audit["resolution_status"] == "AMBIGUOUS"


def test_multiple_visible_chart_regions_fail_closed():
    evidence = current_evidence()
    evidence.update(status="AMBIGUOUS", chart_region_count=2)
    assert resolve_header_identity(evidence)[:3] == ("", "", "")


def test_hidden_unrelated_symbol_does_not_contaminate_active_header():
    evidence = current_evidence()
    evidence["candidates"].append({
        "kind": "symbol", "channel": "other", "scope": "active_chart_header",
        "raw": "OANDA:XAGUSD", "visible": False,
    })
    assert resolve_header_identity(evidence)[:3] == ("XAUUSD", "ICMARKETS", "1m")


@pytest.mark.parametrize("scope", ["watchlist", "alerts_panel"])
def test_unrelated_visible_dom_never_supplies_header_identity(scope):
    evidence = current_evidence()
    for candidate in evidence["candidates"]:
        candidate["scope"] = scope
    symbol, feed, timeframe, audit = resolve_header_identity(evidence)
    assert (symbol, feed, timeframe) == ("", "", "")
    assert audit["resolution_status"] == "MISSING"


def test_structured_symbol_cannot_backfill_missing_independent_header():
    evidence = {
        "status": "OK", "strategy": "NONE", "chart_region_count": 1,
        "structured_symbol": "ICMARKETS:XAUUSD", "candidates": [],
    }
    assert resolve_header_identity(evidence)[:3] == ("", "", "")


def test_cp1252_console_is_reconfigured_and_emits_unicode_json_as_utf8():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    _configure_utf8_stream(stream)
    _write_json({"title": "XAUUSD ▲"}, stream)
    stream.flush()
    rendered = raw.getvalue().decode("utf-8")
    assert json.loads(rendered) == {"title": "XAUUSD ▲"}
