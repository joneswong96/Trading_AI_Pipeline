# Session 4 runtime architecture decision

Status: **OpenClaw deferred for Project A V1**

Decision date: 2026-07-17

Integration baseline: `887065c15c4f19afc466ca771098dde299ca96c7`

Decision owner: Project A Session 0

## Decision

Project A V1 will not install or activate OpenClaw. The exact result of the
mandatory transport question is:

`PRE_EXECUTION_GATEWAY_ENFORCEMENT_NOT_AVAILABLE`

The stable OpenClaw candidate has an identifiable official release, signed
source tag, immutable npm package, supported Node ranges, Windows support,
loopback Gateway, Docker sandbox, tool policy, and inspection commands.
However, its documented and implemented `openclaw agent` command falls back to
embedded execution after selected Gateway failures and timeouts. There is no
documented `--gateway-only` or equivalent fail-closed flag in the exact release.
The fallback model may execute before the caller receives fallback metadata.
That violates Project A's pre-execution boundary and is a release blocker.

Project A V1 should instead add a narrow, disabled-by-default, provider-neutral
transport behind the existing deterministic Python preflight, parser,
post-validation, expiry, cache, and audit boundary. Provider and authentication
selection remain separate decisions. The existing OpenClaw adapter stays in the
repository but remains disabled and unreleased for possible future evaluation.

## Problem and decision criteria

Session 4 needs one non-authoritative model response for a recorded SHADOW
review. It does not need channels, tools, browser control, shell execution,
memory, multi-agent orchestration, or external output delivery. The runtime must
fail before provider dispatch if transport, provider, model, prompt, workspace,
or tool policy differs from the approved identity.

OpenClaw could be approved only if one exact build provided enforceable
Gateway-only dispatch, no embedded/provider fallback, measurable effective
permissions, acceptable Windows deployment, and a material operational benefit
over a direct provider request. Candidate `v2026.7.1` fails the first two
requirements and does not provide a required V1 feature that offsets the added
runtime and credential boundaries.

## Official candidate identity

| Field | Evidence for the exact candidate |
| --- | --- |
| Project/vendor | OpenClaw, an OpenClaw Foundation project |
| Official documentation | <https://docs.openclaw.ai/> |
| Official source | <https://github.com/openclaw/openclaw> |
| Stable candidate examined | `v2026.7.1`, released 2026-07-13; npm publication `2026-07-13T17:58:18Z` |
| Signed source identity | annotated tag object `842a951d5d0843aa6eb77575dc9867bf0603835c`, commit `2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4`; GitHub reports verified SSH signature fingerprint `MS6JWpdE8rcWraHlnuxuwDIkCUZtPKIf1QNa5ZJf3FY` |
| Package coordinate | `openclaw@2026.7.1` |
| Package artifact | `https://registry.npmjs.org/openclaw/-/openclaw-2026.7.1.tgz` |
| Package integrity | npm SRI `sha512-ge/Xss99CHAjPL/ikmH/UFoiOrjcxDB4sW3y9mhyCD+dYW3wzV7TKbAVdkrXFgAG2d2BjpJofP97zUZ+umxo8g==` |
| Registry provenance | npm signature key id `SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U`; npm SLSA provenance endpoint `https://registry.npmjs.org/-/npm/v1/attestations/openclaw@2026.7.1`; publisher metadata is GitHub Actions |
| Node engine | `>=22.22.3 <23 || >=24.15.0 <25 || >=25.9.0`; Node 24 is the documented default target |
| Local environment | Node `v20.18.1` is incompatible; Docker `28.4.0` and WSL2/Ubuntu exist, but no runtime was installed or changed |
| Windows support | Native Windows CLI/Gateway and Windows Hub are documented; WSL2 is the documented most Linux-compatible Gateway runtime |
| State/config | default state `~/.openclaw`; config `~/.openclaw/openclaw.json`; per-agent model auth/runtime state under `agents/<agentId>/agent/openclaw-agent.sqlite` |
| Installation | official docs offer hosted installers, global package managers, source, and local-prefix paths. Project A did not approve or run any installer. The current npm prefix is system-wide, so the default global npm path is not a demonstrated user-local installation here. |
| Uninstall | `openclaw uninstall` / `openclaw gateway uninstall`, then package-manager removal; Windows managed startup may add a Scheduled Task and state-dir scripts |

