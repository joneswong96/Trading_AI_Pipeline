"""tests/test_output_scaffold.py — Phase 3 scaffold（console push dedup / MT5 dry-run / inval watch stub）。

全 table-driven、零外部 call（notify-only、無 broker、無 API key）。
"""
from datetime import datetime, timezone

from ingest.parser import AlertEvent
from output import invalidation_watch as iw
from output import mt5_mirror as mm
from output.telegram_push import ConsolePush, card, dedup_key


def _th(status="ARMED", version=1, dir="Long", invalidation=4100, tid="thesis-1"):
    return {"thesis_id": tid, "version": version, "status": status, "dir": dir,
            "entry": 4150, "sl": 4100, "tp1": 4200, "tp2": 4250,
            "invalidation": invalidation, "rationale": "r"}


def _ev(engine="SNR", event="FIRE", dir="long", price=None):
    return AlertEvent(engine, event, dir, None, None, None, price, {})


# ── telegram_push：console notify-only + dedup key ───────────────────────────────
def test_dedup_key_shape():
    assert dedup_key(_th(status="ARMED", version=2)) == "thesis-1:ARMED:2"


def test_push_dedups_same_key():
    out = []
    p = ConsolePush(emit=out.append)
    assert p.push(_th(status="ARMED", version=1)) is True
    assert p.push(_th(status="ARMED", version=1)) is False    # 同 key → deduped
    assert len(out) == 1


def test_push_new_version_pushes():
    out = []
    p = ConsolePush(emit=out.append)
    p.push(_th(status="ARMED", version=1))
    assert p.push(_th(status="IN_TRADE", version=2)) is True   # 狀態變 = 新 key
    assert len(out) == 2


def test_card_contains_core_fields():
    c = card(_th(status="ARMED", version=1))
    assert "thesis-1" in c and "ARMED" in c and "4150" in c


# ── mt5_mirror：dry-run only ──────────────────────────────────────────────────────
def test_mirror_actionable_dry_run():
    out = []
    order = mm.mirror(_th(status="ARMED", dir="Long"), emit=out.append)
    assert order["dry_run"] is True and order["side"] == "BUY"
    assert order["symbol"] == "XAUUSD" and "DRY-RUN" in out[0]


def test_mirror_short_maps_sell():
    assert mm.build_order(_th(status="IN_TRADE", dir="Short"))["side"] == "SELL"


def test_mirror_non_actionable_no_order():
    out = []
    assert mm.mirror(_th(status="WAIT"), emit=out.append) is None
    assert "唔落單" in out[0]


def test_mirror_no_dir_none():
    assert mm.build_order(_th(status="ARMED", dir=None)) is None


# ── invalidation_watch：stub 判斷，唔行動 ────────────────────────────────────────
def test_watch_explicit_invalidation():
    r = iw.judge(_th(), _ev(event="INVALIDATED"))
    assert r["would_invalidate"] is True


def test_watch_price_break_long():
    r = iw.judge(_th(dir="Long", invalidation=4100), _ev(event="WEAKEN", price=4095))
    assert r["would_invalidate"] is True


def test_watch_intact():
    r = iw.judge(_th(dir="Long", invalidation=4100), _ev(event="FIRE", price=4150))
    assert r["would_invalidate"] is False


def test_watch_no_thesis():
    assert iw.judge(None, _ev())["would_invalidate"] is False


def test_watch_prints_no_action():
    out = []
    iw.watch(_th(), _ev(event="INVALIDATED"), emit=out.append)
    assert "唔行動" in out[0] and "WOULD-INVALIDATE" in out[0]
