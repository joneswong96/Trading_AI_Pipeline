# Event field ownership matrix

Status: **Proposed for Wire Event 1.0 / Canonical Event 1.0**

“Hashed” below identifies the authoritative preimage: **W** wire/raw bytes,
**C** canonical payload, **E** evidence projection, **D** diagnostic only, and
**No** mutable audit metadata. No field is digitally signed in this proposal.
“Dedupe” distinguishes exact/content (`C`) from semantic (`E`) decisions.

| Field / group | Producer | Trusted owner | First creation | Hashed | Dedupe | Evidence ID | Enrichable | Replay behavior |
|---|---|---|---|---|---|---|---|---|
| `wire_schema_version` | Pine/system producer | Session 0 contract; S2 validates | Producer | W,C | route | No | No | Preserve exact value |
| `producer_event_id` | Pine/system producer | Producer; S2 uniqueness check | Producer | W,C | ID | Excluded | No | Preserve; never regenerate |
| `setup_id` | Pine/setup producer | Producer; S2 validates continuity | First setup evidence | W,C,E | C,E | Included | No | Stable across lifecycle |
| `correlation_id` | Producer | Producer; S2 validates | Setup/correlation start | W,C | C | Excluded from E | No | Preserve end to end |
| producer `causation_id` | Producer | Producer; S2 validates reference | Producer | W,C | C | Excluded from E | No | Preserve as producer link |
| `occurred_at` | Producer | Producer; S2 normalizes/validates | Evidence occurrence | W,C,E | C,E | Included | Representation only | Use recorded value |
| `emitted_at` | Producer | Producer | Wire emission | W,C | No | Excluded | No | Preserve; policy clocks may inspect |
| `producer` / `engine` / `provenance` | Producer | Producer; S2 allowlist | Producer | W,C | C where policy needs | Excluded | No | Preserve |
| symbol / venue / point size | Producer | S2 verifies against profile | Producer | W,C; symbol may E | C | SNR/geometry normalization context; symbol is setup scope | Verified canonical annotation may accompany, not overwrite | Preserve both claim and verification |
| base timeframe | Producer | S2 validates | Producer | W,C,E | C,E | Included where event evidence uses it | No | Preserve |
| `event_class` / `event_type` | Producer | S2 validates supported combination | Producer | W,C,E | C,E | Included | No | Unsupported fails closed |
| `hypothesis` / `path` | Producer | S2 validates ratified semantics | Producer | W,C,E | C,E | Included | No | Preserve or reject |
| SNR identity/type/bounds/side | Producer | Producer semantics; S2 shape/normalization | Producer | W,C,E | C,E | Included | Representation only | Deterministically normalize |
| HPA classifications and bar IDs | Producer | Producer after Jones ratification; S2 validates | Producer | W,C,E | C,E | Included when ratified | No semantic enrichment | Confirmed/provisional status preserved |
| timeframe momentum and bar IDs | Producer | Producer after Jones ratification; S2 validates | Producer | W,C,E | C,E | Included when ratified | No semantic enrichment | Fixed TF order |
| rejection evidence | Producer | Producer after Jones ratification; S2 validates | Producer | W,C,E | C,E | Included | No | Missing required evidence rejects |
| break evidence | Producer | Producer after Jones ratification; S2 validates | Producer | W,C,E | C,E | Included | No | Preserve measurements and identity |
| invalidation / expiry evidence | Producer or authorized lifecycle service | S2 transition validator | Event producer | W,C,E | C,E | Included | S2 may add evaluation result, not evidence | Replay transition deterministically |
| entry-window transition | Authorized future producer | S2 state authority | Producer | W,C,E | C,E | Included | S2 adds applied/rejected result | Unsupported in V0.2 |
| trigger identity / price | Producer | Producer; S2 numeric validation | Producer | W,C,E | C,E | Included | Representation only | Canonical decimal form |
| actionable candidate geometry | Producer/authorized compiler, subject to future design | S2 deterministic gates | Producer | W,C,E | C,E | Included | Cannot be inferred | Direction/RR checks replayed |
| `optional_5s_arrow` | Pine | Producer | Producer | W,C | C only if content audit | Excluded | No | Preserve diagnostic, ignore for E |
| producer checksum metadata | Producer | Untrusted diagnostic | Producer | D,C | No | Excluded | No | Preserve result and comparison |
| raw wire bytes | Transport producer | S2 | Receipt | raw hash | exact | Excluded | Immutable | Replay exact bytes when retained |
| `receipt_id` | — | S2 | Raw receipt | C | exact receipt | Excluded | No | Preserve; never regenerate for historical record |
| `received_at` | — | S2 ingest clock | Raw receipt | C | No | Excluded | No | Use recorded actual receipt only |
| transport method/content type/peer-safe metadata | — | S2 | Receipt | No | No | Excluded | Yes, append-only audit | Preserve if recorded; no dispatch effect |
| `raw_bytes_hash` | — | S2 | Receipt | self-excluded | exact | Excluded | No | Recompute from retained raw bytes |
| `canonical_schema_version` | — | Session 0 contract; S2 writes | Canonicalization | C | route | Excluded | No | Preserve |
| `canonical_event_id` | — | S2 | Canonicalization | C | ID | Excluded | No | Stable persisted identity |
| canonical `causation_id` | — | S2 | Canonicalization/release | C | C | Excluded | No | Downstream points here |
| validation status/reason | Producer may propose only | S2 | Validation | C | release gate | Excluded | Append-only superseding record, not overwrite | Replay validator version and outcome |
| `canonical_payload_hash` | — | S2 | Canonicalization | self-excluded | C | Excluded | No | Recompute with pinned serializer |
| evidence projection version/fingerprint | — | Session 0 definition; S2 computes | Canonicalization | C; E preimage | E | Fingerprint represents included fields | No | Recompute with pinned projection |
| dedupe disposition / prior event refs | — | S2 | Dedupe | C or audit | release gate | Excluded | Append-only audit | Re-evaluate only in isolated replay state |
| dead-letter metadata | — | S2 | Failure handling | No | No | Excluded | Append-only | Preserve; never convert to evidence |
| retry/outbox attempt data | — | S2/consumer | Dispatch | No | delivery only | Excluded | Yes | Reset only in explicit replay namespace |
| local paths / database IDs / logs | — | Local runtime | Persistence | No | No | Excluded | Yes | Replace with bounded artifact references if exported |
| spread measurement | Verified ingest/capture source, not Pine unless measured | Deterministic safety gate owner | Measurement boundary | C | Eligibility only | Excluded | New measurement may re-evaluate eligibility but not evidence fingerprint | Preserve value, unit, source, time |

## Consequences

- Pine cannot populate trusted `received_at`, validation disposition, canonical
  hash, canonical event ID, receipt ID, or dedupe result.
- Session 2 cannot rewrite producer evidence to make it valid. Its enrichments
  are separate trusted fields or audit records.
- Exact duplicates, content duplicates, and same-evidence events are observable
  but need not all share one identifier.
- Mutable delivery, retry, transport, and diagnostic data never changes evidence
  identity or causes analysis redispatch.
