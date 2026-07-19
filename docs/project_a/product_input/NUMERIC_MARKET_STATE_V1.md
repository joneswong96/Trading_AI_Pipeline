# Project A Numeric Market State V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

The authority composition and field semantics are approved. Exact freshness
thresholds, producer changes, runtime validation and executable schema work remain
pending and fail closed.

This document defines a data contract, not an executable JSON Schema or producer.

## 1. Contract-wide conventions

- Field names use `snake_case`.
- Timestamps are UTC RFC 3339 strings ending in `Z`.
- Price-like values use native ICMARKETS:XAUUSD or TVC:DXY quote units and carry
  `price_unit=QUOTE` unless an approved normalization says otherwise.
- Durations use seconds; bar ages may additionally use integer bars.
- Ratios use decimal units; percentages use explicit `_pct` names.
- Direction values are `LONG`, `SHORT`, or `NEUTRAL` where a trade direction is
  intended, and `UP`, `DOWN`, or `FLAT` for observed movement.
- Confirmation is `CONFIRMED` or `PROVISIONAL`, accompanied by a boolean
  `confirmed` for consumers that require a strict gate.
- The bare field name `price` is forbidden. Use `level_price`, `market_price`,
  `signal_price`, `entry_price`, or another dimensioned name.
- A source that cannot expose a required value records `null`, lists the field in
  `missing_fields`, and uses reason `MISSING_REQUIRES_PRODUCER_CHANGE`.
- Non-finite numbers, guessed screenshot values, ambiguous units, stale data and
  identity mismatches fail closed.

## 2. Canonical envelope and identity

| Field | Type/unit | Requirement |
|---|---|---|
| `schema_version` | string | Contract label `project_a.numeric_market_state/1.0`; no executable schema is authorized by this approval |
| `state_id` | string | Deterministic identifier from the canonical snapshot content and lineage |
| `setup_id` | string | Stable identity for one setup lifecycle; never reused after reset/expiry/invalidation |
| `symbol` | string | `XAUUSD` for Project A V1 |
| `feed` | string | `ICMARKETS` for XAU evidence; individual DXY records use `TVC` |
| `source_port` | integer | Exactly 9333 or 9222 for production evidence; 4999 rejected |
| `source_layout_id` | string | Pinned TradingView layout ID |
| `source_target_id` | string | CDP process-lifetime target bound to the port/layout during preflight |
| `authority_id` | string | ID from `PRODUCT_INPUT_AUTHORITY.md` |
| `source_revision` | string/null | Pine saved revision or built-in/settings identity |
| `source_sha256` | string/null | Lower-case SHA-256 when available |
| `observed_at` | timestamp | When the bounded observation was taken |
| `source_bar_time` | timestamp | Time identity of the source bar used |
| `received_at` | timestamp | Local trusted receipt time |
| `confirmation_status` | enum | `CONFIRMED` or `PROVISIONAL` |
| `confirmed` | boolean | True only when source-specific close rules pass |
| `freshness_status` | enum | `FRESH`, `STALE`, `MARKET_CLOSED_STALE`, `FUTURE`, `UNKNOWN` |
| `freshness_age_seconds` | seconds | `received_at - source_bar_time`, calendar-aware for classification |
| `missing_fields` | list | Field names with explicit reason codes; never silently omitted |
| `errors` | list | Stable code, authority, field, and non-secret diagnostic text |

`observed_at`, `source_bar_time`, and `received_at` are distinct. Client-provided
receipt time must not override the locally observed receipt time.

## 3. Price-path state

| Field | Type/unit | Derivation and authority |
|---|---|---|
| `current_market_price` | decimal/QUOTE | Exact structured XAU observation from 9333 |
| `previous_event_market_price` | decimal/QUOTE | Market snapshot bound to the prior accepted event in this setup |
| `previous_snapshot_market_price` | decimal/QUOTE | Immediately preceding append-only snapshot |
| `market_price_delta` | decimal/QUOTE | Current minus selected previous market value |
| `market_price_delta_pct` | decimal/percent | Delta divided by previous market value times 100 |
| `market_movement_direction` | enum | `UP`, `DOWN`, or `FLAT` from the signed delta |
| `elapsed_seconds` | decimal/seconds | Difference between the paired source timestamps |
| `market_velocity_quote_per_second` | decimal/QUOTE-per-second | Delta divided by positive elapsed seconds; otherwise unavailable |
| `closed_ohlc_by_timeframe` | records/QUOTE | 1m, 5m, 15m, 30m, 4H, D and W as required by the evidence bundle |
| `price_source_authority_id` | string | Normally `MACD_TV_9333_12_26_9` for 1m–30m and `STRUCTURE_9333_XAU_HTF` for HTF |

