"""Deterministic Project A replay; dry-run is the default and commits require --commit."""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .config import ProjectAConfig
from .database import ProjectADatabase
from .service import ProjectAIngestService, iso, parse_utc, utc_now


def _copy_database(source: Path, target: Path) -> None:
    if not source.exists():
        return
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _stored_items(db: ProjectADatabase, selector: str, value: str | None,
                  limit: int) -> list[tuple[bytes, datetime, str]]:
    with closing(db.connect()) as conn:
        if selector == "receipt":
            rows = conn.execute(
                "SELECT raw_body,received_at,ingest_id FROM project_a_raw_receipts WHERE ingest_id=?",
                (value,),
            ).fetchall()
        elif selector == "event":
            rows = conn.execute(
                "SELECT r.raw_body,r.received_at,r.ingest_id FROM project_a_canonical_events e "
                "JOIN project_a_raw_receipts r ON r.ingest_id=e.ingest_id WHERE e.event_id=?",
                (value,),
            ).fetchall()
        elif selector == "setup":
            rows = conn.execute(
                "SELECT r.raw_body,r.received_at,r.ingest_id FROM project_a_canonical_events e "
                "JOIN project_a_raw_receipts r ON r.ingest_id=e.ingest_id WHERE e.setup_id=? "
                "ORDER BY e.occurred_at,e.event_id LIMIT ?", (value, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT raw_body,received_at,ingest_id FROM project_a_raw_receipts "
                "ORDER BY received_at,ingest_id LIMIT ?", (limit,),
            ).fetchall()
    return [(bytes(row["raw_body"]), parse_utc(row["received_at"]), row["ingest_id"])
            for row in rows]


def _fixture_item(path: Path, case: str | None) -> tuple[bytes, datetime, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if case:
        document = document[case]
    if isinstance(document, dict) and set(document) == {"expected", "payload"}:
        document = document["payload"]
    if not isinstance(document, dict) or "schema_version" not in document:
        raise ValueError("fixture must resolve to one Event 0.2 object")
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    replay_at = parse_utc(document.get("received_at") or document["occurred_at"])
    return raw, replay_at, str(path)


def run(config: ProjectAConfig, *, selector: str, value: str | None = None,
        fixture: Path | None = None, case: str | None = None, limit: int = 100,
        commit: bool = False) -> dict:
    config.assert_safe()
    source_db = ProjectADatabase(config.database_path)
    if fixture:
        items = [_fixture_item(fixture, case)]
    else:
        source_db.assert_ready()
        items = _stored_items(source_db, selector, value, limit)
    if not items:
        raise ValueError("replay selector matched no receipts")

    operation_id = "replay_" + uuid.uuid4().hex
    results = []
    if commit:
        target_config = config
        cleanup = None
        with source_db.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO project_a_replay_operations(replay_operation_id,requested_at,"
                "selector_type,selector_value,mode,result_code,ingest_id) VALUES(?,?,?,?,?,'STARTED',NULL)",
                (operation_id, iso(utc_now()), selector, value or str(fixture), "COMMIT"),
            )
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="project-a-replay-")
        target = Path(cleanup.name) / "dry-run.db"
        _copy_database(config.database_path, target)
        target_config = ProjectAConfig(**{**config.__dict__, "database_path": target})

    try:
        for raw, replay_at, source in items:
            service = ProjectAIngestService(target_config, clock=lambda at=replay_at: at)
            result = service.receive(
                raw, source_metadata={"transport": "REPLAY", "replay_source": source},
                replay_operation_id=operation_id if commit else None,
            )
            results.append(result.response())
        if commit:
            with source_db.transaction(immediate=True) as conn:
                conn.execute(
                    "UPDATE project_a_replay_operations SET result_code='COMPLETED',ingest_id=? "
                    "WHERE replay_operation_id=?",
                    (results[-1]["ingest_id"], operation_id),
                )
        return {
            "ok": True, "mode": "COMMIT" if commit else "DRY_RUN",
            "replay_operation_id": operation_id if commit else None,
            "source_count": len(items), "results": results,
            "committed_effects": commit,
        }
    finally:
        if cleanup:
            cleanup.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Project A SQLite path")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--receipt")
    source.add_argument("--event")
    source.add_argument("--setup")
    source.add_argument("--fixture", type=Path)
    source.add_argument("--batch", action="store_true")
    parser.add_argument("--case", help="case key when fixture is a case map")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--commit", action="store_true",
                        help="commit idempotent replay (default is isolated dry-run)")
    args = parser.parse_args(argv)
    config = ProjectAConfig.from_env()
    if args.db:
        config = ProjectAConfig(**{**config.__dict__, "database_path": args.db})
    selector, value = (
        ("receipt", args.receipt) if args.receipt else
        ("event", args.event) if args.event else
        ("setup", args.setup) if args.setup else
        ("fixture", str(args.fixture)) if args.fixture else ("batch", None)
    )
    try:
        result = run(config, selector=selector, value=value, fixture=args.fixture,
                     case=args.case, limit=max(1, min(args.limit, 1000)), commit=args.commit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:500]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
