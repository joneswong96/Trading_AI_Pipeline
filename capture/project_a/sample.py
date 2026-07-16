"""Build the deterministic Session 3-owned fake candidate bundle."""
from __future__ import annotations

import base64
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .artifacts import ArtifactStore
from .compiler import compile_analysis_request
from .input_boundary import parse_utc, validate_analysis_ready
from .profile import CaptureProfile
from .replay import write_bundle

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def build_sample(*, frozen_cases: str | Path, extension_path: str | Path,
                 profile_path: str | Path, output_root: str | Path,
                 started_at: datetime, finished_at: datetime,
                 created_at: datetime) -> Path:
    cases = json.loads(Path(frozen_cases).read_text(encoding="utf-8"))
    event = deepcopy(cases["accepted_alert"]["payload"])
    extension = json.loads(Path(extension_path).read_text(encoding="utf-8"))
    event["payload"]["analysis"] = extension
    authority = validate_analysis_ready(event, require_compiler_fields=True)
    authority.ensure_unexpired(started_at)
    profile = CaptureProfile.load(profile_path)
    store = ArtifactStore(output_root)
    attempt_dir, manifest = store.begin(
        authority, profile, dispatch_id="dispatch_session3_sample_0001", retry_count=0,
        started_at=started_at, capture_method="FIXTURE", tool_version="session3-sample/1.0.0",
    )
    verification = {
        "page_ready": True,
        "authenticated": True,
        "tab_url_verified": True,
        "layout_verified": True,
        "symbol_verified": True,
        "feed_verified": True,
        "timeframe_verified": True,
        "required_timeframes_available": True,
        "streaming_verified": True,
        "source_bar_covered": True,
    }
    bar_time = parse_utc(extension["bar_time"], "bar_time")
    for timeframe in profile.required_timeframes:
        store.add_artifact(
            attempt_dir, manifest, timeframe=timeframe, observed_timeframe=timeframe,
            captured_at=finished_at, data=_ONE_PIXEL_PNG, mime_type="image/png",
            capture_method="FIXTURE", chart_bar_at=bar_time, verification=verification,
        )
    store.finalize(
        attempt_dir, manifest, finished_at=finished_at,
        preflight={
            "endpoint_verified": True,
            "local_only_verified": True,
            "process_verified": True,
            "target_id": "FIXTURE_TARGET_NOT_LIVE",
            "destination_writable": True,
            **verification,
        },
        restored_base_timeframe=True,
    )
    request = compile_analysis_request(event, manifest, profile, created_at=created_at)
    write_bundle(attempt_dir, event=event, manifest=manifest, request=request, release_at=created_at)
    return attempt_dir
