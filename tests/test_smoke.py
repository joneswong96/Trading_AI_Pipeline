"""Step 0 smoke tests: repo 骨架 + config 行到先算環境 OK."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_assets():
    with open(ROOT / "config" / "assets.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_repo_structure_matches_spec():
    for d in ["config", "capture", "precheck", "analyze", "indicators",
              "gates", "publish", "storage", "scheduler", "tests", "docs"]:
        assert (ROOT / d).is_dir(), f"missing dir: {d}"
    for f in ["CLAUDE.md", ".env.example", "docs/SPEC.md", "docs/runbook.md"]:
        assert (ROOT / f).is_file(), f"missing file: {f}"


def test_assets_yaml_m0_scope():
    cfg = load_assets()
    assets = cfg["assets"]
    # M0 scope 凍結：淨係 XAUUSD enabled
    enabled = [k for k, v in assets.items() if v.get("enabled")]
    assert enabled == ["xauusd"]
    xau = assets["xauusd"]
    # input bundle：5 張 layout = 9 個 chart（restructure 後：g4=1m+5m、g5=15m+30m、g2 純 Renko/WMA）
    shots = xau["screenshots"]
    assert len(shots) == 5
    assert sum(len(s["charts"]) for s in shots) == 9
    # gate mandatory input（Anti-Failure #16）；15m+30m 而家喺 g5
    assert xau["gate_timeframes"] == ["1m", "5m", "15m", "30m"]
    assert any(s["id"] == "g5_15m_30m" for s in shots)
    # 每 1 分鐘（Q4=A）
    assert cfg["scheduler"]["interval_seconds"] == 60


def test_env_example_has_required_keys():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID", "NOTION_TOKEN", "NOTION_CALLLOG_DB_ID",
                "TV_CDP_PORT", "PLAYWRIGHT_PROFILE_DIR"]:
        assert key in text, f".env.example missing {key}"


def test_spec_md_contains_locked_rules():
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    for needle in ["推送政策", "Two-Strike", "MACD 4-TF", "Fresh Eyes",
                   "Anti-Failure", "Golden Sample", "9 個 chart",
                   # 2026-06-11 SPEC B source 更新（Step 3 prompt 依據）
                   "22 Anti-Failure", "Day-Type Gate", "Armed Order framing",
                   "Re-entry 規則", "R:R 標準"]:
        assert needle in spec, f"SPEC.md missing section: {needle}"
