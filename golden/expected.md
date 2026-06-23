# Golden Expected Output — XAUUSD 2026-06-14 20:07 AEDT
# Input: golden/input/ (9 charts, 4 gate TF MACD readable)
# Contract: docs/golden_contract.md (APPROVED & LOCKED 2026-06-14)

## Deterministic Assertions (regression must pass all)
day_type: RANGE
gate: M1=BULL / 5m=BULL / 15m=BEAR / 30m=BEAR  → 2/4  → ANT_LIMIT_ONLY
gate_pass: false  # <3/4
range_confirmed: true
range_bounds: [4183, 4240]
price_in_midband: true   # 4218.50 ∈ mid-band
action: WAIT             # not IN, not SKIP
grade: C                 # 0 confluence layers at current price
dxy_modifier: NEUTRAL    # flat → grade cap B+
htf_override_triggered: false  # 4H+D bull, W bear — not all same direction
forbidden_phrases_count: 0
wait_has_alert: true
wait_alerts: [4240, 4183]

## 5-Line Push Call (structure assert only; prose is free-form)
# line 1 action_call: starts with WAIT, contains alert prices
# line 2 action_now: mentions mid-band / 唔做
# line 3 grade_line: contains "C" and gate score "2/4"
# line 4 reason: mentions RANGE + gate + DXY
# line 5 watch: contains upper (4240) and lower (4183-4185) alerts
