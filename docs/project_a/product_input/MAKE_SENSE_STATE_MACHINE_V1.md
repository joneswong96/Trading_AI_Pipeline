# Project A Make-Sense State Machine V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

The state family, qualitative maturity mapping, B-to-A capture trigger,
exactly-once concept and `FRESHNESS_POLICY_V1.md` thresholds are approved.
Liquidity distance/near-touch follows `LIQUIDITY_DISTANCE_POLICY_V1.md`.
Expansion speed, exhaustion, E1/E2 TTL and structure rules remain pending and
fail closed.

Purpose: build a deterministic numeric whole-picture story before final review or
notification. This document does not activate a runtime transition.

## 1. General invariants

- One `setup_id` owns one lifecycle. Reset, expiry or invalidation closes it; a
  later setup receives a new ID.
- State is rebuilt deterministically from append-only records. No LLM response
  creates, repairs or suppresses a source fact.
- All required evidence must identify its authority, source bar, confirmation
  status and freshness.
- Freshness is evaluated exactly under `FRESHNESS_POLICY_V1.md`; it never extends
  or replaces signal validity/TTL.
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

1. A valid, eligible Liquidity V2 level is in active `IDLE` or `APPROACH` and
   has an approved distance result. `APPROACH` (`0.25 < distance_atr <= 0.50`)
   may support this state; `FAR` cannot establish it from distance.
2. Expansion V3 movement is directed toward that same level under its side-aware
   rule, with a compatible Scanner quality observation when available.
3. Confirmed 5m standard MACD supplies setup context. Its direction need not be a
   universal veto, but any conflict is explicit.
4. There is no deterministic invalidation: broken/expired level, expansion in the
   opposite direction, stale required bar, setup expiry, source conflict, or
   failed identity/integrity gate.

E1 may strengthen B-building evidence, but it is not mandatory and does not by
itself promote the story.

### `B_TO_A_CANDIDATE`

All of the following are required:

1. Liquidity is `HIT`, has source-confirmed sweep/reaction evidence, or is
   `NEAR_TOUCH` under `LIQUIDITY_DISTANCE_POLICY_V1.md`. NEAR_TOUCH may
   contribute only with fresh Expansion toward the tracked level, fresh 5m setup
   evidence, required 1m reaction/weakening, approved Renko maturity, eligible
   level identity and no deterministic invalidation. It is not HIT or reaction
   proof.
2. Expansion is mature, weakening, too extended, or has a numeric reaction fact.
   Scanner quality alone is insufficient.
3. Renko has E2 or stronger maturity evidence in the intended direction. E1 is
   not a prerequisite.
4. Confirmed 1m MACD has weakening or flip evidence compatible with the intended
   reaction.
5. Critical candidate inputs are within their approved maximum ages, retain their
   actual freshness status, and are lineage-complete. Context status is recorded;
   stale or missing DXY, 15m/30m MACD or 4H/D/W structure does not reverse or
   silently block the candidate, but it caps the final grade at B. `AGING` is
   never relabeled `FRESH`.
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
   conflict threshold. Stale or missing DXY caps grade at B, so it cannot support
   grade-A confirmation. There is no universal DXY veto.
7. `entry_price`, `stop_loss_price`, `take_profit_price`, invalidation rule and
   `valid_until` are complete and valid.
8. The complete evidence bundle passes identity, freshness, alignment and hash
   integrity checks.

A matching confirmed Sniper FIRE with receipt age no greater than 15 seconds may
enter `A_CONFIRMED` directly from `B_TO_A_CANDIDATE` when the XAU, 1m, 5m and
bundle GO gates also pass. Without it, an otherwise A-eligible result enters
`WAITING_5S_ENTRY`.

### `WAITING_5S_ENTRY`

The whole-picture thesis and Renko Main satisfy the A requirements, but an
eligible matching Sniper FIRE has not yet arrived.

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

## 3. Approved qualitative transition table

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
| `B_TO_A_CANDIDATE` | `A_CONFIRMED` | Same A gates pass and an eligible matching FIRE is already bound |
| `WAITING_5S_ENTRY` | `A_CONFIRMED` | A new confirmed matching Sniper FIRE arrives within 15 seconds and all final GO freshness gates pass |
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

## 5. Freshness and market-closed effects

- `STALE`, `MISSING`, `CLOCK_INVALID`, `SOURCE_UNAVAILABLE`, or
  `MARKET_CLOSED` critical evidence blocks `A_CONFIRMED`, GO, every writer and
  every order action. `PROVISIONAL` critical evidence also cannot establish A or
  GO.
- Before an actionable candidate, transient missing/source-unavailable evidence
  yields `C_INSUFFICIENT`. A setup that loses temporal validity becomes
  `EXPIRED`; deterministic identity, clock or integrity failure may instead be
  `INVALIDATED`. The transition records the exact authority and reason.
- `AGING` remains usable only for gates expressed as maximum-age checks. A gate
  that explicitly requires `FRESH` rejects it.
- Stale or missing DXY, 15m/30m MACD, or 4H/D/W structure caps final grade at B;
  it does not reverse direction. SR MTF visual context cannot override structured
  evidence.
- During `MARKET_CLOSED`, there is no B-to-A, A, waiting-entry, GO, provider
  review for a new actionable setup, or writer action. Historical bars are
  `CONTEXT_CARRY_FORWARD` only.
- Reopen requires a new current observation, a new confirmed 1m closed bar and
  source health/freshness verification. A pre-closure setup is never
  automatically revived.

## 6. Direction semantics

The intended trade direction is the reaction direction away from the relevant
liquidity level, not automatically the direction of the incoming expansion.
Every transition records both `expansion_direction` and `setup_direction` so an
opposite/reversal relationship is explicit rather than inferred from side names.

Liquidity distance uses movement direction separately: ASK/resistance expects
Expansion `UP`, while BID/support expects Expansion `DOWN`. If movement is away,
distance remains context but cannot promote APPROACH or NEAR_TOUCH. Zero requires
HIT/intersection evaluation; negative signed distance is
`CROSSED_PENDING_CLASSIFICATION`. No distance zone independently establishes
`A_CONFIRMED`, `WAITING_5S_ENTRY`, GO, reversal or trade direction.
