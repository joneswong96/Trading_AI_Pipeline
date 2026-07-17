from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from capture.project_a.cdp import (
    PlaywrightPinnedDriver,
    TransitionConfig,
    wait_for_timeframe_stability,
)
from capture.project_a.errors import Session3Error
from capture.project_a.preflight import ChartState
from capture.project_a.profile import CaptureProfile, REQUIRED_TIMEFRAMES, TabPin

UTC = timezone.utc
NOW = datetime(2026, 7, 17, 4, 20, tzinfo=UTC)
TARGET = "F2F27AAA3050DC8F9769939CB9B2E84C"


def profile() -> CaptureProfile:
    return CaptureProfile.from_dict({
        "symbol": "XAUUSD",
        "enabled": True,
        "real_browser_enabled": True,
        "aliases": ["ICMARKETS:XAUUSD"],
        "broker_feed": "ICMARKETS",
        "host": "127.0.0.1",
        "port": 4999,
        "base_timeframe": "1m",
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "expected_layout_id": "gwnVPYuQ",
        "expected_chart_url": "https://www.tradingview.com/chart/gwnVPYuQ/",
        "expected_chart_count": 1,
        "process_names": ["chrome.exe"],
        "profile_marker": "ProjectA-XAUUSD-4999",
    })


def pin() -> TabPin:
    return TabPin(TARGET, profile().expected_chart_url, profile().expected_layout_id)


def state(*, structured="5s", header="5s", last_bar=True, **changes) -> ChartState:
    bar = NOW - timedelta(minutes=1) if last_bar else None
    data = dict(
        page_ready=True,
        authenticated=True,
        url=profile().expected_chart_url,
        layout_id=profile().expected_layout_id,
        chart_count=1,
        structured_symbol="ICMARKETS:XAUUSD",
        canonical_symbol="XAUUSD",
        header_symbol="XAUUSD",
        broker_feed="ICMARKETS",
        header_feed="ICMARKETS",
        timeframe=structured,
        header_timeframe=header,
        available_timeframes=REQUIRED_TIMEFRAMES,
        data_status="streaming" if last_bar else "unknown",
        last_bar_at=bar,
        last_update_at=bar,
        header_identity_evidence={"resolution": {"resolution_status": "OK"}},
        target_id=TARGET,
        target_match_count=1,
    )
    data.update(changes)
    return ChartState(**data)


class FakeClock:
    def __init__(self, *, advance=True):
        self.value = 0.0
        self.advance = advance
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.advance:
            self.value += seconds

    def wall_clock(self):
        return NOW


class SequenceObserver:
    def __init__(self, observations):
        self.observations = list(observations)
        self.calls = 0

    def __call__(self):
        index = min(self.calls, len(self.observations) - 1)
        self.calls += 1
        value = self.observations[index]
        if isinstance(value, Exception):
            raise value
        return value


def run(observations, *, requested="5s", previous="1m", timeout=1.0, clock=None):
    clock = clock or FakeClock()
    observer = SequenceObserver(observations)
    result = wait_for_timeframe_stability(
        profile(), pin(), requested, previous, observer,
        config=TransitionConfig(timeout_seconds=timeout, poll_interval_seconds=0.1),
        monotonic=clock.monotonic, sleep=clock.sleep, wall_clock=clock.wall_clock,
    )
    return result, observer, clock


def timeout(observations, *, timeout_seconds=0.4, clock=None):
    clock = clock or FakeClock()
    observer = SequenceObserver(observations)
    with pytest.raises(Session3Error) as raised:
        wait_for_timeframe_stability(
            profile(), pin(), "5s", "1m", observer,
            config=TransitionConfig(timeout_seconds=timeout_seconds, poll_interval_seconds=0.1),
            monotonic=clock.monotonic, sleep=clock.sleep, wall_clock=clock.wall_clock,
        )
    assert raised.value.code == "TIMEFRAME_STABILIZATION_TIMEOUT"
    return json.loads(raised.value.detail), observer, clock


def test_exact_observed_sequence_waits_for_header_and_two_stable_samples():
    result, observer, _ = run([
        state(structured="5s", header="1m", last_bar=False),
        state(structured="5s", header="5s"),
        state(structured="5s", header="5s"),
    ])
    assert observer.calls == 3
    assert result.transition_evidence["stable_sample_count"] == 2
    assert result.transition_evidence["observation_count"] == 3


def test_header_changes_first_and_structured_state_lags():
    result, observer, _ = run([
        state(structured="1m", header="5s"),
        state(), state(),
    ])
    assert observer.calls == 3 and result.timeframe == "5s"


def test_missing_last_bar_is_transient_then_succeeds():
    result, observer, _ = run([state(last_bar=False), state(), state()])
    assert observer.calls == 3 and result.last_bar_at is not None


def test_mismatch_after_one_stable_sample_resets_counter():
    result, observer, _ = run([state(), state(header="1m"), state(), state()])
    assert observer.calls == 4
    assert result.transition_evidence["stable_sample_count"] == 2


def test_two_consecutive_stable_samples_return_success():
    result, observer, _ = run([state(), state()])
    assert observer.calls == 2 and result.transition_evidence["status"] == "STABLE"


def test_one_stable_sample_only_never_returns_success():
    evidence, _, _ = timeout([state(), state(header="1m")])
    assert evidence["stable_sample_count"] == 0


