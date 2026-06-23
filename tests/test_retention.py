"""Step 6 tests：retention prune —— pushed 永留、非 push 過期/超容量先 prune。"""
import time

from PIL import Image

from storage.retention import BundleInfo, plan_prune, prune

DAY = 86400
NOW = 1_000_000_000.0
MB = 1024 * 1024


def _b(path, age_days, size_mb, pushed):
    return BundleInfo(path, NOW - age_days * DAY, int(size_mb * MB), pushed)


def test_pushed_never_pruned_even_if_old():
    bundles = [_b("pushed-old", 999, 10, True)]
    plan = plan_prune(bundles, NOW, keep_skip_days=7, max_total_gb=5.0)
    assert plan.delete == []


def test_nonpush_old_pruned_recent_kept():
    bundles = [
        _b("skip-old", 10, 1, False),     # >7d → 刪
        _b("skip-recent", 2, 1, False),   # <7d → 留
    ]
    plan = plan_prune(bundles, NOW, 7, 5.0)
    assert plan.delete == ["skip-old"] and "skip-recent" not in plan.delete


def test_capacity_cap_prunes_oldest_nonpush_first():
    # 全部喺保留期內，但加埋超 5GB → 由最舊非 push prune 到落界
    bundles = [
        _b("push-big", 1, 4000, True),     # pushed，唔可以掂（4 GB）
        _b("skip-older", 3, 1500, False),  # 最舊非 push（1.5 GB）→ 先刪
        _b("skip-newer", 1, 1500, False),  # 次新非 push（1.5 GB）
    ]
    plan = plan_prune(bundles, NOW, keep_skip_days=30, max_total_gb=5.0)
    # 總 7 GB；刪 skip-older 後 5.5 GB 仲超 → 再刪 skip-newer 到 4 GB ≤ 5
    assert "skip-older" in plan.delete
    assert "push-big" not in plan.delete            # pushed 永留
    assert plan.freed_bytes >= 1500 * MB


def test_prune_filesystem_deletes_dirs(tmp_path):
    ss = tmp_path / "screenshots"
    ss.mkdir()
    # 造兩個 bundle：一個舊 skip、一個 pushed
    for name, old in [("skip-old", True), ("kept-push", False)]:
        d = ss / name
        d.mkdir()
        Image.new("RGB", (10, 10)).save(d / "g1.png")
        if old:
            past = NOW - 30 * DAY
            import os
            os.utime(d, (past, past))
    pushed = {str(ss / "kept-push")}
    plan = prune(pushed, {"keep_skip_days": 7, "max_total_gb": 999.0},
                 screenshots_dir=ss, now=NOW)
    assert not (ss / "skip-old").exists()           # 舊 skip 真刪咗
    assert (ss / "kept-push").exists()              # pushed 留低
    assert str(ss / "skip-old") in plan.delete
