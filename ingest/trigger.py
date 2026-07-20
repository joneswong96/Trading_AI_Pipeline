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

# ---- MRF (Mean-Reversion Fade) config（初值未校準，集中一格方便日後 tune）----
# window   = EXP+LIQ 對齊 lookback（成對就係一次 wake 機會）。
# cooldown = 同 fade 方向重複 wake 抑制窗（2026-07-03 Jones 批 15→3）。
# veto     = EXP TOO_LONG 抑制該 fade 方向嘅窗（獨立於 cooldown，唔跟 cooldown 縮）。
MRF_CONFIG = {
    "window_min": 30,
    "cooldown_min": 3,
    "veto_min": 15,
}
MRF_WINDOW_MIN = MRF_CONFIG["window_min"]
MRF_COOLDOWN_MIN = MRF_CONFIG["cooldown_min"]
MRF_VETO_MIN = MRF_CONFIG["veto_min"]
MRF_ENGINES = {"EXP", "LIQ", "MACD", "WMA5S"}
# MACD strengthener events（同 fade 方向就 confirm；dir 已係 fade 方向，唔反）。永不單獨 wake。
_MACD_CONFIRM_EVENTS = {"FLOW_FLIP", "WEAKEN"}

# server 回望要覆蓋最闊嗰個窗（MRF 30 分 > 既有 cooldown 15 分）。
LOOKBACK_MIN = max(COOLDOWN_MIN, MRF_WINDOW_MIN)


@dataclass
class WakeDecision:
    wake: bool
    reason: str


def evaluate(event, recent: list[dict], recent_wakes: list[dict] | None = None) -> WakeDecision:
    """event = 當前 AlertEvent；recent = cooldown 窗內較早 alert_events（dict，已剔走當前）。
    recent_wakes = 上次**真 wake**（wake_log，wake=True）記錄，SNR/legacy cooldown 用佢錨定
    （2026-07-07 fix：log-only alert 唔再續命 cooldown）。缺 → []（保守：無真 wake = 唔 cooldown）。"""
    recent_wakes = recent_wakes or []
    if _telemetry_only(event):
        return WakeDecision(False, "compatibility adapter telemetry-only → 只 log、永不 wake")
    # MRF (Mean-Reversion Fade) —— 獨立規則，自己嘅 30 分窗 + 15 分 cooldown（自成一路，唔用 recent_wakes）。
    # 只食 EXP/LIQ/MACD/WMA5S；其他 engine 回 None，落既有 SNR/SR/Renko 規則。
    mrf = _mrf_decision(event, recent)
    if mrf is not None:
        return mrf

    invalidated = _is_invalidation(event)
    candidate, why = _wake_candidate(event, recent, invalidated)
    if not candidate:
        return WakeDecision(False, why)
    if invalidated:
        return WakeDecision(True, f"{why}；invalidation 被破 → bypass cooldown")
    cd = _in_cooldown(event, recent_wakes)
    if cd:
        return WakeDecision(False, f"cooldown：{cd}（{COOLDOWN_MIN} 分鐘內已 wake，無 invalidation）")
    return WakeDecision(True, why)


# ---- Phase 1.5：thesis-aware wake gate ----

_THESIS_ACTIVE_STATUS = {"ARMED", "IN_TRADE"}


