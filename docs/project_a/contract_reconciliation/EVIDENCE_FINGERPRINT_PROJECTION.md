# Evidence fingerprint projection

Status: **Implemented in the reader-only Session 0 foundation; writers disabled**

## Purpose

The evidence fingerprint answers one question: “Would this canonical event give
the analysis pipeline materially new trading evidence for this setup?” It is not
an event identity, raw-content hash, receipt idempotency key, transport retry key,
or proof of authenticity.

Projection/version name: `project-a-evidence/1.1`.

## Exact projection and ordering

Session 0 reader code builds this ordered logical object. Keys appear in this order before
canonical JSON serialization; the serializer also sorts object keys, so ordering
is deterministic even if a map implementation does not preserve insertion order.

1. `projection_version`
2. `setup_id`
3. `event_class`
4. `event_type`
5. `path`
6. `hypothesis`
7. `snr`: `identity`, `type`, `low`, `high`, `side`
8. `hpa`: fixed timeframe order `1m`, `5m`, `15m`, `30m`; each item contains
   `classification`, `bar_id`, `bar_close`, and `confirmation_state`
9. `momentum`: fixed ratified timeframe order; each item contains `timeframe`,
    `classification`, `direction`, `bar_id`, and `bar_close`
10. `rejection`: reaction identity/classification, observed bar/time, and measurements
11. `break`: direction, level/price, observed bar/time, identity, and measurements
12. `invalidation`: rule identity, level, observed value, bar/time, and reason
13. `expiry`: window identity, basis, start, end, and reason
14. `entry_window`: window identity, transition (`OPEN`/`CLOSED`), effective time,
    and reason
15. `trigger`: `identity`, `price`, and `evidence_time`
16. `geometry`: `entry`, `sl`, `tp`, `rr`, and direction

This is the exhaustive semantic list. Event-specific sections use `null` when
not applicable, not omission. Lists use the fixed timeframe order, never source
JSON order. Only ratified HPA, momentum, rejection, break, invalidation, expiry,
entry-window, and geometry fields may enter their sections. An extension field
does not become evidence merely because a producer sends it.

## Exact exclusions

The projection excludes `event_id`, `producer_event_id`, `canonical_event_id`,
`receipt_id`, correlation/causation IDs, receipt timestamp, emitted timestamp,
canonicalization timestamp, source/producer hash, canonical payload hash, raw
bytes hash, producer checksum/diagnostics, producer/engine/provenance labels,
validation prose, disposition audit details, transport headers/method/peer data,
content type, local/database/artifact paths, dead-letter/retry/outbox metadata,
model or renderer metadata, arbitrary payload extensions, optional 5s Arrow,
and spread.

Spread remains a deterministic eligibility/safety gate. A changed spread may
change release eligibility at the gate that owns the measurement, but it does
not assert new market/setup evidence and does not change this fingerprint.

## Missing and null policy

- A field required by the event type or a ratified rule that is missing, null,
  ambiguous, non-finite, or unnormalizable rejects canonical release. It never
  hashes as an empty string or guessed value.
- A section that is semantically inapplicable is the JSON literal `null`.
- A contract-defined optional value inside an applicable section is explicitly
  `null` only when the contract says “unknown” is legal and distinct from absent.
- Unknown extension fields reject. The small typed allowlist is retained in
  raw/canonical audit but never read by authority or included in this projection.
- Provisional HTF evidence must include `confirmation_state: PROVISIONAL`, bar
  identity, and close time. The recommended default is to disallow provisional
  evidence for canonical Analysis Ready events.

## Numeric normalization

1. Reject JSON booleans, NaN, infinity, non-numeric strings, and values outside
   the owning contract's bounds.
2. Parse JSON numbers with a decimal implementation, not binary float.
3. Normalize every accepted number to finite base-10 decimal form; trailing
   zeroes are removed and negative zero becomes zero. No unratified point-size
   conversion, measurement scale, or rounding rule is introduced here.
4. Serialize normalized numeric values as canonical base-10 strings in the
   projection. Scientific notation, leading plus, and locale separators are
   forbidden. Thus `2415`, `2415.0`, and `2415.00` resolve to the same normalized
   numeric value when all are valid representations.

The exact scales for currently unratified HPA/break/rejection measurements are
blocked on those trading decisions; the projection cannot invent them.

## Timestamp normalization

Parse an allowed UTC input and serialize it as `YYYY-MM-DDTHH:MM:SS.mmmZ`, with
exact millisecond precision. Event V1 rejects sub-millisecond input rather than
rounding it. Naive/local-offset values and leap/invalid dates fail closed.
Top-level `occurred_at` is excluded; event-specific evidence times are included.
Receipt/emission/canonicalization clocks are excluded.

## Hash and serializer ownership

Trusted Python Session 0 reader code owns projection construction, canonical UTF-8 JSON
serialization, and `SHA-256` of those exact bytes. The stored form is
`sha256:<64 lowercase hexadecimal characters>` and is bound to
`project-a-evidence/1.1`. Pine does not compute or authorize this value. Known
vectors and cross-process tests cover Unicode, key order, numeric equivalence,
null/inapplicable sections, and timestamp normalization.

## Dedupe examples

These changes do **not** redispatch because the projection is unchanged:

- a new event ID, receipt ID, receipt/emission time, retry count, or transport
  header for the same evidence;
- JSON member reordering or equivalent numeric lexical form;
- a changed producer checksum, engine build string, local artifact path, audit
  detail, optional 5s Arrow, or unrelated extension field;
- the same setup/evidence received after restart; or
- a changed spread measurement alone. The eligibility gate may close/reopen, but
  analysis needs an explicit entry-window transition to represent that change.

These are genuine retriggers because at least one included semantic value changes:

- a newly confirmed rejection with a different reaction/bar identity;
- first confirmed break, a new break confirmation bar, or changed ratified break
  evidence;
- structural invalidation or expiry evidence;
- an explicit entry-window `OPEN` or `CLOSED` transition;
- a ratified HPA/momentum classification tied to a new confirmed bar;
- changed SNR identity/bounds/side, trigger identity/price, hypothesis/path, or
  actionable candidate geometry; or
- a new setup ID.

Repeated provisional HTF updates require a reconciliation event model and must
not masquerade as immutable confirmed evidence.

## Replay compatibility

Frozen Event 0.2 fixtures continue through the old replay unchanged. A new
adapter fixture records the source contract/version, projection version,
normalization result, fingerprint, and dedupe outcome. Historical records with
insufficient fields cannot be assigned a fabricated v1 fingerprint; they remain
readable under legacy full-payload behavior or are explicitly
`EVIDENCE_PROJECTION_UNAVAILABLE`. Replay uses isolated dedupe state and recorded
event clocks so repeated runs are deterministic.
