# Project A Product Input Authority V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

Owner: Project A Session 0

Approval: Jones Wong, 2026-07-20 Australia/Sydney

Scope: documentation only; no source, indicator, producer, adapter, layout or
runtime below is declared active

## 1. Authority rules

Project A V1 proposes a hybrid, numeric-first evidence stack. Structured reads
provide numeric authority; Pine events provide event-native facts; screenshots
provide visual context. A screenshot may not replace a numeric value that an
approved structured source can provide.

Port authority is explicit and fail-closed:

- `9333` is the primary deterministic XAUUSD, MACD, DXY 15m, and higher-timeframe
  price/structure route.
- `9222` is the supplemental read-only Renko/chart route and the supplemental
  DXY 1m route.
- `4999` is isolated acceptance/test only and is forbidden as production
  evidence.
- A failed or incomplete read on one port must not silently fall back to another
  port.

The status vocabulary distinguishes authority approval from runtime state:

- `APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE`: Jones approved the source/policy role,
  but did not activate runtime use.
- `SAVED_NOT_MATERIALIZED`: approved Pine candidate exists only as saved source.
- `PENDING_RUNTIME_VALIDATION`: source/chart exists, but Product Input runtime
  validation and activation remain pending.
- `PENDING_PRODUCER_CHANGE`: an approved contract field is not exposed by its
  present producer.
- `TEST_ONLY`: acceptance evidence is forbidden as production evidence.
- `LEGACY_REFERENCE`: historical or supporting context, not V1 numeric authority.

## 2. Approved authority summary

| Authority ID | Exact identity | Purpose | Route and timeframe | Runtime status |
|---|---|---|---|---|
| `LIQ_V2_R9` | `Liquidity Levels V2 — 5m Body × MTF Confluence`; owner `Jonesy_Wong`; private revision 9; source SHA-256 `d08576886140222f71f0125428b9974abd4db9b95168c91342178edc1d76ef9e` | Liquidity location, approach, touch, reaction and break lifecycle | Pine event/structured study state when materialized; 5m anchor with 15m/30m/60m confluence; no current production layout | `SAVED_NOT_MATERIALIZED` |
| `EXP_V3_R5` | Saved as `Expansion Leg Signal V3`; Pine title `Expansion Leg Signal V3 Stable`; owner `Jonesy_Wong`; private revision 5; source hash not independently pinned | Confirmed expansion trigger | Pine event on its materialized chart timeframe; exact production timeframe remains pending | `SAVED_NOT_MATERIALIZED` |
| `EXP_SCANNER_R6` | `③ Expansion Scanner [SNR3.0]`; owner `Jonesy_Wong`; private revision 6; source hash not independently pinned | Expansion quality classification only | Pine state/event on the same decision timeframe as `EXP_V3_R5` | `SAVED_NOT_MATERIALIZED` |
| `MACD_TV_9333_12_26_9` | TradingView standard `Moving Average Convergence Divergence`; TradingView built-in; close, EMA 12/26/9 | Price-MACD setup, confirmation and context | `9333`; layouts `cpPWuLlN` and `avpCVaw2`; 1m/5m/15m/30m | `PENDING_RUNTIME_VALIDATION` |
| `DXY_TVC_9333_15M` | `TVC:DXY`; TradingView data; no custom indicator | Primary DXY evidence and grade cap | `9333`; layout `n9qjfufV`; 15m closed bar with SMA20 | `PENDING_RUNTIME_VALIDATION` |
| `DXY_TVC_9222_1M` | `TVC:DXY`; TradingView data; no custom indicator | Supplemental short-horizon DXY evidence | `9222`; layout `ocVwlz2C`; 1m | `PENDING_RUNTIME_VALIDATION` |
| `RENKO_V3_SNIPER_R1` | `Renko V3 — V2 Preserved + 5s Sniper Dashboard`; owner `Jonesy_Wong`; private revision 1; source SHA-256 `327c5043f9ca53f531b8d8e8aa89e6b72d649a527339432bbeeef5bcb463f003` | E1/E2/Main maturity and 5s Sniper FIRE timing | Approved supplemental route role `9222`; production layout not yet materialized; intended Sniper decision timeframe 5s | `SAVED_NOT_MATERIALIZED` |
| `STRUCTURE_9333_XAU_HTF` | `ICMARKETS:XAUUSD` deterministic price structure | Higher-timeframe direction and structure | `9333`; layout `pNqcbOmu`; 4H/D/W closed bars | `PENDING_RUNTIME_VALIDATION` |
| `SR_MTF_V10_CONTEXT` | `SR MTF Pro V10`; owner `Jonesy_Wong`; private saved revision 14; source SHA-256 `9f34462babbd00d7952c87a8c2abc078bcf465c21445a3298bb524c71a1fcb42` | Visual/supporting context only for V1 | `9222`; layout `paH6jur7`; current MTF trend rows 5m/15m/1H/4H/D/W | `LEGACY_REFERENCE` |
| `ACCEPTANCE_4999` | `ProjectA-XAUUSD-4999`, layout `gwnVPYuQ`, target `F2F27AAA3050DC8F9769939CB9B2E84C` | Isolated compile and visual acceptance | `4999`; XAUUSD 1m | `TEST_ONLY` |

