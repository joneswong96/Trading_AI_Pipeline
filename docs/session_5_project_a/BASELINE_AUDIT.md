# Session 5 baseline audit

Audit date: 2026-07-16. Branch: `project-a/session-5-outputs-acceptance-v1`.
Required baseline: `d10f6ea` (`project-a: freeze integration contracts and replay
foundation`). The branch was created at that exact commit in an isolated worktree
because the shared Session 3 checkout contained unrelated untracked work.

## Sources and working baseline

The Project A Hub, Analysis Skill, three-phase SSOT, Phase 3 Hub, Session 5 page,
Phase 3 output/MT5 SSOT, pre-order checklist, actual Notion Call Log database,
Session 0 documents, frozen schemas/fixtures, legacy modules, and tests were read
before implementation. The repository and frozen contracts take precedence where
older Notion examples conflict.

Baseline commands and results:

```powershell
py -m pytest tests/test_project_a_contracts.py tests/test_project_a_replay.py -q
# 16 passed

py -m project_a.replay --all
# exit 0, ok=true, SHADOW, MT5_DEMO, live_execution=false

py -m pytest tests/ -q
# 402 passed, 1 skipped, 1 failed
```

The one complete-suite failure is pre-existing and workspace-specific:
`test_dual_command_copies_are_byte_identical` compares the tracked inner command
copy checked out with CRLF against an outer workspace copy with LF. Session 5 does
not own either command copy and will not rewrite it.

No formatter, linter, static type checker, migration runner, or CI workflow is
configured. `pytest`, `compileall`, Session 0 replay, dependency inspection, config
validation, SQLite integrity checks, and secret-pattern scans are the available
quality gates.

## Existing thesis and verdict-to-output flow

- `analyze/thesis_emit.py` accepts a legacy, unversioned manual-call structure,
  performs partial validation, generates a time-based thesis ID, then separately
  writes SQLite, a JSON backup, wake consumption, and best-effort Notion status.
- `ingest/thesis_store.py` has a useful append-only version concept, but its
  `thesis_log` has no setup/request/verdict/correlation/schema/environment fields,
  no uniqueness constraints, and no atomic output outbox.
- Legacy statuses (`ARMED`, `WAIT`, etc.) and fields (`dir`, `tp1`, `tp2`) do not
  match the frozen Verdict/Thesis contracts. It cannot be used by coercion.
- There is no validated Verdict 1.0 to output runtime. Session 0 replay reads a
  frozen request, fake verdict, frozen thesis fixture, and fake downstream output
  independently; it does not compile or durably deliver outputs.

## Existing renderer boundaries

### Telegram

- `output/telegram_push.py` deterministically formats a legacy five-line card,
  but dedupe is process-local and it marks an item seen before an external result
  is known. Restart and uncertain-response safety are absent.
- `publish/telegram.py` sends Bot API `sendMessage` when both token and chat ID are
  present. It does not require a numeric Jones user ID, prove a direct message,
  retain Telegram message IDs, or provide durable idempotency/reconciliation.
- Destination comes from `TELEGRAM_CHAT_ID`; there is no Jones-only allowlist.
  Missing config disables the legacy publisher, while the legacy output wrapper
  falls back to console rather than reporting a durable blocked delivery.

### Notion Call Log

- `publish/notion_log.py` creates a new page for every call and can query/update
  one legacy wake by `wake_id`. There is no setup-ID lookup, content conflict
  detection, durable idempotency key, renderer-status model, or outcome history.
- The configured destination is `NOTION_CALLLOG_DB_ID`; missing config disables
  the adapter. It does not create databases automatically.
- The actual database inspected read-only is `Phase 1 - Call Log`, data source
  `286023fb-0f17-4865-84aa-557abc838323`. Its fields are `Call`, `dir`, `engine`,
  `event`, `price`, `raw`, `reason`, `tf`, `thesis_status`, `time`, `wake`, and
  `wake_id`. It cannot support stable Project A setup lookup or the full contract
  chain as typed properties. Session 5 must not alter it; a mapping/migration
  proposal is required before a real adapter can safely write.

### TradingView

