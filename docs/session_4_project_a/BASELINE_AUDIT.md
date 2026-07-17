# Session 4 baseline audit

Audit date: 2026-07-16 (Australia/Sydney)

## Baseline and ownership

- Repository: `C:/Users/jones.w/TradingSys/trading-auto`.
- Isolated worktree: `C:/Users/jones.w/TradingSys/trading-auto-session4`.
- Branch: `project-a/session-4-ai-review-v1`.
- Required baseline: `d10f6eaf44658caa83dba19009eeef5162cf033c`.
- `project-a/integration-v1` points exactly to the required baseline.
- The original worktree contains untracked Session 3 files. It was not switched or
  modified; this separate worktree prevents overwrite.
- Applicable repository instructions were read from the original worktree's
  untracked `AGENTS.md` and the tracked `CLAUDE.md`. Both require deterministic
  Python risk gates, replayable artifacts, fresh eyes, XAUUSD-only, notify-only,
  and no broker API.

## Required authority read

- [Project A Hub](https://app.notion.com/p/4034328f1d0c419fa31f77b864456318)
- [Phase 2 Hub](https://app.notion.com/p/5003182d3f3245fbb19022f23995211a)
- [Session 4](https://app.notion.com/p/f18be1d9e51848679a58ddaa3c025dfb)
- [Project A Analysis Skill](https://app.notion.com/p/d542adfd96a74affb66fa17379066c18)
- [Project A three-phase SSOT](https://app.notion.com/p/326236ef979f4545a3e762394026fa94)
- [Pre-order checklist and hard stops](https://app.notion.com/p/e3dd3e5031fb4542a785bb465c3e8c18)
- All six Session 0 documents under `docs/project_a/`, both frozen schema
  documents, contract registry/validator, fixtures, contract tests, and replay.

The repository's frozen contracts are authoritative over illustrative Notion
payloads. No frozen contract or shared fixture is changed by Session 4.

## Existing model and prompt paths

| Area | Baseline finding | Session 4 consequence |
|---|---|---|
| AI/model clients | `analyze/claude_client.py` is the only SDK client. It lazily imports Anthropic, requires `ANTHROPIC_API_KEY`, and invokes a legacy screenshot SOP. No OpenAI/Codex adapter exists. | Do not modify it. Add a new provider-neutral boundary under a Session 4-owned package. |
| Model selection | Legacy default is `claude-sonnet-4-6`; the dependency is intentionally not installed. | Project A model/provider must be explicit and audited. No silent provider fallback. |
| Prompts | `analyze/sop_prompt.py`, `.claude/commands/analyze.md`, and `docs/golden_contract.md` implement the legacy full-analysis flow. | Add a separate versioned quick-review prompt. Do not reuse or mutate the legacy full-analysis prompt. |
| Output parsing | Legacy `_extract_json` returns the first brace-balanced object and ignores surrounding prose. `json.loads` follows, with no duplicate-key rejection or Project A verdict validation. | New parser accepts one bounded JSON object only, rejects prose/fences/duplicate keys, then applies the frozen verdict validator and deterministic post-gates. |
| Retry/timeout | Legacy model client has no explicit timeout or retry classification. Telegram uses a 10-second HTTP timeout and no local retry. | Add explicit model timeout, stable technical failures, bounded retry attempts, and expiry rechecks. |
| Audit | SQLite cycle/thesis tables, JSONL wake files, and call artifacts exist, but no AI-attempt audit with hashes or model provenance exists. | Add a Session 4-owned hash-chained shadow audit store; do not change shared DB shape. |

## Existing integrations and runtime

- Telegram: `publish/telegram.py` sends unrestricted configured chat text using a
  bot token and chat ID; `output/telegram_push.py` is a Phase 3 renderer with
  in-memory dedupe. Neither implements pairing, numeric-user authorization, DM
  type checks, or Project A operator commands. Session 4 will not call them.
- OpenClaw: no `openclaw` executable on `PATH`, no global npm package, no
  `C:/Users/jones.w/.openclaw` state directory, and therefore no installed
  version, agent, workspace, sandbox, tool policy, session store, Telegram
  pairing, or OpenClaw OAuth profile to inspect.
- OAuth: `OPENCLAW_CONFIG_PATH`, `OPENCLAW_STATE_DIR`, and `OPENCLAW_PROFILE` are
  unset. No OpenClaw config or credential location exists. If installed, the
  official default is the protected OpenClaw state directory, separate from the
  agent workspace. Session 4 will not create or modify it.
- Environment credential presence was checked by name only. `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and
  `NOTION_TOKEN` are absent; this worktree has no `.env`. Values were never read
  or printed.
- Docker 28.4.0 is installed. Python launcher provides Python 3.11.3. Node is
  20.18.1; npm is 10.8.2.
- Existing browser/filesystem access belongs to legacy capture code on CDP
  9222/9333. It is outside Session 4 and will not be exposed to the reviewer.
- Existing OpenClaw browser/exec/filesystem permissions: none, because OpenClaw
  is absent. The template must deny them and require per-session sandboxing.

## Credential handling

The repository uses `.env` (gitignored) and empty variable names in
`.env.example`. Runtime browser profiles and common storage artifacts are also
gitignored. Existing code can place a bot token in a request URL at runtime; it
does not log the URL, but it is not an acceptable Session 4 operator boundary.
Session 4 templates use environment/SecretRef placeholders only and never store
token values in the repository or audit records.

## Existing tests and working commands

- Session 0 contract tests: `py -m pytest tests/test_project_a_contracts.py tests/test_project_a_replay.py -q`.
- Offline replay: `py -m project_a.replay --all`.
- Full suite: `py -m pytest tests -q`.
- No formatter, linter, static type checker, or CI workflow is configured.

## Contract conflicts and adapter decisions

1. `AI_VERDICT_SCHEMA_V1` has no dedicated `evidence_refs` field. Session 4 will
   encode evidence references as strict `reason_codes` with the prefix
   `EVIDENCE_`, validate each against the manifest, and document a future schema
   improvement. This is contract-valid and avoids widening the schema.
2. The frozen request names required screenshots but does not contain artifact
   paths or hashes. A narrow out-of-band dispatch envelope supplies a trusted
   artifact root, manifest, bundle hash, and manifest hash. Request fields never
   choose unrestricted paths.
3. The frozen validator uses finite-number checks plus `math.isclose(...,
   abs_tol=1e-9)` for 1:1. Session 4 also uses exact decimal arithmetic at the
   request's authoritative point size; it is stricter, not more permissive.
4. The frozen verdict repeats trusted identifiers and model metadata. Session 4
   requires exact matches, then returns a trusted copy only after validation.

## Next incomplete vertical slice

Implement recorded validated request + manifest -> deterministic preflight ->
mocked/OpenClaw boundary -> strict verdict parsing -> deterministic post-gates ->
durable shadow audit -> safe result, with technical failures separate from trade
verdicts. Real OAuth, Telegram pairing, and user-level OpenClaw configuration are
explicit Jones-operated acceptance steps.

## Proposed Session 4-owned paths

- `project_a_ai_review/**`
- `config_templates/project_a_reviewer/**`
- `fixtures/session_4_project_a/**`
- `tests/session_4_project_a/**`
- `docs/session_4_project_a/**`
