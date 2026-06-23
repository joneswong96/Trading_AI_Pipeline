"""Step 3：Claude vision client（Q8=A：Sonnet）。

真・inference **已 wire**，但 **gated by ready()**：缺 ① ANTHROPIC_API_KEY（.env）或
② sop_prompt.SOP_SYSTEM_PROMPT（golden 驗完先填）就 raise —— **唔跑、唔花錢、唔裝 anthropic**
（守 floor + Anti-Failure #15，唔靜靜出垃圾 call）。兩樣齊 + `pip install anthropic` 就即走。

硬 floor：呢個 client 淨係「讀圖 → 出結構化 call」，永不落單、永不覆寫風險（核心原則 #1）。
Fresh Eyes：唔接受 prior-call 參數，唔 carry forward。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .sop_prompt import SOP_SYSTEM_PROMPT, build_messages, prompt_ready


@dataclass
class AnalyzeResult:
    call: dict          # 結構化 call（畀 call_writer 拆 features/call.json + 5 行）
    raw_text: str       # Claude 原文（debug / 回放）
    model: str


class AnalyzeClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def ready(self) -> tuple[bool, str]:
        """齊唔齊料真・跑。回 (ok, 缺乜)。"""
        if not self.api_key:
            return False, "缺 ANTHROPIC_API_KEY"
        if not prompt_ready():
            return False, "SOP_SYSTEM_PROMPT 未填（golden-sample 未驗）"
        return True, ""

    def analyze(self, screenshot_paths: list[str], *, asset: str = "XAUUSD") -> AnalyzeResult:
        ok, missing = self.ready()
        if not ok:
            raise NotImplementedError(
                f"analyze gated：{missing}（落 .env ANTHROPIC_API_KEY + 填 "
                f"sop_prompt.SOP_SYSTEM_PROMPT 先可真跑；inference 已 wire）")

        from anthropic import Anthropic   # lazy import：未裝 anthropic 都唔影響 module import
        client = Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model, max_tokens=2048,
            system=SOP_SYSTEM_PROMPT,
            messages=build_messages(screenshot_paths, asset=asset))
        text = "".join(getattr(b, "text", "") for b in resp.content)
        call = json.loads(_extract_json(text))
        return AnalyzeResult(call=call, raw_text=text, model=self.model)


def _extract_json(text: str) -> str:
    """由 Claude 回文抽第一個 JSON object（wire 真 call 嗰陣用）。"""
    start, depth = text.find("{"), 0
    if start < 0:
        raise ValueError("回文冇 JSON object")
    for i in range(start, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return text[start:i + 1]
    raise ValueError("JSON object 唔完整")
