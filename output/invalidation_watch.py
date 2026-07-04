"""Phase 3：invalidation watch —— 閉環 MVP。

read-only poll 價源（**備路 9333 quote/OHLC；9222 零接觸**）→ 價穿 active thesis invalidation →
emit 一筆 INVALIDATION event（`source=SYSTEM`）POST 去 /alert → trigger.should_wake 見 active thesis
+ invalidation → **break cooldown WAKE**。**只 emit event，唔改單、唔落單、唔行動**（真正 re-analyze /
持倉調整由人手 /analyze）。judge()/watch() 保留做純判斷 + stub 顯示。

price_source / post_alert / store 全部可注入 → table-driven testable、9222 零掂、零外發。
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


# ── 閉環 MVP：poll 價 → 價穿 → emit INVALIDATION event → /alert ──────────────────

def build_invalidation_payload(active_thesis: dict, price) -> dict:
    """砌 SYSTEM INVALIDATION alert payload（parser legacy 路認得；trigger 當 invalidation break）。"""
    return {
        "engine": "SYSTEM",
        "event": "INVALIDATION",
        "source": "SYSTEM",
        "dir": active_thesis.get("dir"),
        "price": price,
        "thesis_id": active_thesis.get("thesis_id"),
        "invalidation": active_thesis.get("invalidation"),
    }


def _probe_event(active_thesis, price):
    """用當前價砌一個 probe event 交 judge 判價穿（唔入庫，純判斷）。"""
    from ingest.parser import AlertEvent
    return AlertEvent("SYSTEM", "PRICE_PROBE", active_thesis.get("dir"), None, None,
                      None, price, {})


def poll_once(price_source, post_alert, *, store=None, now=None, emit=print) -> dict:
    """一個 poll cycle（read-only）：
    active thesis → price_source() 攞現價 → 價穿 invalidation → post_alert(payload) 出 SYSTEM
    INVALIDATION event。**只 emit，唔行動。** 回 summary dict。

    price_source: () -> float（備路 9333 quote/OHLC，9222 零掂）。
    post_alert:   (payload:dict) -> any（真線 = POST /alert；test = inject）。
    store:        ThesisStore（讀 active thesis）；缺 → 真 store。
    """
    from ingest.thesis_store import ThesisStore
    store = store or ThesisStore()
    active = store.get_active(now)
    if not active:
        emit("[INVAL-WATCH] 無 active thesis → skip poll")
        return {"active": None, "invalidated": False}

    price = price_source()
    res = judge(active, _probe_event(active, price))
    tid = active.get("thesis_id")
    if not res["would_invalidate"]:
        emit(f"[INVAL-WATCH] thesis={tid} price={price} → intact（{res['reason']}）")
        return {"active": tid, "price": price, "invalidated": False}

    payload = build_invalidation_payload(active, price)
    posted = post_alert(payload)
    emit(f"[INVAL-WATCH] thesis={tid} price={price} 價穿 invalidation → emit SYSTEM "
         f"INVALIDATION → /alert（{res['reason']}）；只 emit event，唔行動")
    return {"active": tid, "price": price, "invalidated": True, "posted": posted}
