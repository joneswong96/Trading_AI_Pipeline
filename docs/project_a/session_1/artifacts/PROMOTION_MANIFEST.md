# Session 1 candidate fixture promotion manifest

Source artifact: `candidate_payloads.json`

Generator: `indicators.validation.project_a_sensor_reference.sample_sequence`

Contract: frozen `EVENT_SCHEMA_V0_2`

| Candidate key | Suggested Session 0 golden fixture | Class / type |
|---|---|---|
| `telemetry` | `project_a_telemetry_v0_2.json` | TELEMETRY / SNR_UPDATE |
| `setup_candidate` | `project_a_setup_candidate_v0_2.json` | SETUP_CANDIDATE / SETUP_CANDIDATE |
| `snr_rejection_ready` | `project_a_snr_rejection_ready_v0_2.json` | ANALYSIS_READY / SNR_REJECTION_READY |
| `snr_strong_break_ready` | `project_a_snr_break_ready_v0_2.json` | ANALYSIS_READY / SNR_BREAK_READY |
| `invalidated_lifecycle` | `project_a_setup_invalidated_v0_2.json` | LIFECYCLE / SETUP_INVALIDATED |
| `expired_lifecycle` | `project_a_setup_expired_v0_2.json` | LIFECYCLE / SETUP_EXPIRED |

All six validate without schema modification, and their committed payload hashes
are independently recomputed by `validate_session_1_artifacts.py`. The candidate,
rejection-ready, and invalidation records share
`setup_XAUUSD_1m_20260716T000100Z_S_241975`, demonstrating lifecycle continuity.
The break sample deliberately has `optional_5s_arrow: null`.

The Session 0 owner should review semantics, copy each object into its owned
shared-fixture location, rerun contract and replay tests, and record the promoted
fixture hashes. Session 1 must not perform that copy. The separate
`range_middle_negative_evidence.json` is evidence for a negative test and should
not be promoted as a valid Analysis Ready golden fixture.
