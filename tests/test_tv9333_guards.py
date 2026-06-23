"""tests/test_tv9333_guards.py — 9333 guard 純判定 regression（P2a 補 g7/DXY 保護）。

純函數測（唔連 live 9333）：
- _correct_tab_ok（Fork B guard-4，Option B symbol-agnostic）：非-XAUUSD（TVC:DXY）唔再 false-fail。
- _drift_for_charts（per-tab data-driven verify）：g7 expected TVC:DXY/15m 正面受 drift-guard 保護。
"""
from capture.tv9333 import _correct_tab_ok, _drift_for_charts


# ── _correct_tab_ok：symbol-agnostic（驗 set 有冇 mutate symbol，唔硬鎖 XAUUSD）───────────
def test_correct_ok_xauusd_set_ok():
    assert _correct_tab_ok([{"action": "set_ok", "symbol": "ICMARKETS:XAUUSD",
                             "symbol_after": "ICMARKETS:XAUUSD",
                             "macd_before": True, "macd_after": True}]) is True


def test_correct_ok_dxy_set_ok_not_false_fail():
    # 回歸主旨：非-XAUUSD（TVC:DXY）set_ok 唔再 false-fail（呢個就係 ensure.ok=False 個 bug）
    assert _correct_tab_ok([{"action": "set_ok", "symbol": "TVC:DXY",
                             "symbol_after": "TVC:DXY",
                             "macd_before": False, "macd_after": False}]) is True


def test_correct_ok_dxy_skip_already_no_symbol_after():
    # skip_already 冇 symbol_after → 唔 check symbol，照 OK（真 run g7 就係呢個 path）
    assert _correct_tab_ok([{"action": "skip_already", "symbol": "TVC:DXY",
                             "macd_before": False, "macd_after": False}]) is True


def test_correct_fail_when_set_mutated_symbol():
    # setChartType 改咗 symbol = 真問題（symbol-agnostic 都 catch）
    assert _correct_tab_ok([{"action": "set_ok", "symbol": "ICMARKETS:XAUUSD",
                             "symbol_after": "OANDA:XAUUSD",
                             "macd_before": True, "macd_after": True}]) is False


def test_correct_fail_when_macd_dropped():
    assert _correct_tab_ok([{"action": "set_ok", "symbol": "ICMARKETS:XAUUSD",
                             "symbol_after": "ICMARKETS:XAUUSD",
                             "macd_before": True, "macd_after": False}]) is False


def test_correct_fail_when_action_not_ok():
    assert _correct_tab_ok([{"action": "set_FAIL", "symbol": "ICMARKETS:XAUUSD"}]) is False
    assert _correct_tab_ok([{"action": "error", "symbol": "ICMARKETS:XAUUSD"}]) is False


# ── _drift_for_charts：per-tab data-driven（g7 正面受保護）────────────────────────────────
G7 = dict(symbol="TVC:DXY", intervals=["15"], macd_required=False)
G4 = dict(symbol="ICMARKETS:XAUUSD", intervals=["5", "1"], macd_required=True)


def test_g7_dxy_clean_no_drift():
    charts = [{"interval": "15", "symbol": "TVC:DXY", "chartType": 1, "macd": None}]
    assert _drift_for_charts(charts, **G7) == []


def test_g7_symbol_drift_reported():
    # g7 漂去 XAUUSD → 報 drift（正面保護；唔再「唔 check g7」）
    charts = [{"interval": "15", "symbol": "ICMARKETS:XAUUSD", "chartType": 1, "macd": None}]
    assert any("symbol" in d for d in _drift_for_charts(charts, **G7))


def test_g7_interval_drift_reported():
    # g7 TF 漂去 5m → 報 drift
    charts = [{"interval": "5", "symbol": "TVC:DXY", "chartType": 1, "macd": None}]
    assert any("unexpected" in d for d in _drift_for_charts(charts, **G7))


def test_g7_no_macd_required_not_flagged():
    # g7 冇 MACD 唔報（macd_required False）
    charts = [{"interval": "15", "symbol": "TVC:DXY", "chartType": 1, "macd": None}]
    assert not any("MACD" in d for d in _drift_for_charts(charts, **G7))


def test_g4_macd_missing_reported():
    # gate tab 要 MACD：缺 → drift
    charts = [{"interval": "5", "symbol": "ICMARKETS:XAUUSD", "chartType": 1, "macd": None}]
    assert any("MACD missing" in d for d in _drift_for_charts(charts, **G4))


def test_g4_clean_no_drift():
    charts = [{"interval": "5", "symbol": "ICMARKETS:XAUUSD", "chartType": 1, "macd": "MACD"},
              {"interval": "1", "symbol": "ICMARKETS:XAUUSD", "chartType": 1, "macd": "MACD"}]
    assert _drift_for_charts(charts, **G4) == []


def test_g4_charttype_drift_reported():
    # chartType 漂去 19（Volume Candles）→ drift
    charts = [{"interval": "5", "symbol": "ICMARKETS:XAUUSD", "chartType": 19, "macd": "MACD"}]
    assert any("type=19" in d for d in _drift_for_charts(charts, **G4))
