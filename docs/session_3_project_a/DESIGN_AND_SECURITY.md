# Session 3 design, failure model and security review

## Boundary and data flow

`capture.project_a` is a new Session 3-owned package. It does not import or alter legacy 9222/9333 capture code, Session 2 persistence, AI, output, Telegram, Notion or MT5 modules.

1. `input_boundary.py` validates the exact frozen Event 0.2 contract and accepts only `ANALYSIS_READY`, `ACCEPTED`, XAUUSD, 1m events with one of the two approved paths.
2. `profile.py` provides a multi-symbol-shaped profile but rejects every enabled profile except exact XAUUSD/ICMARKETS/127.0.0.1:4999/1m.
3. `cdp.py` attests the Windows listener/process and standard CDP endpoint. A tab is selected by an operator-pinned target ID plus an exact allowlisted TradingView layout URL. It never selects the first target or uses a title match.
4. `preflight.py` independently checks endpoint, process/profile marker, local-only binding, exact tab, URL/layout/chart count, structured and header symbol/feed/timeframe signals, authentication, modal/disconnect/loading state, available timeframes, streaming state, source-bar coverage, expiry and destination writability.
5. `coordinator.py` switches one chart through `5s -> 1m -> 5m -> 15m -> 30m`, waits for two stable structured observations per switch, captures only after verification, and restores/reverifies 1m in `finally`. Any missing artifact or failed restoration makes the manifest `FAILED` and prevents compilation.
6. `artifacts.py` derives attempt/file paths from hashes and allowlisted timeframe values, writes with exclusive create, hashes actual bytes with SHA-256, and verifies path containment, existence, byte size and hash during replay.
7. `compiler.py` is pure for fixed event, manifest, profile and clock. It creates a deterministic request ID, maps only frozen schema fields, validates the exact Analysis Request 1.0 contract and encodes artifact identities as `<tf>:sha256:<digest>` in the existing `screenshots_required` field.
8. `replay.py` needs only stored files. It verifies artifacts, validates both contracts, recompiles and compares canonical JSON. The separate release gate retains expired bundles but returns `release_to_session_4=false`.
9. `consumer.py` defines the future Session 2 boundary: dispatch ID, validated event, retry count and requested-at time. A replace-atomically file ledger proves at-least-once idempotency without assuming Session 2 tables. Session 2 may replace the ledger behind the same interface.

The reference file ledger assumes one Session 2 dispatcher process per ledger root. Its exclusive temporary writes and atomic replacement protect restart recovery, but they are not a cross-process compare-and-swap transaction. A concurrent production consumer must implement the same interface with a database uniqueness constraint/transaction on `dispatch_id` and the stored input hash.

## Event payload extension

The frozen accepted event fixture lacks expiry, HPA, five momentum values, spread and candidate prices. The compiler therefore requires these fields under Event 0.2's existing, explicitly extensible `payload.analysis` bag:

```json
{
  "expires_at": "UTC Z",
  "bar_time": "UTC Z",
  "session": "ASIAN | LONDON | NEW_YORK | OVERLAP | OFF_HOURS",
  "snr": {"low": 0, "high": 0, "type": "CLASSIC | HNS | BO | SWEEP | TL"},
  "hpa": [],
  "momentum": {"5s": {}, "1m": {}, "5m": {}, "15m": {}, "30m": {}},
  "trigger_price": 0,
  "spread_points": 0,
  "entry_candidate": 0,
  "sl_candidate": 0,
  "tp_candidate": 0,
  "source_event_ids": []
}
```

This is an adapter convention, not a shared-schema change. Missing data fails with `COMPILATION_INPUT_MISSING`; it is never defaulted from market assumptions. Session 0 should ratify this producer/consumer convention before Session 2 wiring.

## Freshness and expiry

- Expiry is producer-supplied and is never calculated or extended by Session 3.
- It is checked before preflight, after capture, before compilation, before every retry, and at release.
- No undocumented age threshold is introduced. Each observed forming/latest bar must not end before the source bar for its own timeframe, structured chronology must be sane, the chart must report streaming/not disconnected, and capture must complete before the original expiry.
- The repository's existing m5/m15 OHLC thresholds remain legacy 9333 behavior and are not generalized to Project A.
- A request reaching expiry is retained and replays successfully, but release to Session 4 is false.

