"""tests/test_notion_backfill.py — Phase 1.5 Notion Call Log wake_id + thesis_status 回填。

injectable Notion mock（唔叫真 API）：① wake 寫入帶 wake_id ② emit 後 page thesis_status 更新
③ 搵唔到 page / API 錯 → emit 主流程唔受影響（thesis_log/wake_queue 永遠優先）。
"""
from datetime import datetime, timedelta, timezone

from analyze import thesis_emit as te
from ingest.thesis_store import ThesisStore
from publish.notion_log import NotionLogger, status_select

_NOW = datetime(2026, 7, 4, 3, 0, 0, tzinfo=timezone.utc)


class _FakeNotion:
    def __init__(self, result=True, raises=False, on=True):
        self.calls, self._result, self._raises, self._on = [], result, raises, on

    def enabled(self):
        return self._on

    def backfill_thesis_status(self, wake_id, status):
        self.calls.append((wake_id, status))
        if self._raises:
            raise RuntimeError("notion api down")
        return self._result


def _armed(**kw):
    base = {"status": "ARMED", "dir": "Long", "entry": 4150, "sl": 4100, "tp1": 4200,
            "tp2": 4250, "invalidation": 4100,
            "valid_until": (_NOW + timedelta(hours=2)).isoformat(), "rationale": "r"}
    base.update(kw)
    return base


def _fx(tmp_path):
    return dict(store=ThesisStore(path=tmp_path / "t.db"), thesis_dir=tmp_path / "th",
                wake_path=tmp_path / "wq.jsonl", now=_NOW)


# ── ① wake 寫入帶 wake_id（_build_props 純函數）────────────────────────────────────
def test_build_props_includes_wake_id():
    props = NotionLogger("tok", "db")._build_props(
        {"engine": "SNR", "event": "FIRE", "wake": True, "wake_id": "wake-abc"})
    assert props["wake_id"]["rich_text"][0]["text"]["content"] == "wake-abc"


def test_build_props_omits_wake_id_when_absent():
    props = NotionLogger("tok", "db")._build_props({"engine": "SNR", "event": "FIRE"})
    assert "wake_id" not in props


def test_status_select_mapping():
    assert status_select("ARMED") == "ARMED" and status_select("IN_TRADE") == "IN_TRADE"
    assert status_select("WAIT") == "WAIT" and status_select("NO_TRADE") == "WAIT"
    assert status_select("INVALIDATED") == "CLOSED" and status_select("EXPIRED") == "CLOSED"
    assert status_select("???") == "WAIT"


# ── ② emit 後對應 page thesis_status 更新 ─────────────────────────────────────────
def test_emit_backfills_notion_status(tmp_path):
    fake = _FakeNotion(result=True)
    res = te.emit(_armed(wake_id="wake-1"), notion=fake, **_fx(tmp_path))
    assert res["notion_status"] is True
    assert fake.calls == [("wake-1", "ARMED")]                 # 帶正確 status


def test_emit_wait_maps_and_backfills(tmp_path):
    fake = _FakeNotion(result=True)
    res = te.emit({"status": "WAIT", "rationale": "gate 2/4", "wake_id": "wake-2"},
                  notion=fake, **_fx(tmp_path))
    assert res["notion_status"] is True and fake.calls[0] == ("wake-2", "WAIT")


# ── ③ 搵唔到 page / API 錯 → emit 主流程唔受影響 ─────────────────────────────────
def test_emit_page_not_found_still_writes_thesis(tmp_path):
    fx = _fx(tmp_path)
    fake = _FakeNotion(result=False)                           # query 冇對應 page
    res = te.emit(_armed(wake_id="wake-x"), notion=fake, **fx)
    assert res["notion_status"] is False
    assert fx["store"].count() == 1                            # thesis_log 照寫（優先）
    assert (fx["thesis_dir"] / f"{res['thesis_id']}-v1.json").exists()


def test_emit_notion_raises_does_not_crash(tmp_path):
    fx = _fx(tmp_path)
    fake = _FakeNotion(raises=True)                            # API 炒車
    res = te.emit(_armed(wake_id="wake-y"), notion=fake, **fx)
    assert res["notion_status"] is None                        # 降級
    assert fx["store"].count() == 1 and res["status"] == "ARMED"   # 主流程完好


def test_emit_no_wake_id_skips_notion(tmp_path):
    fake = _FakeNotion(result=True)
    res = te.emit(_armed(), notion=fake, **_fx(tmp_path))      # 無 wake_id + wake_queue 空
    assert res["notion_status"] is None and fake.calls == []   # 唔叫 backfill


def test_emit_notion_disabled_skips(tmp_path):
    fake = _FakeNotion(on=False)                               # 未配 token
    res = te.emit(_armed(wake_id="wake-z"), notion=fake, **_fx(tmp_path))
    assert res["notion_status"] is None and fake.calls == []