- `capture/tv_mcp.py` is a screenshot/read adapter on CDP 9222. It selects tabs by
  configured layout URL (or positional fallback when no URL is configured) and
  brings tabs to the front. It has no Project A drawing commands.
- `capture/tv9333.py` is a guarded read-only data instance on 9333. It checks
  expected symbols, intervals, chart type, and MACD for configured tabs, but is
  explicitly separate from Project A's route.
- `publish/marker.py` draws on screenshots using Pillow. It is not a TradingView
  MCP drawing adapter; exact chart-object create/update/verify/cleanup does not
  exist.
- Legacy routing uses 9222/9333 and saved multi-tab layouts. Frozen Project A
  requires port 4999, exactly one selected tab, XAUUSD, allowlisted broker feed,
  1m base timeframe, and exact layout identity with no fallback. This conflict
  must remain fail-closed.

### MT5

- `output/mt5_mirror.py` builds a legacy order-shaped dictionary with
  `dry_run=True` hard-coded and has no broker import or network call. This is the
  correct current safety floor.
- It does not validate the frozen Thesis, expiry, spread, RR, account/server,
  trade mode, terminal profile, symbol mapping/precision, feature flag, duplicate
  request, uncertain response, or reconciliation.
- No MT5 environment/account detection exists. Demo cannot currently be
  positively distinguished from live, so any non-fake MT5 action remains blocked.

## Persistence, retry, audit, and outcomes

- Persistence is split between lazily-created SQLite tables (`cycles`,
  `alert_events`, `thesis_log`), JSON/JSONL, screenshots, and Notion.
- There is no migration ledger, transaction spanning artifacts, durable renderer
  outbox, claim lease, retry scheduler, per-attempt audit, terminal-failure state,
  or external-result reconciliation.
- Telegram has in-memory dedupe; Notion is best-effort; wake JSONL backfill rewrites
  a local file. None provides cross-process output exactly-once behavior.
- No ticket/fill, spread/slippage, MAE/MFE, realised P/L/R, or final-outcome model
  exists. The Phase 3 invalidation watcher is separate legacy lifecycle logic, not
  outcome reconciliation.

## Secrets and configuration

- Secrets are loaded from environment variables and `.env`; `.env.example`
  contains blank secret placeholders. Tests delete token environment variables,
  disable dotenv loading, redirect storage, and block external sends.
- Legacy `.env.example` advertises TradingView port 9222 and does not contain
  Project A feed/layout/user/account allowlists. Session 5 will provide a separate
  secret-free template in its owned documentation path rather than changing the
  shared legacy template.

## Exact next incomplete vertical slice

Validated Request 1.0 plus validated Verdict 1.0, accompanied by an explicit
Session 4 post-gate/audit attestation, must compile exactly one immutable Thesis
1.0 and atomically enqueue independently claimable renderer deliveries. Fake
transports then prove deterministic formatting, safety gates, idempotency,
partial-failure recovery, outcomes, replay, and XAUUSD acceptance without any
external side effect.

## Frozen-contract gaps and adapter decision

`THESIS_SCHEMA_V1` intentionally does not contain base timeframe, spread, AOI/SNR,
HPA, reason codes, evidence/source-event references, broker feed, request expiry,
or verdict audit reference. Those values cannot be added to the frozen Thesis.
Session 5 will preserve the validated request and verdict as immutable, hashed
source records beside the canonical Thesis; actionable geometry and verdict always
come from the Thesis, while AOI/evidence/audit fields come only from those bound
source records. A contract-change proposal will document the long-term trade-off.

## Proposed Session 5-owned files

- `output/project_a/**`: compiler boundary, durable SQLite store/outbox, renderer
  interface, fake-safe adapters, dispatcher, outcomes, replay, acceptance harness.
- `tests/session_5_project_a/**`: unit, fake integration, replay, failure/restart,
  configuration, and acceptance tests.
- `docs/session_5_project_a/**`: this audit, design/runbook, configuration template,
  acceptance report template/sample evidence, and change proposals.

Frozen contracts, fixtures, `project_a/**`, upstream session modules, legacy shared
database modules, model prompts, and real external destinations remain unchanged.