## Failure and retry policy

Stable failures carry code, bounded detail, retryable flag, attempt ID and next safe action. Operator-correctable context failures are retryable only against the same dispatch before the original expiry; no automatic tab, symbol, feed or port switching occurs.

| Class | Codes | Retry |
|---|---|---|
| Endpoint | `PORT_UNAVAILABLE`, `MCP_UNAVAILABLE` | Before expiry after restoring the same 4999 route |
| Unsafe identity | `PORT_MISMATCH`, `WRONG_PROCESS`, `UNSAFE_BINDING` | Terminal until configuration/process is manually corrected |
| Tab/chart context | `TAB_NOT_FOUND`, `TAB_AMBIGUOUS`, `WRONG_TAB`, `PAGE_NOT_READY`, `AUTH_UNUSABLE`, `WRONG_SYMBOL`, `WRONG_FEED`, `WRONG_TIMEFRAME`, `WRONG_LAYOUT`, `CHART_NOT_READY`, `STALE_CHART`, `MISSING_TIMEFRAME`, `MODAL_BLOCKING` | Manual correction, same dispatch, original expiry |
| Artifact | `SCREENSHOT_FAILURE`, `ARTIFACT_WRITE_FAILURE`, `PARTIAL_CAPTURE` | Preserve attempt, then retry before expiry |
| Integrity/security | `ARTIFACT_HASH_MISMATCH`, `ARTIFACT_MISSING`, `PATH_TRAVERSAL` | Terminal/quarantine |
| Authority/contract | `SOURCE_EXPIRED`, `SOURCE_INVALID`, `COMPILATION_INPUT_MISSING`, `CONTRACT_COMPILATION_FAILURE` | Terminal; a new source event is required after expiry |
| Delivery | `DISPATCH_CONFLICT`, `RETRY_SEQUENCE_INVALID` | Terminal/quarantine |

## Security findings

- CDP can control arbitrary targets and exposes authenticated page content. Isolation is therefore mandatory: dedicated Chrome profile, one purpose-specific tab, loopback binding, exact process/profile attestation and no unrelated tabs in that profile.
- The vendor MCP package exposes broad read/write tab, UI, layout, Pine and drawing tools, hard-codes 9222 and selects the first fuzzy target. It is not allowlisted for this route and remains unmodified.
- The adapter does not inspect/export cookies, local storage, request headers, tokens or credentials. Logs/manifests contain only bounded identity/evidence metadata.
- Event text never becomes a shell command or file path. PowerShell used for listener attestation is a static command with fixed port 4999. Artifact names come only from an allowlisted timeframe and SHA-256.
- Artifact paths are containment-checked on write and replay. Immutable writes reject different bytes at an existing path.
- The adapter exposes no filesystem browser tool and no command execution tool to TradingView. OpenClaw and AI execution are absent.
- `live_execution=false`, SHADOW and MT5_DEMO are revalidated by the frozen request contract. No order or output module is called.

## Candid architecture assessment

- Port 4999 and single-tab isolation are practical if Jones accepts a dedicated profile and a dedicated single-chart saved layout. Reusing the five-tab 9222 profile would not meet the boundary.
- The current vendor MCP cannot reliably support Project A without upstream configurability for host/port and exact target ID. The wrapper is safer than a vendor patch, but it uses undocumented TradingView internals (`TradingViewApi`, `setResolution`) and will require smoke tests after TradingView/Chrome upgrades.
- Screenshot evidence alone is not sufficient. It cannot reliably prove feed, timeframe, freshness or artifact-to-chart identity. The implementation requires structured state plus header/URL signals and treats PNGs as auditable evidence, not identity authority.
- TradingView DOM/header selectors and internal API shapes are brittle. A structured broker/market-data source with explicit timestamps would materially improve freshness and feed attestation; screenshots should remain supporting evidence.
- The strongest remaining risk is the absence of a real 4999 profile/layout during this session. Mocked tests prove logic, not current TradingView compatibility. Session 0 must require a live smoke test and 20–30 shadow samples before merge/release.
- The frozen request schema has no dedicated artifact manifest field. Hash references in `screenshots_required` are valid but cramped. A future contract version should model artifact records explicitly; no current schema change is required for the candidate.
