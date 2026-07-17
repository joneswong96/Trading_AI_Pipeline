# Project A Pine Wire V1 design note

Owned source: `indicators/pine/snr_dashboard_project_a_v1.pine`

Pine language: v6

Project A version: `v1.0.0-project-a-wire-shadow`

Immutable export provenance:
`2389d4cf29701bf79a1c349a872988bf3216a3d7`,
blob `02f5ac79b22af8819e27b8d5b0924d748ea69ad8`.

## Boundary

`Enable Project A shadow alerts` defaults to false. Emission additionally
requires XAUUSD, the 1-minute chart, a confirmed realtime bar, a producer fact
change, and a new local emission fingerprint. All messages state `SHADOW`,
`MT5_DEMO`, and `live_execution=false`.

The active output is `PROJECT_A_WIRE_EVENT` version `1.0`. Pine owns:

- producer event/correlation identifiers;
- `occurred_at` from the closed 1-minute bar;
- honest `emitted_at` from `timenow` at actual alert construction;
- producer profile/version diagnostics;
- XAUUSD/1m execution-safety declarations; and
- observed SNR/expansion facts.

Pine does not create `received_at`, receipt IDs, raw-byte hashes, canonical
hashes, canonical IDs, validation decisions, dedupe results, or persistence
records. `producer_checksum` is `null`; trusted Python ingress owns SHA-256.

## Allowed events

The corrected producer has two active classes:

- `TELEMETRY / SNR_UPDATE` or `EXPANSION_UPDATE`;
- evidence-supported `SETUP_CANDIDATE / SETUP_CANDIDATE`.

A Setup Candidate requires exactly one new expansion direction from the
published expansion detector and an eligible SNR on the corresponding side
from the published level engine. Simultaneous up/down expansion is ambiguous
and fails closed to telemetry. No latest-event tie-break, ATR proximity, HPA
threshold, HPA concurrence, wick/body pattern, break buffer, body ratio,
momentum count, expiry duration, or lifecycle priority participates.

## HTF and Analysis Ready

The immutable source has no authoritative HPA input. The producer therefore
emits empty HPA and momentum arrays. It neither labels developing HTF evidence
confirmed nor uses it for readiness.

The producer emits no `ANALYSIS_READY`, rejection-ready, strong-break-ready,
invalidation, or expiry event. Those semantics require separately ratified
evidence and are not inferred from the retired Event 0.2 model.

## Legacy behaviour

Only marked Project A blocks and the version/header note differ from the
immutable export. The active block owns no visual or trading operation. Static
provenance tests prove the remaining legacy bytes retain the recorded SHA-256.
TradingView compile and before/after visual parity remain Runtime Activation
Gates.
