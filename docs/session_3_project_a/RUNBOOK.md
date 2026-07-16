# Session 3 setup and recovery runbook

All commands run from `C:\Users\jones.w\TradingSys\trading-auto`. Replace `<profile>`, `<pin>`, `<event>`, `<artifact-root>`, `<bundle>` and the approved layout ID. Do not place credentials in command arguments, profile JSON, pins or artifacts.

## Prepare the dedicated route

Copy `capture\project_a\profile.example.json` to an untracked operator location and replace only the approved single-chart layout ID/URL. Keep XAUUSD, ICMARKETS, 127.0.0.1, 4999, 1m and the five required timeframes unchanged.

Verify 4999 is free and legacy routes are unchanged:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 4999 -ErrorAction SilentlyContinue
Get-NetTCPConnection -State Listen -LocalPort 9222,9333 | Select-Object LocalAddress,LocalPort,OwningProcess
```

An empty first command means 4999 is free. The second command should continue to show the existing loopback listeners; Session 3 never stops or reconfigures them.

Start the approved isolated Chrome profile on loopback port 4999:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-address=127.0.0.1 `
  --remote-debugging-port=4999 `
  --user-data-dir="$env:LOCALAPPDATA\ProjectA-XAUUSD-4999" `
  "https://www.tradingview.com/chart/<APPROVED_LAYOUT_ID>/"
```

Use that profile only for Project A XAUUSD. Sign in interactively if needed. Keep exactly one approved TradingView chart page in the profile. Do not copy/export cookies.

Confirm loopback binding and expected process:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 4999 | Select-Object LocalAddress,OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" | Select-Object Name,CommandLine
Invoke-RestMethod http://127.0.0.1:4999/json/version
```

`LocalAddress` must be `127.0.0.1` or `::1`; command line must contain both `--remote-debugging-port=4999` and `ProjectA-XAUUSD-4999`.

## Inspect and pin one tab

The Project A adapter is the approved CDP/MCP boundary. Do not start `vendor/tradingview-mcp` for this route because it hard-codes 9222 and fuzzy first-target discovery.

```powershell
py -m capture.project_a inspect --profile <profile>
py -m capture.project_a pin-tab --profile <profile> --target-id <EXACT_TARGET_ID> --output <pin>
```

Pinning checks the exact target ID and allowlisted layout URL. It does not use the title. Re-pin after a browser restart because CDP target IDs change.

## Preflight and capture

Verify symbol, ICMARKETS feed, initial 1m, layout, required timeframes, streaming state, source bar, authentication, overlays, destination and expiry without taking a screenshot:

```powershell
py -m capture.project_a preflight --profile <profile> --pin <pin> --event <event> --artifact-root <artifact-root>
```

Capture, hash, compile and apply the release gate:

```powershell
py -m capture.project_a capture --profile <profile> --pin <pin> --event <event> `
  --artifact-root <artifact-root> --dispatch-id <STABLE_DISPATCH_ID> --retry-count 0
```

The capture sequence is 5s, 1m, 5m, 15m, 30m, then verified restoration to 1m. Success prints the immutable bundle directory. A failed attempt still contains `manifest.json` but never `analysis_request.json`.

## Inspect, verify, compile and replay

```powershell
Get-Content -Raw <bundle>\manifest.json
py -m capture.project_a verify --manifest <bundle>\manifest.json
py -m capture.project_a compile --profile <profile> --event <bundle>\source_event.json `
  --manifest <bundle>\manifest.json --created-at <UTC_Z_CLOCK>
py -m capture.project_a replay --profile <profile> --bundle <bundle>
```

Compilation is in-place so manifest-relative artifact paths remain stable. Replay needs no browser, MCP, network, AI or live service.

Build and replay the repository-owned fake candidate:

```powershell
py -m capture.project_a build-sample `
  --frozen-cases fixtures\project_a\event_cases.json `
  --extension samples\session_3_project_a\analysis_extension.json `
  --profile samples\session_3_project_a\profile.fixture.json `
  --output-root samples\session_3_project_a\candidate_bundle `
  --started-at 2026-07-16T00:01:00Z --finished-at 2026-07-16T00:01:10Z `
  --created-at 2026-07-16T00:01:10Z
py -m capture.project_a replay --profile samples\session_3_project_a\profile.fixture.json `
  --bundle samples\session_3_project_a\candidate_bundle\attempt_f3f0ce2b4e76389ffe02d8a6b5e82be0
```

## Failure and retry

Read `manifest.json.failure`. Correct only the stated context; never switch port/tab/symbol/feed automatically. Retry the same dispatch with a strictly increasing count and the unchanged event:

```powershell
py -m capture.project_a capture --profile <profile> --pin <pin> --event <event> `
  --artifact-root <artifact-root> --dispatch-id <SAME_DISPATCH_ID> --retry-count 1
```

Retry does not extend `payload.analysis.expires_at`. At or after expiry, retain the prior attempts and wait for a new Analysis Ready event. Never delete or edit a failed artifact to make it pass.

If a hash, size, path-containment or missing-artifact check fails, quarantine the bundle and do not retry it as trusted evidence. Preserve the failed bytes and manifest.

## Disable and clean up safely

Disable only the isolated 4999 profile; do not touch 9222/9333:

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -match 'ProjectA-XAUUSD-4999' -and $_.CommandLine -match 'remote-debugging-port=4999' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId }
Get-NetTCPConnection -State Listen -LocalPort 4999 -ErrorAction SilentlyContinue
```

Tab pins and dispatch ledger files are mutable operator state and may be archived outside the artifact root. Never delete immutable attempt directories as cleanup.

Confirm no fallback and no downstream action:

```powershell
rg -n "9222|9333" capture\project_a
rg -n "Telegram|Notion|MT5|order_placement|OpenClaw" capture\project_a
```

Any hits are documentation/error context only; the package has no legacy port, publisher, broker or AI imports. A successful Session 3 run stops at the Analysis Request bundle and release decision.
