"""Phase 3 scaffold：MT5 mirror —— **DRY-RUN only**，log 擬似落單，**永不連真 broker**。

floor（CLAUDE.md non-negotiable）：本 repo 永不接 broker API（M3 先講、要 Jones 批）。呢度只由 thesis
砌一張擬似 order dict + log，`dry_run:True` 寫死，冇任何 network / broker call。只 actionable
（ARMED/IN_TRADE）先出 order；WAIT/NO_TRADE/其他 → 唔落（回 None）。
"""
from __future__ import annotations

_ACTIONABLE = {"ARMED", "IN_TRADE"}
_SIDE = {"LONG": "BUY", "SHORT": "SELL"}


def build_order(thesis: dict, *, symbol: str = "XAUUSD", volume: float = 0.01) -> dict | None:
    """thesis → 擬似 MT5 order（dry-run）。非 actionable → None。"""
    st = str(thesis.get("status") or "").upper()
    if st not in _ACTIONABLE:
        return None
    side = _SIDE.get(str(thesis.get("dir") or "").upper())
    if side is None:
        return None
    return {
        "dry_run": True,                      # 硬寫死：永不真落
        "symbol": symbol,
        "side": side,
        "volume": volume,
        "entry": thesis.get("entry"),
        "sl": thesis.get("sl"),
        "tp": thesis.get("tp1"),
        "thesis_id": thesis.get("thesis_id"),
        "version": thesis.get("version"),
        "status": st,
    }


def mirror(thesis: dict, *, emit=print, **kw) -> dict | None:
    """log 擬似落單（唔連 broker）。回 order dict（None = 冇落）。"""
    order = build_order(thesis, **kw)
    if order is None:
        emit(f"[MT5 DRY-RUN] thesis {thesis.get('thesis_id')} status="
             f"{thesis.get('status')} → 唔落單（非 actionable）")
        return None
    emit(f"[MT5 DRY-RUN] 擬似落單 {order['side']} {order['symbol']} vol={order['volume']} "
         f"@ {order['entry']} SL={order['sl']} TP={order['tp']}（thesis {order['thesis_id']} "
         f"v{order['version']}）— 未連真 broker")
    return order
