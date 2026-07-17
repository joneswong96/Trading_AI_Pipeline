# Session 3 corrected offline runbook

This runbook is limited to disabled, deterministic offline validation. Do not
start or inspect a browser, listener, TradingView session, broker feed, or live
adapter during this acceptance.

## Safety posture

The checked-in profiles require:

- XAUUSD
- ICMARKETS
- `127.0.0.1:4999`
- base timeframe 1m
- `5s, 1m, 5m, 15m, 30m`
- `real_browser_enabled=false`

With that setting, `inspect`, `pin-tab`, `preflight`, and real `capture` stop
with `RUNTIME_ACTIVATION_DISABLED` before PowerShell listener inspection, HTTP,
Playwright, or CDP access. There is no fallback to 9222, 9333, another port,
target, tab, symbol, feed, timeframe, or layout.

## Build the recorded synthetic bundle

```powershell
py -3.11 -m capture.project_a build-sample `
  --wire-vectors fixtures/project_a/event_v1_known_vectors.json `
  --adapter samples/session_3_project_a/analysis_adapter.fixture.json `
  --profile samples/session_3_project_a/profile.fixture.json `
  --output-root <EMPTY_OUTPUT_ROOT> `
  --started-at 2026-07-16T01:02:00Z `
  --finished-at 2026-07-16T01:02:10Z `
  --created-at 2026-07-16T01:02:10Z
```

The builder:

1. takes the Wire Event V1 rejection-ready known vector;
2. adds recorded observed spread only in the Session 3-owned copy;
3. runs the replay-only trusted receipt processor;
4. obtains Canonical Event V1;
5. binds the disabled versioned adapter output;
6. writes five one-pixel synthetic PNG fixtures;
7. compiles the frozen Analysis Request schema;
8. writes a non-releasable bundle.

It does not use a browser, network, AI, MT5, broker, Telegram, Notion, OpenClaw,
or production service.

## Verify and replay

```powershell
py -3.11 -m capture.project_a verify `
  --manifest samples/session_3_project_a/candidate_bundle_v1/attempt_8b59cacf927faad01734a7f50903119d/manifest.json

py -3.11 -m capture.project_a replay `
  --profile samples/session_3_project_a/profile.fixture.json `
  --bundle samples/session_3_project_a/candidate_bundle_v1/attempt_8b59cacf927faad01734a7f50903119d
```

Require:

- `ok=true`
- `artifact_count=5`
- `evidence_classification=SYNTHETIC_FIXTURE`
- `runtime_compatibility_claim=NONE`
- `network_used=false`
- `browser_used=false`
- `ai_used=false`
- `release.status=SYNTHETIC_RETAINED`
- `release.release_to_session_4=false`

## Focused and shared tests

```powershell
py -3.11 -m pytest tests/session_3_project_a -q
py -3.11 -m pytest tests/test_project_a_event_v1.py -q
py -3.11 -m pytest tests/test_project_a_contracts.py -q
py -3.11 -m pytest tests/test_project_a_replay.py -q
py -3.11 -m project_a.replay --all
py -3.11 -m compileall -q capture/project_a contracts project_a tests
py -3.11 -m pip check
```

## Failure handling

- Canonical/setup/hash mismatch: quarantine with
  `CANONICAL_LINEAGE_INVALID`.
- Adapter/receipt/source mismatch: quarantine with
  `ADAPTER_LINEAGE_INVALID`.
- Missing adapter compilation fields: fail with
  `COMPILATION_INPUT_MISSING`.
- Expired authority: retain and do not release.
- Artifact path/size/hash failure: quarantine the bundle.
- Any attempt to use the real route before activation: stop with
  `RUNTIME_ACTIVATION_DISABLED`.

Do not edit an immutable bundle to make it pass. Create a new synthetic output
root for a deterministic rebuild.

## Deferred Runtime Activation

Real port-4999, browser, target/layout, TradingView identity, five-timeframe
capture, final 1m restoration, real PNG integrity, and genuine shadow samples
belong to the Session 0 Runtime Activation campaign. They are not part of this
offline run and are not claimed by this candidate.
