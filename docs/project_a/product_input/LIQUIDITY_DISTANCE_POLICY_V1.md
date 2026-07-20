# Project A Liquidity Distance Policy V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

Owner: Project A Session 0

Approval: Jones Wong, 2026-07-20 Australia/Sydney

Scope: deterministic Liquidity V2 distance and lifecycle policy only. This
document does not implement a producer, schema, parser, runtime, capture,
provider, writer, TradingView change or external action.

## 1. Authority and semantic boundary

The liquidity authority is `Liquidity Levels V2 — 5m Body × MTF Confluence`,
owner `Jonesy_Wong`, private revision 9 (`LIQ_V2_R9`). Its conventional side
semantics are:

- `ASK`: upper/high/resistance liquidity;
- `BID`: lower/low/support liquidity; and
- neither side directly implies `LONG` or `SHORT` trade direction.

The source payload's legacy bare `price` means `level_price`. It never means
`market_price`. Canonical records use dimensioned names and preserve the source
payload for audit. Liquidity V2 remains `SAVED_NOT_MATERIALIZED`, Product Input
runtime remains disabled, and this policy does not make the producer complete.

Distance normalization authority is the latest confirmed 5-minute ATR(14).
The current-price input is a fresh current XAU market observation from an
explicit approved structured source. AI, screenshots and visual estimation are
not numeric authorities.

## 2. Canonical calculation record

Every calculation retains these values without conflation:

| Field | Requirement |
|---|---|
| `level_id` | Stable identity for exactly one eligible Liquidity V2 level; missing identity blocks promotion |
| `level_side` | Exactly `ASK` or `BID` |
| `level_price` | Finite positive XAU quote value from the Liquidity V2 level |
| `market_price` | Finite positive current XAU quote observation; never copied from the source's bare `price` |
| `signed_distance_price` | Side-aware pre-touch distance defined in section 3 |
| `absolute_distance_price` | `abs(signed_distance_price)` in the same quote unit |
| `point_size` | Explicit approved XAU quote-to-point conversion input, or null when unavailable |
| `distance_points` | `absolute_distance_price / point_size` only when point size is finite, positive and approved; otherwise null |
| `confirmed_5m_atr14` | Latest confirmed 5m ATR(14), finite and greater than zero |
| `distance_atr` | `absolute_distance_price / confirmed_5m_atr14` when all calculation gates pass |
| `distance_zone` | `FAR`, `APPROACH`, `NEAR_TOUCH`, or null when classification is unavailable/pending |
| `liquidity_distance_status` | `AVAILABLE`, `UNAVAILABLE`, `HIT_INTERSECTION_EVALUATION_REQUIRED`, or `CROSSED_PENDING_CLASSIFICATION` |
| `expected_approach_move_dir` | `UP` for ASK; `DOWN` for BID |
| `observed_expansion_move_dir` | Source movement value `UP`, `DOWN`, `FLAT`, or null; never overloaded as trade direction |
| `moving_toward_level` | True for a valid matching movement, false for a valid non-matching movement, null when movement is unavailable/invalid |
| `calculation_observed_at` | Trusted UTC calculation time |
| `market_price_observed_at` | Trusted UTC observation time for `market_price` |
| `atr_source_bar_time` | Latest confirmed 5m ATR source-bar identity with OPEN/CLOSE semantics and close time |
| `market_price_freshness_status` | Status under `FRESHNESS_POLICY_V1.md` |
| `atr_freshness_status` | Status under `FRESHNESS_POLICY_V1.md` |
| `level_freshness_status` | Status of the level evidence under `FRESHNESS_POLICY_V1.md` |
| `missing_fields` / `errors` | Stable fail-closed field and reason records |

`distance_points` does not approve a point-size value or bid/ask/spread source.
Those authorities remain pending. It may be null while the quote-unit and ATR
distances remain auditable.

## 3. Side-aware signed distance and movement

For an ASK/resistance level expected above price:

```text
signed_distance_price = level_price - market_price
expected_approach_move_dir = UP
```

For a BID/support level expected below price:

```text
signed_distance_price = market_price - level_price
expected_approach_move_dir = DOWN
```

For either side:

