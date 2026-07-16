# XAUUSD shadow acceptance report - recorded fake evidence

> This is deterministic fake/recorded evidence. It is not the Session 0-controlled real 20-30 sample shadow run.

Samples: 28 | Passed: 28 | Failed: 0 | External side effects: none

| Sample | Setup | Verdict | Output statuses | Idempotency | Safety | Pass | Reviewer notes |
|---|---|---|---|---|---|---|---|
| S01 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "DRY_RUN_SUCCEEDED", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS | Recorded fixture executed with deterministic historical clock. |
| S02 | setup_xau_20260716_0001 | MODIFY | `{"MT5_DEMO": "DRY_RUN_SUCCEEDED", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS | Recorded fixture executed with deterministic historical clock. |
| S03 | setup_xau_20260716_0001 | REJECT | `{"NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS | Recorded fixture executed with deterministic historical clock. |
| S04 | setup_xau_20260716_0001 | EXPIRED | `{"NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS | Recorded fixture executed with deterministic historical clock. |
| S05 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "DRY_RUN_SUCCEEDED", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS | Recorded fixture executed with deterministic historical clock. |
| S06 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "DRY_RUN_SUCCEEDED", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS | Recorded fixture executed with deterministic historical clock. |
| S07 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS |  |
| S08 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "PENDING"}` | PASS | PASS | PASS |  |
| S09 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "DRY_RUN_SUCCEEDED", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "PENDING", "TRADINGVIEW": "PENDING"}` | PASS | PASS | PASS |  |
| S10 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS |  |
| S11 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "SUCCEEDED", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "PENDING"}` | PASS | PASS | PASS |  |
| S12 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "SUCCEEDED", "TRADINGVIEW": "PENDING"}` | PASS | PASS | PASS |  |
| S13 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "SUCCEEDED", "TRADINGVIEW": "PENDING"}` | PASS | PASS | PASS |  |
| S14 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS |  |
| S15 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "TERMINAL_FAILED"}` | PASS | PASS | PASS |  |
| S16 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "BLOCKED_SAFETY", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "BLOCKED_SAFETY", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS | PASS |  |
| S17 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "PENDING"}` | PASS | PASS | PASS |  |
| S18 | - | INVALID_INPUT | `{}` | NOT_APPLICABLE | PASS:schema_const | PASS |  |
| S19 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_port | PASS |  |
| S20 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_tab | PASS |  |
| S21 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_timeframe | PASS |  |
| S22 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_feed | PASS |  |
| S23 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_symbol | PASS |  |
| S24 | - | INVALID_INPUT | `{}` | NOT_APPLICABLE | PASS:spread_gate | PASS |  |
| S25 | - | INVALID_INPUT | `{}` | NOT_APPLICABLE | PASS:rr_not_one_to_one | PASS |  |
| S26 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_process | PASS |  |
| S27 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "PENDING", "NOTION": "PENDING", "TELEGRAM": "PENDING", "TRADINGVIEW": "BLOCKED_SAFETY"}` | PASS | PASS:tv_wrong_layout | PASS |  |
| S28 | setup_xau_20260716_0001 | APPROVE | `{"MT5_DEMO": "DRY_RUN_SUCCEEDED", "NOTION": "DRY_RUN_SUCCEEDED", "TELEGRAM": "DRY_RUN_SUCCEEDED", "TRADINGVIEW": "DRY_RUN_SUCCEEDED"}` | PASS | PASS | PASS |  |
