"""tests/test_wake_queue.py — Phase 1.5 wake_queue.jsonl（append / latest-unconsumed / backfill）。"""
from datetime import datetime, timezone

from ingest import wake_queue as wq
from ingest.parser import AlertEvent

_NOW = datetime(2026, 7, 4, 3, 0, 0, tzinfo=timezone.utc)


def _ev(engine="SNR", event="FIRE", dir="long"):
    return AlertEvent(engine=engine, event=event, dir=dir, grade=None, tf=None,
                      time=None, price=None, raw={})


def _path(tmp_path):
    return tmp_path / "wake_queue.jsonl"


def test_build_record_shape():
    rec = wq.build_record(_ev("SNR", "FIRE", "long"),
                          "SNR FIRE → wake", [{"engine": "SR", "event": "GRADE_A",
                                               "dir": "long", "ts": _NOW.isoformat()}], _NOW)
    assert rec["wake_id"].startswith("wake-")
    assert rec["trigger_reason"] == "SNR FIRE → wake"
    assert set(rec["engines"]) == {"SNR", "SR"}
    assert rec["consumed_by"] is None and rec["consumed_at"] is None
    assert len(rec["window_events"]) == 2


def test_append_and_latest_unconsumed(tmp_path):
    p = _path(tmp_path)
    r1 = wq.append(wq.build_record(_ev(), "r1", [], _NOW), path=p)
    r2 = wq.append(wq.build_record(_ev(), "r2", [], _NOW), path=p)
    latest = wq.latest_unconsumed(path=p)
    assert latest["wake_id"] == r2["wake_id"]        # 最新一筆
    assert r1["wake_id"] != r2["wake_id"]


def test_latest_unconsumed_none_when_empty(tmp_path):
    assert wq.latest_unconsumed(path=_path(tmp_path)) is None


def test_mark_consumed_backfills(tmp_path):
    p = _path(tmp_path)
    r1 = wq.append(wq.build_record(_ev(), "r1", [], _NOW), path=p)
    ok = wq.mark_consumed(r1["wake_id"], "thesis-abc", when=_NOW, path=p)
    assert ok is True
    # 已消費 → latest_unconsumed 唔再返佢
    assert wq.latest_unconsumed(path=p) is None
    recs = wq._read_all(p)
    assert recs[0]["consumed_by"] == "thesis-abc"
    assert recs[0]["consumed_at"] == _NOW.isoformat()


def test_mark_consumed_missing_id(tmp_path):
    p = _path(tmp_path)
    wq.append(wq.build_record(_ev(), "r1", [], _NOW), path=p)
    assert wq.mark_consumed("wake-nope", "thesis-x", path=p) is False


def test_mark_consumed_skips_already_consumed(tmp_path):
    p = _path(tmp_path)
    r1 = wq.append(wq.build_record(_ev(), "r1", [], _NOW), path=p)
    wq.mark_consumed(r1["wake_id"], "thesis-1", when=_NOW, path=p)
    # 第二次同 id 已 consumed → False（唔覆寫）
    assert wq.mark_consumed(r1["wake_id"], "thesis-2", path=p) is False
    assert wq._read_all(p)[0]["consumed_by"] == "thesis-1"
