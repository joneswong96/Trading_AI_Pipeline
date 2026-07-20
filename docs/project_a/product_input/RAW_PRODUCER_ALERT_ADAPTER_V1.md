# Project A raw producer `/alert` adapter V1

Status: integrated repository contract; runtime deployment remains separate.

## Boundary and precedence

TradingView has one approved webhook path: `POST /alert`. Ingress reads the raw
body once and applies this order:

1. Parse JSON only for exact Product Input identity detection.
2. Route an allowlisted raw producer to the Project A adapter.
3. Route every other body through the unchanged legacy JSON/text parser.

Detection uses exact top-level schema or producer values, never substrings or an
arbitrary `producer_id`. Once recognized, a payload cannot fall through to
legacy parsing even if strict validation or Section 2 compilation fails.

## Allowlist and canonical path

The active production identities are `LIQ_V2/9`, `EXP_V3/5` and
`RENKO_V3_SNIPER/1`. The strict `EXP_SCANNER/6` identity remains accepted only
as dormant compatibility to avoid regression; it is not materialized, alerted
or required by Section 2. Producer validation stays in `project_a.numeric_state`; ingress
does not duplicate it. Accepted raw bytes flow through:

`raw receipt → NumericMarketState → MakeSenseCompiler → EvidenceBundleRequest`

The pipeline is invoked with empty injected structured-read and screenshot
request adapters. All freshness inputs are `MISSING`, so ingress records only
deterministic telemetry/state. It performs no read, screenshot, provider call,
notification, output write, broker connection or order action.

## Semantics and correlation

- LIQ keeps `level_price` separate from event-time `market_price`; ASK/BID is a
  liquidity side, not trade direction.
- EXP keeps UP/DOWN as movement and story evidence, never LONG/SHORT.
- Scanner is stored separately as quality-only, non-promoting evidence. Exact
  symbol/feed/timeframe/source-bar-time/direction-context matching is
  receipt-order independent. Missing or ambiguous matches remain unpaired.
- Renko E1, E2, MAIN, FIRE and RESET remain stage/timing evidence only.

No missing Entry, SL, TP, grade or trade direction is invented.

## Persistence, dedupe and responses

The adapter uses the configured Project A SQLite owner and adds append-only
adapter receipts, canonical events and state-history tables. Raw bytes are
immutable. Exact retries and semantic retries are idempotent; event-identity or
Scanner-fact conflicts are audit-visible. Validation and compilation are
transactional, so failure produces no partial canonical event or state update.

Valid responses expose only bounded status fields and always report
`wake=false`, `provider_called=false`, `writer_called=false`, and
`order_placed=false`. Recognized validation failures return 4xx; internal
failures return a bounded 503 without paths, payloads or exception detail.

`PROJECT_A_RAW_PRODUCER_INGEST_ENABLED` defaults to `true`. This switch enables
only safe telemetry recognition. It does not alter the independent disabled V1
endpoint, SHADOW/MT5_DEMO safety constants, capture, provider, writer or order
boundaries. A separate controlled deployment is required before a running
non-reload server uses this adapter.
