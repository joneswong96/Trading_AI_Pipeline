# Project A real module map

Audit baseline: commit `dfe5e07` on `main`, inspected 2026-07-16. Repository:
`trading-auto` (`origin` = `joneswong96/Trading_AI_Pipeline`). The parent
`TradingSys` folder is not a Git repository; `vendor/tradingview-mcp` is a
separate vendored Node package outside this repository.

| Module / files | Purpose and current I/O | Dependencies | Project A boundary / owner | Status and gaps |
|---|---|---|---|---|
| `ingest/parser.py` | Accepts JSON, SNR pipe, legacy/MRF/Renko text; emits unversioned `AlertEvent` | stdlib | Session 2 consumes Session 1 events | Implemented legacy parser. Permissive fallback can turn malformed text into Renko-like events; no size/version/ID/provenance enforcement. Needs an adapter to Event 0.2, not a schema rewrite by Session 2. |
| `ingest/webhook_server.py` | FastAPI `POST /alert`; parse → dedupe → SQLite → wake decision → fan-out | FastAPI, dotenv, publishers | Session 2 | Implemented notify-only service. Returns HTTP 200 for parse/insert failures and initializes DB at import. No Project A event endpoint yet. External fan-out is best effort. |
| `ingest/alert_log.py` | Persists normalized alert columns plus raw JSON in `alert_events`; 10-second equality dedupe | SQLite | Session 2; DB shape Session 0 | Implemented. No schema version, stable event/setup/correlation IDs, payload hash uniqueness, or migration framework. |
| `ingest/trigger.py` | Legacy SNR/resonance/MRF wake rules plus active-thesis gate | SQLite-shaped rows | Session 2 | Implemented and tested, but uses fixed cooldowns/proxies. Project A authority requires state-change/no-new-evidence semantics. This is a documented behavior conflict for Session 2. |
| `ingest/wake_queue.py` | Append/rewrite JSONL queue linking wake to thesis | filesystem | Session 2 → Sessions 3/5 | Implemented legacy bridge. JSONL rewrite is local-process oriented and lacks request/setup/correlation contract IDs. |
| `capture/tv_mcp.py`, `capture/screenshot.py` | Five-layout screenshot bundle via CDP 9222 or Playwright | Playwright, TradingView session | Session 3 | Implemented legacy capture. Project A requires dedicated XAUUSD port 4999 and 1m verification; existing capture routing differs. |
| `capture/tv9333.py` | Guarded read-only OHLC/HTF/DXY capture on CDP 9333 | Playwright, local Chrome | Session 3 | Mature deterministic data reads/freshness guards. Port and layout model conflict with Project A 4999 profile; adapter/transition decision needed without weakening current guards. |
| `analyze/sop_prompt.py`, `analyze/golden.py` | Manual screenshot reasoning prompt and legacy call schema | optional model/manual Codex | Session 4 | Existing reasoning path is manual-first and not the fixed AI Verdict 1.0 contract. Must remain untrusted input and shadow-only. |
| `analyze/thesis_emit.py` | Manual thesis validation; append DB, JSON backup, consume wake, best-effort Notion backfill | SQLite, filesystem, Notion adapter | Legacy compatibility; Session 5 consumes frozen thesis | Implemented but schema/status/ID names differ from Thesis 1.0, validates only a subset, generates nondeterministic IDs, and writes in multiple non-transactional steps. Use an explicit compatibility adapter. |
| `ingest/thesis_store.py` | Append-only `thesis_log`, version lookup, latest active thesis | SQLite | Session 5; DB shape Session 0 | Strong append-only concept, but schema lacks setup/request/verdict/correlation/schema-version/environment fields and uniqueness constraints. Migration deferred until feature persistence design is ready. |
| `output/telegram_push.py` | Five-line notify-only card with in-memory dedupe | Telegram publisher | Session 5 | Implemented. Uses legacy thesis fields and process-local dedupe. |
| `publish/notion_log.py` | Notion Call Log page creation/backfill | requests, Notion credentials | Session 5 | Implemented external adapter; network tests are blocked. It truncates raw content and has no outbox/idempotency persistence. |
| `output/mt5_mirror.py` | Builds/logs a fake order with `dry_run=True`; no broker import or network | stdlib | Session 5 | Safe scaffold. Legacy actionable statuses differ from Project A verdicts; it does not verify environment identity. Project A replay uses a separate fake adapter and never calls this module. |
| `publish/marker.py` | Marks screenshots; legacy drawing output | Pillow | Session 5 | Implemented screenshot annotation, not the Project A TradingView 4999 drawing contract. |
| `storage/db.py` | `cycles` SQLite table and pushed-call replay metadata | SQLite | Existing shared DB; Session 0 migration owner | Implemented ad-hoc table creation, no ordered migration runner/transactional outbox. |
| `scheduler/run.py` | Capture/precheck/analyze/publish cycle | most runtime modules | Existing runtime, outside Session 0 feature work | Implemented legacy pipeline. Not wired to frozen contracts. |
| `tests/` | 37 legacy pytest modules with external sends/storage isolated by `conftest.py` | pytest | Shared tests; Session 0 owns contract/integration additions | Strong unit coverage. No lint/type configuration and no prior fixed contract/replay suite. |
| `contracts/`, `fixtures/project_a/`, `project_a/replay.py` | Frozen schemas, deterministic validation, golden artifacts, offline full-chain replay | jsonschema, PyYAML | **Session 0** | Added integration foundation. No feature/live dependencies. |
| `config/project_a.yaml` | Pinned Project A mode, profile, risk, port, contract versions | PyYAML | **Session 0** | Added. Fails closed to XAUUSD/SHADOW/MT5_DEMO/port 4999/1m/10 points/1:1. |

