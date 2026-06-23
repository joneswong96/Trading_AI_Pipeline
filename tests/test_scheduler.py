"""Step 6 tests：run_cycle 串接邏輯（fake deps，唔使 browser/AI）。

鎖實：① trigger+有變 → push、寫 store；② precheck skip → 唔 call analyze；
③ analyze 未 wire（raise）→ 接住、log error、唔炒車；④ dedupe 冇變 → 唔 push（log only）。
"""
import pytest

from analyze.claude_client import AnalyzeResult
from scheduler import run as sched
from scheduler.run import CycleDeps, run_cycle

CALL = {"action": "WAIT", "grade": "B+", "levels": {"entry": 4073.5},
        "alerts": [4057, 4074], "ant": {"side": "Short"},
        "summary": "s", "now": "n", "why": "w", "watch": ["a"]}


class FakeShot:
    def __init__(self, path):
        self.ok, self.path = True, path


class FakeBundle:
    def __init__(self, ok=True, error=None):
        self.ok, self.error, self.shots = ok, error, [FakeShot("a.png")]


class FakeCapture:
    route = "fake"

    def __init__(self, bundle=None):
        self._b = bundle or FakeBundle()

    def capture_bundle(self, cid):
        return self._b


class FakePre:
    def __init__(self, price=4218.5, prev=4218.0, triggered=True, reason="moved"):
        self.price, self.prev_price = price, prev
        self.triggered, self.reason = triggered, reason


class FakePrefilter:
    def __init__(self, dec):
        self._d = dec

    def check(self):
        return self._d


class FakeAnalyzer:
    def __init__(self, call=None, raises=None):
        self._c, self._r = call, raises

    def analyze(self, paths, **kw):
        if self._r:
            raise self._r
        return AnalyzeResult(call=self._c, raw_text="", model="fake")


class FakeStore:
    def __init__(self, last=None):
        self.rows, self._last = [], last

    def log_cycle(self, rec):
        self.rows.append(rec)

    def last_pushed_features(self):
        return self._last


class FakePublisher:
    def __init__(self, enabled=True):
        self._en, self.pushed = enabled, []

    def enabled(self):
        return self._en

    def push(self, text, img=None):
        self.pushed.append(text)


def test_push_path_writes_store_and_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "CALLS_DIR", tmp_path)
    store, pub = FakeStore(last=None), FakePublisher(enabled=True)
    deps = CycleDeps(FakeCapture(), FakePrefilter(FakePre()),
                     FakeAnalyzer(call=CALL), store, pub)
    rec = run_cycle(deps, "cid1")
    assert rec["pushed"] == 1 and rec["action"] == "WAIT"
    assert len(store.rows) == 1 and pub.pushed
    assert (tmp_path / "cid1" / "call.json").exists()      # 可回放


def test_precheck_skip_does_not_call_analyze(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "CALLS_DIR", tmp_path)
    store = FakeStore()
    analyzer = FakeAnalyzer(raises=AssertionError("analyze 唔應該 call"))
    deps = CycleDeps(FakeCapture(), FakePrefilter(FakePre(triggered=False, reason="靜")),
                     analyzer, store, FakePublisher())
    rec = run_cycle(deps, "cid2")
    assert rec["precheck_triggered"] == 0 and rec["pushed"] == 0
    assert "precheck skip" in rec["push_reason"] and len(store.rows) == 1


def test_analyze_not_wired_is_caught_no_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "CALLS_DIR", tmp_path)
    store = FakeStore()
    deps = CycleDeps(FakeCapture(), FakePrefilter(FakePre()),
                     FakeAnalyzer(raises=NotImplementedError("未 wire")), store,
                     FakePublisher())
    rec = run_cycle(deps, "cid3")           # 唔應該 raise 出嚟
    assert "NotImplementedError" in rec["error"] and rec["pushed"] == 0
    assert len(store.rows) == 1


def test_dry_run_has_no_side_effects(monkeypatch, capsys):
    """冇 --start：唔可以 build_default_deps（即唔掂 Store/db/Capture），只印「未 go-live」。"""
    def boom():
        raise AssertionError("dry-run 唔應該 build_default_deps（會開 db）")
    monkeypatch.setattr(sched, "build_default_deps", boom)
    sched.main(argv=[])                      # 冇 --start → 唔應該 raise
    assert "未 go-live" in capsys.readouterr().out


def test_dedupe_no_state_change_logs_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "CALLS_DIR", tmp_path)
    last = {"action": "WAIT", "grade": "B+", "trigger": 4073.5,
            "alerts": [4057, 4074], "has_ant": True}
    store, pub = FakeStore(last=last), FakePublisher(enabled=True)
    # price 4218→4219，唔掂 4057/4074 → 冇任何觸發
    deps = CycleDeps(FakeCapture(), FakePrefilter(FakePre(price=4219.0, prev=4218.0)),
                     FakeAnalyzer(call=CALL), store, pub)
    rec = run_cycle(deps, "cid4")
    assert rec["pushed"] == 0 and "no_state_change" in rec["push_reason"]
    assert not pub.pushed                    # 冇 send
