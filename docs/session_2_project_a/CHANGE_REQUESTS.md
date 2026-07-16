# Session 2 integration decisions requested

## CR-S2-001: Analysis Ready spread location

Event 0.2 does not require a normalized spread field and the frozen `accepted_alert` fixture omits it. The Session 2 safety boundary cannot prove `spread <= 10` from that document. No schema was changed. The runtime requires finite `payload.spread_points` for Analysis Ready and rejects ambiguous `spread`, pip, tick, or USD representations.

Session 0 should decide whether to: (a) approve this payload-bag producer convention and add non-frozen producer/runtime examples, or (b) start the formal contract change process to make normalized spread explicit in Event 0.3. Session 1 must not emit Analysis Ready to this runtime until the selected convention is implemented. An adapter cannot safely infer normalized points.

## CR-S2-002: Ingest versus capture port wording

The Project A docs/config pin TradingView/XAUUSD to `4999`, while the earlier Session 2 brief also called it the webhook port. Jones corrected the scope: `4999` is reserved for Session 3 CDP/MCP capture. The repository's authoritative webhook listener remains `8000` by default. Session 2 therefore adds `/project-a/v0.2/events` to that listener, makes its bind independently configurable, and refuses `4999`.

Session 0 should update frozen integration documentation/config naming so `tradingview.*.port` is unambiguously a capture port and separately record the ingest listener/endpoint. No contract change is needed.

## DR-S2-003: Time profile

No frozen source defines future/stale tolerance. Session 2 proposes explicit fail-closed runtime defaults: 5 seconds future tolerance and 30 minutes stale threshold, with explicit `SETUP_EXPIRED` lifecycle reports allowed to close state after the threshold. Session 0 should approve or replace these values before integration shadow traffic. This changes runtime profile, not wire schema.

## MR-S2-004: Database promotion

Session 2 deliberately uses `storage/project_a.db` and a module-local migration ledger. Session 0 can merge it as an isolated database with no shared migration, or promote the exact additive `project_a_*` schema from `ingest/project_a/database.py` into its future shared migration path. Promotion must retain the version/checksum ledger semantics, run on a disposable copy first, back up `trading.db`, execute `PRAGMA integrity_check`, and rerun restart/outbox/replay tests. Do not copy only selected tables or point two independent migration ledgers at the same names.
