from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from output.project_a.config import OutputConfig, fake_output_config
from output.project_a.dispatcher import Dispatcher
from output.project_a.fakes import FakeNotionTransport
from output.project_a.models import ResultStatus, Session5Error, parse_utc
from output.project_a.renderers import NotionRenderer, telegram_message, tradingview_specs

from .conftest import NOW, compile_input, delivery, non_actionable


@pytest.mark.parametrize(("key", "value", "code"), [
    ("port", 9222, "tv_wrong_port"),
    ("process_identity", "wrong", "tv_wrong_process"),
    ("tab_count", 2, "tv_wrong_tab_count"),
    ("selected_tab_id", "wrong", "tv_wrong_tab"),
    ("symbol", "USTEC", "tv_wrong_symbol"),
    ("feed", "OTHER", "tv_wrong_feed"),
    ("timeframe", "5m", "tv_wrong_timeframe"),
    ("layout_id", "wrong", "tv_wrong_layout"),
])
def test_tradingview_identity_gates_block_without_mutation(runtime, request_doc, verdict_doc,
                                                           key, value, code):
    made = compile_input(runtime, request_doc, verdict_doc)
    runtime["transports"]["tradingview"].identity[key] = value
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TRADINGVIEW")
    rendered = runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    assert rendered.status is ResultStatus.BLOCKED_SAFETY and rendered.error_code == code
    assert runtime["transports"]["tradingview"].objects == {}


