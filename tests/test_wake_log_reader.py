"""tests/test_wake_log_reader.py — webhook._load_recent_wakes 邊界（cooldown 真 wake 來源，restart-safe）。

conftest autouse 已將 srv.WAKE_LOG 指去 per-test temp。covered：缺檔 / 窗內外 ts 過濾 / 壞行跳過 / 空檔。
"""
import json
from datetime import datetime, timedelta, timezone

import ingest.webhook_server as srv


def _rec(mins, engine="SNR", dir="long"):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()
    return json.dumps({"ts": ts, "engine": engine, "dir": dir, "event": "FIRE", "line": None})


def _write(lines):
    srv.WAKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    srv.WAKE_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_missing_file_returns_empty():
    assert srv._load_recent_wakes(15) == []                 # temp WAKE_LOG 未建 → []


def test_within_and_outside_window_filtered():
    _write([_rec(5), _rec(30)])                             # 5 分內 + 30 分外
    got = srv._load_recent_wakes(15)
    assert len(got) == 1 and got[0]["engine"] == "SNR"


def test_malformed_and_blank_lines_skipped():
    _write(["not json", "", _rec(5), "{bad json"])
    got = srv._load_recent_wakes(15)
    assert len(got) == 1                                    # 只得合法嗰筆


def test_empty_file_returns_empty():
    _write([])
    assert srv._load_recent_wakes(15) == []


def test_all_outside_window_empty():
    _write([_rec(20), _rec(60)])
    assert srv._load_recent_wakes(15) == []
