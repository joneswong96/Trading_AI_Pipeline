# Project A OpenAI Analysis Worker

This slice is XAUUSD-only, `SHADOW`, `MT5_DEMO`, notify/write-disabled,
broker-disabled, and order-disabled. The worker consumes the same SQLite
database as `/alert`. It never automates ChatGPT or a Codex browser task.

## Runtime flow

`POST /alert` commits the canonical event, story/job identity, immutable audit
record, and `PENDING_CAPTURE` status in one transaction. The worker invokes one
configured loopback MCP tool; it does not poll a prebuilt evidence inbox. Set:

```powershell
$env:PROJECT_A_MCP_SERVER_URL='http://127.0.0.1:8765/mcp'
$env:PROJECT_A_MCP_CAPTURE_TOOL='project_a_capture_snapshot'
$env:PROJECT_A_CAPTURE_TOKEN='<set-locally-without-echoing>'
$env:PROJECT_A_CAPTURE_SERVER_PID='<verified-8765-listener-pid>'
```

The MCP result must bind the exact job, source event, stage, capture scope,
XAUUSD symbol, fresh structured-read completion, screenshot completion, capture
time, and image evidence IDs. The worker persists every returned image and
verifies its SHA-256. Missing, partial, stale, unbound, oversized, or
hash-mismatched evidence cannot reach the provider. `LIQ_BASELINE` requests use
the full baseline; `E1_DELTA` requests
use the latest materialised Story State, at most six immutable prior Grade
summaries, the current E1, and the new evidence delta. Old screenshot bytes are
not resent.

## Commands (PowerShell)

Set the common database path without printing secrets:

```powershell
$runtime='C:\Users\jones.w\TradingSys\trading-auto'
Set-Location $runtime
$env:PROJECT_A_DB='C:\Users\jones.w\TradingSys\trading-auto\storage\project_a.db'
```

Start the existing webhook server:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m ingest.webhook_server
```

Start the persistent worker in the safe provider-disabled mode:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.worker --db $env:PROJECT_A_DB
```

Configure only the model identity (no default or fallback model is used):

```powershell
$env:PROJECT_A_OPENAI_MODEL='<Jones-approved-model-id>'
```

Verify worker heartbeat and inspect jobs/story:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB health
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB jobs --status PENDING_CAPTURE
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB jobs --status TECHNICAL_FAILURE
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB jobs --status COMPLETED
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB active-story
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB audit --limit 50
```

Record Jones's only two story-closing decisions:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB decision --story-id <story_id> --value ENTERED
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB decision --story-id <story_id> --value SKIPPED
```

Stop safely with `Ctrl+C`. For a hidden Windows process, record the returned PID
and stop only that exact PID before starting the same command again:

```powershell
$process = Start-Process uv -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -ArgumentList @('run','--python','3.11','--with-requirements','requirements.txt','python','-m','project_a_analysis.worker','--db',$env:PROJECT_A_DB)
$process.Id
Stop-Process -Id <recorded-worker-pid>
```

## One-request real-provider activation gate

Do not put a key in source, `.env` committed files, commands, logs, or chat.
Before one Jones-approved SHADOW request, set these in the process environment:

```powershell
$env:OPENAI_API_KEY='<set-locally-without-echoing>'
$env:PROJECT_A_OPENAI_MODEL='<Jones-approved-model-id>'
$env:PROJECT_A_OPENAI_BILLING_CONFIRMED='true'
```

Inspect the captured job and compute the exact model-bound request manifest:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB jobs --status CAPTURED
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.cli --db $env:PROJECT_A_DB request-manifest --job-id <job_id>
```

Then—and only after Jones approves that exact job and request SHA—run exactly:

```powershell
uv run --python 3.11 --with-requirements requirements.txt python -m project_a_analysis.worker --db $env:PROJECT_A_DB --once --approve-one-shadow-request --approved-job-id <job_id> --approved-request-sha256 <lowercase-64-hex>
```

The approval flag is rejected without `--once` and both identities. The worker
claims only that job and fails closed if the captured request hash changed.

The request contains the fixed analyst instructions, story/analysis identities,
bounded Story Memory, canonical trigger, structured evidence, evidence manifest,
and only the screenshots named and hash-verified by the completed manifest.
Screenshots are sent as base64 data URLs with `detail=high`. The response is
constrained and revalidated against `PROJECT_A_GRADE_SCHEMA_V1`; prose, missing
fields, additional fields, bad ranges, and identity changes fail as
`TECHNICAL_FAILURE`. The provider receives no tools.

Estimate text tokens from the final canonical request before approval (rough
planning approximation: UTF-8 character count divided by four). Image tokens
depend on the selected model, dimensions, and detail mode; use the selected
model's current official pricing/token calculator. Recommended spend control:
fund a small hard project budget, retain the one-request CLI gate, inspect the
request manifest and screenshot count, and set a usage alert below that budget
before the first call.
