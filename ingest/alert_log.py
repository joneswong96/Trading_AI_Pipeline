"""Phase 1 ingest：alert_events table（同 Phase 2 共用 trading-auto/storage/trading.db）。

唔掂 Phase 2 嘅 `cycles`。開自己嘅 sqlite3 connection 指去同一個 db file（DEFAULT_DB），
只負責 alert_events 嘅 create / insert / query。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage.db import DEFAULT_DB
from ingest.parser import AlertEvent

ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_events (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts     TEXT,      -- 收到時間（UTC ISO8601）
  engine TEXT,
  event  TEXT,
  dir    TEXT,
  grade  TEXT,
  tf     TEXT,
  price  REAL,
  raw    TEXT        -- 原始 payload（json）
);
"""

_COLS = ["ts", "engine", "event", "dir", "grade", "tf", "price", "raw"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlertLog:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(ALERT_SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.path)

    def insert_alert(self, event: AlertEvent) -> int:
        """寫一行 alert_events，回 new row id（畀 server 剔走自己再餵 trigger）。"""
        row = [_now_iso(), event.engine, event.event, event.dir, event.grade,
               event.tf, event.price, json.dumps(event.raw, ensure_ascii=False)]
        with self._conn() as c:
            cur = c.execute(
                f"INSERT INTO alert_events ({','.join(_COLS)}) "
                f"VALUES ({','.join('?' * len(_COLS))})", row)
            return cur.lastrowid

    def get_recent(self, minutes: int) -> list[dict]:
        """近 `minutes` 分鐘嘅 alert_events（dict，新→舊）。畀 trigger 回望。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT id, ts, engine, event, dir, grade, tf, price, raw "
                "FROM alert_events WHERE ts >= ? ORDER BY id DESC", (cutoff,)
            ).fetchall()
        return [dict(r) for r in rows]

    def is_duplicate(self, event: AlertEvent, within_seconds: int = 10) -> bool:
        """Step 5 ingest dedupe：完全相同 alert（engine+event+dir+tf+price）短窗內重送 → True。

        `IS` 係 null-safe equality（NULL IS NULL → true），所以欄位有 None 都比得。
        """
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(seconds=within_seconds)).isoformat()
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM alert_events WHERE ts >= ? "
                "AND engine IS ? AND event IS ? AND dir IS ? AND tf IS ? AND price IS ? "
                "LIMIT 1",
                (cutoff, event.engine, event.event, event.dir, event.tf, event.price)
            ).fetchone()
        return row is not None
