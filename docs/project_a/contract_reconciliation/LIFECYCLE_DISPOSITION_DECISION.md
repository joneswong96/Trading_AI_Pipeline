# Lifecycle and disposition decision

Status: **V0.2 frozen; V1 reader-only fail-closed ruling implemented**

## Frozen Event 0.2 ruling

The schema enum is broader than the combinations whose meaning was ratified.
Structural validity is therefore necessary but not sufficient for state-machine
acceptance.

| Event class | Event type | Required disposition | V0.2 processing |
|---|---|---|---|
| `ANALYSIS_READY` | `SNR_REJECTION_READY` / `SNR_BREAK_READY` | `ACCEPTED` when all frozen and ratified gates pass | Supported; Session 1 assumptions in the decision register are not ratified gates |
| `LIFECYCLE` | `SETUP_INVALIDATED` | `STRUCTURAL_BREAK` with the ratified invalidation reason/evidence | Supported |
| `LIFECYCLE` | `SETUP_EXPIRED` | `EXPIRED` | Supported |
| `LIFECYCLE` | `ENTRY_WINDOW_OPEN` | any V0.2 disposition | Unsupported |
| `LIFECYCLE` | `ENTRY_WINDOW_CLOSED` | any V0.2 disposition | Unsupported |
| `LIFECYCLE` | `THESIS_INVALIDATED` | any V0.2 disposition | Unsupported |

Other schema-valid class/type/disposition combinations are not implicitly
approved by omission. In particular, frozen validation already rejects
`LIFECYCLE` with `ACCEPTED`; substituting `REJECTED`, `INVALID`, or
`STRUCTURAL_BREAK` does not give entry-window or thesis events an honest meaning.

## Exact fail-closed behavior

For an unsupported V0.2 lifecycle event, Session 2 must:

1. retain one immutable raw receipt and its actual receipt metadata;
2. record structural validation separately from processing support;
3. produce stable outcome `UNSUPPORTED_LIFECYCLE_V02` with no coercion;
4. make no setup/thesis state mutation;
5. create no actionable canonical event and no downstream outbox dispatch;
6. retain audit/dead-letter visibility and acknowledge/reject transport according
   to the separately approved retry policy; and
7. reproduce the same outcome on replay without using a different disposition.

This is a Session 2 runtime correction that may proceed after the contract
decision without waiting for Session 1 trading thresholds: implement the
supported-combination allowlist and fail-closed outcome, plus the semantic
fingerprint projection over already validated opaque evidence. It must not alter
the frozen validator or schema in this task.

## Future version semantics

Wire Event 1.0 reports a lifecycle **transition request/evidence**, while
Canonical Event 1.0 reports whether Session 2 applied it. Do not overload one
`disposition` word for both producer intent and trusted processing outcome.

The reader foundation never permits a V1 lifecycle state mutation unless symbol,
AOI, SNR identity, hypothesis, and setup origin produce a verified canonical
`setup_id`. Missing identity yields `REJECTED / MISSING_CANONICAL_SETUP_IDENTITY`,
`canonical_document=null`, `state_mutation_allowed=false`, and
`dispatch_allowed=false`, while retaining the trusted-ingress raw hash/reference
and processing audit without entering canonical dedupe. Durable raw retention is
Session 2 ingress ownership. Caller-supplied, foreign, receipt-, retry-, machine-, random-, or
contradictory setup identities yield `INVALID_CANONICAL_SETUP_IDENTITY`. Receipt,
transport, retry, machine, or random values never enter derived setup identity.
Even a valid derived setup ID authorizes no mutation until fresh point-of-use
verification binds it to the exact bytes, receipt context, current committed
transaction, and `STATE_MUTATION` action.

The future contract should explicitly define:

| Event | Producer meaning | Canonical transition | Required evidence/owner |
|---|---|---|---|
| `SETUP_INVALIDATED` | Setup evidence crossed its ratified structural invalidation | non-terminal/terminal state as Jones defines; `APPLIED` or stable rejection | Structural level, observed value/time, causation; authorized setup producer |
| `SETUP_EXPIRED` | Ratified setup validity window ended | setup to `EXPIRED`; `APPLIED` | Window basis, start/end, evaluation time |
| `ENTRY_WINDOW_OPEN` | Entry eligibility became open | setup to `ENTRY_WINDOW_OPEN`; `APPLIED` | Ratified gate snapshot and window identity |
| `ENTRY_WINDOW_CLOSED` | Previously open window closed | setup to `ENTRY_WINDOW_CLOSED`; `APPLIED` | Close reason, prior window identity, causation |
| `THESIS_INVALIDATED` | A downstream thesis, not merely Pine setup, became invalid | thesis lifecycle transition; `APPLIED` | Thesis/version identity and authorized downstream source |

Canonical processing status should have an explicit vocabulary such as
`APPLIED`, `DUPLICATE`, `REJECTED_INVALID_TRANSITION`,
`REJECTED_MISSING_EVIDENCE`, and `UNSUPPORTED_VERSION`. Exact state names and
transition ownership require Jones/Session 0 ratification. `THESIS_INVALIDATED`
must not be emitted by Pine unless a future design gives Pine the current thesis
identity and authority; the recommended owner is the deterministic downstream
thesis/lifecycle service.

## Compatibility impact

Session 1 must stop emitting the three unsupported types under Event 0.2 and may
emit only the supported invalidation/expiry forms after their trading semantics
are ratified. Session 2 must reject unsupported combinations even when JSON
Schema accepts their enum values. Future writers require the new wire version;
future state transitions are not backported. Old fixtures remain readable, and
new negative fixtures must cover each unsupported V0.2 combination before any
runtime correction is promoted.
