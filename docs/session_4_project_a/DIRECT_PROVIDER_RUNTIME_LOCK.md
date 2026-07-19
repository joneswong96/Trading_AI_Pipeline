# Project A direct-provider runtime policy lock

Policy status: **APPROVED_FOR_DISABLED_IMPLEMENTATION**

Policy version: `project-a-direct-provider-runtime-v1`

Provider policy: `openai-responses-v1`

Model policy: `openai-gpt-5.4-mini-2026-03-17-v1`

Timeout policy: `project-a-direct-provider-timeout-120s-v1`

Request format: `project-a-provider-request-v1`

Provider response format: `project-a-openai-verdict-wire-v1`

Local response contract: `AI_VERDICT_SCHEMA_V1`

Audit identity: `project-a-direct-provider-openai-gpt54mini-v1`

This specification is approved for disabled implementation only; it is not
executable configuration. `credential_ref` remains null and the only production
transport remains disabled. Credential creation or lookup, network access,
provider calls, runtime activation, and Session 5 remain unauthorized. Any
future operational use requires separate implementation and acceptance evidence.

## Immutable selection

| Field | Exact approved policy value |
|---|---|
| Provider | `openai` |
| Model | `gpt-5.4-mini-2026-03-17` |
| HTTPS origin | `https://api.openai.com` |
| Endpoint path | `/v1/responses` |
| HTTP method | `POST` |
| API version | `v1` in path; no beta header |
| Request content type | `application/json` with a UTF-8 body |
| Accepted response | `application/json` only |
| Authentication | `Authorization: Bearer <restricted-project-service-account-api-key>` |
| Credential reference type | `WINDOWS_CREDENTIAL_MANAGER_GENERIC` |
| Credential reference | remains `null`; approved symbolic target design `ProjectA.Session4.OpenAI.Shadow` |
| Fallback models | empty |
| Cost ceiling field | 10 USD cents reserved per logical review, including eligible retry |

The future runtime must reject any provider, model, origin, path, scheme,
method, API version, auth method, credential class, or policy identity that is
not byte-for-byte equal to this approved lock. It may not accept an alias,
provider discovery result, user base URL, environment base URL, query
parameter, embedded credential, wildcard host/path, alternate region,
compatible endpoint, SDK default, or redirect target.

## Endpoint and HTTP policy

Only this request target is eligible:

```text
POST https://api.openai.com/v1/responses
```

Required outbound headers are `Authorization`, `Content-Type`, `Accept`, and a
deterministic `X-Client-Request-Id`. After Jones chooses the dedicated project,
an exact non-secret OpenAI project identifier must also be locked and sent using
the documented project header; an exact organization identifier is locked if
the account requires it. Their values are intentionally unset here. No secret,
account identifier, or authorization value is logged.

The URL must have no user information, explicit port, query, fragment, trailing
path segment, or alternate hostname. Redirect following is disabled for every
status code. HTTP downgrade, origin coalescing to a different hostname,
arbitrary DNS/endpoint discovery, and provider/model fallback are forbidden.
The response content type must be JSON and the complete body must be buffered
within the response limit before parsing. Streaming, background mode, webhooks,
external output, file upload, provider file IDs, and response retrieval by a
later request are disabled.

## DNS, address, TLS, and connection policy

- Hostname allowlist: exactly `api.openai.com`, compared after IDNA processing
  as a lower-case ASCII name with no trailing dot. No subdomain wildcard.
- Resolution: the operating-system resolver only, once per attempt after the
  lock and gates pass. No DNS-over-HTTPS code, hosts-file bypass, hard-coded IP,
  service discovery, or user-provided resolver.
- Address validation: A and AAAA are permitted. Reject the entire resolution if
  it yields no address or any selected candidate is loopback, private, unique
  local, link-local, multicast, unspecified, documentation, or otherwise
  non-public. Resolve again for an eligible retry; do not reuse an address as
  authority across attempts.
- Connection binding: connect to a validated address from that attempt while
  retaining `api.openai.com` for TLS SNI and hostname verification. The HTTP
  layer must not silently resolve a different address after validation.
- Time bound: DNS, TCP connect, and TLS handshake share the 10-second connect
  budget and the 120-second absolute attempt deadline.
