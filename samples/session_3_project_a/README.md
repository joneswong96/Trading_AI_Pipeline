# Session 3 recorded synthetic samples

`candidate_bundle_v1/attempt_8b59cacf927faad01734a7f50903119d`
is the corrected offline sample. It starts from a valid Wire Event V1 known
vector, records it through the replay-only trusted receipt processor, and binds
the resulting Canonical Event V1 to
`PROJECT_A_SESSION_2_CAPTURE_ADAPTER/1.0`.

The five one-pixel PNGs are explicitly `SYNTHETIC_FIXTURE`; the manifest says
`real_browser_used=false`, `runtime_compatibility_claim=NONE`, and
`release_enabled=false`. Replay reports `SYNTHETIC_RETAINED` and never releases
the bundle to Session 4.

`candidate_bundle/attempt_f3f0ce2b4e76389ffe02d8a6b5e82be0` is the preserved
original V0.2 candidate sample. It is superseded, synthetic, and retained only
as original-history evidence. It is not an accepted input or runtime proof.

Neither directory is TradingView, Chrome, Playwright, real-port, feed, layout,
or visual compatibility evidence.
