# Project A integration foundation

Session 0 owns this offline foundation. It does not implement Sessions 1–5 and
does not enable a live dependency.

## One-command replay

```powershell
py -m project_a.replay --all
```

Optional inspectable file:

```powershell
py -m project_a.replay --all --output storage\json\project_a_replay.json
```

The command validates every golden event path, then replays accepted raw event →
Analysis Request → fake AI Verdict → canonical Thesis → fake TradingView,
Telegram, Notion, and MT5 Demo outputs. It exits non-zero for contract, identifier,
environment, or shadow-safety failure. It performs no network call and places no
order.

## Contract and integration tests

```powershell
py -m pytest tests/test_project_a_contracts.py tests/test_project_a_replay.py -q
```

## Golden fixture inventory

`fixtures/project_a/event_cases.json` contains:

- valid accepted alert;
- explicit rejected alert;
- structural break lifecycle event;
- semantically invalid Analysis Ready payload;
- expired/stale event;
- missing required field;
- unsupported schema version;
- invalid enum/timeframe;
- duplicate/replayed event.

Standalone artifacts are `analysis_request_accepted.json` (fake accepted request),
`ai_verdict_approved.json` (fake AI verdict), `thesis_lifecycle.json` (armed,
invalidated, and expired versions), and `downstream_output.json` (four fake
outputs). They contain no live data, credentials, personal data, or external
dependency.

## Navigation

- `contracts/README.md`: frozen schema rules and compatibility.
- `contracts/CHANGE_REQUEST.md`: only allowed schema-change workflow.
- `MODULE_MAP.md`: real repository/runtime/persistence map and conflicts.
- `OWNERSHIP_AND_BRANCH_PLAN.md`: exact paths, branch/merge plan, release gates.
- `RISKS.md`: concrete risk register.
- `SECURITY_ROLLBACK_RELEASE.md`: security, rollback, shadow-release checklist.
- `DECISIONS.md`: source links, decisions, assumptions, and architecture feedback.

## Foundation definition of done

- [x] Four requested versioned schemas exist and are pinned.
- [x] Structural and semantic validation fails closed with stable reasons.
- [x] Golden fixtures cover required valid/invalid/lifecycle/output paths.
- [x] Identifiers and causation survive the full fixture chain.
- [x] Offline replay needs no AI/broker/TradingView/MT5/API.
- [x] XAUUSD/SHADOW/MT5_DEMO/port 4999/1m/10 points/1:1 are enforced.
- [x] Ownership, compatibility, risks, security, and rollback are explicit.
- [ ] Complete tests and final commit SHA recorded by Session 0 closeout.
