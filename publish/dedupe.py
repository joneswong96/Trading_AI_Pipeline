"""Step 5：推送 dedupe —— deterministic Python，唔靠 LLM（核心原則 + 推送政策）。

推送政策（SPEC.md「推送政策」）：只有狀態有變先 push，五個觸發：
  1 action 變（IN／WAIT／SKIP）  2 grade 變  3 trigger 價變
  4 ANT plan 新出或失效（has_ant 轉態）  5 alert 價被掂（price 由上一 cycle 行到掂 alert）
同一 plan 冇變 → 唔 push，只寫 log。

對比對象：今次 call 嘅 features vs **上一個 pushed** call 嘅 features（call_writer.features 出嘅 dict）。
trigger 5 要 price 資訊：用上一 cycle 價 → 今 cycle 價，睇有冇行過上一個 pushed call 設嘅 alert。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PushDecision:
    push: bool
    reason: str
    fired: list[str] = field(default_factory=list)   # 邊幾個觸發 fire 咗


def _alert_crossed(alerts, prev_price, cur_price):
    """price 由 prev → cur 之間有冇行過（掂到）任何一個 alert。回 alert 值 / None。"""
    if not alerts or prev_price is None or cur_price is None:
        return None
    lo, hi = sorted((prev_price, cur_price))
    for a in alerts:
        if lo <= a <= hi:
            return a
    return None


def should_push(prev: dict | None, cur: dict, *,
                prev_price: float | None = None,
                cur_price: float | None = None) -> PushDecision:
    """今次 call 使唔使 push。prev = 上一個 pushed call 嘅 features（None = 未 push 過）。"""
    if prev is None:
        return PushDecision(True, "first pushed call（冇上一個 pushed 基準）", ["first"])

    fired: list[str] = []
    if cur.get("action") != prev.get("action"):
        fired.append(f"action {prev.get('action')}→{cur.get('action')}")
    if cur.get("grade") != prev.get("grade"):
        fired.append(f"grade {prev.get('grade')}→{cur.get('grade')}")
    if cur.get("trigger") != prev.get("trigger"):
        fired.append(f"trigger {prev.get('trigger')}→{cur.get('trigger')}")
    if bool(cur.get("has_ant")) != bool(prev.get("has_ant")):
        fired.append("ANT 新出/失效")

    crossed = _alert_crossed(prev.get("alerts"), prev_price, cur_price)
    if crossed is not None:
        fired.append(f"alert {crossed} 被掂")

    if fired:
        return PushDecision(True, "狀態有變：" + "；".join(fired), fired)
    return PushDecision(False, "no_state_change（plan 冇變）→ 只寫 log，唔 push", [])
