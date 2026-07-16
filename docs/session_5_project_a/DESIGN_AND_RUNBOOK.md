# Session 5 design, operations, and rollback runbook

## Delivered safety boundary

Session 5 accepts only a structurally and semantically valid frozen Analysis
Request 1.0 plus Verdict 1.0, exact matching identities, an explicit statement
that Session 4 post-gates passed, and a persisted audit reference. Raw model text
is never parsed. Compilation fails before persistence when any boundary fails.

The canonical record is:

```text
immutable request + immutable verdict + audit reference
                         |
                         v
              immutable Thesis 1.0
                         |
                         v
      atomic per-renderer SQLite outbox deliveries
          |          |          |          |
          v          v          v          v
         TV      Telegram     Notion    MT5 fake Demo
```

The frozen Thesis contains the verdict and exact Entry/SL/TP geometry. Request-
only AOI/SNR, spread, source-event IDs, momentum, and evidence remain in the
hashed source record. No renderer recalculates a trade. Outcomes are append-only
history linked by `setup_id` and `thesis_id`; they never update the Thesis row.

Delivery is honestly at-least-once. Stable idempotency keys, external lookup,
immutable content hashes, per-attempt history, claim recovery, and explicit
uncertain-result reconciliation make duplicates harmless. There is no claim of
distributed exactly-once delivery.

## Initialize and validate

Use PowerShell from the repository root:

```powershell
py -m output.project_a.ops validate-config docs\session_5_project_a\CONFIG_TEMPLATE.yaml
```

The committed template is expected to exit 2 until every `REPLACE_WITH_...`
value is replaced in a private copy. Wildcards, nonnumeric Telegram authority,
wrong port/symbol/timeframe, missing MT5 allowlists, non-shadow, non-dry-run, and
any `live_execution` or `order_placement` key fail closed.

Validate the committed synthetic CI/replay profile (expected exit 0):

```powershell
py -m output.project_a.ops validate-config docs\session_5_project_a\RECORDED_FAKE_CONFIG.yaml
```

Initialize the dedicated database and run all adapters in fake mode:

```powershell
py -m output.project_a.replay --db storage\project_a_outputs.db
```

This creates tables additively, runs the frozen fixture on a recorded historical
clock, and performs no external call. Confirm SQLite integrity and status:

```powershell
py -m output.project_a.ops --db storage\project_a_outputs.db status
py -m output.project_a.replay --db storage\project_a_outputs.db --status
```

## Replay and independent retry

Replay one selected renderer in fake mode:

```powershell
py -m output.project_a.replay --db storage\project_a_outputs.db --renderer TELEGRAM
```

Retry only a retryable failed renderer:

```powershell
py -m output.project_a.replay --db storage\project_a_outputs.db --renderer TELEGRAM --failed-only
```

Completed deliveries are not claimed again. Terminal, safety-blocked, or
uncertain deliveries require an explicit audited operation. Recover a claim
abandoned for at least 60 seconds:

```powershell
py -m output.project_a.ops --db storage\project_a_outputs.db recover-abandoned --claim-timeout 60
```

Reset a non-completed delivery only after inspection:

```powershell
py -m output.project_a.ops --db storage\project_a_outputs.db reset DELIVERY_ID --actor Jones --reason "reviewed stable error and approved fake retry"
```

Completed deliveries cannot be reset. `UNCERTAIN` is reconciled through the
renderer lookup by idempotency/client reference before it may become retryable;
the dispatcher API records that operation. Do not interpret a timeout as proof
that no MT5 Demo request was accepted.

## Disable renderers and all effects

Remove one name from `enabled_renderers` before Thesis creation to disable that
renderer. Use an empty list to enqueue no output deliveries:

```yaml
enabled_renderers: []
shadow: true
dry_run: true
```

This branch has fake transports only. There is no live-order value, broker SDK,
`order_send`, Telegram HTTP transport, Notion write transport, or TradingView
mutation transport in the Session 5 package.

## External identity verification checklist

TradingView (before any future separately approved smoke test):

1. Endpoint is exactly port 4999 and belongs to the configured process identity.
2. Exactly one intended TradingView tab is selected; tab/layout IDs match.
3. Symbol is XAUUSD, broker feed is exactly allowlisted, and timeframe is 1m.
4. Thesis is unexpired APPROVE/MODIFY with exact 1:1 geometry and SHADOW mode.
5. Object IDs use `project-a:<thesis_id>:<kind>`; cleanup receives only references
   created by the failed attempt. Never clear all drawings.

