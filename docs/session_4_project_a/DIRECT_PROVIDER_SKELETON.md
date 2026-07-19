# Disabled direct-provider transport skeleton

Status: **implemented but production-disabled**

OpenClaw remains deferred for Project A V1. No direct provider, model,
endpoint, authentication method, credential, API version, or cost ceiling is
approved. The skeleton adds immutable provider-neutral configuration, policy,
request, and technical-result types. Its production factory can construct only
a disabled transport returning `DIRECT_PROVIDER_DISABLED` without invocation.

The transport has no trade-verdict authority. It cannot decide `APPROVE`,
`REJECT`, `MODIFY`, `EXPIRED`, entry, stop loss, take profit, spread, expiry,
geometry, or release. Existing deterministic Python preflight, strict parsing,
schema and identity validation, post-gates, audit persistence, and cached-release
rules remain authoritative.

`config_templates/project_a_reviewer/direct_provider.disabled.yaml` is the only
configuration example. It contains no credential value and keeps provider,
model, endpoint, and credential reference null. Any attempt to enable the
runtime fails before transport construction because no approved runtime-policy
status exists.

The deterministic in-memory fake and its capability are defined only under the
Session 4 test package. Production configuration has no fake selector. No
provider SDK, credential loader, environment-secret reader, network call,
redirect, proxy inheritance, fallback, streaming, tool, browser, exec, file
upload, or external output path is present in the skeleton.

The next gate is a separate provider/model/authentication/runtime-policy
selection and approval. Until that gate is accepted, the direct-provider
runtime must remain disabled and no live smoke test is authorized.
