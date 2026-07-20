# Jones approval checklist — Product Input Authority V1

Status: **APPROVED_AUTHORITY_NOT_RUNTIME_ACTIVE — PENDING ITEMS UNAPPROVED**

Approval date: 2026-07-20 Australia/Sydney. A checked item records Jones's
explicit Product Input policy approval. It does not activate an indicator,
producer, schema, adapter, provider or writer.

## 1. Factual findings

- Port 9333 contains deterministic XAUUSD 1m/5m/15m/30m standard MACD,
  XAUUSD 4H/D/W charts and TVC:DXY 15m.
- Port 9222 contains the supplemental Renko/chart environment and TVC:DXY 1m;
  its native-Renko layout is not the Renko V3 Sniper host.
- Port 4999 is isolated acceptance/test only.
- Liquidity V2 revision 9, Expansion V3 revision 5 and Renko V3 Sniper revision
  1 are the three active saved candidates. Expansion Scanner revision 6 is
  dormant reference/compatibility only.
- The exact Renko V3 Sniper host is layout `YclFo8Ax` on the verified 9333
  profile: ICMARKETS:XAUUSD, 5-second standard candles. The native-Renko 9222
  layout is not parity.
- Current bid/ask/spread lack a trusted approved source.
- The six legacy private libraries are not parity substitutes for the approved
  V1 authorities.

## 2. Approved authority decisions

- [x] Approve `Liquidity Levels V2 — 5m Body × MTF Confluence`, owner
      `Jonesy_Wong`, private revision 9, as the V1 Liquidity authority. Preserve
      conventional ASK/resistance and BID/support semantics, MTF confluence,
      touch count, PRIME/VALID/WEAK grade, lifecycle and first confirmed touch.
- [x] Approve `Expansion Leg Signal V3`, private revision 5, as the sole active
      Expansion movement trigger/direction authority. Retain `③ Expansion
      Scanner [SNR3.0]`, private revision 6, only as dormant compatibility and
      reference; it is not a second vote or a Section 2 dependency.
- [x] Approve TradingView standard price MACD, close EMA 12/26/9, using exact
      9333 closed-bar values: 5m setup, 1m confirmation, and 15m/30m context.
- [x] Approve 9333 TVC:DXY 15m as primary and 9222 TVC:DXY 1m as supplemental,
      used as confirmation/conflict evidence and a possible grade cap, not a
      universal hard veto.
- [x] Approve `Renko V3 — V2 Preserved + 5s Sniper Dashboard`, private revision
      1, source SHA-256
      `85cd8c8c5a3ec2331b0b90dc1f920dd89c6ed68a1a4ba4779037e15de7f17298`,
      as the V1 Renko authority candidate for `YclFo8Ax`, ICMARKETS:XAUUSD,
      5-second standard candles, with status `SAVED_NOT_MATERIALIZED`.
- [x] Approve deterministic 9333 XAUUSD 4H/D/W price structure as V1 numeric
      structure/regime authority and retain SR MTF Pro V10 as visual/supporting
      context only.

## 3. Approved route and transport decisions

- [x] Approve hybrid Pine state-transition events plus direct 9333/9222
      structured reads; screenshots are visual context only.
- [x] Approve port 9333 as primary deterministic production data/capture
      authority.
- [x] Approve port 9222 as explicit supplemental read-only chart and DXY 1m
      authority; the currently verified `YclFo8Ax` production host is on 9333.
- [x] Confirm port 4999 remains `TEST_ONLY` and is forbidden for production
      evidence.
- [x] Approve no silent fallback between ports, layouts, targets, timeframes or
      sources. Target rebinding after restart requires explicit identity
      verification.
- [x] Approve `FRESHNESS_POLICY_V1.md`: exact maximum ages, 75% `AGING`
      boundary, event/capture/clock-skew limits, critical/context effects,
      market-closed handling and final 5s timing requirements.

## 4. Approved maturity and notification decisions

- [x] Approve E1 as early/B-building evidence, E2 as stronger maturity and
      possible B-to-A candidate evidence, Main as confirmed Renko direction, and
      Sniper FIRE as final 5s execution-timing candidate.
- [x] Confirm E1 is not required before E2; E2 or Main may occur without a
      recorded earlier stage.