Every V1 authority above has standing
`APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE`. The final column records the separate
materialization/validation state. Approval does not authorize producer changes,
layout materialization, alerts, writers, provider calls or external actions.

## 3. Exact route identities observed during the factual audit

CDP target IDs are process-lifetime identities. They are recorded here for
lineage, but every future capture must bind the target read-only to the pinned
port and layout ID again. A target-ID change must fail the capture preflight
until the new mapping is recorded; it is not permission to use another port.

| Port | CDP target observed | TradingView layout ID | Required content |
|---:|---|---|---|
| 9333 | `1BFD5343A964E20E4A32CAA1BA59ADDA` | `cpPWuLlN` (`g4_5m_1m`) | ICMARKETS:XAUUSD 5m/1m and standard MACD |
| 9333 | `3A1DA8E727112BD7F13732B3A8732DFE` | `avpCVaw2` (`g5_30m`) | ICMARKETS:XAUUSD 30m/15m and standard MACD |
| 9333 | `3818934C8C5F18141069CF3E7ABAB8E7` | `n9qjfufV` (`g7_DXY`) | TVC:DXY 15m |
| 9333 | `1E5C0F56E8154C894E36377A6B7A7C0C` | `pNqcbOmu` (`g6_HTF`) | ICMARKETS:XAUUSD 4H/D/W |
| 9222 | `ACF2304D2914588BDCBED4238C692328` | `paH6jur7` (`g2_renko_wma_15m`) | Current Renko route; candidate V3 is not yet materialized |
| 9222 | `4D5DE25E24A09C8E51585147B624D85A` | `ocVwlz2C` (`g3_dxy1m_xau15s`) | TVC:DXY 1m and ICMARKETS:XAUUSD 15s |
| 4999 | `F2F27AAA3050DC8F9769939CB9B2E84C` | `gwnVPYuQ` (`New`) | Acceptance only; forbidden for production evidence |

The other existing 9222 layouts remain supplemental visual charts, not
substitutes for the approved 9333 numeric authorities.

## 4. Source details

### 4.1 `LIQ_V2_R9`

- **Primary dimension:** level location and lifecycle.
- **Secondary dimensions:** 1–4 timeframe confluence, touch count, first-touch
  status, and PRIME/VALID/WEAK grade.
- **Confirmed behavior:** pivot and lifecycle updates use confirmed bars and
  lookahead-off higher-timeframe requests.
- **Numeric outputs available in source:** scalar `level_price`, side, anchor
  timeframe, confluence count, touch count, and overlap bounds.
- **Event outputs:** TOUCH by default; optional READY, REJECT, BREAK and PRIME.
- **Known gaps:** current market value is not a separate event field; the
  existing event field named `price` means level value. Band width, reaction
  magnitude, event timestamp, distance, and source revision/hash are absent from
  the event payload. Those gaps are `MISSING_REQUIRES_PRODUCER_CHANGE`.
