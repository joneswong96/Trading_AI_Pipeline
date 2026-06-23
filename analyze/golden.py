"""Golden regression：parse golden/expected.md + check 一個 call 達唔達到 deterministic 斷言。

由 docs/golden_contract.md（APPROVED & LOCKED 2026-06-14）+ golden/expected.md 驅動。
§3.1：只 assert deterministic 欄位（+ 5 行結構），**prose 唔逐字**；Fresh Eyes（cross-snapshot）
單張 golden **唔 assert**。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# Contract §J：forbidden phrases（出現 = 違規）。
FORBIDDEN_PHRASES = [
    "你應該停止交易", "walk away", "are you sure", "consider waiting",
    "hard stop commitment", "violation", "violates lesson",
    "this might not be the best idea",
]

_TF_RE = re.compile(r"(M1|5m|15m|30m)\s*=\s*(\w+)", re.I)
_SCORE_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_TF_KEY = {"m1": "m1", "5m": "m5", "15m": "m15", "30m": "m30"}


def _coerce(v: str):
    v = v.strip()
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.startswith("[") and v.endswith("]"):
        try:
            return list(ast.literal_eval(v))
        except Exception:
            return v
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def _parse_gate(val: str) -> dict:
    out: dict = {"gate": {_TF_KEY.get(m.group(1).lower(), m.group(1).lower()):
                          m.group(2).upper() for m in _TF_RE.finditer(val)}}
    score = _SCORE_RE.search(val)
    if score:
        out["gate_score"] = f"{score.group(1)}/{score.group(2)}"
    parts = [p.strip() for p in val.split("→")]
    if len(parts) >= 3:
        out["gate_mode"] = parts[-1]
    return out


def parse_expected(md: str) -> dict:
    """由 expected.md 抽 `## Deterministic Assertions` 區嘅 key:value（去 inline #comment）。"""
    exp: dict = {}
    in_block = False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## Deterministic"):
            in_block = True
            continue
        if in_block and s.startswith("##"):
            break
        if not in_block or s.startswith("#") or ":" not in s:
            continue
        key, _, rest = s.partition(":")
        key, rest = key.strip(), rest.split("#", 1)[0].strip()
        if key == "gate":
            exp.update(_parse_gate(rest))
        else:
            exp[key] = _coerce(rest)
    return exp


def parse_expected_file(path: str | Path) -> dict:
    return parse_expected(Path(path).read_text(encoding="utf-8"))


def count_forbidden(text: str) -> int:
    t = (text or "").lower()
    return sum(t.count(p.lower()) for p in FORBIDDEN_PHRASES)


def _score_num(v):
    """gate score → numerator int。'2/4' / '2' / 2 → 2；None/讀唔到 → None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).split("/")[0].strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _eq(field: str, exp_v, got_v, fails: list[str]) -> None:
    if isinstance(exp_v, list):
        ok = sorted(got_v or []) == sorted(exp_v)
    elif isinstance(exp_v, str):
        ok = str(got_v).strip().upper() == exp_v.strip().upper()
    else:
        ok = got_v == exp_v
    if not ok:
        fails.append(f"{field}: expected {exp_v!r}, got {got_v!r}")


def check_call(call: dict, expected: dict, *, push_text: str = "") -> list[str]:
    """回 mismatch list（空 = PASS）。只查 contract §3.1 嘅 deterministic 欄位。

    call 欄位（SOP_SYSTEM_PROMPT JSON schema）：day_type / gate{m1,m5,m15,m30,score(int)} /
    gate_pass / range_confirmed / range_bounds / price_in_midband / action / grade /
    dxy_modifier / htf_override_triggered / wait_alerts / wait_has_alert。
    """
    fails: list[str] = []

    for f in ("day_type", "gate_pass", "range_confirmed", "range_bounds",
              "price_in_midband", "action", "grade", "dxy_modifier",
              "htf_override_triggered"):
        if f in expected:
            _eq(f, expected[f], call.get(f), fails)

    # wait_alerts / wait_has_alert：用 call 同名欄位（sample schema）
    if "wait_alerts" in expected:
        _eq("wait_alerts", expected["wait_alerts"], call.get("wait_alerts"), fails)
    if "wait_has_alert" in expected:
        _eq("wait_has_alert", expected["wait_has_alert"], call.get("wait_has_alert"), fails)

    # gate：per-TF + score（call score 係 int，expected 係 'x/4' → 比 numerator）
    if "gate" in expected:
        cg = call.get("gate") or {}
        for tf, d in expected["gate"].items():
            _eq(f"gate.{tf}", d, cg.get(tf), fails)
        if "gate_score" in expected:
            exp_n, got_n = _score_num(expected["gate_score"]), _score_num(cg.get("score"))
            if got_n != exp_n:
                fails.append(f"gate.score: expected {expected['gate_score']}, got {cg.get('score')}")

    # forbidden phrases（scan push 文字）
    if "forbidden_phrases_count" in expected:
        _eq("forbidden_phrases_count", expected["forbidden_phrases_count"],
            count_forbidden(push_text), fails)

    return fails