Telegram: destination and owner must be the same numeric Jones user ID and the
transport must attest direct-message routing. Usernames, groups, channels,
wildcards, or missing IDs are blocked.

Notion: the database ID must match the approved Call Log and its schema must
support exact `setup_id` lookup plus content conflict detection. The current
database does not, so real writes are blocked pending Session 0 approval.

MT5 Demo: connection, `MT5_DEMO` environment, `DEMO` trade mode, exact account,
server, terminal path, symbol mapping, precision, and current spread must all be
positively attested. Absence of “live” is not evidence of Demo. The repository
currently has no such real attestor or broker transport.

## Outcome update

Create a private JSON payload containing all fields enforced by
`OutboxStore.append_outcome`: event/setup/thesis IDs, recorded time, ticket,
requested/fill/exit prices, spread, slippage, open/close times, exit reason,
initial risk, MAE, MFE, realised P/L/R, and one of `PARTIAL`, `CLOSED`,
`CANCELLED`, `REJECTED`, or `UNKNOWN`. Then run:

```powershell
py -m output.project_a.ops --db storage\project_a_outputs.db outcome C:\private\outcome.json
```

Same event ID and same content is idempotent; conflicting content or a mismatched
setup/Thesis fails closed. The programmatic `OutcomeReconciler` also updates the
same fake Notion record when present.

## XAUUSD acceptance

Run 28 fake/recorded samples and produce inspectable artifacts:

```powershell
py -m output.project_a.acceptance --output storage\session5_acceptance.json --markdown storage\session5_acceptance.md
```

For the later real shadow acceptance, Session 0 must copy
`ACCEPTANCE_REPORT_TEMPLATE.md`, obtain Jones approval separately for each real
TradingView/Telegram/Notion/MT5 Demo smoke-test class, run 20-30 genuine Analysis
Ready samples across Asian and London/New York contexts, attach raw audit refs,
and have a reviewer sign every row. Do not reuse recorded fixture evidence as a
real sample.

## Rollback and partial external success

1. Stop Session 5 writers/adapters. Disable all renderers. Do not delete external
   objects, messages, pages, tickets, or audit files.
2. Record the deployed SHA, config hash, database path, and delivery statuses.
3. Back up and verify SQLite without modifying the original:

```powershell
Copy-Item storage\project_a_outputs.db storage\project_a_outputs.rollback-copy.db
py -m output.project_a.ops --db storage\project_a_outputs.rollback-copy.db status
```

4. If Session 5 was merged, Session 0 should revert the Session 5 commit(s) with
   a new Git revert commit. Do not rewrite Session 0 history.
5. Keep the output database quarantined with the old code. This branch adds no
   migration to `storage/trading.db` and therefore has no destructive down step.
6. For partial external success, preserve external references, reconcile each
   uncertain delivery, and retry only the failed renderer. Never rerun successful
   outputs or broadly delete TradingView drawings/Notion records.
7. Run Session 0 contract tests and offline replay before resuming fake mode.

If a future migration is approved, stop writers, use SQLite backup/integrity
checks, execute only its reviewed down plan, and retain raw immutable documents.
No migration rollback should be improvised from this runbook.

## Candid reliability assessment

The new local architecture is reliable for a single-host shadow pipeline: atomic
creation, immutable hashes, leases, attempts, independent status, and explicit
reconciliation close the largest legacy gaps. It is not a distributed queue and
needs one-writer discipline or a reviewed service wrapper for multi-host use.

The existing TradingView code is safe for read/capture only; it is not safe as a
Project A drawing implementation because it uses 9222/9333, may fall back by tab
position, and has no object-level verify/rollback. The new adapter proves the
required protocol only with a fake transport.

Legacy Telegram/Notion idempotency is not robust. Session 5's fake boundary is
robust by content hash and stable identity, but a real Telegram adapter still
needs response lookup/ledger behavior, and the real Notion schema needs migration.
MT5 Demo cannot currently be positively distinguished from live because no real
attestor exists. Adding an SDK before that proof would be unsafe.

Notion is useful as a human-readable mirror, not the sole long-term audit record:
API edits, schema drift, and rich-text limits make immutable local contract JSON,
hashes, attempts, and outcomes the stronger authority. Twenty to thirty samples
are enough for a first shadow integration gate, not for strategy performance or
rare-failure confidence. Retain failure injection and expand operational samples
before any authority increase.
