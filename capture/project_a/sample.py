"""Build the deterministic Session 3-owned synthetic Canonical V1 bundle."""
from __future__ import annotations

import base64
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from contracts import InMemoryDedupeAuthority, canonical_json_bytes, process_wire_event_v1_receipt
from contracts._trusted_ingress import issue_replay_receipt_context

from .artifacts import ArtifactStore
from .compiler import compile_analysis_request
from .errors import Session3Error
from .input_boundary import bind_disabled_analysis_adapter, parse_utc, validate_analysis_ready
from .profile import CaptureProfile
from .replay import write_bundle

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _recorded_canonical(wire_vectors: str | Path, adapter_fixture: dict) -> dict:
    vectors = json.loads(Path(wire_vectors).read_text(encoding="utf-8"))
    wire = deepcopy(vectors["documents"]["rejection_ready"])
    analysis = adapter_fixture["payload"]["analysis"]
    wire["extensions"]["observed_spread_points"] = analysis["spread_points"]
    raw = canonical_json_bytes(wire)
    context = issue_replay_receipt_context(
        raw,
        receipt_id="rcpt_session3_sample_0001",
        received_at="2026-07-16T01:01:01.250Z",
        transport_identity="recorded_session3_sample_0001",
        source_adapter_identity="session3_fixture_builder_v1",
        immutable_raw_reference="recorded_session3_wire_0001",
        canonicalized_at="2026-07-16T01:01:01.300Z",
        replay_clock="2026-07-16T01:01:01.300Z",
    )
    result = process_wire_event_v1_receipt(raw, context, InMemoryDedupeAuthority())
    if result.processing_status != "ACCEPTED" or result.canonical_document is None:
        raise Session3Error("SOURCE_INVALID", f"recorded Canonical V1 build failed: {result.reason_code}")
    return result.canonical_document.document


def build_sample(*, wire_vectors: str | Path, adapter_path: str | Path,
                 profile_path: str | Path, output_root: str | Path,
                 started_at: datetime, finished_at: datetime,
                 created_at: datetime) -> Path:
    adapter_fixture = json.loads(Path(adapter_path).read_text(encoding="utf-8"))
    canonical_event = _recorded_canonical(wire_vectors, adapter_fixture)
    analysis_adapter = bind_disabled_analysis_adapter(canonical_event, adapter_fixture)
    authority = validate_analysis_ready(
        canonical_event,
        analysis_adapter,
        require_compiler_fields=True,
    )
    authority.ensure_capture_chronology(started_at)
    profile = CaptureProfile.load(profile_path)
    store = ArtifactStore(output_root)
    attempt_dir, manifest = store.begin(
        authority,
        profile,
        dispatch_id="dispatch_session3_sample_v1_0001",
        retry_count=0,
        started_at=started_at,
        capture_method="FIXTURE",
        tool_version="session3-synthetic-sample/1.1.0",
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
    bar_time = parse_utc(
        adapter_fixture["payload"]["analysis"]["bar_time"],
        "payload.analysis.bar_time",
    )
    for timeframe in profile.required_timeframes:
        store.add_artifact(
            attempt_dir,
            manifest,
            timeframe=timeframe,
            observed_timeframe=timeframe,
            captured_at=finished_at,
            data=_ONE_PIXEL_PNG,
            mime_type="image/png",
            capture_method="FIXTURE",
            chart_bar_at=bar_time,
            verification=verification,
        )
    store.finalize(
        attempt_dir,
        manifest,
        finished_at=finished_at,
        preflight={
            "synthetic_fixture": True,
            "real_endpoint_inspected": False,
            "real_browser_used": False,
            "runtime_compatibility_claim": "NONE",
            "target_id": "SYNTHETIC_FIXTURE_NO_REAL_TARGET",
            "destination_writable": True,
        },
        restored_base_timeframe=True,
    )
    request = compile_analysis_request(
        canonical_event,
        analysis_adapter,
        manifest,
        profile,
        created_at=created_at,
    )
    write_bundle(
        attempt_dir,
        canonical_event=canonical_event,
        analysis_adapter=analysis_adapter,
        manifest=manifest,
        request=request,
        release_at=created_at,
    )
    return attempt_dir