Every OHLC record contains timeframe, open/high/low/close, source-bar time,
confirmation status and freshness. A delta with no valid predecessor is `null`,
not zero.

## 4. Liquidity state

| Field | Type/unit | Current source availability |
|---|---|---|
| `liquidity_level_id` | string | Producer identity absent: `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `liquidity_side` | enum | `ASK` resistance/high or `BID` support/low from V2 |
| `liquidity_level_price` | decimal/QUOTE | Available from V2 state/event after normalization |
| `liquidity_current_market_price` | decimal/QUOTE | Bounded 9333 snapshot at event time |
| `liquidity_distance_quote` | decimal/QUOTE | Market value minus level value; signed |
| `liquidity_distance_points` | decimal/points | Absolute distance divided by an approved point size |
| `liquidity_distance_atr` | decimal/ATR multiples | Absolute distance divided by matched-timeframe ATR |
| `liquidity_timeframe` | string | V2 anchor `5m`; MTF contributors recorded separately |
| `liquidity_mtf_confluence_count` | integer/count | 1–4 |
| `liquidity_mtf_confluence_total` | integer/count | Exactly 4 for V2 policy |
| `liquidity_touches` | integer/count | Non-negative V2 touch count |
| `liquidity_sweeps` | integer/count or null | V2 does not export sweep state: `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `liquidity_first_touch` | boolean | True only for the first confirmed touch |
| `liquidity_rejection_confirmed` | boolean/null | True only for a confirmed REJECT event; null before the producer exposes it |
| `liquidity_grade` | enum | `PRIME`, `VALID`, or `WEAK` |
| `liquidity_lifecycle` | enum | `IDLE`, `APPROACH`, `HIT`, `REJECT`, or `BREAK` |
| `liquidity_event_time` | timestamp | Missing in current payload: `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `liquidity_band_low` / `liquidity_band_high` | decimal/QUOTE or null | Use only if the producer exposes an authoritative band; otherwise missing |
| `liquidity_freshness_status` | enum | Contract-wide freshness values |
| `liquidity_confirmed` | boolean | True only for a confirmed V2 lifecycle event |

The source event's bare `price` member is never propagated. It is interpreted as
`liquidity_level_price`; `liquidity_current_market_price` comes from the bounded
event-time 9333 snapshot.

## 5. Expansion state

| Field | Type/unit | Current source availability |
|---|---|---|
| `expansion_direction` | enum | `LONG`, `SHORT`, or `NEUTRAL` |
| `expansion_start_market_price` | decimal/QUOTE | Not exported: `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `expansion_current_market_price` | decimal/QUOTE | 9333 bounded snapshot |
| `expansion_displacement_quote` | decimal/QUOTE | V3 internal value; not exported numerically |
| `expansion_atr` | decimal/QUOTE | V3 internal ATR14; not exported numerically |
| `expansion_atr_multiple` | decimal/ATR multiples | Displacement magnitude divided by ATR |
| `expansion_path_efficiency` | decimal/ratio 0–1 | V3 internal value; not exported numerically |
| `expansion_velocity_quote_per_second` | decimal/QUOTE-per-second | Requires start value/time; currently missing |
| `expansion_body_quality` | decimal/ratio 0–1 | Scanner internal value; not exported numerically |
| `expansion_opposing_bars` | integer/count | Scanner internal value; not exported numerically |
| `expansion_age_bars` | integer/bars | Not exported |
| `expansion_age_seconds` | decimal/seconds | Not exported |
| `expansion_confirmed` | boolean | V3 trigger confirmed by default; Scanner quality recorded separately |
| `expansion_quality` | enum | `CLEAN`, `WEAK`, or `UNKNOWN` from Scanner |
| `expansion_too_extended` | boolean/null | Scanner condition; null when unavailable |
| `expansion_source_trigger` | enum | `EXP_UP`, `EXP_DOWN`, or `NONE` |
| `expansion_signal_price` | decimal/QUOTE | V3 close after normalization |

Every V3/Scanner internal numeric output that lacks a producer field remains
`MISSING_REQUIRES_PRODUCER_CHANGE`; downstream code must not reconstruct it from
screenshots.

## 6. MACD state

For each of `1m`, `5m`, `15m`, and `30m`, the 9333 authority records:

| Field | Type/unit |
|---|---|
| `macd_close` | decimal/QUOTE |
| `macd_line` | decimal/QUOTE |
| `macd_signal_line` | decimal/QUOTE |
| `macd_histogram` | decimal/QUOTE |
| `macd_previous_histogram` | decimal/QUOTE |
| `macd_histogram_delta` | decimal/QUOTE-per-bar |
| `macd_histogram_sign` | `POSITIVE`, `NEGATIVE`, or `ZERO` |
| `macd_momentum_state` | `BULL_EXPANSION`, `BULL_WEAKENING`, `BEAR_EXPANSION`, `BEAR_WEAKENING`, `FLAT`, or `FLIP` |
| `macd_flip_direction` | `LONG`, `SHORT`, or `NONE` |
| `macd_source_bar_time` | UTC timestamp |
| `macd_confirmed` | boolean; required true for gates |
| `macd_freshness_status` | contract-wide freshness enum |

