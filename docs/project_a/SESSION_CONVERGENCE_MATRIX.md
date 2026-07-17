# Project A offline session convergence matrix

Status owner: Session 0 Integration Lead
Authoritative starting integration: `project-a/integration-v1` at
`c0bea3b726a1f83c1c42c8a5c992fb1128b04db9`

Offline convergence status: `COMPLETE`; runtime activation gates remain pending.

This is the only convergence status document for Sessions 1–5. Offline
integration acceptance is separate from the runtime activation gates recorded
in `RUNTIME_ACTIVATION_GATES.md`. Missing live evidence does not block a
disabled offline candidate unless it changes legacy behaviour or relies on an
unratified trading semantic.

## Session 1 — Pine sensor

| Field | Status |
|---|---|
| Original branch / candidate | `project-a/session-1-pine-v1` / `2389d4cf29701bf79a1c349a872988bf3216a3d7` |
| Accepted findings | Source provenance must be immutable; Pine must emit producer-owned Wire Event V1 fields only; OFF must preserve legacy behaviour and emit no Project A event; immutable readiness requires confirmed HTF evidence; unratified HPA, ATR, rejection, break, momentum, and expiry rules cannot act as hard gates. |
| Exact correction scope | Regenerate from immutable committed/exported source; remove `received_at` and canonical-hash ownership; default OFF; separate provisional developing-HTF telemetry; disable the listed unratified semantics; do not invent final Analysis Ready without authoritative HPA/AOI evidence. |
| Correction branch | `project-a/session-1-pine-v1-correction` |
| Final correction SHA | `00f4b40bf4a6f42926b395942b845b1443b5ed8c` |
| Focused tests | Artifact validator `4/4 PASS`; `py -3.11 -m pytest tests/test_project_a_pine_sensor.py -q` → `12 passed`; Pine + Event V1 + frozen V0.2 + replay → `179 passed`; compileall and pip check passed. Immutable source blob `02f5ac79b22af8819e27b8d5b0924d748ea69ad8`; preserved legacy SHA-256 `4840f60cb1b4b034304e23d92ba3c40df4e45fbf2abc4b6f51adc2a250b1ca78`. |
| Offline acceptance | `OFFLINE_ACCEPTED_RUNTIME_GATE_PENDING` |
| Integration | `INTEGRATED` at `5848019431df336cea4c3f18b2a95372b49a6140` |
| Runtime Activation Gate | Pine compile, visual parity, and representative rejection/break/lifecycle evidence. |
| Rollback | `git revert -m 1 5848019431df336cea4c3f18b2a95372b49a6140` |

## Session 2 — Ingest, state, and outbox

| Field | Status |
|---|---|
| Original branch / candidate | `project-a/session-2-ingest-state-v1` / `634c4ac4e27a3e0de8f77f02ad00a34e8f32aaec` |
| Accepted findings | Durable raw receipt must precede parse/canonical/dedupe; trusted ingress owns actual `received_at`, canonicalization, hashes, dedupe, audit, and persistence; transaction/recovery and lifecycle handling must fail closed; legacy ingress behaviour must remain compatible. |
| Exact correction scope | Align with integrated Event V1 readers; issue trusted receipt context at ingress; durably transact receipt, exact/semantic dedupe, canonical decision, setup state, and Analysis Ready outbox eligibility in `project_a.db`; implement rollback/restart/abandoned/commit-failure handling; use approved semantic projection; implement specified V0.2 lifecycle support/rejections; preserve legacy `/alert`, cooldown, `trading.db`, JSONL, and port 8000; reject 4999; keep V1 endpoint disabled. |
| Correction branch | `project-a/session-2-ingest-state-v1-correction` |
| Final correction SHA | `995a8d51303b3cd8cbbc79a91c4c6a6112e75946` |
| Focused tests | Session 2 runtime/API/V1 → `55 passed`; Event V1 + frozen V0.2 + replay → `167 passed`; exact legacy compatibility set → `66 passed`; targeted migration/integrity/recovery/concurrency/outbox stress → `12 passed`; compileall and pip check passed. |
| Offline acceptance | `OFFLINE_ACCEPTED_RUNTIME_GATE_PENDING` |
| Integration | `INTEGRATED` at `b3d0882e870f285d9123886146f82fbe85b5af28` |
| Runtime Activation Gate | Durable production deployment evidence and later genuine shadow ingress campaign. |
| Rollback | `git revert -m 1 b3d0882e870f285d9123886146f82fbe85b5af28` |

## Session 3 — Capture and bundle

