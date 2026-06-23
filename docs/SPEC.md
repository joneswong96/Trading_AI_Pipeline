# docs/SPEC.md — trading-auto 完整規則 SPEC（single source）

> **地位**：本檔由 SSOT（`docs/master_plan_ssot.pdf`，即 Notion Master Build Plan 匯出）抄落 repo，係 implement 嗰陣嘅唯一依據。**唔可以自己亂作**；要更深細節睇返 Notion source 頁：📸Chart Analysis (Send Image Here)、🎯Live Trading Supporter Rules、五步：買賣警告信號強度、📚Methodology Reference。
> **更新規則**：SPEC 改動只可以由 Jones 發起；改咗要喺本檔頭注明日期。
> 最後同步：2026-06-11（含 Jones 同日新增嘅推送政策；同日 SPEC B source 更新已 sync：Anti-Failure 20→22、Day-Type Gate、Armed Order framing、Re-entry 規則、R:R 標準更新）。
> 2026-06-14（Jones 發起）：M0 layout restructure —— 15m 由 g2 搬去 g5（g5 = 15m+30m 兩格各帶 MACD），g2 還原純 Renko/WMA；gate TF 乾淨分 g4(1m+5m)/g5(15m+30m)，每格 MACD 讀得清。下面 §M0 Input bundle 表已更新。

---

## 0. 核心設計原則（不可違反）

1. **硬風控永遠 deterministic（Python）**：AI 永不直接覆寫最大風險、SL、日內熔斷、kill switch。
2. **Notify-only 係每個新 pipeline 嘅 floor**：先跑通「可審計輸出」，先至升執行（落單）。
3. **可回放／可審計**：每次輸出都要存 `截圖 + features.json + call.json`，可以用 log 重現任何一個 call。
4. **Human-in-loop（First Goal）**：第 5 步落單係人；AI 出 call 唔等於落單。
5. **可替換**：截圖方式（Playwright↔MCP）、LLM、asset list、策略模組都要可 swap（adapter pattern + config）。
6. **Fresh Eyes**：每張新截圖從零讀，唔可以 carry forward 上一張嘅判斷（起源：2026-03-02 carry forward 導致錯評，Long 75→60）。

---

## 🅰️ SPEC A — 截圖分析 SOP（Chart Analysis）

**輸入（自動）**：一張或多張 TradingView 截圖（15s / 1m / 5m / 15m / 30m + DXY 1m，全部帶 MACD）。AI 自動偵測 ticker、TF、CC、WMA Ribbon、Renko、SC structure、ICT 條件；**偵測唔到就標 ⚠️ 未能確認，唔好靠估**。

**方向**：唔好盲跟圖上 Score Panel；每次自動跑 **Long + Short 雙向 scoring**，兩邊都出分。

### 評分系統（兩個 Mode 各 100 分）

| 類別 | Trend Mode | SC Mode | 條件 |
|---|---|---|---|
| Trigger Score | 25 | 25 | DC=25, SUP/RES=20, Touch=15 |
| Trend Alignment | 25 | 15 | 4H/1H/15M/5M 各 +5（SC 各 +3.75）；雙TF DC 同步 +5 |
| Zone Score | 20 | 15 | Discount/Premium=20（SC 15），EQ=10（SC 7.5） |
| CC Checkbox | 10 | 10 | Confirmation Candle |
| Renko Signal | 10 | 10 | Renko(20)+Renko(50) 同向=10；單一=5；相反=0 |
| WMA Ribbon | 10 | 10 | 6 條線同色 |
| SC Structure | — | 10 | 結構改變成立 |
| SC Flip | — | 5 | 翻轉磚出現 |

**Action Labels（分數 → 行動）**：≥90 🚀 SNIPER（全倉）｜≥75 🔥 HIGH（標準倉）｜≥55 ✅ STAND（輕倉謹慎）｜<55 ❌ WAIT（唔入）｜Bull+Bear DC 衝突 = ⚠️ CONFLICT（嚴禁入）。