- **Legacy replacement:** approved V1 replacement authority for `levelEngine/1`;
  there is no
  parity between them.

Its conventional side meaning is `ASK` for a high/resistance level and `BID`
for a low/support level. The Product Input contract must normalize the source's
ambiguous event field to `level_price` and separately snapshot
`current_market_price`.

`LIQUIDITY_DISTANCE_POLICY_V1.md` approves side-aware pre-touch distance using a
fresh current XAU observation and the latest confirmed, exactly-fresh 5m
ATR(14). It defines FAR above 0.50 ATR, APPROACH above 0.25 through 0.50 ATR,
and NEAR_TOUCH above zero through 0.25 ATR. Distance never manufactures HIT,
REJECT, BREAK, trade direction or grade A. This policy approval does not change
`SAVED_NOT_MATERIALIZED` or activate Product Input runtime.

### 4.2 `EXP_V3_R5` and `EXP_SCANNER_R6`

`EXP_V3_R5` is the approved confirmed trigger authority. Its default logic uses a five-bar
leg, ATR14, minimum 1.2 ATR displacement, minimum 0.60 path efficiency, a
five-bar cooldown, and confirmed-bar gating. It supplies direction,
displacement, ATR-normalized displacement, and path efficiency internally. Its
text event includes ticker, timeframe, movement direction, and a field labelled
`Price`. The bounded legacy `/alert` compatibility adapter treats that value as
the source-reported event `market_price`; it does not promote it to a trade
`signal_price` or entry price.

`EXP_SCANNER_R6` is quality classification only. It distinguishes CLEAN/WEAK and
too-extended movement using displacement/range, candle-body quality and opposing
bars. It is not a second trigger authority.

Known gaps across the pair are explicit expansion start value, speed, age,
exhaustion lifecycle, and a revision-pinned numeric payload. Missing values are
`MISSING_REQUIRES_PRODUCER_CHANGE`. `expDetector/1` is not parity with either
source and is not the V1 authority.

### 4.3 `MACD_TV_9333_12_26_9`

- **Primary dimension:** price momentum by timeframe.
- **Secondary dimensions:** histogram slope, weakening, flip and MTF alignment.
- **Settings:** close, fast EMA 12, slow EMA 26, signal EMA 9.
- **Numeric outputs:** closed-bar close, MACD line, signal line, histogram,
  previous histogram, histogram delta, sign and source-bar time.
- **Event outputs:** Project A derives deterministic expansion/weakening/flip
  states from closed numeric bars; no Pine JSON is authoritative.
- **Confirmation:** only the latest fully closed source bar is admissible.
- **Known gap:** 5s timing is not supplied.

`macdVol/1` is directional-volume logic and is not the standard 9333 price-MACD
authority.

### 4.4 DXY authorities

`DXY_TVC_9333_15M` is primary. It supplies the latest confirmed 15m close,
previous close, change, SMA20, distance from SMA20, source-bar time and freshness.
`DXY_TVC_9222_1M` is supplemental and may add short-horizon price/change context.

DXY is evidence and may cap a grade when materially conflicting. It is not a
universal hard veto. `dxyReader/3` remains optional supporting divergence logic,
not current runtime authority. No DXY source may silently replace missing XAU,
MACD or Renko evidence.

### 4.5 `RENKO_V3_SNIPER_R1`

- **Primary dimension:** maturity from E1 to E2 to Main and final 5s FIRE timing.
- **Secondary dimensions:** WMA/EMA alignment, fade/touch/MACD-turn score, power,
  mode and transfer state.
- **Dependencies:** EMA45; WMA 7/14/21/34/55/80; source box-size input; Sniper
  WMA45 and ATR logic.
- **Events:** Main direction event and Sniper FIRE event.
- **Confirmation:** FIRE is explicitly confirmed. E1/E2 drawing state lacks an
  event-level confirmation field.
- **Known gaps:** E1/E2 event value, source-bar time, age, event identity and TTL
  are not exported. Main lacks a producer event identity and explicit event
  timestamp. All are `MISSING_REQUIRES_PRODUCER_CHANGE`.

