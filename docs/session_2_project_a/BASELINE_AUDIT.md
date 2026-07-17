# Session 2 baseline audit

Audit date: 2026-07-16. Required baseline: `d10f6eaf44658caa83dba19009eeef5162cf033c` (`project-a: freeze integration contracts and replay foundation`). The integration branch contained and pointed to that commit. Session 2 was created from that exact commit. A concurrent checkout was isolated with a dedicated Git worktree; the pre-existing untracked root `AGENTS.md` and other sessions' files were not copied, edited, or overwritten.

## Existing runtime

- Webhook entry point: `py -m ingest.webhook_server`; FastAPI `POST /alert` and `GET /health`.
- Routing: the listener reads `PORT`, defaults to `8000`, and historically binds `0.0.0.0`. TradingView capture uses CDP `9222` and guarded reads use `9333`. Frozen Project A configuration assigns `4999` to the XAUUSD TradingView profile. Per Jones's correction, `4999` is not an ingest port.
- Parsing: `ingest/parser.py` accepts native/legacy JSON, SNR pipe records, MRF JSON, and permissive fallback text. It has no body bound or version boundary. The legacy endpoint decodes with replacement and returns HTTP 200 on parse/insert failures.
- Database: `storage/trading.db`, with `cycles`, `alert_events`, and `thesis_log` lazily created by separate modules. There was no migration ledger or declared database version.
- Alert storage: `alert_events` records normalized legacy columns and JSON text. It does not retain a stable ingest ID, body hash, canonical event hash, schema version, or correlation/causation identifiers.
- Thesis storage: append-oriented `thesis_log`, independently initialized. It is not an Event 0.2 state machine.
- Filesystem storage: `wake_log.jsonl`, `wake_queue.jsonl`, screenshots, calls, JSON bundles, and thesis backups coexist with SQLite. `wake_queue` appends wakes but rewrites the complete file when marking consumption.
- Deduplication: `AlertLog.is_duplicate` uses a 10-second database query over engine/event/direction/timeframe/price. Other output dedupe paths are process-local or feature-based.
- Cooldown: legacy `trigger.py` uses true-wake-anchored 15-minute SNR/legacy cooldown and a separate MRF cooldown. Invalidation can bypass it. This is correct for the legacy path but conflicts with Project A state-change gating.
- Retry: downstream Telegram/Notion/file fan-out uses independent best-effort `try/except`; it has no durable retry queue. JSONL consumption is not a claim/retry protocol.
- Logging/errors: standard Python logging; the legacy parse failure logs a bounded raw-body representation and returns 200. There was no Project A structured result code, dead-letter table, or readiness breakdown.
- Replay/tools: `py -m project_a.replay --all` is Session 0's offline frozen-contract replay. `scripts/wake_audit.py` and `ingest.wake_queue --latest-unconsumed` inspect legacy artifacts. There was no raw-receipt/state/outbox replay.
- Tests: the repository had broad pytest coverage for legacy parser, triggers, cooldown, wake queue, storage, capture, analysis, outputs, frozen contracts, and offline replay. There was no configured formatter, linter, type checker, CI workflow, or migration test framework.
- Working commands: `py -m pytest tests/ -q`, `py -m pytest tests/test_project_a_contracts.py tests/test_project_a_replay.py -q`, `py -m project_a.replay --all`, and `py -m ingest.webhook_server`.

## Contract conflicts and next slice

The exact next incomplete vertical slice was versioned Project A receipt through durable Analysis Ready outbox. Conflicts were: permissive unversioned parsing, HTTP-200 failure responses, import-time/lazy unversioned schemas, fixed cooldowns, short-window dedupe, no durable state/outbox/dead letters, and the Notion/brief ambiguity that called `4999` a Project A port without distinguishing capture from ingest.

The Event 0.2 payload bag does not require `spread_points`, although runtime safety requires normalized spread at Analysis Ready. Session 2 therefore requires finite `payload.spread_points <= 10` for Analysis Ready without changing the frozen schema; the exact frozen accepted fixture remains contract-valid but is not dispatch-eligible until a producer supplies that runtime gate field. This needs Session 0/Session 1 coordination, recorded in `CHANGE_REQUESTS.md`.

## Session 2 ownership

Proposed/used paths are `ingest/project_a/**`, the minimal router inclusion and bind configuration in `ingest/webhook_server.py`, `tests/test_session_2_project_a_*.py`, and `docs/session_2_project_a/**`. Frozen contracts, fixtures, Session 0 Project A docs/config/replay/tests, legacy parser/trigger/storage, Session 1 Pine, and Session 3 capture are read-only.
