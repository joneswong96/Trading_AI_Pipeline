"""Validate Session 1 candidate payloads against frozen Event 0.2.

This is a read-only Pine artifact utility. It does not ingest, persist, route,
or send events.
"""
from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from contracts import EVENT_SCHEMA_V0_2, canonical_json, validate_contract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOADS = (
    ROOT / "docs" / "project_a" / "session_1" / "artifacts" / "candidate_payloads.json"
)


def validate_file(path: Path) -> dict:
    documents = json.loads(path.read_text(encoding="utf-8"))
    outcomes = []
    for name, document in documents.items():
        validate_contract(EVENT_SCHEMA_V0_2, document)
        actual_hash = "sha256:" + sha256(
            canonical_json(document["payload"]).encode("utf-8")
        ).hexdigest()
        if document["source"]["payload_hash"] != actual_hash:
            raise ValueError(f"{name}: source.payload_hash does not match canonical payload")
        outcomes.append(
            {
                "name": name,
                "event_class": document["event_class"],
                "event_type": document["event_type"],
                "setup_id": document["setup_id"],
                "status": "PASS",
            }
        )
    return {"contract": EVENT_SCHEMA_V0_2, "count": len(outcomes), "results": outcomes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payloads", type=Path, default=DEFAULT_PAYLOADS)
    args = parser.parse_args(argv)
    print(json.dumps(validate_file(args.payloads), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
