# Session 1 baseline audit

Date: 2026-07-16 (Australia/Sydney)

Integration baseline: `project-a/integration-v1` at `d10f6ea`

Authoritative Pine repository inspected read-only: `C:/Users/jones.w/One System/snr-rebuild`

## Sources and history inspected

The current dashboard entry point is `src/dashboard/snrDashboard.pine` on the
`snr-rebuild` `main` branch at `29dc151`. Its pre-Session-1 SHA-256 is
`4840f60cb1b4b034304e23d92ba3c40df4e45fbf2abc4b6f51adc2a250b1ca78` after
normalizing line endings to LF. That repository had pre-existing local work, so
Session 1 copied the source into its owned path and did not edit or commit the
authoritative working tree.

The dashboard imports the published `expDetector/1`, `macdVol/1`, `rekoArrow/1`,
`levelEngine/1`, `dxyReader/3`, and `structState/1` libraries. The corresponding
library sources and these reference indicators were inspected: 1-1-1 Trendline,
Expansion Scanner, Liquidity Levels, RenkoV2, SNR Master Dashboard, SNR Pure V2.0,
SNR_Core, and SR MTF Pro V10.

Relevant history inspected includes `29dc151` (Session A visual acceptance),
`a21369f` (Phase 2 dashboard Session A), `4a3be03` (DXY guard), `663d347`, and
`f317796`. Relevant static dashboard and library tests under the authoritative
repository's `tests/` directory were also inspected.

## Existing entry points, state, and alerts

`snrDashboard.pine` is an indicator, not a strategy. It combines expansion,
Renko-arrow, level, DXY, structure, MACD/volume, and volume telemetry. The legacy
decision gate G4 requires the expansion/arrow combination and uses fixed
eligibility windows (`comboWin=6`, `vWin=24`). The current dashboard has no
executable `alert()` or `alertcondition()` call and no Project A setup lifecycle,
HPA engine, rejection-ready event, or strong-break-ready event.

Older reference scripts do contain unrelated alert formats and timing policies:
Expansion Scanner emits unversioned EXP JSON and TOO_LONG alerts; Liquidity Levels
emits TOUCH/SWEEP; RenkoV2 emits WMA5S FLIP; SNR Pure emits FIRE,
ENTRY_PIPELINE, HALT, and CLOSE; SR MTF Pro exposes alert conditions. These are
legacy evidence only and are not replaced or routed by Session 1.

`levelEngine` supplies BODY/WICK/FIB levels with fresh/tested/broken lifecycle
facts. Its sweep cooldown is telemetry logic, not a Project A event throttle.
No existing HPA producer was found. Rejection and strong-break readiness therefore
did not exist as reusable real-code predicates before this session.

## Visual surface to preserve

The baseline plots the nearest resistance in orange and nearest support in aqua,
uses GO/WAIT/conflict background colouring, and renders a 4-by-29 top-right
diagnostic table. The script has `max_lines_count=4`. Its legacy indicator title,
all legacy plots, drawings, table cells, colours, resource limits, input defaults,
and historical/realtime calculations are preservation boundaries. Session 1 adds
no plot, line, box, label, table, or background operation.

An automated byte-preservation test strips only the explicitly marked Project A
blocks and version note, then proves the remainder still hashes to the baseline
SHA-256 above.

## TradingView baseline

The approved isolated development target is CDP port 9444, chart `gwnVPYuQ`,
XAUUSD 5-second. It initially showed `SNR Dashboard [P2 Session B]`. The ordinary
9222/9333 sessions were inspected only enough to identify that they were not the
approved target and were not changed.

The isolated target accepted a server-side Pine compiler check for the Session 1
source. Live editor injection and a before/after chart comparison were not
completed because TradingView displayed `Session disconnected` while another
browser/device owned the account session. Session 1 did not reconnect or replace
the chart source because that could disrupt user state.

## Contract conflicts and incomplete vertical slice

The existing unversioned legacy alert examples lack the frozen Event 0.2 envelope,
stable setup/correlation/causation IDs, explicit UTC times, lifecycle classes,
source payload hashes, and Project A safety fields. The current dashboard is also
alert-silent and treats an arrow as part of a legacy verdict gate, while Project A
requires an optional arrow and evidence-only hypotheses.

The next incomplete vertical slice was therefore: add a default-off, XAUUSD/1m,
shadow-only Event 0.2 sensor to a byte-preserved dashboard snapshot; implement
telemetry, candidate, rejection-ready, strong-break-ready, invalidation, expiry,
semantic deduplication, deterministic identifiers, and candidate evidence without
changing the frozen contract or shared fixtures.
