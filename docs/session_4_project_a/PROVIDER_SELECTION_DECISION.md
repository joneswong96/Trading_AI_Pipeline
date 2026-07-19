# Project A direct-provider selection decision

Status: **APPROVED_FOR_DISABLED_IMPLEMENTATION**

Decision version: `project-a-provider-selection-v1`

Evidence access date: **2026-07-19**

This document records Jones's bounded direct-API policy approval for disabled
implementation only. It does not enable a runtime, create or resolve a
credential, install an SDK, authorize network access or a provider call, or
activate Session 4 or Session 5. The disabled provider-neutral skeleton remains
the only production-constructible transport.

## Executive decision

The selected policy is **OpenAI `gpt-5.4-mini-2026-03-17` through raw HTTPS `POST
https://api.openai.com/v1/responses`**. The approved authentication design is a
restricted, Project A shadow-only OpenAI project service-account API key whose
secret would be held in a Windows Credential Manager Generic Credential and
read directly into the future process only after all local gates pass.

The selection wins because it combines a dated model snapshot, strict JSON
Schema output, five-image support, provider request and usage metadata, a
bounded vision-token formula, low cost, and a mature single REST endpoint. Its
output remains nondeterministic and untrusted. Deterministic Python retains all
preflight, identity, expiry, spread, geometry, RR, audit, cache, and release
authority.

The exact policy lock is in
[`DIRECT_PROVIDER_RUNTIME_LOCK.md`](DIRECT_PROVIDER_RUNTIME_LOCK.md). The
provider, model, endpoint, credential design, data boundary, budget caps, and
other stated values are approved only for a disabled implementation. The exact
OpenAI organization/project scope must be confirmed later; key creation,
credential lookup, network dispatch, and model invocation remain unauthorized.

## Workload and trust boundary

The evaluated workload is XAUUSD, `SHADOW`, low volume, and one response per
review. One request binds one trusted canonical analysis bundle plus exactly
five hash-verified TradingView images in this order:

1. `5s`
2. `1m`
3. `5m`
4. `15m`
5. `30m`

The model may return only an `AI_VERDICT_SCHEMA_V1` candidate with `APPROVE`,
`REJECT`, `MODIFY`, or `EXPIRED`. It receives no tools, browser, execution,
retrieval, URLs, provider discovery, memory, alternate model, or delivery path.
The raw response is technical input; it is never itself a released verdict.

Initial acceptance is 20--30 genuine shadow samples. Reliability, a narrow
failure surface, and bounded cost matter more than minimum latency or maximum
general capability.

## Mandatory eligibility gates

All three shortlisted APIs expose a direct HTTPS API, accept image and text
input, offer schema-constrained JSON, report usage and request identity, publish
authentication/rate-limit/pricing/data/lifecycle documentation, operate without
tools, and are available to Australian API users. The model screen retained two
OpenAI tiers, one Anthropic tier, and two Gemini tiers. No consumer subscription,
browser UI, aggregator, gateway, preview-only model, or `latest` alias is used.

| Mandatory control | OpenAI GPT-5.4 mini | Anthropic Claude Haiku 4.5 | Google Gemini 3.5 Flash |
|---|---|---|---|
| Exact candidate model ID | PASS: `gpt-5.4-mini-2026-03-17` dated snapshot | PASS: `claude-haiku-4-5-20251001` dated snapshot | PASS with limitation: stable `gemini-3.5-flash`, but not a dated snapshot |
| Direct fixed HTTPS API | PASS: Responses API | PASS: Messages API | PASS: Interactions API |
| Five images plus text | PASS | PASS | PASS |
| Strict JSON Schema | PASS: `text.format` with `strict: true` | PASS: `output_config.format` | PASS: `response_json_schema` |
| Tool-free, one response | PASS | PASS | PASS |
| Bounded request/response and usage | PASS | PASS | PASS |
| Stable request identifier | PASS: response ID and `x-request-id` | PASS: response ID and `request-id` | PASS: interaction/response ID |
| Documented auth/rate/errors/pricing | PASS | PASS | PASS |
| Data/training/retention policy | PASS; 30-day abuse-monitoring baseline is explicit | PASS; zero-data-retention options are documented | PASS with limitation: paid-service use and storage are documented, but abuse-retention wording is less numerically precise |
| Lifecycle/deprecation policy | PASS; dated snapshot and GA notice policy | PASS; dated snapshot and retirement date policy | PASS with limitation: stable IDs usually do not change, but are not immutable snapshots |
| Australian access | PASS | PASS | PASS |
| SHADOW with no output delivery | PASS with `store:false` and local-only result | PASS with no external delivery | PASS with `store:false` and local-only result |

