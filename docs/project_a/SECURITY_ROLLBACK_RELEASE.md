# Security, rollback, and shadow-release checklist

## Security gate

- [ ] `git status` contains no `.env`, credentials, runtime DB, screenshots, or logs.
- [ ] Secret scan covers tracked diff and fixture values; raw logs redact tokens,
      passwords, API keys, private keys, account identifiers, and personal data.
- [x] Contract documents have a 256 KiB limit and strict envelope fields.
- [x] Unknown fields fail closed except the documented event payload extension bag.
- [x] Malformed/non-finite/incorrect-timezone documents fail before adapters.
- [x] Malformed AI output cannot become a thesis; actionable output rechecks all
      hard gates and exact 1:1 geometry.
- [ ] Logging implementation review proves no security-sensitive field leakage.
- [ ] Durable idempotency/replay protection exists at ingest and every output.
- [x] Offline replay makes no AI, broker, TradingView, MT5, Telegram, Notion, or
      other network call.
- [x] Session 0 adds no broker SDK/import and places no order.
- [ ] OpenClaw uses dedicated workspace, Jones allowlist/DM pairing, sandbox,
      minimal filesystem/exec/browser permissions, and no broker live credentials.

## Shadow environment gate

- [x] Enabled instrument list is exactly `XAUUSD`.
- [x] Mode is exactly `SHADOW`.
- [x] Execution environment is exactly `MT5_DEMO`.
- [x] `live_execution=false` and `order_placement=false`.
- [x] TradingView profile is XAUUSD, port 4999, base timeframe 1m.
- [x] Spread maximum is 10 normalized points and RR is 1.0.
- [x] Missing/changed environment identity causes non-zero replay failure.
- [x] USTEC and DE40 profiles are disabled; no automatic symbol expansion.
- [ ] Real adapters independently verify identity before every side effect.

## Rollback procedure

1. Stop Project A writers and external shadow adapters. Do not delete artifacts.
2. Record current integration SHA, config hash, contract versions, database path,
   and service state. Preserve logs with sensitive fields redacted.
3. If a database migration exists, take an SQLite backup and integrity check
   before migration. Run only the migration's reviewed down plan; never improvise
   destructive SQL. This foundation deliberately introduces no DB migration.
4. Restore the previous known-good integration commit and its pinned config as a
   unit. Do not mix older readers with newer breaking writers.
5. Run `py -m pytest tests/test_project_a_contracts.py
   tests/test_project_a_replay.py -q` and `py -m project_a.replay --all`.
6. Verify XAUUSD/SHADOW/MT5_DEMO/no-order identity in output.
7. Resume offline replay first, then internal shadow logging. External adapters
   remain disabled until their individual idempotency checks pass.
8. Document cause, lost/duplicated artifacts, recovery evidence, and the new
   known-good SHA.

Contract rollback limitation: after a breaking new version is persisted, do not
resume an older writer/reader unless a tested down-converter exists. Stop and
preserve raw data instead.

## Release checklist

- [ ] All contract/replay and complete repository tests pass.
- [ ] Formatting, compile, and configured lint/type checks pass.
- [ ] Module map, decisions, ownership, risks, and change ledger are current.
- [ ] Feature PRs contain no unapproved shared-file edits.
- [ ] Database migration/rollback evidence attached if applicable.
- [ ] Adapter partial-failure and retry tests prove no duplicates.
- [ ] 20–30 XAUUSD Analysis Ready shadow samples pass, including Asian and
      London/New York, rejection, structural-break, duplicate, and expired cases.
- [x] Previous known-good pre-Project-A baseline SHA: `dfe5e07`.
- [ ] Jones approval obtained for any authority beyond fake/dry-run Demo artifacts.