The registry SRI and provenance are useful artifact evidence, and the signed tag
is useful source evidence. They do not repair a runtime contract that is unsafe
for this use case. No `OPENCLAW_RUNTIME_LOCK.md` is created because the candidate
is not approved.

## Pre-execution Gateway-only result

The exact release documentation states that `openclaw agent` runs a turn through
the Gateway and falls back to the embedded agent when the Gateway request fails.
Its JSON result reports `meta.transport: "embedded"` and
`meta.fallbackFrom: "gateway"` after fallback. The exact tagged implementation
also executes embedded fallback for Gateway timeout and classified Gateway
errors. The registered command offers `--local` to force embedded execution but
does not offer a flag that forbids embedded fallback.

Primary version-specific evidence:

- tagged CLI documentation:
  <https://github.com/openclaw/openclaw/blob/v2026.7.1/docs/cli/agent.md>;
- tagged command implementation, especially lines 940-1003:
  <https://github.com/openclaw/openclaw/blob/v2026.7.1/src/commands/agent-via-gateway.ts#L940-L1003>;
- official Gateway protocol documentation:
  <https://docs.openclaw.ai/gateway/protocol>.

The lower-level Gateway protocol performs a challenge/authenticated handshake,
negotiates protocol version/scopes/capabilities, and fails protocol clients when
the Gateway is unavailable. A new direct WebSocket adapter might avoid the CLI
fallback, but that is a different adapter requiring implementation, protocol
pinning, identity checks, and real acceptance evidence. It is not evidence that
the currently integrated CLI adapter is safe.

| Required invariant | Candidate result |
| --- | --- |
| Gateway transport only before provider dispatch | **FAIL**: `openclaw agent` contains embedded fallback paths |
| No embedded/local fallback | **FAIL**: no fail-closed CLI flag; fallback is implemented |
| No provider/model fallback | Configurable explicit model and empty model fallback list, but OpenClaw also has auth-profile rotation and multiple fallback surfaces. Not accepted without exact effective evidence. |
| Exact provider/model | Explicit `provider/model` is supported; current Project A model is intentionally undecided |
| Exact workspace/agent | Configurable, but the CLI result/handshake does not attest Project A's workspace and prompt hashes before dispatch |
| Exact prompt identity | Project A hashes its prompt; no official Gateway handshake field binds that hash to the imminent run |
| Tools/browser/exec/filesystem | Deny policy exists, but must be proved from effective runtime state; no runtime exists here |
| Loopback Gateway | `gateway.bind: "loopback"` is supported and resolves locally |
| Caller-verifiable identity | Gateway auth, protocol/server version and optional TLS fingerprint exist; the integrated CLI invocation does not pin a Gateway certificate or independent Project A Gateway identity |

Result: `PRE_EXECUTION_GATEWAY_ENFORCEMENT_NOT_AVAILABLE`.

## Sandbox and Windows feasibility

OpenClaw's Docker backend is substantive rather than merely a template. For
`v2026.7.1`, documented defaults include `network: "none"`, read-only root, and
all Linux capabilities dropped. Workspace access can be `none`, `ro`, or `rw`;
tool denial is a separate pre-tool-call layer; `openclaw sandbox explain --json`
reports effective sandbox, workspace, mounts, and tool policy.

Limitations for Project A:

- the Gateway and model/provider client remain on the host; the sandbox mainly
  contains tool execution;
- official documentation calls the sandbox an imperfect boundary;
- the policy plugin emits evidence and attestation hashes but explicitly does
  not enforce tool calls or rewrite runtime behavior at request time;