**HTF Override**：4H+Daily+Weekly 全同向時，逆向 trade 強制降級（STAND→WAIT、HIGH→STAND、SNIPER→HIGH）；順向不受影響。

**Geopolitical**：地緣衝突 XAUUSD 偏 Bullish（避險）；唔好假設其他資產跟金走。

**ICT 精修（Soft Mode，唔改方向只改 timing）**：自動偵測 Sweep / Displacement / MSS / Retest(FVG/OB/Breaker)。Logic（SOP scoring）決定值唔值得做，ICT 只令 entry timing 更準。Logic 出 WAIT/CONFLICT → 唔理 ICT，唔入。ICT 唔當獨立 confluence layer（避免 double-count）。

**Fresh Eyes Rule（必守）**：每張新截圖從零重讀 Renko 磚色 / WMA 顏色 / Score Panel / HTF / DC·SUP·RES 標記。嚴禁 carry forward 上一張判斷。

**輸出格式（Output 0–4）**：0 Signal Listing → 1 Scoring（雙向客觀分）→ 1.5 ICT 精修入場 → 2 Second Brain（獨立判斷，可同分數唔同意）→ 3 24H 預測 → 4 Trade Setup（Entry/SL/TP1-3/Lot/Risk%/入場條件）。自動化版可精簡成 push 用嘅 5 行，但完整 0–4 寫入 log。

**預設交易參數**：短線/scalp；Risk 1%；Lot 0.01；R:R 以 SPEC B「R:R 標準（2026-06-11 更新）」為準（TP 一律 1R → BE → trailing 2R–7R，取代舊「出 1R/2R/3R」）；SL 用最近 structure low/high（唔用固定點數）；Account ~US$600。

**Session（AEDT/Sydney）**：Asian 8am–4pm（金低波幅）；London 6pm–3am（中高）；NY 11pm–8am（最高）；London/NY overlap 11pm–3am = 最佳 scalp 時段。

---

## 🅱️ SPEC B — Live Trading Supporter Rules（gate / grade / tier / 行為）

**Master Rule**：AI 係 trader 嘅 wingman，唔係 gatekeeper。出分析／出 support；唔好主動 inject 風險警告（除非用戶明確問）。**Forbidden phrases**：唔好講「你應該停止交易」「walk away」「are you sure」等 unsolicited meta-coaching。

**Day-Type Gate（開市第一步，2026-06-11 新增）**：開市 30 分內定 TREND／RANGE day，盤中持續更新。**Trend day 判定** ＝ 5m ≥50 點單邊 ＋ 連續 HL/LH ＋ 突破有跟進 → 5m 升級做主導 bias，**4H/1H 冇 veto 權，只調注碼**（同向正常注／逆向半注）。**每個 call 要標明當前日型。**

**Armed Order framing（Trend day 出 call 方式，2026-06-11 新增）**：Trend day 行 Armed Order framing — **Setup／Trigger／Order／管理／有效期 5 樣齊先准出**；每次 frame 兩張（pullback ＋ breakout）；同一 setup WAIT 上限 2 次。

**Re-entry 規則（2026-06-11 新增）**：SL 被掃後 5 分內 5m 收返原方向 ＝ sweep 確認 → 同方向 re-entry 一次（SL 放新 sweep 極端值外，**上限 1 次**）。Notify-only 版做法：偵測到 sweep-reclaim pattern 就 push「re-entry 條件成立」提示。

**R:R 標準（2026-06-11 更新，取代舊「出 1R/2R/3R」）**：TP 一律 1R；+1R → SL 推 BE → 開 trailing（trailing 食 2R–7R）；窄 SL 2–4 點只限 momentum On Time 位，pullback／邊界用 5–8 點放結構外。

