"""Phase 1 — TradingView webhook ingestion（訊號接收層，notify-only）。

收 SNR / SR / Renko alert → parse → dedupe → log → trigger → 若夠料 push「撳 /analyze」。
Phase 1 唔判方向、唔出 call、唔落單（嗰啲係 Phase 2 嘅手動 /analyze flow）。
"""
