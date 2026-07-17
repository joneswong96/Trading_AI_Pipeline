# Direct provider V1 change request

Status: **Proposed; disabled transport skeleton only**

Depends on: `SESSION_4_RUNTIME_DECISION.md`

Implementation authorization: **not granted by this document**

## Purpose

Add a narrow provider-neutral model transport behind the existing Session 4
deterministic Python boundary. The transport supplies untrusted response text;
it receives no schema, expiry, risk, identity, cache, audit, or release authority.

The first implementation task must remain disabled by default and must not make
a network request. Provider, model, endpoint, authentication, pricing, and live
smoke-test approval are separate decisions.

## Existing interface to preserve

Preserve the existing `ModelClient` behavior:

- immutable `ModelIdentity(provider, name, auth_mode)` attribution;
- `invoke(*, session_key, message, artifact_paths, timeout_seconds) -> str`;
- response is untrusted text and passes through the existing bounded parser;
- failures become existing `TechnicalFailure` codes and never trade verdicts;
- `ReviewService` remains the only orchestrator and release boundary.

No caller may depend on provider-specific response objects, streaming events,
usage objects, HTTP headers, SDK exceptions, or credential formats.

## Proposed provider-neutral transport boundary

Introduce, in a later Session 4-owned correction, a disabled adapter configured
with one immutable transport policy:

- explicit provider identifier;
- exact model identifier, never an alias;
- exact HTTPS origin and API path allowlist;
- exact API/SDK version;
- one authentication mode and one credential reference;
- provider/model fallback list fixed to empty;
- bounded connect/read/overall timeouts;
- bounded request and response sizes;
- redirects disabled;
- ambient proxy inheritance disabled unless an explicit reviewed proxy is the
  allowlisted endpoint;
- TLS verification mandatory;
- no local command, subprocess, plugin, browser, tool, file upload service,
  channel, or agent runtime;
- no response delivery outside the existing Session 4 caller.

The transport must accept only the already-built fixed prompt/request payload
and explicitly staged read-only evidence. It must not discover files, enumerate
directories, follow request-provided paths, or send credential-bearing logs.

## Authentication decision still required

Choose exactly one after provider selection:

1. provider API key stored in an approved OS/user-local secret facility and
   resolved only for the request process; or
2. provider-supported OAuth with an approved refresh/revocation lifecycle and a
   documented non-interactive service posture.

The decision must specify credential owner, billing/account class, storage
location, file/ACL posture, rotation, expiry, revocation, backup exclusion, and
incident recovery. No credential value, refresh token, cookie, or authorization
code may enter Git, audit records, prompts, ordinary logs, exception text, or
test fixtures.

Authentication absence, expiry, rejection, or ambiguity must return
`AUTHENTICATION_UNAVAILABLE`. It must not rotate to another profile, reuse a CLI
login, select another account, or change provider/model.

## Provider and model pinning

- Use one canonical provider id and exact model id.
- Reject aliases and provider-less model names.
- Include provider, model, endpoint-origin hash, API version, adapter version,
  authentication mode, and credential-profile identifier hash in the request
  fingerprint and every audit attempt.
- Startup/preflight must fail if runtime policy differs from the reviewed lock.
- Model removal or incompatibility is `MODEL_UNAVAILABLE`, not fallback.
- A provider changing model semantics under the same identifier is residual
  vendor risk and requires version/release monitoring.

## Network allowlist

The enabled future adapter may contact only the exact approved provider HTTPS
origin and path. DNS resolution, TLS SNI/certificate verification, redirects,
proxy variables, SDK telemetry, update checks, and secondary upload/asset hosts
must be reviewed. Any additional hostname is denied until explicitly added by a
new decision.

The adapter must have no route or integration to localhost browser ports,
TradingView, Telegram, Notion, MT5, broker endpoints, webhooks, or Session 5.
SHADOW and `live_execution=false` remain invariant.

## Audit binding

Before network dispatch, persist or make durable through the existing attempt
flow:

- request/setup/correlation/canonical identities;
- bundle, manifest, artifact, and prompt hashes;
- provider/model/API/adapter identities;
- endpoint-origin hash and authentication mode/profile hash;
- timeout and retry policy;
- attempt/retry relationship and trusted start time.

After a response, preserve only the bounded raw response in the protected
Session 4 audit store, record its hash, run the strict parser and post-gates, and
persist the final attempt hash before release. Provider request ids and usage may
be stored only if non-secret and bounded. Audit failure withholds release.

## Error taxonomy and retry

Map provider/transport failures to the existing stable categories:

- missing/expired/rejected credential -> `AUTHENTICATION_UNAVAILABLE`;
- HTTP/network/SDK timeout -> `MODEL_TIMEOUT`;
- explicit provider quota/rate limit -> `RATE_LIMITED`;
- selected model unavailable/overloaded -> `MODEL_UNAVAILABLE`;
- transport/TLS/protocol/session mismatch -> `SESSION_FAILURE` or a narrowly
  reviewed new technical code;
- malformed/oversized/non-JSON model text -> existing parser technical failures;
- audit persistence failure -> `AUDIT_PERSISTENCE_FAILURE`.

Retries remain explicit, bounded, same-provider, same-model, same-endpoint, and
same-auth-profile. Every retry reruns artifact, freshness, expiry, spread, RR,
environment, and fingerprint gates. No retry extends expiry or changes input.

## Required test plan

### Disabled/offline implementation gate

- adapter cannot be selected without an explicit disabled-by-default feature
  gate and a complete runtime lock;
- no import, constructor, config validation, or health check performs network;
- fake transport verifies exact serialized request and headers with credentials
  redacted;
- wrong endpoint/provider/model/API version/auth mode fails before dispatch;
- fallback, redirect, proxy, secondary host, tool call, and file-discovery
  requests fail before dispatch;
- missing/expired auth metadata, timeout, rate limit, provider unavailable,
  malformed response, oversized response, artifact mismatch, path traversal,
  identity mismatch, expiry, and audit failure remain technical/fail closed;
- parser, post-gate, cache, audit-chain, Event V1, frozen V0.2, replay, complete
  repository, secret, path, import, writer, and status gates stay green.

### Later recorded live gate

Only after provider/auth/runtime-lock approval:

- one recorded, explicitly non-actionable SHADOW fixture;
- exact endpoint/provider/model and no fallback confirmed before dispatch;
- no tools, browser, exec, messaging, output, broker, MT5, or order path;
- strict response parsing, audit-chain verification, expiry and cache behavior;
- no result released to Session 5;
- credential values absent from process output, prompt, logs, and audit metadata.

An expired, rejected, or technical result can pass transport acceptance. No test
may alter trusted time merely to obtain `APPROVE`.

## Rollback

1. Keep the adapter feature gate disabled.
2. Stop review dispatch and retain audit artifacts.
3. Remove the provider credential through its approved local/provider controls
   and revoke it provider-side.
4. Revert only the Session 4-owned adapter/config/test commit.
5. Re-run frozen contracts and replay. No database or Session 5 migration is
   required.

The existing recorded/manual client remains available for offline tests.
OpenClaw remains absent from the approved Project A environment, disabled in
Project A, and preserved only as an optional future adapter candidate.

## Exact next smallest implementation task

On a new isolated Session 4 branch, add only a disabled provider-neutral adapter
interface and configuration validator with a fake in-memory transport. Add tests
proving that the default configuration cannot instantiate or dispatch it and
that wrong provider/model/endpoint/fallback settings fail before transport.
Do not add a provider SDK, credential loader, network call, or live test in that
task.
