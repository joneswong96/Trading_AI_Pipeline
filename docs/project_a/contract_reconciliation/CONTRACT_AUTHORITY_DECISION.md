# Project A event contract authority decision

Status: **Session 0 recommendation; decision-preparation only**

Baseline: `8699c467d0fa72ed54a152c2073043c8b538648c`

Date: 2026-07-16

## Decision

Until Jones ratifies and Session 0 implements a replacement, the repository's
frozen `EVENT_SCHEMA_V0_2` is the only executable Event 0.2 authority. Its
authoritative definition is the combined behavior of:

- `contracts/schemas/event_schema_v0_2.json`;
- `contracts/validation.py`;
- `fixtures/project_a/event_cases.json`; and
- `project_a/replay.py`.

The flat JSON example in the [Convergence Contract](https://app.notion.com/p/3dc3bef340b24243b26d5208be32cd70)
is a conflicting document, despite its label `v0.2 RATIFIED BY JONES`. It has a
flat `source`, nested `event`, `time`, `raw`, analysis fields, and
`event_type: ANALYSIS_READY`. The executable repository contract instead has a
strict envelope with identities, correlation and causation, separate occurrence
and receipt timestamps, structured source/instrument/disposition, event class
and event type, and a bounded extension payload.

Those shapes, field meanings, validators, and identity models are incompatible.
Calling both “v0.2” would make version routing non-deterministic and would allow
two different documents to claim the same authority. Page status cannot make an
incompatible document pass the repository's strict validator.

## Temporary freeze rule

1. Sessions 1–5 remain frozen and may not promote candidate payloads or fixtures.
2. Readers accept only the registered strict repository Event 0.2.
3. Writers must not use the flat Notion example as an implementation contract.
4. Event 0.2 is retained as a **legacy executable/read contract**; its meanings
   are not edited in place.
5. A producer-supplied Event 0.2 `received_at` is preserved as legacy data but is
   not accepted as proof of actual network receipt.
6. Unsupported lifecycle combinations fail closed as specified in
   `LIFECYCLE_DISPOSITION_DECISION.md`.

## Why preservation does not ratify the timestamp claim

Frozen Event 0.2 can be preserved without representing Pine's `received_at` as
an actual receipt only by treating the whole record as a legacy producer
document. Session 2 stores the exact raw bytes and separately records its own
receipt clock. It must not overwrite `received_at` inside the producer document:
that would change the document, its canonical bytes, and any hash over it.

Therefore Session 2 may validate the original Event 0.2 and enrich a separate
receipt/audit record. It cannot enrich the same strict Event 0.2 object and still
claim it is the producer payload. A trustworthy canonical event requires a new
contract family.

## Required future documentation update

After the replacement pair is ratified, the Convergence Contract's flat example
should be marked **historical/conceptual and superseded**, with a link to the new
wire and canonical contracts. The repository Event 0.2 documentation should be
marked legacy/dual-read with an end-of-write date. This task deliberately makes
no Notion change and grants no authority to edit the Convergence Contract.

## Source record

This decision reconciles the [Project A Hub](https://app.notion.com/p/4034328f1d0c419fa31f77b864456318),
[Phase 1 Hub](https://app.notion.com/p/4ca9012caca3467c8f50d861873285c8),
[Analysis Skill](https://app.notion.com/p/d542adfd96a74affb66fa17379066c18),
[Session 0 brief](https://app.notion.com/p/23c28736fad14e6880b7c725de6cb695),
Session 1–5 briefs, the master acceptance findings, and the frozen repository
artifacts listed above. No page was updated.
