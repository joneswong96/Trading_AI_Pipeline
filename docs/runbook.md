# Runbook — 點 setup / 點跑 / 點睇 log

> 空殼：每完成一個 build step 就補返對應 section。

## Setup（Step 0 暫時得呢啲）

```powershell
cd C:\Users\jones.w\TradingSys\trading-auto
py -m pip install -r requirements.txt   # 用 py launcher，唔好用 python（會撞 Store alias）
Copy-Item .env.example .env   # 然後填 keys（唔好 commit）
```

## 跑 test

```powershell
python -m pytest tests/ -q
```

（有 make 嘅環境：`make test`）

## Step 1 — Capture 雙路對比（Jones 要做嘅嘢）

### 共同前置
1. 喺 TV save 好 5 個 layout（①4H+1H ②Renko/WMA+15m ③DXY1m+15s ④5m+1m ⑤30m）。
2. 將 5 條 layout URL 填入 `config/assets.yaml` 每個 screenshot 嘅 `url:`。

### 路線 1a（Playwright）登入一次
```powershell
py -m capture.screenshot --login
# 喺彈出嘅 browser 登入 TradingView（paid account），搞掂閂 browser。
# persistent profile 會記住 session（storage/pw_profile/，唔入 git）。
py -m capture.screenshot --once   # 試截一個 bundle 驗證
```

