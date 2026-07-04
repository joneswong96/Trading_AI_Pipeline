"""Phase 3：thesis push —— 真 Telegram（notify-only）+ console fallback。

dedup key = `thesis_id + status + version`（Jones 2026-07-04）：同 thesis 同狀態同版本唔重發；狀態變
（version+1，見 thesis_store append-only）= 新 key = 會發。卡片 = **5 行 Execution Card**，line 5 明標
`notify-only (no order)`。floor：notify-only、**唔落單**（真落單留 mt5_mirror dry-run + Phase 3 promote）；
無 token（test / 未配）→ enabled()=False → graceful console，永不炒車、零外發。
"""
from __future__ import annotations

from publish.telegram import TelegramPublisher

_EMOJI = {"ARMED": "🎯", "IN_TRADE": "✅", "WAIT": "🚫", "NO_TRADE": "⏭",
          "INVALIDATED": "❌", "EXPIRED": "⌛", "CLOSED": "🏁"}


def dedup_key(thesis: dict) -> str:
    return f"{thesis.get('thesis_id')}:{str(thesis.get('status') or '').upper()}:{thesis.get('version')}"


def _f(v):
    return "—" if v is None else v


def execution_card(thesis: dict, *, symbol: str = "XAUUSD") -> str:
    """5 行 Execution Card（SSOT 風格）。line 5 明標 notify-only（no order）。"""
    st = str(thesis.get("status") or "").upper()
    d = thesis.get("dir") or ""
    l1 = f"{_EMOJI.get(st, '📣')} {st} — {d} {symbol}".rstrip()
    l2 = (f"🎯 Entry {_f(thesis.get('entry'))}｜🛑 SL {_f(thesis.get('sl'))}"
          f"｜TP1 {_f(thesis.get('tp1'))} / TP2 {_f(thesis.get('tp2'))}")
    l3 = f"⛔ Invalidation {_f(thesis.get('invalidation'))}｜⌛ valid_until {_f(thesis.get('valid_until'))}"
    l4 = f"📝 {_f(thesis.get('rationale'))}"
    l5 = (f"🔖 {thesis.get('thesis_id')} v{_f(thesis.get('version'))}"
          f"｜wake={_f(thesis.get('wake_id'))}｜notify-only (no order)")
    return "\n".join([l1, l2, l3, l4, l5])


def card(thesis: dict) -> str:                 # 向後相容 alias
    return execution_card(thesis)


class ConsolePush:
    """in-memory dedup 嘅 console push（唔外發）。push() 回 True=印咗 / False=deduped。"""

    def __init__(self, emit=print):
        self._seen: set[str] = set()
        self._emit = emit

    def push(self, thesis: dict) -> bool:
        k = dedup_key(thesis)
        if k in self._seen:
            return False
        self._seen.add(k)
        self._emit(execution_card(thesis))
        return True


class TelegramPush:
    """真 Telegram push（notify-only）+ dedup。無 token → graceful console fallback。

    push() 回 {pushed, deduped, channel}。channel: 'telegram'（真發）/ 'console'（fallback）/ None（deduped）。
    """

    def __init__(self, publisher: TelegramPublisher | None = None, emit=print):
        self._seen: set[str] = set()
        self._pub = publisher or TelegramPublisher()
        self._emit = emit

    def push(self, thesis: dict) -> dict:
        k = dedup_key(thesis)
        if k in self._seen:
            return {"pushed": False, "deduped": True, "channel": None}
        self._seen.add(k)
        text = execution_card(thesis)
        if self._pub.enabled():
            self._pub.push(text)                      # notify-only sendMessage
            self._emit(f"[telegram sent｜notify-only] {k}")
            return {"pushed": True, "deduped": False, "channel": "telegram"}
        self._emit(text)                              # 無 token → console fallback（零外發）
        return {"pushed": True, "deduped": False, "channel": "console"}
