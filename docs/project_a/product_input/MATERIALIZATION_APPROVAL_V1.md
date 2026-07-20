# Project A three-producer materialization approval

Status: **APPROVED_FOR_CONTROLLED_MATERIALIZATION**

Owner: Project A Session 0

Approval: Jones Wong, 2026-07-20 Australia/Sydney

Scope: one controlled SHADOW/no-live runtime and TradingView materialization

## Approved alert set

Exactly three new Project A alerts are authorized:

1. `Project A V1 — LIQ_V2 JSON`
2. `Project A V1 — EXP_V3 JSON`
3. `Project A V1 — RENKO_V3 JSON`

No fourth Project A alert is authorized. The two existing legacy Liquidity and
Expansion alerts are protected and must not be deleted, paused, edited,
recreated or used as new-event validation evidence.

## Expansion authority and Scanner compatibility

`EXP_V3_R5` is the sole active Expansion producer and directional movement
evidence stream. `EXP_SCANNER_R6` is dormant reference/compatibility only: it is
not materialized, added to a chart, assigned an alert, required by Section 2, or
counted as an independent directional vote.

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

This approval permits the exact committed LIQ V2, EXP V3 and Renko V3 Sniper
private candidates to be compiled, saved privately, added to the approved
production layouts, enabled for Project A JSON V1 after Feature-OFF parity, and
snapshotted into the three alerts above. Renko V3 Sniper is hosted only on
layout `YclFo8Ax`, ICMARKETS:XAUUSD, 5-second standard candles; its synthetic
Renko engine does not authorize a native-Renko host. G4-G7 remain unchanged and
port 4999 remains test/acceptance only.
It also permits controlled deployment of the corrected integrated ingest
runtime.

The three alerts continue to target the existing `POST /alert` webhook; no
webhook-path change is required. The integrated raw-producer adapter takes
precedence over legacy parsing only for the exact allowlisted producer schema,
ID and revision tuples. Scanner remains quality-only and non-waking. A
recognized invalid producer payload fails closed and is not reclassified by the
legacy parser.

Repository integration alone is not deployment. Until the separately approved
runtime restart/materialization step loads the integrated revision, the running
server retains its previously loaded behavior and the three alerts must not be
used as proof that the adapter is active.

The following boundary remains mandatory:

- `mode=SHADOW`
- `environment=MT5_DEMO`
- `live_execution=false`
- `order_placed=false`
- `writer_enablement=DISABLED`

This approval does not authorize a synthetic POST, Pine TEST event, provider or
AI call, Telegram/Notion/MT5 output, broker connection, order, public Pine
publication, legacy-alert retirement or use of port 4999 as production evidence.
