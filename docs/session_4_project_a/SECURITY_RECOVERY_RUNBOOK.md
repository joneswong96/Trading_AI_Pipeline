# Project A reviewer security and recovery runbook

All commands are examples for Jones to run locally. Steps marked **STOP** require
Jones's explicit interaction because they install software, modify user-level
OpenClaw state, authenticate, pair Telegram, or handle private identifiers.
Never paste tokens, cookies, OAuth responses, or the numeric Telegram ID into
chat, Git, command arguments, or screenshots.

## 1. Offline validation (safe now)

```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto-session4
py -m pytest tests\session_4_project_a -q
py -m pytest tests\test_project_a_contracts.py tests\test_project_a_replay.py -q
py -m project_a.replay --all
```

Validate the template with non-secret values. Use paths dedicated to Project A,
not the repository, home directory, browser profile, or credential directory:

```powershell
$env:PROJECT_A_REVIEWER_WORKSPACE = 'C:\OpenClaw\project-a-reviewer\workspace'
$env:PROJECT_A_REVIEWER_AGENT_DIR = 'C:\OpenClaw\project-a-reviewer\agent'
$env:PROJECT_A_REVIEWER_MODEL = 'openai/<PINNED_REVIEWED_MODEL>'
$env:PROJECT_A_TELEGRAM_USER_ID = Read-Host 'Jones numeric Telegram user ID (local only)'
py -m project_a_ai_review.cli validate-config
Remove-Item Env:PROJECT_A_TELEGRAM_USER_ID
```

Missing/invalid user ID, wildcard access, sandbox-off, browser-on, missing tool
denies, non-loopback Gateway, or group access must make validation fail.

## 2. Installation readiness (**STOP**)

Current audit: OpenClaw is absent and Node 20.18.1 is below the current official
OpenClaw requirement (Node 22.22.3+, 24.15+, or 25.9+; Node 24 recommended).
Do not install/upgrade during an unattended Session 4 run.

After Jones approves an installation path, use the current official Windows Hub,
PowerShell installer, or WSL2 instructions from
<https://docs.openclaw.ai/install>. Pin the exact OpenClaw version after install:

```powershell
node --version
openclaw --version
openclaw doctor --lint
openclaw security audit --deep --json
```

Record the exact version in release evidence and configure the adapter's
`--required-version`. Do not use `latest` in a released runtime.

## 3. Dedicated agent/workspace (**STOP: user-level config change**)

Create only after reviewing the rendered template:

```powershell
openclaw agents add project-a-reviewer `
  --workspace 'C:\OpenClaw\project-a-reviewer\workspace' `
  --model 'openai/<PINNED_REVIEWED_MODEL>' `
  --non-interactive
openclaw agents list --bindings --json
```

Merge the reviewed `config_templates/project_a_reviewer/openclaw.json` values
through `openclaw config set`/the supported setup UI. Do not overwrite an
existing `~/.openclaw/openclaw.json` wholesale. Keep the dedicated `agentDir`,
workspace, state, and Telegram account isolated. Copy only the provided
workspace `AGENTS.md` and empty `MEMORY.md`; do not copy personal memory.

Restart and capture effective evidence:

```powershell
openclaw gateway restart
openclaw agents list --bindings --json
openclaw sandbox explain --agent project-a-reviewer
openclaw security audit --deep --json
openclaw policy check
```

Required evidence: sandbox `mode=all`, `scope=session`, Docker backend, no
network, workspace `none` or `ro`, browser disabled, host-browser control false,
exec/process/read/write/edit/apply_patch/browser/web/message/session/plugin tools
denied, elevated false, and no broker/credential bind mounts.

## 4. Filesystem/browser/exec/broker denial

Before release, use a disposable canary request and inspect effective policy:

```powershell
openclaw sandbox explain --session 'agent:project-a-reviewer:review_<TEST_HASH>'
openclaw logs --follow
```

Attempting filesystem listing, shell execution, web fetch, browser open, message
send, or node/computer control must be denied by policy. Confirm the agent cannot
read a canary outside `C:\OpenClaw\project-a-reviewer\workspace`, cannot see
browser profiles, `.ssh`, cloud config, repository `.env`, or user home, and has
no broker library/credential/network route. Any success is a release blocker.

The Gateway remains on the host and the OpenClaw sandbox is documented as an
imperfect boundary. Keep Gateway loopback-only, authenticated, rate-limited, and
with Control UI/terminal disabled.

## 5. Codex OAuth (**STOP: Jones interactive login**)

Use official interactive authentication only, targeting the dedicated agent:

```powershell
openclaw models auth --agent project-a-reviewer login `
  --provider openai `
  --profile-id openai:project-a-reviewer
openclaw models auth --agent project-a-reviewer list --provider openai
openclaw models status --agent project-a-reviewer --check
openclaw models status --agent project-a-reviewer --probe `
  --probe-provider openai `
  --probe-timeout 30000 `
  --probe-max-tokens 8
```

