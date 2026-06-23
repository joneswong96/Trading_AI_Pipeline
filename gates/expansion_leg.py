"""gates/expansion_leg.py — Expansion Leg quality（純函數，deterministic）。

純輸入形態 → 輸出 verdict。冇 I/O、冇 network、冇 vision。Claude 只讀 leg 形態
（quality: clean/choppy；length: normal/too_long/too_short），判定交呢度。

contract §E / SOP STEP 5（modifier，唔計 layer，只調 grade/size 或提示）：
  乾淨快(clean)  → 正常 / 加信心
  慢亂(choppy)   → 降級
  太長(too_long) → 唔好 fade（唔好逆住佢做）
  太短(too_short)→ skip
length 條件優先於 quality（太短照 skip、太長照 don't-fade，唔理乾唔乾淨）。
"""
from __future__ import annotations

VALID_QUALITY = ("clean", "choppy")
VALID_LENGTH = ("normal", "too_long", "too_short")


def evaluate_expansion_leg(*, quality: str = "clean", length: str = "normal") -> dict:
    """回 {verdict, grade_effect, quality, length, reason}。

    verdict ∈ {POSITIVE, DOWNGRADE, DONT_FADE, SKIP}。
    grade_effect ∈ {add_confidence, downgrade, none, skip}。
    """
    q = str(quality).lower()
    ln = str(length).lower()

    if ln == "too_short":
        verdict, effect, reason = "SKIP", "skip", "leg too short → skip"
    elif ln == "too_long":
        verdict, effect, reason = "DONT_FADE", "none", "leg too long → don't fade"
    elif q == "choppy":
        verdict, effect, reason = "DOWNGRADE", "downgrade", "slow/choppy leg → downgrade"
    else:                                # clean + normal（含未知 quality 當 clean 處理）
        verdict, effect, reason = "POSITIVE", "add_confidence", "clean/fast leg → positive"

    return {
        "verdict": verdict,
        "grade_effect": effect,
        "quality": q,
        "length": ln,
        "reason": reason,
    }
