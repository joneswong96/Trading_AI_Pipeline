"""Safe recorded Thesis/outbox replay. Fake transports and no external side effects only."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from .compiler import InputAttestation, ThesisCompiler
from .config import fake_output_config
from .dispatcher import Dispatcher
from .fakes import (
    FakeMT5Transport,
    FakeNotionTransport,
    FakeTelegramTransport,
    FakeTradingViewTransport,
)
from .models import parse_utc
from .renderers import MT5DemoRenderer, NotionRenderer, TelegramRenderer, TradingViewRenderer
from .store import OutboxStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "project_a"


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_fake_runtime(db_path: str | Path):
    config = fake_output_config()
    store = OutboxStore(db_path)
    transports = {
        "tradingview": FakeTradingViewTransport(),
        "telegram": FakeTelegramTransport(),
        "notion": FakeNotionTransport(),
        "mt5": FakeMT5Transport(),
    }
    notion = NotionRenderer(config, transports["notion"], store)
    renderers = [
        TradingViewRenderer(config, transports["tradingview"]),
        TelegramRenderer(config, transports["telegram"]),
        notion,
        MT5DemoRenderer(config, transports["mt5"]),
    ]
    return config, store, transports, Dispatcher(store, config, renderers), notion


def replay(
    *, db_path: str | Path,
    request_path: str | Path = FIXTURES / "analysis_request_accepted.json",
    verdict_path: str | Path = FIXTURES / "ai_verdict_approved.json",
    renderer_type: str | None = None,
    failed_only: bool = False,
    at: str | None = None,
) -> dict:
    request, verdict = load_json(request_path), load_json(verdict_path)
    # Historical clock is explicit and safe because this module has no real transport.
    now = parse_utc(at) if at else parse_utc(verdict["generated_at"]) + timedelta(seconds=1)
    config, store, transports, dispatcher, _ = build_fake_runtime(db_path)
    compiled = ThesisCompiler(store, config).compile(
        request, verdict,
        InputAttestation(True, True, "fixture://session-0/ai-verdict-approved"),
        now=now,
    )
    results = dispatcher.dispatch_setup(
        compiled["thesis"]["setup_id"], now=now,
        renderer_type=renderer_type, failed_only=failed_only,
    )
    return {
        "ok": all(item.status.value not in {"TERMINAL_FAILURE", "RETRYABLE_FAILURE",
                                             "BLOCKED_SAFETY", "UNCERTAIN"} for item in results),
        "mode": "SHADOW",
        "dry_run": True,
        "external_side_effects": False,
        "clock_mode": "EXPLICIT" if at else "RECORDED_FIXTURE",
        "created": compiled["created"],
        "setup_id": compiled["thesis"]["setup_id"],
        "thesis_id": compiled["thesis"]["thesis_id"],
        "results": [item.as_dict() for item in results],
        "deliveries": store.deliveries_for_setup(compiled["thesis"]["setup_id"]),
        "transport_counts": {
            "tradingview_objects": len(transports["tradingview"].objects),
            "telegram_messages": len(transports["telegram"].messages),
            "notion_records": len(transports["notion"].records),
            "mt5_dry_run_requests": len(transports["mt5"].orders),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "storage" / "project_a_outputs.db")
    parser.add_argument("--request", type=Path, default=FIXTURES / "analysis_request_accepted.json")
    parser.add_argument("--verdict", type=Path, default=FIXTURES / "ai_verdict_approved.json")
    parser.add_argument("--renderer", choices=["TRADINGVIEW", "TELEGRAM", "NOTION", "MT5_DEMO"])
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--at", help="explicit UTC Z replay clock; fake mode only")
    parser.add_argument("--status", action="store_true", help="inspect statuses after replay")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.status:
            payload = {
                "ok": True, "mode": "SHADOW", "dry_run": True,
                "external_side_effects": False,
                "deliveries": OutboxStore(args.db).all_deliveries(),
            }
        else:
            payload = replay(
                db_path=args.db, request_path=args.request, verdict_path=args.verdict,
                renderer_type=args.renderer, failed_only=args.failed_only, at=args.at,
            )
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 0 if payload["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