- Trust: operating-system public CA store, certificate chain validation, current
  validity, and RFC-compliant hostname verification are mandatory. Minimum TLS
  1.2; TLS 1.3 is allowed. Certificate errors and hostname mismatches fail
  closed.
- Custom trust: no custom CA bundle, private CA, certificate exception,
  insecure flag, trust-on-first-use, or certificate verification bypass.
  Required enterprise TLS interception is a blocker needing a new review.
- Proxy: environment proxy inheritance is disabled. Explicit HTTP/SOCKS/system
  proxies are disabled. Proxy authentication is not supported.
- Redirects: zero redirects, including same-host redirects.
- Reuse: no connection pool or TLS session is shared between logical reviews.
  A connection may serve only its single attempt and is then closed. HTTP/1.1
  or HTTP/2 is acceptable only when the exact origin and certificate rules are
  preserved.
- Logging: record address family and SHA-256 of the packed selected IP, never
  treat it as a trust anchor. Record TLS version, cipher, negotiated HTTP
  version, leaf-certificate SHA-256, issuer organization if exposed, and
  certificate not-before/not-after. Do not log raw DNS packets or full headers.
- Pinning: no certificate or SPKI pin. A CDN certificate/key rotation could
  cause unsafe availability coupling; public-CA plus exact-host validation is
  the practical lock. No fixed provider IP is authoritative.

A hostname allowlist does not by itself solve malicious resolution or
rebinding. The future adapter must prove that the validated attempt address is
the address actually connected while still validating the hostname.

## Request size and image policy

| Limit | Exact approved policy value |
|---|---:|
| Complete UTF-8 HTTP request body | 25,165,824 bytes (24 MiB) |
| Complete HTTP response body | 65,536 bytes |
| Images | exactly 5 |
| Raw bytes per image | 3,145,728 bytes (3 MiB) |
| Raw image bytes total | 15,728,640 bytes (15 MiB) |
| Image dimensions | each side 512--2,048 pixels |
| Image formats | `image/png` or `image/jpeg` only |
| Non-image canonical UTF-8 material | 32,768 bytes maximum |
| Conservative text-token budget | 32,768 input tokens maximum |
| Output | 2,048 tokens and 65,536 UTF-8 bytes maximum |

All limits are checked before credential access. Image bytes must already have
passed the Session 3 manifest, size, media, integrity, XAUUSD/ICMARKETS,
timeframe, freshness, restoration, and redaction checks. Decode each image,
reject decompression bombs or trailing/concatenated content, and ensure decoded
format and dimensions match the manifest before re-encoding a canonical data
URL. External URLs, provider file references, SVG, PDF, animated images,
metadata-only images, and additional attachments are forbidden.

The image order is immutable: `5s`, `1m`, `5m`, `15m`, `30m`. Each position is
bound to its timeframe, media type, raw byte length, and SHA-256 in the
provider-neutral request. A missing, duplicate, reordered, changed, or extra
image fails before credential access.

The 32,768-byte text limit is budgeted pessimistically as up to one input token
per byte for cost reservation. The future encoder must also apply the current
official image-patch formula and reserve the greater of calculated or
conservative image tokens. Unknown tokenization or pricing fails closed.

## Exact provider request mapping

The raw HTTPS JSON object has these locked semantics:

```json
{
  "model": "gpt-5.4-mini-2026-03-17",
  "instructions": "<exact reviewed reviewer prompt bytes>",
  "input": [{
    "role": "user",
    "content": [
      {"type": "input_text", "text": "<canonical project-a-provider-request-v1 JSON>"},
      {"type": "input_image", "image_url": "data:image/png;base64,<5s>", "detail": "high"},
      {"type": "input_image", "image_url": "data:image/png;base64,<1m>", "detail": "high"},
      {"type": "input_image", "image_url": "data:image/png;base64,<5m>", "detail": "high"},
      {"type": "input_image", "image_url": "data:image/png;base64,<15m>", "detail": "high"},
      {"type": "input_image", "image_url": "data:image/png;base64,<30m>", "detail": "high"}
    ]
  }],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "project_a_openai_verdict_wire_v1",
      "strict": true,
      "schema": "<reviewed provider-supported strict schema>"
    }
  },
  "reasoning": {"effort": "none"},
  "max_output_tokens": 2048,
  "tools": [],
  "tool_choice": "none",
  "store": false,
  "stream": false,
  "background": false,
  "truncation": "disabled"
}
```

