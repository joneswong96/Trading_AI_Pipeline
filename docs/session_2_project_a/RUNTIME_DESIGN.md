# Project A ingest/state runtime design

## Routing and safety

Project A keeps `POST /project-a/v0.2/events` and adds
`POST /project-a/v1/events` on the existing FastAPI listener. The V1 route is
fail-closed unless `PROJECT_A_V1_INGEST_ENABLED=true`; the default remains
disabled. The safe/default actual port is `8000`; `PROJECT_A_INGEST_PORT` can
override it, but configuration refuses `4999`. Legacy `POST /alert`, ports
`9222`/`9333`, legacy cooldowns, `trading.db`, JSONL queues, and Session 3's
XAUUSD CDP/MCP profile on `4999` are unchanged. The service contains no model,
screenshot, notification, broker, MT5, or order path.

## Receipt and transaction model

1. The HTTP stream is bounded to `PROJECT_A_MAX_BODY_BYTES` (default 256 KiB) before JSON parsing.
2. One immutable `project_a_raw_receipts` row is committed first for every
   delivery attempt, with local receipt ID, exact accepted body bytes,
   deterministic body hash, actual Session 2 receipt time, content type, bounded
   safe source metadata, and `raw_complete`. Oversized bodies retain a bounded
   `limit+1` prefix and explicitly mark `raw_complete=0`; they are never parsed.
3. Each processing result is append-only in `project_a_receipt_processing`. Raw rows are never updated to hide later outcomes.
4. V1 raw/hash/strict JSON/shape/lifecycle preflight completes before the durable
   dedupe authority begins. Session 2 issues the private production receipt
   context only after raw storage, binding those exact bytes to actual
   `received_at`.
5. A durable claim and second `BEGIN IMMEDIATE` unit atomically reserve exact and
   semantic dedupe, persist the Canonical Event V1 decision, eligible setup
   state, processing audit, and Analysis Ready outbox row. The outbox is held
   with `release_authorized=0` until fresh point-of-use verification confirms the
   committed receipt transaction.
6. Rollback removes canonical/dedupe/state/outbox effects while preserving the
   raw receipt. Commit-unknown or point-of-use confirmation failure is recorded
   as `COMMIT_UNKNOWN`; its outbox remains unclaimable. Stale ingress and outbox
   claims are handled by explicit recovery.
7. Rejections atomically add processing history plus a bounded, queryable dead
   letter. Diagnostics never store stack traces or copy arbitrary payload text.

The module uses a dedicated `storage/project_a.db`. This avoids altering
Session 0-owned shared `trading.db` history. Schema versions 1 and 2 are recorded
with checksums in `project_a_schema_migrations`; startup fails on missing,
partial, non-contiguous, newer, or checksum-mismatched state. Both migrations
are additive and transactional. Its down operation remains “stop writers, back
up, remove the dedicated database only if its data is disposable”; tables are
not destructively removed from a shared database.

## Hashes and uniqueness

- Body hash: SHA-256 of received bytes; identical delivery attempts still receive distinct immutable `ingest_id` rows.
- Event V0.2 retains its legacy canonical and evidence behavior.
- V1 canonical content and semantic evidence hashes are produced only by the
  integrated Event V1 reader. The semantic hash uses
  `project-a-evidence/1.1`, excluding event/receipt IDs, clocks, producer
  diagnostics, extensions, optional 5s Arrow, spread, and other non-evidence
  metadata.
- `project_a_canonical_events.event_id` is the canonical-event primary key.
- Same event ID/same canonical hash returns `IDEMPOTENT_DUPLICATE`; same ID/different hash returns `EVENT_ID_CONFLICT` and a dead letter.
- Same semantic fingerprint under a different event ID is retained canonically but produces no state update or dispatch.
- Outbox `dispatch_key` is unique over destination, purpose, setup, and evidence fingerprint.
- Replay defaults to an isolated SQLite backup. Committed replay requires `--commit`, reuses the real validator/state code, records a replay operation, and cannot duplicate a committed outbox effect.

## Transition table

Only exact Event 0.2 values are persisted as lifecycle state.

