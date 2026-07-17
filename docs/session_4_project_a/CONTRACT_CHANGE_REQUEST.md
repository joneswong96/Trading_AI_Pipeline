# Contract change request for Session 0 review

No frozen file was modified. Current implementation remains contract-valid.

## Problem

The Session 4 brief requires explicit evidence references and a modifiable/
verifiable invalidation condition, but `AI_VERDICT_SCHEMA_V1` has neither an
`evidence_refs` field nor an `invalidation` field. `reason_codes` and `rationale`
are the only available carriers.

## Current adapter solution

- Evidence references use `reason_codes` named
  `EVIDENCE_<NORMALIZED_EVIDENCE_ID>`. Deterministic code rejects missing or
  unknown codes. This safely solves V1 evidence-reference verification without
  schema widening.
- Invalidation is reviewed as evidence/rationale only. The model cannot return a
  structured corrected invalidation value, and deterministic code cannot verify
  or authorize one. Session 4 therefore does not claim that MODIFY can change
  invalidation under V1.

## Proposed future change

Session 0 should consider a coordinated new verdict version containing:

```json
{
  "evidence_refs": ["xauusd_1m"],
  "invalidation": 2414.5
}
```

- `evidence_refs`: required, unique, bounded strings for all verdicts.
- `invalidation`: finite positive number for APPROVE/MODIFY and null for
  REJECT/EXPIRED, with direction/point-size/support checks in semantic validation.

Although the fields look additive, strict `additionalProperties:false` readers
reject them, so rollout requires a new registered version, parallel reader,
fixtures, replay, Session 5 mapping, security review, and rollback drill.

## Evidence an adapter cannot fully solve it

The evidence-code convention is safe but less explicit. No contract-valid adapter
can carry a numeric corrected invalidation because adding it fails the frozen
schema and hiding it in prose would make deterministic validation impossible.

## Impact and rollback

Affected: Session 3 evidence vocabulary, Session 4 prompt/post-gates/audit,
Session 5 thesis compiler, shared fixtures and replay. Rollback keeps V1 and the
reason-code convention; it must reject structured invalidation changes rather
than silently drop them.
