"""Phase 1.5：wake_queue.jsonl —— WAKE 事件隊列（/analyze 消費 + thesis linkage）。

WAKE 時 append 一筆 {wake_id, ts, trigger_reason, engines, window_events, consumed_by:null,
consumed_at:null}。/analyze 開頭讀最新 consumed_by=null 做 timing+audit（唔餵方向）；收尾 thesis
emitter 回填 consumed_by=thesis_id/consumed_at。append-only 語義，backfill 用整檔重寫（jsonl 細）。

只寫 storage/ runtime artifact（gitignored），唔掂 repo 受控檔。
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from capture.base import ROOT

WAKE_QUEUE = ROOT / "storage" / "wake_queue.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_wake_id(now=None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"wake-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"


def build_record(event, reason: str, recent: list[dict], now=None) -> dict:
    """由當前 event + reason + 回望窗 recent 砌 wake record。engines/window_events = 窗內 + 當前。"""
    now = now or datetime.now(timezone.utc)
    window = [{"engine": event.engine, "event": event.event, "dir": event.dir,
               "ts": _now_iso()}]
    for r in recent or []:
        window.append({"engine": r.get("engine"), "event": r.get("event"),
                       "dir": r.get("dir"), "ts": r.get("ts")})
    engines = sorted({(w["engine"] or "").strip() for w in window if w.get("engine")})
    return {
        "wake_id": new_wake_id(now),
        "ts": now.isoformat(),
        "trigger_reason": reason,
        "engines": engines,
        "window_events": window,
        "consumed_by": None,
        "consumed_at": None,
    }


def append(record: dict, path: Path = WAKE_QUEUE) -> dict:
    """append 一筆 wake record 落 jsonl。回原 record。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _read_all(path: Path = WAKE_QUEUE) -> list[dict]:
    if not Path(path).exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def latest_unconsumed(path: Path = WAKE_QUEUE) -> dict | None:
    """最新一筆 consumed_by=null 嘅 wake（/analyze Step 0 讀）。冇 → None。"""
    for rec in reversed(_read_all(path)):
        if rec.get("consumed_by") is None:
            return rec
    return None


def mark_consumed(wake_id: str, thesis_id: str, when=None, path: Path = WAKE_QUEUE) -> bool:
    """回填指定 wake_id 嘅 consumed_by/consumed_at（整檔重寫）。搵唔到 → False。"""
    recs = _read_all(path)
    hit = False
    for rec in recs:
        if rec.get("wake_id") == wake_id and rec.get("consumed_by") is None:
            rec["consumed_by"] = thesis_id
            rec["consumed_at"] = (when or datetime.now(timezone.utc)).isoformat() \
                if not isinstance(when, str) else when
            hit = True
            break
    if hit:
        with open(path, "w", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return hit


if __name__ == "__main__":
    # /analyze Step 0 用：讀最新 unconsumed wake（純讀）。
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if "--latest-unconsumed" in sys.argv:
        rec = latest_unconsumed()
        print(json.dumps(rec, ensure_ascii=False, indent=2) if rec
              else json.dumps({"wake": None, "note": "manual run — 冇 unconsumed wake"},
                              ensure_ascii=False))
        raise SystemExit(0)
    print("用法：py -m ingest.wake_queue --latest-unconsumed")
    raise SystemExit(2)
