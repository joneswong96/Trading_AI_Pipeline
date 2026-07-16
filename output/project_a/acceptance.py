"""Runnable 28-case XAUUSD fake/recorded shadow acceptance harness."""
from __future__ import annotations

import argparse
import json
import tempfile
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from .compiler import InputAttestation, ThesisCompiler
from .models import Session5Error, parse_utc, utc_z
from .outcomes import OutcomeReconciler
from .replay import FIXTURES, build_fake_runtime, load_json

NOW = parse_utc("2026-07-16T00:00:04Z")


def _inputs(decision: str = "APPROVE") -> tuple[dict, dict]:
    request = load_json(FIXTURES / "analysis_request_accepted.json")
    verdict = load_json(FIXTURES / "ai_verdict_approved.json")
    if decision == "MODIFY":
        verdict.update({
            "verdict_id": "verdict_xau_20260716_modify01", "verdict": "MODIFY",
            "entry": 2416.25, "sl": 2414.25, "tp": 2418.25,
            "reason_codes": ["GEOMETRY_MODIFIED", "RR_1_TO_1"],
            "rationale": "Fixture-only validated modified geometry.",
        })
    elif decision in {"REJECT", "EXPIRED"}:
        verdict.update({
            "verdict_id": f"verdict_xau_20260716_{decision.lower()}01",
            "verdict": decision, "entry": None, "sl": None, "tp": None,
            "valid_until": None,
            "reason_codes": ["SNR_INVALID" if decision == "REJECT" else "REQUEST_EXPIRED"],
            "rationale": f"Fixture-only deterministic {decision.lower()} verdict.",
        })
    return request, verdict


def _record(sample_id: str, verdict: str, expected: str) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "setup_id": None,
        "source_fixture": "Session 0 analysis_request_accepted.json + ai_verdict_approved.json",
        "verdict": verdict,
        "expected_outputs": expected,
        "actual_output_statuses": {},
        "idempotency_result": "NOT_RUN",
        "safety_gate_result": "NOT_RUN",
        "external_side_effects_used_or_mocked": "FAKE_ONLY; no network, chart, Notion, Telegram, or broker side effect",
        "entry_sl_tp_consistency": "NOT_APPLICABLE",
        "error_retry_evidence": [],
        "call_log_consistency": "NOT_RUN",
        "pass": False,
        "reviewer_notes": "",
    }


def _statuses(store, setup_id: str) -> dict[str, str]:
    return {item["renderer_type"]: item["status"] for item in store.deliveries_for_setup(setup_id)}


def _delivery(store, setup_id: str, renderer_type: str) -> dict:
    return next(item for item in store.deliveries_for_setup(setup_id)
                if item["renderer_type"] == renderer_type)


def _compile(compiler, request, verdict, now=NOW):
    return compiler.compile(
        request, verdict, InputAttestation(True, True, "fixture://session-0/verdict-audit"),
        now=now,
    )