| Current | Incoming Event 0.2 value | Guard | Next | State/history | Outbox | Outcome/reason |
|---|---|---|---|---|---|---|
| none | `SNR_UPDATE` / `EXPANSION_UPDATE` | valid telemetry | none | no | no | record / `TELEMETRY_RECORDED` |
| none | `SETUP_CANDIDATE` | accepted candidate, valid SNR | `SETUP_CANDIDATE` | yes | no | accept / `CANDIDATE_CREATED` |
| `SETUP_CANDIDATE` | telemetry | new fingerprint/order valid | unchanged | history update | no | accept / `EVIDENCE_UPDATED` |
| `SETUP_CANDIDATE` | `SETUP_CANDIDATE` | new evidence | unchanged | yes | no | accept / `CANDIDATE_UPDATED` |
| none or candidate | `SNR_REJECTION_READY` | accepted, SNR, normalized spread ≤10 | `SNR_REJECTION_READY` | yes | yes | accept / Analysis Ready |
| none or candidate | `SNR_BREAK_READY` | accepted, SNR, normalized spread ≤10 | `SNR_BREAK_READY` | yes | yes | accept / Analysis Ready |
| either ready state | either ready value | semantic fingerprint changed | incoming ready state | yes | yes | immediate new evidence; no cooldown |
| any nonterminal setup | same evidence | same semantic fingerprint | unchanged | no | no | `DUPLICATE_EVIDENCE` |
| candidate/ready | `SETUP_INVALIDATED` | ordering valid | `SETUP_INVALIDATED` | yes | no | immediate terminal transition |
| candidate/ready | `SETUP_EXPIRED` | ordering valid; explicit expiry may report after stale threshold | `SETUP_EXPIRED` | yes | no | immediate terminal transition |
| any | `ENTRY_WINDOW_OPEN` / `ENTRY_WINDOW_CLOSED` / `THESIS_INVALIDATED` | structurally valid V0.2 | unchanged | no | no | `UNSUPPORTED_LIFECYCLE_V02` |
| terminal | any state-opening event | unique, newer | unchanged | no | no | dead letter / `TERMINAL_SETUP_REOPEN` |
| any setup | older occurrence time | not duplicate | unchanged | no | no | dead letter / `OUT_OF_ORDER_EVENT` |
| any | same ID/same content | canonical match | unchanged | no | no | idempotent duplicate |
| any | same ID/different content | hash conflict | unchanged | no | no | dead letter / `EVENT_ID_CONFLICT` |
| any | restart | migration and integrity ready | persisted state | no implicit change | no implicit dispatch | deterministic recovery |

Producer-disposition `REJECTED` events are retained canonically as `RECORDED_REJECTED` but do not open state or dispatch.

## Timestamp profile

Wire timestamps must already be UTC `Z`; offsets and naive values fail the frozen validator. Local receipt, producer `received_at`, event `occurred_at`, and bar time remain distinct. Runtime ordering/freshness uses local receipt time and `occurred_at`, never the client receipt field. With no frozen tolerance values, Session 2 proposes fail-closed defaults of 5 seconds future tolerance and 1,800 seconds stale threshold, both explicit environment settings and clock-injected in tests. This is a runtime profile decision for Session 0 review, not schema widening.

## Outbox consumer interface

For V1, Session 3 receives the trusted Canonical Event V1 document rather than
caller bytes. For V0.2 it retains the validated legacy event. Both use
`outbox_schema_version=1.0`, destination `SESSION_3_PHASE_1_8`, purpose
`COMPILE_ANALYSIS_REQUEST`, and a stable `dispatch_key`. Only
`release_authorized=1` rows can be claimed. Delivery remains at-least-once:
claims change `PENDING/FAILED` to `PROCESSING`, increment durable attempts, and
record an attempt. Acknowledgement marks `DELIVERED`; retryable failure marks
`FAILED`; the configured attempt limit marks `DEAD_LETTER`; abandoned claims
become retryable after the durable claim timeout.

## Operational visibility

Liveness, readiness, and metrics are separate endpoints. Readiness covers database integrity, migration version, outbox query, configuration safety, XAUUSD identity, shadow/no-order state, actual ingest port, and the reserved capture port. Metrics are database-derived receipt/accept/reject/duplicate/conflict/transition/readiness/outbox/dead-letter/replay counts. Structured logs contain only safe IDs and result codes, never raw payloads or stack traces.
