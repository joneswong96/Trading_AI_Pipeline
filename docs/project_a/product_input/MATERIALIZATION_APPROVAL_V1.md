# Project A four-alert materialization approval

Status: **APPROVED_FOR_CONTROLLED_MATERIALIZATION**

Owner: Project A Session 0

Approval: Jones Wong, 2026-07-20 Australia/Sydney

Scope: one controlled SHADOW/no-live runtime and TradingView materialization

## Approved alert set

Exactly four new Project A alerts are authorized:

1. `Project A V1 — LIQ_V2 JSON`
2. `Project A V1 — EXP_V3 JSON`
3. `Project A V1 — EXP_SCANNER JSON`
4. `Project A V1 — RENKO_V3 JSON`

No fifth Project A alert is authorized. The two existing legacy Liquidity and
Expansion alerts are protected and must not be deleted, paused, edited,
recreated or used as new-event validation evidence.

## Expansion evidence family

`EXP_V3_R5` and `EXP_SCANNER_R6` remain separate Pine producers and require
separate TradingView alerts. They form one logical Expansion Evidence family;
they do not count as two directional votes. No source combination is required.

Scanner output is quality evidence only. It is not an independent directional
vote, trade direction, setup approval, wake trigger, AI trigger, notification
trigger or order trigger. It may enrich a corresponding Expansion V3 evidence
object with CLEAN, WEAK, TOO_EXTENDED, candle-body, opposing-bar, age and
maturity facts where the producer exposes them.

Scanner evidence must be correlated to Expansion V3 using available factual
identity fields: symbol, feed, timeframe, source-bar time, event time, producer
identity and compatible direction/context. Correlation failure leaves Scanner
evidence unpaired and context-only. An unpaired Scanner event cannot wake,
promote, call AI, notify or act, and it cannot manufacture a separate market
story.

## Materialization and safety boundary

This approval permits the exact committed private candidates to be compiled,
saved privately, added to the approved 9333/9222 layouts, enabled for Project A
JSON V1 after Feature-OFF parity, and snapshotted into the four alerts above.
It also permits controlled deployment of the corrected integrated ingest
runtime.

The following boundary remains mandatory:

- `mode=SHADOW`
- `environment=MT5_DEMO`
- `live_execution=false`
- `order_placed=false`
- `writer_enablement=DISABLED`

This approval does not authorize a synthetic POST, Pine TEST event, provider or
AI call, Telegram/Notion/MT5 output, broker connection, order, public Pine
publication, legacy-alert retirement or use of port 4999 as production evidence.
