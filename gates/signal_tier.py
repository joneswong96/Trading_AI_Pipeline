"""gates/signal_tier.py — 持倉管理 Signal Tier（純函數，deterministic）。

純輸入 bool 訊號 → 輸出 tier。冇 I/O、冇 network、冇 vision。Claude 只負責由圖讀
出「邊啲訊號出現咗」（vision/判斷）；tier 升級邏輯喺呢度 deterministic 做。

SPEC B「Warning Signal Tiering」全表（4 / 5 / 4）—— **只用喺持倉管理**（in-trade），
setup read（WAIT/IN/SKIP）唔用 tier 色（contract §H，兩系統唔撈亂）：
  🟡 YELLOW（note only，hold）：single wick against(no close) / M1 hist flip alone /
                               single counter candle / spread widening briefly
  🟠 ORANGE（可考慮 tighten）：M5 close against(non-structural) / 2+ counter candle /
                               M5 MACD histogram clear flip / approaching key SNR against /
                               DXY 急轉成對倉位不利
  🔴 RED（cut recommended）  ：M5 close + structural shift(HH/HL 或 LH/LL flip) /
                               HTF MACD flip(15m+) / major SNR break against /
                               original thesis invalidated
升級制：任一 RED → RED；否則任一 ORANGE → ORANGE；否則任一 YELLOW → YELLOW；都冇 → NONE。
用 Signal Tier 代 P&L 做 hold/cut（鼓勵遮住 P&L）。action 係**內部 flag**；出 user 嗰句
一定保留「你決定」（建議，唔係 auto-action；SPEC §Output Style、Anti-Failure #1/#4）。
"""
from __future__ import annotations

# (tier, color, action, 觸發條件 keys) —— 由重到輕，第一個命中即定 tier。
TIER_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("RED", "🔴", "cut", (
        "m5_close_struct_flip",   # M5 close + 結構轉 HH/HL 或 LH/LL flip
        "htf_macd_flip",          # HTF MACD flip (15m+)
        "major_snr_break",        # major SNR break against
        "thesis_invalidated",     # original thesis invalidated
    )),
    ("ORANGE", "🟠", "tighten", (
        "m5_close_against",       # M5 close against (non-structural)
        "reversal_candles_2plus", # 2+ counter candle
        "m5_macd_hist_flip",      # M5 MACD histogram clear flip
        "near_key_snr",           # approaching key SNR against
        "dxy_sharp_adverse",      # DXY 急轉成對倉位不利
    )),
    ("YELLOW", "🟡", "hold", (
        "single_wick",            # single wick against (no close)
        "m1_hist_flip",           # M1 hist flip alone
        "single_counter_candle",  # single counter candle
        "spread_widening_brief",  # spread widening briefly
    )),
)

ALL_SIGNALS: tuple[str, ...] = tuple(k for _, _, _, keys in TIER_RULES for k in keys)


def evaluate_signal_tier(signals: dict | None) -> dict:
    """signals = {訊號 key: bool}（缺 = False）。回 {tier, color, action, reasons}。

    tier=NONE（color=''、action='hold'）= 冇任何降級訊號，正常持有。
    """
    src = signals or {}
    for tier, color, action, keys in TIER_RULES:
        reasons = [k for k in keys if src.get(k)]
        if reasons:
            return {"tier": tier, "color": color, "action": action, "reasons": reasons}
    return {"tier": "NONE", "color": "", "action": "hold", "reasons": []}
