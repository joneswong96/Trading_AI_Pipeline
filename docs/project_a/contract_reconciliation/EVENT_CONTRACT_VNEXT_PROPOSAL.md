# Event contract vNext proposal

Status: **Proposed; not executable or ratified**

Proposed families: **Project A Wire Event 1.0** and **Project A Canonical Event 1.0**

## Recommendation and naming

Use a new pair, `PROJECT_A_WIRE_EVENT_V1` and
`PROJECT_A_CANONICAL_EVENT_V1`. Do not call the replacement merely Event 0.3:
one version would hide the producer/ingress trust boundary. Do not call the
second family Canonical Event 0.2: reusing `0.2` would suggest compatibility
with an object whose receipt and hash semantics are changing.

The compatibility profile name for existing records is
`LEGACY_EVENT_V0_2`. These names are proposals only; approval does not register
them or create schemas.

## Two-document model

### Wire Event 1.0

An immutable statement of what a producer knew when it emitted an event. Pine
owns producer identity, producer event identity, `occurred_at`, `emitted_at`,
symbol, timeframe, event class/type, setup/correlation data, and the raw
deterministic trading evidence. It does not contain actual `received_at`, receipt
identity, canonical disposition, trusted canonical hash, retry data, or local
storage paths.

An optional `producer_checksum` may diagnose transport corruption. It must name
its algorithm, byte encoding, and scope, and is never an authentication,
canonicalization, dedupe, or evidence authority. The wire contract must not
require the current canonical-looking `source.payload_hash` if Python is the
trusted hash owner.

### Canonical Event 1.0

A trusted Session 2 record derived from an immutable raw receipt. It binds the
raw receipt, validated wire fields, actual `received_at`, receipt identity,
canonical identity/correlation, validation result, canonical serialization/hash,
semantic evidence fingerprint, dedupe result, and audit/dead-letter references.
Only this document is released to Sessions 3–5.

Canonicalization must not silently repair trading evidence. Normalization is
limited to ratified representations (for example UTC timestamp and canonical
decimal forms). Any semantic change is rejected or explicitly versioned.

## Ownership and identity

The detailed field decision is in `EVENT_FIELD_OWNERSHIP_MATRIX.md`. The identity
chain is:

1. producer creates `producer_event_id`, `setup_id`, `correlation_id`, and an
   optional producer-side `causation_id`;
2. Session 2 creates `receipt_id` on byte receipt and preserves raw bytes;
3. Session 2 creates `canonical_event_id` after successful validation;
4. Session 2 retains both producer and receipt identities rather than replacing
   either;
5. downstream `causation_id` refers to the released canonical event, while audit
   fields retain the complete producer/receipt link.

Identity generation algorithms, collision handling, and maximum lengths are
contract decisions. Storage keys, database sequence values, and retry attempt
IDs are runtime details and cannot replace contract identities.

## Timestamp semantics

| Timestamp | Meaning | Owner |
|---|---|---|
| `occurred_at` | Close/occurrence time of the market evidence | Producer |
| `emitted_at` | Time producer finished/emitted the wire document | Producer |
| `received_at` | Time trusted ingress received the exact raw bytes | Session 2 |
| `canonicalized_at` | Time Session 2 completed canonicalization | Session 2 audit |
| HTF evidence bar close | Identity/close time of each evidence bar | Evidence producer |

All contract timestamps use normalized UTC. `occurred_at` and `emitted_at` may be
equal but may not be substituted for receipt. Runtime stale/future tolerances are
configuration, not timestamp meaning. Historical replay uses recorded timestamps
and an explicit replay clock; it never invents a historical receipt fact.

## Hash semantics

Session 2 computes:

- `raw_bytes_hash`: SHA-256 over the exact received UTF-8 bytes;
- `canonical_payload_hash`: SHA-256 over the exact Canonical Event 1.0 hash
  preimage, excluding its own hash field and any mutable audit/retry fields; and
- `evidence_fingerprint`: SHA-256 over the projection specified in
  `EVIDENCE_FINGERPRINT_PROJECTION.md`.