The current 9222 chart instead loads an older Renko V2 revision. Therefore this
candidate must not be called runtime-active. `rekoArrow/1` is not Renko V3
parity.

### 4.6 Structure and visual context

`STRUCTURE_9333_XAU_HTF` is the approved numeric authority for confirmed 4H/D/W
direction and price structure. Trend/range classification, break identity and
nearest-obstacle outputs require deterministic definitions before use; absent
values are `MISSING_REQUIRES_PRODUCER_CHANGE`.

`SR_MTF_V10_CONTEXT` remains visual/supporting context only in V1. Its currently
loaded settings disable most structure, confirmation, confluence, gate and
MACD-volume surfaces, so it must not silently become numeric authority.
`structState/1` is a legacy regime derived from `levelEngine/1`, not the approved
structure source.

### 4.7 Legacy `/alert` compatibility adapter status

The repository parser now has two narrow, telemetry-only compatibility paths:

- Expansion V3 text must match
  `EXP UP|DOWN | SYMBOL | TF <integer-minutes> | Price <positive-number>`;
  exchange-qualified symbols such as `ICMARKETS:XAUUSD` are allowed. The adapter
  emits `EXP_UP` or `EXP_DOWN`, records `move_dir=UP|DOWN`, keeps trade `dir=null`,
  and records the source-reported event value as `market_price`. It does not
  derive LONG/SHORT, entry, stop, target, grade, confirmation status or source
  timestamp.
- Liquidity V2 JSON must identify `engine=LIQ_V2` and include a bounded event,
  `side=ASK|BID`, minute timeframe, positive `price`, `mtf=n/4`, and a
  non-negative touch count. The adapter maps bare source `price` to
  `level_price`; `market_price` and `signal_price` remain null. `ASK` means the
  upper/resistance role and `BID` the lower/support role; neither implies trade
  direction.

Both paths retain the exact received source payload inside legacy `raw`
evidence and carry an explicit telemetry-only marker. They cannot independently
wake analysis or satisfy the overlapping legacy EXP/LIQ MRF rule. Malformed or
unsupported input fails closed as `UNKNOWN`. Existing legacy SNR, SR, Renko and
MRF formats keep their established behavior.

This repository adapter status is not Product Input runtime activation. A
currently running non-reload server continues using its pre-change loaded code
until a separately authorized controlled restart from the integrated revision.
Previously misclassified SQLite rows remain immutable audit history; no row is
silently rewritten. Their retained raw text permits a separately reviewed future
correction/replay process.

## 5. Legacy-source disposition

| Legacy source | V1 disposition |
|---|---|
| `levelEngine/1` | `LEGACY_REFERENCE`; not Liquidity V2 parity |
| `expDetector/1` | `LEGACY_REFERENCE`; not Expansion V3 parity |
| `macdVol/1` | `LEGACY_REFERENCE`; not the standard 9333 MACD authority |
| `rekoArrow/1` | `LEGACY_REFERENCE`; not Renko V3 parity and lacks E1/E2/Main/Sniper mapping |
| `dxyReader/3` | `LEGACY_REFERENCE`; optional supporting logic, not current runtime authority |
| `structState/1` | `LEGACY_REFERENCE`; derived regime, not 9333 structure authority |

No existing frozen contract, fixture, reader or historical event is re-labelled
by this proposal.

## 6. Fail-closed authority behavior

- Every observation carries `authority_id`, port, layout ID, target ID, source
  revision/hash where available, source-bar time, receipt time, and confirmation
  status.
- An identity mismatch, unavailable port, stale source bar, non-finite number,
  missing required evidence, or unexpected timeframe produces an explicit
  unavailable/error state. It never produces a substituted value.
- A missing numeric field is `null` and is listed with reason
  `MISSING_REQUIRES_PRODUCER_CHANGE`; zero is never a missing-value sentinel.
- Provisional evidence cannot satisfy a confirmed gate unless a Jones-approved
  rule explicitly permits it.
- `4999` evidence is always rejected from production state construction.
