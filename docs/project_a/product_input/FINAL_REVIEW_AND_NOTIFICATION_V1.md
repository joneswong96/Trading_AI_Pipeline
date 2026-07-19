# Project A Final Review and Notification V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE**

The separate verdict/grade model and exactly-once B-to-A notification concept are
approved. Provider execution, real SHADOW calls and every external writer remain
disabled and require separate approval.

This contract defines review and notification semantics only. It does not enable
an AI provider, writer, Telegram, Notion, webhook, broker or order path.

## 1. Separate verdict and grade

Verdict and grade are independent required outputs.

| Dimension | Allowed values | Meaning |
|---|---|---|
| Verdict | `APPROVE`, `REJECT`, `MODIFY`, `EXPIRED` | Action on the submitted setup and evidence |
| Grade | `A`, `B`, `C` | Current evidence quality/maturity |

- `APPROVE` accepts the submitted geometry and validity unchanged.
- `MODIFY` may propose changed entry, stop-loss, take-profit, invalidation or
  validity only when each changed field is explicit and supported by the same
  immutable evidence bundle.
- `REJECT` closes or returns the setup according to a deterministic reason.
- `EXPIRED` means the evidence or setup validity elapsed before approval/entry.
- Grade A alone does not authorize notification. Verdict, state, geometry,
  freshness, lineage and the matching FIRE rule must also pass.

## 2. Required final readout

Every final review result contains:

| Field | Requirement |
|---|---|
| `setup_id` and `review_id` | Stable setup identity and deterministic review identity |
| `reviewed_state_id` | Exact Numeric Market State reviewed |
| `evidence_bundle_id` / `evidence_manifest_sha256` | Immutable capture reference and hash |
| `verdict` | One allowed verdict |
| `grade` | A, B or C |
| `setup_direction_5m` | `LONG`, `SHORT`, or `NEUTRAL`, backed by 5m context |
| `confirmation_1m_status` | Direction and confirmed/unconfirmed status |
| `watch_direction_5s` | Required Sniper FIRE direction or `NONE` |
| `cancellation_condition` | Deterministic condition with evidence-field references |
| `entry_price` | Decimal XAU quote value or null when no actionable geometry |
| `stop_loss_price` | Decimal XAU quote value or null |
| `take_profit_price` | Decimal XAU quote value or null |
| `invalidation_condition` | Deterministic rule and optional `invalidation_level_price` |
| `valid_until` | UTC timestamp; required for APPROVE/MODIFY |
| `evidence_references` | Ordered source-event, snapshot, transition and manifest IDs |
| `missing_fields` / `errors` | Explicit fail-closed records |

The bare field name `price` is forbidden. Geometry uses dimensioned field names.
APPROVE or MODIFY requires finite values, unambiguous units, directionally valid
entry/SL/TP geometry and a future `valid_until` at decision time.

## 3. Final-review gates

An A-grade APPROVE or MODIFY result requires:

1. Current story is `B_TO_A_CANDIDATE` or `WAITING_5S_ENTRY` under the same setup.
2. Liquidity reaction is valid and confirmed.
3. Confirmed standard 5m MACD thesis remains valid.
4. Confirmed standard 1m MACD supports the intended direction.
5. Confirmed Renko Main matches that direction.
6. DXY is not materially conflicting under the approved grade-cap policy.
7. Structure evidence, expansion trigger/quality and all mandatory source
   identities are present and fresh.
8. Capture manifest and every referenced artifact hash validate.
9. Entry/SL/TP, invalidation and expiry are complete and deterministic.
10. No required risk field is silently guessed. If an approved spread gate exists
    while spread remains unavailable, the result cannot be APPROVE or MODIFY.

A missing required gate produces grade C or REJECT/EXPIRED as appropriate; the
reviewer may not repair source data.

## 4. Waiting for the 5s event

When all A requirements except a fresh matching Sniper FIRE pass, the story is
`WAITING_5S_ENTRY`. Its output repeats:

- the confirmed 5m setup direction;
- the 1m confirmation status;
- the required 5s FIRE direction;
- the exact cancellation condition; and
- `valid_until`.

Only a newly accepted, confirmed, fresh FIRE for the same setup and direction may
complete the entry transition. An older FIRE cannot be borrowed from another
setup or from before the candidate transition.

## 5. Exactly-once B-to-A notification

A notification is eligible only when all conditions are true:

1. The setup's previous final grade was `B`.
2. The current final grade is `A`.
3. Verdict is `APPROVE` or `MODIFY`.
4. The setup remains valid and unexpired.
5. The 5m thesis remains valid.
6. The 1m confirmation is confirmed and matching.
7. A new, confirmed, fresh Sniper FIRE matches the setup direction.
8. The evidence bundle and final review pass integrity checks.
9. This semantic transition has not already been notified.

The deterministic notification key is the SHA-256 of the notification-contract
version, setup ID, prior grade, current grade, verdict, final review ID, matching
Sniper FIRE event ID and entry-geometry revision. Before delivery, a persistent
outbox must atomically reserve that key. A successful delivery records the key,
destination-independent receipt reference and time. Retries reuse the same key;
they do not create a second logical notification.

A persistent A state, repeated snapshot, repeated review, duplicate FIRE, process
restart or delivery retry must not repeat the notification.

A new notification requires all of:

- a new setup ID following prior invalidation, expiry or explicit reset;
- a new B-to-A grade transition;
- a new matching entry event; and
- a notification key not present in the immutable notification history.

No delivery channel is authorized by this documentation. Telegram, Notion and
other external writers remain disabled until separately approved.

## 6. Rejection, expiry and modification behavior

- `REJECT` and `EXPIRED` never generate a B-to-A notification.
- `MODIFY` does not change source evidence, setup direction or source facts. It
  produces a new geometry revision linked to the reviewed proposal.
- A modification after a notification requires invalidating the old setup and a
  new setup/entry transition; it cannot silently edit the notified record.
- If a source later reconciles provisional evidence into conflicting confirmed
  evidence, append an invalidation/reconciliation record. Never overwrite the
  original review or notification.

## 7. Audit lineage

The final result and any notification record retain setup/state/review IDs,
evidence manifest hash, source-event IDs, source revision/hashes, confirmation and
freshness states, deterministic rule version, notification key, and predecessor
record references. Secret values and machine-local paths are forbidden.
