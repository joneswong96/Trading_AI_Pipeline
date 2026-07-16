# Session 3 baseline audit

Audit date: 2026-07-16 (Australia/Sydney). Baseline: `d10f6eaf44658caa83dba19009eeef5162cf033c` on `project-a/integration-v1`. Working branch: `project-a/session-3-capture-bundle-v1`.

## Existing runtime

- Legacy capture launches Chrome with `--remote-debugging-port=9222 --user-data-dir=%LOCALAPPDATA%\ChromeCDP` and five saved TradingView layout URLs. `capture/tv_mcp.py` connects with Playwright CDP and takes one screenshot per tab. `capture/screenshot.py` is the slower persistent-profile Playwright alternative.
- Legacy structured reads launch a separate Chrome profile with `--remote-debugging-port=9333 --user-data-dir=%USERPROFILE%\ChromeCDP9333`. `capture/tv9333.py` verifies configured panes, symbols, intervals, candle type and MACD presence and reads closed-bar HTF/DXY/OHLC data.
- Live audit: 9222 and 9333 listened only on `127.0.0.1`, owned by the expected Chrome launch commands. Port 4999 had no listener and its CDP endpoint was unavailable. No process conflict exists at audit time.
- Existing 9222 targets were the five documented layouts (`X8AjBAIW`, `paH6jur7`, `ocVwlz2C`, `cpPWuLlN`, `avpCVaw2`). Existing 9333 targets were `cpPWuLlN`, `avpCVaw2`, `pNqcbOmu`, and `n9qjfufV`.

## MCP and browser boundary

- `vendor/tradingview-mcp` is a separate untracked-by-Git Node package at `C:\Users\jones.w\TradingSys\vendor\tradingview-mcp`, package version `1.0.0`. It has installed dependencies but no `.git` metadata, so no repository/branch/commit can be attested locally.
- Its `src/connection.js` and `src/core/tab.js` hard-code `localhost:9222`; target discovery accepts the first TradingView chart-like target and then a fuzzy TradingView fallback. That violates Project A's port 4999 and explicit-tab requirements. The package will remain unmodified and will not be used as capture authority.
- The Project A route therefore needs a narrow local adapter over CDP on exactly `127.0.0.1:4999`, an exact operator-pinned target ID and layout URL, and structured chart verification. The adapter may use the same underlying TradingView/Playwright capabilities without depending on vendor internals.

## Existing capture and storage behaviour

- `capture/tv_mcp.py` URL-matches configured tabs but falls back to tab order when a URL is absent. It does not verify a dedicated profile, process identity, feed, base timeframe, layout state, freshness, modal/loading state, or exactly one selected tab. It uses a fixed one-second settle delay.
- `capture/screenshot.py` navigates one page through five layouts, waits a fixed four seconds and detects only a known login wall. `detect_login_wall` fails open when body inspection fails.
- Legacy artifacts are mutable PNGs under `storage/screenshots/<cycle_id>/`; file names are layout IDs. Optional JSON reads are written directly. There is no atomic immutable store, manifest, byte hash, corruption verification, or complete failure record.
- The 9333 reader has useful structured verification and close-time freshness functions. Its authoritative live thresholds cover only m5 (600 s) and m15 (1800 s), not the Project A five-timeframe bundle or source-event expiry. Those thresholds cannot be silently generalized.

## Existing replay and tests

- Session 0 provides strict JSON Schema plus semantic validators, canonical JSON, frozen event/request fixtures, contract tests, and `py -m project_a.replay --all`. Replay is offline and pins XAUUSD, port 4999, 1m, SHADOW, MT5_DEMO, no order placement, spread 10 and RR 1:1.
- Legacy capture tests are mock-only. The historical 10-by-10 report recorded 10/10 success for both Playwright and 9222 CDP, but it did not prove Project A identity, feed, timeframe, expiry or artifact integrity.
- No formatter, linter or static type checker configuration was found. Pytest and Python compilation are the configured code gates.

## Contract conflicts and next slice

- The frozen request schema has no manifest object. Artifact identities and SHA-256 values must be encoded in the existing `screenshots_required` string list while the full immutable manifest remains a sibling bundle artifact. No shared schema field will be added.
- The frozen accepted Analysis Ready event proves the event boundary but its payload does not contain all request compiler inputs or an expiry. Real compilation must require a documented payload extension and fail closed when it is absent. A Session 3-owned sample may clone the frozen accepted envelope/IDs and add only payload-extension data; shared fixtures remain unchanged.
- No authoritative generic chart-age threshold exists. The route will require explicit expiry from the event, base-bar identity/freshness evidence, and structured live/ready state. It will not invent a hidden timeout for higher timeframes.
- Exact next vertical slice: validated Analysis Ready input -> strict 4999/pinned-tab preflight -> deterministic five-timeframe capture interface -> immutable SHA-256 manifest -> pure request compiler -> expiry release gate -> offline replay -> at-least-once dispatch adapter.

## Session 3-owned paths

- `capture/project_a/**`: profile, preflight, CDP adapter, artifact store, compiler, replay, dispatch consumer and CLI.
- `tests/session_3_project_a/**`: mock/browser-boundary, compiler, integrity, replay and idempotency tests.
- `docs/session_3_project_a/**`: this audit, runbook, design/security notes and promotion manifest.
- `samples/session_3_project_a/**`: fake artifacts, enriched event input, manifest and candidate request bundle.

No Pine, ingest/database, frozen contract, shared fixture, AI, output, MT5, 9222 or 9333 implementation will be changed.