### 路線 1b（CDP 9222）開 Chrome
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\ChromeCDP"
# 喺呢個 Chrome 登入 TV，按 ①→⑤ 順序開 5 個 layout tab（唔好閂）。
py -m capture.tv_mcp --once       # 試截一個 bundle 驗證
```

### 跑 10×10 對比（Step 1c）
```powershell
py -m capture.compare --trials 10
# 報告：docs/capture_comparison.md → 交 Jones 揀主力路線
```

## 9333 — 專用 data-read instance（同 9222 capture 隔離）

9333 = 獨立 Chrome，做將來 DXY / H4·D·W OHLC / M2 multi-symbol 取數，唔阻住 9222 capture。
一條命令 ensure（health → 未起就 launch 持久 profile + gate layout → 驗證 → 報 ready/drift）：

```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto
py -m capture.tv9333 --ensure     # idempotent 冷啟動 + Fork B 校 chartType + verify
```

> ⚠️ **最常踩（重開前必睇）：`9333 port 冇上嚟` 或驗到 tab 唔啱 → 先「完全閂晒」ChromeCDP9333 profile（`C:\Users\jones.w\ChromeCDP9333`，喺 USERPROFILE 唔喺 LOCALAPPDATA）嗰個 Chrome 嘅所有 window，再 `py -m capture.tv9333 --ensure`。**
> Chrome 係 per-profile single-instance：若該 profile 已經開咗、但**當初 launch 冇帶 `--remote-debugging-port=9333`**，再 launch 唔會補返 debug port，只會把 URL 轉去現有 window → `--ensure` 會一直報 `9333 port 冇上嚟`。**唯一解 = 全閂該 profile 再 `--ensure`**（佢會帶 port 重新 launch）。

- **唔靠 MCP `layout_switch`**：直接開 saved-layout URL（g4=cpPWuLlN / g5=avpCVaw2）做 tab；純 Playwright CDP 通道（同 capture Route A 同一 proven accessor）。
- **9222 一個字都唔掂**：PORT 鎖死 9333，`launch` / `_verify` 有 `assert PORT != 9222`。

### P0 一鍵冷啟動 → ensure → 截圖（9333-only，唔掂 9222）
```powershell
# 1) 強制冷啟動（嚴格 filter，只殺 ChromeCDP9333；9222 嘅 ChromeCDP 唔中）
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  ? { $_.CommandLine -match 'ChromeCDP9333' } | % { Stop-Process -Id $_.ProcessId -Force }
# 2) ensure（idempotent launch + Fork B chartType 校正 + verify；已 up 唔重複開）
py -m capture.tv9333 --ensure       # ok=true = 4 pane type1 / ICMARKETS:XAUUSD / MACD present
# 3) ad-hoc 截圖（hygiene 前置：清 crosshair + bring_to_front，防 stale frame）
py -m capture.tv9333 --shot         # → storage/tv9333_shots/<ts>/
```
9333-only flag：`--ensure`（冷啟動+校+驗）｜`--launch`（淨 idempotent 冷啟動）｜`--health`（三態 down/up_no_target/healthy）｜`--verify`｜`--correct`｜`--shot`（未 healthy 會叫你先 --ensure）｜`--htf <bundle>`（g6_HTF 純讀 closed-bar → `<bundle>/htf_closed.json`）｜`--dxy <bundle>`（g7_DXY 純讀 closed-bar → `<bundle>/dxy_closed.json`）｜`--ohlc <bundle>`（g4/g5/g6 純讀 N 條 OHLC → `<bundle>/ohlc_history.json`，swing 偵測 input）。

### P1 HTF read（g6_HTF → htf_closed.json，餵 htf_override 4H/D/W direction）
**g6_HTF**（saved layout `pNqcbOmu`，1 tab × 3 pane = H4+D+W ICMARKETS:XAUUSD candles，9333-only）由 `--ensure` 連 gate tab 一齊開。`--htf` 純讀每 pane 嘅 **off1 closed-bar** OHLC → `close vs SMA(N)±band` 算方向（knob 喺 `config/assets.yaml` `htf_direction`，N=20/band=0.1%）→ 寫 `htf_closed.json`（`readings.{h4,d,w}.direction`）。**零 setResolution/setSymbol/setChartType（純讀，mirror `macd_closed.json`）。**
```powershell
# /analyze 接數 flow（HTF 由 vision g2 換成 deterministic）：
py -m capture.tv9333 --ensure                 # 確保 9333 + g6_HTF up（g6 冇 MACD → correct 階段 15s best-effort timeout 屬預期）
py -m capture.tv_mcp --once                    # 9222 capture（現狀不變，唔掂 9333）
py -m capture.tv9333 --htf storage\screenshots\<cycle_id>   # 寫 htf_closed.json 入同一 bundle
# analyze 讀 htf_closed.json：唔見/complete:false → STOP fail-loud，唔靜靜跌返 vision g2。
```
> ⚠️ **g6_HTF 唔入 `assets.yaml` 嘅 `screenshots[]`**（喺獨立 `htf_read` key）：因為 9222 capture（`tv_mcp`）只 iterate `screenshots[]`，加入會令佢喺 9222 搵唔到呢個 tab 而 loud-fail。HTF read 只行 9333。

### P2a DXY read（g7_DXY → dxy_closed.json，餵 confluence 個 dxy_state）
**g7_DXY**（saved layout，1 tab × 1 pane = DXY **15m** plain candles，9333-only）由 `--ensure` 連 gate/g6 一齊開。`--dxy` 純讀該 pane **off1 closed-bar** close → `close vs SMA(15m)±band` 算方向（knob 喺 `config/assets.yaml` `dxy_direction`，N=20/band=0.1%）→ 寫 `dxy_closed.json`（`reading.direction` = `BULLISH/BEARISH/NEUTRAL`，**trade-agnostic**）。CONFIRM/NEUTRAL/ADVERSE 喺 `/analyze` 配 trade 方向 `map_dxy_state` 先算。**零 setResolution/setSymbol/setChartType（純讀，mirror `htf_closed.json`）。**
```powershell
py -m capture.tv9333 --ensure                              # g4/g5 + g6_HTF + g7_DXY（g7 冇 MACD → 15s best-effort timeout 屬預期）
py -m capture.tv9333 --dxy storage\screenshots\<cycle_id>  # 寫 dxy_closed.json 入同一 bundle
# analyze：讀 reading.direction → map_dxy_state(dir, trade) → grade_from_layers 個 dxy_state；
#          唔見/complete:false → STOP fail-loud，唔靜靜跌返 vision g3。DXY 只封頂 grade，永不調入唔入(#18)。
```
> ⚠️ **g7_DXY 同 g6 一樣唔入 `screenshots[]`**（喺獨立 `dxy_read` key）。`dxy_read.url` 留空時 launch 安全跳過、`--dxy` 報 tab not found（唔 crash）。

### P2c swing-pivot read（g4/g5/g6 → ohlc_history.json，餵 swing SNR source）
`--ohlc` **一條連線純讀** g4 m5 / g5 m15 / g6 h4·d·w 每 TF ~300 條 closed-bar OHLC → 寫 `ohlc_history.json`（chronological、`bars[tf][-1]`=off1）。`analyze/swing_pivots.py` analyze-time 用 fractal（`config swing` k=2、strict `>`/`<`、no-repaint scan i∈[k,len-1-k]）算 swing high/low → 餵 `assemble_snr` 做 SNR source（dedup→1 層；major/minor=annotation only）。**零 setResolution/setSymbol/setChartType（純讀）；`htf_closed.json` 零郁。**

**/analyze 完整接數次序**（HTF/DXY/SNR 全 deterministic）：
```powershell
py -m capture.tv9333 --ensure                              # 確保 9333 四 tab up
py -m capture.tv_mcp  --once                               # 9222 capture（唔掂 9333）
py -m capture.tv9333 --htf  storage\screenshots\<cycle_id> # HTF 方向 + PDH/PDL/PWH/PWL
py -m capture.tv9333 --dxy  storage\screenshots\<cycle_id> # DXY modifier
py -m capture.tv9333 --ohlc storage\screenshots\<cycle_id> # swing OHLC history
py -m analyze.snr_levels    storage\screenshots\<cycle_id> <現價>  # 含 swing 嘅合併 SNR menu → grading
```
> ⚠️ swing OHLC 讀 g4/g5/g6 **既有 tab**（唔加新 layout）；guard：interval 配唔到→raise、每 pane symbol assert ICMARKETS:XAUUSD。

### M1 verify 涵蓋（2026-06-18 真 run 鎖實）
- getter **已驗返到值**：`symbol`→`ICMARKETS:XAUUSD`、`chartType`→`1`(Candles)、`interval`、`MACD present` 全部讀到。
  → **symbol / chartType drift 偵測係生效嘅**（唔係「未鎖實」）；`ok=true` = tab 齊 + symbol/type 啱 + MACD present。
- ✅ **M1.1（2026-06-18）chartType auto-correct（Fork B）**：`--ensure` 喺 panes ready 後 on-launch 逐 pane 校 chartType→Candles(1)，**9333-local、永不 re-save cloud layout**（cpPWuLlN/avpCVaw2 同 9222 共享）。chartType-19 真身 = **Volume Candles**（cosmetic real-OHLC，唔影響 OHLC/MACD 讀數）。`symbol` / MACD detect 嘅 auto-correct 仍留 M2。
- ⚠️ **M1 已知限制**：`--ensure` 只喺 **port 全 down** 先 launch 開 tab；若 instance **up 但 gate tab 缺/漂咗**，會 fail-loud `ok=false`，要照上面 ⚠️ 全閂再 `--ensure`（live 補缺 tab 嘅 self-heal = M1.1 候選增強）。

## 跑 pipeline

⏳ Step 6 接通 scheduler 先有。到時：`make run` / `python -m scheduler.run`

## 生產起動程序（Phase 1.5 Wake→Analyze Bridge + Phase 3）

> notify-only，永不落單（MT5 mirror 維持 dry-run）。全部絕對路徑，`cd trading-auto` 先。

### ① 起 webhook（ingest /alert）
```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto
py -m ingest.webhook_server          # uvicorn 起 :8000（PORT 由 .env 覆寫）；POST /alert
```
- ⚠️ **改 code 後要 restart 先生效**：呢個係 `uvicorn.run(app)`，**冇 `--reload`**。改咗 `ingest/` 任何 code → **Ctrl-C 停咗再重跑**，唔會熱更新。
- dev 想 auto-reload（會自動重載改動）：`py -m uvicorn ingest.webhook_server:app --reload --port 8000`（**生產唔好用 `--reload`**）。
- 健康檢查：`GET http://localhost:8000/health` → `{"ok":true}`。

