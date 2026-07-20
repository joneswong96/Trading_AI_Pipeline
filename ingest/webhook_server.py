"""Phase 1 ingest：FastAPI webhook server。POST /alert。

Flow：parse → ingest dedupe → alert_log.insert → trigger.evaluate
       → 若 wake：Telegram 提示「✅ 夠料喇，撳 /analyze」+ Notion(guard) + 落檔；否則只 log。

容錯：快回 200；fan-out 每個 downstream 各自 try/except，任何一個失敗都唔拖冧 endpoint。
PORT 由 .env 讀，default 8000（跟 Phase 1 SSOT）。
"""
from __future__ import annotations

import json
import logging
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
from ingest.project_a.api import router as project_a_router
from ingest.project_a.config import ProjectAConfig
from ingest.project_a.raw_producer_adapter import (
    ProjectARawProducerAdapter,
    detect_raw_producer,
)
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
app.include_router(project_a_router)
_alog = AlertLog()
_thesis = ThesisStore()
_raw_producer_adapter: ProjectARawProducerAdapter | None = None


def configure_raw_producer_adapter(adapter: ProjectARawProducerAdapter | None) -> None:
    """Inject or clear the isolated raw-producer adapter (primarily for tests)."""

    global _raw_producer_adapter
    _raw_producer_adapter = adapter


def _get_raw_producer_adapter() -> ProjectARawProducerAdapter:
    global _raw_producer_adapter
    if _raw_producer_adapter is None:
        _raw_producer_adapter = ProjectARawProducerAdapter(ProjectAConfig.from_env())
    return _raw_producer_adapter


def _load_active_thesis(now):
    """Phase 1.5：讀最新 active thesis 餵 should_wake。thesis_log 空 / 讀失敗 → None（行為同 Phase 1）。"""
    try:
        return _thesis.get_active(now)
    except Exception:
        log.exception("get_active thesis failed（fall back None）")
        return None


def _load_recent_wakes(minutes):
    """2026-07-07 fix：讀 wake_log.jsonl（真 wake，wake=True）近 `minutes` 分鐘記錄，餵 cooldown 錨定。
    restart-safe（讀持久檔）；log-only alert 從不入 wake_log → 唔會續命 cooldown。讀失敗 → []。"""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    out = []
    try:
        if not WAKE_LOG.exists():
            return out
        with open(WAKE_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (rec.get("ts") or "") >= cutoff:      # 只取窗內（string ISO UTC 可比）
                    out.append(rec)
    except OSError:
        log.exception("wake_log 讀取失敗（fall back []）")
    return out


@app.get("/health")
def health():
    return {"ok": True, "service": "ingest", "phase": 1}


@app.post("/alert")
async def alert(request: Request):
    raw_body = await request.body()
    producer = detect_raw_producer(raw_body)
    if producer.candidate:
        try:
            result = _get_raw_producer_adapter().receive(raw_body, detection=producer)
        except Exception:
            # Recognized Project A payloads fail closed and never fall through to
            # the legacy parser. Do not include body or exception details here.
            log.exception("Project A raw-producer adapter failed closed")
            return JSONResponse(
                {
                    "ok": False,
                    "accepted": False,
                    "deduped": False,
                    "producer": producer.producer,
                    "event": producer.event,
                    "telemetry_status": "FAILED_CLOSED",
                    "state_status": "UNCHANGED",
                    "wake": False,
                    "provider_called": False,
                    "writer_called": False,
                    "order_placed": False,
                    "error_code": "PRODUCER_ADAPTER_FAILURE",
                },
                status_code=503,
            )
        return JSONResponse(result.response(), status_code=result.http_status)

    body = raw_body.decode("utf-8", "replace")

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
    recent_wakes = _load_recent_wakes(trigger.COOLDOWN_MIN)  # 真 wake 錨定 cooldown（2026-07-07 fix）
    wake, reason = trigger.should_wake(recent, active, event, now, recent_wakes=recent_wakes)
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
        "line": trigger._snr_line(event.raw or {}),   # SNR line（cooldown 細分；無 → None）
        "reason": decision.reason,
    }
    with open(WAKE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    import uvicorn
    project_a_config = ProjectAConfig.from_env()
    project_a_config.assert_safe()
    port = project_a_config.ingest_port
    log.info("ingest webhook server up on :%d（POST /alert；POST %s）",
             port, project_a_config.endpoint)
    uvicorn.run(app, host=project_a_config.ingest_host, port=port)