No mandatory gate is failed. The Gemini stability and retention qualifications
are material score deductions, not hidden exceptions to Project A controls.

## Candidate comparison

The provider-level table uses the strongest workload-suitable finalist from
each provider. The lower-cost nano/lite models remain eligible and are scored
below; they are not silently excluded.

| Property | OpenAI | Anthropic | Google Gemini |
|---|---|---|---|
| Exact model | `gpt-5.4-mini-2026-03-17` | `claude-haiku-4-5-20251001` | `gemini-3.5-flash` |
| Endpoint candidate | `POST /v1/responses` | `POST /v1/messages` | `POST /v1beta/interactions` |
| API header/version | REST `v1`; no beta header | `anthropic-version: 2023-06-01` | path `v1beta` |
| Context / max output | 400,000 / 128,000 tokens | 200,000 / 64,000 tokens | 1,048,576 / 65,536 tokens |
| Project output lock | 2,048 tokens | 2,048 tokens | 2,048 tokens |
| Provider image capacity | Up to 1,500 images and 512 MB documented; Project lock is 5 and 15 MiB raw | Up to 100 images for Haiku's 200k context; 32 MB request; Project lock would be 5 | Up to 3,600 images; 20 MB inline request; Project lock would be 5 |
| Image formats | PNG, JPEG, WEBP, non-animated GIF | JPEG, PNG, GIF, WEBP | PNG, JPEG, WEBP, HEIC, HEIF |
| Schema control | Strict JSON Schema | Structured outputs | Structured outputs |
| Sampling lock | Reasoning effort `none`; temperature and seed omitted | Temperature can be locked, but no determinism claim | Sampling parameters can be locked, but no determinism claim |
| Tools | Empty/disabled | Omitted | Omitted |
| Request/usage evidence | Response ID, `x-request-id`, usage, rate-limit headers | Message ID, `request-id`, usage, rate-limit headers | Interaction/response ID, usage metadata, model version where returned |
| Auth candidate | Restricted project service-account API key | Workspace API key or Workload Identity Federation | Google Cloud service-account-bound API key |
| Input/output price per 1M tokens | USD 0.75 / 4.50 | USD 1.00 / 5.00 | USD 1.50 / 9.00 |
| Image accounting | 32-pixel patches, capped at 1,536 before model multiplier 1.62 | Documented pixel/token rules and image limits | Documented tiled image-token accounting |
| Model lifecycle | Dated snapshot; GA deprecation policy | Dated snapshot; retirement not sooner than 2026-10-15 at access date | Stable name; no dated snapshot guarantee |
| Provider-side routing | Service infrastructure may route internally; Project A forbids any requested model/endpoint fallback and validates reported model when present | Same Project A rule | Same Project A rule; stable model-name mutability is a residual risk |
| SDK dependence | None; raw REST only | None; raw REST only | None; raw REST only |

Provider maximums are evidence of eligibility, not Project A allowances. The
smaller limits in the runtime lock are authoritative.

### Eligible low-cost tier screen

| Exact model | Eligibility | Official workload positioning / Project A judgment | Standard input/output price per 1M | Typical five-chart estimate | Typical 30-sample estimate |
|---|---|---|---:|---:|---:|
| `gpt-5.4-mini-2026-03-17` | PASS; dated snapshot, images, Responses, strict outputs | Selected: still a compact model, with less dense-chart reasoning risk than a simple-task nano tier | USD 0.75 / 4.50 | USD 0.0198 | USD 0.60 |
| `gpt-5.4-nano-2026-03-17` | PASS; dated snapshot, images, Responses, strict outputs | Not selected: OpenAI documents nano for simple, high-volume classification/extraction/ranking; joint interpretation of five dense charts is not a simple extraction task | USD 0.20 / 1.25 | USD 0.0067 | USD 0.20 |
| `claude-haiku-4-5-20251001` | PASS; dated snapshot, images, Messages, structured outputs | Anthropic's smallest eligible current tier; credible finalist, but near published lifecycle horizon | USD 1.00 / 5.00 | USD 0.0208 | USD 0.62 |
| `gemini-3.5-flash` | PASS with stable-name/data qualifications; images, Interactions, structured outputs | Gemini finalist; more capable than needed in some areas and materially more expensive | USD 1.50 / 9.00 | USD 0.0327 | USD 0.98 |
| `gemini-3.1-flash-lite` | PASS with stable-name/data qualifications; images, Interactions, structured outputs | Not selected: Google documents it for lightweight/straightforward high-volume tasks; Project A volume is low and joint chart reasoning is the larger risk | USD 0.25 / 1.50 | USD 0.0055 | USD 0.17 |

