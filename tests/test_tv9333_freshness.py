"""OHLC close-time freshness metadata + strict CLI regression tests.

Pure/unit-only: no CDP, Chrome, TradingView, Telegram, wake, Thesis, or broker access.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from capture import tv9333


NOW = datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)
NOW_EPOCH = int(NOW.timestamp())


def _bars(tf, *, raw_age_seconds, count=5):
    step = tv9333.OHLC_INTERVAL_SECONDS[tf]
    latest = NOW_EPOCH - raw_age_seconds
    return [[latest - step * i, 1.0, 2.0, 0.5, 1.5]
            for i in reversed(range(count))]


@pytest.mark.parametrize(
    "tf,raw_age,expected_age,expected_fresh,expected_reason",
    [
        ("m5", 13 * 60, 8 * 60, True, "within_threshold"),
        ("m5", 15 * 60 + 1, 10 * 60 + 1, False, "age_exceeds_threshold"),
        ("m15", 45 * 60, 30 * 60, True, "within_threshold"),
    ],
)
def test_freshness_uses_confirmed_close_time(
        tf, raw_age, expected_age, expected_fresh, expected_reason):
    got = tv9333.build_ohlc_freshness(
        {tf: _bars(tf, raw_age_seconds=raw_age)}, captured_at=NOW)["by_tf"][tf]

    assert got["age_since_close_seconds"] == expected_age
    assert got["fresh"] is expected_fresh
    assert got["reason"] == expected_reason


@pytest.mark.parametrize(
    "bars,reason",
    [
        ([[None, 1, 2, 0, 1]], "invalid_timestamp"),
        ([[NOW_EPOCH - 900, 1, 2, 0, 1],
          [NOW_EPOCH - 900, 1, 2, 0, 1]], "duplicate_timestamp"),
        ([[NOW_EPOCH - 600, 1, 2, 0, 1],
          [NOW_EPOCH - 900, 1, 2, 0, 1]], "non_monotonic_timestamp"),
    ],
)
def test_invalid_timestamp_or_chronology_fails_closed(bars, reason):
    got = tv9333.build_ohlc_freshness({"m5": bars}, captured_at=NOW)["by_tf"]["m5"]

    assert got["fresh"] is False
    assert got["reason"] == reason
    if reason in {"duplicate_timestamp", "non_monotonic_timestamp"}:
        assert got["latest_raw_bar_timestamp"] is not None
        assert got["latest_confirmed_bar_close_time"] is not None


def test_missing_timestamp_fails_closed():
    got = tv9333.build_ohlc_freshness(
        {"m5": [[]]}, captured_at=NOW)["by_tf"]["m5"]

    assert got["fresh"] is False
    assert got["reason"] == "missing_timestamp"


def test_overall_enforces_only_m5_m15_and_htf_is_report_only():
    bars = {
        "m5": _bars("m5", raw_age_seconds=13 * 60),
        "m15": _bars("m15", raw_age_seconds=45 * 60),
        "h4": _bars("h4", raw_age_seconds=8 * 60 * 60),
    }
    got = tv9333.build_ohlc_freshness(bars, captured_at=NOW)

    assert got["overall"]["fresh"] is True
    assert got["required_timeframes"] == ["m5", "m15"]
    assert got["by_tf"]["h4"]["age_since_close_seconds"] == 4 * 60 * 60
    assert got["by_tf"]["h4"]["fresh"] is False
    assert got["by_tf"]["h4"]["enforced_in_overall"] is False
    assert got["by_tf"]["h4"]["reason"] == "report_only_no_live_threshold"


def _all_tf_bars(*, stale_m5):
    return {
        "m5": _bars("m5", raw_age_seconds=(20 * 60 if stale_m5 else 13 * 60)),
        "m15": _bars("m15", raw_age_seconds=45 * 60),
        "h4": _bars("h4", raw_age_seconds=8 * 60 * 60),
        "d": _bars("d", raw_age_seconds=2 * 24 * 60 * 60),
        "w": _bars("w", raw_age_seconds=14 * 24 * 60 * 60),
    }


def test_non_strict_stale_record_still_writes_and_complete_is_unchanged(tmp_path):
    record = tv9333._write_ohlc_history(
        tmp_path / "bundle", bars=_all_tf_bars(stale_m5=True), discovery={},
        n_bars=5, min_bars=5, captured_at=NOW)

    saved = json.loads((tmp_path / "bundle" / "ohlc_history.json").read_text(encoding="utf-8"))
    assert record["complete"] is True
    assert saved["complete"] is True
    assert saved["freshness"]["overall"]["fresh"] is False
    assert saved["captured_utc"] == saved["captured_at"] == "2027-01-15T12:00:00Z"


@pytest.mark.parametrize("strict,expected_exit", [(False, 0), (True, 2)])
def test_ohlc_cli_stale_is_opt_in_strict(
        monkeypatch, tmp_path, capsys, strict, expected_exit):
    bundle = tmp_path / ("strict" if strict else "non-strict")

    def fake_read(path):
        return tv9333._write_ohlc_history(
            path, bars=_all_tf_bars(stale_m5=True), discovery={},
            n_bars=5, min_bars=5, captured_at=NOW)

    argv = ["capture.tv9333", "--ohlc", str(bundle)]
    if strict:
        argv.append("--require-fresh")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(tv9333, "read_ohlc_history", fake_read)

    assert tv9333.main() == expected_exit
    captured = capsys.readouterr()
    assert (bundle / "ohlc_history.json").exists()
    assert '"complete": true' in captured.out
    assert '"status": "stale"' in captured.out
    if strict:
        assert "OHLC freshness gate failed" in captured.err
        assert "m5:" in captured.err
        assert "close_time=" in captured.err
        assert "age=900.0s" in captured.err
        assert "threshold=600s" in captured.err
    else:
        assert "OHLC freshness warning (non-strict; bundle retained)" in captured.err
