"""Step 5 tests：推送 dedupe —— 鎖實「狀態冇變 → 唔 push」+ 五個觸發。"""
from publish.dedupe import should_push

BASE = {"action": "WAIT", "grade": "B+", "trigger": 4073.5,
        "alerts": [4057, 4074], "has_ant": True}


def test_first_pushed_call_pushes():
    assert should_push(None, dict(BASE)).push


def test_no_state_change_no_push():
    d = should_push(dict(BASE), dict(BASE), prev_price=4218.0, cur_price=4219.0)
    assert not d.push and "no_state_change" in d.reason and d.fired == []


def test_action_change_pushes():
    assert should_push(BASE, dict(BASE, action="IN")).push


def test_grade_change_pushes():
    assert should_push(BASE, dict(BASE, grade="A")).push


def test_trigger_change_pushes():
    assert should_push(BASE, dict(BASE, trigger=4080.0)).push


def test_ant_flip_pushes():
    assert should_push(BASE, dict(BASE, has_ant=False)).push


def test_alert_touched_pushes():
    # price 由 4075 行到 4073，跨過 4074 alert → push
    d = should_push(BASE, dict(BASE), prev_price=4075.0, cur_price=4073.0)
    assert d.push and "4074" in d.reason


def test_alert_not_touched_no_push():
    d = should_push(BASE, dict(BASE), prev_price=4218.0, cur_price=4219.0)
    assert not d.push