### ② 起 invalidation watch（常駐 daemon，閉環 re-WAKE）
poll read-only 價源 → 價穿 active thesis 嘅 `invalidation` → emit `SYSTEM INVALIDATION` → POST /alert → break-cooldown 自動 re-WAKE。**只 emit event，唔改單、唔行動。**
```powershell
Set-Location C:\Users\jones.w\TradingSys\trading-auto
py -m output.invalidation_watch --daemon --interval 10   # 每 10 秒 poll（--interval 可調）
```
- **poll 價源**：`capture.tv9333.read_price_9333` = **備路 9333 g4 m5 off1 closed-bar close**（reuse 現有 `_HTF_OHLC_JS` accessor；off1 同全系統 closed-bar 紀律一致，殺 live jitter）——**9222 零接觸**。
- **無 active thesis → idle**：唔 poll 價（慳資源）；有 thesis 先讀價判穿。
- **9333 down / 讀唔到** → log warning + **skip 呢輪**（唔 crash、唔 mutate、唔 emit）。
- **防轟炸 dedup**：同一 `thesis_id+version` 嘅 breach **只 emit 一次**（狀態變 → `version+1` 新 key 先再 emit）。
- **點停**：**Ctrl-C**（graceful shutdown）。
- **前置**：webhook（①）要 up（POST 目標 `localhost:8000/alert`）＋ 9333 要 up（`py -m capture.tv9333 --ensure`）。

### ③ 全鏈一句 flow
```
TradingView alert → POST /alert → trigger.should_wake
  → (無 active thesis) 照規則 WAKE ┐
  → (有 active thesis) engine alert 只 log；INVALIDATION 破 → WAKE
        ↓ WAKE
  Telegram「✅ 夠料喇，撳 /analyze」+ append wake_queue.jsonl（consumed_by=null）
        ↓ Jones
  /clear（Fresh Eyes 清 context）→ /analyze
        ↓ Step 0 讀 wake_queue（timing+audit，唔餵方向）… Step 5 thesis emit
  thesis_log（append-only，version+1）+ storage/thesis/ backup + 回填 wake_queue.consumed_by
        ↓ push
  Telegram 5-line Execution Card（notify-only；dedup=thesis_id+status+version）
        ↓ 持倉期間
  invalidation_watch poll 價 → 價穿 invalidation → SYSTEM INVALIDATION → POST /alert
        ↺ 自動 re-WAKE（break cooldown）→ 叫 Jones 再 /analyze
```

