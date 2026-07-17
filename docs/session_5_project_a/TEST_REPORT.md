# Session 5 verification report

Run on Windows from `project-a/session-5-outputs-acceptance-v1` at the recorded
baseline plus Session 5 working changes. All external transports were fakes.

| Check | Command | Exact result |
|---|---|---|
| Session 0 contracts/replay tests | `py -m pytest tests/test_project_a_contracts.py tests/test_project_a_replay.py -q` | `16 passed in 0.97s` |
| Session 0 offline replay | `py -m project_a.replay --all` | exit 0; `ok=true`, `SHADOW`, `MT5_DEMO`, `live_execution=false` |
| Session 5 tests | `py -m pytest tests/session_5_project_a -q` | `65 passed in 9.83s` |
| Recorded acceptance | `py -m output.project_a.acceptance --output ... --markdown ...` | exit 0; 28/28 fake samples passed; 0 real samples claimed |
| Python compile | `py -m compileall -q analyze capture contracts gates ingest output precheck project_a publish scheduler scripts storage tests` | exit 0 |
| Dependency consistency | `py -m pip check` | `No broken requirements found.` |
| Fake config validation | `py -m output.project_a.ops validate-config docs\session_5_project_a\RECORDED_FAKE_CONFIG.yaml` | exit 0; shadow/dry-run true |
| Replay one renderer | `py -m output.project_a.replay --db <temp> --renderer TELEGRAM` | exit 0; one fake message; zero other transport effects |
| SQLite integrity/status | `py -m output.project_a.ops --db <temp> status` | `integrity_check=ok` |
| Full repository suite | `py -m pytest tests/ -q` | `467 passed, 1 skipped, 1 failed in 21.27s` |
| Full suite excluding baseline failure | `py -m pytest tests/ -q -k 'not test_dual_command_copies_are_byte_identical'` | `467 passed, 1 skipped, 1 deselected in 18.23s` |

The sole full-suite failure is unchanged from the pre-edit baseline:
`tests/test_analyze_live_freshness_contract.py::test_dual_command_copies_are_byte_identical`.
The inner tracked command is checked out with CRLF while the outer workspace copy
uses LF. Session 5 owns neither file and did not rewrite them.

Secret/safety pattern review covered Session 5 code, docs, tests, config, and
recorded artifacts. Matches were only negative tests/error names or documentation
stating forbidden `order_send`/MetaTrader5/live behavior. No credentials, tokens,
cookies, account secrets, private destinations, or live configuration were found.
Frozen contract and fixture paths have no diff.

No formatter, lint, type-check, migration-runner, or CI configuration exists in
the repository. `ruff` and `mypy` are not installed (`No module named ...`), so no
lint/type pass is claimed. The branch adds no dependency and no shared database
migration.

Real integration evidence: none. No real TradingView mutation, Telegram message,
Notion write, MT5 connection, or MT5 Demo order was attempted.
