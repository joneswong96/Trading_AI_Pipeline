# Session 1 Runtime Activation Gate

No TradingView operation is performed during offline convergence.

When runtime activation is separately authorized:

1. Compile `indicators/pine/snr_dashboard_project_a_v1.pine` in the approved
   isolated TradingView profile.
2. With Project A OFF, compare the title, plots, bands, background, drawings,
   4-by-29 table, defaults, historical bars, and realtime bar against the
   immutable Session B baseline.
3. Confirm OFF produces no Project A alert.
4. On XAUUSD 1m only, enable the shadow flag and use `Any alert() function call`
   with once-per-bar-close.
5. Inspect messages as Wire Event V1. Confirm there is no `received_at`,
   canonical hash, receipt identity, geometry, lifecycle, or Analysis Ready
   output.
6. Exercise support candidate, resistance candidate, simultaneous-direction
   ambiguity, telemetry, recalculation, and disabled-mode cases.
7. Confirm all HTF/HPA readiness evidence remains absent until a separately
   ratified confirmed-bar source exists.
8. Record Pine compile result and before/after visual evidence without
   configuring a live or production webhook.

Successful offline tests do not claim completion of these runtime gates.