### ④ `wake_queue.jsonl` vs `wake_log.jsonl`（兩個都喺 `storage/`，gitignored）
| 檔 | 角色 | 寫入 | 有冇被消費 |
|---|---|---|---|
| **`wake_queue.jsonl`** | **Phase 1.5 新 bridge 隊列**：機器可消費、帶 thesis linkage（`consumed_by`/`consumed_at`/`wake_id`/`window_events`）。/analyze Step 0 讀最新 `consumed_by=null`、Step 5 thesis emit 回填。 | `ingest.wake_queue.append`（webhook WAKE 時） | ✅ 會被 thesis emit 消費（1:1） |
| **`wake_log.jsonl`** | **舊 Phase 1 fanout log**：純 append 證物（engine/event/dir/reason），畀人眼/audit 回放，**唔會被消費、無 thesis linkage**。 | webhook `_append_wake`（同 Telegram/Notion fanout 一齊） | ❌ 淨 log，冇 consume 概念 |

> 兩個都喺 WAKE 時各寫一筆：`wake_queue` = 驅動 /analyze 消費同 thesis 閉環嘅**新橋**；`wake_log` = 保留嘅**舊 fanout 流水帳**。

## 睇 log

⏳ Step 6 先有。SQLite 喺 `storage/trading.db`；每 cycle 嘅檔案喺 `storage/screenshots|json|calls/<cycle_id>`。

## Troubleshooting

> 2026-06-14 Step 1 setup 實戰踩過嘅坑（Win11 + Program Files Python 3.11）。

### 環境 / Python
- **`python` 認唔到 / 彈「install from Microsoft Store」**：撞咗 Windows Store 嘅 app execution alias。**一律用 `py`**（Program Files Python 3.11，packages 喺 `--user` site）。想 plain `python` 行得返：Settings › Apps › Advanced app settings › App execution aliases，熄 `python.exe`/`python3.exe`。
- **`py -m pip install -r requirements.txt` 報 `UnicodeDecodeError: cp1252`**：requirements.txt 有中文註解，pip 預設用 cp1252 decode。檔已存成 **UTF-8 BOM** 解決；若再出，改用逐個 package 名裝（`py -m pip install pytest pyyaml python-dotenv playwright`）。
- **`playwright` 裸命令 not recognized**：script 喺 `...\AppData\Roaming\Python\Python311\Scripts`，唔喺 PATH。用 **`py -m playwright ...`**。
- **`Executable doesn't exist at ...chrome.exe`（route 1a）**：裝咗 playwright package 但未落載瀏覽器。`py -m playwright install chromium`（連 headless shell）。
- **print ✅/❌ 時 `UnicodeEncodeError: charmap`**：stdout 被 pipe/重定向時預設 cp1252。CLI entrypoint 已加 `force_utf8_stdout()`（base.py）；自己寫 script 都記住叫。

### route 1a（Playwright）
- **`--login` 撞 Google「This browser or app may not be secure」**：Google 封 automation browser 嘅 OAuth。**唔好用 Sign in with Google**，改用 TradingView **email + 密碼**。純 Google account 要先喺正常 Chrome 設密碼。
- **`--once` 報 5/5 但全部係登入牆**：未登入。private layout 登出會出「We can't open this chart layout for you」，截到圖照算 ✅。已加 `detect_login_wall` guard → 而家會標 `not_logged_in`。先 `--login` 登入妥當（喺同個 browser 開條 layout URL 見到真圖）先再 `--once`。session 存 `storage/pw_profile/`，過期要重 `--login`。

### route 1b（CDP 9222）
- **`ECONNREFUSED ::1:9222`**：CDP Chrome 冇開（或 port 撞）。開：`& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\ChromeCDP"`。開咗未：`Test-NetConnection localhost 9222 -InformationLevel Quiet`（True 先好跑）。
- **`搵唔到 <id> 嘅 tab` / `冇對應 tab`**：CDP Chrome 冇開齊 5 個 layout tab（或未登入）。要 5 個 layout URL 全部開做 tab 並 logged-in。睇實際開咗咩 tab：`py -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.connect_over_cdp('http://127.0.0.1:9222'); [print(pg.url) for c in b.contexts for pg in c.pages]; p.stop()"`。
- 注意 ChromeCDP profile（`--user-data-dir=...\ChromeCDP`）同你平時 Chrome、同 route 1a 個 `pw_profile` 係**三個唔同 profile**，各自要登入。
