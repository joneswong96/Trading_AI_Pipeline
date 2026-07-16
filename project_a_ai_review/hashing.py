"""Canonical hashes used for integrity, identity, and audit attribution."""
from __future__ import annotations

import hashlib
from pathlib import Path

from contracts import canonical_json


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_hash(manifest: dict) -> str:
    return sha256_text(canonical_json(manifest))


def bundle_hash(request: dict, artifact_manifest_hash: str) -> str:
    return sha256_text(canonical_json(request) + "\n" + artifact_manifest_hash)


def request_storage_key(request_id: str) -> str:
    return sha256_text(request_id)[:40]
