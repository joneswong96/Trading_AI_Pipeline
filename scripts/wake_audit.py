"""scripts/wake_audit.py — wake 質素審計（**read-only**，唔改任何 trigger 邏輯）。

讀 storage/wake_log.jsonl（舊 fanout 流水帳）+ wake_queue.jsonl（Phase 1.5 bridge，可能空）+
thesis_log（trading.db）+ bundles ohlc_history（做 range 位置）→ 出 markdown 報表：
  ① 每日 + 每 session（Asian/London/NY/overlap）wake 數
  ② 按 trigger_reason 分類（SNR FIRE / SNR PRIMED / MRF fade / 共振 / INVALIDATION / 其他）
  ③ wake→結果：consumed→thesis status（WAIT/NO_TRADE=白叫；ARMED/IN_TRADE=有效）；
     未 consumed = Jones 冇跟（fatigue）。wake_queue 空 → 用 thesis_log status 分佈補充。
  ④ 每個 wake 時價距最近 range boundary 幾遠（用**時間最近**嘅 ohlc_history m5 recent-range）
     → 驗證「mid-band wake 多數白叫」假設。

純函數（session_of / categorize_reason / range_position / build_report）injectable、可測。
Sydney 分區（config sessions）：overlap 23-03｜London 18-23｜NY 03-08｜Asian 08-16｜off 16-18。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

_CATEGORIES = [
    ("INVALIDATION", lambda r: "invalidation" in r.lower()),
    ("SNR FIRE", lambda r: "SNR FIRE" in r),
    ("SNR PRIMED", lambda r: "PRIMED" in r),
    ("MRF fade", lambda r: "MRF" in r or "fade" in r.lower()),
    ("共振", lambda r: "共振" in r or "resonance" in r.lower()),
]
_ACTIVE = {"ARMED", "IN_TRADE"}
_WHITE = {"WAIT", "NO_TRADE"}


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def local_dt(ts_iso, tz_offset_hours=10):
    dt = _parse(ts_iso)
    return None if dt is None else dt.astimezone(timezone(timedelta(hours=tz_offset_hours)))


def session_of(ts_iso, tz_offset_hours=10) -> str:
    """Sydney local 分區（非重疊 partition）。無效 ts → 'unknown'。"""
    ldt = local_dt(ts_iso, tz_offset_hours)
    if ldt is None:
        return "unknown"
    h = ldt.hour + ldt.minute / 60.0
    if h >= 23 or h < 3:
        return "London/NY overlap"
    if 18 <= h < 23:
        return "London"
    if 3 <= h < 8:
        return "NY"
    if 8 <= h < 16:
        return "Asian"
    return "off-session"


def categorize_reason(reason: str) -> str:
    r = reason or ""
    for name, pred in _CATEGORIES:
        if pred(r):
            return name
    return "其他"


def range_position(price, bars_m5, *, lookback=60, midband_pct=0.60):
    """price 對 m5 recent-range（最後 lookback 條 bar 嘅 min low / max high）位置。
    回 {low, high, dist_to_boundary, midband:bool}。price/bars 不足 → None。"""
    if price is None or not bars_m5:
        return None
    window = bars_m5[-lookback:]
    lows = [b[3] for b in window if len(b) >= 5]
    highs = [b[2] for b in window if len(b) >= 5]
    if not lows or not highs:
        return None
    low, high = min(lows), max(highs)
    if high <= low:
        return None
    dist = min(abs(price - high), abs(price - low))
    margin = (1 - midband_pct) / 2 * (high - low)
    midband = (low + margin) <= price <= (high - margin)
    return {"low": round(low, 2), "high": round(high, 2),
            "dist_to_boundary": round(dist, 2), "midband": midband}


def nearest_ohlc(wake_ts, bundles):
    """揀 captured_utc 同 wake_ts 時間最近嘅 bundle。bundles=[{captured_utc, bars}]。無 → None。"""
    wt = _parse(wake_ts)
    if wt is None or not bundles:
        return None
    best, bestd = None, None
    for b in bundles:
        bt = _parse(b.get("captured_utc"))
        if bt is None:
            continue
        d = abs((bt - wt).total_seconds())
        if bestd is None or d < bestd:
            best, bestd = b, d
    return best


# ── loaders（read-only）───────────────────────────────────────────────────────────

def load_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        return []
    return out


def load_theses(store=None):
    from ingest.thesis_store import ThesisStore
    store = store or ThesisStore()
    import sqlite3
    con = sqlite3.connect(store.path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT thesis_id, version, status, dir, wake_id, ts "
                           "FROM thesis_log ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [dict(r) for r in rows]


def load_bundles(root="storage/screenshots"):
    import glob
    import os
    out = []
    for p in glob.glob(os.path.join(root, "*", "ohlc_history.json")):
        try:
            rec = json.load(open(p, encoding="utf-8"))
            out.append({"captured_utc": rec.get("captured_utc"),
                        "bars": (rec.get("bars") or {}).get("m5") or []})
        except (OSError, json.JSONDecodeError):
            continue
    return out


# ── report ─────────────────────────────────────────────────────────────────────────

def _counter(items):
    d = {}
    for it in items:
        d[it] = d.get(it, 0) + 1
    return d


def build_report(wakes, queue, theses, bundles, *, since=None, tz=10, midband_pct=0.60) -> str:
    wl = [w for w in wakes if (since is None or (w.get("ts") or "") >= since)]
    L = ["# Wake 質素審計報表（read-only）",
         f"- 範圍：{since or '全部'} 起｜wake_log {len(wl)} 筆"
         f"｜wake_queue {len(queue)} 筆｜thesis_log {len(theses)} row｜bundles {len(bundles)}",
         f"- Sydney tz=+{tz}；mid-band = 中間 {int(midband_pct*100)}%（config midband_no_trade_pct）", ""]

    # ① 每日 + 每 session
    days = _counter(local_dt(w.get("ts"), tz).date().isoformat()
                    for w in wl if local_dt(w.get("ts"), tz))
    sess = _counter(session_of(w.get("ts"), tz) for w in wl)
    L.append("## ① 每日 / 每 session wake 數")
    L.append("| 日期(Sydney) | wake |")
    L.append("|---|---|")
    for d in sorted(days):
        L.append(f"| {d} | {days[d]} |")
    L.append("\n| session | wake |")
    L.append("|---|---|")
    for s in ("Asian", "London", "London/NY overlap", "NY", "off-session", "unknown"):
        if sess.get(s):
            L.append(f"| {s} | {sess[s]} |")

    # ② 分類
    cats = _counter(categorize_reason(w.get("reason", "")) for w in wl)
    L.append("\n## ② 按 trigger_reason 分類")
    L.append("| category | wake | % |")
    L.append("|---|---|---|")
    tot = len(wl) or 1
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        L.append(f"| {c} | {n} | {round(100*n/tot)}% |")

    # ③ wake→結果
    L.append("\n## ③ wake → 結果（consumed→thesis）")
    tstatus = _counter((t.get("status") or "?").upper() for t in theses)
    if queue:
        by_tid = {t.get("thesis_id"): (t.get("status") or "").upper() for t in theses}
        white = eff = uncons = other = 0
        for q in queue:
            cb = q.get("consumed_by")
            if not cb:
                uncons += 1
                continue
            st = by_tid.get(cb, "")
            if st in _WHITE:
                white += 1
            elif st in _ACTIVE:
                eff += 1
            else:
                other += 1
        qn = len(queue)
        L.append(f"- wake_queue {qn} 筆：**白叫(WAIT/NO_TRADE) {white}**｜**有效(ARMED/IN_TRADE) {eff}**"
                 f"｜其他 status {other}｜**未 consumed（Jones 冇跟／fatigue）{uncons}**")
        L.append(f"- fatigue rate（未 consumed）= {round(100*uncons/(qn or 1))}%；"
                 f"白叫 rate（consumed 中）= {round(100*white/((white+eff+other) or 1))}%")
    else:
        L.append("- ⚠️ **wake_queue 空**（Phase 1.5 bridge 未累積 / 已 reset）→ 無 wake↔thesis 逐筆 linkage。"
                 "歷史 wake_log 早過 bridge，本身冇 queue 記錄。")
    L.append(f"- thesis_log status 分佈：" +
             ("｜".join(f"{k}={v}" for k, v in sorted(tstatus.items())) or "（空）") +
             "（WAIT/NO_TRADE=白叫傾向；ARMED/IN_TRADE=有效）")

    # ④ range 位置
    L.append("\n## ④ wake 時價 vs 最近 range boundary（mid-band 白叫假設）")
    rows, mid, edge, nodata = [], 0, 0, 0
    for w in wl:
        rp = range_position(w.get("price"), (nearest_ohlc(w.get("ts"), bundles) or {}).get("bars"),
                            midband_pct=midband_pct)
        if rp is None:
            nodata += 1
            continue
        if rp["midband"]:
            mid += 1
        else:
            edge += 1
        rows.append((w.get("ts", "")[:19], categorize_reason(w.get("reason", "")),
                     w.get("price"), rp["low"], rp["high"], rp["dist_to_boundary"], rp["midband"]))
    an = mid + edge
    L.append(f"- 有價+ohlc 可算 {an} 筆（缺價/缺 ohlc {nodata} 筆跳過）："
             f"**mid-band {mid}（{round(100*mid/(an or 1))}%）**｜近邊界 {edge}")
    L.append("- 假設「mid-band wake 多數白叫」：要 consumed→WAIT linkage 先能逐筆驗證；"
             + ("wake_queue 空 → 本輪只出 mid-band 佔比，linkage 待 bridge 數據。"
                if not queue else "見 ③ 交叉。"))
    if rows:
        L.append("\n| ts | category | price | range low | high | dist→邊界 | mid-band |")
        L.append("|---|---|---|---|---|---|---|")
        for r in rows[:20]:
            L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {'✅' if r[6] else '—'} |")
    return "\n".join(L)


def main(argv=None) -> int:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="wake 質素審計（read-only）")
    ap.add_argument("--since", help="只計 ts >= 呢個（UTC ISO，如 2026-07-03T12:52:00Z）")
    ap.add_argument("--wake-log", default="storage/wake_log.jsonl")
    ap.add_argument("--wake-queue", default="storage/wake_queue.jsonl")
    ap.add_argument("--tz", type=int, default=10)
    args = ap.parse_args(argv)
    since = (args.since or "").replace("Z", "+00:00") or None
    print(build_report(load_jsonl(args.wake_log), load_jsonl(args.wake_queue),
                       load_theses(), load_bundles(), since=since, tz=args.tz))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
