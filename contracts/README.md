# Project A frozen contracts

Status: existing Event 0.2 and pipeline contracts are **FROZEN on
`project-a/integration-v1`**. Event V1 entries below are a reader-only foundation;
their writers are disabled. Changes require the process in `CHANGE_REQUEST.md`.

| Contract | Wire version | Schema file | Producer | Consumers |
|---|---:|---|---|---|
| `EVENT_SCHEMA_V0_2` | `0.2` | `schemas/event_schema_v0_2.json` | Sessions 1–2 | Sessions 2–3, replay |
| `PROJECT_A_WIRE_EVENT_V1` | `1.0` | `schemas/project_a_wire_event_v1.json` | **Writer disabled** | Session 0 dual reader only |
| `PROJECT_A_CANONICAL_EVENT_V1` | `1.0` | `schemas/project_a_canonical_event_v1.json` | **Writer disabled** | Session 0 dual reader/replay only |
| `ANALYSIS_REQUEST_SCHEMA_V1` | `1.0` | `schemas/analysis_request_schema_v1.json` | Session 3 | Session 4, replay |
| `AI_VERDICT_SCHEMA_V1` | `1.0` | `schemas/ai_verdict_schema_v1.json` | Session 4 | Session 5, replay |
| `PROJECT_A_GRADE_SCHEMA_V1` | `1.0` | `schemas/project_a_grade_schema_v1.json` | Analysis Worker | Story Memory, local audit |
| `THESIS_SCHEMA_V1` | `1.0` | `schemas/thesis_schema_v1.json` | Session 5 compiler | Session 5 adapters, Session 0 acceptance |

## Common contract rules

- Identifiers are opaque, stable strings. `setup_id` and `correlation_id` are
  preserved across every stage. `causation_id` points to the immediate parent.
- Timestamps are ISO 8601 UTC and must end in `Z`. Naive timestamps and local
  offsets are rejected even when mathematically equivalent to UTC.
- Instrument values use canonical uppercase symbols. The schema remains shaped
  for future profiles, but Project A V1 validation/config enables only `XAUUSD`.
- Timeframes use canonical compact values (`5s`, `1m`, `4h`, `1d`, etc.). V1
  analysis requests require a `1m` base timeframe.
- Top-level and defined nested objects use `additionalProperties: false`.
  Event V1 diagnostics/extensions are closed allowlists of benign, typed,
  non-authoritative fields. Reserved control concepts are rejected in keys and
  string values. `EVENT_SCHEMA_V0_2.payload` remains frozen and untrusted.
- Documents are limited to 256 KiB. Secret-like keys must be absent, empty, or
  `REDACTED`. Raw payload references belong in protected storage, not contracts.
- Deterministic serialization is UTF-8 JSON with keys sorted, no insignificant
  whitespace, finite normalized base-10 numbers, and no Unicode normalization.
  Numeric equivalents (`1`, `1.0`, `1e0`, negative zero) serialize identically.
  Before fixed-form rendering, numbers are limited to 64 significant digits,
  absolute exponent and adjusted exponent 10,000, and 2,048 rendered characters.
  Wire schemas impose their own tighter numeric magnitudes where applicable.
  This Project A policy is deliberately not represented as RFC 8785. Use
  `contracts.canonical_json` for hashes and fixture comparisons.
- Validation rejects before persistence or downstream calls. Stable error codes
  distinguish structural schema errors from semantic hard-gate failures.
- No contract authorizes live execution. Analysis requests, verdicts, and theses
  pin `SHADOW`, `MT5_DEMO`, and `live_execution=false`.

## Contract-specific decisions

### Wire and Canonical Event 1.0 reader foundation

Wire Event 1.0 contains only producer-known evidence and never accepts trusted
receipt, canonical identity/hash, validation, retry, dead-letter, or ingest audit
fields. `validate_*_shape` and `parse_wire_event_v1_bytes` produce only
non-authoritative document wrappers. A canonical JSON document that passes its
schema remains untrusted.

`process_wire_event_v1_receipt` first completes a raw boundary over exact bounded
bytes: hash, strict UTF-8/JSON parse, lifecycle identity checks, and Wire shape
validation. Malformed or invalid input returns an auditable `REJECTED` result
with no Canonical Event and without consulting canonical dedupe. Durable raw
receipt retention is a separate trusted-ingress responsibility owned by the
future Session 2 adapter; this foundation does not represent in-memory state as
durable storage. Only valid Wire input enters a `DedupeAuthority` transaction,
where receipt decision, exact reservation, semantic reservation, decision
persistence, and eligibility share one commit boundary.

