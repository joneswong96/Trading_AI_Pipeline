# Project A Freshness Policy V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

Approver: Jones Wong

Approval date: 2026-07-20 Australia/Sydney

Scope: deterministic freshness policy only; no runtime, producer, provider,
TradingView or writer activation

## 1. Purpose and separation from signal validity

Project A must never treat an old but successfully extracted value as current
market evidence. Freshness answers whether an observation is temporally usable
for an approved role. Signal validity or TTL answers whether the signal remains
logically valid. They are separate gates:

- a temporally fresh observation may contain an invalid or expired signal;
- a stale observation cannot be promoted even when its signal claims validity;
- E1/E2/Main validity and TTL are not defined by this policy; and
- weekend or closed-market evidence may remain historical context but cannot be
  current execution evidence.

Every freshness decision records its status, maximum-age rule, measured age,
timestamp basis, source identity and deterministic reason. No non-`FRESH` status
is silently converted to `FRESH`.

## 2. Canonical timestamps

Freshness uses UTC and, as applicable:

| Field | Meaning |
|---|---|
| `source_observed_at` | Timestamp emitted by the approved source/producer for its observation or event; never replaced by receipt time |
| `source_bar_time` | Source bar identity with required `source_bar_time_semantics` of `OPEN` or `CLOSE` |
| `source_bar_close_time` | Actual or deterministically derived bar-close time used for closed-bar age |
| `observed_at` | Trusted UTC time when Project A directly read the source |
| `received_at` | Trusted UTC time when the ingest boundary received an event |
| `capture_started_at` | Trusted UTC start of the bounded capture operation |
| `capture_completed_at` | Trusted UTC completion of the bounded capture operation |
| `trusted_now_utc` | Current trusted UTC time used for the decision |

Australia/Sydney is presentation-only and is never canonical storage or
calculation time.

### 2.1 Bar-time semantics

- `source_bar_time` must state whether it is bar open or bar close.
- Closed-bar age is calculated from `source_bar_close_time`, not merely the bar's
  open time.
- If a source supplies only bar-open time, the collector may derive bar-close
  time only from an approved timeframe/session rule and must record
  `source_bar_close_time_derived=true`. If session boundaries make that derivation
  ambiguous, the close time is `MISSING`.
- `observed_at` is the direct-read time. `received_at` is transport evidence for
  an event and cannot replace missing `source_observed_at`, source event time or
  `source_bar_close_time`.
- Server receipt time is used only for transport and audit calculations.
- Time calculations use UTC. Negative durations are forbidden.
- A timestamp more than 10 seconds in the future relative to the relevant trusted
  comparison time is `CLOCK_INVALID`.
- A future skew from 0 through 10 seconds is recorded as
  `future_skew_seconds`; age is recorded as zero rather than a negative duration.
- Malformed timestamps or impossible source/bar/observation/receipt/capture
  ordering are `CLOCK_INVALID`.

## 3. Freshness status enum

| Status | Definition and allowed use |
|---|---|
| `FRESH` | Age is below 75% of the approved maximum, the source is confirmed where required, and the value is suitable for its approved role. |
| `AGING` | Age is at least 75% of the maximum and no greater than the maximum. It remains within the maximum-age window but is never labeled `FRESH`. A gate that explicitly requires `FRESH` rejects it. |
| `STALE` | Age is greater than the approved maximum. It cannot promote an actionable state. |
| `MARKET_CLOSED` | A separately approved deterministic market/feed-open source says the relevant market/feed is closed or not expected to produce bars. Historical context may be displayed only as `CONTEXT_CARRY_FORWARD`. |
| `MISSING` | A required value or timestamp is absent. |
| `CLOCK_INVALID` | A timestamp is malformed, more than 10 seconds in the future, produces impossible ordering, or would require a negative duration. |
| `SOURCE_UNAVAILABLE` | The approved route cannot be read and no approved explicit supplemental source can supply that exact role. |
| `PROVISIONAL` | The value belongs to a developing bar or unconfirmed event. It may inform B-building only where explicitly allowed and cannot establish A confirmation. |

Status precedence prevents a less severe label from hiding a hard failure:
`MISSING`/`CLOCK_INVALID`/`SOURCE_UNAVAILABLE`/`MARKET_CLOSED` first, then
`STALE`, then `PROVISIONAL`, then `AGING`, then `FRESH`. Exact error precedence
between simultaneous hard failures is recorded without discarding any reason.

