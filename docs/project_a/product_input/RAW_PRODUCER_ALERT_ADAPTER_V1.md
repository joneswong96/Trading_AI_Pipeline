# Project A raw producer `/alert` adapter V1

Status: **IMPLEMENTED — SINGLE-LIQ RESEARCH TRIGGER, FAIL-CLOSED**

TradingView has one approved webhook transport: `POST /alert`. Recognized
Project A JSON is parsed from the exact raw UTF-8 body before the legacy parser.
Invalid recognized input returns a bounded 4xx/503 and never falls through to
legacy routing or fanout.

## Active and compatibility identities

`LIQ_V2/9 LIQ_TOUCH` is the only active production research trigger. It must be
confirmed, `FRESH`, no more than 15 minutes old, not future-dated, and exactly
ICMARKETS:XAUUSD on the 5m authority. Level, market-price and ATR freshness must
be `FRESH`, and the 5m ATR must be confirmed.

Strict `EXP_V3/5`, `RENKO_V3_SNIPER/1`, and `EXP_SCANNER/6` interception remains
for compatibility safety. Those events, plus non-touch LIQ lifecycle events,
are telemetry-only and cannot wake research, request capture, promote a story,
call a provider, write output, notify, or place an order.

## Research intent and dedupe

The first valid LIQ touch inserts one append-only
`project_a_liq_research_requests` row containing the complete, hashed structured
read and screenshot request, with an explicit unbound-target preflight gate.
Append-only status history supports `PENDING`, one-worker `CLAIMED`, and terminal
`COMPLETED`/`FAILED`; completion requires a lowercase 64-hex capture-manifest
SHA-256. The schema is additive and separately versioned, so the accepted
raw-receipt V1 checksum and history remain intact.

The Project A response sets `wake=true` and
`evidence_acquisition_requested=true` only for that newly queued touch. This is
a Project A research wake, not the legacy wake/fanout path; receipt rows retain
`legacy_wake_eligible=0`.

Exact, formatting-equivalent, semantic same-event, and identical-evidence
retries do not create another research intent. Conflicting facts for the same
level/touch/time identity fail closed. A genuine re-touch must monotonically
advance both touch count and source time; it creates a new evidence key
immediately, with no fixed cooldown.

## Evidence and safety boundary

The queued intent is not a completed Evidence Bundle or Grade. The offline
Evidence Bundle compiler describes the approved MCP structured reads and
screenshots; execution belongs to a separately approved capture runtime.
Missing or stale evidence remains explicit and promotion remains false.

All raw-receipt, event, state, and research-intent records are immutable or
append-only. Provider, writer, broker and order flags are structurally false.
Project A V1/provider/output paths remain disabled, with SHADOW, MT5_DEMO,
`live_execution=false`, and `order_placement=false`.
