# Project A proposed Make-Sense State Machine V1

Status: **PROPOSED — JONES APPROVAL REQUIRED**

Purpose: build a deterministic numeric whole-picture story before final review or
notification. This document does not activate a runtime transition.

## 1. General invariants

- One `setup_id` owns one lifecycle. Reset, expiry or invalidation closes it; a
  later setup receives a new ID.
- State is rebuilt deterministically from append-only records. No LLM response
  creates, repairs or suppresses a source fact.
- All required evidence must identify its authority, source bar, confirmation
  status and freshness.
- Port or layout mismatch, stale required evidence, unresolved conflicting
  evidence, missing bundle integrity, or missing risk geometry fails closed.
- DXY is evidence/grade-cap logic, not a universal veto.
- E1 is not required before E2.
- `4999` evidence is never admissible.

## 2. State definitions

### `NO_STORY`

No coherent setup exists. There may be market observations, but no valid
liquidity approach and directed expansion pair has been established.

### `C_INSUFFICIENT`

A possible setup exists, but one or more mandatory B-building facts are missing,
stale, provisional where confirmation is required, contradictory, or identity
invalid. It carries grade C and cannot trigger capture or notification.

### `B_BUILDING`

All of the following are required:

1. A valid, fresh Liquidity V2 level is in `IDLE` with a bounded approach, or in
   `APPROACH`.
2. Expansion V3 is directed toward that level, with a compatible Scanner quality
   observation when available.
3. Confirmed 5m standard MACD supplies setup context. Its direction need not be a
   universal veto, but any conflict is explicit.
4. There is no deterministic invalidation: broken/expired level, expansion in the
   opposite direction, stale required bar, setup expiry, source conflict, or
   failed identity/integrity gate.

E1 may strengthen B-building evidence, but it is not mandatory and does not by
itself promote the story.

### `B_TO_A_CANDIDATE`

All of the following are required:

1. Liquidity is `HIT` or has source-confirmed sweep/reaction evidence. A bounded
   near-touch may qualify only if Jones approves a numeric distance threshold;
   until then, near-touch promotion is disabled.
2. Expansion is mature, weakening, too extended, or has a numeric reaction fact.
   Scanner quality alone is insufficient.
3. Renko has E2 or stronger maturity evidence in the intended direction. E1 is
   not a prerequisite.
4. Confirmed 1m MACD has weakening or flip evidence compatible with the intended
   reaction.
5. Liquidity, expansion, MACD, DXY, Renko and structure inputs needed for review
   are fresh and lineage-complete.
6. No deterministic invalidation exists.

Entering this state is the only V1 production capture trigger.

### `A_CONFIRMED`

All of the following are required:

1. Final verdict is `APPROVE` or `MODIFY`.
2. Final grade is `A`.
3. The Liquidity V2 reaction remains valid.
4. Confirmed 1m MACD supports the intended direction.
5. Renko Main is confirmed in that direction.
6. DXY is `CONFIRM` or `NEUTRAL`, or any conflict is below the approved material
   conflict threshold. There is no universal DXY veto.
7. `entry_price`, `stop_loss_price`, `take_profit_price`, invalidation rule and
   `valid_until` are complete and valid.
8. The complete evidence bundle passes identity, freshness, alignment and hash
   integrity checks.

A matching, fresh Sniper FIRE may enter `A_CONFIRMED` directly from
`B_TO_A_CANDIDATE`. Without it, an otherwise A-eligible result enters
`WAITING_5S_ENTRY`.

### `WAITING_5S_ENTRY`

The whole-picture thesis and Renko Main satisfy the A requirements, but a fresh
matching Sniper FIRE has not yet arrived.

The state output must contain:

- `setup_direction_5m`;
- `confirmation_1m_status`;
- `required_sniper_fire_direction_5s`; and
- a deterministic `cancellation_condition` covering opposite Main/FIRE, thesis
  invalidation, geometry invalidation, evidence staleness and `valid_until`.

This state does not notify a B-to-A entry.

### `INVALIDATED`

The setup is closed by a deterministic invalidation such as level BREAK,
opposite confirmed evidence beyond approved tolerance, invalid geometry,
identity/integrity failure, or explicit cancellation. It is terminal for the
current setup ID.

### `EXPIRED`

The setup is closed because `valid_until`, evidence freshness or an approved
setup lifetime elapsed without a valid entry transition. It is terminal for the
current setup ID.

## 3. Proposed transition table

| From | To | Required transition evidence |
|---|---|---|
| `NO_STORY` | `C_INSUFFICIENT` | Partial liquidity/expansion story exists but mandatory B facts are incomplete |
| `NO_STORY` | `B_BUILDING` | All B-building gates pass on fresh evidence |
| `C_INSUFFICIENT` | `B_BUILDING` | Missing or provisional facts become valid and confirmed |
| `C_INSUFFICIENT` | `NO_STORY` | Candidate evidence disappears without a setup |
| `B_BUILDING` | `B_TO_A_CANDIDATE` | All candidate gates pass; append transition and trigger one bounded capture |
| `B_BUILDING` | `C_INSUFFICIENT` | Non-terminal evidence becomes incomplete or stale |
| `B_TO_A_CANDIDATE` | `B_BUILDING` | Reaction/maturity evidence weakens but setup remains valid and fresh |
| `B_TO_A_CANDIDATE` | `WAITING_5S_ENTRY` | Final verdict/grade, reaction, 1m, Main, DXY, geometry and bundle all pass; matching FIRE absent |
| `B_TO_A_CANDIDATE` | `A_CONFIRMED` | Same A gates pass and a fresh matching FIRE is already bound |
| `WAITING_5S_ENTRY` | `A_CONFIRMED` | A new, confirmed, fresh matching Sniper FIRE arrives before cancellation/expiry |
| Any non-terminal state | `INVALIDATED` | Deterministic invalidation or integrity failure |
| Any non-terminal state | `EXPIRED` | Approved expiry or freshness limit elapses |
| `INVALIDATED` or `EXPIRED` | `NO_STORY` | A new setup ID begins; prior history remains immutable |

There is no automatic transition from `A_CONFIRMED` back to B under the same
setup ID. A material thesis change first invalidates or expires the setup and
requires a new setup ID.

## 4. Evidence conflict and missing behavior

- Missing required data yields `C_INSUFFICIENT` before a candidate exists and
  blocks promotion after it exists.
- A source conflict that could change direction, grade, geometry or validity
  blocks final review until deterministically resolved or invalidates the setup.
- A provisional event may be stored and displayed, but a transition that requires
  confirmation waits for the confirmed reconciliation.
- Duplicate source events do not repeat transitions or captures.
- A transition stores the exact predecessor state ID and the evidence record IDs
  that caused it.

## 5. Direction semantics

The intended trade direction is the reaction direction away from the relevant
liquidity level, not automatically the direction of the incoming expansion.
Every transition records both `expansion_direction` and `setup_direction` so an
opposite/reversal relationship is explicit rather than inferred from side names.
