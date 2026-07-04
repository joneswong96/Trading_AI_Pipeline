"""Phase 3 scaffold：invalidation watch —— **STUB**，讀 active thesis + 最新 event，print 判斷，
**唔行動**（唔改 thesis、唔 push、唔落單）。

判斷邏輯對齊 trigger._event_invalidates（explicit INVALIDATION event 或價穿 invalidation level），
但呢度只**觀察 + print**；真正 arm/invalidate 落 thesis + 觸發 re-analyze 留 Phase 3 promote。
"""
from __future__ import annotations

_INVALIDATION_EVENTS = {"INVALIDATED", "INVALIDATION", "BREAK", "BROKEN"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def judge(active_thesis: dict | None, latest_event) -> dict:
    """回 {would_invalidate: bool, reason}。無 active thesis / 無 event → would_invalidate False。"""
    if not isinstance(active_thesis, dict):
        return {"would_invalidate": False, "reason": "無 active thesis"}
    if latest_event is None:
        return {"would_invalidate": False, "reason": "無最新 event"}

    ev = str(getattr(latest_event, "event", "") or "").strip().upper()
    if ev in _INVALIDATION_EVENTS:
        return {"would_invalidate": True, "reason": f"explicit invalidation event（{ev}）"}

    lvl = _num(active_thesis.get("invalidation"))
    price = _num(getattr(latest_event, "price", None))
    d = str(active_thesis.get("dir") or "").upper()
    if lvl is not None and price is not None:
        if d == "LONG" and price <= lvl:
            return {"would_invalidate": True,
                    "reason": f"long thesis 跌穿 invalidation（{price}≤{lvl}）"}
        if d == "SHORT" and price >= lvl:
            return {"would_invalidate": True,
                    "reason": f"short thesis 升穿 invalidation（{price}≥{lvl}）"}
    return {"would_invalidate": False, "reason": "未破 invalidation"}


def watch(active_thesis, latest_event, *, emit=print) -> dict:
    """print 判斷,唔行動。回 judge() 結果。"""
    res = judge(active_thesis, latest_event)
    tid = active_thesis.get("thesis_id") if isinstance(active_thesis, dict) else None
    flag = "⚠️ WOULD-INVALIDATE" if res["would_invalidate"] else "✅ intact"
    emit(f"[INVAL-WATCH stub] thesis={tid} → {flag}｜{res['reason']}（唔行動）")
    return res
