# Project A Liquidity Level Identity and Selection V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

Owner: Project A Session 0

Approval: Jones Wong, 2026-07-20 Australia/Sydney

Scope: documentation-only stable identity, lifecycle ownership, candidate
eligibility, deterministic competing-level selection, tracked-level lock and
release policy for `Liquidity Levels V2 — 5m Body × MTF Confluence`, owner
`Jonesy_Wong`, private revision 9.

This policy does not implement a producer, state machine, schema, parser,
capture, provider, writer or runtime. Liquidity V2 remains
`SAVED_NOT_MATERIALIZED` and is not producer-complete or runtime-active.

## 1. Stable level identity

Every production Liquidity level must carry:

- `level_id` and `level_version`;
- `producer_id` and `producer_revision`;
- `symbol`, `feed`, `anchor_timeframe` and `side`;
- `source_pivot_time` or an equivalent producer-native source creation
  identity;
- tick-normalized originating `level_price`;
- `created_at_source`, `first_observed_at` and `last_observed_at`;
- `lifecycle`, `grade`, MTF confluence and confirmed touch count; and
- confirmation status and freshness status.

`level_id` identifies one originating level and must be deterministic and stable
at the producer. It must not depend on server receipt time, database row ID,
array or screen position, distance rank, grade, touch count, lifecycle, current
market value, or any mutable observation.

The approved conceptual identity preimage is:

```text
LIQ_V2 | producer_revision | symbol | feed | anchor_timeframe | side |
source_creation_identity | tick_normalized_origin_price
```

The producer should emit the resulting opaque deterministic `level_id`. Python
may verify or namespace that ID, but must not silently replace it with an ID
derived from receipt time. The hash algorithm, exact field encoding and exact
byte representation remain pending for the later producer contract.

If the producer cannot expose a source pivot time, producer-native creation
sequence or equivalent stable creation identity, identity status is
`MISSING_REQUIRES_PRODUCER_CHANGE`. The level remains audit-visible telemetry or
context but cannot become a tracked B/A setup level. Current market value plus
receipt time is never an identity substitute.

The ambiguous bare field name `price` is forbidden in this contract. Origin
geometry uses `level_price`; a current XAU observation uses `market_price`; and
trade geometry uses dimensioned entry, stop-loss and take-profit fields.

## 2. Level version

`level_id` preserves the originating level. `level_version` identifies a
material revision of its immutable or geometry-bearing source data.

These mutable observations do not create a new version:

- distance and current market value;
- producer-permitted grade movement;
- touch count and last-observed time;
- lifecycle progression; and
- freshness status.

These changes require explicit correction/version handling:

- corrected originating `level_price`;
- changed band geometry;
- corrected source creation identity;
- a producer revision that changes the level algorithm;
- corrected source side; or
- corrected anchor timeframe.

An old version must not be silently mutated. A version change is audit-visible,
links the replaced and replacement versions, and does not rewrite prior facts.

## 3. Per-level lifecycle ownership

Lifecycle is owned independently by each `level_id` and `level_version`. The
approved conceptual progression is:

```text
IDLE -> APPROACH -> HIT -> REJECT or BREAK
```

Additional terminal or non-actionable conditions are `INVALIDATED`, `EXPIRED`,
`REMOVED`, `STALE` and `SOURCE_UNAVAILABLE`.

A touch, sweep, rejection or break for one identity/version must never update a
different level. Lifecycle must not regress silently. Producer correction is an
explicit correction/version event. Given the same immutable events, restart or
offline replay must reconstruct the same lifecycle. AI may not create, merge,
repair or rewrite lifecycle facts. Exact HIT tolerance, band geometry, sweep
depth, rejection magnitude and break-close distance remain pending.

## 4. Candidate filter

Before ranking, exclude from promotion any level that is:

- grade `WEAK`;
- broken, invalidated, expired, removed, stale or source-unavailable;
- missing a valid `level_id` or carrying an invalid `level_price`;
- missing or ambiguous side;
- provisional where confirmed evidence is required;
- for the wrong symbol, feed or anchor timeframe;
- based on current XAU or confirmed 5m ATR evidence that fails freshness; or
- `CROSSED_PENDING_CLASSIFICATION` without lifecycle resolution.

Excluded levels remain audit-visible and are not deleted. Promotion-eligible
grades are `PRIME` first and `VALID` second.

## 5. Directional eligibility

An Expansion `UP` market story ranks only ASK/resistance levels as approach
targets. An Expansion `DOWN` market story ranks only BID/support levels as
approach targets. This describes market movement toward a level, not a trade
direction. It must never infer `UP -> LONG`, `DOWN -> SHORT`, `ASK -> SHORT`, or
`BID -> LONG`. A later confirmed reaction determines the trade thesis.