Typical estimates use five 1920x1080 high-detail charts, 8,000 text tokens, and
1,000 output tokens. For OpenAI, images use the documented patch caps and model
multipliers (1.62 mini, 2.46 nano). Anthropic uses 1,560 visual tokens per
1920x1080 standard-tier image. Gemini uses the documented rough six-tile,
258-token-per-tile estimate for each 1920x1080 image. Values are rounded upward
for planning and do not guarantee billing.

The mini recommendation is not based merely on greater general capability. It
is a risk/cost choice for five simultaneous dense charts: the approximately USD
0.40 difference between mini and nano over 30 acceptance samples is immaterial
under the proposed budget, while nano/lite are officially positioned for
simple/lightweight high-volume work. The real 20--30 sample campaign remains
necessary; the decision does not claim an unrun quality benchmark.

Larger flagship/pro models were screened out because no Project A mandatory
capability gap requires their cost or operational surface. They are not
fallbacks and are not included in the runtime lock.

## Weighted scoring

Each category is scored from 0 to 100. A weighted score cannot rescue a failed
mandatory gate.

| Category | Weight | OpenAI mini | OpenAI nano | Anthropic Haiku | Gemini 3.5 Flash | Gemini 3.1 Flash-Lite |
|---|---:|---:|---:|---:|---:|---:|
| Fail-closed transport control | 25% | 95 | 95 | 93 | 85 | 85 |
| Structured-output reliability | 20% | 95 | 95 | 93 | 90 | 90 |
| Image-review suitability | 15% | 90 | 78 | 82 | 92 | 76 |
| Authentication/credential safety | 15% | 85 | 85 | 88 | 82 | 82 |
| Operational simplicity | 10% | 90 | 90 | 88 | 75 | 75 |
| Cost boundability | 10% | 95 | 99 | 88 | 78 | 98 |
| Model lifecycle/stability | 5% | 90 | 90 | 70 | 65 | 70 |
| **Weighted total** | **100%** | **92.0** | **90.6** | **88.5** | **83.9** | **83.8** |

The scores are Project A engineering recommendations, not provider claims.
OpenAI's main advantage is the combined dated snapshot, strict endpoint lock,
explicit vision accounting, and price. Anthropic's authentication options and
control surface are strong, but the evaluated Haiku snapshot has a nearer
published lifecycle horizon. Gemini is image-capable, but its stable rather
than dated model identity, `v1beta` path, and upcoming API-key transition add
avoidable drift and operations risk. Nano and Flash-Lite reduce cost but score
lower on image-review suitability for this low-volume, five-chart task.

## Model controls and nondeterminism

The recommended request sets reasoning effort to `none`, returns one response,
uses strict JSON Schema, and caps output at 2,048 tokens. It omits temperature
and seed rather than relying on unsupported or weak reproducibility controls.
No claim of deterministic model output is made. Reproducibility comes from
immutable input, image, prompt, schema, policy, and model identities plus local
validation and audit hashes.

Schema enforcement constrains shape, not truth, reasoning quality, trade safety,
or provider availability. A valid JSON document can still be wrong or
adversarial and must pass the existing parser and deterministic post-gates.

## Cost analysis

Official GPT-5.4 mini standard pricing at the access date is USD 0.75 per one
million input tokens and USD 4.50 per one million output tokens. Cached-input
discounts are ignored. For high-detail image input, the conservative Project A
calculation rounds each 32-by-32-pixel patch count upward after applying the
model multiplier of 1.62 and never assumes fewer tokens than the documented
formula. A provider-capped image is therefore budgeted at
`ceil(1,536 * 1.62) = 2,489` input tokens.

| Scenario | Input assumption | Output assumption | Estimated cost |
|---|---|---:|---:|
| Minimum planning case | Five 512x512 images: 2,075 image tokens; 4,000 text tokens | 256 | **USD 0.0057** |
| Typical planning case | Five high-detail 1920x1080 charts budgeted at cap: 12,445 image tokens; 8,000 text tokens | 1,000 | **USD 0.0198** |
| Upper bounded attempt | 12,445 image tokens; 32,768 text tokens | 2,048 | **USD 0.0432** |

