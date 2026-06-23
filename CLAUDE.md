# Project: trading-auto

## Goal (current)
- M0: 自動 screenshot → Claude vision 跑 SOP → 5 行 Call → Telegram + Notion log. Notify-only. 單一 asset: XAUUSD.
- 進度同每步 verify 見 ../PLAN.md（v2，2026-06-11 已批）。

## Non-negotiables
- 硬風控 deterministic (Python). LLM 永不直接落單/覆寫風險.
- 每個新 pipeline floor = notify-only. 本 repo 永不接 broker API（M3 先講，要 Jones 批）.
- 每次輸出可回放: 存 screenshot + features.json + call.json.
- Fresh Eyes: 每張新圖從零讀, 唔 carry forward 上一 cycle 判斷入 prompt.
- 推送政策: 狀態有變先 push（action 變/grade 變/trigger 價變/ANT 新出或失效/alert 被掂）；plan 冇變淨 log. Dedupe 係 deterministic Python, 唔靠 LLM.
- Pre-check 讀價用 Playwright 由 TradingView DOM 讀, 唔准用 OCR.
- Signal Tier 色（🟡🟠🔴）只用喺持倉管理；setup read 第一句係 action call, 兩個系統唔撈亂.

## User profile
- Name: Jones / TZ: Australia/Sydney / 繁體中文+廣東話回覆
- First Goal: AI 出 call, 我手動落單. Ultra Goal: 全自動唔使 monitor.
- 工作方式: 有歧義嘅決定（model/路線/SPEC 解讀）開 question 俾 Jones 揀, 唔好自己 default.

## Markets (phased)
- M0: XAUUSD. M2 加: 美股, 指數. config: config/assets.yaml

## Input bundle (M0 layout) — 2026-06-14 restructure
- 5 張 layout = 9 個 chart:
  ① g1 4H+1H ② g2 1s Renko/WMA(純結構) ③ g3 DXY 1m+XAU 15s ④ g4 5m+1m ⑤ g5 15m+30m
- gate TF 乾淨分 2 張：g4=1m+5m、g5=15m+30m，**每格都要有讀得清 MACD pane**（Anti-Failure #16）.
- 4H/1H 只做開場 bias、冇 veto（唔計入 gate）.

## Capture (Q2=C 已拍板 2026-06-14)
- **主力 = route 1b TV MCP (CDP 9222)**：對比 10/10、6.6s/bundle（route 1a 24.9s）。報告 docs/capture_comparison.md.
- **Fallback = route 1a Playwright**（核心原則 #5 可替換）.
- 前置：部機長開 `chrome --remote-debugging-port=9222 --user-data-dir=%LOCALAPPDATA%\ChromeCDP`，開齊 5 個 layout tab 並登入 TV（一閂就截唔到）.
- Guard：登入牆 → ok=False (not_logged_in)；URL 配唔到 → loud fail（唔靜靜截錯 tab）.
- 截圖節奏：每 1 分鐘 (Q4=A). Step 6 scheduler 用 route 1b.

## LLM (Q8=A, Jones 2026-06-11 拍板)
- 分析用 Claude Sonnet (vision). 成本靠 pre-check + 推送 dedupe 控制.
- Deterministic 計算 (pre-check/dedupe/M1 gates) 用 Python, 唔用 LLM.

## 現行模式 (2026-06-15)：手動 on-demand `/analyze`（食訂閱、唔叫 API、唔使 key）
- 打 `/analyze`（.claude/commands/analyze.md，TradingSys + trading-auto 兩層都有）→ capture 一個 bundle → Claude Code 睇 5 張圖跑 SOP → 出 JSON + 5 行 call，**唔 push、唔改檔**.
- 分析 rulebook = analyze/sop_prompt.py 嘅 `SOP_SYSTEM_PROMPT` + docs/golden_contract.md（APPROVED & LOCKED）.
- logged macd_readings 對 **captured PNG**（replayable），唔對 live；疑問 re-crop 同一 bundle.
- API 路（analyze/claude_client.py，wired 但 gated by ready()）+ golden regression（tests/test_golden_regression.py，skip-until-key）**留俾將來無人值守自動版**，而家唔郁.

## Output
- 5 行 Call: 結論(方向/入唔入) / 而家做咩 / SL·TP / 點解(一句) / 跟住睇邊度
- Push 附一張 marked 截圖 (Q10=C): publish/marker.py 用 Pillow. M0 = level legend box（TV 價軸 canvas, DOM 攞唔到 price↔pixel, 2026-06-14 證實）; 精準水平線 defer M2/M3 TV MCP（price_to_y/mark_chart 已備）.
- 完整 Output 0–4 寫入 storage/calls/.

## Spec
- 全部規則喺 docs/SPEC.md (由 SSOT master_plan_ssot.pdf 抄落嚟, single source). gate/grade/tier 以 SPEC 為準. 唔可以自己亂作.

## Run
- make dev / make test / make run（Windows 冇 make 就用 docs/runbook.md 嘅對應 python 指令）
- test: python -m pytest tests/ -q