## Runtime and persistence boundaries

Current runtime entry points are `py -m ingest.webhook_server`, `py -m
scheduler.run`, `py -m capture.tv_mcp`, `py -m capture.tv9333`, `py -m
analyze.thesis_emit`, and `py -m output.invalidation_watch`. Project A adds only
the offline entry point `py -m project_a.replay --all` in Session 0 scope.

SQLite is a single local file (`storage/trading.db`) with tables created lazily
by three modules: `cycles`, `alert_events`, and `thesis_log`. JSONL wake logs and
filesystem screenshot/call/thesis backups are additional persistence boundaries.
There is no migration ledger, queue, transaction spanning artifacts, or durable
output outbox. No migration is introduced in this foundation because Sessions
2/3/5 have not yet established the exact persisted representations; guessing
columns now would create a second contract. Any later migration is Session 0
owned, additive first, backed up, and rollback-tested.

## External dependencies and deployment paths

- TradingView and logged-in Chrome profiles on CDP 9222/9333 today; Project A
  target profile is XAUUSD port 4999.
- Telegram Bot API and Notion REST API, both credential-gated and blocked in tests.
- Optional/manual model reasoning; no installed model SDK is required by the
  integration replay.
- FastAPI/Uvicorn local port 8000 for legacy ingest.
- SQLite and local artifact directories under `storage/`.
- MT5 is not imported or connected. The existing mirror and new replay are fake/
  dry-run only.
- Deployment documentation is Windows command-based in `docs/runbook.md`; no CI
  workflow, container, service manager, migration runner, or production deploy
  manifest exists in this repository.

## Integration boundaries

```text
Session 1 Pine producer
  -> EVENT_SCHEMA_V0_2 fixture
Session 2 ingest/state
  -> validated ANALYSIS_READY event
Session 3 capture/request compiler
  -> ANALYSIS_REQUEST_SCHEMA_V1 fixture
Session 4 shadow AI reviewer
  -> AI_VERDICT_SCHEMA_V1 fixture
Session 5 thesis/output adapters
  -> THESIS_SCHEMA_V1 + fake/real-shadow outputs
Session 0 replay/acceptance/merge
```

All builders can develop from recorded fixtures. No builder needs TradingView,
AI, Telegram, Notion, MT5, or another session branch to run its contract tests.

## Key conflicts and integration-compatible interpretations

1. Notion Project A says port 4999/1m; current code uses 9222 capture and 9333
   reads. The frozen Project A request contract pins 4999; existing code remains
   untouched. Session 3 must implement a verified adapter or request an explicit
   architecture decision—never silently fall back across ports.
2. Project A fixes RR at 1:1; current `assets.yaml` advertises 1R/2R/3R and legacy
   theses expose `tp1`/`tp2`. Frozen request/verdict/thesis contracts expose one
   TP and enforce exact 1:1. A compatibility renderer may derive display-only
   legacy fields, but cannot change decision geometry.
3. Project A uses state-change gating; legacy trigger uses fixed cooldowns in
   several paths. Session 2 must preserve legacy behavior behind an adapter while
   implementing Project A dedupe/new-evidence rules for versioned events.
4. Project A verdict values differ from legacy thesis statuses. The frozen
   contracts keep verdict (`APPROVE/REJECT/MODIFY/EXPIRED`) distinct from thesis
   lifecycle state (`ARMED/...`). No implicit string reuse.
5. Hub says MT5 Demo mirror; repository rule says no broker API. Safest compatible
   interpretation is a fake/dry-run Demo artifact only until Jones separately
   authorizes a broker integration. Session 0 has not broadened that authority.