The 30-sample planning estimates are approximately USD 0.17 minimum, USD 0.60
typical, and USD 1.30 at the bounded upper estimate, before tax and without a
retry. At the typical assumption, monthly estimates are USD 0.60 for 30
reviews, USD 1.98 for 100, and USD 5.95 for 300.

Locked caps for disabled implementation:

- USD 0.05 estimated maximum per provider attempt;
- USD 0.10 reserved maximum per logical review including one eligible retry;
- USD 1.00 per UTC day and USD 10.00 per calendar month;
- exactly five images, at most 3 MiB each and 15 MiB raw total;
- 24 MiB encoded HTTP request, 32,768 text-input tokens, 2,048 output tokens,
  and 65,536 response bytes;
- one automatic retry at most.

Cost reservation and enforcement must be proven before any network dispatch.
Before dispatch, the adapter must reserve the applicable worst-case attempt
cost from every local cap. A retry requires a new reservation. If pricing is
unknown, changed, stale, or the reservation would exceed any cap, fail before
network dispatch. These are estimates, not guaranteed billing; taxes, provider
rounding, and future price changes can differ. A price change invalidates the
lock and requires Jones approval.

## Data governance

OpenAI states that API data is not used to train its models by default unless
the organization opts in. The documented baseline permits abuse-monitoring logs
for up to 30 days. `store:false` prevents Responses application-state retention,
but eligible prompt-cache state can persist for up to 24 hours unless the
account has approved Zero Data Retention or Modified Abuse Monitoring controls.
Those account controls are not assumed or approved here.

No Australian processing or data-residency guarantee is selected. Jones accepts
documented global processing only for the redacted XAUUSD chart screenshots and
canonical Project A SHADOW evidence described here. Enterprise regional
controls, if later considered, may alter price and lock identity.

Charts may reveal financial and personal information. Before hashing or
dispatch, pixels and metadata must be rejected or redacted if they expose:

- broker account number, balance, equity, positions, live-order data, or order
  panel;
- personal notifications, notification content, TradingView/other account
  identity, or alert content;
- Telegram, email, API keys, tokens, cookies, or other secrets;
- browser chrome, other tabs, unrelated watchlists, or unrelated account state.

Only the five required chart regions and the minimum canonical evidence may be
sent. No external image URL, file ID, provider retrieval, or unrelated metadata
is allowed.

Locked local retention for disabled implementation:

- raw redacted images, canonical prompt/provider request content, and raw
  provider response: 30 days from completion;
- non-content audit hashes, identities, usage, cost, gates, and deletion
  tombstones: 365 days;
- incident/legal hold only through an explicit documented exception.

Deletion must first disable dispatch for the affected request, preserve a
hash-only tombstone with deletion time/reason/actor, securely remove the local
content files using the approved audit-store procedure, verify absence, and
retain the hash-chain evidence. There is no provider delete request because the
selected policy uses `store:false`; provider abuse-monitoring deletion follows the
provider/account policy. Raw credentials and authorization headers are never
audit content.

## Authentication and credential lifecycle

The approved authentication design is `Authorization: Bearer <API key>` using a
restricted API key owned by a dedicated OpenAI Project A SHADOW service account.
The exact dedicated OpenAI organization/project scope must be confirmed later.
A personal consumer ChatGPT session, OAuth token, browser
cookie, personal API key, or a key from a live/production trading environment
is not eligible.

The approved credential-reference design is
`WINDOWS_CREDENTIAL_MANAGER_GENERIC`; the symbolic future target is
`ProjectA.Session4.OpenAI.Shadow`. The target name is not a secret and contains
no filesystem path. The repository continues to hold `credential_ref: null`.
Key creation and credential lookup remain unauthorized. No credential is
created, read, or resolved by this decision.

Future lifecycle requirements are:

- Jones confirms the exact OpenAI organization, project, billing boundary,
  service account, and key permissions before any separately authorized key
  creation;
- the key permits only the minimum Responses capability and no administration;
- the process reads it directly from the OS credential store only after config,
  policy-lock, expiry, artifact, identity, cost, and network policy validation;
- the value is held in memory only for the attempt, never placed in Git, YAML,
  command arguments/history, general environment variables, logs, exceptions,
  audit records, prompts, or child processes;
