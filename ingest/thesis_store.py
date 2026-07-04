"""Phase 1.5：thesis_log table（同 alert_events / cycles 共用 trading-auto/storage/trading.db）。

**append-only + versioning**（Jones 2026-07-04 拍板）：狀態變 = 同 thesis_id 出 version+1 新 row，
**永不 edit 舊 row**（完整可審計）。get_active 只認 status∈{ARMED,IN_TRADE}、未過 valid_until 嘅
最新 version，餵 trigger.should_wake 做 thesis-aware gate。

唔掂 Phase 2 `cycles` / Phase 1 `alert_events`；開自己 connection 指同一 db file。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from storage.db import DEFAULT_DB

THESIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS thesis_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  thesis_id    TEXT,
  version      INTEGER,
  status       TEXT,     -- ARMED|IN_TRADE|WAIT|NO_TRADE|INVALIDATED|EXPIRED|CLOSED
  dir          TEXT,
  entry        REAL,
  sl           REAL,
  tp1          REAL,
  tp2          REAL,
  invalidation TEXT,     -- price 或文字描述
  valid_until  TEXT,
  rationale    TEXT,
  wake_id      TEXT,     -- linkage 返 wake_queue
  ts           TEXT,     -- emit 時間（UTC ISO8601）
  raw          TEXT      -- 完整 thesis JSON
);
"""

_COLS = ["thesis_id", "version", "status", "dir", "entry", "sl", "tp1", "tp2",
         "invalidation", "valid_until", "rationale", "wake_id", "ts", "raw"]

_ACTIVE_STATUS = ("ARMED", "IN_TRADE")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThesisStore:
    def __init__(self, path=DEFAULT_DB):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(THESIS_SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.path)

    def next_version(self, thesis_id: str) -> int:
        """同 thesis_id 現有 max(version)+1；未見過 → 1。"""
        if not thesis_id:
            return 1
        with self._conn() as c:
            row = c.execute("SELECT MAX(version) FROM thesis_log WHERE thesis_id = ?",
                            (thesis_id,)).fetchone()
        return (row[0] or 0) + 1

    def append(self, thesis: dict) -> tuple[str, int]:
        """append-only INSERT 一個 thesis version。thesis_id 缺 → 由 caller 先定；version 缺 →
        自動 next_version。回 (thesis_id, version)。**唔 update 舊 row**。"""
        tid = thesis.get("thesis_id")
        ver = thesis.get("version") or self.next_version(tid)
        row = {
            "thesis_id": tid, "version": ver, "status": thesis.get("status"),
            "dir": thesis.get("dir"), "entry": thesis.get("entry"), "sl": thesis.get("sl"),
            "tp1": thesis.get("tp1"), "tp2": thesis.get("tp2"),
            "invalidation": _txt(thesis.get("invalidation")),
            "valid_until": thesis.get("valid_until"), "rationale": thesis.get("rationale"),
            "wake_id": thesis.get("wake_id"), "ts": thesis.get("ts") or _now_iso(),
            "raw": json.dumps(thesis, ensure_ascii=False),
        }
        vals = [row[k] for k in _COLS]
        with self._conn() as c:
            c.execute(f"INSERT INTO thesis_log ({','.join(_COLS)}) "
                      f"VALUES ({','.join('?' * len(_COLS))})", vals)
        return tid, ver

    def get_active(self, now=None) -> dict | None:
        """最近一個 active thesis：per thesis_id 取最新 version，status∈{ARMED,IN_TRADE} 且未過
        valid_until，按 ts 取最新。冇 → None。餵 should_wake。"""
        now = now or datetime.now(timezone.utc)
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            # 每 thesis_id 嘅最新 version row（append-only，max(version) = 現態）
            rows = c.execute(
                "SELECT t.* FROM thesis_log t "
                "JOIN (SELECT thesis_id, MAX(version) v FROM thesis_log GROUP BY thesis_id) m "
                "ON t.thesis_id = m.thesis_id AND t.version = m.v "
                "ORDER BY t.ts DESC").fetchall()
        for r in rows:
            if (r["status"] or "").strip().upper() not in _ACTIVE_STATUS:
                continue
            vu = _parse(r["valid_until"])
            if vu is not None and now >= vu:
                continue
            d = dict(r)
            d["invalidation"] = _num_or_txt(d.get("invalidation"))
            return d
        return None

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM thesis_log").fetchone()[0]


def _txt(v):
    return None if v is None else str(v)


def _num_or_txt(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _parse(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
