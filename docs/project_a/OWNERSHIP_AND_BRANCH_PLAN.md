# Ownership matrix and branch plan

Session 0 is the sole merge owner and conflict-resolution owner.

| Session | Branch | Exclusive feature paths | Shared inputs (read-only) | Deliverable dependency |
|---|---|---|---|---|
| 0 Integration | `project-a/integration-v1` | `contracts/**`, `fixtures/project_a/**`, `project_a/**`, `config/project_a.yaml`, `tests/test_project_a_*`, `docs/project_a/**`, future `migrations/**` and CI integration config | all repository paths for audit | Starts first; merges last |
| 1 Pine sensor | `project-a/session-1-pine` | Existing/approved Pine source location and Session 1 tests/docs only; repository path must be declared in its baseline audit | Event 0.2 schema/fixtures | Event producer first |
| 2 Ingest/state | `project-a/session-2-ingest` | `ingest/**` and Session 2 tests/docs | Event schema/fixtures | After contracts; parallel with 1/3 |
| 3 Capture/compiler | `project-a/session-3-compiler` | `capture/**`, new compiler-owned package, Session 3 tests/docs | Event + request schemas/fixtures | After contracts; consumes recorded events |
| 4 AI/operator | `project-a/session-4-ai-review` | New reviewer/operator package and Session 4 tests/docs; no hard-gate files | Request + verdict schemas/fixtures | After contracts; consumes recorded requests |
| 5 Outputs | `project-a/session-5-outputs` | `output/**`, `publish/**`, Session 5 tests/docs | Verdict + thesis schemas/fixtures | After contracts; consumes recorded verdicts |

`analyze/**`, `scheduler/**`, `storage/**`, `requirements.txt`, root config, and
database shape are shared/legacy-sensitive: a feature session must request Session
0 ownership before editing them. Existing tests may be extended by their module
owner, but frozen contract tests are Session 0-only.

## Workflow

1. Every session branches from the pinned integration commit and records that SHA.
2. A builder first produces its baseline audit: existing commits, tests, working
   commands, path ownership, gaps, and contract change requests.
3. Feature PRs target `project-a/integration-v1`, never another feature branch.
4. Required review evidence: changed files, before/after tests, offline demo,
   sample contract artifact, rollback note, security note, limitations, and no
   shared-schema diff.
5. Session 0 reviews contract conformance and path ownership, rebases/merges one
   session at a time, and runs the complete gates after each merge.
6. Merge order: Session 1 producer → Session 2 ingest/state → Session 3 compiler →
   Session 4 reviewer → Session 5 outputs. Sessions may build in parallel from
   fixtures; order is for integration, not development blocking.
7. Conflicts in shared or legacy-sensitive files return to Session 0. Feature
   sessions do not resolve them by changing frozen contracts.
8. Contract proposals follow `contracts/CHANGE_REQUEST.md`.

## Final release gates

- Clean ownership diff and approved contract-change ledger.
- Schema meta-validation and all golden fixture/contract tests pass.
- Full no-network replay passes and outputs remain inspectable.
- Repository formatting/compile/type checks available to the repo and complete
  pytest suite pass, or pre-existing failures are separately evidenced.
- No secrets or generated runtime artifacts are tracked.
- XAUUSD only; port 4999; 1m base; spread ≤10 normalized points; RR 1:1.
- SHADOW and MT5_DEMO identity verified; live/order placement false and fail closed.
- Output idempotency/outbox tests pass before any external shadow adapter is enabled.
- 20–30 XAUUSD Analysis Ready shadow samples, including reject/expired/break paths.
- Database backup/migration/rollback drill if a migration is later introduced.
- Previous known-good integration SHA and operator recovery command recorded.

## Handoff format

Each session hands back: branch and commit SHA; files changed; exact test commands
and results; demo command/output; known limitations/risks; requested contract
changes; rollback procedure; and the next session's required fixture/artifact.
