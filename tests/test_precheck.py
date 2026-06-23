"""Step 2 tests：pre-check 決策邏輯（純函數，唔使 TV / browser）。"""
from precheck.prefilter import _to_float, decide

LEVELS = [4057.05, 4073.77, 4028.40]
MOVE, NEAR = 1.0, 1.5


def test_decide_first_cycle_triggers():
    d = decide(4218.0, None, LEVELS, MOVE, NEAR)
    assert d.triggered and "first cycle" in d.reason


def test_decide_moved_triggers():
    d = decide(4220.0, 4218.0, [], MOVE, NEAR)
    assert d.triggered and "Δ2.00" in d.reason


def test_decide_static_far_from_level_skips():
    d = decide(4218.3, 4218.0, [4000.0], MOVE, NEAR)  # Δ0.3 < 1.0，又遠離 level
    assert not d.triggered and "skip" in d.reason


def test_decide_near_level_triggers_even_if_static():
    # Δ0.2 < move_threshold，但距 4057.05 得 0.45 ≤ near_level → trigger
    d = decide(4057.5, 4057.3, LEVELS, MOVE, NEAR)
    assert d.triggered and "近 key level" in d.reason
    assert d.nearest_level == 4057.05


def test_to_float_handles_commas_and_junk():
    assert _to_float("4,218.50") == 4218.5
    assert _to_float("x") is None
    assert _to_float(None) is None