For a maximum age `M` and non-negative age `A`:

- `FRESH` when `0 <= A < 0.75 × M`;
- `AGING` when `0.75 × M <= A <= M`; and
- `STALE` when `A > M`.

At exactly 75%, status is `AGING`. At exactly the maximum, status remains
`AGING`; it becomes `STALE` only when older than the maximum.

## 4. Approved maximum ages during normal open-market operation

### 4.1 Live/current observations

| Evidence | Maximum age | `AGING` begins |
|---|---:|---:|
| XAU current/forming market observation | 10 seconds | 7.5 seconds |
| DXY current/forming market observation | 30 seconds | 22.5 seconds |
| 5-second execution observation | 15 seconds | 11.25 seconds |
| 15-second supplemental observation | 45 seconds | 33.75 seconds |

Direct structured-read age is measured at `trusted_now_utc` from the trusted
`observed_at`. If the source also emits `source_observed_at`, both timestamps are
retained and any inconsistency is validated; receipt time is not substituted.

### 4.2 Closed-bar evidence

| Timeframe | Maximum age | Human equivalent | `AGING` begins |
|---|---:|---:|---:|
| 1m | 120 seconds | 2 minutes | 90 seconds |
| 5m | 420 seconds | 7 minutes | 315 seconds |
| 15m | 1,200 seconds | 20 minutes | 900 seconds |
| 30m | 2,400 seconds | 40 minutes | 1,800 seconds |
| 1H | 5,400 seconds | 90 minutes | 4,050 seconds |
| 4H | 18,000 seconds | 5 hours | 13,500 seconds |
| Daily | 108,000 seconds | 30 hours | 81,000 seconds |
| Weekly | 691,200 seconds | 8 days | 518,400 seconds (6 days) |

Closed-bar age is `trusted_now_utc - source_bar_close_time`. A currently forming
bar cannot use this table as confirmed closed-bar evidence.

### 4.3 DXY routes

| Route | Evidence | Maximum age | `AGING` begins |
|---|---|---:|---:|
| 9333 | TVC:DXY 15m confirmed closed bar | 1,200 seconds | 900 seconds |
| 9222 | TVC:DXY 1m confirmed supplemental closed bar | 120 seconds | 90 seconds |
| Approved direct route | DXY current/forming observation | 30 seconds | 22.5 seconds |

The 15m and 1m sources retain separate identity, status and bar time. Neither
silently substitutes for the other.

## 5. Webhook/event transport freshness

Event transport age is `received_at - source_observed_at` or the producer's
explicit source event time. `received_at` cannot manufacture a missing source
event time.

| Transport delay | Treatment |
|---|---|
| 0–30 seconds inclusive | Promotion-eligible only if every other source, confirmation and state gate passes |
| More than 30 through 120 seconds inclusive | Late audit evidence; stored and deduplicated, but cannot independently promote `B_TO_A_CANDIDATE` |
| More than 120 seconds | `STALE` for setup promotion; still audit-visible and deduplicated |

The human shorthand “31–120 seconds” refers to the second row. Sub-second
implementations apply the exact `>30` and `<=120` boundaries.

## 6. Capture bundle freshness

| Capture requirement | Maximum |
|---|---:|
| Capture operation duration (`capture_completed_at - capture_started_at`) | 45 seconds |
| XAU current observation age at bundle completion | 15 seconds |
| 1m structured observation age at bundle completion | 120 seconds |
| Screenshot to corresponding structured-read absolute skew | 30 seconds |
| 9333 to 9222 observation-time absolute skew in one final bundle | 30 seconds |
| Local/source future clock skew | 10 seconds |

An operation over 45 seconds or a skew above its limit invalidates the bundle for
promotion. The 15-second bundle-completion allowance does not relax the stricter
10-second XAU current-observation requirement for final GO evaluation. If the
bundle XAU observation is older than 10 seconds at GO, it must be refreshed; the
old observation remains audit-visible.

All bundle artifacts retain their own observation times. A bundle completion time
does not make an older artifact fresh.

## 7. Final 5-second execution timing

A GO notification requires all of the following at one trusted evaluation time:

- Sniper FIRE transport/receipt age is no more than 15 seconds;
- current XAU observation age is no more than 10 seconds;
- matching 1m confirmation has status exactly `FRESH`;
- matching 5m thesis evidence has status exactly `FRESH`;
- the complete evidence bundle remains valid and within all applicable skew and
  integrity limits; and
- FIRE direction, producer identity, source time and confirmation are present.

Because the 1m and 5m checks explicitly require `FRESH`, `AGING` does not satisfy
those two final GO gates even though it remains within the general maximum age.
This freshness policy does not define E1/E2/Main signal TTL.

## 8. Critical and context evidence

### 8.1 Critical for B-to-A, A and GO

Critical evidence is:

- XAU current market observation;
- 5m setup evidence;
- 1m confirmation evidence;
- Liquidity event/state;
- Renko Main for A confirmation;
- matching Sniper FIRE for GO;
- source identity and source timestamps; and
- bundle integrity.

If a critical item is `STALE`, `MISSING`, `CLOCK_INVALID`,
`SOURCE_UNAVAILABLE`, or `MARKET_CLOSED`, there is no promotion to
`A_CONFIRMED`, no GO notification, and no order or writer action. The setup moves
to the appropriate non-actionable state and records the exact failed authority,
field, status, measured age and maximum.

`PROVISIONAL` critical evidence cannot establish `A_CONFIRMED` or GO. `AGING`
remains explicitly `AGING`; it may satisfy a maximum-age-only gate, but never a
gate that requires status exactly `FRESH`.

### 8.2 Context evidence

Context evidence is DXY, 15m/30m MACD, 4H/D/W structure and SR MTF visual
context.

- Stale or missing DXY does not reverse direction; it caps final grade at B.
- Stale or missing 15m/30m MACD context caps final grade at B.
- Stale or missing 4H/D/W structure caps final grade at B.
- Visual-only SR MTF context cannot override exact structured evidence.
- A grade cap does not convert missing context into neutral or fresh evidence.

## 9. Market-closed policy

During a scheduled XAU or relevant feed closure:

- current/forming market observations are `MARKET_CLOSED`;
- there is no `B_TO_A_CANDIDATE` promotion, `A_CONFIRMED` transition,
  `WAITING_5S_ENTRY` promotion, GO notification, or provider review for a new
  actionable setup;
- there is no Telegram, Notion, MT5, broker, order or other writer action; and
- historical closed bars may be displayed only with
  `freshness_status=MARKET_CLOSED` and
  `evidence_usage=CONTEXT_CARRY_FORWARD`.

`CONTEXT_CARRY_FORWARD` is a usage label, not `FRESH` execution evidence.

On reopen, Project A requires a new current-market observation, a new confirmed
1m closed bar, and successful source identity/health/freshness verification. A
pre-closure B/A setup is not automatically revived; it must be deterministically
rebuilt as a new setup or explicitly revalidated under a separately approved
rule.

This document does not encode a holiday calendar. Market-open determination
requires a separately approved deterministic source/calendar implementation.
Until that exists, missing expected bars together with unavailable current prices
fail closed as `SOURCE_UNAVAILABLE`; Project A must not guess `MARKET_CLOSED`.

## 10. Provisional versus confirmed evidence

- Developing MACD values are `PROVISIONAL`.
- Developing Expansion values are `PROVISIONAL` unless the producer explicitly
  marks the relevant bar/event confirmed.
- E1/E2 visual state without source event time and confirmation remains
  `PENDING_PRODUCER_CHANGE`; it cannot establish A.
- Renko Main and Sniper FIRE require source timestamp, direction, producer
  identity and confirmation.
- Screenshot observations cannot upgrade provisional numeric evidence to
  confirmed.
- AI review cannot override or repair stale, provisional, missing,
  clock-invalid, source-unavailable or market-closed deterministic evidence.

## 11. Deterministic result and audit requirements

Each freshness evaluation records authority ID, evidence role, status, measured
age seconds, maximum seconds, 75% boundary seconds, timestamp basis, confirmation
status, source/bar/capture timestamps, clock skew, reason code and evaluation
time. Late, stale and rejected evidence remains append-only, audit-visible and
subject to the existing exact-duplicate and semantic-idempotency rules.

Freshness policy approval does not authorize Pine changes, producer work,
TradingView materialization, provider activation, runtime calls, credentials,
external writers, MT5, broker connections or live execution.