Opposite-side levels remain context and potential obstacle/invalidation evidence.
They cannot replace the tracked approach level. Nearest-obstacle calculation and
all entry/SL/TP obstacle use remain pending final-review and risk policy.

## 6. Exact deterministic ranking

Eligible candidates for the same story are compared by this exact ordered
seven-key tuple:

1. distance zone: `NEAR_TOUCH`, then `APPROACH`, then `FAR`;
2. grade: `PRIME`, then `VALID`;
3. higher MTF confluence first;
4. lower `distance_atr` first;
5. fewer confirmed touches first;
6. newer confirmed source creation time first; and
7. lexicographically smaller `level_id` first.

Comparison proceeds to the next key only when every earlier key is equal. AI,
screenshot position, database insertion order and arbitrary source/list ordering
are forbidden ranking inputs.

If every eligible candidate is `FAR`, the deterministic top-ranked context level
may be displayed, but distance alone creates no tracked B setup, capture or AI
review. State remains `NO_STORY` or `C_INSUFFICIENT` unless separate approved
evidence establishes otherwise.

## 7. Multiple eligible and NEAR_TOUCH levels

When multiple candidates are `NEAR_TOUCH`, apply the same seven-key tuple and
select exactly one proposed/tracked primary. Preserve every other candidate as
secondary context. Never merge identities because their values are close, and
never aggregate touch count, grade or lifecycle across identities. AI cannot
replace the selected primary.

If candidates are equal through the first six keys, the `level_id` tie-break
still selects deterministically. Such equality may produce an ambiguity
diagnostic, but does not block selection when both identities are valid.

## 8. Tracked-level lock

Before `B_BUILDING`, the top deterministic candidate may be the proposed setup
level. At transition into `B_BUILDING`, lock:

- `tracked_level_id` and `tracked_level_version`;
- the complete seven-key selection tuple and selection time;
- the candidate snapshot and selection reason;
- the Expansion movement direction; and
- all rejected or secondary candidates.

After `B_BUILDING`, the setup must not silently switch because another level
becomes closer, changes grade, gains confluence or receives more touches. A
newly superior level remains secondary context, may form a separate future
candidate setup, or waits until the current setup terminates.

## 9. Release and no-silent-switch policy

The tracked level may be released only when:

- its level is `INVALIDATED`, `EXPIRED`, `REMOVED`, or has confirmed `BREAK`;
- its source identity becomes invalid;
- its source remains unavailable beyond approved policy;
- the setup is explicitly `INVALIDATED` or `EXPIRED`;
- direction/story is reset;
- an operator approves reset; or
- a source correction creates a replacement version after the current setup is
  safely terminated.

Release closes the old setup lifecycle, preserves its complete audit history,
runs a new deterministic selection and creates a new setup identity. The old
setup ID is never reused.

Future producer/state-machine behavior must express a tracked-level change with
conceptual `TRACKED_LEVEL_RELEASED` and `TRACKED_LEVEL_SELECTED` events. A later
policy may add `SECONDARY_LEVEL_PROMOTED`. This documentation does not implement
those events. Every change must retain old and new level ID/version, release
reason, selection tuple, transition time and source evidence.

## 10. Restart and replay determinism

Given identical immutable events and source observations, restart and offline
replay must reproduce the same candidate set, ranking order, selected level,
tracked-level lock and release decision. Selection cannot depend on process-only
memory, current array order, filesystem order, non-canonical database insertion
order or wall-clock replay time.

## 11. Freshness interaction

Candidate promotion requires a fresh current XAU observation, fresh confirmed 5m
ATR(14), fresh level evidence, valid source identity, and no market closure,
source error or clock error under `FRESHNESS_POLICY_V1.md`. `AGING` may be
displayed as context but cannot create a new B/A tracked setup where the gate
requires exactly `FRESH`.

Stale evidence must not silently switch the setup to another level. Record the
source condition, apply the approved release rules and fail closed.

## 12. Decisions still pending

This policy does not approve:

- the `level_id` hash algorithm or exact byte encoding;
- producer-native source creation identity implementation;
- HIT tolerance or deterministic intersection implementation;
- band geometry, sweep depth, rejection magnitude or break-close distance;
- near-touch persistence or nearest-obstacle calculation;
- Expansion speed or exhaustion formulas;
- E1/E2 TTL or structure/range algorithm;
- point-size or bid/ask/spread authority;
- Pine producer changes or TradingView materialization;
- provider activation or a real SHADOW model call; or
- Telegram, Notion, MT5, broker or other output activation.

All pending decisions fail closed. The boundary remains `mode=SHADOW`,
`environment=MT5_DEMO`, `live_execution=false`, `order_placed=false`, and
`writer_enablement=DISABLED`.