**MACD 4-TF Alignment Gate（入場閘）**：睇 M1 / 5m / 15m / 30m。≥3/4 同向 = Confirmation entry OK；<3/4 = 淨係 ANT 限價單。1H/4H 只做開場 bias，唔計入 gate。15s = scalp timing（調幾時入，唔調入唔入）。DXY 1m = inverse confirm（金應同 DXY 反向），唔投 gate 票。Histogram = momentum（唔係 volume）。

**Multi-Layer Confluence Grade（信心度 = layer count）**：同時 scan 所有 confluence source（Horizontal SNR / Diagonal TL / HPA 0.5 Fib / Broken S/R Flip / MACD alignment / Price Action / Liquidity Grab / Round Number / 3rd Touch）。1–2 layer → C（SKIP）；3 → B+（細注）；4 → A（可加 R）；5+ → A+（最高信心）。冇一個 source 係 primary，數總 layer。要 ≥1 個 5m/15m anchor（純 LTF stack 唔可當 B+）。
**⚠️ 計 layer 紀律**：gate 唔夠 3/4 時 MACD alignment 唔成立，唔可以當 layer；唔肯定嘅 source 寧缺莫濫（見 Anti-Failure #15）。

**DXY Modifier（唔計 layer）**：DXY 反向確認到位 = quality✅；橫行/同向 → grade 封頂 B+ + 細注。DXY 只調 grade/size，唔調「入唔入」或「入場時機」（過度用 DXY 卡入場 = Anti-Failure #18）。

**Expansion Leg Modifier（唔計 layer）**：乾淨快 → 正常/加信心；慢亂 → 降級細注；太長 → 唔好當 reversal fade；太短 → skip。

**Range / No-Trade Gate**：3+ 次掂邊界收唔穿、或 30+ 分鐘冇 5m 收盤破邊界 = RANGE → mid-band 一律 🚫 唔做。只有 5m 收盤破區間 + DXY confirm + gate ≥3/4 先畀方向。**Two-Strike 斷路器**：同一 band 連續 2 個方向 call 都被 invalidate → 強制宣告 chop、停止畀方向。

**Track A（市價）/ Track B（限價）+ 6 Entry Types**：可並行（兩個都中 = 兩個都食，各自計 SL/R）。Track B：Type 1（BO+50% 回調掛單，default）/ Type 2（切 15s 多重 confirm）/ Type 4（直接食 BO level，RR 較差）。Track A：Type 3（M1 HNS neckline react）/ Type 5（AOI 後突破前高低）/ Type 6（M1 DC candle reject + 收盤企穩）。限價落點可用 FVG/OB 精修縮 SL。

**Signal Tier（持倉管理，只有 🔴 = cut）**：🟡 YELLOW（單 wick / M1 hist flip）= note only，hold；🟠 ORANGE（M5 收盤逆向 / 2+ 逆向 candle / 近關鍵 SNR）= 可考慮 tighten；🔴 RED（M5 收盤+結構轉 HH/HL 翻 / HTF MACD flip / 主 SNR 破 / thesis 失效）= cut recommended。用 Signal Tier 代替 P&L 做 hold/cut（鼓勵遮住 P&L）。
**⚠️ Tier 色只用喺持倉管理**：setup read 唔用 tier 色，兩個系統唔可以撈亂。

**輸出風格**：Setup read 第一句必係 action call（IN / WAIT for [X+Y] / SKIP）；in-trade 第一句必係 tier flag。方向一律用 Long/Short（唔用 buy/sell/做多做空）。每個 WAIT 必帶 alert 價 + early trigger。「睇邊度」最多 2 個位（一上一下）。入咗倉即出「管理階梯」（綁價唔綁感覺）。

### 22 Anti-Failure Modes（premortem，當 guardrails；2026-06-11 由 20 條增至 22 條）

