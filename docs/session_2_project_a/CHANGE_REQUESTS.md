# Session 2 retained runtime notes

## CR-S2-001: Analysis Ready spread location

Event 0.2 does not require a normalized spread field and the frozen `accepted_alert` fixture omits it. The Session 2 safety boundary cannot prove `spread <= 10` from that document. No schema was changed. The runtime requires finite `payload.spread_points` for Analysis Ready and rejects ambiguous `spread`, pip, tick, or USD representations.

This remains a legacy Event V0.2-only runtime convention. Wire/Canonical Event
V1 uses the accepted Event V1 validation and semantic projection without
changing the frozen V0.2 schema.

## CR-S2-002: Ingest versus capture port wording

The Project A docs/config pin TradingView/XAUUSD to `4999`, while the earlier Session 2 brief also called it the webhook port. Jones corrected the scope: `4999` is reserved for Session 3 CDP/MCP capture. The repository's authoritative webhook listener remains `8000` by default. Session 2 therefore adds `/project-a/v0.2/events` to that listener, makes its bind independently configurable, and refuses `4999`.

The correction keeps ingest configurable/default `8000` and rejects `4999`.
No contract change was made.

## DR-S2-003: Time profile

No frozen source defines future/stale tolerance. Session 2 proposes explicit fail-closed runtime defaults: 5 seconds future tolerance and 30 minutes stale threshold, with explicit `SETUP_EXPIRED` lifecycle reports allowed to close state after the threshold. Session 0 should approve or replace these values before integration shadow traffic. This changes runtime profile, not wire schema.

## MR-S2-004: Database promotion

Session 2 keeps `storage/project_a.db` for the first shadow cycle and adds
checksum-ledger migration 2 for the durable Event V1 authority. Any later
promotion must retain both checksums, run on a disposable copy first, back up
`trading.db`, execute `PRAGMA integrity_check`, and rerun
restart/concurrency/outbox/replay tests. Do not copy selected tables or point two
independent migration ledgers at the same names.
