from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from contracts import (
    AI_VERDICT_SCHEMA_V1,
    ANALYSIS_REQUEST_SCHEMA_V1,
    EVENT_SCHEMA_V0_2,
    THESIS_SCHEMA_V1,
    ContractError,
    canonical_json,
    validate_contract,
)
from contracts.registry import SCHEMA_FILES

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "project_a"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_all_frozen_schemas_are_valid_draft_2020_12():
    for path in SCHEMA_FILES.values():
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_event_golden_cases_have_stable_expected_reasons():
    outcomes = set()
    for name, case in load("event_cases.json").items():
        expected = case["expected"]
        if expected["valid"]:
            validate_contract(EVENT_SCHEMA_V0_2, case["payload"])
            outcomes.add(case["payload"]["disposition"]["status"])
        else:
            with pytest.raises(ContractError) as error:
                validate_contract(EVENT_SCHEMA_V0_2, case["payload"])
            assert error.value.code == expected["error_code"], name
    assert {"ACCEPTED", "REJECTED", "STRUCTURAL_BREAK", "EXPIRED", "DUPLICATE"} <= outcomes


@pytest.mark.parametrize(
    ("contract", "fixture"),
    [
        (ANALYSIS_REQUEST_SCHEMA_V1, "analysis_request_accepted.json"),
        (AI_VERDICT_SCHEMA_V1, "ai_verdict_approved.json"),
    ],
)
def test_valid_pipeline_fixtures(contract, fixture):
    assert validate_contract(contract, load(fixture))


def test_fake_thesis_lifecycle_is_valid_and_versioned():
    lifecycle = load("thesis_lifecycle.json")
    for thesis in lifecycle:
        validate_contract(THESIS_SCHEMA_V1, thesis)
    assert [item["version"] for item in lifecycle[:2]] == [1, 2]
    assert {item["state"] for item in lifecycle} == {"ARMED", "INVALIDATED", "EXPIRED"}


def test_unknown_top_level_fields_fail_closed():
    request = load("analysis_request_accepted.json")
    request["future_unpinned_field"] = True
    with pytest.raises(ContractError) as error:
        validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
    assert error.value.code == "schema_additionalProperties"


def test_security_sensitive_values_fail_closed():
    event = load("event_cases.json")["accepted_alert"]["payload"]
    event["payload"]["token"] = "not-a-real-token"
    with pytest.raises(ContractError) as error:
        validate_contract(EVENT_SCHEMA_V0_2, event)
    assert error.value.code == "sensitive_value"


def test_rr_and_shadow_constraints_are_semantic_or_schema_gates():
    request = load("analysis_request_accepted.json")
    request["tp_candidate"] = request["entry_candidate"] + 3
    with pytest.raises(ContractError) as error:
        validate_contract(ANALYSIS_REQUEST_SCHEMA_V1, request)
    assert error.value.code == "rr_not_one_to_one"

    verdict = load("ai_verdict_approved.json")
    verdict["model"]["mode"] = "LIVE"
    with pytest.raises(ContractError) as error:
        validate_contract(AI_VERDICT_SCHEMA_V1, verdict)
    assert error.value.code == "schema_const"


def test_serialisation_round_trip_is_stable():
    thesis = load("thesis_lifecycle.json")[0]
    first = canonical_json(thesis)
    second = canonical_json(json.loads(first))
    assert first == second
    assert "NaN" not in first


def test_identifiers_and_causation_survive_full_fixture_chain():
    event = load("event_cases.json")["accepted_alert"]["payload"]
    request = load("analysis_request_accepted.json")
    verdict = load("ai_verdict_approved.json")
    thesis = load("thesis_lifecycle.json")[0]
    output = load("downstream_output.json")
    assert {item["setup_id"] for item in (event, request, verdict, thesis, output)} == {event["setup_id"]}
    assert {item["correlation_id"] for item in (event, request, verdict, thesis, output)} == {event["correlation_id"]}
    assert request["causation_id"] == event["event_id"]
    assert verdict["causation_id"] == request["request_id"]
    assert thesis["causation_id"] == verdict["verdict_id"]


def test_fixture_mutation_does_not_affect_source():
    source = load("analysis_request_accepted.json")
    mutated = deepcopy(source)
    mutated["source_event_ids"].append("evt_another_valid_identifier")
    assert source != mutated
