# Golden Output Contract（SPEC B 版）— ✅ APPROVED & LOCKED（2026-06-14）

> **地位**：golden self-proof 嘅 **expected-output contract**，取代舊嘅 SPEC.md 150–170「7 點」。由 [SPEC.md](SPEC.md) 🅱️ SPEC B 抽出。
> **2026-06-14 Jones 兩輪核完 PASS、approve 鎖**：gate TF / grade / forbidden / 22 條對齊 SSOT（🎯 Live Trading Supporter Rules）；C/G/J 補充 + 兩個 open Q 已拍板（見 §3.1、§2.G）。**改動要 Jones 發起。**
> 鎖咗之後：存 `golden/input/`（新 capture，9 charts、4 gate TF 都有 MACD）+ `golden/expected.md`（用本 contract 寫實），再 wire Step 3 regression。

---

## 0. 先決：golden INPUT 必須夠料先算數

舊 golden（2026-06-11）**算唔到 gate**：缺 30m、g2 嘅 15m 又冇 MACD → 4-TF gate 只計到 ≤2 TF。
所以**唔可以**攞舊圖做 baseline。新 golden input 要求：

- 9 個 chart（layout restructure 後）：g1 4H+1H｜g2 純 Renko/WMA｜g3 DXY1m+15s｜g4 5m+1m｜**g5 15m+30m**。
- **4 個 gate TF（1m / 5m / 15m / 30m）每格都有讀得清嘅 MACD pane**。缺任何一個 → input 唔合格，唔好攞嚟驗。

---

## 1. 正確分析次序（contract 要見到呢個 flow，唔可以跳）

```
Day-Type Gate → Range/Momentum(Track 選擇) Gate → MACD 4-TF Gate（實數）
   → Expansion Leg / DXY modifier（唔計 layer）→ Layer-count Grade
   → HTF Override（逆向降級）→ 5 行 Output
```

---

## 2. PASS 條件（逐項；全部 ✓ 先算 PASS）

### A. Day-Type Gate（開市第一步）
- [ ] **每個 call 標明當前日型**（TREND / RANGE）。
- [ ] Trend day 判定 = 5m ≥50 點單邊 ＋ 連續 HL/LH ＋ 突破有跟進 → 5m 升做主導 bias；
      **4H/1H 冇 veto，只調注碼**（同向正常注／逆向半注）。
- [ ] 唔可以喺 trend day 仲行 range 流程／畀 4H veto 順勢升浪（Anti-Failure #21）。
- [ ] **Trend day = Armed Order framing**：Setup／Trigger／Order／管理／有效期 **5 樣齊**先准出；雙向**各 frame 一張**（pullback ＋ breakout）。
- [ ] **WAIT ≤ 2**：同一 setup 第 3 次 WAIT = 違規 → 改掛 limit（ANT）或宣告 No-Trade（Anti-Failure #22）。

### B. Range / No-Trade Gate
- [ ] RANGE 判定 = 3+ 次掂邊界收唔穿，或 30+ 分鐘冇 5m 收盤破邊界。
- [ ] RANGE 確認 → **mid-band 一律 🚫 唔畀方向**（Anti-Failure #17）。
- [ ] 只有「5m 收盤破區間 ＋ DXY confirm ＋ gate ≥3/4」先畀方向。
- [ ] Two-Strike：同一 band 連續 2 個方向 call 都被 invalidate → 宣告 chop、停畀方向。

### C. Momentum / Trend Gate（揀 Track A 市價 / Track B 限價）
- [ ] 用 momentum 狀態揀 track：💀 力竭 → **Track B 限價**；🔥 強逆勢 → **唔接刀**；↩️ counter-trend → **淨限價**。
- [ ] 「而家做咩」嗰行要**反映 Track**：Track A = 市價入；Track B = 掛限價（ANT）。

### D. MACD 4-TF Gate（**實數，唔可以扮讀到**）
- [ ] 逐個 TF 出明 ✓/✗：**M1 / 5m / 15m / 30m**（例：`M1 ✓ / 5m ✓ / 15m ✗ / 30m ✓ → 3/4`）。
- [ ] ≥3/4 同向 = Confirmation entry OK；<3/4 = **淨係 ANT 限價單**。
- [ ] **1H/4H 唔計入 gate**（只做開場 bias）；15s = scalp timing；DXY 1m = inverse confirm（**唔投 gate 票**）。
- [ ] 缺某 TF（讀唔到 MACD）→ 標 ⚠️ 唔好估（Anti-Failure #15 False Precision、#16 Mandatory Input）。

### E. Modifiers（唔計 layer，只調 grade/size 或 timing）
- [ ] **DXY**：反向確認到位 = quality✅；橫行/同向 → grade **封頂 B+** ＋ 細注。DXY **唔調**「入唔入」或「入場時機」（Anti-Failure #18 / #20）。
- [ ] **Expansion Leg**：乾淨快 → 正常/加信心；慢亂 → 降級；太長 → 唔好 fade；太短 → skip。

