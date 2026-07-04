"""Phase 1 ingest：FastAPI webhook server。POST /alert。

Flow：parse → ingest dedupe → alert_log.insert → trigger.evaluate
       → 若 wake：Telegram 提示「✅ 夠料喇，撳 /analyze」+ Notion(guard) + 落檔；否則只 log。

容錯：快回 200；fan-out 每個 downstream 各自 try/except，任何一個失敗都唔拖冧 endpoint。
PORT 由 .env 讀，default 8000（跟 Phase 1 SSOT）。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from capture.base import ROOT
from ingest.alert_log import AlertLog
from ingest.parser import parse
from ingest import trigger
from ingest import wake_queue
from ingest.thesis_store import ThesisStore
from publish.telegram import TelegramPublisher
from publish.notion_log import NotionLogger

load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("ingest.webhook")

WAKE_LOG = ROOT / "storage" / "wake_log.jsonl"
WAKE_TEXT = "✅ 夠料喇，撳 /analyze"

app = FastAPI(title="trading-auto ingest", version="phase1")
_alog = AlertLog()
_thesis = ThesisStore()


def _load_active_thesis(now):
    """Phase 1.5：讀最新 active thesis 餵 should_wake。thesis_log 空 / 讀失敗 → None（行為同 Phase 1）。"""
    try:
        return _thesis.get_active(now)
    except Exception:
        log.exception("get_active thesis failed（fall back None）")
        return None


@app.get("/health")
def health():
    return {"ok": True, "service": "ingest", "phase": 1}


@app.post("/alert")
async def alert(request: Request):
    body = (await request.body()).decode("utf-8", "replace")

    # 1) parse（壞 body 都回 200，唔俾 TradingView 死命重送）
    try:
        event = parse(body)
    except Exception:
        log.exception("parse failed; body=%r", body[:500])
        return JSONResponse({"ok": False, "stage": "parse"}, status_code=200)

    # 2) ingest dedupe（短窗重送）
    if _alog.is_duplicate(event):
        log.info("ingest dedupe（重送）：%s %s %s", event.engine, event.event, event.dir)
        return {"ok": True, "deduped": True, "wake": False,
                "reason": "ingest dedupe（短窗重送）"}

    # 3) 寫 alert_events
    try:
        new_id = _alog.insert_alert(event)
    except Exception:
        log.exception("alert_log insert failed")
        return JSONResponse({"ok": False, "stage": "insert"}, status_code=200)

    # 4) trigger（剔走啱啱寫嗰行，淨低較早嘅做回望）
    #    回望窗用 LOOKBACK_MIN（=max(cooldown 15, MRF 30)），確保 MRF 30 分窗有齊資料；
    #    既有規則各自喺 evaluate 內再 _within 收窄，行為不變。
    recent = [r for r in _alog.get_recent(trigger.LOOKBACK_MIN) if r["id"] != new_id]
    now = datetime.now(timezone.utc)
    active = _load_active_thesis(now)                     # Phase 1.5 thesis-aware gate
    wake, reason = trigger.should_wake(recent, active, event, now)
    decision = trigger.WakeDecision(wake, reason)
    log.info("alert %s %s dir=%s → wake=%s（%s）",
             event.engine, event.event, event.dir, wake, reason)

    # 5) fan-out（淨係 wake 先；每個 downstream 各自容錯）+ append wake_queue（Phase 1.5）
    wake_id = None
    if wake:
        wake_id = _append_wake_queue(event, reason, recent, now)
        _fanout(event, decision, wake_id)

    return {"ok": True, "deduped": False, "wake": wake, "reason": reason,
            "wake_id": wake_id}


def _append_wake_queue(event, reason, recent, now):
    """Phase 1.5：WAKE 時 append storage/wake_queue.jsonl（供 /analyze 消費 + thesis linkage）。"""
    try:
        rec = wake_queue.append(wake_queue.build_record(event, reason, recent, now))
        log.info("wake_queue append → %s", rec["wake_id"])
        return rec["wake_id"]
    except Exception:
        log.exception("wake_queue append failed（continue）")
        return None


def _fanout(event, decision, wake_id=None):
    text = f"{WAKE_TEXT}\n{event.engine} {event.event} {event.dir or ''}".rstrip()
    text += f"\n理由：{decision.reason}"

    # (1) Telegram — Phase 1 已 wire 真 send；無 token 就 graceful skip
    try:
        tg = TelegramPublisher()
        if tg.enabled():
            tg.push(text)
            log.info("telegram pushed")
        else:
            log.info("telegram disabled（無 token）— would push：%s",
                     text.replace("\n", " | "))
    except Exception:
        log.exception("telegram fanout failed（continue）")

    # (2) Notion Call Log — Phase 1 (M1) wired；enabled() true 就 create row
    try:
        nl = NotionLogger()
        if nl.enabled():
            nl.log({"engine": event.engine, "event": event.event,
                    "dir": event.dir, "tf": event.tf, "price": event.price,
                    "time": event.time, "reason": decision.reason,
                    "wake": decision.wake, "wake_id": wake_id,
                    "raw": json.dumps(event.raw, ensure_ascii=False)}, text)
            log.info("notion logged")
        else:
            log.info("notion disabled（無 token）— skip")
    except Exception:
        log.exception("notion fanout failed（continue）")

    # (3) 落檔 — wake 證物（jsonl append，可回放）
    try:
        _append_wake(event, decision)
        log.info("wake 落檔 → %s", WAKE_LOG)
    except Exception:
        log.exception("wake 落檔 failed（continue）")


def _append_wake(event, decision):
    WAKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "engine": event.engine, "event": event.event, "dir": event.dir,
        "grade": event.grade, "tf": event.tf, "price": event.price,
        "reason": decision.reason,
    }
    with open(WAKE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    log.info("ingest webhook server up on :%d（POST /alert）", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
