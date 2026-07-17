"""Validate corrected Session 1 engineering fixtures as Wire Event V1.

This is a read-only Pine artifact utility. It does not ingest, persist, route,
or send events.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from contracts import PROJECT_A_WIRE_EVENT_V1, validate_wire_event_v1_shape

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOADS = (
    ROOT / "docs" / "project_a" / "session_1" / "artifacts" / "candidate_payloads.json"
)


def validate_file(path: Path) -> dict:
    documents = json.loads(path.read_text(encoding="utf-8"))
    outcomes = []
    for name, document in documents.items():
        validate_wire_event_v1_shape(document)
        outcomes.append(
            {
                "name": name,
                "event_class": document["event_class"],
                "event_type": document["event_type"],
                "setup_origin": document["setup_origin"],
                "status": "PASS",
            }
        )
    return {
        "contract": PROJECT_A_WIRE_EVENT_V1,
        "count": len(outcomes),
        "results": outcomes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payloads", type=Path, default=DEFAULT_PAYLOADS)
    args = parser.parse_args(argv)
    print(json.dumps(validate_file(args.payloads), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