`verify_and_authorize_canonical_event_v1` is required immediately at every
state mutation, dispatch, audit acceptance, outbox creation, downstream handoff,
or authority-relevant replay release. It recomputes every trusted field from the
exact raw bytes, receipt context, current open committed transaction, and
intended action. Its fresh `CanonicalVerificationResultV1` must be consumed once
by that same transaction. Authorization is atomic and once-only for each
transaction generation/action pair; generation advance invalidates pending
results and consumption checks the current generation. Parsed, canonical,
processing, and verification types
are data/result surfaces: class identity, `isinstance`, internal-looking fields,
copy, pickle, subclassing, or a caller's `authority=true` never prove authority.
The generic reader always returns V1 inputs as `SHAPE_VALID / authority=NONE`.

Replay receipt issuance lives only in the private `_trusted_ingress` module and
is absent from ordinary exports. There is no production issuer. Python module
privacy is not a cryptographic boundary and malicious code in the same process
is explicitly outside the isolation claim; production adapters will require
process/security isolation. The enforced API safety property is that an ordinary
consumer cannot act without fresh exact-byte, context-, transaction-, and
action-bound verification.

Receipt transport identity means a stable provider delivery/idempotency key,
not a connection, process, random attempt, machine, or local-path identity. An
offline in-memory dedupe implementation exists only for tests/replay; a runtime
adapter must be durable and unavailability, invalid adapter results, transaction
failure, and partial/unknown commits fail closed. Every receipt keeps a
unique receipt ID and immutable raw reference even when duplicate suppression
prevents dispatch.

`canonical_json` is the single deterministic serializer: UTF-8, sorted object
keys, compact `,`/`:` separators, array order preserved, lowercase JSON
booleans/null, no ASCII requirement, no NFC normalization, and finite normalized
base-10 numbers. Trusted byte parsing uses `Decimal`; unsupported/non-finite
values reject. Semantic evidence additionally normalizes every included time to
`YYYY-MM-DDTHH:MM:SS.mmmZ`; offsets, missing zones, leap seconds, invalid dates,
and more than millisecond precision reject.

Ordinary Event 0.2 reads are always `LEGACY_UNVERIFIED`, non-dispatching, and
non-mutating. Caller metadata cannot establish `LEGACY_TRUSTED`. No trusted
legacy migration API exists until an immutable stored-receipt adapter is built.

### Event 0.2

Required envelope fields include schema/identity/correlation, UTC occurrence and
receipt times, source/provenance/hash, instrument/timeframe, event class/type,
nullable setup/hypothesis/path, explicit disposition, and payload. An
`ANALYSIS_READY` event semantically requires `setup_id`, `hypothesis`, and
`path`. The disposition enum makes accepted, rejected, structural-break,
invalid, expired, and duplicate paths observable without inspecting prose.

### Analysis request 1.0

Required fields follow the Analysis Skill bundle: request/setup/source IDs,
expiry, symbol/path/base TF/session, SNR/HPA, five momentum slots, prices,
spread, risk constraints, screenshots, and compiler provenance. Semantic checks
enforce future expiry, ordered SNR bounds, spread at or below 10 normalized
points, directional price geometry, and exact 1:1 RR.

### AI verdict 1.0

Only `APPROVE`, `REJECT`, `MODIFY`, and `EXPIRED` are legal. Actionable verdicts
require all hard gates, finite 1:1 prices, and a UTC expiry. Non-actionable
verdicts must carry null order prices. Model provenance is audit data only and
is pinned to shadow mode.

### Thesis 1.0

The thesis is canonical, versioned, append-only state. Actionable decisions are
`ARMED`/`IN_TRADE`, require valid 1:1 prices and expiry, and remain shadow/demo.
Non-actionable states retain identifiers and rationale but cannot retain order
prices. One setup maps to one thesis identity; lifecycle changes increment
`version` rather than mutating history.

## Compatibility and migration

- Version names are `<contract family>/<major.minor>` conceptually; the wire
  field stays `0.2` or `1.0` while registry constants remain stable Python names.
- Additive change: a new optional field with a safe default and readers updated
  before writers. Because unknown fields fail closed outside the event payload,
  even additive envelope changes require a minor version and coordinated rollout.
- Breaking change: required field/type/enum/meaning/identifier/timezone change.
  It requires a new major version (or event `0.3` before event 1.0), parallel
  readers, migration fixtures, and an explicit rollback plan.
- Readers accept only versions registered in `contracts.registry`. Writers emit
  exactly their pinned version. No silent coercion, fallback, or version guessing.
- Schema migrations are owned by Session 0. Feature sessions may implement
  adapters but may not change frozen schemas or database shape independently.
- Deprecation requires at least one full shadow acceptance cycle with dual-read
  evidence. Old writers stop before old readers are removed.
- Every change updates schema, semantic validator, valid/invalid fixtures,
  contract tests, replay output, compatibility notes, and pinned consumer docs.
- Rollback returns all writers/readers/config to the previous known-good commit.
  A writer rollback is unsafe after persisting a breaking newer version unless a
  tested down-converter exists; otherwise stop ingestion and preserve data.

## Consumer example

```python
from contracts import EVENT_SCHEMA_V0_2, validate_contract

event = validate_contract(EVENT_SCHEMA_V0_2, candidate)
```
