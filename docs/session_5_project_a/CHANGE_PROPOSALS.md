# Session 5 contract and Notion mapping proposals

No frozen contract, shared fixture, real Notion schema, or legacy database was
changed on this branch.

## Proposal 1: Thesis evidence binding in a future minor contract

Problem: Phase 3 requires AOI/SNR, spread, broker feed/base timeframe, reason
codes, evidence/source-event references, and a persisted Verdict audit reference,
but `THESIS_SCHEMA_V1` cannot represent them. Renderers need these fields for
TradingView AOI, Telegram spread, and the complete Call Log.

Current safe adapter: Session 5 stores immutable, canonical request/verdict JSON
and hashes beside the frozen Thesis. Trade geometry/verdict always come from the
Thesis; request-only display/audit values come from the bound request. This solves
V1 without widening the contract.

Proposed Session 0 decision: consider a future optional, strictly typed
`evidence_binding` in a minor Thesis version containing request/verdict hashes,
source-event IDs, audit reference, base timeframe, feed/venue identity, spread,
AOI/SNR, and bounded evidence references. Do not copy mutable renderer statuses or
outcomes into the immutable Thesis. This is additive in concept but still needs a
new registered version because unknown fields currently fail closed.

Security/rollback: references must be bounded and secret-free; raw payloads stay
in protected storage. Readers for the current version remain until one full
shadow cycle proves dual-read behavior. Writers stop before rollback.

## Proposal 2: Notion Call Log mapping/migration

Actual inspected data source: `286023fb-0f17-4865-84aa-557abc838323`, with legacy
fields `Call`, `dir`, `engine`, `event`, `price`, `raw`, `reason`, `tf`,
`thesis_status`, `time`, `wake`, and `wake_id`.

It lacks the stable Project A lookup/conflict fields needed for safe upsert. A real
renderer must remain blocked until Session 0/Jones approves either a new Project A
Call Log or additive fields on the existing database. Minimum proposal:

| Field | Suggested type | Purpose |
|---|---|---|
| `setup_id` | rich text, operationally unique | exact logical-record lookup |
| `thesis_id` | rich text | canonical Thesis link |
| `content_hash` | rich text | same-ID conflict detection |
| `request_id` / `verdict_id` | rich text | source chain |
| `correlation_id` | rich text | cross-stage trace |
| `renderer_statuses` | rich text/JSON | independent delivery snapshot |
| `audit_ref` | rich text or URL | bounded persisted evidence reference |
| `outcome_status` | select | latest Demo outcome summary |

The immutable complete request/verdict/Thesis and attempt/outcome history should
remain in local durable storage; Notion should mirror them and link to bounded
audit artifacts. A migration needs export/backup, duplicate-setup audit, a dry run,
mapping tests, update-in-place proof, and rollback by removing only newly added
fields after writers stop. Session 5 did not perform or request that write.

## Shared SQLite

No shared SQLite migration is required. Session 5 uses a dedicated additive
database so Session 0 can merge and test without modifying `storage/trading.db`.
If Session 0 later consolidates stores, it owns the migration ledger, backup,
integrity check, dual readers, and reviewed down plan.
