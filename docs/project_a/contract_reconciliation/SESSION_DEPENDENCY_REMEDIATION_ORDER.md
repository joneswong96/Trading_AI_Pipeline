# Session dependency remediation order

Status: **Recommended gate order; all candidate promotion remains frozen**

This is a dependency order, not authority to modify, cherry-pick, merge, rebase,
run live tools, or start sampling.

| Order | Gate and required evidence | Owner / candidate disposition |
|---:|---|---|
| 1 | Ratify executable contract authority, Wire/Canonical 1.0 naming, receipt ownership, canonical hash ownership, lifecycle support, and compatibility policy | Jones + Session 0 |
| 2 | Publish an immutable authoritative Pine source baseline: repository URL/path, clean commit, submodule/library versions, exact source SHA-256, uncommitted-diff statement, and reproducible extraction | Jones/Session 0; source only, no strategy promotion |
| 3 | Decide every HPA/readiness/invalidation/expiry/identity item in `SESSION_1_SEMANTIC_DECISION_REGISTER.md`, or remove it from canonical authority | Jones |
| 4 | Decide confirmed versus provisional HTF policy; if provisional, ratify bar identity and reconciliation events | Jones + Session 0 |
| 5 | Rebuild and independently re-review Session 1 against the immutable source, Wire Event 1.0, ratified semantics, known hash/checksum vectors if retained, reload tests, visual parity, and real shadow-safe emission | **Rebuild**, not a narrow patch; old commit remains evidence only |
| 6 | Correct and independently re-review Session 2: dual reader, immutable raw receipt, Canonical Event 1.0, actual receipt time, trusted hashes, supported lifecycle allowlist, semantic projection, restart/transaction/outbox behavior | **Patch/revise candidate architecture**, with new migration fixtures; do not rebuild trading logic |
| 7 | Complete real Session 3 port-4999 evidence: approved single XAUUSD/ICMARKETS/1m tab, full timeframe capture, restore/reverify 1m, identity/freshness negatives, canonical source binding, and replay | **Patch adapter/interface and regenerate fixtures**; live gate separately authorized |
| 8 | Correct and re-review Session 4 cached release: bind cached verdict/release to current canonical request, attestation/hash, recheck expiry and gates immediately before release, and retain Gateway-only/disabled real adapter posture | **Patch**; regenerate bound request/verdict fixtures |
| 9 | Correct and re-review Session 5 handoff/persistence: require Session 4 attestation, bind thesis/output identity to canonical chain, resolve durable persistence/Notion mapping, and preserve independent renderer idempotency | **Patch**; regenerate handoff fixtures, no Notion write yet |
| 10 | Integrate only approved readers-before-writers in dependency order: Session 0 contract readers/migration fixtures, S2 canonicalizer, S3, S4, S5, then S1 wire writer; run frozen and new gates after each step | Session 0 merge owner; order intentionally differs from feature numbering for safe version rollout |
| 11 | Separately authorize and run the genuine 20–30 XAUUSD shadow campaign after all offline, real-adapter-specific, identity, rollback, and no-live-order gates pass | Jones explicit authorization; Session 0/S5 report |

## Independent Session 2 work after the contract decision

Session 2 can implement two corrections without waiting for Jones to choose the
numerical Session 1 rules:

1. a version/type allowlist that rejects unsupported Event 0.2 lifecycle events
   with `UNSUPPORTED_LIFECYCLE_V02`, preserving raw receipt and causing no state
   mutation/dispatch; and
2. the projection engine/known-vector tests using the ratified projection shape,
   treating HPA/momentum/reaction values as validated opaque fields until their
   trading meanings are ratified.

It cannot finalize required-field sets, numeric scales, or release eligibility
for unratified trading evidence.

## Why the downstream split is rebuild versus patch

Session 1's producer timestamps, hash authority, event envelope, readiness
semantics, HTF stability, and source lineage all change at its core emission
boundary, so piecemeal repair would be harder to audit than a rebuild from the
published baseline. Session 2 already has the correct raw-ingress/state/outbox
direction and needs a contract-boundary correction. Sessions 3–5 have useful
isolated architecture but must patch their input binding and regenerate recorded
artifacts; their core capture/reviewer/output responsibilities do not need a full
rewrite based on current evidence.

No existing candidate becomes mergeable merely because this order is accepted.
Each still requires its own independent review and exact promotion gates.
