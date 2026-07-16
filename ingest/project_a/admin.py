"""Local Project A database administration and inspection commands."""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import ProjectAConfig
from .service import ProjectAIngestService

_INSPECT = {
    "receipts": "SELECT ingest_id,body_hash,body_bytes,raw_complete,received_at FROM project_a_raw_receipts ORDER BY received_at DESC LIMIT ?",
    "state": "SELECT * FROM project_a_setup_state ORDER BY updated_at DESC LIMIT ?",
    "outbox": "SELECT outbox_id,dispatch_key,event_id,setup_id,status,attempt_count,available_at,last_error FROM project_a_outbox ORDER BY created_at DESC LIMIT ?",
    "dead-letters": "SELECT * FROM project_a_dead_letters ORDER BY latest_seen_at DESC LIMIT ?",
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("health")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("target", choices=sorted(_INSPECT))
    inspect.add_argument("--limit", type=int, default=20)
    retry = sub.add_parser("retry-outbox")
    retry.add_argument("outbox_id")
    sub.add_parser("recover-claims")
    args = parser.parse_args(argv)
    config = ProjectAConfig.from_env()
    if args.db:
        config = ProjectAConfig(**{**config.__dict__, "database_path": args.db})
    try:
        service = ProjectAIngestService(config)
        if args.command == "init":
            result = {"ok": True, "database": str(config.database_path), "schema_version": 1}
        elif args.command == "health":
            result = service.health()
        elif args.command == "inspect":
            with closing(service.db.connect()) as conn:
                rows = conn.execute(_INSPECT[args.target],
                                    (max(1, min(args.limit, 1000)),)).fetchall()
            result = {"ok": True, "target": args.target, "rows": [dict(row) for row in rows]}
        elif args.command == "retry-outbox":
            result = {"ok": service.retry_outbox(args.outbox_id), "outbox_id": args.outbox_id}
        else:
            result = {"ok": True, "recovered": service.recover_abandoned_claims()}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("ok") else 2
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:500]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
