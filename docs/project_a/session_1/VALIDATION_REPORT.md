# Session 1 validation report

Date: 2026-07-16

## Automated results

| Check | Exact result |
|---|---|
| `py -m indicators.validation.validate_session_1_artifacts` | 6 candidates, 6 PASS against `EVENT_SCHEMA_V0_2`; payload hashes recomputed |
| `py -m pytest tests/test_project_a_pine_sensor.py tests/test_project_a_contracts.py tests/test_project_a_replay.py -q` | 31 passed in 1.34s |
| `py -m project_a.replay --all` | `ok: true`; accepted, rejected, structural break, malformed, expired, missing-field, bad-version, bad-enum, and duplicate cases exercised |
| `py -m pytest tests -q` | 418 passed, 1 skipped in 8.80s on the isolated Session 1 baseline |
| TradingView MCP `pine analyze` | success; 0 issues |
| TradingView MCP `pine check` | compiled; 0 errors, 0 warnings |
| Authoritative `snr-rebuild` PowerShell tests | 4 scripts PASS: decision truth table, Session A contract, Session B render telemetry, DXY init guard |

The isolated worktree inherited CRLF checkout conversion for
`.claude/commands/analyze.md`, while its byte-identity test compares an LF copy in
the parent workspace. The first isolated full run therefore reported one
line-ending-only failure (416 passed, 1 failed, 1 skipped). The unchanged command
was temporarily materialized with the expected LF bytes, producing the clean full
result above, and then restored from the index. It is clean and is not part of the
Session 1 commit. An earlier full run in the shared workspace also passed (463
passed, 1 skipped) before concurrent session files were isolated.

The Session 1 tests specifically prove the six samples, malformed rejection,
range-middle negative behavior, same-evidence deduplication, immediate new
reaction and break emission, optional null 5s arrow, immediate invalidation and
expiry, setup/causation continuity, SHA-256 payload hashes, default-off safety,
absence of a fixed Project A cooldown, and byte preservation of the legacy Pine
surface outside owned blocks.

## Visual status

A baseline screenshot was captured from the approved isolated TradingView target.
The target then displayed `Session disconnected` because another browser/device
owned the account session. Opening the Pine panel succeeded, but editor source
injection and live chart compilation could not proceed in that disconnected
state. No reconnect action was taken, no source was injected, and no chart or
alert state was changed.

Accordingly, this report claims successful server-side Pine compilation and
static legacy-byte preservation, but does not claim a completed before/after
visual regression. The exact outstanding steps are in
`TRADINGVIEW_ALERT_CHECKLIST.md` and are a promotion prerequisite.
