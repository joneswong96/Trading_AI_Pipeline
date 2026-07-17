# XAUUSD real shadow acceptance report template

Copy this file for the Session 0-controlled run. Do not mark recorded fake samples
as real. For every row attach the source fixture/artifact, actual renderer status,
idempotency evidence, safety result, retry/error evidence, and Call Log reference.

Common fields per sample: Sample ID; Setup ID; source fixture; verdict; expected
outputs; actual output statuses; idempotency result; safety-gate result; external
side effects used or mocked; Entry/SL/TP consistency; error/retry evidence; Call
Log consistency; pass/fail; reviewer notes.

| Sample | Scenario | Setup ID | Verdict | Expected outputs | Actual statuses | Idempotency | Safety gate | Side effects/mocks | Geometry | Retry evidence | Call Log | Pass | Reviewer notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R01 | APPROVE rejection-ready | | | | | | | | | | | | |
| R02 | APPROVE strong-break-ready | | | | | | | | | | | | |
| R03 | MODIFY validated geometry | | | | | | | | | | | | |
| R04 | REJECT | | | | | | | | | | | | |
| R05 | EXPIRED | | | | | | | | | | | | |
| R06 | Asian range context | | | | | | | | | | | | |
| R07 | London trend context | | | | | | | | | | | | |
| R08 | New York/overlap context | | | | | | | | | | | | |
| R09 | Duplicate replay | | | | | | | | | | | | |
| R10 | TradingView succeeds / Telegram fails | | | | | | | | | | | | |
| R11 | Telegram succeeds / Notion fails | | | | | | | | | | | | |
| R12 | Notion succeeds / MT5 Demo dry-run fails | | | | | | | | | | | | |
| R13 | MT5 uncertain response | | | | | | | | | | | | |
| R14 | TradingView partial objects | | | | | | | | | | | | |
| R15 | Process crash after external success | | | | | | | | | | | | |
| R16 | Restart abandoned-claim recovery | | | | | | | | | | | | |
| R17 | Terminal renderer failure | | | | | | | | | | | | |
| R18 | Thesis expires with pending tasks | | | | | | | | | | | | |
| R19 | Wrong symbol | | | | | | | | | | | | |
| R20 | Wrong port | | | | | | | | | | | | |
| R21 | Wrong tab | | | | | | | | | | | | |
| R22 | Wrong timeframe | | | | | | | | | | | | |
| R23 | Wrong broker feed | | | | | | | | | | | | |
| R24 | Spread above 10 points | | | | | | | | | | | | |
| R25 | Invalid RR | | | | | | | | | | | | |
| R26 | Telegram destination failure | | | | | | | | | | | | |
| R27 | Notion record/update failure | | | | | | | | | | | | |
| R28 | Outcome reconciliation | | | | | | | | | | | | |

Sign-off: reviewer, date/time (UTC and Australia/Sydney), branch/SHA, private
configuration hash, database integrity result, known deviations, and Jones
approval references for every real external smoke-test class.
