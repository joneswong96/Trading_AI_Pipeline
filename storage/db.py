"""Step 6：SQLite —— 每 cycle 一行（可回放／可審計，核心原則 #3）。

一行記低：cycle_id、時間、route、現價、precheck 結果、call 摘要（action/grade/trigger/
alerts/has_ant）、有冇 push + 原因、error、bundle 路徑。dedupe 由 `last_pushed_features()`
攞返上一個 pushed call 嘅 features（跨重啟都記得，唔淨靠 in-memory）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from capture.base import ROOT

DEFAULT_DB = ROOT / "storage" / "trading.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_id           TEXT,
  ts                 TEXT,
  route              TEXT,
  price              REAL,
  precheck_triggered INTEGER,
  action             TEXT,
  grade              TEXT,
  trigger_price      REAL,
  alerts             TEXT,      -- json list
  has_ant            INTEGER,
  pushed             INTEGER,   -- 0/1
  push_reason        TEXT,
  error              TEXT,
  bundle_dir         TEXT
);
"""

_COLS = ["cycle_id", "ts", "route", "price", "precheck_triggered", "action",
         "grade", "trigger_price", "alerts", "has_ant", "pushed", "push_reason",
         "error", "bundle_dir"]


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.path)

    def log_cycle(self, rec: dict) -> None:
        """寫一行。rec 用 _COLS 嘅 key；alerts(list) 自動轉 json、bool 轉 0/1。"""
        row = dict(rec)
        if isinstance(row.get("alerts"), (list, tuple)):
            row["alerts"] = json.dumps(list(row["alerts"]))
        for k in ("precheck_triggered", "has_ant", "pushed"):
            if k in row and isinstance(row[k], bool):
                row[k] = int(row[k])
        vals = [row.get(k) for k in _COLS]
        with self._conn() as c:
            c.execute(
                f"INSERT INTO cycles ({','.join(_COLS)}) "
                f"VALUES ({','.join('?' * len(_COLS))})", vals)

    def last_pushed_features(self) -> dict | None:
        """最近一個 pushed=1 嘅 call features（畀 dedupe 比對）。冇 → None。"""
        with self._conn() as c:
            row = c.execute(
                "SELECT action, grade, trigger_price, alerts, has_ant "
                "FROM cycles WHERE pushed = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {
            "action": row[0], "grade": row[1], "trigger": row[2],
            "alerts": json.loads(row[3] or "[]"), "has_ant": bool(row[4]),
        }

    def pushed_bundle_dirs(self) -> set[str]:
        """有 push 過嘅 bundle 資料夾（retention 用：呢啲永留，可回放證物 #3）。"""
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT bundle_dir FROM cycles "
                "WHERE pushed = 1 AND bundle_dir IS NOT NULL").fetchall()
        return {r[0] for r in rows}

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
