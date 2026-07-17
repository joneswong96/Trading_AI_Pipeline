# Session 2 Project A runbook

Run from the repository root in PowerShell. These commands require no production secret or live service.

## Dependencies and clean database

```powershell
py -m pip install -r requirements.txt
$env:PROJECT_A_DB = "$PWD\storage\project_a.db"
py -m ingest.project_a.admin init
py -m ingest.project_a.admin health
```

Initialization transactionally applies migrations 1 and 2, records both
checksums, and verifies SQLite integrity. For a disposable clean start, stop the
service, preserve any existing database, set `PROJECT_A_DB` to a new path, then
run `init`. Never delete an active database.

Wire Event V1 ingest is disabled by default. Offline test profiles may set
`PROJECT_A_V1_INGEST_ENABLED=true`; do not treat that as runtime activation.

## Start and verify routing

Port `4999` is reserved for Session 3 capture. The existing safe webhook port is `8000`.

```powershell
$env:PROJECT_A_INGEST_HOST = "0.0.0.0"
$env:PROJECT_A_INGEST_PORT = "8000"
py -m ingest.webhook_server
```

If another safe legacy listener already owns `8000`, stop the duplicate process; do not move either service to `4999`. In another shell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/project-a/v0.2/health/live
Invoke-RestMethod http://127.0.0.1:8000/project-a/v0.2/health/ready
Invoke-RestMethod http://127.0.0.1:8000/project-a/v0.2/metrics
```

## Send fixture-derived valid and malformed events

The frozen accepted fixture lacks the runtime spread gate. Create an in-memory request from it without modifying the fixture, add explicit normalized points, and make timestamps current:

```powershell
$cases = Get-Content -Raw fixtures\project_a\event_cases.json | ConvertFrom-Json
$event = $cases.accepted_alert.payload
$now = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$event.occurred_at = $now
$event.received_at = $now
$event.payload | Add-Member -NotePropertyName spread_points -NotePropertyValue 5 -Force
$body = $event | ConvertTo-Json -Depth 20 -Compress
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8000/project-a/v0.2/events -ContentType application/json -Body $body
Invoke-WebRequest -SkipHttpErrorCheck -Method Post -Uri http://127.0.0.1:8000/project-a/v0.2/events -ContentType application/json -Body '{broken'
```

## Inspect state

```powershell
py -m ingest.project_a.admin inspect receipts --limit 20
py -m ingest.project_a.admin inspect state --limit 20
py -m ingest.project_a.admin inspect outbox --limit 20
py -m ingest.project_a.admin inspect dead-letters --limit 20
```

Use a SQLite read-only client for deeper queries. Relevant tables include
`project_a_raw_receipts`, `project_a_receipt_transactions`,
`project_a_exact_dedupe`, `project_a_semantic_dedupe`,
`project_a_receipt_processing`, `project_a_canonical_events`,
`project_a_setup_state`, `project_a_setup_state_v1`,
`project_a_setup_state_history`, `project_a_outbox`,
`project_a_outbox_attempts`, and `project_a_dead_letters`.

## Outbox retry/recovery

```powershell
py -m ingest.project_a.admin retry-outbox out_REPLACE_WITH_ID
py -m ingest.project_a.admin recover-claims
```

Session 3 consumers use `ProjectAIngestService.claim_outbox(worker_id)`, `deliver_outbox(outbox_id, worker_id)`, and `fail_outbox(...)`. They must deduplicate on `dispatch_key`.

`recover-claims` also marks stale V1 ingress claims `ABANDONED`.
`COMMIT_UNKNOWN` and abandoned V1 outboxes remain unclaimable; never manually
flip `release_authorized`.

## Replay

Dry-run is default and copies the real database to an isolated temporary database:

```powershell
py -m ingest.project_a.replay --receipt ing_REPLACE_WITH_ID
py -m ingest.project_a.replay --event evt_REPLACE_WITH_ID
py -m ingest.project_a.replay --setup setup_REPLACE_WITH_ID --limit 100
py -m ingest.project_a.replay --batch --limit 100
py -m ingest.project_a.replay --fixture fixtures\project_a\event_cases.json --case accepted_alert
```

Replay detects stored Event V0.2 versus Wire Event V1 bytes. V1 replay enables
only the isolated replay service; it does not enable the HTTP endpoint.

Committed replay requires explicit authority and remains idempotent:

```powershell
py -m ingest.project_a.replay --receipt ing_REPLACE_WITH_ID --commit
```

The exact frozen accepted fixture dry-run reports `SPREAD_POINTS_REQUIRED`; this is deliberate CR-S2-001 evidence. Use the HTTP fixture-derived command above for a dispatch-eligible event.

## Stop, backup, integrity, and rollback

Stop safely with `Ctrl+C`; do not kill SQLite during a write. Then:

```powershell
$stamp = Get-Date -Format yyyyMMdd-HHmmss
Copy-Item -LiteralPath $env:PROJECT_A_DB -Destination "$env:PROJECT_A_DB.$stamp.bak"
py -c "import sqlite3,os; c=sqlite3.connect(os.environ['PROJECT_A_DB']); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()"
```

Code rollback: stop writers, record the branch SHA and database schema version,
restore the previous known-good integration commit, and keep the Project A
database untouched. Older code that does not know schema version 2 must not
write it. Because this is a dedicated additive database, rollback does not
require mutating legacy `trading.db`.

If readiness reports an incompatible/partial schema, stop ingestion, back up the database, preserve raw records, and escalate to Session 0. Do not edit the ledger or run improvised destructive SQL.

Confirm shadow-only mode at any time:

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/project-a/v0.2/health/ready) | Select-Object shadow_mode,live_execution,order_placement,enabled_symbol,ingest_port,reserved_capture_port
```
