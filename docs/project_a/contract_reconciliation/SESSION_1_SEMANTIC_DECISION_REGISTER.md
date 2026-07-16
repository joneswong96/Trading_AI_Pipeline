# Session 1 semantic decision register

Status: **Jones decisions required before Session 1 rebuild**

Candidate source: commit `2389d4cf29701bf79a1c349a872988bf3216a3d7`,
`indicators/pine/snr_dashboard_project_a_v1.pine`

None of the rules below is ratified by frozen Event 0.2, the Project A Hub,
Phase 1 Hub, Analysis Skill, or Convergence Contract at the specificity used in
the candidate. Each changes whether or when an event becomes Analysis Ready and
is therefore a trading-semantic decision, not a replaceable coding detail.

| ID | Candidate rule and source | Authority | Options | Session 0 recommendation | Downstream impact / exact Jones decision |
|---|---|---|---|---|---|
| S1-01 | HPA = 50-bar high/low range position (`:241-244`) | No authoritative HPA algorithm found | Approve; replace with named existing HPA source; remove as readiness gate | Replace with a published, versioned HPA source or remove the gate | Changes HPA evidence and candidate eligibility. Jones must name the HPA authority/formula and timeframe inputs. |
| S1-02 | Premium at `>=0.60`, discount at `<=0.40` (`:244`) | None | Approve values; choose different boundaries; categorical upstream HPA | Do not ratify proxy thresholds | Changes direction/location classification. Jones must approve exact boundaries and equality behavior or an upstream category source. |
| S1-03 | Valid HPA when at least two of four TFs are non-middle (`:409-410`) | Analysis Skill requires context but no `2-of-4` rule | Approve; require directional concurrence; weighted/required TFs; no gate | Require directionally coherent, explicitly named TF policy; no mere non-middle count | Changes readiness and conflicts. Jones must select TFs, count/weights, direction rule, and missing behavior. |
| S1-04 | Candidate must be within one 5m ATR of target (`:421-424`) | None | Approve; fixed normalized points; band touch/percentage; observation-only | Keep proximity out of canonical readiness until calibrated | Changes setup creation volume/timing. Jones must approve metric, ATR period/TF, threshold, boundary equality, and stale/missing ATR behavior. |
| S1-05 | Latest expansion chooses active support/resistance; equality favors up (`:416-423`) | No tie-break authority | Approve; reject ambiguity; nearest band; explicit priority/state machine | Fail closed on simultaneous/equal candidates; emit telemetry until unambiguous | Changes side/hypothesis/setup ID. Jones must select simultaneous-candidate and equality tie-break behavior. |
| S1-06 | Rejection is sweep-reclaim, prior-bar engulf, or wick `>=` body with close conditions (`:458-470`) | Analysis Skill names rejection concepts but not these formulas | Approve each pattern; adopt existing published detector; subset; remove readiness authority | Map to an authoritative detector and ratify each pattern separately | Changes rejection path and trigger identity. Jones must approve pattern definitions, precedence, bar-close requirement, band touch/reclaim rules, and equality cases. |
| S1-07 | Break buffer = `0.3 * ATR(14,5m)` (`:38`, `:474-476`) | None | Approve; different ATR/threshold; points/ticks; level-close only | Do not ratify without shadow calibration | Changes break timing and invalidation (also uses buffer). Jones must approve ATR source/period/TF, multiplier, direction, and equality behavior. |
| S1-08 | Strong-break candle body/range `>=0.55` (`:458-476`) | None | Approve; different ratio; expansion detector output; no body gate | Use a named existing expansion/strong-break definition, not a new ratio | Changes break readiness. Jones must approve formula, threshold, zero-range handling, and whether wicks matter. |
| S1-09 | At least two of 1m/5m/15m/30m momentum slots agree (`:472-477`) | No `2-of-4` authority | Approve; required TF set; weighted policy; conflict veto; no gate | Ratify a directionally explicit fixed-TF policy after HTF decision | Changes break direction/readiness. Jones must choose TFs, count/weights, classification source, missing/conflict behavior. |
| S1-10 | Setup expires after 30 closed 1m bars (`:33`, `:480`) | No duration authority | Approve 30 bars; wall-clock window; session/path-specific expiry; downstream expiry | Use an explicit event/window duration contract, not an input default | Changes lifecycle closure and sample eligibility. Jones must select clock, duration per path/session, start instant, pause rules, and equality boundary. |
| S1-11 | Invalidation uses close beyond active band plus the same 0.3 ATR buffer (`:479`) | Only structural invalidation concept exists; exact rule absent | Approve; raw band breach; separate invalidation threshold; downstream thesis rule | Separate setup invalidation from break-confirmation threshold | Changes supported V0.2 lifecycle behavior. Jones must approve level owner, close/wick basis, buffer, confirmation count, and path-specific behavior. |
| S1-12 | Event priority: invalidation, expiry, rejection, break, candidate, telemetry (`:491-539`; design note) | No collision priority authority | Approve; emit multiple causally ordered events; fail ambiguity; different priority | Emit causally ordered distinct transitions where possible; otherwise fail closed | Can suppress evidence on collision bars. Jones must approve collision cases, priority, and whether multiple events per bar are legal. |
| S1-13 | Readiness uses developing 5m/15m/30m values via `request.security(...lookahead_off)` (`:397-403`) | No immutable HTF policy | Confirmed only; provisional with reconciliation; developing as final | Confirmed HTF bars by default | Affects reload stability, fingerprint, S2 dedupe, S3 bundle. Jones must approve confirmed-only or the full provisional/reconciliation model. |
| S1-14 | `barstate.isconfirmed`/realtime on 1m is sufficient immutability (`:544`) | No; it does not confirm higher TF bars | Treat all evidence confirmed; confirm each source bar; provisional metadata | Require each included TF's bar identity/confirmed state | Changes event truth after reload. Jones must confirm per-timeframe close policy. |
| S1-15 | Setup identity uses encounter time, side, and band-centre ticks (`:440-456`) | Frozen contract requires stable opaque ID but not algorithm | Approve; SNR source identity; deterministic UUID/hash; S2-issued canonical setup ID | Bind producer setup ID to stable SNR identity/version, not rounded centre alone | Affects lifecycle correlation and dedupe. Jones must approve what constitutes the same setup after band movement/reload. |
| S1-16 | Trigger price is current close; candidate geometry is absent (`:542`, `:550`) | Hub/Analysis Skill require trigger/entry concepts but do not settle producer geometry | Close; touch/reclaim/break level; downstream compiler owns geometry | Define trigger separately from actionable entry/SL/TP geometry | Affects fingerprint and Sessions 3–5. Jones must approve trigger meaning and which session owns actionable geometry. |

## HTF recommendation and alternative

Default: only confirmed higher-timeframe bars may contribute to an immutable
canonical Analysis Ready event. Each slot records timeframe, source bar identity,
and close time.

If Jones requires developing HTF evidence, it must be marked `PROVISIONAL`, carry
the HTF bar identity and scheduled close, and later produce an explicit confirm,
revise, or retract reconciliation event. Session 2 must never label it reload-
stable, and Sessions 3–5 must not treat it as final without a separately approved
eligibility rule.

## Promotion consequence

The candidate may remain engineering evidence, but it cannot gain canonical
Analysis Ready authority. Session 1 should be rebuilt from an immutable,
fingerprinted Pine source baseline after these decisions, rather than patched in
place around assumptions whose combined behavior has not been approved.
