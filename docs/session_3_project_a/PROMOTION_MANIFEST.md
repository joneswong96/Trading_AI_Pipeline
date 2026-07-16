# Session 3 promotion manifest for Session 0

## Source authority

- Baseline commit: `d10f6eaf44658caa83dba19009eeef5162cf033c`.
- Shared frozen fixture: `fixtures/project_a/event_cases.json`, SHA-256 `73468e68a2417ac7566457b1b3e4d92e9f34a38dc59b82bb577b423ce1eb8c58`.
- Frozen Event schema SHA-256: `7aa3d862b386ff4db3f23d3af8f9c18ed99e6e70db785a0036eb56ec42534028`.
- Frozen Analysis Request schema SHA-256: `d8323d866282081a1ac0aa642f30ef6cc4429ec302f39065cd04257189541596`.
- Shared files above are unchanged. The candidate clones `accepted_alert.payload` and adds the documented Event extension at `payload.analysis`; IDs and all frozen envelope fields are preserved.

## Candidate bundle

Path: `samples/session_3_project_a/candidate_bundle/attempt_f3f0ce2b4e76389ffe02d8a6b5e82be0`

| File | SHA-256 |
|---|---|
| `source_event.json` | `3d26ad1a4be6c9dea3152826d76d7804993361737a35b88ca39e012438f70772` |
| `manifest.json` | `29b6b530d5210bfc3866ac8e406461b59b7b5f67771c7010c27b9c4bbd5d4b26` |
| `analysis_request.json` | `e8cdb0ba93c7034d488d6987310f4663bab1e123471553168575cf72153c948f` |
| `release.json` | `badee41c5262b9a634368c99e5c3198f1eb45f8a11b0b435dd2bc04e1be6eba5` |

The five 68-byte fake PNGs each hash to `431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460`. They intentionally exercise all required timeframes but are not live TradingView evidence.

Candidate request ID: `req_e35ada7686891f17f11260dcef5682f769dd3698`. It validates against the real frozen Analysis Request 1.0 contract, uses XAUUSD/ICMARKETS, base 1m, five timeframe hash references, spread 8, exact 1:1, SHADOW, MT5_DEMO, `live_execution=false`, and preserves setup/correlation/causation/source-event IDs.

## Promotion checks

```powershell
py -m capture.project_a verify --manifest samples\session_3_project_a\candidate_bundle\attempt_f3f0ce2b4e76389ffe02d8a6b5e82be0\manifest.json
py -m capture.project_a replay --profile samples\session_3_project_a\profile.fixture.json --bundle samples\session_3_project_a\candidate_bundle\attempt_f3f0ce2b4e76389ffe02d8a6b5e82be0
py -m pytest tests\session_3_project_a tests\test_project_a_contracts.py tests\test_project_a_replay.py -q
py -m project_a.replay --all
```

## Session 0 decisions and handoff

1. Ratify `payload.analysis` as the narrow Session 2 -> Session 3 adapter convention, or return an adapter-only revision. No frozen schema change is requested.
2. Confirm an approved dedicated single-chart XAUUSD/ICMARKETS TradingView layout ID and the isolated `ProjectA-XAUUSD-4999` browser profile.
3. Run the documented real-browser smoke test on 4999. Do not treat mocked tests or fake PNGs as live validation.
4. If accepted, merge this branch without copying Session 1/untracked work and optionally promote the candidate into a future Session 0-owned shared fixture pack.
5. Collect 20–30 real Analysis Ready shadow samples before release, including both paths, all sessions, retry, expired and rejection cases.

## Session 4 interface

Session 3 provides an accepted bundle directory containing:

- exact `analysis_request.json` validated against Analysis Request 1.0;
- immutable raw artifacts under `artifacts/`;
- `manifest.json` with source IDs, per-timeframe verification and SHA-256 values;
- `source_event.json` for provenance;
- `release.json`, which must have `release_to_session_4=true` at dispatch time.

Session 4 must reject a missing/failed manifest, failed integrity replay, or `release_to_session_4=false`. It must not recapture, extend expiry, infer another symbol/feed, or use the bundle as order authority.