The histogram delta is current confirmed histogram minus the previous confirmed
histogram. `FLIP` records a sign transition; expansion/weakening remains available
as the associated before/after classification. Alignment is a deterministic list
of timeframe states, not a separately guessed score.

## 7. DXY state

| Field | Type/unit | Authority |
|---|---|---|
| `dxy_15m_market_price` | decimal/DXY index points | 9333 current structured observation |
| `dxy_15m_close` | decimal/DXY index points | Latest confirmed 15m bar on 9333 |
| `dxy_15m_change` | decimal/DXY index points | Current confirmed close minus previous confirmed close |
| `dxy_15m_change_pct` | decimal/percent | Explicit percentage change |
| `dxy_15m_sma20` | decimal/DXY index points | SMA20 from closed 15m bars |
| `dxy_15m_distance_sma20` | decimal/DXY index points | Close minus SMA20 |
| `dxy_15m_distance_sma20_pct` | decimal/percent | Explicit percentage distance |
| `dxy_1m_market_price` | decimal/DXY index points | Supplemental 9222 observation |
| `dxy_1m_change` | decimal/DXY index points | Supplemental confirmed-bar change when available |
| `dxy_direction` | `UP`, `DOWN`, or `FLAT` | Deterministic configured-band classification |
| `dxy_xau_relationship` | `CONFIRM`, `CONFLICT`, or `NEUTRAL` | Evidence/grade-cap only |
| `dxy_15m_source_bar_time` / `dxy_1m_source_bar_time` | timestamp | Kept separately; no false alignment |
| `dxy_freshness_status` | enum | Recorded per timeframe |

No DXY value is a universal hard veto. Missing supplemental 1m DXY does not
replace or invalidate primary 15m DXY, but it is recorded as unavailable.

## 8. Renko state

| Field | Type/unit | Current source availability |
|---|---|---|
| `renko_e1_direction` | `LONG`, `SHORT`, or `NONE` | Source logic exists; event output missing |
| `renko_e1_signal_price` | decimal/QUOTE | `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `renko_e1_source_bar_time` | timestamp | `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `renko_e1_age_seconds` | seconds | Requires event time; currently missing |
| `renko_e1_confirmed` | boolean/null | Explicit event confirmation missing |
| `renko_e2_direction` | `LONG`, `SHORT`, or `NONE` | Source logic exists; event output missing |
| `renko_e2_signal_price` | decimal/QUOTE | `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `renko_e2_source_bar_time` | timestamp | `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `renko_e2_age_seconds` | seconds | Requires event time; currently missing |
| `renko_e2_confirmed` | boolean/null | Explicit event confirmation missing |
| `renko_main_direction` | `LONG`, `SHORT`, or `NONE` | Main event logic exists |
| `renko_main_signal_price` | decimal/QUOTE | Available in Main event after normalization |
| `renko_main_source_bar_time` | timestamp | Missing from payload; bounded snapshot may bind it |
| `renko_main_age_seconds` | seconds | Derived only after an authoritative event time exists |
| `renko_main_confirmed` | boolean | Main alert has an explicit confirmed gate |
| `renko_sniper_fire_direction` | `LONG`, `SHORT`, or `NONE` | FIRE event |
| `renko_sniper_score` | integer/points 0–100 | FIRE event |
| `renko_sniper_power` | source enum/string | FIRE event; allowlist required before runtime |
| `renko_sniper_mode` | `WEAK`, `1R:1R`, `RUNNER`, or `SWING` | FIRE event |
| `renko_sniper_transfer` | `5s ONLY`, `15s PUSH`, or `1m PUSH` | FIRE event |
| `renko_sniper_signal_price` | decimal/QUOTE | FIRE event |
| `renko_sniper_source_bar_time` | timestamp | Missing from current payload |
| `renko_maturity_level` | `NONE`, `E1`, `E2`, `MAIN`, or `SNIPER_FIRE` | Highest currently valid evidence, not assumed sequential |
| `renko_reset_reason` | stable enum | Opposite cycle, Main completion, invalidation, expiry, or source reset |
| `renko_invalidation_condition` | structured text/reference | Must be explicit; no inferred TTL |
| `renko_source_revision` | string | `1` |
| `renko_source_sha256` | string | Pinned candidate hash |

E1 is not required before E2. Exact four-of-six and five-of-six predicates cannot
fire on the same bar, but E1/E2/Main may occur during one broader setup on
different bars. The Main cross TTL is not an E1/E2 event TTL.

