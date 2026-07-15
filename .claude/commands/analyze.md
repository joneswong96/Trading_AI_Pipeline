---
description: 手動 on-demand XAUUSD 分析（食訂閱、唔叫 API、唔使 key）：capture 一個新 bundle → 我睇 5 張圖跑 SOP → 出結構化 JSON + 5 行 call。唔 push、唔改任何檔。全部絕對路徑，喺邊層開 Claude 都用得。
---

# /analyze — XAUUSD 手動分析（manual on-demand 路）

你（Claude Code）係今次嘅**分析大腦**。
**硬規矩：唔好叫 Anthropic API、唔好用 ANTHROPIC_API_KEY、唔好 push。改檔界線（Phase 1.5，Jones 2026-07-04 修訂）：唔准改 repo 受控檔（code / config / contract / golden — 防 drift），但准寫/append `storage/` runtime artifacts（gitignored；同 Step 1 已寫 PNG / `macd_closed.json` 同一類）——即 Step 5 thesis emitter 寫 `thesis_log` / `storage/thesis/` / 回填 `wake_queue`。** 呢條係手動路，同 API 路（`analyze/claude_client.py`）+ golden regression 平行，唔好掂嗰邊。

## Rulebook（唯一依據，先 Read 佢哋做規則書，唔好自己亂作）
- SOP（分析規則 + 輸出 JSON schema + 5 行格式）：Read `C:\Users\jones.w\TradingSys\trading-auto\analyze\sop_prompt.py`，攞 `SOP_SYSTEM_PROMPT`。
- Golden contract（PASS 條件 §2 A–K）：Read `C:\Users\jones.w\TradingSys\trading-auto\docs\golden_contract.md`。

## 步驟（照順序）

### 0 — Wake context（Phase 1.5；timing + audit only，**禁餵方向**）
呢步淨係睇「點解而家跑 /analyze」＋ 為收尾 thesis linkage 記低 `wake_id`。**硬規：wake 嘅 engine / dir / reason 只做 timing 同 audit linkage，唔准餵入分析、唔准影響雙向 scoring（Fresh Eyes / 硬規格 #1）。** 分析方向照由圖 + gates 決定，同 wake 講咩無關。
PowerShell 跑（純讀，唔改檔）：
```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto; py -m ingest.wake_queue --latest-unconsumed
```
- 出到 `wake_id`（有未消費 wake）→ **記低 `wake_id`**（Step 5 thesis emit 要回填佢做 linkage）；可講一句 timing note：「今次係 `<trigger_reason>` 叫起（engines=…）」。**唔准由 wake 方向/engine 推分析方向或偏 scoring。**
- `wake: null`（manual run，冇 unconsumed）→ 照跑，Step 5 thesis 嘅 `wake_id` 留空。

