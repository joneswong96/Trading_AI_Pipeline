"""Durable per-request locking and hash-chained shadow audit records."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from contracts import canonical_json

from .errors import FailureCode, InputRejected, TechnicalFailure
from .hashing import request_storage_key, sha256_text


class ShadowAuditStore:
    def __init__(self, root: Path, *, lock_timeout_seconds: float = 10.0):
        self.root = Path(root)
        self.lock_timeout_seconds = lock_timeout_seconds
        self._secure_directory(self.root)

    @staticmethod
    def _secure_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _secure_file(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def request_dir(self, request_id: str) -> Path:
        directory = self.root / "requests" / request_storage_key(request_id)
        self._secure_directory(directory)
        return directory

    @contextmanager
    def lock(self, request_id: str) -> Iterator[Path]:
        directory = self.request_dir(request_id)
        lock_path = directory / ".lock"
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
                os.fsync(descriptor)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TechnicalFailure(
                        FailureCode.CONCURRENT_IN_FLIGHT,
                        "another review holds the durable request lock",
                        True,
                    )
                time.sleep(0.05)
        try:
            yield directory
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _atomic_create(path: Path, document: dict) -> None:
        data = (canonical_json(document) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def ensure_request_metadata(
        self,
        request_id: str,
        *,
        fingerprint: str,
        bundle_hash: str,
        prompt_hash: str,
        model_key: str,
    ) -> None:
        path = self.request_dir(request_id) / "request.json"
        expected = {
            "request_id": request_id,
            "fingerprint": fingerprint,
            "bundle_hash": bundle_hash,
            "prompt_hash": prompt_hash,
            "model_key": model_key,
        }
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != expected:
                raise InputRejected(
                    FailureCode.DUPLICATE_CONFLICT,
                    "same request_id has a conflicting bundle/prompt/model fingerprint",
                )
            return
        self._atomic_create(path, expected)

    def append_attempt(self, request_id: str, record: dict) -> str:
        path = self.request_dir(request_id) / "attempts.jsonl"
        previous = "0" * 64
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    previous = json.loads(line)["record_hash"]
        envelope = {"previous_hash": previous, "record": record}
        record_hash = sha256_text(canonical_json(envelope))
        persisted = {**envelope, "record_hash": record_hash}
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(persisted) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._secure_file(path)
        return record_hash

    def last_attempt_id(self, request_id: str) -> str | None:
        path = self.request_dir(request_id) / "attempts.jsonl"
        if not path.exists():
            return None
        last: dict | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = json.loads(line)
        return last["record"].get("attempt_id") if last else None

    def attempt_count(self, request_id: str) -> int:
        path = self.request_dir(request_id) / "attempts.jsonl"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def store_raw_response(self, request_id: str, attempt_id: str, raw: str) -> str:
        directory = self.request_dir(request_id) / "raw"
        self._secure_directory(directory)
        path = directory / f"{attempt_id}.txt"
        data = raw.encode("utf-8")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return sha256_text(raw)

    def save_completed(self, request_id: str, result: dict) -> None:
        path = self.request_dir(request_id) / "completed.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != result:
                raise TechnicalFailure(
                    FailureCode.AUDIT_PERSISTENCE_FAILURE,
                    "completed verdict is immutable",
                )
            return
        self._atomic_create(path, result)

    def load_completed(self, request_id: str) -> dict | None:
        path = self.request_dir(request_id) / "completed.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def verify_chain(self, request_id: str) -> bool:
        path = self.request_dir(request_id) / "attempts.jsonl"
        previous = "0" * 64
        if not path.exists():
            return True
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["previous_hash"] != previous:
                return False
            envelope = {"previous_hash": previous, "record": item["record"]}
            if sha256_text(canonical_json(envelope)) != item["record_hash"]:
                return False
            previous = item["record_hash"]
        return True
