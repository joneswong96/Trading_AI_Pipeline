# Adversarial model-output corpus

Tests create each full output by copying `candidates/approve.json` and applying
the exact mutation below; this avoids duplicating a large near-identical object
while keeping the attack reproducible and Session 4-owned.

| Case | Exact raw/mutation | Expected stable code |
|---|---|---|
| Extra prose | `malformed/extra_prose.txt` | `MALFORMED_MODEL_OUTPUT` |
| Markdown fence | `malformed/code_fence.txt` | `MALFORMED_MODEL_OUTPUT` |
| Unknown verdict | replace `verdict` with `HOLD` | `OUTPUT_SCHEMA_FAILURE` |
| Missing field | delete `rationale` | `OUTPUT_SCHEMA_FAILURE` |
| Extra field | add `extra_field: true` | `OUTPUT_SCHEMA_FAILURE` |
| Wrong request ID | replace with `req_wrong_00000001` | `IDENTIFIER_MISMATCH` |
| Wrong setup ID | replace with `setup_wrong_00000001` | `IDENTIFIER_MISMATCH` |
| Invalid evidence | replace reason codes with `EVIDENCE_UNKNOWN` | `EVIDENCE_REFERENCE_MISMATCH` |
| String price | replace `entry` with `"2416.5"` | `OUTPUT_SCHEMA_FAILURE` |
| Invalid RR | replace `tp` with `2419.5` | schema/RR failure; never repaired |
| Spread bypass | mutate request spread to 11 while retaining output | input rejection; model never called |
| Expired APPROVE | advance trusted clock to expiry after invocation | `EXPIRY_FAILURE` |
| Live injection | add `live_execution: true` | `OUTPUT_SCHEMA_FAILURE` |
| Prompt injection | `malformed/prompt_injection.txt` as artifact content | ignored as instruction; deterministic gates unchanged |
| Tool call | `malformed/tool_call.json` | `OUTPUT_SCHEMA_FAILURE` |
| Timeout | `technical_failures.json#timeout` | `MODEL_TIMEOUT`, no verdict |
| OAuth expiry | `technical_failures.json#oauth_expiry` | `AUTHENTICATION_UNAVAILABLE`, no verdict |
| Rate limit | `technical_failures.json#rate_limit` | `RATE_LIMITED`, no verdict |
| Model unavailable | `technical_failures.json#model_unavailable` | `MODEL_UNAVAILABLE`, no verdict |
