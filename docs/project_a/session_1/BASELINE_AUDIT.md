# Session 1 immutable-source provenance

Date: 2026-07-16 (Australia/Sydney)

Correction branch baseline:
`project-a/session-1-pine-v1-correction`, preserving original candidate
`2389d4cf29701bf79a1c349a872988bf3216a3d7` and merging accepted integration
baseline `c0bea3b726a1f83c1c42c8a5c992fb1128b04db9`.

## Immutable exported source

The correction does not read, edit, or commit Jones's working copy at
`C:/Users/jones.w/One System/snr-rebuild`.

The immutable source artifact is the Pine export already committed in the
original Session 1 candidate:

- commit:
  `2389d4cf29701bf79a1c349a872988bf3216a3d7`;
- path: `indicators/pine/snr_dashboard_project_a_v1.pine`;
- Git blob: `02f5ac79b22af8819e27b8d5b0924d748ea69ad8`;
- legacy Session B surface after removing the marked Project A blocks and
  restoring the original version/header:
  `sha256:4840f60cb1b4b034304e23d92ba3c40df4e45fbf2abc4b6f51adc2a250b1ca78`.

That committed Git object is the safe immutable exported artifact used to
regenerate the correction. Focused tests read the object directly with
`git show`, verify its blob identity, and prove the corrected file strips back
to the same legacy SHA-256. The current dirty external `snr-rebuild` checkout
is not provenance and is not touched.

## Preserved legacy boundary

The immutable source is an indicator, not a strategy. Its title, imports,
legacy calculations, plots, background, drawings, inputs, and 4-by-29
diagnostic table remain byte-identical after removing only the marked Project A
input and event blocks and restoring the original header.

The Project A feature remains default OFF. The active Project A block adds no
plot, line, box, label, table, background, order, transport, or broker action.
OFF therefore emits no Project A event. Live visual parity remains a Runtime
Activation Gate and is not claimed by offline tests.

## Findings applied

The original Event 0.2 producer and its unratified readiness model are retired.
Its output call is removed and its HPA, proximity, rejection, break,
invalidation, and expiry authority gates are fixed false.

The active producer emits Wire Event V1 facts only. It does not own
`received_at`, receipt identity, raw/canonical hashes, canonicalization, dedupe,
audit, persistence, geometry, or final Analysis Ready semantics.

No authoritative HPA/AOI readiness algorithm exists in the immutable source.
Accordingly:

- HPA and HTF momentum evidence arrays are empty;
- no developing HTF value is used for immutable readiness;
- an unambiguous new published expansion toward an eligible published SNR may
  emit only `SETUP_CANDIDATE`;
- ambiguous or otherwise incomplete evidence remains telemetry;
- no rejection-ready, break-ready, lifecycle, expiry, or Analysis Ready event
  is produced.