The executable contract must define each preimage. A JSON object cannot hash a
hash value that is part of itself. A Pine checksum, if present, is recorded as
untrusted diagnostic metadata and does not satisfy any of these fields. No
digital signature is proposed in this pack; a checksum or hash is not a
signature.

## Validation and release sequence

1. Capture raw bytes, receipt clock, transport limits, and `receipt_id` before
   parsing; compute `raw_bytes_hash`.
2. Parse exactly once with duplicate-key, size, UTF-8, finite-number, and secret
   controls; route only an explicit wire version.
3. Validate Wire Event 1.0 shape and semantics without adding trusted fields to
   the producer object.
4. Apply ratified symbol, timestamp, lifecycle, and safety policies. Quarantine
   unsupported or ambiguous input with a stable reason.
5. Normalize only approved representations and build Canonical Event 1.0.
6. Compute canonical payload hash and semantic evidence fingerprint.
7. Evaluate exact-receipt, producer-ID, canonical-content, and semantic-evidence
   dedupe as distinct decisions.
8. Persist raw receipt, canonical event/state transition, and outbox atomically
   where required. Release only an accepted, new-evidence canonical event.

Validation result is Session 2-owned. A producer may report a proposed event
type/reason but cannot declare its own canonical acceptance.

## Backward compatibility and replay

The strict Event 0.2 reader remains unchanged. A legacy adapter:

- validates the original object against frozen Event 0.2;
- preserves the object and its original canonical JSON/hash behavior;
- labels producer `received_at` as `legacy_declared_received_at` in surrounding
  audit metadata, never as trusted receipt;
- uses independently recorded raw-receipt metadata when available;
- emits Canonical Event 1.0 only through an explicit, tested conversion profile;
- refuses conversion when required receipt or semantic evidence cannot be
  established.

Old fixtures remain byte-for-byte readable through the frozen replay. New
migration fixtures must show old raw input, adapter decision, new canonical
output, and rejection cases. If historical raw receipt time is absent, replay
records that fact; a replay clock may test policy but is not persisted as the
original `received_at`.

## Migration options

Recommended option: parallel readers and a wire-writer cutover.

1. Ratify both schemas, validators, projections, lifecycle table, and migration
   fixtures under Session 0 ownership.
2. Deploy Session 2 dual-read with Canonical Event 1.0 output disabled.
3. Prove legacy conversion/rejection and rollback on recorded data.
4. Enable canonical output for accepted Event 0.2 receipts while Pine remains on
   the legacy writer, where honest conversion is possible.
5. Deploy Wire Event 1.0 Pine writer only after Session 1 semantic/HTF rulings.
6. Move Sessions 3–5 readers to Canonical Event 1.0.
7. Stop Event 0.2 writers after one full shadow acceptance cycle; retain its
   reader for audit/replay.

An alternative clean cutover is safer if no real Event 0.2 receipts need
migration, but it gives less rollout evidence. Editing Event 0.2 in place is
rejected.

## Rollback implications

Stop writers before readers. Wire 1.0 can roll back to Event 0.2 only while a
tested old writer is still compatible with the active ingest path. Canonical 1.0
records must never be relabelled as Event 0.2. Preserve raw bytes, both readers,
version tags, receipt metadata, and canonical records. If a newer record has no
lossless down-converter, stop ingestion and retain it; do not coerce it. Database
migration, if later required, needs backup, integrity check, forward/down tests,
and a separate Session 0 approval.

## Contract, policy, and configuration boundaries

Contract changes include family/version names, fields and their meanings,
identity/correlation rules, timestamp/hash preimages, lifecycle vocabulary,
evidence projection shape, required evidence, and wire-to-canonical conversion.

Runtime policy includes raw-storage retention, retry/dead-letter scheduling,
transaction boundaries, stale/future handling behavior, and historical replay
mode. Configuration includes tolerance durations, listener port/path, enabled
symbols, database path, and adapter enablement. A value becomes a trading
semantic contract—not mere configuration—when it determines whether evidence
is rejection/break/readiness, expiry, direction, or actionable geometry.
