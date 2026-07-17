# Session 1 fixed offline acceptance

Date: 2026-07-16

Status: `OFFLINE_ACCEPTED_RUNTIME_VISUAL_PENDING`

## Fixed commands

| Command | Result |
|---|---|
| `py -3.11 -m indicators.validation.validate_session_1_artifacts` | 4 Wire V1 fixtures PASS |
| `py -3.11 -m pytest tests/test_project_a_pine_sensor.py -q` | 12 passed |
| `py -3.11 -m pytest tests/test_project_a_pine_sensor.py tests/test_project_a_event_v1.py tests/test_project_a_contracts.py tests/test_project_a_replay.py -q` | 179 passed |
| `py -3.11 -m project_a.replay --all` | `ok=true`; SHADOW; MT5_DEMO; `live_execution=false`; fake outputs; Event V1 writer disabled |
| `py -3.11 -m compileall -q contracts project_a indicators tests` | PASS |
| `py -3.11 -m pip check` | No broken requirements |
| `git diff --check` | PASS |

## Focused proof

The Session 1 regressions prove:

- the original candidate commit/blob is a real immutable exported Git artifact;
- the corrected source strips to the same recorded legacy Session B SHA-256;
- the feature defaults OFF and the reference producer emits nothing while OFF;
- all committed artifacts validate as Wire Event V1;
- Pine owns no trusted receipt or canonical-hash field;
- HPA/HTF momentum arrays are empty;
- an unambiguous new published expansion plus eligible published SNR emits only
  Setup Candidate;
- simultaneous expansion directions fail closed to telemetry;
- no Analysis Ready or lifecycle path exists in the active producer;
- the old Event 0.2 output and all documented unratified authority gates are
  explicitly disabled; and
- duplicate same-bar evidence is suppressed without an arbitrary cooldown.

## Runtime Activation Gate

No live TradingView action was performed. Pine compiler evidence and
before/after visual parity must be obtained later in the approved isolated
profile. Representative support/resistance candidate and ambiguity alerts must
also be captured then. These items block runtime activation, not disabled
offline integration.