The exact serialized schema, prompt bytes, and parameter support must be proven
against the official Responses API contract during implementation review. If an
empty `tools`, `tool_choice`, `background`, or other explicit denial field is
not accepted by the locked API/model, the implementation must stop for a policy
revision; it may not silently omit a security-significant lock.

`project-a-openai-verdict-wire-v1` is a provider-compatible, strict-shape schema:
root object; every output property required; `additionalProperties:false` at
every object; four-value verdict enum; nullable numeric trade fields; bounded
arrays/strings where supported; and no free-form wrapper or prose. It is not a
replacement for `AI_VERDICT_SCHEMA_V1`. The complete returned JSON is parsed,
then validated against the frozen local `AI_VERDICT_SCHEMA_V1` and all semantic
post-gates. Unsupported provider-schema keywords may be omitted only from the
wire schema and remain mandatory locally. Any inability to express the required
shape with the provider's supported strict subset blocks implementation.

Temperature, top-p, seed, previous-response ID, conversation ID, service tier,
prompt cache key, safety override, parallel tool calls, and tool declarations
are omitted. Provider defaults therefore remain a source of nondeterminism; no
seed or temperature determinism is claimed. The candidate count is one by the
Responses API shape.

The canonical input-text object must bind, without secret or local path:

- `request_id`, `setup_id`, `canonical_event_id`, canonical-content hash,
  analysis-request hash, and source event IDs;
- exact request expiry and the trusted clock reading used by preflight;
- prompt version and SHA-256;
- policy version, audit identity, provider/model/timeout/request/response
  identities, and canonical policy-lock SHA-256;
- the canonical analysis bundle and deterministic gate summary;
- the ordered five-item image manifest with timeframe, content SHA-256, byte
  length, dimensions, and media type;
- the local output contract identity and expected trusted response identity.

`X-Client-Request-Id` is UUIDv5 using the standard DNS namespace UUID
`6ba7b810-9dad-11d1-80b4-00c04fd430c8` and the UTF-8 name
`<audit_identity>:<policy_lock_hash>:<request_id>:<attempt_ordinal>`, where the
ordinal is `1` or `2`. The derivation is an audit/tracing identity, not a claim
of server-side idempotency.

## Response lock and release boundary

A successful transport result requires all of the following before returning
raw technical output to the existing parser:

- final HTTP status 200 and JSON content type;
- body no larger than 65,536 bytes and exactly one complete JSON response;
- OpenAI response ID and `x-request-id` present and structurally valid;
- requested and reported model exactly `gpt-5.4-mini-2026-03-17` where the model
  field is supplied;
- complete input, output, total, and any reasoning/cached usage metadata;
- exactly one completed schema-constrained output, with no refusal,
  incomplete/truncated status, tool call, extra output item, external reference,
  or prose;
- extracted JSON no larger than 65,536 bytes;
- strict wire-schema validation followed by frozen local
  `AI_VERDICT_SCHEMA_V1` parsing and all deterministic post-gates.

Missing usage, missing provider request ID, model mismatch, refusal, incomplete
output, extra output, malformed JSON, schema-invalid JSON, or post-gate failure
is a technical failure. No candidate verdict is released. The provider's
response ID is never used to retrieve or continue a response.

Audit the provider, exact requested/reported model, origin/path, API version,
HTTP status, attempt ordinal, start/end/latency, provider response ID,
`x-request-id`, deterministic client request ID, rate-limit headers in bounded
numeric form, input/output/reasoning/cached/total usage, estimated and reported
cost, response byte count, raw response SHA-256, extracted JSON SHA-256,
policy-lock SHA-256, prompt SHA-256, ordered image hashes, TLS/address metadata,
technical outcome, parser/post-gate outcome, cap reservation/reconciliation, and
release-withheld/allowed state. Never audit authorization, key values, complete
headers, data URLs, raw credentials, OS credential material, or local paths.