def test_permanent_structured_header_disagreement_times_out():
    evidence, _, _ = timeout([state(header="1m")])
    assert evidence["latest_structured_interval"] == "5s"
    assert evidence["latest_header_interval"] == "1m"


def test_last_bar_absent_until_deadline_times_out():
    evidence, _, _ = timeout([state(last_bar=False)])
    assert evidence["last_bar_present"] is False


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"structured_symbol": "OANDA:XAGUSD", "canonical_symbol": "XAGUSD"}, "WRONG_SYMBOL"),
        ({"broker_feed": "OANDA"}, "WRONG_FEED"),
        ({"target_id": "OTHER"}, "WRONG_TAB"),
        ({"layout_id": "other-layout"}, "WRONG_LAYOUT"),
        ({"chart_count": 2}, "WRONG_LAYOUT"),
        ({"modal_blocking": True}, "MODAL_BLOCKING"),
    ],
)
def test_hard_transition_identity_failures_are_immediate(changes, code):
    observer = SequenceObserver([replace(state(), **changes)])
    clock = FakeClock()
    with pytest.raises(Session3Error) as raised:
        wait_for_timeframe_stability(
            profile(), pin(), "5s", "1m", observer,
            config=TransitionConfig(timeout_seconds=1, poll_interval_seconds=0.1),
            monotonic=clock.monotonic, sleep=clock.sleep, wall_clock=clock.wall_clock,
        )
    assert raised.value.code == code
    assert observer.calls == 1 and clock.sleeps == []


def test_conflicting_header_evidence_is_an_immediate_hard_failure():
    conflicting = replace(
        state(),
        header_identity_evidence={"resolution": {"resolution_status": "AMBIGUOUS"}},
    )
    observer = SequenceObserver([conflicting])
    clock = FakeClock()
    with pytest.raises(Session3Error) as raised:
        wait_for_timeframe_stability(
            profile(), pin(), "5s", "1m", observer,
            monotonic=clock.monotonic, sleep=clock.sleep, wall_clock=clock.wall_clock,
        )
    assert raised.value.code == "WRONG_SYMBOL"
    assert observer.calls == 1


def test_monotonic_deadline_is_enforced():
    evidence, observer, clock = timeout([state(header="1m")], timeout_seconds=0.4)
    assert clock.value == pytest.approx(0.4)
    assert observer.calls == 4
    assert evidence["elapsed_seconds"] == pytest.approx(0.4)


def test_poll_count_is_bounded_even_if_injected_clock_does_not_advance():
    evidence, observer, clock = timeout(
        [state(header="1m")], timeout_seconds=0.4, clock=FakeClock(advance=False)
    )
    assert observer.calls == 5
    assert len(clock.sleeps) == 4
    assert evidence["observation_count"] == 5


def test_transient_chart_not_ready_exception_resets_and_recovers():
    transient = Session3Error("CHART_NOT_READY", "series is loading")
    result, observer, _ = run([transient, state(), state()])
    assert observer.calls == 3 and result.timeframe == "5s"


def test_restoration_uses_same_two_sample_rule_and_tolerates_header_lag():
    result, observer, _ = run([
        state(structured="1m", header="30m"),
        state(structured="1m", header="1m"),
        state(structured="1m", header="1m"),
    ], requested="1m", previous="30m")
    assert observer.calls == 3
    assert result.transition_evidence["requested_timeframe"] == "1m"
    assert result.transition_evidence["stable_sample_count"] == 2


def test_restoration_timeout_remains_fail_closed():
    clock = FakeClock()
    observer = SequenceObserver([state(structured="1m", header="30m")])
    with pytest.raises(Session3Error) as raised:
        wait_for_timeframe_stability(
            profile(), pin(), "1m", "30m", observer,
            config=TransitionConfig(timeout_seconds=0.4, poll_interval_seconds=0.1),
            monotonic=clock.monotonic, sleep=clock.sleep, wall_clock=clock.wall_clock,
        )
    assert raised.value.code == "TIMEFRAME_STABILIZATION_TIMEOUT"


class FakePage:
    def __init__(self, clock):
        self.clock = clock
        self.switch_calls = 0
        self.screenshot_calls = 0

    def evaluate(self, _script, _value):
        self.switch_calls += 1
        return {"ok": True}

    def wait_for_timeout(self, milliseconds):
        self.clock.sleep(milliseconds / 1000)

    def screenshot(self, **_kwargs):
        self.screenshot_calls += 1
        return b"real-png"


def test_driver_issues_one_switch_and_never_screenshots_before_stabilization():
    clock = FakeClock()
    page = FakePage(clock)
    observer = SequenceObserver([state(header="1m"), state(), state()])
    driver = PlaywrightPinnedDriver(
        profile(), pin(),
        transition_config=TransitionConfig(timeout_seconds=1, poll_interval_seconds=0.1),
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
    )
    driver._page = page
    driver._last_observed_timeframe = "1m"
    driver.inspect = observer
    stable = driver.switch_and_wait("5s", timeout_seconds=1)
    assert page.switch_calls == 1
    assert page.screenshot_calls == 0
    assert observer.calls == 3 and stable.header_timeframe == "5s"
    assert driver.screenshot() == b"real-png"
    assert page.screenshot_calls == 1


def test_transition_configuration_rejects_unbounded_or_weakened_values():
    with pytest.raises(ValueError):
        TransitionConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        TransitionConfig(poll_interval_seconds=0)
    with pytest.raises(ValueError):
        TransitionConfig(required_stable_samples=1)
