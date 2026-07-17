# Session 4 architecture and handoff

## V1 runtime decision

Session 0 has deferred OpenClaw for Project A V1. The exact stable candidate
still performs embedded fallback from `openclaw agent` after selected Gateway
failures/timeouts, so it cannot satisfy the pre-execution Gateway-only release
gate. The existing adapter remains disabled and preserved for future evaluation.
See `SESSION_4_RUNTIME_DECISION.md` and
`DIRECT_PROVIDER_V1_CHANGE_REQUEST.md` for the evidence and bounded next task.

## Outcome and trust boundary

```text
Session 3 dispatch envelope
  -> frozen request validation
  -> freshness/expiry/feed/symbol/TF/spread/environment/RR gates
  -> canonical artifact path/size/hash verification
  -> durable per-request lock + fingerprint
  -> isolated project-a-reviewer session
  -> raw response capture + protected hash
  -> exact-one-object parser
  -> frozen verdict validation
  -> identifier/evidence/expiry/spread/RR/MODIFY gates
  -> hash-chained audit persistence
  -> validated shadow result (or input/technical failure)
```

The Python runtime is the schema, time, risk, identity, idempotency, audit, and
release authority. OpenClaw is a model/session operator only. No module imports a
broker, Session 5, Phase 3 output, Telegram renderer, Notion renderer, or MT5.

## Session 3 input interface

`DispatchEnvelope` accepts:

- `dispatch_id`;
- validated `ANALYSIS_REQUEST_SCHEMA_V1` document;
- canonical `bundle_hash`;
- artifact manifest (`evidence_id`, relative path, SHA-256, byte size, media type);
- canonical artifact-manifest hash;
- trusted artifact root supplied by the runtime, never Telegram/model input;
- non-authoritative attempt metadata.

The bundle hash is SHA-256 of `canonical_json(request) + "\n" + manifest_hash`.
The manifest hash is SHA-256 of its canonical JSON. Manifest paths must be
relative and resolve beneath the trusted root. Evidence IDs must exactly equal
the frozen request's `screenshots_required` set.

Session 3 may call `ReviewService.review(dispatch)` and receives exactly one of:

- `VERDICT` with a frozen-schema-valid shadow verdict and audit record hash;
- `INPUT_REJECTION` with stable code, request ID where available, and no model call;
- `TECHNICAL_FAILURE` with stable code/retryability and no verdict.

There is no coupling to Session 3 database, queue, or filesystem layout.

## Preflight gates

1. Frozen request structural and semantic validator.
2. Trusted-clock future skew, maximum age, and expiry.
3. XAUUSD, ICMARKETS feed, 1m, port/provenance constants.
4. Exactly four required evidence IDs for the recorded request.
5. Canonical path, existence, size, and SHA-256 per artifact.
6. Manifest and bundle hashes.
7. Spread at most 10 normalized points.
8. Exact Decimal 1:1 geometry aligned to `point_size`.
9. `SHADOW`, `MT5_DEMO`, and `live_execution=false`.

Any failure prevents model invocation.

## Prompt package

- Version: `project-a-reviewer-v1.0.0`.
- Source: `project_a_ai_review/prompts/reviewer_v1.md`.
- SHA-256: `72046128ef211cf1dee260462ea82c4c13baad68b50bf94e2536c127b04cd16d`.
  It is calculated over exact UTF-8 prompt bytes and recorded in every attempt.
- Dynamic request message is canonical JSON and clearly separated from the fixed
  system instructions.

The model must emit one of `APPROVE`, `REJECT`, `MODIFY`, or `EXPIRED` only. The
prompt treats bundle/artifact/Telegram/web/OCR content as evidence, denies tools,
and forbids browsing, commands, brokers, orders, gate overrides, invented
evidence, Markdown, fences, prose, and extra fields.

## Strict parsing and post-gates

The parser accepts at most 65,536 UTF-8 bytes, strips outer whitespace only,
requires the entire remaining text to be one JSON object, rejects code fences,
duplicate keys, NaN/Infinity, arrays, prose, and trailing data, then applies
`AI_VERDICT_SCHEMA_V1`.

Post-validation then:

1. matches request/setup/correlation/causation IDs, hypothesis, and path;
2. verifies model/provider/prompt/shadow attribution;
3. copies trusted verdict ID, request identities, and trusted generation time;
4. verifies every `EVIDENCE_*` reason code maps to a manifest evidence ID;
5. rechecks expiry using the trusted clock;
6. rechecks spread, XAUUSD, 1m, SHADOW/MT5_DEMO/no-live environment;
7. recomputes Decimal RR and directional order at point-size precision;
8. requires APPROVE to preserve original geometry and request expiry exactly;
9. requires MODIFY geometry to pass independently and forbids extending expiry;
10. persists audit before returning.

No invalid APPROVE is repaired into MODIFY or REJECT.

## Technical failure model

Stable codes cover schema/input freshness/expiry/artifacts/hashes, OpenClaw/auth/
rate limit/timeout/model/session, malformed/schema-invalid output, identifier/
evidence/RR/spread/expiry/environment/MODIFY scope, duplicate conflict,
concurrency, retry exhaustion, cancellation, config, and audit persistence.

Technical failures are separate objects with `retryable`; they never use a trade
verdict enum and cannot enter the Session 5 output boundary.

## Isolation, idempotency, and retry

- Session key: `agent:project-a-reviewer:review_<sha256(request_id)[:32]>`.
- Dedicated agent, workspace, agent directory, model, and Telegram account.
- OpenClaw sandbox: `all`, `session`, Docker, no network, read-only root, all
  capabilities dropped, browser disabled.
- Filesystem/runtime/web/browser/message/session/plugin tools are denied;
  elevated execution and agent-to-agent messaging are disabled.
- Workspace memory is intentionally empty. No durable request facts are written.
- Durable request directory is a hash of request ID, not a request-chosen path.
- Fingerprint pins bundle, manifest, prompt, adapter, provider/model/auth.
- Same fingerprint returns the immutable completed result without a new call.
- Same request ID with another fingerprint is rejected.
- An exclusive per-request lock serializes processes/threads.
- Technical retries are explicit, limited to two total attempts by default, carry
  `retry_of`, and rerun every preflight gate without extending expiry.

OpenClaw's documented CLI may fall back from Gateway to embedded execution. The
client rejects such result metadata, but the fallback could already have run.
Therefore the live CLI path remains unreleased until a pinned installed version
proves a Gateway-only invocation or an approved direct Gateway adapter replaces
it. Mock/manual paths are not affected.

## Audit design

Runtime default/recommended root: `storage/shadow/project_a_ai_review` (already
gitignored). Per-request storage contains:

- immutable fingerprint metadata;
- append-only `attempts.jsonl` with previous-record hash and record hash;
- protected raw model response per attempt (bounded; normal logs store only hash);
- immutable `completed.json`.

Attempts record all required identities/hashes/versions, provider/model/auth,
session, UTC start/end, pre/post gates, RR, spread/expiry checks, retry relation,
outcome, and shadow status. Audit chain verification is a CLI command. An audit
write/fsync failure withholds the verdict.

This detects ordinary tampering but cannot defeat a local administrator who can
rewrite the complete chain; remote anchoring is a later release improvement.

## Session 5 output interface

Future Session 5 may consume only `ReviewResult.status == "VERDICT"` where:

- the verdict passes the frozen schema and every post-gate;
- `audit_record_hash` is present and its chain verifies;
- trusted clock says the actionable result is not expired;
- request/setup identity matches the source dispatch;
- mode remains SHADOW/MT5_DEMO/no-live.

Session 4 makes no Session 5 call. Session 0 should implement an explicit
consumer adapter after merge rather than importing Session 4 audit internals.

## Manual fallback

`py -m project_a_ai_review.cli review-recorded` routes a manually obtained model
response through the same request/artifact validation, prompt version, strict
parser, frozen schema, deterministic post-gates, idempotency, and audit store.
Provider/model/auth mode are explicit CLI arguments and become fingerprinted
audit attribution. It never silently changes provider/model and remains shadow.

## Rollback

Session 4 adds only new owned paths. Disable the agent/channel, stop invocation,
retain audit evidence, and revert the Session 4 commit on the integration branch.
No database downgrade or frozen fixture migration is required.
