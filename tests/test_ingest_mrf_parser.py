"""Phase 1 ingest — MRF 4 engine parser tests（EXP / LIQ / MACD / WMA5S）。

驗：4 個 payload 正常 parse 成 AlertEvent；額外欄位（rangeHi/rangeLo/side/level/
touches/sweeps/exec/htf…）原封不動入 raw；ts 用 server 收到時間。
"""
import json

from ingest.parser import parse


def test_exp_up_parsed_with_extras():
    ev = parse(json.dumps({
        "engine": "EXP", "event": "EXP_UP", "dir": "LONG", "grade": "CLEAN",
        "tf": "1", "price": 4179.6, "rangeHi": 4185.2, "rangeLo": 4162.8}))
    assert ev.engine == "EXP"
    assert ev.event == "EXP_UP"
    assert ev.dir == "long"           # 原始 signal 方向（fade 由 trigger 反推）
    assert ev.grade == "CLEAN"
    assert ev.tf == "1"
    assert ev.price == 4179.6
    assert ev.time is not None        # server receive time
    # 額外欄位原封不動
    assert ev.raw["rangeHi"] == 4185.2
    assert ev.raw["rangeLo"] == 4162.8


def test_exp_too_long_no_grade_or_range():
    ev = parse(json.dumps({"engine": "EXP", "event": "TOO_LONG", "tf": "1", "price": 4179.6}))
    assert ev.engine == "EXP"
    assert ev.event == "TOO_LONG"
    assert ev.grade is None
    assert "rangeHi" not in ev.raw and "rangeLo" not in ev.raw


def test_liq_touch_parsed_with_extras():
    ev = parse(json.dumps({
        "engine": "LIQ", "event": "TOUCH", "side": "ASK", "dir": "SHORT",
        "tf": "1", "price": 4179.6, "level": 4180.1, "touches": 2}))
    assert ev.engine == "LIQ"
    assert ev.event == "TOUCH"
    assert ev.dir == "short"
    assert ev.raw["side"] == "ASK"
    assert ev.raw["level"] == 4180.1
    assert ev.raw["touches"] == 2


def test_liq_sweep_preserves_sweeps_field():
    ev = parse(json.dumps({
        "engine": "LIQ", "event": "SWEEP", "side": "BID", "dir": "LONG",
        "tf": "1", "price": 4179.6, "level": 4175.0, "sweeps": 3}))
    assert ev.engine == "LIQ" and ev.event == "SWEEP" and ev.dir == "long"
    assert ev.raw["sweeps"] == 3
    assert ev.raw["side"] == "BID"


def test_macd_flow_flip_preserves_exec_htf():
    ev = parse(json.dumps({
        "engine": "MACD", "event": "FLOW_FLIP", "dir": "LONG",
        "tf": "1", "price": 4179.6, "exec": 3, "htf": 4}))
    assert ev.engine == "MACD"
    assert ev.event == "FLOW_FLIP"
    assert ev.dir == "long"
    assert ev.raw["exec"] == 3
    assert ev.raw["htf"] == 4


def test_macd_weaken_parsed_preserves_extras():
    # v2 momentum-turn event；MACD 已 whitelisted，passthrough + extras 入 raw
    ev = parse(json.dumps({
        "engine": "MACD", "event": "WEAKEN", "dir": "SHORT",
        "tf": "5", "price": 4180.0, "exec": 2, "htf": 3}))
    assert ev.engine == "MACD"
    assert ev.event == "WEAKEN"
    assert ev.dir == "short"
    assert ev.tf == "5"
    assert ev.raw["exec"] == 2
    assert ev.raw["htf"] == 3


def test_wma5s_flip_green_parsed():
    ev = parse(json.dumps({
        "engine": "WMA5S", "event": "FLIP_GREEN", "dir": "LONG",
        "tf": "5S", "price": 4179.6}))
    assert ev.engine == "WMA5S"
    assert ev.event == "FLIP_GREEN"
    assert ev.dir == "long"
    assert ev.tf == "5S"


def test_wma5s_flip_red_parsed():
    ev = parse(json.dumps({
        "engine": "WMA5S", "event": "FLIP_RED", "dir": "SHORT",
        "tf": "5S", "price": 4179.6}))
    assert ev.engine == "WMA5S" and ev.event == "FLIP_RED" and ev.dir == "short"


def test_mrf_malformed_never_crashes():
    # 壞 JSON → fallback，唔會 raise
    ev = parse('{"engine":"EXP","event":')
    assert ev is not None
