# Project A Session 0 decision log

## Sources read

- [Project A Hub](https://app.notion.com/p/4034328f1d0c419fa31f77b864456318)
- [Project A Analysis Skill](https://app.notion.com/p/d542adfd96a74affb66fa17379066c18)
- [Phase 1 Hub](https://app.notion.com/p/4ca9012caca3467c8f50d861873285c8)
- [Phase 2 Hub](https://app.notion.com/p/5003182d3f3245fbb19022f23995211a)
- [Phase 3 Hub](https://app.notion.com/p/c3f76e8aac3c49738a27ee14beb9dff4)
- Repository commit `dfe5e07`, `AGENTS.md`, `CLAUDE.md`, config, runbook, schema/
  persistence modules, output adapters, and tests.

## Decisions

1. **File contracts plus semantic Python validation.** JSON Schema Draft 2020-12
   provides portable shape definitions; `contracts.validation` preserves the
   repository convention of deterministic Python hard gates. `jsonschema` is now
   an explicit dependency rather than an accidental environment package.
2. **Strict envelopes, one event extension bag.** Unknown envelope fields reject
   to prevent silent semantic drift. Legacy producers need an adapter, while
   `event.payload` retains bounded forward-compatible telemetry.
3. **Explicit disposition.** Rejected, structural-break, invalid, expired, and
   duplicate paths are first-class values, not inferred from log text.
4. **One canonical TP and exact 1:1.** Legacy `tp1/tp2` and config 1R/2R/3R are
   not carried into frozen Project A contracts. Display adapters may not alter
   geometry.
5. **Verdict and thesis state remain separate.** AI emits four allowed verdicts;
   deterministic code maps them into append-only thesis lifecycle states.
6. **No database migration yet.** Existing tables cannot safely be expanded
   without knowing Sessions 2/3/5 persistence designs, and Session 0 must not
   invent feature storage. Contracts/fixtures unblock independent development.
   Any migration remains Session 0-owned and must include backup/down evidence.
7. **Port conflict fails closed.** Project A pins 4999. Legacy 9222/9333 code is
   unchanged; Session 3 must build a verified adapter or escalate architecture.
8. **MT5 Demo means fake/dry-run under current repository authority.** The Hub's
   Demo mirror does not override the repository's explicit no-broker-API rule.
   Any actual MT5 connection requires a separate Jones decision.
9. **No feature code modifications.** Session 0 foundation lives in exclusively
   owned paths plus the necessary dependency declaration.
10. **No migration of legacy statuses/payloads by coercion.** Compatibility must
    be explicit, tested, and auditable; invalid input is quarantined/rejected.

## Assumptions

- `XAUUSD` uses venue `ICMARKETS` and point size `0.01` in deterministic fixtures;
  broker adapters remain responsible for verified normalized-point conversion.
- UTC timestamps ending in `Z` are the only wire representation even though
  local operations use Australia/Sydney.
- The recorded fixtures are development artifacts, not evidence for the final
  20–30 real shadow-sample acceptance gate.
- `setup_id` is stable across lifecycle changes; `event_id`, `request_id`,
  `verdict_id`, and `thesis_id` are distinct identities linked by causation.

## Architecture feedback

The six-session split is reasonable only with frozen fixtures and exclusive paths;
without those, the current monolithic runtime and ad-hoc persistence would make
parallel changes unsafe. The strongest existing ideas are deterministic gates,
append-only thesis versions, replayable artifacts, and blocked external sends in
tests. The weakest assumptions are that a port transition is trivial, that JSONL
plus three lazy SQLite schemas form a reliable integration bus, and that a Demo
mirror is automatically safe without environment attestation and an outbox.

Before Sessions 1–5 begin, pin the Session 0 commit, require every session's
baseline audit, and resolve whether Project A replaces or coexists with the
9222/9333 runtime. Do not introduce an MT5 SDK or OpenClaw write authority during
feature development. Build adapters against fixtures first; add persistence and
external shadow side effects only after failure-injection/idempotency tests.
