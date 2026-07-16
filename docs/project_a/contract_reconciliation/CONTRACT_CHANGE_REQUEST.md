# Contract change request: separate Project A wire and canonical events

Request ID: `CR-PA-EVENT-001`

Owner: Project A Session 0

Status: **PROPOSED — Jones decision required; no implementation authorized**

Baseline: `8699c467d0fa72ed54a152c2073043c8b538648c`

## Problem statement

Frozen repository Event 0.2 is a strict envelope, while the Notion Convergence
Contract contains an incompatible flat payload under the same v0.2 label. The
current Pine candidate fills `received_at` with `timenow`, cannot know network
receipt, and claims a canonical-looking SHA-256. Session 2 separately knows the
actual receipt clock and is the trusted validation/canonicalization boundary.
Event 0.2 also exposes lifecycle enum values without ratified disposition/state
semantics, and Session 2's whole-payload fingerprint lets irrelevant metadata
cause redispatch.

An adapter alone cannot give the same immutable strict Event 0.2 object both a
producer timestamp and a different trusted receipt timestamp. Nor can it move
hash/disposition ownership without changing field meaning. Editing Event 0.2 in
place would break its frozen identity and historical replay.

## Frozen V0.2 status

`EVENT_SCHEMA_V0_2`, `contracts/validation.py`, frozen fixtures, and the replay
harness remain unchanged and executable. They become the `LEGACY_EVENT_V0_2`
compatibility profile only after a new contract is implemented. Until then they
remain the sole executable Event 0.2 authority. The flat Notion document is not
an executable alternative.

## Proposed version and compatibility classification

Create two new families:

- `PROJECT_A_WIRE_EVENT_V1` / wire `1.0`; and
- `PROJECT_A_CANONICAL_EVENT_V1` / canonical `1.0`.

This is a **breaking, new-family change**: required fields, trust owner,
timestamp/hash meaning, identity chain, lifecycle semantics, and dedupe behavior
change. It is not an additive Event 0.2 minor change and should not be called only
Event 0.3. Using Canonical Event 0.2 would falsely imply semantic compatibility.

## Impact

### Producer / Session 1

Rebuild emission against Wire Event 1.0. Replace producer `received_at` with
honest `emitted_at`; remove required canonical `payload_hash`; optionally retain
a scoped, explicitly non-authoritative `producer_checksum`. Emit only ratified
evidence/lifecycle semantics, confirmed HTF evidence by default, stable producer
identity, and no validation/dedupe claims.

### Session 2

Retain immutable raw bytes and actual receipt time, add version routing/legacy
adapter, build Canonical Event 1.0, compute raw/canonical/evidence hashes, enforce
the lifecycle allowlist, separate exact/content/semantic dedupe, and release only
accepted new evidence. It may not mutate raw producer payloads.

### Sessions 3–5

Consume canonical rather than producer identity. Session 3 patches compiler
source binding and regenerates bundle fixtures. Session 4 patches cached release
to bind/recheck the current request/canonical chain. Session 5 patches attestation,
thesis/outbox linkage, and persistence handoff. Their frozen request/verdict/
thesis contracts need separate change requests if new fields are required; this
request does not silently widen them.

### Fixtures and replay

Keep every Event 0.2 fixture byte-for-byte. Add wire-valid/invalid, raw-receipt,
canonical-valid/invalid, lifecycle, normalization, hash known-vector, migration,
same-evidence-metadata-change, genuine-retrigger, and rollback fixtures. Replay
must run the frozen V0.2 path and the new dual-read path. Historical records
without actual receipt metadata remain readable but cannot be upgraded by
inventing `received_at`.

## Migration plan

1. Jones ratifies the decisions below and Session 0 publishes executable schemas,
   validators, projection vectors, lifecycle table, compatibility matrix, and
   fixture plan on a separate contract implementation branch.
2. Merge readers before writers. Deploy Session 2 dual-read and store canonical
   output disabled/audit-only first.
3. Demonstrate exact Event 0.2 preservation and explicit convert/reject outcomes
   on recorded data. Back up and migration-test any persistence change.
