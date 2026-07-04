"""tests/test_thesis_store.py — Phase 1.5 thesis_log（append-only + versioning + get_active）。"""
from datetime import datetime, timedelta, timezone

from ingest.thesis_store import ThesisStore

_NOW = datetime(2026, 7, 4, 3, 0, 0, tzinfo=timezone.utc)


def _store(tmp_path):
    return ThesisStore(path=tmp_path / "t.db")


def _th(tid="thesis-1", status="ARMED", dir="Long", invalidation=4100,
        valid_until=None, ts=None, version=None):
    return {"thesis_id": tid, "status": status, "dir": dir, "entry": 4150, "sl": 4100,
            "tp1": 4200, "tp2": 4250, "invalidation": invalidation,
            "valid_until": valid_until or (_NOW + timedelta(hours=2)).isoformat(),
            "rationale": "test", "wake_id": "wake-x", "ts": ts or _NOW.isoformat(),
            "version": version}


def test_append_assigns_version_1(tmp_path):
    s = _store(tmp_path)
    tid, ver = s.append(_th())
    assert (tid, ver) == ("thesis-1", 1) and s.count() == 1


def test_version_increments_append_only(tmp_path):
    s = _store(tmp_path)
    s.append(_th(status="ARMED"))
    _, v2 = s.append(_th(status="IN_TRADE"))
    _, v3 = s.append(_th(status="INVALIDATED"))
    assert (v2, v3) == (2, 3) and s.count() == 3       # 3 row，舊 row 保留


def test_get_active_returns_latest_version(tmp_path):
    s = _store(tmp_path)
    s.append(_th(status="ARMED"))
    s.append(_th(status="IN_TRADE"))                   # 最新 version = IN_TRADE（active）
    a = s.get_active(_NOW)
    assert a["thesis_id"] == "thesis-1" and a["status"] == "IN_TRADE" and a["version"] == 2
    assert a["invalidation"] == 4100                   # 數字還原


def test_get_active_none_when_latest_not_active(tmp_path):
    s = _store(tmp_path)
    s.append(_th(status="ARMED"))
    s.append(_th(status="INVALIDATED"))                # 最新非 active
    assert s.get_active(_NOW) is None


def test_get_active_skips_expired(tmp_path):
    s = _store(tmp_path)
    past = (_NOW - timedelta(hours=1)).isoformat()
    s.append(_th(status="ARMED", valid_until=past))
    assert s.get_active(_NOW) is None


def test_get_active_none_when_empty(tmp_path):
    assert _store(tmp_path).get_active(_NOW) is None


def test_get_active_picks_most_recent_thesis(tmp_path):
    s = _store(tmp_path)
    s.append(_th(tid="thesis-old", status="ARMED",
                 ts=(_NOW - timedelta(minutes=30)).isoformat()))
    s.append(_th(tid="thesis-new", status="ARMED", ts=_NOW.isoformat()))
    assert s.get_active(_NOW)["thesis_id"] == "thesis-new"


def test_wait_status_not_active(tmp_path):
    s = _store(tmp_path)
    s.append(_th(status="WAIT"))
    assert s.get_active(_NOW) is None
