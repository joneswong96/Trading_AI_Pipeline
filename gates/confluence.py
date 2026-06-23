"""gates/confluence.py — layer-count grade（純函數，deterministic）。

純輸入數字 → 輸出 grade。冇 I/O、冇 network、冇 vision。Claude 只負責「數到幾多
confluence layer」（vision/判斷）；grade 嘅映射 + 封頂規則喺呢度 deterministic 做。

contract §F：
  layer 數：0–2 → C｜3 → B+｜4 → A｜5+ → A+
  封頂 B+：① 冇 5m/15m anchor（純 LTF stack 唔可當 B+）
           ② DXY 橫行(NEUTRAL) 或 同向(ADVERSE)（§E：grade 封頂 B+）
caller 責任（唔喺本函數）：唔好將 ICT/FVG/OB 當 layer；gate 唔過 3/4 時 MACD
alignment 唔當 layer（Anti-Failure #14）。本函數只收**已篩好嘅最終 layer 數**。
"""
from __future__ import annotations

_ORDER = ("C", "B+", "A", "A+")
_CAP = "B+"
_DXY_CAP_STATES = {"NEUTRAL", "ADVERSE"}


def _base_grade(layers: int) -> str:
    if layers >= 5:
        return "A+"
    if layers == 4:
        return "A"
    if layers == 3:
        return "B+"
    return "C"           # 0–2


def grade_from_layers(layers: int, has_5m_or_15m_anchor: bool, dxy_state: str) -> dict:
    """回 {grade, base_grade, capped, cap_reasons}。

    grade = base_grade 經封頂後嘅結果；capped = 有冇被封頂拉低。
    """
    base = _base_grade(max(0, int(layers)))
    cap_reasons: list[str] = []
    if not has_5m_or_15m_anchor:
        cap_reasons.append("no_5m_15m_anchor")
    state = (dxy_state or "").upper()
    if state in _DXY_CAP_STATES:
        cap_reasons.append(f"dxy_{state.lower()}")

    grade = base
    if cap_reasons and _ORDER.index(grade) > _ORDER.index(_CAP):
        grade = _CAP
    return {
        "grade": grade,
        "base_grade": base,
        "capped": grade != base,
        "cap_reasons": cap_reasons,
    }