```text
absolute_distance_price = abs(signed_distance_price)
distance_atr = absolute_distance_price / confirmed_5m_atr14
```

`moving_toward_level=true` only when the observed Expansion movement equals the
side's expected approach movement. A valid opposite or FLAT observation records
`moving_toward_level=false`. Missing, ambiguous or invalid movement records null
and fails any gate that requires movement toward the level.

UP/DOWN describe market movement. They do not mean LONG/SHORT. Absolute
distance may be recorded for audit, but it cannot decide whether movement is
toward the level and cannot override a negative signed distance.

## 4. Calculation gates and unavailable behavior

Before division or zone classification:

1. `level_side` is unambiguously ASK or BID.
2. `level_price` and `market_price` are finite, positive and in matching XAU
   quote units.
3. The market-price source and observation time are explicit.
4. `confirmed_5m_atr14` is finite, greater than zero, confirmed, explicitly
   sourced and in the matching quote unit.
5. The XAU current observation and confirmed 5m ATR status are exactly `FRESH`.
6. Level evidence is eligible, identity-complete and not stale or otherwise
   unavailable.
7. Calculation uses deterministic decimal behavior. Runtime rounding and
   representation must be separately defined before activation.

If ATR is missing, zero, negative, non-finite, provisional, stale, unit-invalid
or source-ambiguous, then `distance_atr=null`,
`liquidity_distance_status=UNAVAILABLE`, and distance cannot promote B-building
or B-to-A. The same fail-closed outcome applies to invalid/missing market or
level price, ambiguous side, mismatched units, invalid identity, or a required
input that is not exactly `FRESH`.

No AI, screenshot, receipt-time substitution or guessed value may repair an
unavailable calculation.

## 5. Exact distance boundaries

The rules are exact and introduce no floating-point tolerance:

| Precondition / normalized distance | Classification | Approved use |
|---|---|---|
| `signed_distance_price < 0` | `distance_zone=null`; `CROSSED_PENDING_CLASSIFICATION` | Audit and lifecycle classification only; no FAR/APPROACH/NEAR_TOUCH promotion |
| `signed_distance_price = 0` | `distance_zone=null`; `HIT_INTERSECTION_EVALUATION_REQUIRED` | Evaluate producer HIT/intersection evidence; distance alone does not create HIT |
| `0.00 < distance_atr <= 0.25` | `NEAR_TOUCH` | Pre-touch monitoring; may contribute to B-to-A only with all independent gates |
| `0.25 < distance_atr <= 0.50` | `APPROACH` | May contribute to B-building only with all independent gates |
| `distance_atr > 0.50` | `FAR` | Context only |

Therefore exactly `0.25` ATR is `NEAR_TOUCH`, exactly `0.50` ATR is
`APPROACH`, and values greater than `0.50` ATR are `FAR`.

## 6. Lifecycle separation

- `NEAR_TOUCH` is not HIT, SWEEP, REJECT, BREAK, reversal, entry or trade.
- `HIT` requires producer-confirmed lifecycle evidence or deterministic
  price/level intersection evidence defined by a later producer contract.
- `REJECT` requires confirmed post-HIT reaction evidence.
- `BREAK` requires an approved confirmed close/break lifecycle rule. A transient
  observation beyond a level does not create BREAK.
- A negative signed distance means price is beyond the expected pre-touch side.
  `CROSSED_PENDING_CLASSIFICATION` requires producer lifecycle evidence to
  distinguish HIT, SWEEP, REJECT, BREAK, or a stale/mismatched level.

Crossing does not infer trade direction, reversal, grade A or notification.
Producer-specific HIT tolerance, sweep depth, rejection magnitude and break
close distance remain pending.

## 7. Level eligibility

Distance classification applies only to one identity-complete active level.
Eligible lifecycle/quality candidates are:

- grade `PRIME` or `VALID`;
- lifecycle `APPROACH`; or
- lifecycle `IDLE` while the source still marks the level active and valid.

`WEAK` may remain context but cannot independently promote `B_BUILDING`.
Broken/invalidated, expired/removed, stale, identity-missing, side-ambiguous or
price-missing levels are ineligible. Candidate ranking and per-identity
lifecycle ownership follow `LIQUIDITY_LEVEL_IDENTITY_SELECTION_V1.md`; this
distance policy does not alter source lifecycle facts.