def should_wake(recent_events, active_thesis, new_event, now=None, recent_wakes=None):
    """Phase 1.5 thesis-aware gate → (wake: bool, reason: str)。recent_wakes = 真 wake 記錄，
    傳落 evaluate 做 SNR/legacy cooldown 錨定（2026-07-07 fix）。

    有 active thesis（status∈{ARMED,IN_TRADE}、now<valid_until、未 invalidated）：
      - new_event 破 thesis invalidation（explicit INVALIDATION event 或價穿 invalidation level）
        → (True, …bypass cooldown WAKE)；
      - 其他 engine alert → (False, …active thesis 只 log，唔重複 WAKE)。
    無 active thesis（或 thesis 已過期/非 ARMED/IN_TRADE/已 invalidated）
      → 委派現有 `evaluate`（MRF/SNR/共振/cooldown 行為 byte-identical，零 regress）。
    """
    now = now or datetime.now(timezone.utc)
    if _telemetry_only(new_event):
        return False, "compatibility adapter telemetry-only → 只 log、永不 wake"
    if _thesis_active(active_thesis, now):
        tid = active_thesis.get("thesis_id") or "?"
        st = _u(active_thesis.get("status"))
        if _event_invalidates(new_event, active_thesis):
            return True, f"active thesis {tid}（{st}）invalidation 被破 → bypass cooldown WAKE"
        return False, (f"active thesis {tid}（{st}，未過 valid_until/未破）"
                       f"→ engine alert 只 log，唔重複 WAKE")
    d = evaluate(new_event, recent_events, recent_wakes)
    return d.wake, d.reason


def _thesis_active(thesis, now) -> bool:
    """thesis 係咪仍然 active（會 gate 住普通 engine wake）。缺/非 dict → False。"""
    if not isinstance(thesis, dict):
        return False
    if _u(thesis.get("status")) not in _THESIS_ACTIVE_STATUS:
        return False
    if thesis.get("invalidated"):
        return False
    vu = _parse_ts(thesis.get("valid_until"))
    if vu is not None and now >= vu:            # 過期 → 唔再 active
        return False
    return True


def _event_invalidates(new_event, thesis) -> bool:
    """new_event 係咪推翻緊 active thesis：explicit invalidation event，或價穿 invalidation level。"""
    if _is_invalidation(new_event):
        return True
    lvl = _num(thesis.get("invalidation"))
    price = _num(getattr(new_event, "price", None))
    if lvl is None or price is None:
        return False
    d = _u(thesis.get("dir"))
    if d == "LONG" and price <= lvl:            # long thesis 跌穿 invalidation
        return True
    if d == "SHORT" and price >= lvl:           # short thesis 升穿 invalidation
        return True
    return False


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


def _in_cooldown(event, recent_wakes):
    """由上次**真 wake**（wake_log，wake=True）計 COOLDOWN_MIN 分鐘（2026-07-07 fix）。

    舊 proxy「同 engine 15 分鐘內有無較早 alert」會被 SNR log-only（SCANNING/APPROACHING/BLOCKED）
    不斷續命，實鎖幾個鐘、擋死真 FIRE/PRIMED（2026-07-06 live bug）。改為只認真 wake 記錄——log-only /
    被擋 event 唔會入 wake_log，自然唔續命。cooldown key = engine+dir（+ SNR line if 兩邊都有）不變。
    """
    eng, d = _u(event.engine), _u(event.dir)
    line = _snr_line(event.raw or {})
    for r in _within(recent_wakes, COOLDOWN_MIN):
        if _u(r.get("engine")) != eng:
            continue
        if d and _u(r.get("dir")) != d:
            continue
        rline = r.get("line") if r.get("line") is not None else _snr_line(_loads(r.get("raw")))
        if line and rline and str(line) != str(rline):   # 兩邊都有線 id 但唔同條 → 唔當重複
            continue
        return (f"上次真 wake @ {str(r.get('ts', ''))[:19]}（engine={eng}"
                + (f"+dir={event.dir}" if d else "") + (f"+line={line}" if line else "") + "）")
    return None


# ---- MRF (Mean-Reversion Fade) ----

