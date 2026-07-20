# Project A Product Input Authority V1 approval record

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

| Record field | Value |
|---|---|
| Approver | Jones Wong |
| Approval date | 2026-07-20 Australia/Sydney |
| Approval source | Explicit Project A Session 0 instruction |
| Contract commit approved | `ab252a7d42be5dda37bbbceab2bd529bd761b931` |
| Execution boundary | `mode=SHADOW`; `environment=MT5_DEMO`; `live_execution=false`; `order_placed=false`; `writer_enablement=DISABLED` |

This record approves Product Input authority and policy. It does not declare any
indicator, Pine producer, chart layout, CDP adapter, AI provider or external
writer runtime-active.

## 0. Controlled materialization correction

Jones Wong explicitly approved one controlled materialization on 2026-07-20,
as recorded in `MATERIALIZATION_APPROVAL_V1.md`. The corrected alert limit is
exactly four new Project A alerts:

- `Project A V1 — LIQ_V2 JSON`
- `Project A V1 — EXP_V3 JSON`
- `Project A V1 — EXP_SCANNER JSON`
- `Project A V1 — RENKO_V3 JSON`

Expansion V3 and Expansion Scanner remain separate Pine producers but form one
logical Expansion Evidence family, not two directional votes. Scanner evidence
is quality-only and must be correlated using factual identity fields. Unpaired
Scanner evidence is context-only and cannot independently wake, promote, call
AI, notify or act. The two existing legacy alerts remain protected, no source
combination is required, and no fifth Project A alert is authorized.

This correction authorizes only the bounded runtime, private-Pine, layout and
four-alert work in that approval. It does not weaken the SHADOW/no-live boundary
or authorize synthetic events, providers, outputs, MT5, brokers or orders.

## 1. Approved authorities

1. **Liquidity:** `Liquidity Levels V2 — 5m Body × MTF Confluence`, owner
   `Jonesy_Wong`, private revision 9. Conventional high means ASK/resistance and
   low means BID/support. MTF confluence, touch count, PRIME/VALID/WEAK grade,
   IDLE/APPROACH/HIT/REJECT/BREAK lifecycle and first confirmed touch are
   preserved. The source's ambiguous payload field `price` means level value; a
   later producer contract must use `level_price`, `market_price` and
   `signal_price` as applicable. Liquidity V1 revision 11 is
   `LEGACY_REFERENCE`. `LIQUIDITY_DISTANCE_POLICY_V1.md` is approved as the
   side-aware pre-touch distance policy; this does not materialize or activate
   the producer.
2. **Expansion:** `Expansion Leg Signal V3`, private revision 5, is the confirmed
   trigger/direction authority. `③ Expansion Scanner [SNR3.0]`, private revision
   6, supplies quality classification only. They form one Expansion Evidence
   object and do not count as two independent votes. Missing numeric outputs stay
   missing. `expDetector/1` is `LEGACY_REFERENCE`.
3. **MACD:** TradingView standard price MACD, close EMA 12/26/9, using exact
   closed-bar 9333 values for 1m, 5m, 15m and 30m. The 5m timeframe supplies setup
   direction, 1m supplies confirmation, and 15m/30m supply context. Developing
   custom MACD engines are not V1 authorities; 1m Confidence, 6TF MACD and
   `macdVol/1` remain reference/research sources.
4. **DXY:** 9333 TVC:DXY 15m is primary deterministic authority and 9222
   TVC:DXY 1m is explicit supplemental evidence. DXY confirms, conflicts or caps
   grade; it is not a universal hard veto. `dxyReader/3` is optional
   `LEGACY_REFERENCE` logic.
5. **Renko:** `Renko V3 — V2 Preserved + 5s Sniper Dashboard`, private revision 1,
   source SHA-256
   `327c5043f9ca53f531b8d8e8aa89e6b72d649a527339432bbeeef5bcb463f003`,
   is the approved V1 authority candidate. It remains
   `SAVED_NOT_MATERIALIZED`. Current Renko V2, `rekoArrow/1`, the standalone E1/E2
   test source and Renko V3 revision 4 without Sniper are not parity.
6. **Structure/regime:** deterministic 9333 ICMARKETS:XAUUSD 4H/D/W and approved
   deterministic price-structure facts are the V1 authority. SR MTF Pro V10 is
   visual/supporting context only; its disabled surfaces are not structured
   evidence. `structState/1` is `LEGACY_REFERENCE`.

