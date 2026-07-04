"""Phase 3 scaffold：thesis push —— console **notify-only**（print 卡片），**未接真 Telegram**。

dedup key = `thesis_id + status + version`（Jones 2026-07-04）：同一 thesis 同狀態同版本唔重複 push；
狀態變（version+1，見 thesis_store append-only）= 新 key = 會 push。floor：notify-only、無 API key、
唔連任何外部 service（真 Telegram wiring 留 Phase 3 promote）。
"""
from __future__ import annotations


def dedup_key(thesis: dict) -> str:
    return f"{thesis.get('thesis_id')}:{str(thesis.get('status') or '').upper()}:{thesis.get('version')}"


def card(thesis: dict) -> str:
    """人睇卡片（純字串，唔送出去）。"""
    st = str(thesis.get("status") or "").upper()
    lines = [f"📣 THESIS {thesis.get('thesis_id')} v{thesis.get('version')} — {st}"]
    d = thesis.get("dir")
    if d:
        lines.append(f"方向：{d}")
    if thesis.get("entry") is not None:
        lines.append(f"Entry {thesis.get('entry')}｜SL {thesis.get('sl')}｜"
                     f"TP1 {thesis.get('tp1')}｜TP2 {thesis.get('tp2')}")
    if thesis.get("invalidation") is not None:
        lines.append(f"invalidation：{thesis.get('invalidation')}")
    if thesis.get("rationale"):
        lines.append(f"理由：{thesis.get('rationale')}")
    return "\n".join(lines)


class ConsolePush:
    """in-memory dedup 嘅 console push。push() 回 True=印咗 / False=deduped。"""

    def __init__(self, emit=print):
        self._seen: set[str] = set()
        self._emit = emit

    def push(self, thesis: dict) -> bool:
        k = dedup_key(thesis)
        if k in self._seen:
            return False
        self._seen.add(k)
        self._emit(card(thesis))
        return True