- native Windows CLI/Gateway is supported, but the documented Docker sandbox is
  Linux-container oriented and WSL2 is the recommended Linux-compatible route;
- a containerized Gateway needs Docker socket access to orchestrate sibling
  sandboxes, which is an additional host-control boundary;
- loopback inside a Docker container is not reachable through ordinary bridge
  port publishing; changing the Gateway to `0.0.0.0`/LAN to make that work would
  violate Project A's exposure rule unless a separately reviewed host-network
  design were used;
- OAuth/API credentials stay in the host-side state/auth store, outside the
  tool sandbox. That is appropriate for provider access but means the sandbox
  does not isolate the Gateway credential boundary itself.

Jones's machine has Docker and WSL2, so a Linux-compatible deployment is
possible. It would require at least Node/runtime maintenance, a Gateway process
or user service, Docker/WSL lifecycle, state/credential backup and rotation,
configuration drift monitoring, security/policy audits, sandbox image
maintenance, logs/audit retention, and health/restart monitoring. This is
disproportionate for a no-tool single-call V1 reviewer.

## Authentication, fallback, and audit

OpenClaw supports provider API keys, OAuth, token flows, and provider plugins.
OpenAI auth can use ChatGPT/Codex OAuth or an API key. Credentials are kept in
per-agent state; official model status commands can report non-secret health.
OpenClaw also supports auth-profile rotation and model fallback. Those are
availability features, but Project A requires one exact provider/model/auth path
and technical failure instead of substitution.

The Gateway protocol provides a metadata-only audit ledger for agent and tool
lifecycles. It is useful operational telemetry, but it excludes prompts,
messages, tool arguments/results, and raw errors, expires records after 30 days,
and does not replace Project A's immutable request fingerprint, raw-response
hash, completed verdict record, or hash-chained release audit. OpenClaw would add
an audit surface rather than replace an existing required one.

The official repository publishes many security advisories, including high
severity advisories dated 2026-06-30. This decision does not claim that
`v2026.7.1` is affected by those already-fixed issues; it records that every
future runtime lock would require an advisory-by-advisory applicability review.

## Direct-provider comparison

The proposed alternative is transport-only. It does not move any schema, risk,
expiry, identity, parser, cache, or release authority out of Python.

| Dimension | OpenClaw `v2026.7.1` | Narrow direct-provider transport |
| --- | --- | --- |
| Authentication | OAuth/API key plus OpenClaw profile lifecycle and rotation | One approved provider credential, stored outside Git; exact method remains a decision |
| Provider/model pinning | Rich routing, profile rotation and fallback machinery | One exact endpoint/provider/model; no candidate chain |
| Pre-execution enforcement | Integrated CLI can fall back to embedded | Caller constructs one allowlisted HTTPS request or fails before sending |
| Network | Gateway/provider/plugin/update/channel surfaces require governance | One allowlisted provider origin; no redirects or proxy substitution |
| Tools/browser/exec | Must be configured, denied, inspected, and regression-tested | No tool protocol or execution capability exists in the adapter |
| Sandbox value | Useful when tools execute; Gateway/provider client remain host-side | Limited benefit because the transport performs no tools or local execution |
| Audit | Additional metadata ledger plus Project A audit | Project A audit remains sole release authority; transport metadata is bound into it |
| Retry/failure | Multiple availability and failover mechanisms | Same provider/model only; bounded retry; stable technical failure |
| Windows operations | Node + Gateway + state + optional WSL2/Docker/service | Existing Python process plus provider SDK/HTTP dependency |
| Upgrade burden | Runtime, Node, plugins, sandbox image, protocol, advisories | One library/API version and explicit provider contract |
| Cost/lock-in | OpenClaw plus provider; broad surface | Provider-specific wire adapter behind a provider-neutral interface; replaceable |
| Testability | Requires real Gateway/sandbox/policy acceptance | Deterministic fake transport plus one narrowly approved live smoke test |
| Recovery | Gateway/service/state/auth/sandbox recovery | Disable adapter, revoke one credential, retain Project A audit |

