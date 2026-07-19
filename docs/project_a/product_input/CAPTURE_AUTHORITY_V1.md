# Project A Capture Authority V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE — PENDING_RUNTIME_VALIDATION**

The B-to-A trigger, port roles, hybrid evidence routes, no-fallback rule and
no-mutation boundary are approved. Exact timeframe freshness thresholds and
production layout materialization remain pending.

Trigger: entry into `B_TO_A_CANDIDATE`

## 1. Authority boundary

- Primary structured numeric source: CDP `9333`.
- Supplemental Renko/chart source: CDP `9222`.
- `4999` is forbidden for production evidence.
- No port, layout, target, symbol, feed, timeframe or indicator fallback is
  permitted.
- Screenshots provide visual big-picture context. Structured reads provide exact
  numeric authority.
- Capture is read-only: no tab activation that changes chart state, no layout or
  setting edits, no alert interaction, and no save/publish action.

## 2. Exact route allowlist

| Port | Layout ID | Target observed in the authority audit | Required identity and role |
|---:|---|---|---|
| 9333 | `cpPWuLlN` | `1BFD5343A964E20E4A32CAA1BA59ADDA` | `g4_5m_1m`; ICMARKETS:XAUUSD 5m/1m; standard MACD 12/26/9 |
| 9333 | `avpCVaw2` | `3A1DA8E727112BD7F13732B3A8732DFE` | `g5_30m`; ICMARKETS:XAUUSD 30m/15m; standard MACD 12/26/9 |
| 9333 | `pNqcbOmu` | `1E5C0F56E8154C894E36377A6B7A7C0C` | `g6_HTF`; ICMARKETS:XAUUSD 4H/D/W |
| 9333 | `n9qjfufV` | `3818934C8C5F18141069CF3E7ABAB8E7` | `g7_DXY`; TVC:DXY 15m |
| 9222 | `paH6jur7` | `ACF2304D2914588BDCBED4238C692328` | `g2_renko_wma_15m`; proposed Renko V3 source must be materialized and independently validated before use |
| 9222 | `ocVwlz2C` | `4D5DE25E24A09C8E51585147B624D85A` | `g3_dxy1m_xau15s`; TVC:DXY 1m supplemental evidence |

CDP target IDs may change after a Chrome restart. A read-only preflight must bind
the current target to the exact pinned port and TradingView layout ID and record
that mapping in the bundle manifest. A changed target fails the current attempt
until explicitly rebound; it never authorizes a different layout or port.

## 3. Trigger and no-duplicate behavior

The sole trigger is an append-only transition into `B_TO_A_CANDIDATE`. The
capture idempotency key is the SHA-256 of:

- schema/capture-contract version;
- setup ID;
- predecessor and candidate state IDs;
- transition event ID and source time; and
- the ordered authority/revision/hash set.

An identical key returns the previously committed bundle reference. It does not
take new screenshots or issue new structured reads. A retry after a partial
failure writes a linked attempt record and may complete only the missing
artifacts; it must not overwrite a prior artifact.

## 4. Required screenshots

One bounded bundle requires these exact visual artifacts:

1. `9333/cpPWuLlN`: XAUUSD 5m and 1m with readable standard MACD panes.
2. `9333/avpCVaw2`: XAUUSD 30m and 15m with readable standard MACD panes.
3. `9333/pNqcbOmu`: XAUUSD 4H/D/W big-picture structure.
4. `9333/n9qjfufV`: TVC:DXY 15m.
5. `9222/paH6jur7`: the validated Renko V3/Sniper chart.

The 9222 DXY 1m layout is a required structured supplemental read but needs a
screenshot only when a DXY 1m transition materially affects review. SR MTF Pro
V10 may appear as visual context; its visual text is not numeric authority.

A screenshot records port, layout ID, target ID, page URL identity, observed time,
pixel dimensions, media type, byte length and SHA-256. Screenshot OCR or visual
estimation may not populate numeric fields.

## 5. Required structured reads