- [x] Approve the Make-Sense state family: `NO_STORY`, `C_INSUFFICIENT`,
      `B_BUILDING`, `B_TO_A_CANDIDATE`, `A_CONFIRMED`, `WAITING_5S_ENTRY`,
      `INVALIDATED`, and `EXPIRED`.
- [x] Approve entry into `B_TO_A_CANDIDATE` as the complete-capture trigger.
- [x] Approve `LIQUIDITY_DISTANCE_POLICY_V1.md`: confirmed 5m ATR(14)
      normalization; side-aware ASK/BID signed distance; exact FAR, APPROACH and
      NEAR_TOUCH boundaries; zero/crossed fail-closed handling; and no automatic
      HIT, REJECT, BREAK, A or GO inference. This is policy approval only and
      does not activate Liquidity V2 or runtime.
- [x] Liquidity stable identity and deterministic competing-level selection V1.
      This includes explicit level versions, per-level lifecycle ownership, the
      exact seven-key ranking, tracked-level lock and explicit release; it does
      not activate Liquidity V2 or runtime.
- [x] Approve exactly-once B-to-A notification only for prior grade B, current
      grade A, verdict APPROVE/MODIFY, valid 5m thesis, confirmed 1m direction,
      and a new matching Sniper FIRE.
- [x] Confirm persistent A, retries, duplicate FIRE events and process restarts do
      not repeat a logical notification. A new one requires a new setup boundary,
      B-to-A transition and matching entry event.

## 5. Pending producer, algorithm and runtime decisions

- [ ] Approve an exact Expansion speed formula. **Pending; fail closed.**
- [ ] Approve an exact Expansion exhaustion formula. **Pending; fail closed.**
- [ ] Approve an exact E1/E2 event TTL. **Pending; fail closed.**
- [ ] Approve an exact structure/range algorithm. **Pending; fail closed.**
- [ ] Approve an exact nearest-obstacle calculation. **Pending; fail closed.**
- [ ] Approve a trusted bid/ask/spread authority. **Pending; unavailable.**
- [x] Approve one controlled production TradingView layout materialization,
      including Renko V3 Sniper, under `MATERIALIZATION_APPROVAL_V1.md`.
- [x] Approve exactly three new Project A alerts: `LIQ_V2`, `EXP_V3`, and
      `RENKO_V3`. Expansion V3 is the sole active Expansion producer. Scanner is
      dormant reference/compatibility only: no chart materialization, alert,
      directional vote, Section 2 dependency, wake or promotion. The two
      existing legacy alerts remain protected, and no fourth Project A alert is
      authorized.
- [ ] Approve Pine producer changes for missing Liquidity, Expansion and Renko
      numeric/event fields. **Pending; `PENDING_PRODUCER_CHANGE`.**
- [ ] Approve provider runtime activation. **Pending; disabled.**
- [ ] Approve a real SHADOW model call. **Pending; not authorized.**
- [ ] Approve Telegram, Notion or MT5 Demo output activation. **Pending; writers
      disabled.**

## 6. Approved execution boundary

- [x] Preserve `mode=SHADOW` and `environment=MT5_DEMO`.
- [x] Preserve `live_execution=false`, `order_placed=false`, and
      `writer_enablement=DISABLED`.
- [x] Confirm this approval does not authorize live broker execution, real-account
      orders, a provider call, MT5 connection, Pine publication or credential
      creation. TradingView alert creation and runtime materialization are
      limited to the exact bounded actions in `MATERIALIZATION_APPROVAL_V1.md`.

## 7. Legacy/reference disposition

- [x] Liquidity V1 revision 11 is `LEGACY_REFERENCE`, not the V1 authority.
- [x] `expDetector/1`, `macdVol/1`, `dxyReader/3`, `rekoArrow/1`,
      `structState/1`, current Renko V2, the standalone E1/E2 test source and
      Renko V3 revision 4 without Sniper are reference/supporting sources only as
      specified in the authority contract.

## 8. Approval record and next boundary

The controlling approval record is `APPROVAL_RECORD.md`. Every unchecked item
remains unapproved. The next task requires a new explicit instruction and must not
be inferred from this checklist.