The direct transport must preserve all existing Session 4 controls: deterministic
preflight, artifact hashes, request/setup/canonical identity, trusted expiry,
strict single-object JSON parsing, duplicate-key and non-finite-number rejection,
Decimal geometry, audit-chain persistence, cached-verdict revalidation, stable
technical failures, SHADOW mode, and absence of tools, browser, exec, Telegram,
Notion, TradingView mutation, MT5, or order paths.

## Security and operations conclusion

OpenClaw is valuable when Project A needs multi-channel ingress, managed agent
sessions, tools, memory, plugins, or cross-device operation. V1 intentionally
needs none of those capabilities. For V1, OpenClaw adds a Node/Gateway service,
state and credential database, protocol client, fallback logic, configuration
precedence, plugin surface, optional WSL2/Docker boundary, audit ledger, and
upgrade/advisory process. It removes no existing deterministic release gate.

The direct provider alternative adds a provider network boundary but no local
agent runtime and no tool capability. That is materially easier to fail closed,
test, monitor, disable, and recover. This conclusion intentionally contradicts
the original OpenClaw-oriented plan because the V1 outcome and enforceable trust
boundary take priority over the original component choice.

## Final recommendation

**Defer OpenClaw for Project A V1. Build only a disabled provider-neutral
transport boundary next, then select one provider/authentication method through
a separate approval.**

OpenClaw may be reconsidered only if a future exact stable release supplies a
documented and source-verifiable fail-closed Gateway-only invocation, binds the
effective agent/workspace/model/prompt identity before dispatch, exposes
measurable effective policy, and provides a required operational capability that
the direct adapter cannot provide.

## Explicitly deferred actions

- OpenClaw and Node installation or upgrade;
- Gateway, agent, workspace, state, service, sandbox, or port creation;
- OAuth/API-key entry, credential migration, or provider probe;
- model invocation of any kind;
- Telegram pairing or enablement;
- Notion, TradingView, MT5, broker, webhook, order, or Session 5 activation;
- implementation of the direct provider adapter;
- provider, model, endpoint, pricing, or authentication selection.

## Primary official references

- Release `v2026.7.1`: <https://github.com/openclaw/openclaw/releases/tag/v2026.7.1>
- Exact agent CLI contract: <https://github.com/openclaw/openclaw/blob/v2026.7.1/docs/cli/agent.md>
- Exact fallback source: <https://github.com/openclaw/openclaw/blob/v2026.7.1/src/commands/agent-via-gateway.ts#L940-L1003>
- Installation and Node requirements: <https://docs.openclaw.ai/install>
- Windows support: <https://docs.openclaw.ai/platforms/windows>
- Uninstall: <https://docs.openclaw.ai/install/uninstall>
- Gateway runbook and safety statements: <https://docs.openclaw.ai/gateway>
- Gateway protocol/handshake/audit: <https://docs.openclaw.ai/gateway/protocol>
- Gateway configuration and audit: <https://docs.openclaw.ai/gateway/configuration-reference>
- Sandbox architecture: <https://docs.openclaw.ai/gateway/sandboxing>
- Tool/sandbox/elevated precedence: <https://docs.openclaw.ai/gateway/sandbox-vs-tool-policy-vs-elevated>
- Policy inspection versus enforcement: <https://docs.openclaw.ai/cli/policy>
- Models/auth/fallbacks: <https://docs.openclaw.ai/cli/models> and <https://docs.openclaw.ai/concepts/model-failover>
- OAuth and credential behavior: <https://docs.openclaw.ai/oauth>
- State/config locations: <https://docs.openclaw.ai/help/environment>
- Security advisories: <https://github.com/openclaw/openclaw/security/advisories>