At candidate time `T`, the bundle must include:

- XAU current structured market value and latest fully closed OHLC for 1m, 5m,
  15m and 30m from 9333;
- standard MACD line, signal line, histogram, previous histogram and source-bar
  time for each of those four timeframes;
- latest fully closed XAU 4H/D/W OHLC and approved structure outputs from 9333;
- TVC:DXY 15m current value, closed close/change/SMA20/distance and bar time from
  9333;
- TVC:DXY 1m supplemental current/closed values and bar time from 9222;
- Liquidity V2 and Expansion source event lineage plus bounded 9333 event-time
  snapshots;
- Renko E1/E2/Main/FIRE state and event lineage from the validated 9222 candidate;
  and
- every missing producer field explicitly listed as
  `MISSING_REQUIRES_PRODUCER_CHANGE`.

Bid, ask and spread remain unavailable and block any approved gate that requires
them.

## 6. Freshness and source-bar alignment — pending

Status: **PENDING_RUNTIME_VALIDATION**. The following draft thresholds are not
approved and cannot activate a gate:

1. Every gate uses the most recent fully closed source bar at or before `T`; no
   future or still-forming source bar can satisfy a confirmed field.
2. Intraday delivery lag from expected bar close to trusted receipt must not
   exceed two source-bar durations: 2 minutes for 1m, 10 minutes for 5m, and 30
   minutes for 15m. The proposed 30m maximum is 30 minutes, not 60 minutes.
3. Renko 5s FIRE must be confirmed and received no later than 10 seconds after
   its source-bar close. E1/E2/Main age is unavailable until producer event times
   exist.
4. 4H/D/W freshness is calendar-aware and requires the latest closed TradingView
   bar expected for the feed session, rather than a raw wall-clock age alone.
5. All records must satisfy `source_bar_time <= observed_at <= received_at`, apart
   from a separately approved clock-skew tolerance. No tolerance is assumed here.
6. The 1m, 5m, 15m and 30m bars need not share one timestamp, but each must be the
   latest confirmed bar at or before the same capture time `T`. The manifest
   records `T` and every individual bar identity.

These exact thresholds remain pending Jones approval. Until approved and
implemented, freshness-dependent capture and promotion fail closed.

## 7. Bundle integrity

The immutable manifest contains:

- contract version, setup/state/transition IDs and capture time `T`;
- every authority ID, port, layout, target, symbol/feed, timeframe, source
  revision/hash and confirmation status;
- ordered artifact records with relative logical name, media type, bytes and
  SHA-256;
- structured-read canonical SHA-256 values;
- missing/error records;
- predecessor bundle/reference when retrying; and
- one manifest SHA-256 calculated after artifact hashes are fixed.

No machine-local absolute path is part of the production manifest. Storage paths
are deployment configuration, not evidence identity.

## 8. Missing, stale and weekend behavior

- Missing required evidence, identity mismatch, stale/future data, invalid hash,
  non-finite numeric input or unvalidated Renko V3 causes a failed bundle. The
  story does not advance.
- Optional DXY 1m evidence may be unavailable without substituting 15m or another
  port; its absence is explicit and may lower confidence under approved policy.
- During a weekend or known market closure, old bars are classified
  `MARKET_CLOSED_STALE`. A diagnostic bundle may be created for read-path testing,
  but it cannot trigger final review, `A_CONFIRMED`, or notification.
- On market reopen, each required intraday timeframe must first produce a fresh
  fully closed bar. Pre-open bars are not carried forward as fresh evidence.

## 9. Restoration and no-mutation rules

Capture must leave tab count, target mapping, layout, symbol, feed, timeframe,
chart type, visible indicators, indicator inputs, drawings, alert state and
profile unchanged. Existing alerts remain untouched and the Alerts panel remains
closed. No broker, MT5, webhook, order, Pine save/publish or provider action is
part of capture.

The post-capture verifier compares the observed identity map with preflight. Any
drift fails the bundle and is reported; the capture process does not repair it.
