"""Step 5：Notion Call Log（create page 已 wire；Phase 1 M1.1 = typed columns）。

每個 pushed call / wake 開一 row。真 write 要 NOTION_TOKEN + NOTION_CALLLOG_DB_ID（.env）。
未配前 `enabled()` False，caller graceful skip。

主路 = typed columns（Call Log DB 已有齊欄）：title(Call=engine+event)、engine(select)、
event/tf/reason/raw(rich_text)、wake(checkbox)、price(number)、time(date)、dir(select)。
無值嘅 dir/time/price 唔加（送 null select name / 空值會 400）。rich_text 每段 ≤2000。
標題欄名由 NOTION_TITLE_PROP 決定（default "Call"）。5 行 push text 照擺 page body 做人睇 card。
"""
from __future__ import annotations

import os

NOTION_API = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"


class NotionLogger:
    def __init__(self, token: str | None = None, db_id: str | None = None):
        self.token = token or os.environ.get("NOTION_TOKEN", "")
        self.db_id = db_id or os.environ.get("NOTION_CALLLOG_DB_ID", "")

    def enabled(self) -> bool:
        return bool(self.token and self.db_id)

    def log(self, call: dict, push_text: str) -> None:
        if not self.enabled():
            raise NotImplementedError(
                "Notion 未配（缺 NOTION_TOKEN / NOTION_CALLLOG_DB_ID）")
        # Phase 1 (M1.1) wired：POST /v1/pages，typed columns 為主路。
        import requests
        engine = call.get("engine") or ""
        event = call.get("event") or ""
        title = f"{engine} {event}".strip() or "alert"
        title_prop = os.environ.get("NOTION_TITLE_PROP", "Call")

        def _rt(s):  # rich_text，每段 content ≤2000
            return {"rich_text": [{"text": {"content": str(s or "")[:2000]}}]}

        props = {
            title_prop: {"title": [{"text": {"content": title[:2000]}}]},
            "engine":   {"select": {"name": engine}},
            "event":    _rt(event),
            "tf":       _rt(str(call.get("tf") or "")),
            "wake":     {"checkbox": bool(call.get("wake"))},
            "reason":   _rt(call.get("reason") or ""),
            "raw":      _rt(call.get("raw") or ""),
        }
        if not engine:                       # 空 select name 會 400 → 唔加
            props.pop("engine")
        if call.get("price") is not None:
            props["price"] = {"number": float(call["price"])}
        if call.get("time"):
            props["time"] = {"date": {"start": call["time"]}}   # ISO8601
        if call.get("dir"):
            props["dir"] = {"select": {"name": call["dir"]}}     # 無 dir 唔加

        payload = {"parent": {"database_id": self.db_id}, "properties": props}
        body = (push_text or "").strip()
        if body:   # bonus：5 行擺 page body 做人睇 card
            payload["children"] = [{
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [
                    {"type": "text", "text": {"content": body[:2000]}}]},
            }]
        resp = requests.post(
            NOTION_API,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            json=payload, timeout=10)
        resp.raise_for_status()
