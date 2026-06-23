"""Step 6 tests：SQLite store —— last_pushed_features 畀 dedupe（跨 cycle 記得）。"""
from storage.db import Store


def test_log_and_last_pushed_roundtrip(tmp_path):
    db = Store(tmp_path / "t.db")
    db.log_cycle({
        "cycle_id": "c1", "ts": "t", "route": "tv_mcp_cdp", "price": 4218.5,
        "precheck_triggered": 1, "action": "WAIT", "grade": "B+",
        "trigger_price": 4073.5, "alerts": [4057, 4074], "has_ant": 1,
        "pushed": 1, "push_reason": "first", "error": None, "bundle_dir": "d"})
    f = db.last_pushed_features()
    assert f["action"] == "WAIT" and f["grade"] == "B+" and f["trigger"] == 4073.5
    assert f["alerts"] == [4057, 4074] and f["has_ant"] is True


def test_non_pushed_row_does_not_shadow_pushed(tmp_path):
    db = Store(tmp_path / "t.db")
    db.log_cycle({"cycle_id": "c1", "pushed": 1, "action": "WAIT", "grade": "B+",
                  "trigger_price": 1, "alerts": [1], "has_ant": 0})
    db.log_cycle({"cycle_id": "c2", "pushed": 0, "action": "IN", "grade": "A",
                  "trigger_price": 2, "alerts": [2], "has_ant": 1})
    assert db.last_pushed_features()["action"] == "WAIT"   # 仍然係 pushed 嗰個
    assert db.count() == 2


def test_no_pushed_yet_returns_none(tmp_path):
    db = Store(tmp_path / "t.db")
    db.log_cycle({"cycle_id": "c1", "pushed": 0, "action": "WAIT"})
    assert db.last_pushed_features() is None
