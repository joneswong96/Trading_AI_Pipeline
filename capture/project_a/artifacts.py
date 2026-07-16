"""Immutable artifact storage, SHA-256 manifests and integrity replay."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path, PurePosixPath

from contracts import canonical_json

from .errors import Session3Error
from .input_boundary import AnalysisAuthority, utc_z
from .profile import CaptureProfile


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise Session3Error("PATH_TRAVERSAL", f"unsafe artifact path {value!r}")
    return path


def write_bytes_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        existing = path.read_bytes()
        if existing != data:
            raise Session3Error("ARTIFACT_WRITE_FAILURE", f"immutable path already has different bytes: {path.name}")


def write_json_immutable(path: Path, document: dict) -> None:
    write_bytes_immutable(path, (canonical_json(document) + "\n").encode("utf-8"))


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def writable(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".write_probe"
            with probe.open("xb"):
                pass
            probe.unlink()
            return True
        except OSError:
            return False

    def begin(self, authority: AnalysisAuthority, profile: CaptureProfile, *,
              dispatch_id: str, retry_count: int, started_at: datetime,
              capture_method: str, tool_version: str) -> tuple[Path, dict]:
        seed = canonical_json({
            "dispatch_id": dispatch_id,
            "event_id": authority.event_id,
            "retry_count": retry_count,
            "started_at": utc_z(started_at),
            "profile": profile.identity_dict(),
        }).encode("utf-8")
        attempt_id = "attempt_" + sha256_bytes(seed)[:32]
        request_id = "req_" + sha256_bytes(b"request\0" + seed)[:40]
        attempt_dir = (self.root / attempt_id).resolve()
        if attempt_dir.parent != self.root:
            raise Session3Error("PATH_TRAVERSAL", "attempt directory escaped artifact root")
        attempt_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_version": "1.0",
            "status": "IN_PROGRESS",
            "capture_attempt_id": attempt_id,
            "dispatch_id": dispatch_id[:128],
            "retry_count": retry_count,
            "request_id": request_id,
            "setup_id": authority.setup_id,
            "source_event_id": authority.event_id,
            "source_event_ids": list((authority.analysis or {}).get("source_event_ids") or [authority.event_id]),
            "correlation_id": authority.correlation_id,
            "causation_id": authority.event_id,
            "source_causation_id": authority.event.get("causation_id"),
            "schema_versions": {"event": "0.2", "analysis_request": "1.0", "manifest": "1.0"},
            "symbol": profile.symbol,
            "broker_feed": profile.broker_feed,
            "base_timeframe": profile.base_timeframe,
            "required_timeframes": list(profile.required_timeframes),
            "source_event_timestamp": authority.event["occurred_at"],
            "source_bar_timestamp": utc_z(authority.bar_time),
            "source_expires_at": utc_z(authority.expires_at) if authority.expires_at else None,
            "started_at": utc_z(started_at),
            "finished_at": None,
            "capture_method": capture_method,
            "tool_version": tool_version,
            "port": profile.port,
            "artifacts": [],
            "preflight": {},
            "restored_base_timeframe": False,
            "failure": None,
        }
        return attempt_dir, manifest

    def add_artifact(self, attempt_dir: Path, manifest: dict, *, timeframe: str,
                     observed_timeframe: str, captured_at: datetime, data: bytes,
                     mime_type: str, capture_method: str, chart_bar_at: datetime,
                     verification: dict) -> dict:
        if timeframe not in manifest["required_timeframes"]:
            raise Session3Error("MISSING_TIMEFRAME", f"unexpected timeframe {timeframe}")
        digest = sha256_bytes(data)
        suffix = ".png" if mime_type == "image/png" else ".bin"
        relative = f"artifacts/{timeframe}_{digest}{suffix}"
        _safe_relative(relative)
        path = (attempt_dir / Path(*PurePosixPath(relative).parts)).resolve()
        if attempt_dir not in path.parents:
            raise Session3Error("PATH_TRAVERSAL", "artifact path escaped attempt directory")
        write_bytes_immutable(path, data)
        record = {
            "requested_timeframe": timeframe,
            "observed_timeframe": observed_timeframe,
            "symbol": manifest["symbol"],
            "broker_feed": manifest["broker_feed"],
            "capture_timestamp": utc_z(captured_at),
            "source_event_timestamp": manifest["source_event_timestamp"],
            "chart_bar_timestamp": utc_z(chart_bar_at),
            "artifact_path": relative,
            "mime_type": mime_type,
            "byte_size": len(data),
            "sha256": digest,
            "capture_method": capture_method,
            "verification": verification,
        }
        manifest["artifacts"].append(record)
        return record

    def finalize(self, attempt_dir: Path, manifest: dict, *, finished_at: datetime,
                 preflight: dict, restored_base_timeframe: bool,
                 failure: Session3Error | None = None) -> Path:
        manifest["finished_at"] = utc_z(finished_at)
        manifest["preflight"] = preflight
        manifest["restored_base_timeframe"] = restored_base_timeframe
        manifest["failure"] = failure.as_dict() if failure else None
        required = set(manifest["required_timeframes"])
        observed = {record["requested_timeframe"] for record in manifest["artifacts"]}
        complete = failure is None and required == observed and restored_base_timeframe
        manifest["status"] = "COMPLETE" if complete else "FAILED"
        path = attempt_dir / "manifest.json"
        write_json_immutable(path, manifest)
        return path


def verify_manifest(manifest_path: str | Path) -> dict:
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Session3Error("ARTIFACT_MISSING", f"manifest missing: {manifest_path}") from exc
    root = manifest_path.parent
    for record in manifest.get("artifacts", []):
        relative = _safe_relative(record["artifact_path"])
        artifact = (root / Path(*relative.parts)).resolve()
        if root not in artifact.parents:
            raise Session3Error("PATH_TRAVERSAL", f"artifact escaped bundle: {relative}")
        if not artifact.is_file():
            raise Session3Error("ARTIFACT_MISSING", f"missing artifact: {relative}")
        data = artifact.read_bytes()
        if len(data) != record["byte_size"] or sha256_bytes(data) != record["sha256"]:
            raise Session3Error("ARTIFACT_HASH_MISMATCH", f"integrity failure: {relative}")
    return manifest