### F. Layer-count Grade（信心度 = layer 數）
- [ ] 列出 confluence layers（Horizontal SNR / Diagonal TL / HPA 0.5 Fib / Broken S/R Flip / MACD alignment / Price Action / Liquidity Grab / Round Number / 3rd Touch）。
- [ ] **數總 layer**（冇一個 source 係 primary）：1–2 → C(SKIP)｜3 → B+(細注)｜4 → A(可加R)｜5+ → A+。
- [ ] 要 **≥1 個 5m/15m anchor**（純 LTF stack 唔可當 B+）。
- [ ] **gate 唔夠 3/4 時 MACD alignment 唔可以當 layer**（Anti-Failure **#14** 谷大 grade）。
- [ ] **ICT（FVG/OB）唔計入 layer**，只做 Track B 落點精修（防 double-count 谷大 grade）。

### G. HTF Override（源自 SPEC A；locked 2026-06-11 golden 靠佢）
- [ ] 4H＋Daily＋Weekly **全同向** → **逆向** trade 強制降級（SNIPER→HIGH、HIGH→STAND、STAND→WAIT）；**順向不受影響**。
- [ ] 註：呢條係 **SPEC A**（唔係 SPEC B）。保留入 contract 因為 locked 2026-06-11 sample 用咗；將來要 SPEC B-only 再由 Jones 發起移走。

### H. 5 行 Output 格式
- [ ] 第一句**必係 action call**：`IN` / `WAIT for [X+Y]` / `SKIP`（setup read 唔用 tier 色🟡🟠🔴）。
- [ ] 5 行：結論(方向/入唔入)｜而家做咩(**反映 Track A 市價 / Track B 限價**)｜SL·TP｜點解(一句)｜跟住睇邊度。
- [ ] 方向一律 **Long/Short**（唔用 buy/sell/做多做空）。
- [ ] 「睇邊度」**最多 2 個位**（一上一下）。
- [ ] R:R 標準：TP 一律 1R → +1R 推 BE → trailing 2R–7R（唔再出舊「1R/2R/3R」）。

### I. WAIT 必帶條件
- [ ] 每個 WAIT **必帶 alert 價 ＋ early trigger 條件**（唔可以 vague WAIT，Anti-Failure #9）。

### J. Forbidden phrases（Master Rule — 一句都唔可以出）
- [ ] 冇以下 unsolicited meta-coaching（wingman 唔係 gatekeeper，Anti-Failure #1）：
  - 「你應該停止交易」/「walk away」/「are you sure」
  - 「Consider waiting」（除非用戶明確問）
  - 「Hard stop commitment」
  - 「+XR violation」/「violates Lesson X」
  - 「This might not be the best idea」
  - 任何情緒／疲勞／紀律 meta-coaching。

### K. 22 Anti-Failure — 一條都唔可以踩
1 Gatekeeper｜2 Confirmation Bias｜3 Sycophancy｜4 Premature Defensive｜5 寫低≠做到｜
6 Skip Pre-Marking｜7 MACD Laziness｜8 Single-Direction Prep（要雙向 scoring）｜9 Vague WAIT｜
10 Re-analyzing Levels｜11 Calc Errors｜12 Recency Bias（entry 可快、regime 唔可快）｜
13 Divergence Not Flagged｜14 Cheerleader/谷大 grade｜15 False Precision／扮讀到數｜
16 漏 Mandatory Input（15s/DXY/Expansion Leg/30m）｜17 Range 內亂畀方向｜
18 Modifier-as-Gate（DXY 卡入場）｜19 逆 M1·M5·M15 flow 入場｜20 DXY 1min noise 當大方向｜
21 Trend Day 仲用 Range 流程／4H veto 順勢升浪｜22 Snapshot 思維（frame 咗要 track 結局：trigger/invalidate/過期）。

---

## 3. Self-proof 程序（A 修好 layout、B 核完 contract 之後先做）

1. 用**新 capture**（9 charts、4 gate TF 都有 MACD）做 input。
2. 跑 SOP → 出 output。
3. 攞本 contract §2 逐項打勾；**全 ✓ → PASS**。
4. PASS → 存 `golden/input/`（嗰套圖）+ `golden/expected.md`（用本 contract 寫實 expected）→ Jones 鎖。
5. 鎖咗 → Claude wire `analyze/sop_prompt.SOP_SYSTEM_PROMPT` + claude_client inference + 寫 Step 3 regression test（assert output 過 §2 可驗項）。

### 3.1 expected.md 鎖嘅範圍（regression 會 assert 乜）

- **一定 assert**：5 行 push call（SPEC B）+ §2 入面**單張 snapshot 驗得到**嘅 deterministic 項 ——
  MACD 4-TF gate 實數（C/D）、grade + layer 數（F）、Track 選擇（C/H）、HTF override（G）、
  forbidden phrases 零命中（J）、WAIT 帶 alert+trigger（I）、格式（H）。
- **SPEC A Output 0–4 完整 prose**：✅ **Jones 拍板（2026-06-14）= 只 assert「結構齊 + 關鍵數字」**
  —— 0 Signal Listing→4 Trade Setup 段落有齊 + 關鍵價/分數/gate 數對；**prose 唔逐字**
  （free-form 逐字 = regression 太脆）。expected.md + Step 3 regression 照呢個方向寫。
- **Fresh Eyes（#6；#22 嘅 track-結局部分）= cross-snapshot 規則**（唔 carry forward 上一 cycle）→
  **單張 golden 冇得 assert**，明確標**唔驗**；留俟 multi-cycle test（之後 / Step 6 之上）。

---

> **status：✅ APPROVED & LOCKED（2026-06-14，Jones 兩輪核完 PASS）。** 之後改動要 Jones 發起。