def _mrf_decision(event, recent) -> WakeDecision | None:
    """MRF 規則。回 WakeDecision（wake 或帶因由嘅唔 wake）；非 MRF engine 回 None。

    WAKE 條件：30 分鐘窗內，同一 fade 方向同時有 (1) EXP_UP/EXP_DOWN 同
    (2) LIQ TOUCH/SWEEP。fade 對映：EXP_UP→short、EXP_DOWN→long；LIQ ASK→short、
    BID→long。MACD FLOW_FLIP 同 fade 方向 = strengthener（macd_confirm=true，非必需）。
    EXP TOO_LONG = veto（抑制該 fade 方向 + 開 cooldown）。WMA5S = 只 log，永不 wake。
    """
    eng = _u(event.engine)
    if eng not in MRF_ENGINES:
        return None

    if eng == "WMA5S":
        return WakeDecision(False, "strategy=MRF｜WMA5S：只 log（唔計、永不 wake）")

    if eng == "EXP" and _u(event.event) == "TOO_LONG":
        vd = _too_long_veto_dir(_u(event.dir))
        return WakeDecision(
            False,
            f"strategy=MRF｜EXP TOO_LONG veto（fade={vd or 'both'}）→ 抑制 + cooldown")

    if eng == "MACD":
        return WakeDecision(
            False, "strategy=MRF｜MACD（FLOW_FLIP/WEAKEN）：strengthener only（單獨唔 wake）")

    # 到呢度：EXP_UP/EXP_DOWN 或 LIQ TOUCH/SWEEP
    fade = _fade_dir(event.engine, event.event, event.dir, event.raw)
    if fade not in ("long", "short"):
        return WakeDecision(False, "strategy=MRF｜判唔到 fade 方向 → 只 log")

    win = _within(recent, MRF_WINDOW_MIN)
    has_exp = (eng == "EXP") or _any_fade(win, "EXP", fade)
    has_liq = (eng == "LIQ") or _any_fade(win, "LIQ", fade)
    if not (has_exp and has_liq):
        return WakeDecision(
            False, f"strategy=MRF｜fade={fade} 未夠對（EXP={has_exp} LIQ={has_liq}）→ 只 log")

    if _mrf_vetoed(fade, recent):
        return WakeDecision(False, f"strategy=MRF｜fade={fade} 窗內有 EXP TOO_LONG → veto 抑制")

    if _mrf_in_cooldown(fade, recent):
        return WakeDecision(
            False, f"strategy=MRF｜fade={fade} cooldown（{MRF_COOLDOWN_MIN} 分鐘內已 wake）")

    reason = f"strategy=MRF｜EXP+LIQ 同 fade={fade}（{MRF_WINDOW_MIN} 分鐘窗）→ wake"
    grade, level = _mrf_evidence(event, win, fade)
    if grade:
        reason += f"；exp_grade={grade}"
    if level is not None:
        reason += f"；liq_level={level}"
    macd = _macd_confirm(win, fade)      # e.g. "WEAKEN@1" / "FLOW_FLIP@5"
    if macd:
        reason += f"；macd_confirm=true（{macd}）"
    return WakeDecision(True, reason)


def _mrf_evidence(event, win, fade):
    """由當前 event + 窗內配對，抽 wake message 要嘅 EXP grade 同 LIQ level。

    完成配對嘅 event 只帶一邊資料（如 current=LIQ 冇 grade），另一邊要去 win 揾返。
    """
    eng = _u(event.engine)
    raw = event.raw or {}
    grade = event.grade if eng == "EXP" else _fade_pick(win, "EXP", fade, "grade")
    level = raw.get("level") if eng == "LIQ" else _fade_pick(win, "LIQ", fade, "level")
    return grade, level


def _fade_pick(win, engine, fade, key):
    """喺 win 揾第一條同 fade 方向嘅 `engine` row，回其 `key`（先睇 raw 再睇欄）。冇 → None。"""
    eng = engine.upper()
    for r in win:
        if _u(r.get("engine")) == eng and _fade_dir_row(r) == fade:
            rawd = _loads(r.get("raw"))
            v = rawd.get(key)
            if v is None:
                v = r.get(key)
            if v is not None:
                return v
    return None


