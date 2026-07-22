"""Local, secret-free operator inspection for Project A analysis."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from capture.base import ROOT

from .provider import request_manifest_sha256
from .store import AnalysisStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("PROJECT_A_DB", str(ROOT / "storage" / "project_a.db")))
    commands = parser.add_subparsers(dest="command", required=True)
    jobs = commands.add_parser("jobs")
    jobs.add_argument("--status", choices=(
        "PENDING_CAPTURE", "CAPTURED", "CLAIMED", "COMPLETED", "TECHNICAL_FAILURE"))
    commands.add_parser("active-story")
    commands.add_parser("health")
    audit = commands.add_parser("audit")
    audit.add_argument("--limit", type=int, default=50)
    request = commands.add_parser("request-manifest")
    request.add_argument("--job-id", required=True)
    decision = commands.add_parser("decision")
    decision.add_argument("--story-id", required=True)
    decision.add_argument("--value", required=True, choices=("ENTERED", "SKIPPED"))
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    store = AnalysisStore(args.db)
    if args.command == "jobs":
        value = store.inspect_jobs(args.status)
    elif args.command == "active-story":
        value = store.active_story()
    elif args.command == "health":
        value = store.health()
    elif args.command == "audit":
        value = store.audit(limit=args.limit)
    elif args.command == "request-manifest":
        model = os.getenv("PROJECT_A_OPENAI_MODEL", "").strip()
        if not model:
            raise SystemExit("PROJECT_A_OPENAI_MODEL is required")
        job, evidence = store.load_job_bundle(args.job_id)
        value = {
            "job_id": args.job_id,
            "analysis_id": job["analysis_id"],
            "model": model,
            "request_manifest_sha256": request_manifest_sha256(job, evidence, model),
            "stage": job["stage"],
            "e1_count": job["e1_count"],
            "image_count": len(evidence.images),
        }
    else:
        store.close_story(
            args.story_id, decision=args.value, at=datetime.now(timezone.utc), actor="JONES"
        )
        value = {"ok": True, "story_id": args.story_id, "decision": args.value}
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
