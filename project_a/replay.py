"""Deterministic, no-network Project A golden-fixture replay harness."""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from contracts import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    EVENT_SCHEMA_V0_2,
    THESIS_SCHEMA_V1,
    ContractError,
    canonical_json,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "project_a"
CONFIG = ROOT / "config" / "project_a.yaml"


class ReplayFailure(RuntimeError):
    pass


def _load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["project_a"]


def _enforce_shadow(config: dict) -> None:
    required = {
        "enabled_instruments": ["XAUUSD"],
        "mode": "SHADOW",
        "execution_environment": "MT5_DEMO",
        "live_execution": False,
        "order_placement": False,
        "fail_closed_on_environment_mismatch": True,
        "base_timeframe": "1m",
    }
    for key, expected in required.items():
        if config.get(key) != expected:
            raise ReplayFailure(f"unsafe config: {key} must be {expected!r}")
    tv = config.get("tradingview", {}).get("XAUUSD", {})
    if (tv.get("enabled") is not True or tv.get("port") != 4999
            or tv.get("expected_symbol") != "XAUUSD"
            or tv.get("expected_timeframe") != "1m"):
        raise ReplayFailure("unsafe config: XAUUSD/port 4999/1m identity mismatch")
    if any(profile.get("enabled") for symbol, profile in config.get("tradingview", {}).items()
           if symbol != "XAUUSD"):
        raise ReplayFailure("unsafe config: non-XAUUSD profile enabled")
    if config.get("risk") != {"max_spread_points": 10, "rr": 1.0}:
        raise ReplayFailure("unsafe config: risk must be 10 normalized points and 1:1 RR")
    expected_contracts = {
        "event": EVENT_SCHEMA_V0_2,
        "analysis_request": ANALYSIS_REQUEST_SCHEMA_V1,
        "ai_verdict": AI_VERDICT_SCHEMA_V1,
        "thesis": THESIS_SCHEMA_V1,
    }
    if config.get("contracts") != expected_contracts:
        raise ReplayFailure("unsafe config: contract versions do not match the frozen registry")


def replay_event_cases() -> list[dict]:
    results = []
    for name, case in _load_json("event_cases.json").items():
        expected = case["expected"]
        try:
            validate_contract(EVENT_SCHEMA_V0_2, case["payload"])
            actual = {"valid": True, "outcome": case["payload"]["disposition"]["status"]}
        except ContractError as exc:
            actual = {"valid": False, "error_code": exc.code, "error": str(exc)}
        if actual["valid"] != expected["valid"]:
            raise ReplayFailure(f"{name}: validity mismatch: {actual}")
        if expected["valid"] and actual["outcome"] != expected["outcome"]:
            raise ReplayFailure(f"{name}: outcome mismatch: {actual}")
        if not expected["valid"] and actual["error_code"] != expected["error_code"]:
            raise ReplayFailure(f"{name}: error mismatch: {actual}")
        results.append({"case": name, **actual})
    return results


def replay_accepted_pipeline() -> dict:
    config = _config()
    _enforce_shadow(config)
    event = deepcopy(_load_json("event_cases.json")["accepted_alert"]["payload"])
    request = _load_json("analysis_request_accepted.json")
    verdict = _load_json("ai_verdict_approved.json")
    thesis = _load_json("thesis_lifecycle.json")[0]
    output = _load_json("downstream_output.json")

    stages = [
        ("event", EVENT_SCHEMA_V0_2, event),
        ("analysis_request", ANALYSIS_REQUEST_SCHEMA_V1, request),
        ("ai_verdict", AI_VERDICT_SCHEMA_V1, verdict),
        ("thesis", THESIS_SCHEMA_V1, thesis),
    ]
    for _, contract, document in stages:
        validate_contract(contract, document)

    ids = {
        "setup_id": event["setup_id"],
        "correlation_id": event["correlation_id"],
        "event_id": event["event_id"],
        "request_id": request["request_id"],
        "verdict_id": verdict["verdict_id"],
        "thesis_id": thesis["thesis_id"],
    }
    checks = [
        request["causation_id"] == ids["event_id"],
        verdict["causation_id"] == ids["request_id"],
        thesis["causation_id"] == ids["verdict_id"],
        all(doc["setup_id"] == ids["setup_id"] for doc in (request, verdict, thesis, output)),
        all(doc["correlation_id"] == ids["correlation_id"] for doc in (request, verdict, thesis, output)),
        output["outputs"]["mt5"]["order_placed"] is False,
        output["outputs"]["mt5"]["environment"] == "MT5_DEMO",
    ]
    if not all(checks):
        raise ReplayFailure("identifier propagation or shadow-output invariant failed")
    return {
        "status": "PASS",
        "pipeline": [name for name, _, _ in stages] + ["fake_outputs"],
        "identifiers": ids,
        "outputs": output["outputs"],
        "canonical_thesis": canonical_json(thesis),
    }


def run_all() -> dict:
    cases = replay_event_cases()
    return {
        "ok": True,
        "mode": "SHADOW",
        "environment": "MT5_DEMO",
        "live_execution": False,
        "event_cases": cases,
        "accepted_pipeline": replay_accepted_pipeline(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="run all required paths (default)")
    parser.add_argument("--output", type=Path, help="also write canonical JSON output")
    args = parser.parse_args(argv)
    try:
        result = run_all()
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 0
    except (ContractError, ReplayFailure, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