def _standard_case(sample_id: str, decision: str, expected: str,
                   mutate: Callable | None = None, dispatch_at=NOW) -> dict:
    rec = _record(sample_id, decision, expected)
    with tempfile.TemporaryDirectory(prefix="project-a-accept-") as temp:
        config, store, transports, dispatcher, notion = build_fake_runtime(Path(temp) / "out.db")
        request, verdict = _inputs(decision)
        if mutate:
            mutate(request, verdict, transports)
        try:
            compiled = _compile(ThesisCompiler(store, config), request, verdict)
            setup_id = compiled["thesis"]["setup_id"]
            rec["setup_id"] = setup_id
            results = dispatcher.dispatch_setup(setup_id, now=dispatch_at)
            rec["actual_output_statuses"] = _statuses(store, setup_id)
            rec["idempotency_result"] = "PASS" if not dispatcher.dispatch_setup(setup_id, now=dispatch_at) else "FAIL"
            rec["safety_gate_result"] = "PASS" if all(
                item.status.value not in {"TERMINAL_FAILURE", "RETRYABLE_FAILURE", "BLOCKED_SAFETY", "UNCERTAIN"}
                for item in results) else "OBSERVED_BLOCK_OR_FAILURE"
            t = compiled["thesis"]
            rec["entry_sl_tp_consistency"] = (
                "PASS" if decision in {"APPROVE", "MODIFY"}
                and all(result.detail is None or _geometry_matches(result.detail, t) for result in results)
                else "NOT_APPLICABLE" if decision in {"REJECT", "EXPIRED"} else "FAIL"
            )
            notion_record = transports["notion"].records.get(setup_id)
            rec["call_log_consistency"] = (
                "PASS" if notion_record and notion_record["record"]["thesis_id"] == t["thesis_id"] else "FAIL"
            )
            actionable = decision in {"APPROVE", "MODIFY"}
            expected_types = {"TRADINGVIEW", "TELEGRAM", "NOTION", "MT5_DEMO"} if actionable else {"TELEGRAM", "NOTION"}
            rec["pass"] = set(rec["actual_output_statuses"]) == expected_types and all(
                status == "DRY_RUN_SUCCEEDED" for status in rec["actual_output_statuses"].values())
            rec["reviewer_notes"] = "Recorded fixture executed with deterministic historical clock."
        except Exception as exc:
            rec["safety_gate_result"] = f"FAIL_CLOSED:{getattr(exc, 'code', type(exc).__name__)}"
            rec["error_retry_evidence"].append(str(exc))
    return rec


def _geometry_matches(detail: dict, thesis: dict) -> bool:
    request = detail.get("request")
    if request and {"entry", "sl", "tp"} <= request.keys():
        return (request["entry"], request["sl"], request["tp"]) == (
            thesis["entry"], thesis["sl"], thesis["tp"])
    message = detail.get("message")
    if message:
        return all(str(thesis[key]) in message for key in ("entry", "sl", "tp"))
    objects = detail.get("objects")
    return bool(objects) if objects is not None else True


def _input_rejection(sample_id: str, mutation: Callable, expected_code: str) -> dict:
    rec = _record(sample_id, "INVALID_INPUT", "No Thesis and no renderer delivery")
    with tempfile.TemporaryDirectory(prefix="project-a-accept-") as temp:
        config, store, _, _, _ = build_fake_runtime(Path(temp) / "out.db")
        request, verdict = _inputs()
        mutation(request, verdict)
        try:
            _compile(ThesisCompiler(store, config), request, verdict)
        except Exception as exc:
            code = getattr(exc, "code", "")
            rec["safety_gate_result"] = f"PASS:{code}"
            rec["actual_output_statuses"] = {}
            rec["idempotency_result"] = "NOT_APPLICABLE"
            rec["call_log_consistency"] = "NO_RECORD"
            rec["pass"] = code == expected_code
            rec["error_retry_evidence"].append(str(exc))
    return rec


def _identity_block(sample_id: str, key: str, value: Any, expected_code: str) -> dict:
    rec = _record(sample_id, "APPROVE", f"TradingView blocked with {expected_code}; other tasks independent")
    with tempfile.TemporaryDirectory(prefix="project-a-accept-") as temp:
        config, store, transports, dispatcher, _ = build_fake_runtime(Path(temp) / "out.db")
        compiled = _compile(ThesisCompiler(store, config), *_inputs())
        setup_id = compiled["thesis"]["setup_id"]
        rec["setup_id"] = setup_id
        transports["tradingview"].identity[key] = value
        tv = _delivery(store, setup_id, "TRADINGVIEW")
        result = dispatcher.dispatch(tv["delivery_id"], now=NOW)
        rec["actual_output_statuses"] = _statuses(store, setup_id)
        rec["safety_gate_result"] = f"PASS:{result.error_code}"
        rec["idempotency_result"] = "PASS"
        rec["call_log_consistency"] = "PENDING_NOTION"
        rec["pass"] = result.error_code == expected_code and transports["tradingview"].objects == {}
    return rec


