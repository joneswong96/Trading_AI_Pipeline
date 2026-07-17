# Session 1 Wire V1 engineering fixture manifest

Source artifact: `candidate_payloads.json`

Generator: `indicators.validation.project_a_sensor_reference.sample_sequence`

Contract: `PROJECT_A_WIRE_EVENT_V1`

| Key | Class / type | Meaning |
|---|---|---|
| `telemetry` | TELEMETRY / SNR_UPDATE | level-state fact change, no setup |
| `support_setup_candidate` | SETUP_CANDIDATE / SETUP_CANDIDATE | new down expansion toward eligible support |
| `resistance_setup_candidate` | SETUP_CANDIDATE / SETUP_CANDIDATE | new up expansion toward eligible resistance |
| `ambiguous_expansion_telemetry` | TELEMETRY / EXPANSION_UPDATE | simultaneous directions fail closed |

These are synthetic offline engineering fixtures, not captured TradingView
evidence and not Runtime Activation proof. They contain producer-owned Wire V1
fields only. They deliberately contain no trusted receipt time, canonical hash,
HPA authority, actionable geometry, lifecycle, or Analysis Ready event.