def _fade_dir(engine, event, dir_, raw) -> str | None:
    """一個 alert 對應嘅 fade 方向（long/short）。非 MRF-relevant 回 None。"""
    if isinstance(raw, dict) and raw.get("_telemetry_only") is True:
        return None
    e, ev = _u(engine), _u(event)
    if e == "EXP":
        if ev == "EXP_UP":
            return "short"
        if ev == "EXP_DOWN":
            return "long"
        return None                       # TOO_LONG 另路處理
    if e == "LIQ" and ev in ("TOUCH", "SWEEP"):
        side = _u((raw or {}).get("side"))
        if side == "ASK":
            return "short"
        if side == "BID":
            return "long"
        return None
    if e == "MACD" and ev in _MACD_CONFIRM_EVENTS:
        d = _u(dir_)                       # MACD FLOW_FLIP/WEAKEN 方向 = fade 方向（順住做，唔反）
        if d in ("LONG", "SHORT"):
            return d.lower()
    return None


def _macd_confirm(win, fade) -> str | None:
    """窗內第一條同 fade 方向嘅 MACD confirm event（FLOW_FLIP/WEAKEN）→ 回 `EVENT@tf` label。冇 → None。"""
    for r in win:
        if _u(r.get("engine")) != "MACD":
            continue
        ev = _u(r.get("event"))
        if ev in _MACD_CONFIRM_EVENTS and _fade_dir_row(r) == fade:
            tf = r.get("tf") or _loads(r.get("raw")).get("tf")
            return f"{ev}@{tf}" if tf else ev
    return None


def _fade_dir_row(r: dict) -> str | None:
    return _fade_dir(r.get("engine"), r.get("event"), r.get("dir"), _loads(r.get("raw")))


def _any_fade(win, engine, fade) -> bool:
    eng = engine.upper()
    return any(_u(r.get("engine")) == eng and _fade_dir_row(r) == fade for r in win)


def _too_long_veto_dir(move_dir) -> str | None:
    """TOO_LONG 由 move 方向反推要 veto 嘅 fade 方向；冇 dir 回 None（veto 兩邊）。"""
    d = _u(move_dir)
    if d == "LONG":
        return "short"
    if d == "SHORT":
        return "long"
    return None


def _mrf_vetoed(fade, recent) -> bool:
    """veto 窗內有 EXP TOO_LONG（同 fade 方向，或無 dir）→ 抑制。窗獨立於 cooldown。"""
    for r in _within(recent, MRF_VETO_MIN):
        if _u(r.get("engine")) == "EXP" and _u(r.get("event")) == "TOO_LONG":
            vd = _too_long_veto_dir((_loads(r.get("raw")).get("dir")) or r.get("dir"))
            if vd is None or vd == fade:
                return True
    return False


def _mrf_in_cooldown(fade, recent) -> bool:
    """任何 MRF wake（唔理 EXP 定 LIQ 觸發）都 arm 該 fade 方向嘅 cooldown。

    schema 冇「wake 過」flag，用 proxy：
      (1) wake 窗(30m)內曾成過同 fade 嘅 EXP+LIQ 對 → 代表 wake 發生過；
      (2) cooldown 窗內有較早嘅同 fade 觸發 event（EXP_UP/DOWN 或 LIQ TOUCH/SWEEP）
          → 就係上次 wake 嗰下，仲喺 cooldown 內。
    舊 bug：舊 proxy 要求 EXP 同 LIQ 兩邊都喺 cooldown 窗內；當 EXP 老出 cooldown 窗
    （但仲喺 30m wake 窗）時，LIQ-triggered 嘅重複 wake 就擋唔到。而家只要 cooldown 窗內
    有任何一邊同 fade 觸發 event 就當上次 wake 未過，唔再漏。
    """
    wake_win = _within(recent, MRF_WINDOW_MIN)
    if not (_any_fade(wake_win, "EXP", fade) and _any_fade(wake_win, "LIQ", fade)):
        return False                       # 未成過對 → 未 wake 過 → 唔 cooldown
    cd = _within(recent, MRF_COOLDOWN_MIN)
    return _any_fade(cd, "EXP", fade) or _any_fade(cd, "LIQ", fade)


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


def _telemetry_only(event) -> bool:
    raw = getattr(event, "raw", None)
    return isinstance(raw, dict) and raw.get("_telemetry_only") is True


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
