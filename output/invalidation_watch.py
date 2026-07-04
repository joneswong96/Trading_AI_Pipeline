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


# ── 常駐 daemon（每 interval 秒 poll 一次）─────────────────────────────────────────

def poll_cycle(store, price_source, post_alert, emitted: set, *, now=None, emit=print) -> dict:
    """一個 daemon cycle（injectable，unit-testable）。回 {action, ...}。

    action：'idle'（無 active thesis → **唔 poll 價**，慳資源）｜'skip_price_down'（price_source 回 None，
    9333 down/讀唔到 → skip 唔 crash）｜'intact'（未穿）｜'emitted'（價穿 + 首次 → emit SYSTEM INVALIDATION）
    ｜'dedup_skip'（同 thesis_id+version breach 已 emit 過 → 唔重轟）。emitted set 記 (thesis_id, version)。
    """
    active = store.get_active(now)
    if not active:
        return {"action": "idle"}
    price = price_source()
    if price is None:
        emit("[INVAL-WATCH daemon] 價源讀唔到（9333 down？）→ skip 呢輪，唔 mutate")
        return {"action": "skip_price_down"}
    res = judge(active, _probe_event(active, price))
    key = (active.get("thesis_id"), active.get("version"))
    if not res["would_invalidate"]:
        return {"action": "intact", "price": price}
    if key in emitted:
        return {"action": "dedup_skip", "price": price}
    emitted.add(key)
    posted = post_alert(build_invalidation_payload(active, price))
    emit(f"[INVAL-WATCH daemon] thesis={key[0]} v{key[1]} price={price} 價穿 → emit SYSTEM "
         f"INVALIDATION → /alert（首次；後續同 version 唔重 emit）")
    return {"action": "emitted", "price": price, "posted": posted, "key": key}


def _default_post_alert(url="http://localhost:8000/alert"):
    import requests
    return lambda payload: requests.post(url, json=payload, timeout=5).json()


def run_daemon(interval: float = 10, *, price_source=None, post_alert=None, store=None,
               emit=print, sleep=None, max_cycles=None) -> dict:
    """常駐 poll loop。price_source 缺 → capture.tv9333.read_price_9333（備路 9333，9222 零掂）；
    post_alert 缺 → POST localhost:8000/alert。Ctrl-C graceful shutdown。max_cycles = 測試用有限圈。"""
    import time as _time
    if price_source is None:
        from capture.tv9333 import read_price_9333
        price_source = read_price_9333
    if post_alert is None:
        post_alert = _default_post_alert()
    if store is None:
        from ingest.thesis_store import ThesisStore
        store = ThesisStore()
    sleep = sleep or _time.sleep

    emitted: set = set()
    cycles = 0
    emit(f"[INVAL-WATCH daemon] up｜interval={interval}s｜價源=9333 off1（9222 零掂）｜Ctrl-C 停")
    try:
        while max_cycles is None or cycles < max_cycles:
            try:
                poll_cycle(store, price_source, post_alert, emitted, emit=emit)
            except Exception:                       # 一輪炒車唔拖冧 daemon
                emit("[INVAL-WATCH daemon] poll cycle error（continue，唔 crash）")
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            sleep(interval)
    except KeyboardInterrupt:
        emit("[INVAL-WATCH daemon] Ctrl-C → graceful shutdown")
    return {"cycles": cycles, "emitted": len(emitted)}


def main(argv=None) -> int:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="invalidation watch daemon（notify-only，9222 零掂）")
    ap.add_argument("--daemon", action="store_true", help="常駐 poll loop")
    ap.add_argument("--interval", type=float, default=10, help="poll 間隔（秒，default 10）")
    args = ap.parse_args(argv)
    if not args.daemon:
        ap.error("要 --daemon（唯一模式；一次性 poll 用 poll_once 函數）")
    run_daemon(interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