### 1 — Capture 一個新 bundle
PowerShell 跑（絕對路徑，cwd 唔拘）：
```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto; py -m capture.tv_mcp --once
```
睇 output：
- `ok=True` 同 **5 個 shot 全部 ✅** → 由 `cycle=<id>` 嗰行攞 `<id>`，bundle = `C:\Users\jones.w\TradingSys\trading-auto\storage\screenshots\<id>\`。繼續 Step 2。
- 任何 `❌` 或 `ok=False` → **STOP，fail-loud**，照抄 error 話 Jones 知，唔好繼續分析：
  - `ECONNREFUSED ... 9222` → CDP Chrome 冇開（睇下面「開機」）。
  - `搵唔到 <id> 嘅 tab（want=...）` → 嗰個 layout tab 冇開／冇登入；開返齊 5 個 tab。
  - `搵唔到 TV chart tab` → CDP 連到但一個 chart tab 都冇。

### 1.5 — Live OHLC ingestion barrier（**必須早過讀圖、任何 gate、方向／WAIT、Thesis**）
Capture成功攞到`<bundle>`後，立即跑9333 OHLC producer嘅strict live mode；呢個係`LIVE_OHLC_INGESTION_BARRIER`，唔准搬落Step 2/3之後：
```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto
$ohlcOutput = & py -m capture.tv9333 --ohlc <bundle> --require-fresh 2>&1
$ohlcExit = $LASTEXITCODE
$ohlcOutput | ForEach-Object { Write-Output $_ }
$ohlcText = $ohlcOutput | Out-String
if ($ohlcExit -eq 0) {
  Write-Output "OHLC_FRESH_OK"
} elseif (($ohlcExit -eq 1) -and ($ohlcText -match '"complete"\s*:\s*false')) {
  Write-Error "DATA_INCOMPLETE — OHLC required TF count/schema incomplete；bundle已保留"; exit 1
} elseif ($ohlcExit -eq 2) {
  Write-Error "DATA_STALE — OHLC m5/m15 freshness failed；bundle已保留；檢查上面stale TF/close-time/age/threshold"; exit 2
} else {
  Write-Error "OHLC_PRODUCER_ERROR — producer exit=$ohlcExit；bundle已保留"; exit $ohlcExit
}
```

Exit contract（逐字執行，**non-zero係terminal abort**）：
- `0`：`complete=true`兼`freshness.overall.fresh=true`；先可以繼續Step 2。
- `1`兼producer summary明示`"complete": false`：報`DATA_INCOMPLETE`後**STOP**；若exit 1係exception／無合法summary，必須報`OHLC_PRODUCER_ERROR`，唔准誤標incomplete。
- `2`：報`DATA_STALE`後**STOP**；由producer output照抄每個stale TF嘅`latest_confirmed_bar_close_time`、`age_since_close_seconds`、`freshness_threshold_seconds`同reason，建議Jones檢查9333；**唔准自動restart／reload／navigate**。
- 其他non-zero：報`OHLC_PRODUCER_ERROR`＋原exit/error後**STOP**。

任何non-zero都必須保留bundle供audit，並且**唔准進入Step 2/3/4/5**：唔讀圖、唔跑`gates/`、唔作Long/Short/WAIT、唔砌Thesis JSON、唔叫`analyze.thesis_emit`、唔Telegram、唔更新invalidation watch、唔回填`wake_queue`。Step 0只係read-only記低`wake_id`，所以abort後該wake必須保持`consumed_by=null`／`consumed_at=null`，留俾下一次fresh run。`DATA_INCOMPLETE`／`DATA_STALE`／`OHLC_PRODUCER_ERROR`係data-quality terminal result，**絕對唔准轉譯成WAIT Thesis、NO_TRADE、market invalidation、Long/Short或grade downgrade**。

### 2 — Read 5 張圖（絕對路徑）
`C:\Users\jones.w\TradingSys\trading-auto\storage\screenshots\<id>\` 入面：
- `g1_4h_1h.png` — 4H(左)+1H(右)，HTF bias，各帶 MACD
- `g2_renko_wma.png` — Renko + WMA ribbon；右邊 trend panel = 5m/15m/1H/4H/D/W + Renko score
- `g3_dxy1m_xau15s.png` — DXY 1m(左) + XAU 15s(右)
- `g4_5m_1m.png` — 5m(左) + 1m(右)，各帶 MACD = **gate TF**
- `g5_15m_30m.png` — 30m(左) + 15m(右)，各帶 MACD = **gate TF**

### 3 — 跑 SOP（照 rulebook STEP 1–8）
**大原則（M1 phase 1，2026-06-15；MACD 數 2026-06-17 promote 後例外）：你淨係做 vision —— 由圖 crop-read 原始數字 / 讀結構事實（**MACD gate 數例外：由 `macd_closed.json` 讀 closed-bar off1，唔再 crop legend**）。所有 rule judgment（day-type / MACD gate / range / grade / HTF override / expansion-leg / two-strike / signal-tier）一律交 `gates/` 嘅 Python deterministic function，唔好自己判、唔好心算。** 讀完數行嗰條 `py -c`，攞返嘅 verdict 直接入 JSON。`gates/` 嘅判斷 = 唯一權威；同 SOP prompt 文字有出入以 `gates/` 為準（已 table-driven 測過、可回放）。

- **Day-Type 判定（deterministic，STEP 1 第一步）**：你讀結構事實（5m 單邊移動點數、有冇連續 HL/LH、突破有冇跟進，加 range 結構：掂邊界次數 / 有冇 5m 收破 / 幾耐冇破），交 function：
  `py -c "import json; from gates.day_type import compute_day_type; print(json.dumps(compute_day_type(fivemin_move_pts=_, consecutive_hl_lh=_, breakout_with_followthrough=_, boundary_touches=_, fivemin_close_broke=_, minutes_since_break=_)))"`
  攞 `day_type` 入 JSON。**TREND**（≥50pt 單邊+HL/LH+跟進）→ Armed Order framing；**RANGE** → mid-band 唔畀方向；**NEITHER**（regime 未確認）→ **唔開 Armed Order、唔用 trend-day「4H/1H 冇 veto」、亦唔當 range mid-band 自動封方向**；default = WAIT/觀望，要 5m 收破 + DXY confirm + gate ≥3/4 先畀方向。**唔好自己定 day_type。**
- **MACD 4-TF gate — Step A 讀數（closed-bar off1，由 capture 寫入 `macd_closed.json`）**：由 `<bundle>\macd_closed.json` 嘅 `readings.{m1,m5,m15,m30}` 攞 closed-bar (off1) MACD `hist/macd/signal`，**唔再 vision crop-read live-edge legend**（promote 2026-06-17：macd_gate shadow 5/5 fidelity-clean、0 disagree；Path X = MCP closed-bar off1，**gate 邏輯不變**）。
  - **closed bar（off1）= 已收嗰支**，唔受半成形 bar 嘅 live jitter 影響（shadow R3 證實 live-edge 撞 crossover 會瞬間翻 gate）。capture（route 1b，9222 同一條 Playwright 連線）用 `chartsCount()`+`chart(i)` 攞齊兩 pane、`valueAt(lastIndex-1)` 寫入 bundle。
  - **replayable 保住**：logged 數對 **bundle 嘅 `macd_closed.json`（凍結 artifact）**，唔對 live；有疑問 re-read **同一 bundle** 個 json，唔好攞 live 對（MACD 每 tick 漂）。
  - `complete:false` 或某 TF 唔喺 `readings` → 該格傳 `None`（**唔准估**，Anti-Failure #15）；function 當 NEUTRAL（唔投票）。
  - `macd_closed.json` **完全唔見**（舊 bundle / capture off1 fail）→ **STOP fail-loud**，照講俾 Jones 知，**唔好靜靜跌返 vision live-edge**（避免 closed/live 撈亂、破 replay）。
  - （可選 audit）想核對 → crop 嗰格 PNG legend 睇 **live-edge** 做參考，但 **legend = live-edge ≠ off1**，唔好攞嚟當 gate input。
- **MACD 4-TF gate — Step B 判定（deterministic，唔好自己判）**：喺 `trading-auto` 行——
  ```powershell
  Set-Location C:\Users\jones.w\TradingSys\trading-auto
  py -c "import sys,json; sys.stdout.reconfigure(encoding='utf-8'); from gates.macd_gate import compute_macd_gate; print(json.dumps(compute_macd_gate({'m1':{'hist':_,'macd':_,'signal':_},'m5':{'hist':_,'macd':_,'signal':_},'m15':{'hist':_,'macd':_,'signal':_},'m30':{'hist':_,'macd':_,'signal':_}}), ensure_ascii=False))"
  ```
  攞返嘅 `m1/m5/m15/m30`（三態）、`score`、`gate_pass`、`display` 直接入 JSON `gate{}` + `gate_pass`（`direction` 供參考）。**3-state**：`hist>0 且 macd>signal`=BULL；`hist<0 且 macd<signal`=BEAR；其餘=NEUTRAL（唔投票）。`score`=主方向對齊 TF 數，`gate_pass=score≥3`。
- **Range 判定（deterministic）**：你由圖讀結構事實（掂邊界次數、有冇 5m 收盤破邊界、幾耐冇破、上下邊界價、現價），交 function：
  `py -c "import json; from gates.range_gate import compute_range_gate; print(json.dumps(compute_range_gate(boundary_touches=_, fivemin_close_broke=_, minutes_since_break=_, bounds=[_,_], price=_)))"`
  攞 `range_confirmed / price_in_midband / allow_direction` 入 JSON。RANGE 確認 + mid-band → action=WAIT、🚫 唔畀方向（Anti-Failure #17）。
- **Expansion-Leg 判定（deterministic，modifier，唔計 layer）**：你讀 leg 形態（`quality`: clean/choppy；`length`: normal/too_long/too_short），交 function：
  `py -c "import json; from gates.expansion_leg import evaluate_expansion_leg; print(json.dumps(evaluate_expansion_leg(quality='clean|choppy', length='normal|too_long|too_short')))"`
  攞 `verdict/grade_effect`：POSITIVE=加信心｜DOWNGRADE=降級｜DONT_FADE=太長唔好逆做｜SKIP=太短唔做。只調 grade/size 或提示，**唔調入唔入時機**（Anti-Failure #18）。
- **DXY modifier 判定（deterministic，9333 純讀 — 唔再 vision 讀 g3 1m）**：
  - **Step A 讀方向**：由 `<bundle>\dxy_closed.json` 嘅 `reading.direction` 攞 DXY 方向（`BULLISH/BEARISH/NEUTRAL`；close-vs-SMA(15m)±band，off1 closed-bar；producer = `tv9333 --dxy <bundle>`，knob 喺 `config/assets.yaml` `dxy_direction`）。`dxy_closed.json` **唔見** 或 `complete:false` → **STOP fail-loud**，照講俾 Jones 知，**唔好靜靜跌返 vision g3**（保 replay、唔撈 source；同 `macd_closed.json`/`htf_closed.json` 同一紀律）。
  - **Step B map state（配你個 trade 方向，per scored direction）**：
    `py -c "from analyze.dxy_state import map_dxy_state; print(map_dxy_state('<BULLISH|BEARISH|NEUTRAL>','<Long|Short>'))"`
    DXY 同金 **inverse**：trade Long → DXY BEARISH=CONFIRM／BULLISH=ADVERSE；trade Short → 反轉。**DXY NEUTRAL，或 action=WAIT／`day_type=NEITHER`／未定方向 → 一律 NEUTRAL（寫死）**。雙向 frame（pullback+breakout 各一張）→ Long/Short **各 map 一次**（CONFIRM/ADVERSE 視方向相反）。
  - 攞返個 state 入 JSON `dxy_modifier`，並餵 `grade_from_layers(..., dxy_state=<state>)`。**只封頂 grade/size（NEUTRAL/ADVERSE→B+），永不調入唔入／入場時機（#18）；deadband 殺 1m noise（#20）。** `confluence.py` 零改。
- **SNR 精確價（deterministic menu，P2b Tier 1 + P2c swing）+ layer-attribution 契約**：數 confluence layer 前，攞精確 SNR menu 做**價格參考**（**唔改 layer 點數規則**）。
  - **menu 來源（deterministic）+ call-site**：`<bundle>\htf_closed.json` 嘅 `readings.{d,w}.high/low` = **PDH/PDL/PWH/PWL** ＋ config `key_levels`（pass-through）＋ round numbers（$50 grid、$100 位 major）＋ **P2c 自動 swing pivot**（`swing_high`/`swing_low`，fractal 掃 OHLC 歷史、TF-tiered、no-repaint）。OHLC已由Step 1.5 strict producer寫好兼驗fresh；**呢度唔准再用non-strict `--ohlc`重跑或繞過barrier**。`<現價>` = 你由chart讀到嘅spot：
    ```powershell
    Set-Location C:\Users\jones.w\TradingSys\trading-auto
    py -m analyze.snr_levels <bundle> <現價>   # 出含 swing 嘅合併 menu（無 ohlc_history → 退化 P2b）
    ```
    出 `levels[]`（同價去重、標 `sources`，例 `swing_high(W,major)`）＋ `nearest`（距現價最近 + `dist`），餵下面 layer-attribution 契約。`htf_closed.json` 唔見 → menu 退化成淨 round + key_levels（唔 STOP）。
  - **layer-attribution 契約（`confluence.py` 零改，menu 只令價精確 + 去重）**：
    1. **vision 仍係 layer 計數者，唔可減 coverage**：menu **冇覆蓋**嘅 horizontal SNR（你喺圖見到嘅其他位）**vision 照數**。menu 只精確化「已知 objective 位」，唔係 SNR 全集。
    2. **cross-source dedup（唔好雙計）**：容差（`dedup_tol`）內，**vision 位 ↔ menu 位（PDH/round/key_level）視為同一層**，唔好「vision 一層 ＋ deterministic 一層」雙計。
    3. **Round Number 最多當 1 個 layer type**：唔好每個 round 價各加一層（menu 列幾個 round 價只係參考，count 仍 = 1）。
    4. **menu 角色 = 精確價 ＋「現價 near SNR」boolean（`nearest.dist ≤ near_level_usd`，原值 1.5 不變）＋ 去重參考**；layer **count 仍由你按 sop STEP 6 原規則出** → `confluence.py` 真零改。
    5. **swing pivot（P2c）= 普通 SNR source**：dedup 後同其他 SNR source 一樣**最多算返原規則層數**（撞 PDH/PWH/round/key_level 容差內 = 同一層）。**`major`/`intermediate`/`minor` = annotation only**（source tag 俾你/vision 衡量重要性），**唔改 deterministic 層數 / grade weight**。
  - **Tier 3 留 vision**：swing high/low 結構位、diagonal TL、broken S/R flip = 結構判斷，**menu 唔覆蓋、vision 繼續數**（[[input-determinization-boundary]] P3）。
  - `htf_closed.json` 缺 high/low（舊 bundle）→ menu 嗰幾個 source 自動跳過，**vision 照數 fallback**（SNR 唔似 direction 要 source 純度，唔 STOP）。
- **Grade 判定（deterministic）**：你數總 confluence layer（**gate 唔過 3/4 時 MACD 唔當 layer**；ICT/FVG/OB 唔當 layer，Anti-Failure #14），交 function：
  `py -c "import json; from gates.confluence import grade_from_layers; print(json.dumps(grade_from_layers(<layers>, has_5m_or_15m_anchor=<True|False>, dxy_state='CONFIRM|NEUTRAL|ADVERSE')))"`
  攞 `grade` 入 JSON。**唔好自己定 grade**（B+ 封頂規則 function 已包：冇 5m/15m anchor、DXY NEUTRAL/ADVERSE）。
- **HTF Override 判定 — Step A 讀方向（closed-bar，由 9333 寫入 `htf_closed.json`）**：由 `<bundle>\htf_closed.json` 嘅 `readings.{h4,d,w}.direction` 攞 **4H / Daily / Weekly** 方向（deterministic：off1 closed-bar，close vs SMA(N) ±band 死區，knob 喺 `config/assets.yaml` `htf_direction`），**唔再 vision 讀 g2 trend panel**（P1 接數 2026-06-20：Approach A 靜態 3-pane `g6_HTF`(pNqcbOmu) 純讀 OHLC，**gate 邏輯不變**）。
  - **producer flow**：`/analyze` = `tv9333 --ensure`（確保 9333 + g6_HTF up）→ 9222 capture（現狀不變）→ `tv9333 --htf <bundle>` 寫 `htf_closed.json` → 讀返餵 gate。
  - `htf_closed.json` **唔見** 或 `complete:false`（g6_HTF tab 缺/未 ready）→ **STOP fail-loud**，照講俾 Jones 知，**唔好靜靜跌返 vision g2**（保 replay、唔撈 source；同 `macd_closed.json` 同一紀律）。
  - 某 TF `direction:"NEUTRAL"`（死區 / history < N）→ 照傳 `'NEUTRAL'`：gate `_norm()`→`None`→唔 aligned→**唔觸發**（safe，已核 `htf_override.py:17-26`）。
- **HTF Override 判定 — Step B（deterministic，唔好自己判）**：用上面 3 個方向 + 你個 trade 方向 + 現 tier（= 你 grade 對應級，見下），交 function：
  `py -c "import json; from gates.htf_override import compute_htf_override; print(json.dumps(compute_htf_override(htf_4h='BULLISH|BEARISH', htf_daily='_', htf_weekly='_', trade_direction='Long|Short', tier='SNIPER|HIGH|STAND|WAIT')))"`
  攞 `htf_override_triggered / tier_out` 入 JSON。**4H+D+W 全同向 且 trade 逆向** → triggered=true、tier 降一級（SNIPER→HIGH→STAND→WAIT）；三者唔齊同向或順向 → 唔觸發。**唔好自己判。**
  - **tier ↔ grade = 同一把 4 級尺**（A+=SNIPER｜A=HIGH｜B+=STAND｜C=WAIT）：傳入 `tier` = 你 grade 對應級；triggered → 實跌一級；`tier_out` 換返 grade 做**最終 grade**（WAIT=C → action SKIP/WAIT）。**所以唔會出「grade A+ 但 tier WAIT」兩 label 打架** —— override 即係 grade 實跌一級，5 行第 3/4 句寫明「因逆 aligned-HTF 降級」。（contract §G / SPEC A）
- **Two-Strike 斷路器（deterministic，畀方向前先過）**：同一 band 若近期有方向 call 記錄（Jones 提供 / 你 track 嘅結局，Anti-Failure #22；冇就跳過，**唔自己作** prior call，Fresh Eyes #6），交 function：
  `py -c "import json; from gates.two_strike import evaluate_two_strike; print(json.dumps(evaluate_two_strike([{'band':'<id>','direction':'Long','invalidated':True},{'band':'<id>','direction':'Short','invalidated':True}])))"`
  `chop=true` → **停畀方向、宣告 No-Trade（chop）**，唔好再喺嗰 band 出方向（SPEC B / contract §B）。
- **Signal Tier（deterministic，淨係持倉中先用）**：若 Jones 講明**而家持緊倉**（in-trade），第一句改出 **tier flag**（🟡/🟠/🔴），**唔係** setup action call —— setup read（WAIT/IN/SKIP）一律唔出 tier 色，兩系統唔撈亂（contract §H / CLAUDE.md）。你讀 in-trade 訊號（SPEC 全表 13 個）交 function：
  `py -c "import sys,json; sys.stdout.reconfigure(encoding='utf-8'); from gates.signal_tier import evaluate_signal_tier; print(json.dumps(evaluate_signal_tier({'single_wick':False,'m1_hist_flip':False,'single_counter_candle':False,'spread_widening_brief':False,'m5_close_against':False,'reversal_candles_2plus':False,'m5_macd_hist_flip':False,'near_key_snr':False,'dxy_sharp_adverse':False,'m5_close_struct_flip':False,'htf_macd_flip':False,'major_snr_break':False,'thesis_invalidated':False}), ensure_ascii=False))"`
  function 返嘅 `action`（cut/tighten/hold）**淨係內部 flag**；出俾 Jones 嗰句**一定係建議 + 「你決定」**，唔可以變「已幫你 cut / 已 tighten」（SPEC §Output Style、Anti-Failure #1 Gatekeeper / #4 Premature Defensive）。措辭固定：
  - 🟡 `YELLOW FLAG — note only`（hold）
  - 🟠 `ORANGE FLAG — 可考慮 tighten`
  - 🔴 `RED FLAG — cut suggested，你決定`
  tier=NONE → 冇 flag，正常持有。
- 次序：Day-Type → Range gate（含 Two-Strike）→ MACD 4-TF gate → DXY/Expansion modifier → layer-count grade → HTF override（讀 `htf_closed.json` 嘅 4H/D/W direction）。**以上 day-type / gate / range / grade / HTF override / expansion / two-strike / signal-tier 全部由 `gates/` 嘅 `py -c` 判，你只負責讀數讀結構，唔自己判。**
- **Trend-day Armed Order（`day_type=TREND` 出 armed order 時，contract §2.A）**：每張框單要齊 **5 元素，缺一即 incomplete，唔准淨係出 alert 價**：
  🎯 **Setup**（位/結構）｜⏰ **Trigger**（觸發條件）｜💣 **Entry｜SL｜TP**（**TP 寫死 = 1R**，即 entry↔SL 嘅距離，**唔好擺 2R**；SL=最近 structure low/high）｜📐 **管理**（到 +1R → SL 推 BE → 開 trailing **食 2R–7R**；2R+ 靠 trailing，唔靠固定 TP）｜⌛ **Expiry**（有效期）。
  雙向**各 frame 一張**（pullback + breakout）。輸出加 `armed_orders` 欄位（array，每個含上面 5 元素），five_line_call line 2/5 要帶 Entry/SL/TP/expiry。
- 守 contract §2 A–K：forbidden phrases 一句都唔出；每個 WAIT 必帶 alert + trigger；「睇邊度」≤2；setup read 唔用 tier 色；方向 Long/Short。

### 4 — 出兩段（輸出喺對話，唔好寫檔）
**(a) 結構化 JSON** — 照 SOP schema 出齊：
`day_type / gate{m1,m5,m15,m30,score,display} / gate_pass / range_confirmed / range_bounds / price_in_midband / action / grade / confluence_layers / dxy_modifier / htf_override_triggered / htf_stack / forbidden_phrases_count / wait_has_alert / wait_alerts / track / macd_readings / five_line_call`
+ `armed_orders[]`（**`day_type=TREND` 出 armed order 時必齊**，每個含 `setup / trigger / entry / sl / tp / rr / management / expiry`；缺 SL/TP/expiry = incomplete）。

**(b) 5 行 call**（人睇）— 將 `five_line_call` 用 `|||` 拆做 5 行 print，照 contract §2.H：
1. action call（`🚫 WAIT for […]` / `✅ IN — Long/Short` / `⏭ SKIP — …`，帶 alert 價）
2. 而家做咩（Track A 市價 / Track B 限價 / range mid「坐定定，唔好追」）
3. Grade + gate score（例：`Grade：C – SKIP（gate 2/4 <3；0 layer）`）
4. 點解（一句）
5. 跟住睇邊度（≤2 個位，一上一下，各帶 alert 價 + trigger）

### 5 — 收尾（含 Phase 1.5 thesis emitter）
- 報一句 bundle 路徑（`...\storage\screenshots\<id>\`，可回放）。
- **Thesis emit（每次 /analyze 都做，status 含 WAIT/NO_TRADE → wake 消費 ↔ emit 1:1）**：將你 Step 4 出嘅 5 行 call + gates 結果 map 成 Thesis JSON，交 emitter 寫（**你唔准自己手寫 DB**；emitter 做 validate → append → backup → 回填）：
  - Thesis JSON 欄位：`{thesis_id?(缺自動生), status, dir, entry, sl, tp1, tp2, invalidation, valid_until, rationale, wake_id?(= Step 0 記低嗰個，缺就留空)}`。status map：armed order → `ARMED`；已 IN → `IN_TRADE`；WAIT → `WAIT`；SKIP → `NO_TRADE`。actionable（ARMED/IN_TRADE）必帶 dir(Long/Short)/entry/sl/valid_until，否則 emitter fail-loud。
  - 跑（`storage/` runtime write，唔改受控檔）：
    ```powershell
    Set-Location C:\Users\jones.w\TradingSys\trading-auto
    '<你砌好的 Thesis JSON 一行>' | py -m analyze.thesis_emit
    ```
    出 `{ok:true, thesis_id, version, backup, wake_consumed}` → 報一句：thesis_id / version / 有冇回填到 wake。`ok:false`（validation）→ 照抄 error，**唔准當寫咗**。
- **再 confirm：冇 push、冇叫 API、冇改 repo 受控檔（只寫咗 storage/ thesis artifacts）。** 想留底由 Jones 自己 copy。

---

## 開機（打 /analyze 之前要 ready）
1. CDP Chrome 開咗：
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\ChromeCDP"
   ```
2. 喺嗰個 Chrome 開齊 **5 個 TradingView layout tab** 並登入：
   g1 `chart/X8AjBAIW/` ｜ g2 `chart/paH6jur7/` ｜ g3 `chart/ocVwlz2C/` ｜ g4 `chart/cpPWuLlN/` ｜ g5 `chart/avpCVaw2/`
3. 確認 port listen：`Test-NetConnection 127.0.0.1 -Port 9222 -InformationLevel Quiet`（回 `True` 先打 /analyze）。
