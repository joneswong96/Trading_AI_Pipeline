# Project A integration risk register

Likelihood/impact: Low, Medium, High. A release gate is mandatory evidence, not a
promise to address later.

| Risk | L | I | Mitigation | Owner | Release gate |
|---|---|---|---|---|---|
| Legacy payloads are unversioned and conflict with Event 0.2 | High | High | Explicit adapter; quarantine invalid/unknown versions; never rewrite schema meaning | S2 + S0 | Recorded legacy samples convert or reject with expected reason |
| Hidden shared state across SQLite, JSONL, filesystem, and import-time singletons | High | High | Isolated test paths; transactional design review; durable IDs; crash/restart tests | S2/S5 | Restart replay proves no loss/duplicate |
| Fixed cooldown logic conflicts with state-change/no-new-evidence gate | High | High | Separate Project A state machine keyed by setup/evidence hash; preserve legacy path | S2 | Duplicate and new-evidence matrix passes |
| 9222/9333 runtime routing conflicts with Project A port 4999 | High | High | Dedicated verified profile; no fallback; adapter decision before wiring | S3 | 100% symbol/port/1m verification on shadow samples |
| Schema drift from feature branches editing frozen files | Medium | High | Exclusive Session 0 ownership and CI diff check | S0 | No unapproved frozen-path diff |
| Timestamp formats are naive/local/mixed | High | High | Require UTC `Z`; reject naive/offset values at contract boundary | S1–S5 | Timezone invalid fixtures fail |
| Duplicate/replay detection is short-window equality only | High | High | Stable event ID + payload hash + setup/evidence idempotency; durable uniqueness | S2 | Same-bar, same-hash, restart replay tests pass |
| AI output is nondeterministic or malformed | High | High | Fixed Verdict 1.0 parser; size limit; hard gates rechecked in Python; shadow only | S4 | Four verdicts + malformed/timeout tests pass |
| AI/prompt/screenshot content performs injection or exfiltration | Medium | High | Treat as untrusted; isolated agent; allowlist/sandbox; no broker credentials; secret scan | S4 | Threat model and permission audit pass |
| Existing DB lacks schema/version/correlation fields and migration ledger | High | High | Defer guessed migration; Session 0 additive migration with backup and down plan | S0/S2/S5 | Migration dry run + rollback on copy of DB |
| Multi-step thesis persistence is non-transactional | Medium | High | Idempotent append/outbox design using pinned IDs | S5/S0 | Failure-injection test across each write boundary |
| Telegram/Notion retries can duplicate or diverge | Medium | Medium | Durable outbox with per-adapter idempotency keys | S5 | Partial-failure replay produces one result/adapter |
| Secrets leak through raw payloads/logs/fixtures | Medium | High | Secret-like field rejection/redaction; git scan; test logs sanitized | All/S0 | No-secret scan and fixture review pass |
| Demo/live identity is absent, ambiguous, or accidentally changed | Medium | Critical | Exact constants in schema/config; fail closed; no broker imports in Session 0 | S0/S5 | Unsafe config tests fail; operator sees Demo identity |
| Existing MT5 scaffold is mistaken for authorization to connect | Medium | Critical | Keep fake/dry-run; require separate Jones decision for broker API | S0/S5 | Dependency/import/network audit shows no broker connection |
| Contract rollback after newer data is persisted loses meaning | Medium | High | Dual readers, stop writers first, retain raw immutable artifacts, no blind downgrade | S0 | Compatibility and rollback drill documented/passed |
| No CI/lint/type configuration currently exists | High | Medium | Use compile + pytest now; add minimal CI only through Session 0 review | S0 | Exact available checks recorded; no claimed check omitted silently |
| 20–30 real shadow samples are unavailable during foundation build | High | Medium | Recorded fixtures unblock development; real acceptance remains final release gate | S0/S5 | Sample pack and acceptance report complete |

## Incomplete rollback paths

The current repository has no database migration ledger, durable outbox, deploy
manifest, or automated service rollback. Therefore a code rollback alone is not
sufficient after future schema writes. Until those are implemented, Project A
must remain offline/shadow and persistence migrations must not be deployed.