Every authority has approval standing
`APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE`. Saved Pine candidates retain
`SAVED_NOT_MATERIALIZED`; existing chart/data sources require
`PENDING_RUNTIME_VALIDATION` before Product Input runtime use.

## 2. Approved port roles

- `9333`: primary deterministic production data and capture authority.
- `9222`: explicit supplemental read-only Renko/chart and DXY 1m evidence route.
- `4999`: `TEST_ONLY`; forbidden for production evidence.
- No silent fallback or substitution is permitted.
- A browser target may be rebound after restart only after explicit verification
  of port, account, layout, symbol, feed, timeframe and required studies.

## 3. Approved transport policy

- Pine events provide implemented state transitions for Liquidity, Expansion,
  Renko and lifecycle evidence.
- 9333 structured reads provide primary exact XAU observations, closed OHLC,
  1m/5m/15m/30m MACD, 15m DXY, 4H/D/W context, source-bar times and freshness
  inputs.
- 9222 provides explicitly approved supplemental Renko, DXY 1m and chart
  evidence.
- Screenshots provide visual big-picture evidence only. They do not override
  exact structured numbers.
- Missing producer values use `PENDING_PRODUCER_CHANGE`; they are never estimated
  or silently synthesized.

## 4. Approved maturity and notification mapping

- E1 is early/B-building evidence.
- E2 is stronger maturity and possible B-to-A candidate evidence.
- Main is confirmed Renko direction.
- Sniper FIRE is the final 5s execution-timing candidate.
- E1 is not required before E2. E2 or Main may occur without a recorded earlier
  stage. No mandatory E1→E2→Main sequence is allowed.
- Sniper FIRE cannot create a thesis and remains valid only while the approved 5m
  thesis and confirmed 1m direction remain valid.
- The approved state family is `NO_STORY`, `C_INSUFFICIENT`, `B_BUILDING`,
  `B_TO_A_CANDIDATE`, `A_CONFIRMED`, `WAITING_5S_ENTRY`, `INVALIDATED`, and
  `EXPIRED`.
- Entry into `B_TO_A_CANDIDATE` triggers complete capture.
- Final review returns separate verdict and grade. An eligible B-to-A transition
  notifies exactly once; persistent A, retries, duplicate FIRE events and process
  restarts do not create duplicates.

## 5. Approved freshness policy

`FRESHNESS_POLICY_V1.md` is approved with statuses `FRESH`, `AGING`, `STALE`,
`MARKET_CLOSED`, `MISSING`, `CLOCK_INVALID`, `SOURCE_UNAVAILABLE`, and
`PROVISIONAL`. `AGING` begins at 75% of the maximum and is never relabeled
`FRESH`. Freshness remains separate from signal validity/TTL.

Approved maximum ages are XAU current 10 seconds, DXY current 30 seconds, 5s
execution 15 seconds, 15s supplemental 45 seconds, and closed bars: 1m 120, 5m
420, 15m 1,200, 30m 2,400, 1H 5,400, 4H 18,000, Daily 108,000, and Weekly
691,200 seconds. Event transport is promotion-eligible through 30 seconds,
late/non-promoting above 30 through 120 seconds, and stale above 120 seconds.

Capture must complete within 45 seconds; XAU current age at completion is at most
15 seconds, 1m age at most 120 seconds, screenshot/read skew at most 30 seconds,
9333/9222 skew at most 30 seconds, and future clock skew at most 10 seconds.
Final GO requires Sniper FIRE receipt age at most 15 seconds, XAU current age at
most 10 seconds, and status exactly `FRESH` for matching 1m and 5m evidence.

Critical stale/missing/clock-invalid/source-unavailable/market-closed evidence
blocks A and GO. Critical provisional evidence cannot establish A or GO. Stale
or missing DXY, 15m/30m MACD, or 4H/D/W structure caps grade at B without
reversing direction. Market-closed history is context carry-forward only and
cannot promote a setup. AI cannot override deterministic freshness.

## 5.1 Approved Liquidity distance policy

`LIQUIDITY_DISTANCE_POLICY_V1.md` is approved with these exact limits:

- latest confirmed, exactly-fresh 5m ATR(14) is the normalization authority;
- fresh current XAU `market_price` and Liquidity V2 `level_price` remain distinct;
- ASK/resistance signed distance is level minus market and expects Expansion UP;
- BID/support signed distance is market minus level and expects Expansion DOWN;
- above 0.50 ATR is FAR, above 0.25 through 0.50 is APPROACH, and above zero
  through 0.25 is NEAR_TOUCH;
- zero requires HIT/intersection evaluation and negative signed distance is
  `CROSSED_PENDING_CLASSIFICATION`;
- invalid, missing, provisional or non-fresh required inputs make distance
  unavailable and block promotion; and
- distance alone cannot infer trade direction, HIT, REJECT, BREAK, A, GO,
  geometry, capture or notification.

Each eligible level retains independent stable identity and distance. Candidate
selection is now controlled by the separately approved policy in section 5.2.
This distance approval is documentation-only and does not implement or activate
Liquidity V2, capture, providers, outputs or runtime.

## 5.2 Approved Liquidity level identity and selection policy

`LIQUIDITY_LEVEL_IDENTITY_SELECTION_V1.md` is approved. A production level
requires producer-stable `level_id`, explicit `level_version`, complete producer,
symbol/feed/timeframe/side/source-creation lineage, dimensioned `level_price`,
source/observation times, independent lifecycle/grade/confluence/touch state,
confirmation and freshness. Missing source creation identity is
`MISSING_REQUIRES_PRODUCER_CHANGE` and blocks tracked B/A promotion.

Eligible same-story candidates use the exact ordered tuple: distance zone
NEAR_TOUCH/APPROACH/FAR; grade PRIME/VALID; higher MTF confluence; lower
`distance_atr`; fewer confirmed touches; newer confirmed source creation time;
then lexicographically smaller `level_id`. Expansion UP ranks ASK/resistance and
Expansion DOWN ranks BID/support without inferring trade direction. FAR is
context-only. At `B_BUILDING` the selected identity/version and full decision
record lock until an explicit approved release; no newly superior or
opposite-side level may silently replace it. Multiple valid NEAR_TOUCH levels
select one deterministically and preserve all others as secondary context.

This approval is documentation-only. The identity hash/encoding and producer
implementation remain pending, and Liquidity V2 remains
`SAVED_NOT_MATERIALIZED`, not producer-complete and not runtime-active.

## 6. Approved SHADOW/no-live boundary

The existing boundary remains mandatory:

- `mode=SHADOW`
- `environment=MT5_DEMO`
- `live_execution=false`
- `order_placed=false`
- `writer_enablement=DISABLED`

Authority approval cannot weaken these values or activate an output.

## 7. Pending decisions

The following remain unapproved and fail closed:

- producer-specific Liquidity HIT tolerance and deterministic intersection rule;
- Liquidity band-width handling, sweep depth, rejection magnitude and break
  close distance;
- near-touch time persistence;
- the `level_id` hash algorithm, exact byte encoding and producer-native source
  creation identity implementation;
- exact Expansion speed formula;
- exact Expansion exhaustion formula;
- exact E1/E2 event TTL;
- exact structure/range algorithm;
- exact nearest-obstacle calculation;
- trusted bid/ask/spread and point-size authority;
- production TradingView layout materialization beyond the bounded approval in
  `MATERIALIZATION_APPROVAL_V1.md`;
- Pine producer changes;
- provider runtime activation;
- a real SHADOW model call; and
- Telegram, Notion or MT5 Demo output activation.

## 8. Explicitly unauthorized actions

This approval does not authorize:

- live broker execution or automatic real-account orders;
- an AI-provider call or provider credential change;
- MT5 connection or output;
- Telegram, Notion, webhook or other external writer activation;
- TradingView alert creation beyond the exact four-alert approval, any legacy
  alert modification, or any test triggering;
- Pine modification, public publication or producer implementation; private
  candidate saves are limited to `MATERIALIZATION_APPROVAL_V1.md`;
- TradingView indicator/layout materialization beyond the bounded approval in
  `MATERIALIZATION_APPROVAL_V1.md`;
- runtime, schema, fixture, test or configuration changes; or
- use of port 4999 as production evidence.

Any later task must name its authority, remain inside the approved SHADOW/no-live
boundary, resolve only explicitly approved pending decisions, and pass a separate
runtime safety review.