The canonical policy-lock SHA-256 is computed over an implementation-owned,
canonical serialization of every approved lock field. Any field change produces
a new identity and invalidates cached results; this Markdown file alone is not
the runtime hash source.

## Timeout policy

- Connect phase (DNS + TCP + TLS): 10 seconds total.
- Read inactivity/response phase: at most 110 seconds.
- Absolute provider attempt deadline: 120 seconds from resolution start,
  overriding all phase timers.
- Retry delay: official `Retry-After` when valid and 0--30 seconds; otherwise
  bounded exponential delay with jitter, capped at 30 seconds.
- Attempts: one initial attempt plus at most one eligible automatic retry.
- Absolute logical-review network window: 270 seconds including maximum retry
  delay; existing request expiry can make it shorter and is never extended.

Before the initial attempt and retry, re-run trusted time/expiry, request
identity, artifact hash, image redaction, spread, RR, environment, credential,
network-policy, and cost-cap gates. If the request cannot remain valid through
the attempt deadline, do not dispatch.

## Rate-limit and concurrency policy

Provider quotas depend on the approved OpenAI project and usage tier and are not
hard-coded as an entitlement. Project A adds stricter local limits: one
provider attempt in flight, no more than six attempts in any rolling 60-second
window, and no more than 20 attempts in one UTC day, in addition to the cost
caps. Queued requests keep their original expiry; waiting never extends it.

Record documented rate-limit limit/remaining/reset headers when present after
strict numeric/length validation. They may reduce dispatch but never increase a
local limit. A missing rate-limit header is recorded as unavailable; it is not
an alternate quota source. HTTP 429 may receive the one bounded eligible retry
under the table below. Project A never changes project, account, model, service
tier, endpoint, or key to escape a rate limit, and never automatically requests
a quota increase.

## Error, retry, and ambiguity policy

There is one provider, one model, one endpoint, and no fallback. Automatic retry
is permitted at most once and only with identical canonical input, prompt,
schema, model, and policy hashes, a new attempt ordinal/client request ID, a
`retry_of` link, revalidated gates, and a newly reserved cost allowance.

| Outcome | Automatic retry | Locked handling |
|---|---|---|
| DNS resolution failure | Once only if classified temporary and zero request bytes sent | Technical failure if retry fails; never change resolver/host |
| TLS failure | No | Security/configuration technical failure; no bypass or alternate route |
| Connect refusal/timeout | Once only if zero request bytes sent | Same address policy, fresh DNS resolution |
| Read timeout | No | Ambiguous provider processing; withhold release and reconcile manually |
| HTTP 400 | No | Request/policy technical failure |
| HTTP 401/403 | No | Authentication/account/scope technical failure; disable until resolved |
| HTTP 408 | Once after a complete explicit error response | New audited attempt and cost reservation |
| HTTP 409 | No | Unexpected state conflict; manual reconciliation |
| HTTP 413 | No | Local size-policy defect; no larger request |
| HTTP 429 | Once, honoring bounded `Retry-After` | No quota/project/model change |
| HTTP 500/502/503/504 | Once after a complete explicit error response | Same endpoint/model only |
| Other HTTP 4xx/5xx | No | Technical failure and policy review |
| Malformed or oversized JSON | No | Technical failure; raw hash retained |
| Wire/local schema-invalid JSON | No | Technical failure; no repair prompt |
| Provider request/response ID missing | No | Unreconcilable technical failure |
| Usage metadata missing/inconsistent | No | Cost-unreconcilable technical failure |
| Connection lost after any request-body byte | No | Ambiguous processing/cost; manual reconciliation |
| Connection lost after provider may have completed | No | Ambiguous success; no second model call |
| Refusal/incomplete/truncated/tool output/model mismatch | No | Technical failure; no fallback or continuation |

Only pre-send failures and complete, explicit eligible error responses can be
retried. A connection loss or timeout after request transmission is never
treated as proof that the provider did not process or bill the request. Project
A does not assume the Responses API supplies server-side idempotency.
`X-Client-Request-Id` is trace evidence only; no `Idempotency-Key` header is sent
without an official, separately reviewed provider contract.

No provider error becomes `REJECT`, `EXPIRED`, or any other trade verdict. A
successful but unauditable response is also a technical failure.