| Field | Status |
|---|---|
| Original branch / candidate | `project-a/session-3-capture-bundle-v1` / `b77c5cd9c5e69fb323d4aac370f3ab5c7b25fe1e` |
| Accepted findings | Bundle requests require trusted canonical/receipt lineage; browser identity is exactly `127.0.0.1:4999`; fallback ports/tabs/symbols/feeds/timeframes/layouts are forbidden; synthetic evidence cannot be represented as real runtime proof. |
| Exact correction scope | Consume trusted Canonical Event V1 or disabled adapter output; bind request/setup/source/canonical/receipt identities; keep `payload.analysis` adapter-versioned; retain expiry/freshness/chronology/hash/idempotency/final-1m rules; label fake PNGs and recorded bundles synthetic; keep real browser paths disabled and fail closed when 4999 is unavailable. |
| Correction branch | `project-a/session-3-capture-bundle-v1-correction` |
| Final correction SHA | `afe593aaac4a6ba4504c6d26abd7e1fcdcadc7d7` |
| Focused tests | `py -3.11 -m pytest tests/session_3_project_a -q` → `59 passed`; Session 3 + Event V1 + frozen V0.2 + replay → `226 passed`; shared capture comparison → `9 passed`; recorded bundle verification `5 artifacts`; deterministic replay reports synthetic-only, browser/network/AI false, release false; compileall and pip check passed. |
| Offline acceptance | `OFFLINE_ACCEPTED_RUNTIME_GATE_PENDING` |
| Integration | `INTEGRATED` at `f2c47cf6588ac7d738b7d8f4c4b49e51f15decb2` |
| Runtime Activation Gate | Approved 4999 profile, real five-timeframe capture, final 1m restoration, and real bundle replay. |
| Rollback | `git revert -m 1 f2c47cf6588ac7d738b7d8f4c4b49e51f15decb2` |

## Session 4 — AI review

| Field | Status |
|---|---|
| Original branch / candidate | `project-a/session-4-ai-review-v1` / `40bc1712dc46247869061aa1e3c56cda91e142dd` |
| Accepted findings | Cached completion cannot bypass deterministic preflight, current expiry, complete audit-chain verification, or request/hash/identity checks; audit persistence failure must withhold verdict; technical failures remain technical. |
| Exact correction scope | Revalidate before cached release; verify final `audit_record_hash`; withhold corrupt/missing/malformed/mismatched cached verdicts; preserve strict single-object JSON, Decimal gates, idempotency/conflict detection, and disabled OpenClaw. |
| Correction branch | `project-a/session-4-ai-review-v1-correction` |
| Final correction SHA | `ff85c7d35784c7d449a720372fe96b1b7063e9ab` |
| Focused tests | `py -3.11 -m pytest tests/session_4_project_a -q` → `110 passed`; Event V1 + frozen V0.2 + replay → `167 passed`; compileall and pip check passed. |
| Offline acceptance | `OFFLINE_ACCEPTED_RUNTIME_GATE_PENDING` |
| Integration | `INTEGRATED` at `a39ae0502e5fb9bc85d0167052c3cb90dee3567c` |
| Runtime Activation Gate | OpenClaw Gateway-only proof, embedded-fallback exclusion, OAuth and auth-expiry handling. |
| Rollback | `git revert -m 1 a39ae0502e5fb9bc85d0167052c3cb90dee3567c` |

## Session 5 — Outputs

| Field | Status |
|---|---|
| Original branch / candidate | `project-a/session-5-outputs-acceptance-v1` / `30a2871ea9bb5a190b9893d59283d33d07bfd797` |
| Accepted findings | Session 4 attestation must be cryptographically/data-bound rather than caller booleans; operation persistence, outcome validation, migrations, retry counters, and disabled renderer defaults require correction; real transports remain disabled. |
| Exact correction scope | Bind canonical request/verdict/Thesis/setup/audit lineage; fix `record_operation`; validate finite typed outcomes, spread, chronology, identity, duplicates/conflicts/order; add migration ledger/checksum and reject partial state; gate fake MT5 by explicit recorded-test profile; fix terminal retry/manual-reset attempts; retain atomic Thesis/renderer task and idempotent at-least-once reconciliation; keep all real transports disabled and legacy Notion Call Log blocked. |
| Correction branch | `project-a/session-5-outputs-acceptance-v1-correction` |
| Final correction SHA | `074d2dcd837b915ffcf6336bd22d5a5e628e4ee2` |
| Focused tests | `py -3.11 -m pytest tests/session_5_project_a -q` → `78 passed`; recorded fake acceptance `28/28`; Event V1 + frozen V0.2 + replay → `167 passed`; compileall and pip check passed. |
| Offline acceptance | `OFFLINE_ACCEPTED_RUNTIME_GATE_PENDING` |
| Integration | `INTEGRATED` at `611d7aed09c49b7a4ae76aa98d85b0cdf1d1b395` |
| Runtime Activation Gate | Telegram pairing/delivery, additive Notion migration/upsert, positive MT5 Demo attestation, renderer smoke tests. |
| Rollback | `git revert -m 1 611d7aed09c49b7a4ae76aa98d85b0cdf1d1b395` |

## Offline integration wave

Session 0 integrated Sessions 1, 2, 3, 4, and 5 in dependency order. The
post-merge focused results were respectively `12`, `55`, `59`, `110`, and `78`
passing tests. Runtime-only evidence remains deferred to the activation gates;
the final repository suite passed with `868 passed, 1 skipped`, complete offline
replay returned `ok=true` with writers disabled, and the frozen, SQLite,
ownership, secret, path, import, configuration, and mixed-EOL gates passed.
