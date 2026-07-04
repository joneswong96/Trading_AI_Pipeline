"""tests/conftest.py — Phase 3 test hardening（autouse 隔離）。

堵返 commit-2 demo 個漏洞：**任何 test 都零外發（Telegram/Notion）、零污染真 storage、永不讀真 .env**。
- 停 fanout：TelegramPublisher/NotionLogger enabled()→False、push/log→若被叫即 fail（catch 漏網）。
- storage 一律 temp：DEFAULT_DB / wake_queue / thesis_dir / wake_log 全部改 per-test tmp。
- 唔讀真 .env：清走 token env var + load_dotenv 變 no-op。
需要真外發 / 真 storage 嘅 test 可自行 monkeypatch 覆蓋返（呢度只設安全預設）。
"""
import pytest


def _blocked(*_a, **_k):
    raise AssertionError("external send blocked in tests（conftest autouse）")


@pytest.fixture(autouse=True)
def _test_isolation(tmp_path, monkeypatch):
    # ── 1) 永不讀真 .env / 無外部 token ────────────────────────────────────────────
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID",
              "NOTION_TOKEN", "NOTION_DB_ID", "NOTION_DATABASE_ID", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    try:
        import dotenv
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False, raising=False)
    except ImportError:
        pass

    # ── 2) 停晒 fanout / 外發 ─────────────────────────────────────────────────────
    from publish.notion_log import NotionLogger
    from publish.telegram import TelegramPublisher
    monkeypatch.setattr(TelegramPublisher, "enabled", lambda self: False)
    monkeypatch.setattr(NotionLogger, "enabled", lambda self: False)
    monkeypatch.setattr(TelegramPublisher, "push", _blocked, raising=False)
    monkeypatch.setattr(NotionLogger, "log", _blocked, raising=False)

    # ── 3) storage 一律 temp（default-arg 綁死 → 改埋 __defaults__）────────────────
    tmp_db = str(tmp_path / "trading.db")
    tmp_wq = tmp_path / "wake_queue.jsonl"
    tmp_thesis = tmp_path / "thesis"

    import storage.db as sdb
    from ingest import alert_log as al
    from ingest import thesis_store as ts
    from ingest import wake_queue as wq
    from analyze import thesis_emit as te

    for mod in (sdb, al, ts):
        monkeypatch.setattr(mod, "DEFAULT_DB", tmp_db, raising=False)
    for cls in (sdb.Store, al.AlertLog, ts.ThesisStore):
        monkeypatch.setattr(cls.__init__, "__defaults__", (tmp_db,))

    monkeypatch.setattr(wq, "WAKE_QUEUE", tmp_wq, raising=False)
    monkeypatch.setattr(wq.append, "__defaults__", (tmp_wq,))
    monkeypatch.setattr(wq._read_all, "__defaults__", (tmp_wq,))
    monkeypatch.setattr(wq.latest_unconsumed, "__defaults__", (tmp_wq,))
    monkeypatch.setattr(wq.mark_consumed, "__defaults__", (None, tmp_wq))

    monkeypatch.setattr(te, "THESIS_DIR", tmp_thesis, raising=False)
    kw = dict(te.emit.__kwdefaults__ or {})
    kw["thesis_dir"] = tmp_thesis
    monkeypatch.setattr(te.emit, "__kwdefaults__", kw)

    # webhook 有 import-time module 實例（真 DB）+ WAKE_LOG const → 換 temp（有 fastapi 先）
    try:
        import ingest.webhook_server as srv
        monkeypatch.setattr(srv, "_alog", al.AlertLog(tmp_db), raising=False)
        monkeypatch.setattr(srv, "_thesis", ts.ThesisStore(tmp_db), raising=False)
        monkeypatch.setattr(srv, "WAKE_LOG", tmp_path / "wake_log.jsonl", raising=False)
    except Exception:
        pass

    yield
