"""Phase 1 ingest：觸發規則 + cooldown -> wake decision（deterministic Python）。

規則（Phase 1 SPEC）：
1. SNR FIRE / PRIMED → 即刻 wake。
2. 近 5 分鐘內 SR(grade) + Renko 同向 ≥2 共振 → wake。
3. cooldown：同 engine + 同 dir(+ SNR 線 if payload 有) 15 分鐘內唔重複 wake，
   除非 invalidation 被破（thesis 被推翻一定要叫醒）。
4. noise guard：唔係上面兩種 confirm/refute → 只 log 唔 wake。

**唔 reuse publish/dedupe.py**：嗰個係 Phase 2 call-plan 級（比 action/grade/trigger
features），唔啱 raw-alert 層。呢度自己查 alert_events 做 cooldown。

cooldown 近似：alert_events 唔存「有冇 wake 過」flag（schema 跟 SPEC 鎖死），所以用
「同 engine+dir(+line) 喺 15 分鐘內有無較早 alert」做代理——對 SNR 重複 FIRE 嘅抑制
完全準；resonance 路可能略保守，M0 可接受。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SNR_WAKE_EVENTS = {"FIRE", "PRIMED"}
COOLDOWN_MIN = 15
RESONANCE_WINDOW_MIN = 5
_INVALIDATION_EVENTS = {"INVALIDATED", "INVALIDATION", "BREAK", "BROKEN"}


@dataclass
class WakeDecision:
    wake: bool
    reason: str


def evaluate(event, recent: list[dict]) -> WakeDecision:
    """event = 當前 AlertEvent；recent = cooldown 窗內較早 alert_events（dict，已剔走當前）。"""
    invalidated = _is_invalidation(event)
    candidate, why = _wake_candidate(event, recent, invalidated)
    if not candidate:
        return WakeDecision(False, why)
    if invalidated:
        return WakeDecision(True, f"{why}；invalidation 被破 → bypass cooldown")
    cd = _in_cooldown(event, recent)
    if cd:
        return WakeDecision(False, f"cooldown：{cd}（15 分鐘內已 wake，無 invalidation）")
    return WakeDecision(True, why)


def _wake_candidate(event, recent, invalidated):
    eng, ev = _u(event.engine), _u(event.event)
    if eng == "SNR" and ev in SNR_WAKE_EVENTS:
        return True, f"SNR {ev} → 即刻 wake"
    if invalidated:
        return True, f"{eng} {ev} invalidation（thesis 被推翻）"
    res = _resonance(event, recent)
    if res:
        return True, res
    return False, "noise_guard：非 SNR FIRE/PRIMED、亦無 SR+Renko 共振 → 只 log"


def _resonance(event, recent):
    """近 5 分鐘 SR(grade) + Renko 同向 → 2 源共振。當前 event 計埋一份。"""
    d = _u(event.dir)
    if d not in {"LONG", "SHORT"}:
        return None
    win = _within(recent, RESONANCE_WINDOW_MIN)
    sr = (_u(event.engine) == "SR" and bool(event.grade)) or any(
        _u(r["engine"]) == "SR" and r.get("grade") and _u(r["dir"]) == d for r in win)
    renko = (_u(event.engine) == "RENKO") or any(
        _u(r["engine"]) == "RENKO" and _u(r["dir"]) == d for r in win)
    if sr and renko:
        return f"5 分鐘內 SR(grade)+Renko 同向（{d.lower()}）共振 → wake"
    return None


def _in_cooldown(event, recent):
    eng, d = _u(event.engine), _u(event.dir)
    line = _snr_line(event.raw or {})
    for r in _within(recent, COOLDOWN_MIN):
        if _u(r["engine"]) != eng:
            continue
        if d and _u(r["dir"]) != d:
            continue
        rline = _snr_line(_loads(r.get("raw")))
        if line and rline and line != rline:   # 兩邊都有線 id 但唔同條 → 唔當重複
            continue
        return f"同 engine={eng}+dir={event.dir}" + (f"+line={line}" if line else "")
    return None


# ---- helpers ----

def _u(s) -> str:
    return (s or "").strip().upper()


def _loads(s) -> dict:
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s) if s else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _snr_line(raw: dict) -> str | None:
    for k in ("line", "snr_line", "line_id", "level"):
        v = raw.get(k)
        if v is not None:
            return str(v)
    return None


def _is_invalidation(event) -> bool:
    raw = event.raw or {}
    if raw.get("invalidation_broken") or raw.get("invalidated"):
        return True
    return _u(event.event) in _INVALIDATION_EVENTS


def _within(recent, minutes):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    out = []
    for r in recent:
        ts = _parse_ts(r.get("ts"))
        if ts is not None and ts >= cutoff:
            out.append(r)
    return out


def _parse_ts(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
