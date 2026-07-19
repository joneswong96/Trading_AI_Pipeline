# Jones approval checklist — Product Input Authority V1

Status: **ALL ITEMS UNAPPROVED**

Checking an item is a product decision, not runtime activation. Activation,
producer changes, schemas, tests and external writers require separate tasks.

## 1. Factual findings

These findings were observed read-only and do not require policy approval:

- Port 9333 currently contains deterministic XAUUSD 1m/5m/15m/30m standard MACD,
  XAUUSD 4H/D/W charts and TVC:DXY 15m.
- Port 9222 currently contains the supplemental Renko/chart environment and
  TVC:DXY 1m.
- Port 4999 is the isolated acceptance profile.
- Liquidity V2 revision 9, Expansion V3 revision 5, Expansion Scanner revision 6
  and Renko V3 Sniper revision 1 are saved but not materialized in the proposed
  production layouts.
- The currently loaded 9222 Renko script is an older Renko V2, not the proposed
  Renko V3 Sniper authority.
- Current bid/ask/spread lack a trusted approved source.
- The six legacy private libraries are not parity substitutes for the proposed
  authorities.

## 2. Proposed authority decisions

- [ ] Approve `Liquidity Levels V2 — 5m Body × MTF Confluence`, private revision
      9, as the proposed Liquidity authority.
- [ ] Approve `Expansion Leg Signal V3`, private revision 5, as the confirmed
      expansion trigger, with `③ Expansion Scanner [SNR3.0]`, private revision 6,
      used only for CLEAN/WEAK/too-extended quality classification.
- [ ] Approve TradingView standard price MACD, close EMA 12/26/9, using exact
      9333 closed-bar values for 1m/5m/15m/30m.
- [ ] Approve 9333 TVC:DXY 15m as primary and 9222 TVC:DXY 1m as supplemental,
      used as evidence/grade cap rather than a universal hard veto.
- [ ] Approve `Renko V3 — V2 Preserved + 5s Sniper Dashboard`, private revision
      1, source SHA-256
      `327c5043f9ca53f531b8d8e8aa89e6b72d649a527339432bbeeef5bcb463f003`,
      as the proposed Renko authority.
- [ ] Approve deterministic 9333 XAUUSD 4H/D/W price structure as numeric
      structure/regime authority and keep SR MTF Pro V10 as visual/supporting
      context only for V1.

## 3. Proposed route and transport decisions

- [ ] Approve hybrid Pine events plus direct 9333/9222 structured reads.
- [ ] Approve port 9333 as primary deterministic data/capture authority.
- [ ] Approve port 9222 as explicit supplemental read-only Renko/chart authority.
- [ ] Confirm port 4999 remains test/acceptance only and forbidden for production
      evidence.
- [ ] Approve no silent fallback between ports, layouts, targets or sources.
- [ ] Approve the proposed freshness and source-bar-alignment rules in
      `CAPTURE_AUTHORITY_V1.md`, including market-closure fail-closed behavior.

## 4. Proposed maturity and notification decisions

- [ ] Approve E1 as earliest/B-building evidence, E2 as stronger B-to-A candidate
      evidence, Main as reversal confirmation, and Sniper FIRE as final 5s timing.
- [ ] Confirm E1 is not required before E2.
- [ ] Approve the `B_TO_A_CANDIDATE` capture trigger and the Make-Sense transition
      gates.
- [ ] Approve exactly-once B-to-A notification only for prior grade B, current
      grade A, verdict APPROVE/MODIFY, valid 5m thesis, confirmed 1m, and a new
      matching Sniper FIRE.
- [ ] Confirm a persistent A state never repeats the notification and a new
      notification requires a new setup, reset/invalidation/expiry boundary, new
      B-to-A transition and new matching entry event.

## 5. Producer-gap decisions

- [ ] Authorize a later Pine-producer proposal for Liquidity event time, current
      market value, band/reaction data and unambiguous field names. No change is
      authorized by this checklist alone.
- [ ] Authorize a later producer proposal for Expansion numeric start,
      displacement, ATR, efficiency, body quality, opposing bars, speed and age.
- [ ] Authorize a later producer proposal for E1/E2/Main event identities,
      dimensioned signal values, source-bar times, confirmation and reset/validity
      data.
- [ ] Decide the deterministic structure regime/break/obstacle definitions.
- [ ] Decide and approve a trusted bid/ask/spread source before any spread gate can
      pass.

## 6. Explicit non-decisions

Approval of this checklist does not by itself:

- mark a source runtime-active or production-approved;
- load an indicator or edit Pine;
- create or edit an alert;
- approve an executable schema or JSON producer;
- enable OpenAI, Telegram, Notion, webhook, MT5, broker or order actions;
- alter frozen Event V0.2/Event V1 contracts, fixtures or historical records; or
- authorize a merge into `project-a/integration-v1`.

## 7. Required approval record

Jones's approval record should identify the reviewed commit SHA, list each checked
item, record any changed wording or threshold, and explicitly state whether the
next task is producer-contract design or another documentation correction. Any
unchecked item remains unapproved and fails closed.
