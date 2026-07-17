"""Audited local operations for the Session 5 outbox. No external adapter is invoked."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import OutputConfig
from .store import OutboxStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("storage/project_a_outputs.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    recover = sub.add_parser("recover-abandoned")
    recover.add_argument("--claim-timeout", type=int, default=60)
    reset = sub.add_parser("reset")
    reset.add_argument("delivery_id")
    reset.add_argument("--actor", required=True)
    reset.add_argument("--reason", required=True)
    outcome = sub.add_parser("outcome")
    outcome.add_argument("payload", type=Path)
    validate = sub.add_parser("validate-config")
    validate.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        if args.command == "validate-config":
            config = OutputConfig.from_yaml(args.path)
            payload = {"ok": True, "shadow": config.shadow, "dry_run": config.dry_run,
                       "enabled_renderers": list(config.enabled_renderers)}
        else:
            store = OutboxStore(args.db)
            if args.command == "status":
                payload = {"ok": True, "deliveries": store.all_deliveries(),
                           "integrity_check": store.integrity_check()}
            elif args.command == "recover-abandoned":
                payload = {"ok": True, "recovered": store.recover_abandoned(
                    now, args.claim_timeout)}
            elif args.command == "reset":
                store.manual_reset(args.delivery_id, actor=args.actor,
                                   reason=args.reason, now=now)
                payload = {"ok": True, "delivery_id": args.delivery_id,
                           "operation": "MANUAL_RESET"}
            else:
                document = json.loads(args.payload.read_text(encoding="utf-8"))
                payload = {"ok": True, "created": store.append_outcome(document),
                           "event_id": document["event_id"]}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
