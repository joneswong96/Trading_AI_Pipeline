"""Step 6：截圖 retention —— prune 舊 bundle，但留住可回放證物（核心原則 #3）。

政策（config：assets.yaml `retention`）：
  - 有 push 嘅 bundle → **永留**（pushed_bundle_dirs，由 Store 攞）。
  - 冇 push / precheck skip 嘅 → 過 `keep_skip_days`（default 7）就 prune。
  - screenshots 總容量超 `max_total_gb`（default 5）→ 由**最舊非 push** 開始 prune 到落界。

prune 係 daily job（scheduler go-live 掛 cron 04:00），唔入每分鐘 cycle。
plan_prune() 係純函數可離線測；prune() 做 IO。**SSOT 次序唔郁**：呢個 prune 唔改
capture→precheck 嘅 pipeline 次序，淨係事後清 disk。
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from capture.base import ROOT

SCREENSHOTS_DIR = ROOT / "storage" / "screenshots"
_GB = 1024 ** 3
_DAY = 86400

DEFAULTS = {"keep_skip_days": 7, "max_total_gb": 5.0}


@dataclass
class BundleInfo:
    path: str
    mtime: float   # epoch 秒
    size: int      # bytes
    pushed: bool


@dataclass
class PrunePlan:
    delete: list[str] = field(default_factory=list)
    freed_bytes: int = 0
    reason: dict[str, str] = field(default_factory=dict)


def plan_prune(bundles: list[BundleInfo], now: float,
               keep_skip_days: int, max_total_gb: float) -> PrunePlan:
    """純函數：畀 bundle list → 邊啲要刪。pushed 嘅永遠唔刪。"""
    keep_secs = keep_skip_days * _DAY
    cap = max_total_gb * _GB
    plan = PrunePlan()

    # 1) 非 push 且過期 → 刪
    survivors: list[BundleInfo] = []
    for b in bundles:
        if not b.pushed and (now - b.mtime) > keep_secs:
            plan.delete.append(b.path)
            plan.freed_bytes += b.size
            plan.reason[b.path] = f"非 push 過期（>{keep_skip_days}d）"
        else:
            survivors.append(b)

    # 2) survivors 仲超總容量 → 由最舊非 push 開始補刪
    total = sum(b.size for b in survivors)
    if total > cap:
        for b in sorted((s for s in survivors if not s.pushed), key=lambda x: x.mtime):
            if total <= cap:
                break
            plan.delete.append(b.path)
            plan.freed_bytes += b.size
            plan.reason[b.path] = "超總容量上限"
            total -= b.size
    return plan


def _scan(screenshots_dir: Path, pushed_dirs: set[str]) -> list[BundleInfo]:
    out: list[BundleInfo] = []
    if not screenshots_dir.exists():
        return out
    for d in screenshots_dir.iterdir():
        if not d.is_dir():
            continue
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        out.append(BundleInfo(str(d), d.stat().st_mtime, size, str(d) in pushed_dirs))
    return out


def load_cfg() -> dict:
    cfg = dict(DEFAULTS)
    try:
        import yaml
        with open(ROOT / "config" / "assets.yaml", encoding="utf-8") as f:
            cfg.update(yaml.safe_load(f).get("retention", {}) or {})
    except Exception:
        pass
    return cfg


def prune(pushed_dirs: set[str], cfg: dict | None = None, *,
          screenshots_dir: Path = SCREENSHOTS_DIR, now: float | None = None,
          dry_run: bool = False) -> PrunePlan:
    cfg = cfg or load_cfg()
    bundles = _scan(Path(screenshots_dir), pushed_dirs)
    plan = plan_prune(bundles, now or time.time(),
                      int(cfg["keep_skip_days"]), float(cfg["max_total_gb"]))
    if not dry_run:
        for p in plan.delete:
            shutil.rmtree(p, ignore_errors=True)
    return plan


def run_prune(store) -> PrunePlan:
    """daily job entry：由 Store 攞 pushed bundle → prune，印 report。"""
    plan = prune(store.pushed_bundle_dirs())
    print(f"[retention] 刪 {len(plan.delete)} 個 bundle，"
          f"釋放 {plan.freed_bytes / _GB:.2f} GB")
    return plan


if __name__ == "__main__":
    from capture.base import force_utf8_stdout
    from storage.db import Store
    force_utf8_stdout()
    p = prune(Store().pushed_bundle_dirs(), dry_run="--apply" not in __import__("sys").argv)
    mode = "DRY-RUN（加 --apply 先真刪）" if "--apply" not in __import__("sys").argv else "APPLIED"
    print(f"[retention {mode}] 會刪 {len(p.delete)} 個，釋放 {p.freed_bytes / _GB:.2f} GB")
    for path, why in list(p.reason.items())[:20]:
        print(f"  {path} — {why}")
