# Session 3 design, failure model and security review

## Boundary and data flow

`capture.project_a` is a new Session 3-owned package. It does not import or alter legacy 9222/9333 capture code, Session 2 persistence, AI, output, Telegram, Notion or MT5 modules.

1. `input_boundary.py` accepts Canonical Event V1 only. It recomputes canonical content, semantic evidence, stable setup and canonical IDs from `wire_event`; requires an accepted, non-duplicate, dispatch-eligible trusted-ingress record; and binds the exact receipt lineage.
2. Data absent from Canonical Event V1 but required by the frozen Analysis Request schema is supplied only by `PROJECT_A_SESSION_2_CAPTURE_ADAPTER/1.0`. This adapter is `DISABLED_RECORDED_ONLY`, has `runtime_enabled=false`, and binds its `payload.analysis` to the exact canonical/setup/producer/receipt/hash lineage.
3. `profile.py` rejects every profile except exact XAUUSD/ICMARKETS/127.0.0.1:4999/1m. `real_browser_enabled` defaults false and the probe/driver/capture path raises `RUNTIME_ACTIVATION_DISABLED` before subprocess, HTTP, Playwright, or CDP access.
4. `cdp.py` and `preflight.py` retain strict 4999, exact target, XAUUSD, ICMARKETS, layout, timeframe and freshness checks for the later Runtime Activation campaign. There is no 9222/9333, tab, symbol, feed, timeframe or layout fallback.
5. `coordinator.py` preserves `5s -> 1m -> 5m -> 15m -> 30m` capture and final verified 1m restoration. In the offline candidate it may be exercised only with `capture_method=FIXTURE`; the real route is disabled.
6. `artifacts.py` binds every attempt to request/setup/source/canonical/semantic/raw/receipt/adapter lineage. Every artifact and manifest says whether it is synthetic and carries `runtime_compatibility_claim=NONE`.
7. `compiler.py` creates a deterministic request ID from the complete lineage. Because frozen Analysis Request 1.0 requires `evt_` IDs, it uses the deterministic alias `evt_<canonical-hash>` and records the actual `cevt_` identity in the manifest.
8. `replay.py` needs only stored files. It verifies the exact lineage, artifacts and deterministic request. Synthetic bundles are `SYNTHETIC_RETAINED`; every release remains false until Runtime Activation.
9. `consumer.py` fingerprints the Canonical V1 plus disabled adapter output together and records the complete lineage in its offline idempotency ledger.

The reference file ledger assumes one Session 2 dispatcher process per ledger root. Its exclusive temporary writes and atomic replacement protect restart recovery, but they are not a cross-process compare-and-swap transaction. A concurrent production consumer must implement the same interface with a database uniqueness constraint/transaction on `dispatch_id` and the stored input hash.

## Versioned adapter convention

`payload.analysis` is not an Event V1 extension and is not shared event
semantics. It exists only inside the explicitly versioned, disabled Session 2
adapter output:

```json
{
  "adapter_family": "PROJECT_A_SESSION_2_CAPTURE_ADAPTER",
  "adapter_version": "1.0",
  "runtime_enabled": false,
  "status": "DISABLED_RECORDED_ONLY",
  "source": {
    "canonical_event_id": "cevt_...",
    "canonical_content_hash": "sha256:...",
    "semantic_evidence_hash": "sha256:...",
    "setup_id": "setup_...",
    "producer_event_id": "wevt_...",
    "receipt_id": "rcpt_...",
    "raw_content_hash": "sha256:...",
    "immutable_raw_reference": "..."
  },
  "payload": {
    "analysis": {
      "expires_at": "UTC Z",
      "bar_time": "UTC Z",
      "session": "ASIAN | LONDON | NEW_YORK | OVERLAP | OFF_HOURS",
      "instrument": {"symbol": "XAUUSD", "venue": "ICMARKETS", "point_size": 0.01},
      "snr": {"low": 0, "high": 0, "type": "CLASSIC | HNS | BO | SWEEP | TL"},
      "hpa": [],
      "momentum": {"5s": {}, "1m": {}, "5m": {}, "15m": {}, "30m": {}},
      "trigger_price": 0,
      "spread_points": 0,
      "entry_candidate": 0,
      "sl_candidate": 0,
      "tp_candidate": 0
    }
  }
}
```

The adapter source block must repeat and exactly match canonical event ID,
canonical/semantic hashes, setup ID, producer event ID, receipt ID, raw hash and
immutable raw reference. Canonical SNR, trigger, geometry, observed spread, HPA
projection and bar time are cross-checked. Missing or conflicting data fails
closed. Momentum/session/expiry translation remains adapter-version behavior,
not a change to Event V1 semantics.

## Freshness and expiry

- Expiry is supplied by the versioned disabled adapter and is never calculated or extended by Session 3.
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
| Authority/contract | `SOURCE_EXPIRED`, `SOURCE_INVALID`, `CANONICAL_LINEAGE_INVALID`, `ADAPTER_LINEAGE_INVALID`, `COMPILATION_INPUT_MISSING`, `CONTRACT_COMPILATION_FAILURE` | Terminal; quarantine mismatched lineage or wait for new authority after expiry |
| Runtime | `RUNTIME_ACTIVATION_DISABLED` | Terminal in the offline candidate; complete the separately authorized activation gate |
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
- The strongest remaining risk is the absence of real 4999 evidence. Offline integration does not claim TradingView/Chrome/Playwright compatibility. A separately authorized real five-timeframe capture, final 1m restoration, integrity replay and representative shadow samples remain Runtime Activation Gates.
- The frozen request schema has no dedicated artifact manifest field. Hash references in `screenshots_required` are valid but cramped. A future contract version should model artifact records explicitly; no current schema change is required for the candidate.