## 8. Multiple eligible levels

For every eligible level:

1. Calculate distance independently and preserve stable `level_id`.
2. Never merge levels solely because their prices are close.
3. Never apply one level's touch count, grade or lifecycle to another level.
4. Never silently switch the setup's tracked level.
5. Keep every candidate audit-visible.

`LIQUIDITY_LEVEL_IDENTITY_SELECTION_V1.md` selects the primary using, in order:
NEAR_TOUCH/APPROACH/FAR, PRIME/VALID, higher MTF confluence, lower
`distance_atr`, fewer confirmed touches, newer confirmed source creation time,
then lexicographically smaller `level_id`. Only the next key is considered on
equality. Multiple NEAR_TOUCH levels do not fail closed merely because they
compete: exactly one valid identity is primary and the others remain secondary.
FAR remains context-only. Nearest-obstacle calculation remains unapproved.

## 9. Make-Sense state use

### `FAR`

Context only. Distance cannot independently establish `B_BUILDING`.

### `APPROACH`

May contribute to `B_BUILDING` only when Expansion is moving toward the same
eligible level, required price/ATR/level/Expansion evidence is fresh, and no
deterministic invalidation exists. It cannot establish `B_TO_A_CANDIDATE` alone.

### `NEAR_TOUCH`

May contribute to `B_TO_A_CANDIDATE` only when all of the following also pass:

- fresh Expansion movement toward the tracked level;
- exactly fresh 5m setup evidence;
- required confirmed 1m reaction/weakening evidence;
- Renko maturity at the approved state requirement;
- eligible identity-complete level and calculation inputs; and
- no deterministic invalidation.

NEAR_TOUCH may support the complete B-to-A transition and therefore bounded
capture, but it does not establish `A_CONFIRMED`.

### `HIT`, `SWEEP`, `REJECT`, `BREAK` and final states

HIT/SWEEP/REJECT require their approved lifecycle/reaction evidence before final
review. BREAK follows its confirmed producer rule and may invalidate the setup.
Distance classification alone cannot establish `A_CONFIRMED`, GO,
`WAITING_5S_ENTRY`, approval, geometry or notification. Those outcomes retain
the independently approved 5m/1m/Renko/final-review requirements.

If Expansion is moving away, distance remains audit-visible but cannot promote
APPROACH or NEAR_TOUCH. The later implementation may keep context, regress or
invalidate only under an independently approved state-machine rule.

## 10. Freshness and market closure

Distance-based promotion requires:

- XAU current observation status exactly `FRESH`;
- confirmed 5m ATR source status exactly `FRESH`;
- eligible level evidence not `STALE`, `MISSING`, `CLOCK_INVALID`,
  `SOURCE_UNAVAILABLE` or `MARKET_CLOSED`; and
- all other state-specific critical gates under `FRESHNESS_POLICY_V1.md`.

`AGING` values may be retained as context but cannot satisfy these exactly-FRESH
distance gates. During `MARKET_CLOSED`, historical values are context only: no
actionable APPROACH/NEAR_TOUCH calculation and no B-to-A, A or GO promotion is
allowed. AI and screenshot evidence cannot override freshness.

## 11. Decisions still pending

This policy does not approve:

- producer-specific HIT tolerance or deterministic intersection implementation;
- band-width handling;
- sweep depth;
- rejection magnitude;
- break close distance;
- near-touch time persistence;
- nearest-obstacle calculation;
- the stable-identity hash algorithm, exact byte encoding and producer-native
  source creation identity implementation;
- Expansion speed or exhaustion formula;
- E1/E2 TTL;
- structure/range algorithm;
- bid/ask/spread or point-size authority;
- Pine producer changes or TradingView materialization;
- provider activation or a real SHADOW model call; or
- Telegram, Notion, MT5 or broker/output activation.

All pending decisions fail closed. The execution boundary remains
`mode=SHADOW`, `environment=MT5_DEMO`, `live_execution=false`,
`order_placed=false`, and `writer_enablement=DISABLED`.
