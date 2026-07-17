"""Live capture orchestration separated from pure compilation and replay."""
from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Callable, Protocol

from .artifacts import ArtifactStore
from .errors import Session3Error
from .input_boundary import validate_analysis_ready
from .preflight import verify_chart_state, verify_preflight
from .profile import CaptureProfile, TabPin


class Probe(Protocol):
    def inspect(self, profile: CaptureProfile): ...


class Driver(AbstractContextManager):
    def inspect(self): ...
    def switch_and_wait(self, timeframe: str): ...
    def screenshot(self) -> bytes: ...


def capture_event(canonical_event: dict, analysis_adapter: dict,
                  profile: CaptureProfile, pin: TabPin,
                  store: ArtifactStore, probe: Probe,
                  driver_factory: Callable[[CaptureProfile, TabPin], Driver], *,
                  dispatch_id: str, retry_count: int,
                  now: Callable[[], datetime],
                  capture_method: str = "PROJECT_A_CDP",
                  tool_version: str = "project-a-session-3/1.0.0") -> tuple[dict, str]:
    if capture_method != "FIXTURE":
        profile.require_real_browser_activation()
    authority = validate_analysis_ready(
        canonical_event,
        analysis_adapter,
        require_compiler_fields=True,
    )
    started_at = now().astimezone(timezone.utc)
    authority.ensure_capture_chronology(started_at)
    if not store.writable():
        raise Session3Error("DESTINATION_UNWRITABLE", str(store.root))
    attempt_dir, manifest = store.begin(
        authority, profile, dispatch_id=dispatch_id, retry_count=retry_count,
        started_at=started_at, capture_method=capture_method, tool_version=tool_version,
    )
    error: Session3Error | None = None
    preflight = {}
    restored = False
    driver = None
    try:
        endpoint, targets = probe.inspect(profile)
        with driver_factory(profile, pin) as driver:
            try:
                initial = driver.inspect()
                preflight = verify_preflight(
                    profile, pin, endpoint, targets, initial, authority,
                    observed_at=now(), destination_writable=True,
                )
                for timeframe in profile.required_timeframes:
                    state = driver.switch_and_wait(timeframe)
                    captured_at = now().astimezone(timezone.utc)
                    verification = verify_chart_state(
                        profile, authority, state, expected_timeframe=timeframe,
                        observed_at=captured_at,
                    )
                    data = driver.screenshot()
                    store.add_artifact(
                        attempt_dir, manifest, timeframe=timeframe,
                        observed_timeframe=state.timeframe, captured_at=captured_at,
                        data=data, mime_type="image/png", capture_method=capture_method,
                        chart_bar_at=state.last_bar_at, verification=verification,
                    )
                authority.ensure_unexpired(now())
            except Session3Error as exc:
                error = exc
            except Exception as exc:
                error = Session3Error("MCP_UNAVAILABLE", f"{type(exc).__name__}: {exc}")
            finally:
                try:
                    restored_state = driver.switch_and_wait(profile.base_timeframe)
                    verify_chart_state(
                        profile, authority, restored_state,
                        expected_timeframe=profile.base_timeframe, observed_at=now(),
                    )
                    restored = True
                except Exception:
                    restored = False
    except Session3Error as exc:
        error = exc
    except Exception as exc:
        error = Session3Error("MCP_UNAVAILABLE", f"{type(exc).__name__}: {exc}")
    finished_at = now().astimezone(timezone.utc)
    if error is None and not restored:
        error = Session3Error("WRONG_TIMEFRAME", "1m restoration could not be verified")
    manifest_path = store.finalize(
        attempt_dir, manifest, finished_at=finished_at, preflight=preflight,
        restored_base_timeframe=restored, failure=error,
    )
    if error is not None:
        raise Session3Error(error.code, error.detail, attempt_id=manifest["capture_attempt_id"])
    return manifest, str(manifest_path)
