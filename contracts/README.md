# Project A frozen contracts

Status: **FROZEN on `project-a/integration-v1`**. Changes require the process in
`CHANGE_REQUEST.md`.

| Contract | Wire version | Schema file | Producer | Consumers |
|---|---:|---|---|---|
| `EVENT_SCHEMA_V0_2` | `0.2` | `schemas/event_schema_v0_2.json` | Sessions 1–2 | Sessions 2–3, replay |
| `ANALYSIS_REQUEST_SCHEMA_V1` | `1.0` | `schemas/analysis_request_schema_v1.json` | Session 3 | Session 4, replay |
| `AI_VERDICT_SCHEMA_V1` | `1.0` | `schemas/ai_verdict_schema_v1.json` | Session 4 | Session 5, replay |
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
  `EVENT_SCHEMA_V0_2.payload` is the only extension bag; readers must ignore
  unknown payload keys and must not promote them into decision authority.
- Documents are limited to 256 KiB. Secret-like keys must be absent, empty, or
  `REDACTED`. Raw payload references belong in protected storage, not contracts.
- Deterministic serialization is UTF-8 JSON with keys sorted, no insignificant
  whitespace, finite numbers only, and no Unicode escaping requirement. Use
  `contracts.canonical_json` for hashes and fixture comparisons.
- Validation rejects before persistence or downstream calls. Stable error codes
  distinguish structural schema errors from semantic hard-gate failures.
- No contract authorizes live execution. Analysis requests, verdicts, and theses
  pin `SHADOW`, `MT5_DEMO`, and `live_execution=false`.

## Contract-specific decisions

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