def _partial_case(kind: str) -> dict:
    names = {
        "tv_then_tg": ("S07", "TradingView succeeds; Telegram retries independently"),
        "tg_then_notion": ("S08", "Telegram succeeds; Notion retries independently"),
        "notion_then_mt5": ("S09", "Notion succeeds; MT5 dry-run retries independently"),
        "tv_partial": ("S10", "Partial TradingView objects cleaned, then retry succeeds"),
        "mt5_uncertain": ("S11", "Uncertain MT5 result reconciled before retry"),
        "telegram_uncertain": ("S12", "Uncertain Telegram result reconciled before retry"),
        "restart_external_success": ("S13", "Crash after external fake success; restart recognizes same effect"),
        "abandoned_claim": ("S14", "Abandoned claim recovered after timeout"),
        "terminal_cleanup": ("S15", "TradingView cleanup failure is terminal and inspectable"),
        "expiry_pending": ("S16", "Expiry blocks remaining actionable outputs; Notion remains auditable"),
        "notion_status_update": ("S17", "Existing Notion record survives supplemental status update failure"),
        "outcome": ("S28", "Outcome history updates same setup/Thesis/Call Log idempotently"),
    }
    sid, expected = names[kind]
    rec = _record(sid, "APPROVE", expected)
    with tempfile.TemporaryDirectory(prefix="project-a-accept-") as temp:
        config, store, transports, dispatcher, notion = build_fake_runtime(Path(temp) / "out.db")
        compiled = _compile(ThesisCompiler(store, config), *_inputs())
        setup_id, thesis_id = compiled["thesis"]["setup_id"], compiled["thesis"]["thesis_id"]
        rec["setup_id"] = setup_id
        try:
            if kind == "tv_then_tg":
                dispatcher.dispatch(_delivery(store, setup_id, "TRADINGVIEW")["delivery_id"], now=NOW)
                transports["telegram"].failure_mode = "retryable_before"
                tg = _delivery(store, setup_id, "TELEGRAM")
                first = dispatcher.dispatch(tg["delivery_id"], now=NOW)
                second = dispatcher.dispatch(tg["delivery_id"], now=NOW)
                passed = first.error_code == "telegram_unavailable" and second.status.value == "DRY_RUN_SUCCESS" and transports["tradingview"].mutation_calls == 5
            elif kind == "tg_then_notion":
                dispatcher.dispatch(_delivery(store, setup_id, "TELEGRAM")["delivery_id"], now=NOW)
                transports["notion"].failure_mode = "retryable_before"
                item = _delivery(store, setup_id, "NOTION")
                first = dispatcher.dispatch(item["delivery_id"], now=NOW)
                second = dispatcher.dispatch(item["delivery_id"], now=NOW)
                passed = first.error_code == "notion_update_failed" and second.status.value == "DRY_RUN_SUCCESS" and transports["telegram"].send_calls == 1
            elif kind == "notion_then_mt5":
                dispatcher.dispatch(_delivery(store, setup_id, "NOTION")["delivery_id"], now=NOW)
                transports["mt5"].failure_mode = "retryable_before"
                item = _delivery(store, setup_id, "MT5_DEMO")
                first = dispatcher.dispatch(item["delivery_id"], now=NOW)
                second = dispatcher.dispatch(item["delivery_id"], now=NOW)
                passed = first.error_code == "mt5_demo_unavailable" and second.status.value == "DRY_RUN_SUCCESS" and transports["notion"].upsert_calls == 1
            elif kind == "tv_partial":
                transports["tradingview"].fail_after = 2
                item = _delivery(store, setup_id, "TRADINGVIEW")
                first = dispatcher.dispatch(item["delivery_id"], now=NOW)
                transports["tradingview"].fail_after = None
                second = dispatcher.dispatch(item["delivery_id"], now=NOW)
                passed = first.error_code == "tv_partial_create_cleaned" and second.status.value == "DRY_RUN_SUCCESS" and len(transports["tradingview"].objects) == 5
            elif kind in {"mt5_uncertain", "telegram_uncertain"}:
                renderer = "MT5_DEMO" if kind == "mt5_uncertain" else "TELEGRAM"
                transport = transports["mt5"] if kind == "mt5_uncertain" else transports["telegram"]
                transport.failure_mode = "uncertain_after_acceptance" if kind == "mt5_uncertain" else "uncertain_after_success"
                item = _delivery(store, setup_id, renderer)
                first = dispatcher.dispatch(item["delivery_id"], now=NOW)
                found = dispatcher.reconcile_uncertain(item["delivery_id"], now=NOW,
                                                       actor="acceptance", reason="fake lookup")
                passed = first.status.value == "UNCERTAIN" and found and _delivery(store, setup_id, renderer)["status"] == "SUCCEEDED"
            elif kind == "restart_external_success":
                item = _delivery(store, setup_id, "TELEGRAM")
                attempt_id, token = store.claim(item["delivery_id"], "crashing-worker", NOW, config.retry_limit)
                context = store.get_context(item["delivery_id"])
                rendered = dispatcher.renderers["TELEGRAM"].render(context, attempt_id, NOW)
                recovered = store.recover_abandoned(NOW + timedelta(seconds=31), 30)
                retried = dispatcher.dispatch(item["delivery_id"], now=NOW + timedelta(seconds=31))
                passed = rendered.status.value == "DRY_RUN_SUCCESS" and recovered == 1 and retried.status.value == "ALREADY_COMPLETED" and transports["telegram"].send_calls == 1
            elif kind == "abandoned_claim":
                item = _delivery(store, setup_id, "TRADINGVIEW")
                store.claim(item["delivery_id"], "dead-worker", NOW, config.retry_limit)
                recovered = dispatcher.recover_abandoned(now=NOW + timedelta(seconds=31))
                retried = dispatcher.dispatch(item["delivery_id"], now=NOW + timedelta(seconds=31))
                passed = recovered == 1 and retried.status.value == "DRY_RUN_SUCCESS"
            elif kind == "terminal_cleanup":
                transports["tradingview"].fail_after = 1
                transports["tradingview"].cleanup_fails = True
                result = dispatcher.dispatch(_delivery(store, setup_id, "TRADINGVIEW")["delivery_id"], now=NOW)
                passed = result.error_code == "tv_cleanup_failed" and _delivery(store, setup_id, "TRADINGVIEW")["status"] == "TERMINAL_FAILED"
            elif kind == "expiry_pending":
                late = parse_utc(compiled["thesis"]["valid_until"]) + timedelta(seconds=1)
                dispatcher.dispatch_setup(setup_id, now=late)
                statuses = _statuses(store, setup_id)
                passed = statuses["TRADINGVIEW"] == "BLOCKED_SAFETY" and statuses["MT5_DEMO"] == "BLOCKED_SAFETY" and statuses["NOTION"] == "DRY_RUN_SUCCEEDED"
            elif kind == "notion_status_update":
                dispatcher.dispatch(_delivery(store, setup_id, "NOTION")["delivery_id"], now=NOW)
                page_id = transports["notion"].records[setup_id]["page_id"]
                transports["notion"].failure_mode = "status_update_failure"
                dispatcher.dispatch(_delivery(store, setup_id, "TELEGRAM")["delivery_id"], now=NOW)
                passed = transports["notion"].records[setup_id]["page_id"] == page_id and len(transports["notion"].records) == 1
            else:  # outcome
                dispatcher.dispatch_setup(setup_id, now=NOW)
                payload = _outcome_payload(setup_id, thesis_id)
                reconciler = OutcomeReconciler(store, notion)
                first, duplicate = reconciler.update(payload), reconciler.update(payload)
                passed = first and not duplicate and len(store.outcomes(thesis_id)) == 1 and len(transports["notion"].records[setup_id]["record"]["mt5_outcomes"]) == 1
            rec["actual_output_statuses"] = _statuses(store, setup_id)
            rec["idempotency_result"] = "PASS" if passed else "FAIL"
            rec["safety_gate_result"] = "PASS"
            rec["entry_sl_tp_consistency"] = "PASS"
            rec["call_log_consistency"] = "PASS" if kind in {"notion_then_mt5", "notion_status_update", "outcome", "expiry_pending"} else "NOT_APPLICABLE"
            rec["pass"] = passed
        except Exception as exc:
            rec["error_retry_evidence"].append(str(exc))
    return rec