## Authentication and credential lock

Approved design: a dedicated OpenAI Project A SHADOW service-account API key,
restricted to the minimum Responses permission, stored under the Windows
Credential Manager Generic Credential target `ProjectA.Session4.OpenAI.Shadow`.
The exact organization/project/billing boundary and service-account scope must
be confirmed later. Key creation and credential lookup remain unauthorized.

Approved disabled-implementation storage and injection policy:

1. Keep `credential_ref` null and runtime disabled; no implementation may load a
   credential under this approval.
2. Store only the future secret in a user-scoped Windows Credential Manager
   Generic Credential named `ProjectA.Session4.OpenAI.Shadow`.
3. Store the approved target reference and expected organization/project
   identity hashes in protected non-secret runtime configuration, never the key.
4. Resolve directly through an in-process OS API only after all non-secret
   policy, input, expiry, cost, DNS/TLS configuration, and artifact gates pass.
5. Construct the authorization header in memory immediately before dispatch;
   do not export a broad environment variable, launch a helper, or expose it to
   model content.
6. Redact `Authorization`, bearer/key patterns, credential errors, and headers
   before logs/audit. Disable crash dumps for the secret-bearing process and
   prevent child-process inheritance. Clear temporary buffers best effort.
7. Destroy the in-memory reference after the attempt.

Missing/inaccessible credentials fail before DNS. Known expired/revoked keys,
wrong-account or wrong approved organization/project metadata, or changed
credential fingerprints fail before dispatch. HTTP 401/403, unexpected
organization/project response
metadata, or billing-scope mismatch disable further dispatch and require Jones
reconciliation; they are not retryable.

Use separate projects and keys for developer/test and approved shadow service;
synthetic tests use no provider credential. No live-execution, broker, MT5,
Session 5, personal consumer, or production-trading credential may be visible to
this process.

Allow at most 90 days between rotations and rotate immediately after suspected exposure: disable
dispatch, Jones approves a replacement, create it in the same dedicated project,
record only its fingerprint/metadata, update the OS target atomically, run a
separately approved health gate, revoke the old key, and verify revocation. Do
not back up or export the secret. Recovery creates a new key. Removal disables
dispatch, removes only the dedicated Generic Credential, revokes the provider
key, and deletes the service account/project only after retained audits are safe.

## Cost lock

Pricing evidence and calculations are in
[`PROVIDER_SELECTION_DECISION.md`](PROVIDER_SELECTION_DECISION.md). The locked
budget policy for disabled implementation is:

| Cap | Locked value |
|---|---:|
| Provider attempt estimated cost | USD 0.05 |
| Logical review reservation including possible retry | USD 0.10 |
| UTC daily | USD 1.00 |
| Calendar month | USD 10.00 |
| Automatic retries | 1 |
| Images / raw bytes | exactly 5 / at most 15 MiB total |
| Text budget | at most 32,768 UTF-8 bytes, reserved as 32,768 tokens |
| Output | at most 2,048 tokens and 65,536 bytes |

At the evidence date, calculations use USD 0.75 per million input tokens, USD
4.50 per million output tokens, and up to 2,489 input tokens for each image
after the documented high-detail patch multiplier. Cached-input savings are
never assumed. Provider-reported usage is reconciled against the reservation
after every response, including technical failures when usage is available.

Pricing configuration has an approval timestamp and expires after 30 days even
if no change is known. Unknown, stale, increased, non-USD, or unbounded pricing,
an unreserved retry, or a cap exceedance fails before dispatch. A provider-side
budget is defense in depth and must not replace local caps. The runtime never
raises a cap, changes service tier, or switches model automatically.

Cost reservation and enforcement must be proven before any network dispatch.

## Data-governance lock

- Send only the canonical XAUUSD evidence and five redacted chart images.
- Reject broker account number, balance/equity, personal notification or other
  notification content, account identity, alert content, Telegram/email,
  credential, cookie, browser tab, unrelated watchlist, live-order data, order
  panel, and unrelated account-state exposure.
- Strip nonessential image metadata and canonicalize image bytes before hashing.
- `store:false`; no prior response, conversation, provider file, URL, background
  job, or external delivery.