- authorization and key-like values are redacted; crash dumps for the secret-
  bearing process are disabled; memory clearing is best effort;
- development/test and shadow keys/projects are separate; no live-execution or
  production trading credential is present;
- allow at most 90 days between rotations and rotate immediately on suspected exposure by
  approving a replacement fingerprint, atomically changing the OS reference,
  verifying health, then revoking the old key;
- missing, expired, revoked, wrong-project, wrong-organization, or inaccessible
  credentials fail closed as authentication unavailable before dispatch where
  detectable; HTTP 401/403 never triggers fallback or automatic retry;
- no secret backup or export is allowed; disaster recovery creates a new
  restricted key after Jones approval;
- uninstall disables dispatch, removes only the dedicated Generic Credential,
  revokes the provider key, and removes the dedicated service account/project
  only after audit retention requirements are satisfied.

## Rejected alternatives

### Anthropic Claude Haiku 4.5

`claude-haiku-4-5-20251001` is eligible and a credible second-place candidate.
It provides a dated snapshot, vision, structured outputs, direct Messages API,
request/usage metadata, documented key and workload-identity options, and
published data controls. It was not selected because its USD 1.00/5.00 token
price is higher and its published snapshot lifecycle horizon was nearer at the
access date. Project A does not need a second provider, and adding it would
violate the no-fallback lock.

### Google Gemini 3.5 Flash

`gemini-3.5-flash` is eligible and strong for high-volume image input. It was not
selected because the evaluated identifier is stable but not a dated immutable
snapshot, the chosen direct endpoint is under a `v1beta` path, Google documents
an API-key authentication transition affecting standard keys, and the paid
service's abuse-retention description is less numerically bounded than the
selected candidate. Its USD 1.50/9.00 price also has no advantage at Project
A's low volume.

## Limitations and change control

- Model output is nondeterministic, untrusted, and can be semantically wrong
  despite schema validity.
- The API is external: availability, latency, quota, policy, pricing, routing,
  and model lifecycle remain outside Project A control.
- `store:false` is not a zero-data-retention guarantee.
- The credential design, data-processing boundary, budgets, and local retention
  are approved only as disabled-implementation policy; the exact OpenAI
  organization/project and operational enforcement remain unconfirmed.
- No implementation has proved actual request encoding, TLS behavior, request
  IDs, reported-model behavior, usage reconciliation, or errors.
- A dated model does not prevent service retirement.

Any provider, model, origin/path, API version, schema, prompt, image order,
authentication method, credential reference, price, cap, data-control setting,
timeout, retry rule, or reported-model rule change requires: disable; update the
policy document and canonical lock hash; rerun offline tests/security checks;
Jones approval; and a separately authorized redacted SHADOW smoke test. There is
no automatic upgrade and no alias substitution.

## Explicitly deferred implementation

This package does not add an adapter, HTTP/DNS/TLS code, SDK, dependency,
configuration enablement, API key, credential reference, provider project,
account setting, cost alert, network call, model invocation, smoke test, Session
4 activation, Session 5 activation, Telegram, Notion, broker, MT5, webhook, or
order action. This documentation approval authorizes only a separate disabled
implementation with offline evidence; it does not authorize any credential,
network, provider, runtime, or external action.

## Official primary sources

The classification column distinguishes provider contract terms, provider-
documented behavior, and Project A recommendations. All sources were accessed
2026-07-19.

