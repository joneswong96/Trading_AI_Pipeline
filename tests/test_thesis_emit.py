"""tests/test_thesis_emit.py — Phase 1.5 thesis emitter（validate fail-loud + emit + wake 回填）。"""
from datetime import datetime, timedelta, timezone

import pytest

from analyze import thesis_emit as te
from ingest import wake_queue as wq
from ingest.thesis_store import ThesisStore

_NOW = datetime(2026, 7, 4, 3, 0, 0, tzinfo=timezone.utc)


def _armed(**kw):
    base = {"status": "ARMED", "dir": "Long", "entry": 4150, "sl": 4100, "tp1": 4200,
            "tp2": 4250, "invalidation": 4100,
            "valid_until": (_NOW + timedelta(hours=2)).isoformat(),
            "rationale": "gate 3/4 + SNR"}
    base.update(kw)
    return base


def _fixtures(tmp_path):
    return (ThesisStore(path=tmp_path / "t.db"), tmp_path / "thesis", tmp_path / "wq.jsonl")


# ── validate fail-loud ────────────────────────────────────────────────────────────
def test_validate_bad_status():
    with pytest.raises(te.ThesisValidationError):
        te.validate({"status": "FOO", "rationale": "x"})


def test_validate_missing_rationale():
    with pytest.raises(te.ThesisValidationError):
        te.validate(_armed(rationale=""))


def test_validate_actionable_needs_dir_entry_sl():
    with pytest.raises(te.ThesisValidationError):
        te.validate(_armed(dir=None))
    with pytest.raises(te.ThesisValidationError):
        te.validate(_armed(entry=None))


def test_validate_wait_minimal_ok():
    te.validate({"status": "WAIT", "rationale": "gate 2/4 <3"})   # 唔 raise


# ── emit：寫 thesis_log + backup + wake 回填 ──────────────────────────────────────
def test_emit_actionable_writes_and_versions(tmp_path):
    store, tdir, wqp = _fixtures(tmp_path)
    r1 = te.emit(_armed(thesis_id="thesis-1"), store=store, thesis_dir=tdir,
                 wake_path=wqp, now=_NOW)
    assert r1["version"] == 1 and (tdir / "thesis-1-v1.json").exists()
    r2 = te.emit(_armed(thesis_id="thesis-1", status="IN_TRADE"), store=store,
                 thesis_dir=tdir, wake_path=wqp, now=_NOW)
    assert r2["version"] == 2 and (tdir / "thesis-1-v2.json").exists()
    assert store.count() == 2                              # append-only
    assert store.get_active(_NOW)["status"] == "IN_TRADE"


def test_emit_invalid_writes_nothing(tmp_path):
    store, tdir, wqp = _fixtures(tmp_path)
    with pytest.raises(te.ThesisValidationError):
        te.emit(_armed(status="BOGUS"), store=store, thesis_dir=tdir, wake_path=wqp, now=_NOW)
    assert store.count() == 0 and not tdir.exists()       # fail-loud → 零寫


def test_emit_backfills_wake_by_id(tmp_path):
    store, tdir, wqp = _fixtures(tmp_path)
    from ingest.parser import AlertEvent
    ev = AlertEvent("SNR", "FIRE", "long", None, None, None, None, {})
    rec = wq.append(wq.build_record(ev, "SNR FIRE", [], _NOW), path=wqp)
    res = te.emit(_armed(wake_id=rec["wake_id"]), store=store, thesis_dir=tdir,
                  wake_path=wqp, now=_NOW)
    assert res["wake_consumed"] == rec["wake_id"]
    assert wq.latest_unconsumed(path=wqp) is None          # 已消費
    assert wq._read_all(wqp)[0]["consumed_by"] == res["thesis_id"]


def test_emit_backfills_latest_when_no_wake_id(tmp_path):
    store, tdir, wqp = _fixtures(tmp_path)
    from ingest.parser import AlertEvent
    ev = AlertEvent("SNR", "FIRE", "long", None, None, None, None, {})
    wq.append(wq.build_record(ev, "SNR FIRE", [], _NOW), path=wqp)
    res = te.emit(_armed(), store=store, thesis_dir=tdir, wake_path=wqp, now=_NOW)
    assert res["wake_consumed"] is not None                # 揀 latest-unconsumed


def test_emit_wait_no_wake_ok(tmp_path):
    store, tdir, wqp = _fixtures(tmp_path)
    res = te.emit({"status": "WAIT", "rationale": "gate 2/4"}, store=store,
                  thesis_dir=tdir, wake_path=wqp, now=_NOW)
    assert res["status"] == "WAIT" and res["wake_consumed"] is None
    assert store.count() == 1                              # WAIT 都 emit（1:1）
    assert store.get_active(_NOW) is None                  # WAIT 唔 gate 下一個 wake