`--check` exits non-zero for missing/expired/expiring auth. `--probe` is a real
request and can consume quota; use only for acceptance/diagnosis. Never open or
print `auth-profiles.json`; only list non-secret profile metadata.

### OAuth expiry/recovery

1. Disable new review dispatch; retain pending requests and do not extend expiry.
2. Record `AUTHENTICATION_UNAVAILABLE`, provider/model/auth mode only.
3. Run non-secret `models status --agent ... --check`.
4. **STOP:** Jones reauthenticates with the login command above. If stuck, add
   `--force`; this deletes the selected agent's saved provider profiles before
   rerunning login and does not revoke access provider-side.
5. Re-run security audit, auth check/probe, then retry only unexpired requests.

### Revoke/rotate

Disable the agent/channel first. Remove provider auth through the supported
OpenClaw Gateway control plane for `project-a-reviewer`, verify the profile is
absent with `models auth ... list`, and revoke OpenClaw access in the OpenAI
account/provider security dashboard. Removing local auth alone does not revoke
provider-side access. Rotation changes protected runtime state only, never Git.

## 6. Rate limit, timeout, and model outage

- `RATE_LIMITED`, `MODEL_TIMEOUT`, and `MODEL_UNAVAILABLE` remain technical
  failures. Never convert them to REJECT or switch provider/model silently.
- Default adapter timeout is 90 seconds; total attempts default to two.
- Retry only with the same bundle/prompt/model fingerprint and `retry_of` attempt
  ID. Every retry rechecks artifacts, freshness, spread, RR, and expiry.
- If the request expires, stop; do not extend `expires_at`.
- Subscription OAuth is best-effort and not an SLA. Use the manual fallback only
  with an explicitly selected/audited provider and model.

## 7. Telegram pairing (**STOP: Jones pairing/ID confirmation**)

Keep `channels.telegram.enabled=false` until OAuth, sandbox, and policy checks
pass. Store the bot token only through the approved SecretRef/service environment.
Use a numeric ID, never a username.

```powershell
openclaw pairing list telegram --account project-a-reviewer
openclaw pairing approve telegram <PAIRING_CODE> --account project-a-reviewer --notify
openclaw channels status --probe
openclaw security audit --deep --json
```

Jones must verify the pairing event's `from.id` locally, set it as the single
`allowFrom` entry, confirm `dmPolicy=pairing`, `groupPolicy=disabled`, empty
groups/group allowlist, `configWrites=false`, and no wildcard. Pairing approval
does not authorize groups. Unknown users must remain unpaired/denied and audited
without message contents. Use BotFather `/setjoingroups` to deny group adds where
appropriate.

Allowed deterministic commands only:

- `/review <known_request_id>`
- `/status <known_request_id>`
- `/retry <known_request_id>`
- `/cancel <known_request_id>`
- `/health`

Free text, filesystem paths, pasted bundles, shell/tool/live-order/bypass
commands, groups, channels, usernames, and unknown users are denied.

## 8. Start/review/inspect/retry/cancel

Keep Telegram and real OpenClaw disabled for the recorded manual proof:

```powershell
$audit = 'C:\OpenClaw\project-a-reviewer\audit'
py -m project_a_ai_review.cli review-recorded `
  --dispatch fixtures\session_4_project_a\dispatch_recorded.json `
  --response fixtures\session_4_project_a\candidates\approve.json `
  --artifact-root fixtures\session_4_project_a\artifacts `
  --audit-root $audit `
  --provider fixture `
  --model recorded-reviewer `
  --auth-mode none `
  --now 2026-07-16T00:00:03Z
py -m project_a_ai_review.cli verify-audit `
  --audit-root $audit `
  --request-id req_xau_20260716_0001
```

For a real reviewed installation, use `review-openclaw` with the pinned exact
model/version and a dedicated staging/audit root. Do not run it until the
Gateway-only transport issue in the architecture document is resolved and the
real smoke gate is approved.

Retry passes `--retry-of <attempt_id>`. Cancel a pending OpenClaw run through the
supported task/session cancel command, then record `CANCELLED`; never manufacture
a verdict. A stale lock after a confirmed dead process requires Jones review of
the request audit directory before removing only that request's `.lock`.

## 9. Disable and prove no live route

```powershell
openclaw agents unbind --agent project-a-reviewer --all
openclaw gateway stop
openclaw agents list --bindings --json
```

Do not delete the agent/workspace/audit until evidence is retained. Confirm:

- Telegram disabled/unbound;
- no active Project A review session;
- no browser/exec/network tool;
- no broker credentials or imports;
- no Session 5/MT5 calls in the audit;
- repository config remains `SHADOW`, `MT5_DEMO`, `live_execution=false`, and
  `order_placement=false`.

## 10. Configuration drift/change control

After any OpenClaw/model/prompt/config/plugin/skill change:

1. Disable dispatch.
2. Record new exact versions/hashes.
3. Re-render and validate the template.
4. Run `doctor --lint`, deep security audit, policy check, sandbox explain, tool
   canaries, offline tests, and a separately labelled real smoke test.
5. Session 0 approves release. Completed verdicts remain immutable.