## 9. Structure/regime state

| Field | Type/unit | Current source availability |
|---|---|---|
| `structure_4h_direction` | `UP`, `DOWN`, or `FLAT` | Exact from approved deterministic 4H rule |
| `structure_daily_direction` | `UP`, `DOWN`, or `FLAT` | Exact from approved deterministic daily rule |
| `structure_weekly_direction` | `UP`, `DOWN`, or `FLAT` | Exact from approved deterministic weekly rule |
| `structure_regime` | `TREND`, `RANGE`, or `AMBIGUOUS` | Rule not yet approved: `MISSING_REQUIRES_PRODUCER_CHANGE` |
| `structure_break_level_price` | decimal/QUOTE | Rule/output missing |
| `structure_last_break_direction` | `UP`, `DOWN`, or `NONE` | Rule/output missing |
| `structure_last_break_time` | timestamp | Rule/output missing |
| `structure_nearest_obstacle_level_price` | decimal/QUOTE | Rule/output missing |
| `structure_confirmed` | boolean | True only from closed 4H/D/W evidence |
| `structure_freshness_status` | enum | Calendar-aware per timeframe |

SR MTF Pro V10 may be referenced visually, but its visual labels do not populate
these numeric fields in V1.

## 10. Risk and availability

| Field | Type/unit | V1 behavior |
|---|---|---|
| `bid_market_price` | decimal/QUOTE or null | Unavailable until a trusted source is approved |
| `ask_market_price` | decimal/QUOTE or null | Unavailable until a trusted source is approved |
| `spread_value` | decimal or null | Unavailable until a trusted source is approved |
| `spread_unit` | `POINTS`, `QUOTE`, or null | Null while spread is unavailable |
| `risk_data_source` | authority ID or null | Null while no authority is approved |
| `risk_availability_status` | enum | `AVAILABLE`, `UNAVAILABLE`, or `INVALID` |

The current bid, ask and spread are `null` with availability `UNAVAILABLE`. They
must not be estimated from screenshot pixels or replaced with zero. Any gate that
requires spread remains blocked.

## 11. Append-only history and price memory

The canonical history consists of immutable `SOURCE_EVENT`, `EVENT_SNAPSHOT`,
`CLOSED_BAR_SNAPSHOT`, `STATE_TRANSITION`, `RECONCILIATION`, `INVALIDATION`,
`EXPIRY`, and `NOTIFICATION` records.

Every accepted source event causes a bounded event-time snapshot from 9333 and,
when Renko is involved, a bounded supplemental 9222 read. Periodic closed-bar
snapshots may occur only at required timeframe closures. Tick-level continuous
polling is outside V1.

Each history record must preserve enough information to reconstruct:

- previous and current market values, direction, distance travelled and elapsed
  time;
- distance to liquidity before and after the event;
- expansion maturity and quality;
- MACD transition by timeframe;
- DXY transition;
- Renko maturity transition; and
- structure transition.

Required lineage includes source timestamp, receipt timestamp, confirmation
status, authority ID, port/layout/target, source revision/hash, parent event ID,
setup ID and the resulting state ID.

### 11.1 Duplicate and idempotency rules

1. **Exact duplicate:** suppress only when the SHA-256 of canonical source
   identity, source event identity, source-bar time, confirmation status and
   normalized payload is identical.
2. **Semantic idempotency:** use a deterministic key over setup ID, authority ID,
   event type, direction, level ID where applicable, normalized signal or level
   value, source-bar time and source revision/hash.
3. A provisional observation followed by a confirmed observation is not silently
   overwritten. Append a `RECONCILIATION` record linked to both.
4. Conflicting events with the same semantic key are retained, marked conflict,
   and fail the affected gate.
5. Rebuild order is source timestamp, trusted receipt timestamp, then canonical
   record hash. Replaying the same history must yield the same state ID.
6. No mutable “latest” row is authoritative; any cache is a disposable projection
   of append-only history.

## 12. Null and error behavior

- Required but unavailable data stays `null` and appears in `missing_fields`.
- `MISSING_REQUIRES_PRODUCER_CHANGE` means the selected source cannot currently
  expose the field; retries alone cannot cure it.
- `SOURCE_UNAVAILABLE`, `IDENTITY_MISMATCH`, `STALE_SOURCE_BAR`,
  `FUTURE_SOURCE_BAR`, `UNIT_AMBIGUOUS`, `NON_FINITE_VALUE`, and
  `CONFIRMATION_REQUIRED` are distinct fail-closed conditions.
- Partial state may support `C_INSUFFICIENT`; it may not be promoted to a higher
  story state when a required gate is missing.
- Errors contain no credentials, browser profile paths, cookies, tokens or
  unrelated account data.
