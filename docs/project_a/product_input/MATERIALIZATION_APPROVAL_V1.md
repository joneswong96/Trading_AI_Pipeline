# Project A single-LIQ materialization approval

Status: **APPROVED_FOR_CONTROLLED_MATERIALIZATION**

Product Authority: Jones Wong

Supersedes: the 2026-07-20 three-producer/three-alert materialization plan

## Sole production alert

Exactly one new Project A alert is authorized:

- `Project A V1 — LIQ_V2 — XAUUSD 5m`

It uses the exact accepted private Liquidity V2 candidate on
ICMARKETS:XAUUSD, 5-minute standard candles, `Any alert() function call`,
script-generated JSON, and
`https://pureness-fondness-rust.ngrok-free.dev/alert`.

The Project A JSON surface emits `LIQ_TOUCH` only. Each distinct touch or
re-touch edge may create one research trigger. Approach, prime-hit, reject,
break, invalidation, or other lifecycle transitions must not create Project A
production alerts.

Before creation, production Chrome 9333 must positively verify the account,
symbol, feed, timeframe, chart type, candidate identity, Feature-OFF parity,
and absence of an exact equivalent Project A LIQ alert. Existing alerts and
layouts are protected and must not be edited, paused, deleted, retired, or
recreated.

## Compatibility evidence

`EXP_V3_R5`, `RENKO_V3_SNIPER_R1`, and `EXP_SCANNER_R6` are not production
alert authorities. They are not materialized, alerted, independent votes,
wake triggers, promotion triggers, or prerequisites for research. Their strict
parsers may remain for compatibility and historical evidence, but a receipt
from any of them is telemetry-only and cannot create a research acquisition
request.

Expansion direction is movement evidence, never automatic trade direction.
Renko and 5-second evidence are optional captured timing/context evidence.
Scanner remains dormant reference/compatibility only.

## LIQ research trigger

One valid, confirmed, fresh, non-duplicate `LIQ_V2/9 LIQ_TOUCH` from the
approved XAUUSD/ICMARKETS/5m source creates an append-only Project A research
intent. It remains isolated from the legacy wake/fanout path. The intent asks
the approved capture boundary to acquire exact structured reads and screenshots
covering available price, level, distance, spread, Expansion context, MACD,
multi-timeframe structure, 5-second context, DXY, SNR/HPA, freshness, integrity,
and visual evidence.

The alert is a research trigger, not a Grade, direction, entry, provider call,
notification, or order. Missing, stale, ambiguous, wrong-source, or invalid
evidence is recorded and cannot be promoted or fabricated. A completed Evidence
Bundle remains required before grading or review.

## Safety boundary

This approval does not enable AI/provider dispatch, OAuth, Telegram, Notion,
MT5, broker connectivity, live execution, order placement, public Pine
publication, synthetic webhook events, legacy database inspection, use of port
4999 as production, or G4-G7 mutation. Runtime remains SHADOW, MT5_DEMO,
`live_execution=false`, and `order_placement=false`.

If no natural touch occurs after materialization, record:

`NATURAL LIQ ALERT VERIFICATION PENDING`
