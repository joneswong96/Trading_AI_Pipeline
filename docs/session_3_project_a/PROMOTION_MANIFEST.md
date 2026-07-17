# Session 3 corrected offline promotion manifest

## Source authority

- Original candidate: `b77c5cd9c5e69fb323d4aac370f3ab5c7b25fe1e`.
- Accepted Event V1 baseline: `c0bea3b726a1f83c1c42c8a5c992fb1128b04db9`.
- Frozen Event V0.2 fixture SHA-256:
  `cc751d83d5648c167c663ec2a449ddb1650ae5f7507912303bd66253a7e8d6a4`.
- Frozen Event V0.2 schema SHA-256:
  `2b9f9ec23fbfaecd7bf161a5f29a2aa4f0ab2b4c128223d8fe3122402f1579ca`.
- Frozen Analysis Request schema SHA-256:
  `53eadeda56a155f906eb378153c8e31a900222d12a9f7c439ff8e0879a7f5acf`.

The corrected boundary does not consume Event V0.2. It consumes accepted,
non-duplicate, dispatch-eligible Canonical Event V1 and the exact disabled
`PROJECT_A_SESSION_2_CAPTURE_ADAPTER/1.0` output. The adapter owns only its
versioned `payload.analysis` translation convention; it does not add shared
Event V1 semantics.

## Corrected recorded bundle

Path:
`samples/session_3_project_a/candidate_bundle_v1/attempt_8b59cacf927faad01734a7f50903119d`

| File | SHA-256 |
|---|---|
| `source_canonical_event.json` | `fc2eb1d8f2265ccbc79a411a1c4af1c5e86c0ee9b0978470af6714ca5bc490fe` |
| `source_adapter_output.json` | `848990b73748cde4b9a2d29cb51661730cac538f0b096ec97c41b70a6901ef04` |
| `manifest.json` | `269ae8cc217b9a2a8c982d8df937834f1a7ed524b85e3a60a752bfcf21dac6b9` |
| `analysis_request.json` | `314d05a386d1879872a07d944753adb41e6bb819bd39231d3259a4021e49ddf8` |
| `release.json` | `d843c6f0dd98b01c6ee2dc3667a78a3f5ecab3a1ee666063b56c219608302645` |

The five PNG files are deterministic one-pixel synthetic fixtures. Each hashes
to `431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460`.

Bound lineage:

- request ID: `req_bbbc4181c7673951b0e978742b1d81f18147d5b3`
- setup ID: `setup_10389478bde01fe59035f0ab63e6f273`
- canonical event ID:
  `cevt_a42f53cee3cc581dc0bddbb536fbc3f444f6e1a4693e5e8c559473df33499a69`
- canonical/raw content hash:
  `sha256:a42f53cee3cc581dc0bddbb536fbc3f444f6e1a4693e5e8c559473df33499a69`
- semantic evidence hash:
  `sha256:b9092c1e82e0bda8f83aef2bad0c566a8adc658958410c40403636bd93ed2517`
- receipt ID: `rcpt_session3_sample_0001`
- adapter output hash:
  `sha256:be1e618f4ef52fabec2c92b1b03646e9587396bc8da8f21ff7793dd307608ec6`

The frozen Analysis Request schema accepts only `evt_` causation/source IDs, so
the request uses the deterministic alias `evt_<canonical-hash>`. The manifest
retains the actual `cevt_` identity and every receipt/hash link.

## Offline status

- `evidence_classification=SYNTHETIC_FIXTURE`
- `real_browser_used=false`
- `runtime_compatibility_claim=NONE`
- `release_enabled=false`
- release status: `SYNTHETIC_RETAINED`
- `release_to_session_4=false`
- network/browser/AI use during replay: false

This bundle proves deterministic offline compilation, integrity, lineage,
expiry and replay only. It is not TradingView, Chrome, Playwright, port 4999,
ICMARKETS feed, layout, timeframe switching, visual parity, or real screenshot
evidence.

## Fixed offline checks

```powershell
py -3.11 -m pytest tests/session_3_project_a -q
py -3.11 -m capture.project_a verify --manifest samples/session_3_project_a/candidate_bundle_v1/attempt_8b59cacf927faad01734a7f50903119d/manifest.json
py -3.11 -m capture.project_a replay --profile samples/session_3_project_a/profile.fixture.json --bundle samples/session_3_project_a/candidate_bundle_v1/attempt_8b59cacf927faad01734a7f50903119d
py -3.11 -m pytest tests/test_project_a_event_v1.py tests/test_project_a_contracts.py tests/test_project_a_replay.py -q
py -3.11 -m project_a.replay --all
```

## Runtime Activation Gate

The separately authorized activation campaign must provide:

- approved isolated `127.0.0.1:4999` profile and exact target/layout;
- real XAUUSD/ICMARKETS/1m identity evidence;
- real `5s/1m/5m/15m/30m` capture;
- verified final 1m restoration;
- real artifact integrity and replay;
- representative genuine XAUUSD shadow samples.

Until that campaign, `real_browser_enabled=false`, the probe and driver stop
before external access, and no bundle can be released downstream.
