"""Step 3：call_writer —— 由結構化 call 砌 push 用 5 行 + 寫 features.json / call.json。

5 行 Call（CLAUDE.md Output）：
  1 結論（方向／入唔入）  2 而家做咩  3 SL·TP  4 點解（一句）  5 跟住睇邊度
完整 Output 0–4 寫入 call.json 嘅 `full`（可回放，核心原則 #3）。

純 formatting，deterministic、可離線測；唔靠 LLM、唔判 action。
缺欄位 → 該行用「—」或者跳過，唔 crash（防截圖／prompt 偶發缺值）。
"""
from __future__ import annotations

import json
from pathlib import Path

ACTION_FALLBACK = "—"


def _fmt_levels(call: dict) -> str:
    """SL·TP 行：由 levels 砌 'SL 4078.5 ｜ TP1 4066 → TP2 4057'。"""
    lv = call.get("levels", {}) or {}
    parts = []
    if lv.get("sl") is not None:
        parts.append(f"SL {lv['sl']}")
    tps = [lv.get(k) for k in ("tp1", "tp2", "tp3") if lv.get(k) is not None]
    if tps:
        parts.append("TP " + " → ".join(str(t) for t in tps))
    return " ｜ ".join(parts) if parts else ACTION_FALLBACK


def render_5line(call: dict) -> str:
    """砌 push 用 5 行。SOP prompt 直接出 `five_line_call`（||| 分隔）→ 優先用；
    否則由欄位砌（舊 schema fallback）。第一行 = action call。"""
    flc = call.get("five_line_call")
    if flc:
        return "\n".join(p.strip() for p in str(flc).split("|||"))
    action = call.get("action") or ACTION_FALLBACK
    direction = call.get("direction")
    head = f"{action}" + (f" {direction}" if direction else "")
    summary = call.get("summary")
    line1 = f"{head} — {summary}" if summary else head

    watch = call.get("watch") or []
    watch_str = "；".join(str(w) for w in watch[:2]) if watch else ACTION_FALLBACK  # ≤2 個位

    lines = [
        line1,
        call.get("now") or ACTION_FALLBACK,
        _fmt_levels(call),
        call.get("why") or ACTION_FALLBACK,
        watch_str,
    ]
    return "\n".join(lines)


def _features_of(call: dict) -> dict:
    """抽 deterministic 比較 / log 用嘅 features（dedupe 同推送政策睇呢啲）。"""
    return {
        "action": call.get("action"),
        "direction": call.get("direction"),
        "grade": call.get("grade"),
        "gate": call.get("gate"),
        "trigger": (call.get("levels", {}) or {}).get("entry"),
        "alerts": call.get("alerts", []),
        "has_ant": bool(call.get("ant")),
    }


def write_call(out_dir: str, call: dict, *, cycle_id: str | None = None) -> dict:
    """寫 features.json + call.json，回 {features, call, push} 路徑 + 5 行。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    features = _features_of(call)
    push = render_5line(call)

    (d / "features.json").write_text(
        json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "call.json").write_text(
        json.dumps(call, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "push.txt").write_text(push, encoding="utf-8")
    return {
        "features": features,
        "push": push,
        "features_path": str(d / "features.json"),
        "call_path": str(d / "call.json"),
    }
