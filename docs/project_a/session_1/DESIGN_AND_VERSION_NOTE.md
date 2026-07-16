# Project A Pine sensor design and version note

Owned source: `indicators/pine/snr_dashboard_project_a_v1.pine`

Pine language: v6

Project A version note: `v0.4.0-project-a-shadow`

Legacy TradingView title preserved: `SNR Dashboard [P2 Session B]`

## Boundary and compatibility

The source is the current authoritative Session B dashboard snapshot plus two
clearly marked Project A-owned blocks. `Enable Project A shadow alerts` defaults
to false. Emission additionally requires XAUUSD, the 1-minute chart, a confirmed
realtime bar, and an actual semantic state change. Payloads state `SHADOW`,
`MT5_DEMO`, and `live_execution=false`. The Pine layer never places orders,
routes webhooks, supplies a final AI verdict, or claims final execution authority.

The script uses one `alert()` call with `alert.freq_once_per_bar_close`. Legacy
alerts are untouched; the baseline dashboard had none. No 4999/9222/9333 routing
is implemented.

## Evidence semantics

HPA is conservatively derived from a rolling 50-bar high/low position on 1m, 5m,
15m, and 30m. A slot is premium at or above 0.60 and discount at or below 0.40;
at least two non-middle slots are required. This is an explicit Session 1
assumption because the inspected code has no HPA producer. A range-middle state
is telemetry-only.

The candidate path requires a current clean expansion toward the nearest eligible
support or resistance, proximity within the 5m ATR, and valid HPA context. A
rejection-ready transition requires a closed 1m REJECT, SWEEP_RECLAIM, or ENGULF
reaction at the active band. A strong-break transition requires a first closed 1m
cross beyond a 0.3 times 5m ATR buffer, body/range at least 0.55, and at least two
of 1m/5m/15m/30m momentum slots continuing in the break direction.

The 5-second momentum timestamp and direction are supporting evidence. The
current published libraries do not expose a reliable lower-timeframe arrow
series, so `optional_5s_arrow` is truthfully `null` and is never a gate.

Event priority on one closed bar is invalidation, expiry, rejection-ready,
strong-break-ready, new candidate, then telemetry. This makes lifecycle closure
unambiguous and prevents multiple competing envelopes from the same evaluation.

## Timestamps and identifiers

`occurred_at` and payload `bar_time` use the 1m `time_close`, formatted in UTC
with a terminal `Z`. `received_at` and payload `created_time` use `timenow`, also
formatted in UTC. Lower-timeframe evidence uses its own timestamp and is never
substituted for bar time.

Setup identity is reproducible from:

`XAUUSD | 1m | encounter-start UTC | support/resistance side | band-centre ticks`

It remains stable until the setup closes or a genuinely different target starts.
Correlation ID uses the same suffix. Event identity adds closed-bar UTC, event
type, and trigger; causation points to the preceding emitted event in that setup.
There is no randomness or machine-local identity.

## Deduplication fingerprint

The semantic fingerprint contains, in fixed order: event type; setup ID or NONE;
bar-close UTC; trigger; reason; active low/high; four HPA slots; four base momentum
slots; and lifecycle state. It intentionally excludes JSON member order and
event-creation time. The last fingerprint is updated only after emission. Thus an
unchanged recalculation cannot duplicate, while a new reaction, first confirmed
break, invalidation, expiry, or other meaningful state transition can emit on the
next eligible evaluation without an arbitrary cooldown.

Payload `source.payload_hash` is SHA-256 over the deterministic payload JSON. The
Pine implementation performs SHA-256 locally using arithmetic bit-word helpers;
no new Pine or repository dependency is introduced. The independent Python
reference recomputes SHA-256 over the frozen contract's canonical JSON form for
artifact validation.

## Safety limitations

Pine has no trustworthy bid/ask spread at this boundary. The envelope reports the
frozen maximum of 10 normalized points but does not claim that Pine measured it;
the downstream Session 0 validator remains the fail-closed authority. RR is fixed
to 1.0, but this sensor deliberately supplies no entry, stop, target, sizing, or
execution instruction.

Historical bars can calculate the visual dashboard and Project A evidence state,
but alerts require confirmed realtime bars. Higher/lower-timeframe requests can
change during an open realtime bar; the confirmed-bar gate is the principal
recalculation safeguard. A live TradingView replay and visual comparison remains
required before promotion.