4. Patch Sessions 3–5 to consume Canonical Event 1.0 and pass offline replay.
5. Rebuild Session 1 from the immutable source baseline and enable Wire Event 1.0
   only in default-off shadow mode.
6. Complete one approved shadow acceptance cycle, then stop old writers. Retain
   Event 0.2 reader/replay support for audit.

## Rollback plan

Stop writers and outbox release first. Restore the prior reader/writer/config set
as one unit. Never relabel Canonical Event 1.0 as Event 0.2. Preserve raw bytes,
receipt metadata, both versioned records, and migration ledger. Roll back database
shape only from a verified backup/down migration after integrity and replay
checks. If no lossless converter exists, stop ingestion and retain newer data
rather than coercing or deleting it.

## Explicit Jones decisions required

Jones must explicitly approve or replace:

1. repository strict Event 0.2 as current executable authority and the future
   historical/superseded marking of the flat Notion v0.2 example;
2. the Wire Event 1.0 / Canonical Event 1.0 family names and version strategy;
3. Pine ownership of `occurred_at`/`emitted_at` and Session 2 ownership of actual
   `received_at`, receipt ID, canonical hash, validation, dedupe, and audit;
4. removal of required canonical `payload_hash` from the producer contract and
   whether an optional diagnostic checksum remains;
5. the V0.2 supported/unsupported lifecycle table and future transition owners;
6. the evidence projection, normalization rules, and metadata-insensitive dedupe;
7. every trading rule in `SESSION_1_SEMANTIC_DECISION_REGISTER.md`;
8. confirmed-only HTF evidence (recommended) or the complete provisional and
   reconciliation model;
9. trigger/candidate geometry ownership and stable setup identity rules;
10. dual-read migration duration, legacy writer stop condition, and retention;
11. any persistence migration; and
12. separate authorization for real adapters and the 20–30 sample campaign.

## Mandatory questions resolved by this request

1. **Preserve Event 0.2 honestly?** Yes, as a legacy producer/read contract with
   its exact field retained but not treated as trusted network receipt.
2. **Can S2 enrich `received_at` while validating V0.2?** It may validate the
   untouched producer object and add actual receipt to a separate receipt/
   canonical record. It may not overwrite the same V0.2 object.
3. **Separate producer schema?** Yes; this is required for a clean future trust
   boundary.
4. **Replacement name?** Wire Event 1.0 plus Canonical Event 1.0, not Event 0.3
   alone and not Canonical Event 0.2.
5. **Required producer `payload_hash`?** No canonical hash. Only an optional,
   explicitly diagnostic producer checksum may remain.
6. **Old fixtures/replay?** Preserve bytes and frozen reader; add explicit legacy
   adapter profiles and never fabricate absent receipt facts.
7. **Contract versus runtime/config?** Field meanings, versions, identities,
   lifecycle, hash preimages, and projection are contract. Retry/storage/tolerance
   behavior is runtime policy; values/ports/paths/enables are config unless they
   define trading evidence.
8. **Jones trading semantics?** All 16 items in the Session 1 register, including
   HPA, rejection, break, proximity, momentum, expiry, invalidation, tie-break,
   identity/geometry, collision priority, and HTF policy.
9. **Independent S2 correction?** Lifecycle allowlist/fail-close and projection
   machinery can proceed after this contract decision, using opaque validated
   evidence until trading semantics are ratified.
10. **Rebuild versus patch?** Rebuild S1; patch/revise S2; patch input/release/
    handoff bindings in S3, S4, and S5 and regenerate their fixtures.

## Not authorized by approval of this document alone

Approval does not modify a schema, validator, fixture, runtime, database, config,
Notion page, candidate branch, or TradingView alert. It does not ratify any
Session 1 trading threshold, enable provisional HTF evidence, approve a candidate
for merge, authorize cherry-pick/rebase/merge, enable OpenClaw/Telegram/Notion/
MT5, authorize live TradingView mutation, promote fixtures, or start shadow
sampling. Each requires the gated implementation/review or explicit authority
identified above.
