"""Step 3 golden regression（contract §3.1）。

- parse golden/expected.md + check_call 邏輯：而家就測（deterministic）。
- live regression（跑真 analyze → 對 expected）：等 wiring（key + SOP_SYSTEM_PROMPT）先郁，
  未齊料就 skip。Fresh Eyes（cross-snapshot）單張 golden 唔 assert（contract §3.1）。
"""
from pathlib import Path

import pytest

from analyze.claude_client import AnalyzeClient
from analyze.call_writer import render_5line
from analyze.golden import check_call, count_forbidden, parse_expected_file

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MD = ROOT / "golden" / "expected.md"
INPUT_DIR = ROOT / "golden" / "input"

# 「應該 PASS」嘅 call = Jones 2026-06-14 golden sample output（SOP_SYSTEM_PROMPT schema）
GOOD_CALL = {
    "day_type": "RANGE",
    "gate": {"m1": "BULL", "m5": "BULL", "m15": "BEAR", "m30": "BEAR", "score": 2,
             "display": "M1✓ / 5m✓ / 15m✗ / 30m✗ = 2/4"},
    "gate_pass": False,
    "range_confirmed": True,
    "range_bounds": [4183.0, 4240.0],
    "price_in_midband": True,
    "action": "WAIT",
    "grade": "C",
    "confluence_layers": 0,
    "dxy_modifier": "NEUTRAL",
    "htf_override_triggered": False,
    "wait_has_alert": True,
    "wait_alerts": [4240.0, 4183.0],
    "track": "NONE",
    "five_line_call": (
        " WAIT for [5m 收盤破 4,240 + DXY confirm + gate ≥3/4]|||"
        "而家：坐定定，唔好追（RANGE mid-band 4,183–4,240）|||"
        "Grade：C – SKIP（gate 2/4 <3；0 layer；DXY 橫行→封頂 B+）|||"
        "點解：RANGE 確認；M1✓5m✓15m✗30m✗ = 2/4；HTF override 唔觸發|||"
        "睇邊度：上 alert @ 4,240（5m 收穿+DXY 跌→Long）｜下 alert @ 4,183（5m 收跌+DXY 升→Short）"),
}


def test_expected_md_parses():
    exp = parse_expected_file(EXPECTED_MD)
    assert exp["day_type"] == "RANGE"
    assert exp["gate"] == {"m1": "BULL", "m5": "BULL", "m15": "BEAR", "m30": "BEAR"}
    assert exp["gate_score"] == "2/4" and exp["gate_pass"] is False
    assert exp["range_bounds"] == [4183, 4240] and exp["price_in_midband"] is True
    assert exp["action"] == "WAIT" and exp["grade"] == "C"
    assert exp["dxy_modifier"] == "NEUTRAL" and exp["htf_override_triggered"] is False
    assert exp["wait_alerts"] == [4240, 4183] and exp["forbidden_phrases_count"] == 0


def test_check_call_passes_on_matching_call():
    exp = parse_expected_file(EXPECTED_MD)
    assert check_call(GOOD_CALL, exp, push_text=render_5line(GOOD_CALL)) == []


def test_check_call_flags_mismatches():
    exp = parse_expected_file(EXPECTED_MD)
    bad = dict(GOOD_CALL, action="IN", gate_pass=True, grade="A")
    fails = check_call(bad, exp, push_text="")
    joined = " ".join(fails)
    assert "action" in joined and "gate_pass" in joined and "grade" in joined


def test_check_call_flags_forbidden_phrase():
    exp = parse_expected_file(EXPECTED_MD)
    fails = check_call(GOOD_CALL, exp, push_text="你應該停止交易，walk away")
    assert any("forbidden" in f for f in fails)


def test_count_forbidden():
    assert count_forbidden("這張圖 consider waiting，are you sure？") >= 2
    assert count_forbidden("WAIT for 5m 收破 4240，alert 4183") == 0


def test_golden_input_present():
    pngs = list(INPUT_DIR.glob("*.png"))
    assert {p.stem for p in pngs} >= {"g4_5m_1m", "g5_15m_30m"}  # 4 gate TF 來源齊


def test_live_regression_runs_when_wired():
    """真 analyze(golden/input) → check_call。未 wire（無 key）就 skip。

    自動 load .env → Jones 落咗 ANTHROPIC_API_KEY + pip install anthropic 之後，skip 自動變 live。
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    client = AnalyzeClient()
    ok, missing = client.ready()
    if not ok:
        pytest.skip(f"golden live regression 等 wiring：{missing}")
    exp = parse_expected_file(EXPECTED_MD)
    paths = sorted(str(p) for p in INPUT_DIR.glob("*.png"))
    res = client.analyze(paths)
    fails = check_call(res.call, exp, push_text=render_5line(res.call))
    assert fails == [], f"golden regression mismatches: {fails}"
