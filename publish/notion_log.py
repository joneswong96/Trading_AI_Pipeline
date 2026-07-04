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
NOTION_DB_QUERY = "https://api.notion.com/v1/databases/{db_id}/query"
NOTION_PAGE = "https://api.notion.com/v1/pages/{page_id}"
NOTION_VERSION = "2022-06-28"

# thesis_status Notion select 只有 4 個 option（WAIT/ARMED/IN_TRADE/CLOSED）；emit status 收窄映射。
_STATUS_SELECT = {"ARMED": "ARMED", "IN_TRADE": "IN_TRADE", "WAIT": "WAIT",
                  "NO_TRADE": "WAIT", "CLOSED": "CLOSED", "INVALIDATED": "CLOSED",
                  "EXPIRED": "CLOSED"}


def status_select(status: str) -> str:
    """emit status → thesis_status select option（4 選項；未知 → WAIT 保守）。"""
    return _STATUS_SELECT.get(str(status or "").strip().upper(), "WAIT")


class NotionLogger:
    def __init__(self, token: str | None = None, db_id: str | None = None):
        self.token = token or os.environ.get("NOTION_TOKEN", "")
        self.db_id = db_id or os.environ.get("NOTION_CALLLOG_DB_ID", "")

    def enabled(self) -> bool:
        return bool(self.token and self.db_id)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}

    def _build_props(self, call: dict) -> dict:
        """typed columns props（純函數，可測）。無值嘅 select/date/number 唔加（送 null 會 400）。"""
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
        if call.get("wake_id"):
            props["wake_id"] = _rt(call["wake_id"])              # Phase 1.5 linkage
        return props

    def log(self, call: dict, push_text: str) -> None:
        if not self.enabled():
            raise NotImplementedError(
                "Notion 未配（缺 NOTION_TOKEN / NOTION_CALLLOG_DB_ID）")
        # Phase 1 (M1.1) wired：POST /v1/pages，typed columns 為主路。
        import requests
        payload = {"parent": {"database_id": self.db_id}, "properties": self._build_props(call)}
        body = (push_text or "").strip()
        if body:   # bonus：5 行擺 page body 做人睇 card
            payload["children"] = [{
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [
                    {"type": "text", "text": {"content": body[:2000]}}]},
            }]
        resp = requests.post(NOTION_API, headers=self._headers(), json=payload, timeout=10)
        resp.raise_for_status()

    def backfill_thesis_status(self, wake_id: str, status: str) -> bool:
        """Phase 1.5：query wake_id 對應嘅 Call Log page → PATCH thesis_status。
        搵到並更新 → True；搵唔到對應 page → False。API 錯會 raise（caller best-effort 包住）。"""
        if not self.enabled():
            raise NotImplementedError("Notion 未配")
        import requests
        q = requests.post(
            NOTION_DB_QUERY.format(db_id=self.db_id), headers=self._headers(),
            json={"filter": {"property": "wake_id", "rich_text": {"equals": wake_id}},
                  "page_size": 1}, timeout=10)
        q.raise_for_status()
        results = q.json().get("results") or []
        if not results:
            return False
        page_id = results[0]["id"]
        u = requests.patch(
            NOTION_PAGE.format(page_id=page_id), headers=self._headers(),
            json={"properties": {"thesis_status": {"select": {"name": status_select(status)}}}},
            timeout=10)
        u.raise_for_status()
        return True
