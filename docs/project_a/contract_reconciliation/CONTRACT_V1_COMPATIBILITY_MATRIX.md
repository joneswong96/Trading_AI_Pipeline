# Project A Event V1 compatibility matrix

Status: **Reader-first foundation; all V1 writers disabled**

Correction-2 base: `f6b0eab7c03c7c301ae4993b34b7ebdd52978c89`

## Reader and writer status

| Contract | Reader | Writer/runtime endpoint | Trusted receipt | State/dispatch authority |
|---|---|---|---|---|
| Frozen `EVENT_SCHEMA_V0_2` | Enabled, unchanged shape | Existing frozen profile only; no change here | Always `LEGACY_UNVERIFIED`; caller metadata cannot promote it | None from an ordinary read |
| `PROJECT_A_WIRE_EVENT_V1` | Enabled for validation/recorded replay | **Disabled / not implemented** | Forbidden | None; producer evidence only |
| `PROJECT_A_CANONICAL_EVENT_V1` | Shape reader plus receipt processor and point-of-use verifier | **Disabled / not connected to Session 2** | Exact bytes + private-ingress context required | One intended action only after fresh current-transaction verification |
| Unknown/ambiguous family or version | Rejected | Disabled | None | None |

No config selects a V1 writer. `config/project_a.yaml` remains pinned to
`EVENT_SCHEMA_V0_2`, SHADOW, MT5_DEMO, `live_execution=false`, and
`order_placement=false`.

## Deterministic rules

- Reader selection uses the explicit `(contract_family, schema_version)` pair.
  Event 0.2 is the sole exception because its frozen shape predates
  `contract_family`; it is recognized only as `schema_version=0.2` with no family.
- Exact bounded Wire bytes are hashed before UTF-8 decode/strict JSON parse.
  Shape validation and processing results grant no authority. Point-of-use
  verification recomputes receipt, content/semantic hashes, canonical/setup IDs,
  dedupe, validation, permissions, execution profile, and audit from exact bytes
  plus the current receipt transaction. No class, marker, wrapper, `isinstance`,
  copy, pickle, subclass, or caller field is a bearer credential.
- `canonical_content_hash` is SHA-256 over canonical UTF-8 Wire V1 bytes.
  `raw_content_hash` is SHA-256 over exact received bytes.
- Exact receipt dedupe keys `(transport_identity, canonical_content_hash)`, where
  transport identity is a stable provider delivery key and excludes attempt
  metadata. Semantic dedupe uses only `project-a-evidence/1.1`; source/transport metadata,
  checksums, extensions, receipt/emission times, IDs, optional 5s data, and spread
  do not participate.
- Stable `setup_id` is a trusted Python hash over symbol, authoritative AOI/SNR
  identities, hypothesis, and setup origin. Producer event ID, timestamps,
  transport, machine identity, and randomness do not participate.
- Canonical JSON is UTF-8, sorted-key, compact JSON with preserved array order,
  lowercase booleans/null, byte-preserving Unicode (no NFC), and finite normalized
  decimal numbers. Limits are 64 significant digits, 10,000 absolute exponent
  and adjusted exponent, and 2,048 fixed-form characters, checked before render.
  It is a Project A policy, not a claim of RFC 8785 compliance.

## Processing and authority surfaces

| Surface | Meaning | Authority |
|---|---|---|
| Legacy V0.2 read dictionary | Frozen shape/compatibility result | None |
| `ParsedWireEventV1` | Parsed and shape-valid Wire data | None |
| `CanonicalEventV1Document` | Canonical schema-shaped data | None |
| `ReceiptProcessingResultV1` | Auditable receipt outcome, optionally with Canonical data | None |
| `CanonicalVerificationResultV1` | Fresh one-action result bound to exact bytes/context/open committed transaction and generation | One atomic consumption per generation/action |

The replay-only issuer is isolated in `contracts._trusted_ingress` and is not a
public export; a production issuer is absent. Same-process hostile Python is not
an isolation boundary. Future production ingress/dedupe components require a
durable adapter and an appropriate process/security boundary.

## Lifecycle compatibility

| V0.2 event | Read | State mutation | Dispatch | Result |
|---|---:|---:|---:|---|
| `SETUP_INVALIDATED` + `STRUCTURAL_BREAK` | Shape only | No | No | `LEGACY_V02_UNVERIFIED` |
| `SETUP_EXPIRED` + `EXPIRED` | Shape only | No | No | `LEGACY_V02_UNVERIFIED` |
| `ENTRY_WINDOW_OPEN` | Retain raw | No | No | `UNSUPPORTED_LIFECYCLE_V02` |
| `ENTRY_WINDOW_CLOSED` | Retain raw | No | No | `UNSUPPORTED_LIFECYCLE_V02` |
| `THESIS_INVALIDATED` | Retain raw | No | No | `UNSUPPORTED_LIFECYCLE_V02` |

Wire/Canonical V1 can represent explicit entry-window and thesis invalidation
evidence, but no Session 1 writer may emit it and no runtime consumer is enabled.
Missing/null origin, AOI, hypothesis, or SNR identity yields an auditable
`ReceiptProcessingResultV1(REJECTED, MISSING_CANONICAL_SETUP_IDENTITY)` with
`canonical_document=null`. Caller-, receipt-, retry-, machine-, random-, foreign-,
or contradictory setup identities yield `INVALID_CANONICAL_SETUP_IDENTITY`.

## Migration and replay

1. Never mutate or relabel Event 0.2. Frozen schema/fixture byte hashes are pinned
   in the migration fixture and tests.
2. Every ordinary V0.2 read remains `LEGACY_UNVERIFIED`; its producer
   `received_at` is never promoted and caller receipt dictionaries are rejected.
3. `LEGACY_TRUSTED` has no enabled API. A future internal migration adapter must
   bind immutable stored bytes/hash, source identity, deterministic record, and audit.
4. Wire receipt processing hashes and strictly parses exact raw UTF-8 JSON bytes
   before canonical dedupe. Parse/schema rejection remains independent of dedupe
   availability and retains its ingress hash/reference. Durable malformed-receipt
   retention remains a separate Session 2 ingress responsibility. Valid Wire data
   then uses one atomic transaction covering receipt decision, both dedupe
   reservations, eligibility, decision persistence, and commit.
5. Replay may use an explicit replay clock, but it remains audit metadata and
   cannot become historical `received_at`.
6. Migration fixtures are non-production, make no state change, and exercise
   unverified legacy read, V1 receipt processing, exact duplicate,
   metadata-only semantic duplicate, genuine evidence change, and unsupported
   legacy lifecycle retention.

## Fail-closed rules

Unknown/ambiguous versions, malformed/non-UTF-8/BOM/duplicate-key/trailing-data
raw JSON, byte/context mismatch, producer-supplied authority, missing/unavailable
dedupe/transaction failures, unsafe profiles, provisional HTF Analysis Ready evidence, invalid geometry,
non-finite values, reserved/unknown extensions, every trusted-field tamper, missing
lifecycle setup identity, and unsupported V0.2 mutation all fail before dispatch.

## Candidate remediation

- Session 1: rebuild against Wire V1 only after trading semantics/source/HTF
  ratification.
- Session 2: patch/revise to host these readers and trusted canonicalization.
- Session 3: patch canonical input binding and regenerate fixtures.
- Session 4: patch cached-release/request attestation.
- Session 5: patch canonical handoff, identity, and persistence binding.

Approval of this reader foundation does not approve any candidate or writer.
