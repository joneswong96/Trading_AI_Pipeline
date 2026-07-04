"""Phase 1.5：thesis emitter —— /analyze 收尾叫，food Thesis JSON → validate → append thesis_log
→ storage/thesis/ backup → 回填 wake_queue（consumed_by/consumed_at）。

Jones 2026-07-04 拍板：writes deterministic + unit-testable（Claude 只砌 JSON，唔手寫 DB）；schema
validation 集中一處，invalid → **fail-loud 唔寫**（同 snr_levels/tv9333 producer 模式一致）。
只寫 storage/ runtime artifact（gitignored），唔掂 repo 受控檔。thesis_log append-only（狀態變 =
version+1 新 row）。每次 /analyze 都 emit（status 含 WAIT/NO_TRADE）→ wake 消費 ↔ emit 1:1。

用法：py -m analyze.thesis_emit --json <file>   或   … | py -m analyze.thesis_emit （stdin）
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from capture.base import ROOT
from ingest import wake_queue
from ingest.thesis_store import ThesisStore

THESIS_DIR = ROOT / "storage" / "thesis"

ALLOWED_STATUS = {"ARMED", "IN_TRADE", "WAIT", "NO_TRADE", "INVALIDATED", "EXPIRED", "CLOSED"}
_ACTIONABLE = {"ARMED", "IN_TRADE"}
_DIRS = {"LONG", "SHORT"}


class ThesisValidationError(ValueError):
    """schema 唔過 → fail-loud，唔寫任何嘢。"""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate(thesis: dict) -> None:
    """schema gate（fail-loud）。invalid → raise ThesisValidationError，caller 唔應寫。"""
    if not isinstance(thesis, dict):
        raise ThesisValidationError("thesis 唔係 dict")
    status = str(thesis.get("status") or "").strip().upper()
    if status not in ALLOWED_STATUS:
        raise ThesisValidationError(f"status={thesis.get('status')!r} 唔喺 {sorted(ALLOWED_STATUS)}")
    if not str(thesis.get("rationale") or "").strip():
        raise ThesisValidationError("rationale 必填（audit）")
    if status in _ACTIONABLE:
        d = str(thesis.get("dir") or "").strip().upper()
        if d not in _DIRS:
            raise ThesisValidationError(f"{status} 要 dir∈Long/Short，得 {thesis.get('dir')!r}")
        for k in ("entry", "sl"):
            if _num(thesis.get(k)) is None:
                raise ThesisValidationError(f"{status} 要數值 {k}，得 {thesis.get(k)!r}")
        if not str(thesis.get("valid_until") or "").strip():
            raise ThesisValidationError(f"{status} 要 valid_until")


def new_thesis_id(now=None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"thesis-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"


def emit(thesis: dict, *, store: ThesisStore | None = None, thesis_dir: Path = THESIS_DIR,
         wake_path: Path = None, now=None) -> dict:
    """validate → thesis_id/ts 補齊 → store.append(version+1) → backup → 回填 wake_queue。
    回 {thesis_id, version, status, backup, wake_consumed}。invalid → raise（唔寫）。"""
    now = now or datetime.now(timezone.utc)
    validate(thesis)                                      # fail-loud 先，未寫任何嘢

    t = dict(thesis)
    t["thesis_id"] = t.get("thesis_id") or new_thesis_id(now)
    t["status"] = str(t["status"]).strip().upper()
    t.setdefault("ts", now.isoformat())

    store = store or ThesisStore()
    tid, ver = store.append(t)                            # append-only INSERT（version 自動）
    t["version"] = ver

    thesis_dir = Path(thesis_dir)
    thesis_dir.mkdir(parents=True, exist_ok=True)
    backup = thesis_dir / f"{tid}-v{ver}.json"            # 每 version 一個 backup（append-only）
    backup.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")

    # 回填 wake_queue：優先用 thesis 帶嘅 wake_id（Step 0 記低嗰個），冇就 latest-unconsumed。
    wake_path = wake_path or wake_queue.WAKE_QUEUE
    wid = t.get("wake_id")
    if not wid:
        latest = wake_queue.latest_unconsumed(path=wake_path)
        wid = latest.get("wake_id") if latest else None
    consumed = wake_queue.mark_consumed(wid, tid, when=now, path=wake_path) if wid else False

    return {"thesis_id": tid, "version": ver, "status": t["status"],
            "backup": str(backup), "wake_consumed": wid if consumed else None}


def main(argv=None) -> int:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    if "--json" in argv:
        i = argv.index("--json")
        raw = Path(argv[i + 1]).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    try:
        thesis = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"JSON parse: {e}"}, ensure_ascii=False))
        return 2
    try:
        res = emit(thesis)
    except ThesisValidationError as e:
        print(json.dumps({"ok": False, "error": f"validation: {e}"}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": True, **res}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