1 Gatekeeper｜2 Confirmation Bias｜3 Sycophancy｜4 Premature Defensive｜5 寫低≠做到｜6 Skip Pre-Marking｜7 MACD Laziness｜8 Single-Direction Prep｜9 Vague WAIT｜10 Re-analyzing Levels｜11 Calc Errors｜12 Recency Bias（entry 可快、regime 唔可快）｜13 Divergence Not Flagged｜14 Cheerleader/谷大 grade｜15 False Precision/扮讀到數｜16 漏 Mandatory Input（15s/DXY/Expansion Leg/30m）｜17 Range 內亂畀方向｜18 Modifier-as-Gate（DXY 卡入場）｜19 逆 M1·M5·M15 flow 入場｜20 DXY 1min noise 當大方向｜**21 Trend Day 仲用 Range 流程／4H veto 順勢升浪**｜**22 Snapshot 思維（frame 咗嘅 plan 必須 track 結局：trigger／invalidate／過期）**。

---

## 🅲 SPEC C — 五步信號強度（pattern strength，做 context 加權）

**賣出（看跌）**：M頭/雙頂 100%｜下跌旗形 80%｜菱形頂 65%｜箱型盤整 50%（危險別碰）。
**買入（看漲）**：上升楔形 100%｜上升旗形 80%｜W底/雙底 65%｜箱型 50%（別碰）。
**整合次序**：先睇 MA 定大方向 → 畫水平線搵關鍵 SNR → 睇 K 線型態確認進出場。
源頭：五步：買賣警告信號強度。

---

## 🅳 SPEC D — 三面框架 + 市場階段 + 相關性（深度方法論）

**核心邏輯**：基本面決定買咩、技術面決定幾時買、情緒面解釋點解郁。
**市場四階段**：A 吸籌（低量，❌唔 trade）→ B 突破（放量，✅觀察）→ C 回測（縮量，✅最佳入場）→ D 推升（順勢持倉，✅2R+）。
**Volume Profile**：VAH（貴/減倉）/ POC（最大量/強 S·R）/ VAL（平/吸籌）。
**FVG**：三 K 缺口，回補做支撐/阻力。
**Trailing**：固定距離 / ATR×2 / 結構停利（移到前 swing low/high）。
**相關性**：DXY 與 XAUUSD 負相關；USDJPY 強→金受壓。
**避險時段**：NFP/CPI 唔 trade。
完整細節 + Pine 範例 + 三個 AI Agent（Overreaction / Situational / Fundamental Analyst）見 Full Prompt v2 同 Prompt V1。

---

## 📲 推送政策（2026-06-11 Jones 新增，M0 起生效）

**只有狀態有變先 push**，觸發條件五種：
1. action 變（IN／WAIT／SKIP 轉態）
2. grade 變
3. trigger 價變
4. ANT plan 新出或失效
5. alert 價被掂

同一個 plan 冇變 → **淨寫 log，唔 push**。唔准每個 cycle 都 ping。
實現要求：dedupe 比較係 deterministic Python（比對今次 call 同上一次 pushed call），唔靠 LLM 判斷。

---

## 📐 M0 Input bundle 規格（截圖 layout）

**4 張圖（每張 2 個 chart，共 8 個）＋ 30m ＝ 9 個 chart**：

| 圖 | 內容 | 用途 |
|---|---|---|
| ① g1_4h_1h | XAUUSD 4H ＋ 1H（帶 MACD、SNR 線） | HTF bias ＋ 主要目標位 |
| ② g2_renko_wma | 1s Renko ＋ WMA ribbon（帶 W/D/4H/1H trend panel） | 純結構圖：Renko/WMA 確認 ＋ HPA 區 |
| ③ g3_dxy1m_xau15s | DXY 1m ＋ XAUUSD 15s | DXY modifier ＋ scalp timing |
| ④ g4_5m_1m | XAUUSD 5m ＋ 1m（IC Markets，帶 MACD） | Gate 投票 ＋ entry 結構 |
| ⑤ g5_15m_30m | XAUUSD 15m ＋ 30m（IC Markets，兩格帶 MACD） | MACD 4-TF gate 嘅 15m+30m 兩票（Anti-Failure #16） |