def test_tradingview_partial_cleanup_never_deletes_unrelated_objects(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    tv = runtime["transports"]["tradingview"]
    tv.upsert("user:unrelated", {"object_id": "user:unrelated", "kind": "USER"})
    tv.fail_after = 2  # unrelated call plus one Project A object, then fail
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TRADINGVIEW")
    rendered = runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    assert rendered.error_code == "tv_partial_create_cleaned"
    assert "user:unrelated" in tv.objects
    assert all("user:unrelated" not in ref for ref in tv.deleted_refs)


def test_tradingview_retry_creates_no_duplicate_objects(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TRADINGVIEW")
    runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    before = dict(runtime["transports"]["tradingview"].objects)
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW) is None
    assert runtime["transports"]["tradingview"].objects == before and len(before) == 5


def test_expiry_rechecked_before_actionable_outputs(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    late = parse_utc(made["thesis"]["valid_until"]) + timedelta(seconds=1)
    results = runtime["dispatcher"].dispatch_setup(made["thesis"]["setup_id"], now=late)
    by_type = {runtime["store"].get_context(item.delivery_id).delivery["renderer_type"]: item
               for item in results}
    assert by_type["TRADINGVIEW"].error_code == "thesis_expired_before_drawing"
    assert by_type["TELEGRAM"].error_code == "thesis_expired_before_notification"
    assert by_type["MT5_DEMO"].error_code == "thesis_expired_before_mt5"
    assert by_type["NOTION"].status is ResultStatus.DRY_RUN_SUCCESS


def test_telegram_render_is_deterministic_and_semantic(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")
    context = runtime["store"].get_context(item["delivery_id"])
    first = telegram_message(context)
    assert first == telegram_message(context)
    for value in ("XAUUSD", "LONG", "APPROVE", "2416.5", "2414.5", "2418.5",
                  made["thesis"]["valid_until"], made["thesis"]["setup_id"]):
        assert value in first


def test_telegram_does_not_inject_model_markdown(runtime, request_doc, verdict_doc):
    verdict_doc["rationale"] = "*[click](tg://user?id=1)<b>unsafe</b>\x00"
    made = compile_input(runtime, request_doc, verdict_doc)
    context = runtime["store"].get_context(
        delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")["delivery_id"])
    message = telegram_message(context)
    assert "tg://" not in message and "<b>" not in message and "\x00" not in message


def test_telegram_retry_does_not_repeat_successful_tradingview(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    setup = made["thesis"]["setup_id"]
    runtime["dispatcher"].dispatch(delivery(runtime["store"], setup, "TRADINGVIEW")["delivery_id"], now=NOW)
    runtime["transports"]["telegram"].failure_mode = "retryable_before"
    tg = delivery(runtime["store"], setup, "TELEGRAM")
    assert runtime["dispatcher"].dispatch(tg["delivery_id"], now=NOW).status is ResultStatus.RETRYABLE_FAILURE
    assert runtime["dispatcher"].dispatch(tg["delivery_id"], now=NOW).status is ResultStatus.DRY_RUN_SUCCESS
    assert runtime["transports"]["tradingview"].mutation_calls == 5
    assert runtime["transports"]["telegram"].send_calls == 2


def test_telegram_uncertain_result_is_reconciled_before_retry(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "TELEGRAM")
    runtime["transports"]["telegram"].failure_mode = "uncertain_after_success"
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW).status is ResultStatus.UNCERTAIN
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW) is None
    assert runtime["dispatcher"].reconcile_uncertain(
        item["delivery_id"], now=NOW, actor="test", reason="lookup fake Telegram") is True
    assert runtime["transports"]["telegram"].send_calls == 1


def test_missing_or_non_numeric_telegram_allowlist_fails_config_closed():
    base = {
        "shadow": True, "dry_run": True, "enabled_renderers": ["TELEGRAM"],
        "tradingview": {"port": 4999, "expected_process_identity": "fake",
                        "expected_symbol": "XAUUSD", "feed_allowlist": ["ICMARKETS"],
                        "expected_timeframe": "1m", "expected_layout_id": "layout",
                        "expected_tab_id": "tab"},
        "telegram": {"destination_id": "@jones", "owner_user_id": "", "direct_message_only": True},
        "notion": {"database_id": "db", "schema_fields": []},
        "mt5": {"account_allowlist": ["demo"], "server_allowlist": ["demo-server"],
                "terminal_path_allowlist": ["demo-path"], "symbol_mapping": "XAUUSD"},
    }
    with pytest.raises(Session5Error, match="telegram_allowlist"):
        OutputConfig.from_mapping(base)


def test_notion_retry_updates_same_record(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    setup = made["thesis"]["setup_id"]
    item = delivery(runtime["store"], setup, "NOTION")
    runtime["transports"]["notion"].failure_mode = "retryable_before"
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW).status is ResultStatus.RETRYABLE_FAILURE
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW).status is ResultStatus.DRY_RUN_SUCCESS
    assert len(runtime["transports"]["notion"].records) == 1


def test_notion_conflicting_setup_record_fails_closed(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    setup = made["thesis"]["setup_id"]
    runtime["transports"]["notion"].records[setup] = {
        "page_id": "fake://existing", "core_hash": "conflict", "record": {}}
    item = delivery(runtime["store"], setup, "NOTION")
    rendered = runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    assert rendered.status is ResultStatus.TERMINAL_FAILURE
    assert rendered.error_code == "notion_setup_conflict"


@pytest.mark.parametrize("decision", ["REJECT", "EXPIRED"])
def test_notion_retains_reject_and_expired_complete_chain(runtime, request_doc, verdict_doc, decision):
    made = compile_input(runtime, request_doc, non_actionable(verdict_doc, decision))
    setup = made["thesis"]["setup_id"]
    runtime["dispatcher"].dispatch_setup(setup, now=NOW)
    record = runtime["transports"]["notion"].records[setup]["record"]
    assert record["request"]["source_event_ids"] == request_doc["source_event_ids"]
    assert record["verdict"]["verdict"] == decision
    assert record["thesis"]["decision"] == decision
    assert record["audit_ref"] == "fixture://audit/verdict"


def test_actual_legacy_notion_schema_is_blocked_without_migration(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    legacy = replace(runtime["config"], notion=replace(runtime["config"].notion,
                                                       schema_fields=("Call", "wake_id", "thesis_status")))
    fake = FakeNotionTransport()
    renderer = NotionRenderer(legacy, fake, runtime["store"])
    dispatcher = Dispatcher(runtime["store"], legacy, [renderer])
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "NOTION")
    rendered = dispatcher.dispatch(item["delivery_id"], now=NOW)
    assert rendered.error_code == "notion_schema_incompatible" and fake.records == {}


@pytest.mark.parametrize(("field", "value", "code"), [
    ("environment", "UNKNOWN", "mt5_unknown_environment"),
    ("trade_mode", "LIVE", "mt5_live_or_unknown_account"),
    ("account_id", None, "mt5_account_not_allowlisted"),
    ("server", "OTHER", "mt5_server_not_allowlisted"),
    ("symbol", "GOLD", "mt5_symbol_mapping"),
])
def test_mt5_positive_demo_attestation_is_mandatory(runtime, request_doc, verdict_doc,
                                                     field, value, code):
    made = compile_input(runtime, request_doc, verdict_doc)
    runtime["transports"]["mt5"].attestation[field] = value
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "MT5_DEMO")
    rendered = runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    assert rendered.status is ResultStatus.BLOCKED_SAFETY and rendered.error_code == code
    assert runtime["transports"]["mt5"].orders == {}


def test_mt5_spread_rechecked_immediately_before_dry_run(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    runtime["transports"]["mt5"].attestation["spread_points"] = 11
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "MT5_DEMO")
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW).error_code == "mt5_spread_gate"


def test_mt5_defaults_to_dry_run_and_demo_flag_disabled(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "MT5_DEMO")
    rendered = runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    request = rendered.detail["request"]
    assert rendered.status is ResultStatus.DRY_RUN_SUCCESS
    assert request["dry_run"] is True and request["order_placed"] is False
    assert request["demo_mirror_enabled"] is False


def test_duplicate_mt5_request_creates_no_second_fake_order(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "MT5_DEMO")
    runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW)
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW) is None
    assert runtime["transports"]["mt5"].submit_calls == 1 and len(runtime["transports"]["mt5"].orders) == 1


