"""Step 3 tests：call_writer（deterministic）+ sop_prompt 骨架 + client gate（未 wire 要 raise）。"""
import json
from pathlib import Path

import pytest
from PIL import Image

from analyze.call_writer import render_5line, write_call
from analyze.claude_client import AnalyzeClient
from analyze.sop_prompt import build_messages, prompt_ready

SAMPLE_CALL = {
    "action": "WAIT", "direction": "Short",
    "summary": "5m 收破 4,073.77 + DXY 反向先入 — range 正中 🚫唔做",
    "now": "等 trigger，唔好追",
    "levels": {"snr": 4073.77, "entry": 4073.5, "sl": 4078.5, "tp1": 4066, "tp2": 4057},
    "why": "range 中間 + gate 2/4 唔夠",
    "watch": ["下 4,057 收穿→Short", "上 4,073 收上→Long", "第三個唔應該出"],
    "grade": "B+", "gate": "2/4", "alerts": [4057, 4074], "ant": {"side": "Short"},
}


def test_render_5line_shape_and_action_first():
    lines = render_5line(SAMPLE_CALL).split("\n")
    assert len(lines) == 5
    assert lines[0].startswith("WAIT Short")            # action call 第一句
    assert "SL 4078.5" in lines[2] and "TP" in lines[2]
    assert "第三個" not in lines[4]                       # watch ≤2，第三個唔出


def test_render_5line_tolerates_missing_fields():
    lines = render_5line({"action": "SKIP"}).split("\n")
    assert lines[0] == "SKIP"
    assert "—" in lines[1]                               # 缺欄位用 —，唔 crash


def test_write_call_writes_features_and_call(tmp_path):
    res = write_call(str(tmp_path), SAMPLE_CALL)
    feats = json.loads(Path(res["features_path"]).read_text(encoding="utf-8"))
    assert feats["action"] == "WAIT" and feats["grade"] == "B+"
    assert feats["trigger"] == 4073.5 and feats["has_ant"] is True
    assert Path(res["call_path"]).exists()


def test_build_messages_has_text_then_images(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"s{i}.png"
        Image.new("RGB", (8, 8)).save(p)
        paths.append(str(p))
    content = build_messages(paths, asset="XAUUSD")[0]["content"]
    assert content[0]["type"] == "text"
    assert sum(c["type"] == "image" for c in content) == 3


def test_prompt_ready_after_wiring():
    assert prompt_ready() is True                       # SOP_SYSTEM_PROMPT 已填（Jones approved 2026-06-14）


def test_client_gated_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ok, missing = AnalyzeClient(api_key="").ready()
    assert ok is False and "ANTHROPIC_API_KEY" in missing


def test_analyze_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(NotImplementedError):
        AnalyzeClient(api_key="").analyze(["a.png"])


def test_ready_true_with_key_and_prompt():
    ok, _ = AnalyzeClient(api_key="sk-test").ready()    # 只 check gate，唔 call API
    assert ok is True


def test_render_5line_prefers_five_line_call():
    call = {"five_line_call": "a|||b|||c|||d|||e", "action": "IN"}
    assert render_5line(call).split("\n") == ["a", "b", "c", "d", "e"]
