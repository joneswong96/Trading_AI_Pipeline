# Project A Read-Only Capture Service

The service binds only `127.0.0.1`, connects only to the already-running production
Chrome endpoint `http://127.0.0.1:9333`, and exposes exactly one MCP tool:
`project_a_capture_snapshot`. It never launches, navigates, focuses, clicks, types,
changes chart state, opens Pine/alerts, or accepts caller-supplied browser operations.

## Set safe local configuration

Run from PowerShell. The token is generated in memory and is not printed:

```powershell
$runtime='C:\Users\jones.w\TradingSys\trading-auto'
Set-Location $runtime
$tokenBytes=New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
$env:PROJECT_A_CAPTURE_TOKEN=[Convert]::ToBase64String($tokenBytes)
[Array]::Clear($tokenBytes,0,$tokenBytes.Length)
$env:PROJECT_A_CAPTURE_HOST='127.0.0.1'
$env:PROJECT_A_CAPTURE_PORT='8765'
$env:PROJECT_A_CAPTURE_DB="$runtime\storage\project_a_capture_service.db"
$env:PROJECT_A_CAPTURE_ARTIFACT_ROOT="$runtime\storage\project_a_capture_evidence"
$env:PROJECT_A_DB="$runtime\storage\project_a.db"
$env:PROJECT_A_MCP_SERVER_URL='http://127.0.0.1:8765/mcp'
$env:PROJECT_A_MCP_CAPTURE_TOOL='project_a_capture_snapshot'
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PROJECT_A_OPENAI_MODEL -ErrorAction SilentlyContinue
Remove-Item Env:PROJECT_A_OPENAI_BILLING_CONFIRMED -ErrorAction SilentlyContinue
```

The same `PROJECT_A_CAPTURE_TOKEN` value must be inherited by the capture-service
and worker processes. Do not write it to source, committed files, chat, or logs.

## Start and verify capture service

Foreground:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_capture_service serve
```

Hidden process with recorded launcher PID:

```powershell
$captureProcess=Start-Process uv -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -ArgumentList @('run','--python','3.11','--with-requirements','requirements.txt','python','-m','project_a_capture_service','serve')
$captureDeadline=[DateTime]::UtcNow.AddSeconds(30)
do {
  $captureListeners=@(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)
  if($captureListeners.Count -eq 1){break}
  Start-Sleep -Milliseconds 100
} while([DateTime]::UtcNow -lt $captureDeadline)
if($captureListeners.Count -ne 1 -or $captureListeners[0].LocalAddress -ne '127.0.0.1'){throw 'Capture service did not establish one loopback listener'}
$env:PROJECT_A_CAPTURE_SERVER_PID=[string]$captureListeners[0].OwningProcess
```

Authenticated health and exact MCP schema check:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_capture_service health
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_capture_service mcp-ready
```

Read-only production 9333 preflight (no tool call and no synthetic LIQ/E1):

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_capture_service preflight
```

Inspect capture failures and verify the append-only audit chain:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_capture_service audit --limit 50
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB jobs --status PENDING_CAPTURE
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB jobs --status TECHNICAL_FAILURE
```

Verify the service listener is loopback-only:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8765 | Select-Object LocalAddress,LocalPort,OwningProcess
```

The only accepted address is `127.0.0.1`. Resolve and verify the exact listener
before stopping it; refuse to act if the listener is missing, duplicated, bound to
another address, or is not the capture-service process:

```powershell
$captureListeners=@(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)
if($captureListeners.Count -ne 1 -or $captureListeners[0].LocalAddress -ne '127.0.0.1'){throw 'Capture listener identity is unsafe'}
$captureLeaf=Get-CimInstance Win32_Process -Filter "ProcessId=$($captureListeners[0].OwningProcess)"
if($captureLeaf.Name -ne 'python.exe' -or $captureLeaf.CommandLine -notmatch 'project_a_capture_service'){throw 'Capture process identity is unsafe'}
Stop-Process -Id $captureLeaf.ProcessId
if($captureProcess -and (Get-Process -Id $captureProcess.Id -ErrorAction SilentlyContinue)){
  $captureLauncher=Get-CimInstance Win32_Process -Filter "ProcessId=$($captureProcess.Id)"
  if($captureLauncher.CommandLine -notmatch 'project_a_capture_service'){throw 'Capture launcher identity is unsafe'}
  Stop-Process -Id $captureProcess.Id
}
$captureProcess=Start-Process uv -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -ArgumentList @('run','--python','3.11','--with-requirements','requirements.txt','python','-m','project_a_capture_service','serve')
$captureDeadline=[DateTime]::UtcNow.AddSeconds(30)
do {
  $captureListeners=@(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)
  if($captureListeners.Count -eq 1){break}
  Start-Sleep -Milliseconds 100
} while([DateTime]::UtcNow -lt $captureDeadline)
if($captureListeners.Count -ne 1 -or $captureListeners[0].LocalAddress -ne '127.0.0.1'){throw 'Capture service did not establish one loopback listener'}
$env:PROJECT_A_CAPTURE_SERVER_PID=[string]$captureListeners[0].OwningProcess
```

Restart the Analysis Worker after a capture-service restart so it inherits the
new pinned `PROJECT_A_CAPTURE_SERVER_PID`. The worker refuses to send the bearer
token unless that exact PID owns the verified loopback listener.

## Start provider-disabled Analysis Worker

```powershell
$workerProcess=Start-Process uv -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -ArgumentList @('run','--python','3.11','--with-requirements','requirements.txt','python','-m','project_a_analysis.worker','--db',$env:PROJECT_A_DB,'--poll-seconds','15')
$workerProcess.Id
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB health
```

The latest worker row must show `provider_enabled: 0`. Do not configure a model,
billing approval, or `OPENAI_API_KEY` during capture-service activation.

Capture integrity failures use durable exponential backoff and are quarantined
as `TECHNICAL_FAILURE` after five failed attempts, preventing one bad capture
from creating a tight loop or permanently starving later pending work.

## Fixed security boundary

- HTTP body maximum: 65,536 bytes.
- One capture at a time; four capture calls per minute maximum.
- Baseline: exactly five PNGs, 20 MiB total maximum.
- E1 delta: exactly two PNGs, 8 MiB total maximum.
- Fixed CDP operations: `Runtime.evaluate` with one repository-hashed read-only
  script and `Page.captureScreenshot`; all other methods are rejected.
- Fixed layouts: `cpPWuLlN`, `avpCVaw2`, `pNqcbOmu`, `n9qjfufV`, `YclFo8Ax`.
- Missing, duplicate, stale, wrong-account, wrong-symbol/feed/timeframe/layout,
  non-candle, changed-state, or hash-conflicting evidence fails closed.