| Provider / scope | Official source | Applies to | Classification |
|---|---|---|---|
| OpenAI model identity, limits, pricing | <https://developers.openai.com/api/docs/models/gpt-5.4-mini> | `gpt-5.4-mini` and `gpt-5.4-mini-2026-03-17` | Documented behavior |
| OpenAI nano identity, limits, pricing | <https://developers.openai.com/api/docs/models/gpt-5.4-nano> | `gpt-5.4-nano-2026-03-17` | Documented behavior |
| OpenAI Responses request | <https://developers.openai.com/api/reference/resources/responses/methods/create> | `POST /v1/responses` | Documented API contract |
| OpenAI strict outputs | <https://developers.openai.com/api/docs/guides/structured-outputs> | Responses JSON Schema | Documented behavior |
| OpenAI vision and image tokens | <https://developers.openai.com/api/docs/guides/images-vision> | GPT-5.4 mini image input | Documented behavior |
| OpenAI data controls/retention | <https://developers.openai.com/api/docs/guides/your-data> | API data, Responses, ZDR/MAM | Documented behavior |
| OpenAI errors | <https://developers.openai.com/api/docs/guides/error-codes> | REST API | Documented behavior |
| OpenAI rate limits | <https://developers.openai.com/api/docs/guides/rate-limits> | Project/rate-limit headers | Documented behavior |
| OpenAI request IDs/compatibility | <https://platform.openai.com/docs/api-reference/backward-compatibility> | `x-request-id`, `X-Client-Request-Id`, API compatibility | Documented API contract |
| OpenAI projects/service accounts | <https://help.openai.com/en/articles/9186755-managing-your-work-in-the-api-platform-with-projects> | Project keys and service accounts | Documented behavior |
| OpenAI restricted-key permissions | <https://help.openai.com/en/articles/8867743-assign-api-key-permissions> | API key scope | Documented behavior |
| OpenAI key safety | <https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety> | Secret handling | Documented recommendation |
| OpenAI deprecation | <https://developers.openai.com/api/docs/deprecations> | GA APIs/models | Documented lifecycle policy |
| OpenAI regional access | <https://developers.openai.com/api/docs/supported-countries> | Australia | Documented behavior |
| Anthropic models/IDs | <https://platform.claude.com/docs/en/about-claude/models/overview> and <https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions> | Claude Haiku 4.5 snapshot | Documented behavior |
| Anthropic Messages API | <https://platform.claude.com/docs/en/api/messages/create> | `POST /v1/messages` | Documented API contract |
| Anthropic structured outputs | <https://platform.claude.com/docs/en/build-with-claude/structured-outputs> | Claude Haiku 4.5 | Documented behavior |
| Anthropic vision | <https://platform.claude.com/docs/en/build-with-claude/vision> | Image formats/limits/accounting | Documented behavior |
| Anthropic auth/API | <https://platform.claude.com/docs/en/api/overview> and <https://platform.claude.com/docs/en/manage-claude/authentication> | API keys and workload identity | Documented API contract |
| Anthropic errors/rates | <https://platform.claude.com/docs/en/api/errors> and <https://platform.claude.com/docs/en/api/rate-limits> | Request IDs, errors, quotas | Documented behavior |
| Anthropic pricing/data | <https://platform.claude.com/docs/en/about-claude/pricing> and <https://platform.claude.com/docs/en/manage-claude/api-and-data-retention> | API pricing and data controls | Documented behavior |
| Anthropic lifecycle/regions | <https://platform.claude.com/docs/en/about-claude/model-deprecations> and <https://platform.claude.com/docs/en/api/supported-regions> | Haiku 4.5, Australia | Documented behavior |
| Gemini model and versioning | <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash> and <https://ai.google.dev/gemini-api/docs/models#model-version-patterns> | `gemini-3.5-flash` | Documented behavior |
| Gemini Flash-Lite model | <https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite> | `gemini-3.1-flash-lite` | Documented behavior |
| Gemini Interactions API | <https://ai.google.dev/gemini-api/docs/interactions-overview> and <https://ai.google.dev/api> | `POST /v1beta/interactions` | Documented API contract |
| Gemini structured outputs | <https://ai.google.dev/gemini-api/docs/structured-output> | JSON Schema response | Documented behavior |
| Gemini images | <https://ai.google.dev/gemini-api/docs/image-understanding> | Formats, count, token accounting | Documented behavior |
| Gemini auth | <https://ai.google.dev/gemini-api/docs/generate-content/api-key> | API keys | Documented API contract |
| Gemini errors/rates | <https://ai.google.dev/gemini-api/docs/troubleshooting> and <https://ai.google.dev/gemini-api/docs/rate-limits> | REST errors and quotas | Documented behavior |
| Gemini response metadata | <https://ai.google.dev/api/generate-content> | Usage, model version, response ID | Documented API contract |
| Gemini pricing/terms | <https://ai.google.dev/gemini-api/docs/pricing> and <https://ai.google.dev/gemini-api/terms> | Paid Gemini API | Contractual and documented behavior |
| Gemini lifecycle/regions | <https://ai.google.dev/gemini-api/docs/deprecations> and <https://ai.google.dev/gemini-api/docs/available-regions> | Model/API lifecycle, Australia | Documented behavior |
| All Project A locks, scores, caps, retention and credential design | This decision and `DIRECT_PROVIDER_RUNTIME_LOCK.md` | Project A V1 | Recommendation; not provider contract |
