"""Phase 1 ingest parser tests。

Renko：TradingView strategy.order.action 出細楷 "buy"/"sell" JSON
→ event 大楷、dir 正規化（buy→long / sell→short）。
"""
from ingest.parser import parse


def test_renko_buy_lowercase():
    ev = parse('{"engine":"Renko","event":"buy","dir":"buy","tf":"1","price":2415.0}')
    assert ev.engine == "Renko"
    assert ev.event == "BUY"
    assert ev.dir == "long"


def test_renko_sell_lowercase():
    ev = parse('{"engine":"Renko","event":"sell","dir":"sell","tf":"1","price":2410.0}')
    assert ev.engine == "Renko"
    assert ev.event == "SELL"
    assert ev.dir == "short"


def test_renko_dir_from_event_when_dir_missing():
    # 冇 dir 欄位：由 event "buy" 補返 dir=long
    ev = parse('{"engine":"Renko","event":"buy","tf":"1"}')
    assert ev.engine == "Renko" and ev.event == "BUY" and ev.dir == "long"


def test_renko_partial_long_rejected():
    # partial_long 唔係有效 Renko event → 唔當 Renko（engine UNKNOWN，dir 清走）
    ev = parse('{"engine":"Renko","event":"partial_long","dir":"buy","tf":"1"}')
    assert ev.engine == "UNKNOWN"
    assert ev.dir is None


def test_renko_partial_short_rejected():
    ev = parse('{"engine":"Renko","event":"partial_short","dir":"sell","tf":"1"}')
    assert ev.engine == "UNKNOWN"
    assert ev.dir is None


def test_renko_empty_event_rejected():
    ev = parse('{"engine":"Renko","event":"","dir":"buy","tf":"1"}')
    assert ev.engine == "UNKNOWN"
    assert ev.dir is None