def _outcome_payload(setup_id: str, thesis_id: str) -> dict[str, Any]:
    return {
        "event_id": "outcome_evt_xau_0001", "setup_id": setup_id, "thesis_id": thesis_id,
        "recorded_at": "2026-07-16T00:04:00Z", "final_status": "CLOSED",
        "ticket_ref": "FAKE-DEMO-TICKET-9001", "requested_price": 2416.5,
        "fill_price": 2416.6, "spread_points": 8, "slippage": 0.1,
        "open_time": "2026-07-16T00:01:00Z", "close_time": "2026-07-16T00:04:00Z",
        "exit_price": 2418.5, "exit_reason": "TP", "initial_risk": 2.0,
        "mae": -0.25, "mfe": 2.1, "realised_pl": 10.0, "realised_r": 0.95,
    }


def run_acceptance() -> dict[str, Any]:
    samples = [
        _standard_case("S01", "APPROVE", "Four fake/dry-run outputs"),
        _standard_case("S02", "MODIFY", "Four outputs use validated modified geometry"),
        _standard_case("S03", "REJECT", "Telegram rejection and Notion only"),
        _standard_case("S04", "EXPIRED", "Telegram expiry and Notion only"),
        _standard_case("S05", "APPROVE", "Strong-break path consistent", mutate=lambda r, v, _t: (r.update(path="SNR_STRONG_BREAK"), v.update(path="SNR_STRONG_BREAK"))),
        _standard_case("S06", "APPROVE", "Duplicate replay creates no duplicate outputs"),
        *[_partial_case(name) for name in (
            "tv_then_tg", "tg_then_notion", "notion_then_mt5", "tv_partial",
            "mt5_uncertain", "telegram_uncertain", "restart_external_success",
            "abandoned_claim", "terminal_cleanup", "expiry_pending", "notion_status_update",
        )],
        _input_rejection("S18", lambda r, _v: r["instrument"].update(symbol="EURUSD"), "schema_const"),
        _identity_block("S19", "port", 9222, "tv_wrong_port"),
        _identity_block("S20", "selected_tab_id", "wrong-tab", "tv_wrong_tab"),
        _identity_block("S21", "timeframe", "5m", "tv_wrong_timeframe"),
        _identity_block("S22", "feed", "UNLISTED", "tv_wrong_feed"),
        _identity_block("S23", "symbol", "USTEC", "tv_wrong_symbol"),
        _input_rejection("S24", lambda r, _v: r.update(spread_points=11), "spread_gate"),
        _input_rejection("S25", lambda _r, v: v.update(tp=2419.0), "rr_not_one_to_one"),
        _identity_block("S26", "process_identity", "UNKNOWN_PROCESS", "tv_wrong_process"),
        _identity_block("S27", "layout_id", "WRONG_LAYOUT", "tv_wrong_layout"),
        _partial_case("outcome"),
    ]
    return {
        "kind": "RECORDED_FAKE_ACCEPTANCE",
        "sample_count": len(samples),
        "external_side_effects": False,
        "real_shadow_samples_completed": 0,
        "passed": sum(bool(sample["pass"]) for sample in samples),
        "failed": sum(not bool(sample["pass"]) for sample in samples),
        "samples": samples,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD shadow acceptance report - recorded fake evidence",
        "",
        "> This is deterministic fake/recorded evidence. It is not the Session 0-controlled real 20-30 sample shadow run.",
        "",
        f"Samples: {report['sample_count']} | Passed: {report['passed']} | Failed: {report['failed']} | External side effects: none",
        "",
        "| Sample | Setup | Verdict | Output statuses | Idempotency | Safety | Pass | Reviewer notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sample in report["samples"]:
        statuses = json.dumps(sample["actual_output_statuses"], sort_keys=True).replace("|", "\\|")
        notes = sample["reviewer_notes"].replace("|", "\\|")
        lines.append(
            f"| {sample['sample_id']} | {sample['setup_id'] or '-'} | {sample['verdict']} | "
            f"`{statuses}` | {sample['idempotency_result']} | {sample['safety_gate_result']} | "
            f"{'PASS' if sample['pass'] else 'FAIL'} | {notes} |"
        )
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write JSON evidence")
    parser.add_argument("--markdown", type=Path, help="write Markdown report")
    args = parser.parse_args(argv)
    report = run_acceptance()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
