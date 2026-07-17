"""Operator CLI for Project A capture, compilation and offline replay."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from contracts import canonical_json

from .artifacts import ArtifactStore, verify_manifest
from .cdp import PlaywrightPinnedDriver, WindowsCdpProbe
from .compiler import compile_analysis_request
from .coordinator import capture_event
from .errors import Session3Error
from .input_boundary import parse_utc
from .preflight import select_pinned_target, verify_endpoint, verify_preflight
from .profile import CaptureProfile, TabPin
from .replay import replay_bundle, write_bundle
from .sample import build_sample


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_state(path: Path, document: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".tmp.{os.getpid()}")
    temp.write_text(canonical_json(document) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="inspect only the exact port 4999 endpoint")
    inspect.add_argument("--profile", required=True)
    pin = commands.add_parser("pin-tab", help="write an explicit target-ID pin")
    pin.add_argument("--profile", required=True)
    pin.add_argument("--target-id", required=True)
    pin.add_argument("--output", required=True)
    preflight = commands.add_parser("preflight", help="run every live identity gate without capture")
    for item in (preflight,):
        item.add_argument("--profile", required=True)
        item.add_argument("--pin", required=True)
        item.add_argument("--canonical-event", required=True)
        item.add_argument("--analysis-adapter", required=True)
        item.add_argument("--artifact-root", required=True)
    capture = commands.add_parser("capture", help="capture and compile one Analysis Ready event")
    capture.add_argument("--profile", required=True)
    capture.add_argument("--pin", required=True)
    capture.add_argument("--canonical-event", required=True)
    capture.add_argument("--analysis-adapter", required=True)
    capture.add_argument("--artifact-root", required=True)
    capture.add_argument("--dispatch-id", required=True)
    capture.add_argument("--retry-count", type=int, default=0)
    compile_cmd = commands.add_parser("compile", help="compile in place from frozen event and manifest")
    compile_cmd.add_argument("--profile", required=True)
    compile_cmd.add_argument("--canonical-event", required=True)
    compile_cmd.add_argument("--analysis-adapter", required=True)
    compile_cmd.add_argument("--manifest", required=True)
    compile_cmd.add_argument("--created-at", required=True)
    replay = commands.add_parser("replay", help="verify artifacts and deterministically rebuild offline")
    replay.add_argument("--profile", required=True)
    replay.add_argument("--bundle", required=True)
    replay.add_argument("--at")
    verify = commands.add_parser("verify", help="verify manifest paths, sizes and SHA-256 values")
    verify.add_argument("--manifest", required=True)
    sample = commands.add_parser("build-sample", help="build the deterministic synthetic Canonical V1 bundle")
    sample.add_argument("--wire-vectors", required=True)
    sample.add_argument("--adapter", required=True)
    sample.add_argument("--profile", required=True)
    sample.add_argument("--output-root", required=True)
    sample.add_argument("--started-at", required=True)
    sample.add_argument("--finished-at", required=True)
    sample.add_argument("--created-at", required=True)
    return parser


def run(argv=None) -> dict:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        manifest = verify_manifest(args.manifest)
        return {"ok": True, "status": manifest["status"], "artifact_count": len(manifest["artifacts"])}
    if args.command == "build-sample":
        root = build_sample(
            wire_vectors=args.wire_vectors, adapter_path=args.adapter,
            profile_path=args.profile, output_root=args.output_root,
            started_at=parse_utc(args.started_at, "started_at"),
            finished_at=parse_utc(args.finished_at, "finished_at"),
            created_at=parse_utc(args.created_at, "created_at"),
        )
        return {"ok": True, "bundle": str(root)}
    profile = CaptureProfile.load(args.profile)
    if args.command == "replay":
        at = parse_utc(args.at, "at") if args.at else None
        return replay_bundle(args.bundle, profile, replay_at=at)
    if args.command == "compile":
        canonical_event = _load_json(args.canonical_event)
        analysis_adapter = _load_json(args.analysis_adapter)
        manifest = verify_manifest(args.manifest)
        created = parse_utc(args.created_at, "created_at")
        request = compile_analysis_request(
            canonical_event,
            analysis_adapter,
            manifest,
            profile,
            created_at=created,
        )
        write_bundle(
            Path(args.manifest).resolve().parent,
            canonical_event=canonical_event,
            analysis_adapter=analysis_adapter,
            manifest=manifest,
            request=request,
            release_at=created,
        )
        return {"ok": True, "request_id": request["request_id"], "bundle": str(Path(args.manifest).resolve().parent)}
    probe = WindowsCdpProbe()
    endpoint, targets = probe.inspect(profile)
    verify_endpoint(profile, endpoint)
    if args.command == "inspect":
        return {
            "ok": True,
            "endpoint": {"host": endpoint.host, "port": endpoint.port,
                         "addresses": endpoint.local_addresses, "pid": endpoint.pid,
                         "process_name": endpoint.process_name, "browser": endpoint.browser,
                         "protocol_version": endpoint.protocol_version},
            "targets": [target.__dict__ for target in targets],
        }
    if args.command == "pin-tab":
        candidate = TabPin(args.target_id, profile.expected_chart_url, profile.expected_layout_id)
        selected = select_pinned_target(profile, candidate, targets)
        _atomic_state(Path(args.output), candidate.as_dict())
        return {"ok": True, "target_id": selected.target_id, "pin": str(Path(args.output).resolve())}
    canonical_event = _load_json(args.canonical_event)
    analysis_adapter = _load_json(args.analysis_adapter)
    pin = TabPin.load(args.pin)
    store = ArtifactStore(args.artifact_root)
    if args.command == "preflight":
        from .input_boundary import validate_analysis_ready
        authority = validate_analysis_ready(
            canonical_event,
            analysis_adapter,
            require_compiler_fields=True,
        )
        with PlaywrightPinnedDriver(profile) as driver:
            result = verify_preflight(profile, pin, endpoint, targets, driver.inspect(), authority,
                                      observed_at=_now(), destination_writable=store.writable())
        return {"ok": True, "preflight": result}
    manifest, path = capture_event(
        canonical_event, analysis_adapter, profile, pin, store, probe, PlaywrightPinnedDriver,
        dispatch_id=args.dispatch_id, retry_count=args.retry_count, now=_now,
    )
    created = parse_utc(manifest["finished_at"], "finished_at")
    request = compile_analysis_request(
        canonical_event,
        analysis_adapter,
        manifest,
        profile,
        created_at=created,
    )
    write_bundle(
        Path(path).parent,
        canonical_event=canonical_event,
        analysis_adapter=analysis_adapter,
        manifest=manifest,
        request=request,
        release_at=created,
    )
    return {"ok": True, "request_id": request["request_id"], "bundle": str(Path(path).parent)}


def main(argv=None) -> int:
    try:
        print(json.dumps(run(argv), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (Session3Error, OSError, ValueError, KeyError, RuntimeError) as exc:
        payload = exc.as_dict() if isinstance(exc, Session3Error) else {
            "code": "MCP_UNAVAILABLE", "detail": str(exc)[:500], "retryable": False,
        }
        print(json.dumps({"ok": False, "error": payload}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