---

## 📸 Golden Sample — 2026-06-11 13:37 AEDT（prompt regression test 基準）

> 用途：① input→output 對照做 regression test（同一類市況，自動化版要出到同一個結論）；② 5 行 Call 格式範本。
> ⚠️ 呢個 sample 嘅 input 缺 30m（當日 layout 未補），所以 gate 只計到 3 TF——**呢個係 test input 特例，唔係常態**。Production layout 有齊 9 charts。

**當日市況**：4H/1H 大跌浪後，價 4,066.9 夾喺 4,057.05–4,073.77 range 中間；DXY 99.95–99.975 橫行；Asian session（最靜時段）。

**正確答案範本**：

```
WAIT for [5m 收盤破 4,057.05 或 4,073.77 ＋ DXY 反向確認] — 而家喺 range 正中間，🚫 唔做
Gate：M1 ✗（零軸搖擺）/ M5 ↓弱 / M15 ↓弱 / M30 ⚠️ 冇圖 → 2/4，唔夠 3/4 → 淨係 ANT 限價
Range Gate：兩邊各掂 3+ 次冇 5m 收盤破 → RANGE 確認，mid-band 唔做，Two-Strike 生效
睇邊度：下 4,057.05（5m 收穿＋DXY 升 → Short，TP 4,040→4,028.4，HTF 順向主 scenario）
　　　　上 4,073.77（5m 收上＋DXY 跌 → Long，但 W+D bearish HTF Override 強制降級細注）
ANT：限價 Short 4,073–4,074｜SL 4,078.5｜TP1 4,066 → TP2 4,057｜RR≈1.5–2
Grade：B+ 細注（3 layers；DXY 橫行 → 封頂 B+，0.01 lot）
Alert：4,057 / 4,074
```

**呢個範例示範咗嘅 SPEC 行為（regression checklist）**：
1. 第一句必係 action call（WAIT 必帶 trigger 條件 ＋ alert 價）
2. 雙向 scoring，唔盲跟任何 panel（4H panel 標 BULLISH 但圖面 bearish → 標 ⚠️ 矛盾，以圖面＋MACD 為準）
3. 缺 mandatory input（30m）→ 標 ⚠️ 唔好估
4. Range 內 mid-band 唔畀方向（Anti-Failure #17）
5. DXY 只封頂 grade，唔卡入場（Anti-Failure #18）
6. Session context（Asian ＝ 靜，動能等 London）
7. 「睇邊度」最多兩個位，一上一下

---

## 🛠️ Milestones 邊界（M0 焦點）

**M0 — 接通神經（單一 asset，notify-only）**
- Scope 凍結：淨係 XAUUSD、每 1 分鐘截一次；capture 雙路（Playwright＋TV MCP）對比後由 Jones 揀主力。
- Pipeline：截圖 → pre-check（DOM 讀價，唔用 OCR）→ Claude 跑 SPEC A（精簡）→ 出 5 行 Call ＋ marked 截圖 → Telegram push（推送政策約束）→ 寫 SQLite + Notion Call Log。
- 硬 floor 寫死：永不落單、永不判 action；MCP/程式淨係讀+通知。
- **Verify Gate**：跑通後連續行 ≥2 小時無 crash；跑 10 個 cycle，≥9 個「Telegram 收到（或正確 dedupe/skip）＋ 內容跟 SOP ＋ log 欄位齊 ＋ 無落單」先升 M1。

**M1+**（唔喺本階段 scope）：M1 gate/grade/tier Python 化 → M2 加美股/指數 → M3 半自動（paper broker、人 confirm、VPS、kill switch）→ M4 tick 數據 → M5 Ultra Goal 全自動。每關過 verify gate 先升。
