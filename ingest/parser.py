"""Phase 1 ingest：raw webhook body -> AlertEvent。

容錯食 JSON / SNR pipe / 純文字。認得：
- SNR Pure V2.0 原生（top-level "type"：FIRE / ENTRY_PIPELINE(stage) / HALT / CLOSE）
- SNR DD30 雙線（pipe 行 + JSON 行）同淨 pipe（SNR|sym|tf|DIR|…）
- 現有手砌 schema（engine/event/dir）—— 向後兼容，原邏輯不變
- SR MTF（engine=SR / GRADE_*）；Renko 純文字（方向+box+score）
- MRF 4 engine（EXP / LIQ / MACD / WMA5S）—— 獨立 passthrough，額外欄位全入 raw

解析優先序：先 "type"（SNR native）→ MRF 4 engine → legacy engine/event → fallback pipe/text。
dir 一律 lower()。SNR 冇 close/price，用 entry 當 price（log 用，唔影響 wake）。原生冇 time
→ 用 server 收到時間。認唔到先至 UNKNOWN。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AlertEvent:
    engine: str                       # "SNR" | "SR" | "Renko" | "UNKNOWN"
    event: str                        # "FIRE" | "PRIMED" | "SCANNING" | "GRADE_A_LONG" | "BUY" ...
    dir: str | None                   # "long" | "short" | None
    grade: str | None                 # "A" | "B" | ... | None
    tf: str | None
    time: str | None                  # alert 自報時間；原生冇就 server 收到時間
    price: float | None
    raw: dict = field(default_factory=dict)   # 原始 payload + 所有額外欄位


# ENTRY_PIPELINE 唔 wake 嘅 stage（只 log）
_SNR_LOG_ONLY_STAGES = {"SCANNING", "APPROACHING", "BLOCKED"}

# MRF (Mean-Reversion Fade) 4 個新 engine —— 由 TradingView alert() 直送 JSON
_MRF_ENGINES = {"EXP", "LIQ", "MACD", "WMA5S"}


def parse(body: str) -> AlertEvent:
    """raw body -> AlertEvent。成段 JSON → SNR pipe/DD30 → Renko 文字。"""
    body = (body or "").strip()
    payload = _try_json(body)
    if isinstance(payload, dict):
        return _parse_json(payload)
    snr = _parse_snr_pipe(body)
    if snr is not None:
        return snr
    return _parse_text(body)


def _parse_json(p: dict) -> AlertEvent:
    """單段 JSON：SNR native（top-level type）→ MRF 4 engine → legacy engine/event。"""
    if p.get("type"):
        ev = _parse_snr_native(p)
        if ev is not None:
            return ev
    mrf = _parse_mrf_json(p)
    if mrf is not None:
        return mrf
    return _parse_legacy_json(p)


def _parse_mrf_json(p: dict) -> AlertEvent | None:
    """MRF 4 engine（EXP / LIQ / MACD / WMA5S）獨立 passthrough。

    唔行 SR/Renko 分支，避免撞到既有正規化；額外欄位（rangeHi/rangeLo/grade/side/
    level/touches/sweeps/exec/htf…）原封不動放喺 raw，交俾 trigger 判 fade。
    ts 用 server 收到時間（原生 payload 冇自報 time）。認唔到 engine 回 None。
    """
    eng = str(p.get("engine") or "").strip()
    if eng.upper() not in _MRF_ENGINES:
        return None
    return AlertEvent(
        engine=eng,                              # 保留 vendor casing（EXP/LIQ/MACD/WMA5S）
        event=str(p.get("event") or "").strip() or "UNKNOWN",
        dir=_norm_dir(p.get("dir")),             # 原始 signal 方向；fade 由 trigger 反推
        grade=_str_or_none(p.get("grade")),      # EXP "CLEAN" 等，原樣保留
        tf=_str_or_none(p.get("tf")),
        time=_now_iso(),                         # ts = server receive time
        price=_f(p.get("price")),
        raw=p,                                   # 全部額外欄位原封不動
    )


def _parse_snr_native(p: dict) -> AlertEvent | None:
    """SNR Pure V2.0 原生（top-level "type"）。認唔到 type 回 None，留俾 legacy。"""
    t = str(p.get("type") or "").strip().upper()
    if not t:
        return None
    dir_ = _norm_dir(p.get("dir"))
    price = _f(p.get("entry"))   # SNR 冇 close/price，用 entry 當 price

    if t == "FIRE":
        event = "FIRE"
    elif t == "ENTRY_PIPELINE":
        stage = str(p.get("stage") or "").strip().upper()
        if stage == "FIRE":
            event = "FIRE"
        elif stage == "PRIMED":
            event, dir_, price = "PRIMED", None, None   # PRIMED payload 冇 dir/entry
        elif stage in _SNR_LOG_ONLY_STAGES:
            event = stage
        elif stage:
            event = stage          # 未知 stage：保守當 log-only
        else:
            return None            # ENTRY_PIPELINE 但無 stage → 唔當 native
    elif t == "HALT":
        event = "HALT"
    elif t == "CLOSE":
        event = "CLOSE"
    else:
        return None                # 有 type 但唔識 → 俾 legacy 試

    return AlertEvent(
        engine="SNR",
        event=event,
        dir=dir_,
        grade=None,
        tf=_str_or_none(p.get("tf")),
        time=_str_or_none(p.get("time")) or _now_iso(),
        price=price,
        raw=p,
    )


def _parse_snr_pipe(body: str) -> AlertEvent | None:
    """SNR DD30 雙線（pipe 行 + JSON 行）或淨 pipe（SNR|sym|tf|DIR|…）。"""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    pipe_line = next((ln for ln in lines if ln.upper().startswith("SNR|")), None)
    json_line = next((ln for ln in lines if ln.startswith("{")), None)

    # B-1：有 JSON 行（DD30 雙線）
    if json_line is not None:
        j = _try_json(json_line)
        if isinstance(j, dict):
            if j.get("type"):                       # JSON 本身就係 native
                ev = _parse_snr_native(j)
                if ev is not None:
                    if pipe_line:
                        ev.raw = {"pipe": pipe_line, **j}
                    return ev
            # 冇 type 但有 sym+dir+entry，且有 SNR| pipe 行 → FIRE
            if pipe_line is not None and all(k in j for k in ("sym", "dir", "entry")):
                return AlertEvent(
                    engine="SNR", event="FIRE",
                    dir=_norm_dir(j.get("dir")), grade=None,
                    tf=_str_or_none(j.get("tf")),
                    time=_str_or_none(j.get("time")) or _now_iso(),
                    price=_f(j.get("entry")),
                    raw={"pipe": pipe_line, **j},
                )

    # B-2：淨 pipe（SNR|sym|tf|DIR|…）
    if pipe_line is not None:
        parts = [x.strip() for x in pipe_line.split("|")]
        if len(parts) >= 4 and parts[0].upper() == "SNR":
            return AlertEvent(
                engine="SNR", event="FIRE",
                dir=_norm_dir(parts[3]), grade=None,
                tf=_str_or_none(parts[2]),
                time=_now_iso(), price=None,
                raw={"pipe": pipe_line, "parts": parts},
            )
    return None


def _parse_legacy_json(p: dict) -> AlertEvent:
    """現有手砌 schema（engine/event/dir）+ SR。向後兼容，原邏輯不變。"""
    engine = str(p.get("engine") or "").strip()
    eng_u = engine.upper()
    event = str(p.get("event") or "").strip()
    dir_ = _norm_dir(p.get("dir"))
    grade = p.get("grade")
    grade = (str(grade).strip().upper() or None) if grade is not None else None

    # SR：由 event 推 dir + grade（GRADE_A_LONG / GRADE_B_SHORT …）
    if eng_u == "SR" or event.upper().startswith("GRADE_"):
        engine = engine or "SR"
        m = re.search(r"GRADE_([A-Z])", event.upper())
        if m and not grade:
            grade = m.group(1)
        if dir_ is None:
            dir_ = _dir_from_text(event)

    # SNR：dir 無就由 entry/sl 推（entry > sl = long）
    if eng_u == "SNR" and dir_ is None:
        dir_ = _dir_from_entry_sl(p)

    # Renko：TradingView strategy.order.action 出細楷 "buy"/"sell"
    # 只認 buy/sell（大細楷皆可）→ event 大楷（BUY/SELL）、dir 缺就由 event 補。
    # partial_long / partial_short / 空 等其他值 → 唔當有效 Renko alert，回 UNKNOWN
    # （engine=UNKNOWN + dir=None，免被當 Renko 計入 resonance / wake）。
    if eng_u == "RENKO":
        if event.lower() not in ("buy", "sell"):
            return AlertEvent(
                engine="UNKNOWN", event=event or "UNKNOWN", dir=None, grade=None,
                tf=_str_or_none(p.get("tf")), time=_str_or_none(p.get("time")),
                price=_f(p.get("price")), raw=p)
        event = event.upper()
        if dir_ is None:
            dir_ = _dir_from_text(event)

    # 兜底：dir 仍無 → 試由 event 文字推
    if dir_ is None:
        dir_ = _dir_from_text(event)

    return AlertEvent(
        engine=engine or "UNKNOWN",
        event=event or "UNKNOWN",
        dir=dir_,
        grade=grade,
        tf=_str_or_none(p.get("tf")),
        time=_str_or_none(p.get("time")),
        price=_f(p.get("price")),
        raw=p,
    )


def _parse_text(body: str) -> AlertEvent:
    """Renko 純文字：方向 + box + score（容錯抽欄位）。"""
    dir_ = _dir_from_text(body)
    box = _search_num(r"box[=:\s]+([\d.]+)", body)
    score = _search_num(r"score[=:\s]+([\d.]+)", body)
    tf = _search_str(r"tf[=:\s]+(\w+)", body)
    price = _search_num(r"price[=:\s]+([\d.]+)", body)
    if price is None:
        price = box   # Renko：無明價就用 box 價
    event = {"long": "BUY", "short": "SELL"}.get(dir_, "RENKO")
    return AlertEvent(
        engine="Renko",
        event=event,
        dir=dir_,
        grade=None,
        tf=tf,
        time=None,
        price=price,
        raw={"text": body, "box": box, "score": score, "tf": tf},
    )


# ---- helpers ----

def _try_json(s: str):
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _str_or_none(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _norm_dir(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"long", "buy", "bull", "up"}:
        return "long"
    if s in {"short", "sell", "bear", "down"}:
        return "short"
    return s or None


def _dir_from_text(s: str) -> str | None:
    # 把 _ / 等非字母當分隔（"GRADE_A_LONG" → "grade a long"），\b 先襯得到 long
    s = re.sub(r"[^a-z]+", " ", (s or "").lower())
    if re.search(r"\b(buy|long|bull)\b", s):
        return "long"
    if re.search(r"\b(sell|short|bear)\b", s):
        return "short"
    return None


def _dir_from_entry_sl(p: dict) -> str | None:
    entry, sl = _f(p.get("entry")), _f(p.get("sl"))
    if entry is None or sl is None:
        return None
    if entry > sl:
        return "long"
    if entry < sl:
        return "short"
    return None


def _search_num(pat: str, s: str) -> float | None:
    m = re.search(pat, s, re.I)
    return _f(m.group(1)) if m else None


def _search_str(pat: str, s: str) -> str | None:
    m = re.search(pat, s, re.I)
    return m.group(1) if m else None