- API data training opt-in must remain disabled for the dedicated organization.
- The baseline accepts documented provider abuse-monitoring retention up to 30
  days and possible eligible prompt-cache retention up to 24 hours. It does not
  claim Zero Data Retention.
- Jones accepts global processing and no Australian residency only for redacted
  XAUUSD chart screenshots and canonical Project A SHADOW evidence within this
  exclusion boundary. A regional-processing change requires a new policy lock
  and cost review.
- Locked local content retention: 30 days for raw redacted images, canonical
  prompt/provider request content, and raw provider response; 365 days for
  non-content audit identities, hashes, usage/cost, gate results, and deletion
  tombstone. Explicit incident/legal hold is the only extension.
- Raw provider responses may be stored only in the existing protected,
  request-scoped audit store, within 65,536 bytes, with access limited to the
  shadow reviewer/auditor. Never store raw response in Git or external output.
- Deletion disables the affected request, records a hash-only actor/time/reason
  tombstone, removes local content using the approved audit-store procedure,
  verifies absence, and retains the audit chain. `store:false` means there is no
  Responses object to delete; provider-controlled abuse logs follow account
  policy.

Zero Data Retention or Modified Abuse Monitoring may later reduce provider
retention, but neither is assumed. Enabling either is an account-level change
requiring Jones evidence and a policy revision.

## Upgrade, deprecation, and drift process

There is no automatic model/API upgrade. A changed or retired snapshot,
provider alias substitution, response-reported model mismatch, price change,
new endpoint/version, schema support change, auth transition, data-policy
change, TLS requirement, or rate-limit behavior disables dispatch.

Before any replacement:

1. keep the current runtime disabled;
2. research current official primary sources and record access date;
3. choose one exact stable snapshot and endpoint, never `latest`;
4. update every affected lock field and canonical policy hash;
5. review strict-schema compatibility and cost/data/auth implications;
6. rerun all offline skeleton, Session 4, contracts, replay, scope, secret,
   path, import, writer, and policy tests;
7. obtain Jones approval;
8. run a separately authorized redacted XAUUSD SHADOW smoke/negative gate;
9. promote only after audit and rollback evidence passes.

Official deprecation notice is an immediate planning trigger, not permission to
substitute a model. If no replacement is approved before retirement, remain
disabled and return a technical model-unavailable failure.

## Rollback and disablement

Rollback never invokes another model or provider. On policy, credential,
network, usage, cost, retention, audit, schema, model, or security failure:

1. set/retain `enabled:false` through the existing reviewed configuration path;
2. stop new dispatch and allow no queued request to extend its expiry;
3. preserve the request/audit chain and record release withheld;
4. remove the approved credential reference from runtime configuration;
5. revoke the dedicated provider key if compromise/account risk exists;
6. restore the disabled skeleton configuration with all selection fields null;
7. verify the production factory constructs only `DisabledReviewTransport` and
   returns `DIRECT_PROVIDER_DISABLED` without DNS/network access;
8. retain/decommission local evidence under the data-governance procedure.

Completed validated shadow audit results remain immutable, but rollback never
releases them to Session 5. No broker, MT5, webhook, Telegram, Notion, alert, or
order path is part of rollback.

## Disabled-implementation boundary and remaining blockers

Jones has approved the following policy only for disabled implementation:

- OpenAI, exact `gpt-5.4-mini-2026-03-17`, origin/path, and all lock identities;
- dedicated Project A SHADOW service-account/restricted-key design and the
  Windows Credential Manager Generic Credential target design;
- global data processing, training opt-out evidence, provider retention, local
  30/365-day retention, and screenshot redaction boundary;
- per-attempt/logical/daily/monthly budgets and pricing-expiry rule;
- DNS/address/TLS/proxy/connection logging policy;
- request/wire-schema mapping, parameter support, timeouts, retry matrix, and
  exact audit fields;

The exact organization/project/billing scope still requires later confirmation.
A later implementation branch must prove the locked policies offline. Any
no-delivery SHADOW smoke test requires separate authorization.

Until then: no SDK, dependency, credential, API call, model invocation, account
change, network change, runtime activation, or Session 5 action is authorized.
