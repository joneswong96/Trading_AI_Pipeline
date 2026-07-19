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

## 1. Approved authorities

1. **Liquidity:** `Liquidity Levels V2 — 5m Body × MTF Confluence`, owner
   `Jonesy_Wong`, private revision 9. Conventional high means ASK/resistance and
   low means BID/support. MTF confluence, touch count, PRIME/VALID/WEAK grade,
   IDLE/APPROACH/HIT/REJECT/BREAK lifecycle and first confirmed touch are
   preserved. The source's ambiguous payload field `price` means level value; a
   later producer contract must use `level_price`, `market_price` and
   `signal_price` as applicable. Liquidity V1 revision 11 is
   `LEGACY_REFERENCE`.
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

## 5. Approved SHADOW/no-live boundary

The existing boundary remains mandatory:

- `mode=SHADOW`
- `environment=MT5_DEMO`
- `live_execution=false`
- `order_placed=false`
- `writer_enablement=DISABLED`

Authority approval cannot weaken these values or activate an output.

## 6. Pending decisions

The following remain unapproved and fail closed:

- exact freshness thresholds per timeframe;
- exact Liquidity near-touch distance;
- exact Expansion speed formula;
- exact Expansion exhaustion formula;
- exact E1/E2 event TTL;
- exact structure/range algorithm;
- exact nearest-obstacle calculation;
- trusted bid/ask/spread authority;
- production TradingView layout materialization;
- Pine producer changes;
- provider runtime activation;
- a real SHADOW model call; and
- Telegram, Notion or MT5 Demo output activation.

## 7. Explicitly unauthorized actions

This approval does not authorize:

- live broker execution or automatic real-account orders;
- an AI-provider call or provider credential change;
- MT5 connection or output;
- Telegram, Notion, webhook or other external writer activation;
- TradingView alert creation, modification or test triggering;
- Pine modification, save, publication or producer implementation;
- TradingView indicator/layout materialization;
- runtime, schema, fixture, test or configuration changes; or
- use of port 4999 as production evidence.

Any later task must name its authority, remain inside the approved SHADOW/no-live
boundary, resolve only explicitly approved pending decisions, and pass a separate
runtime safety review.