def test_uncertain_mt5_result_reconciles_by_client_id_before_retry(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    item = delivery(runtime["store"], made["thesis"]["setup_id"], "MT5_DEMO")
    runtime["transports"]["mt5"].failure_mode = "uncertain_after_acceptance"
    assert runtime["dispatcher"].dispatch(item["delivery_id"], now=NOW).status is ResultStatus.UNCERTAIN
    assert runtime["dispatcher"].reconcile_uncertain(
        item["delivery_id"], now=NOW, actor="test", reason="client ID lookup")
    assert runtime["transports"]["mt5"].submit_calls == 1


def test_all_renderer_semantics_match_one_thesis(runtime, request_doc, verdict_doc):
    made = compile_input(runtime, request_doc, verdict_doc)
    setup, thesis = made["thesis"]["setup_id"], made["thesis"]
    runtime["dispatcher"].dispatch_setup(setup, now=NOW)
    specs = tradingview_specs(runtime["store"].get_context(
        delivery(runtime["store"], setup, "TRADINGVIEW")["delivery_id"]))
    prices = {item["kind"]: item.get("price") for item in specs if "price" in item}
    message = next(iter(runtime["transports"]["telegram"].messages.values()))["message"]
    notion = runtime["transports"]["notion"].records[setup]["record"]["thesis"]
    mt5 = next(iter(runtime["transports"]["mt5"].orders.values()))["request"]
    assert (prices["ENTRY"], prices["SL"], prices["TP"]) == (thesis["entry"], thesis["sl"], thesis["tp"])
    assert all(str(thesis[key]) in message for key in ("entry", "sl", "tp"))
    assert notion == thesis
    assert (mt5["entry"], mt5["sl"], mt5["tp"]) == (thesis["entry"], thesis["sl"], thesis["tp"])
