"""gates/macd_gate.py — MACD 4-TF gate（純函數，deterministic）。

純輸入數字 → 輸出 verdict。冇 I/O、冇 network、冇 vision。Claude 只負責由圖
crop-read 出每格 hist/macd/signal；**呢度先係 gate 判斷嘅唯一權威**（rule judgment
搬落 Python，2026-06-15 M1 phase 1）。

3-state 分類（取代 SOP 2-state 做 deterministic authority）：
  hist > 0 且 macd > signal      = BULL
  hist < 0 且 macd < signal      = BEAR
  其餘（mixed / 等於 / 0）         = NEUTRAL
讀唔到（None / 缺欄位）→ 該 TF 當 NEUTRAL（唔投票），**唔估**（Anti-Failure #15）。

只有 M1 / 5m / 15m / 30m 投票（contract §D）；1H/4H/15s/DXY 唔投。
score  = 主方向（BULL vs BEAR 較多嗰邊）對齊嘅 TF 數（contract §D「≥3/4 同向」）。
direction = BULL/BEAR 邊邊多；打和 → BULL（long-bias 預設，對齊 golden display）。
gate_pass = score >= 3。
"""
from __future__ import annotations

GATE_TFS = ("m1", "m5", "m15", "m30")
_LABEL = {"m1": "M1", "m5": "5m", "m15": "15m", "m30": "30m"}


def classify_tf(reading: dict | None) -> str:
    """單一 TF 三態分類。reading = {"hist","macd","signal"}；None/缺值 → NEUTRAL。"""
    if not reading:
        return "NEUTRAL"
    hist = reading.get("hist")
    macd = reading.get("macd")
    signal = reading.get("signal")
    if hist is None or macd is None or signal is None:
        return "NEUTRAL"
    if hist > 0 and macd > signal:
        return "BULL"
    if hist < 0 and macd < signal:
        return "BEAR"
    return "NEUTRAL"


def compute_macd_gate(readings: dict | None) -> dict:
    """readings = {"m1":{hist,macd,signal}, "m5":..., "m15":..., "m30":...}（值可 None）。

    回 deterministic verdict：
      {m1,m5,m15,m30: 三態, direction, score, gate_pass, display}。
    display 例：'M1✓ / 5m✓ / 15m✗ / 30m✗ = 2/4'（✓ = 同主方向）。
    """
    src = readings or {}
    verdicts = {tf: classify_tf(src.get(tf)) for tf in GATE_TFS}
    bull = sum(1 for v in verdicts.values() if v == "BULL")
    bear = sum(1 for v in verdicts.values() if v == "BEAR")
    direction = "BULL" if bull >= bear else "BEAR"   # 打和 → BULL
    score = bull if direction == "BULL" else bear
    gate_pass = score >= 3
    marks = [f"{_LABEL[tf]}{'✓' if verdicts[tf] == direction else '✗'}" for tf in GATE_TFS]
    display = " / ".join(marks) + f" = {score}/4"
    return {
        "m1": verdicts["m1"],
        "m5": verdicts["m5"],
        "m15": verdicts["m15"],
        "m30": verdicts["m30"],
        "direction": direction,
        "score": score,
        "gate_pass": gate_pass,
        "display": display,
    }
