from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from contracts import AI_VERDICT_SCHEMA_V1, ContractError, canonical_json, validate_contract
from project_a_ai_review.errors import FailureCode, TechnicalFailure
from project_a_ai_review.gates import post_validate
from project_a_ai_review.models import ModelIdentity
from project_a_ai_review.parser import parse_model_json

from .conftest import candidate_raw, load_candidate, make_dispatch


def trusted_fields(request, generated="2026-07-16T00:00:03.000Z"):
    return {
        "verdict_id": "verdict_trusted_candidate_0001",
        "request_id": request["request_id"],
        "setup_id": request["setup_id"],
        "correlation_id": request["correlation_id"],
        "causation_id": request["request_id"],
        "generated_at": generated,
    }


def post(candidate, request, manifest, now):
    return post_validate(
        candidate,
        request=request,
        manifest=manifest,
        trusted_fields=trusted_fields(request),
        now=now,
        model=ModelIdentity("fixture", "recorded-reviewer", "none"),
    )


@pytest.mark.parametrize("name", ["approve", "reject", "modify", "expired"])
def test_all_four_candidates_pass_frozen_schema(name):
    assert validate_contract(AI_VERDICT_SCHEMA_V1, load_candidate(name))


@pytest.mark.parametrize("name", ["approve", "reject", "modify", "expired"])
def test_all_four_candidates_pass_post_gates(name, request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    now = trusted_now + timedelta(minutes=5) if name == "expired" else trusted_now
    verdict, gates = post(load_candidate(name), request_doc, dispatch.manifest_document(), now)
    assert verdict["verdict"] == name.upper()
    assert gates["schema_valid"] is True


@pytest.mark.parametrize(
    "raw",
    [
        "prose {\"a\":1}",
        "```json\n{\"a\":1}\n```",
        "{\"a\":1} trailing",
        "{\"a\":1,\"a\":2}",
        "[1,2,3]",
        "{\"x\":NaN}",
        "",
    ],
)
def test_strict_parser_rejects_prose_fences_duplicates_and_non_object(raw):
    with pytest.raises(TechnicalFailure) as error:
        parse_model_json(raw)
    assert error.value.code == FailureCode.MALFORMED_MODEL_OUTPUT


def test_strict_parser_accepts_whitespace_only_around_object():
    assert parse_model_json(" \n {\"a\":1}\t ") == {"a": 1}


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda x: x.update(verdict="HOLD"), FailureCode.OUTPUT_SCHEMA_FAILURE),
        (lambda x: x.pop("rationale"), FailureCode.OUTPUT_SCHEMA_FAILURE),
        (lambda x: x.update(extra_field=True), FailureCode.OUTPUT_SCHEMA_FAILURE),
        (lambda x: x.update(entry="2416.5"), FailureCode.OUTPUT_SCHEMA_FAILURE),
        (lambda x: x.update(request_id="req_wrong_00000001"), FailureCode.IDENTIFIER_MISMATCH),
        (lambda x: x.update(setup_id="setup_wrong_00000001"), FailureCode.IDENTIFIER_MISMATCH),
        (lambda x: x.update(reason_codes=["EVIDENCE_UNKNOWN"]), FailureCode.EVIDENCE_REFERENCE_MISMATCH),
        (lambda x: x.update(live_execution=True), FailureCode.OUTPUT_SCHEMA_FAILURE),
    ],
)
def test_schema_and_identity_attacks_fail_closed(request_doc, artifact_root, trusted_now, mutate, code):
    dispatch = make_dispatch(request_doc, artifact_root)
    candidate = load_candidate("approve")
    mutate(candidate)
    with pytest.raises(TechnicalFailure) as error:
        post(candidate, request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code == code


def test_wrong_model_or_prompt_attribution_rejected(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    candidate = load_candidate("approve")
    candidate["model"]["prompt_version"] = "unreviewed-prompt"
    with pytest.raises(TechnicalFailure) as error:
        post(candidate, request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code == FailureCode.IDENTIFIER_MISMATCH


def test_invalid_approve_rr_not_repaired(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    candidate = load_candidate("approve")
    candidate["tp"] = 2419.5
    with pytest.raises(TechnicalFailure) as error:
        post(candidate, request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code in {FailureCode.OUTPUT_SCHEMA_FAILURE, FailureCode.RR_FAILURE}


def test_valid_rr_but_changed_approve_rejected_as_modify_scope(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    candidate = load_candidate("approve")
    candidate.update(entry=2416.4, sl=2414.4, tp=2418.4)
    with pytest.raises(TechnicalFailure) as error:
        post(candidate, request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code == FailureCode.MODIFY_SCOPE_FAILURE


def test_invalid_modify_rr_rejected(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    candidate = load_candidate("modify")
    candidate["tp"] = 2418.5
    with pytest.raises(TechnicalFailure) as error:
        post(candidate, request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code in {FailureCode.OUTPUT_SCHEMA_FAILURE, FailureCode.RR_FAILURE}


def test_modify_cannot_extend_validity(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    candidate = load_candidate("modify")
    candidate["valid_until"] = "2026-07-16T00:06:02Z"
    with pytest.raises(TechnicalFailure) as error:
        post(candidate, request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code == FailureCode.EXPIRY_FAILURE


def test_post_review_expiry_blocks_approve(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    with pytest.raises(TechnicalFailure) as error:
        post(
            load_candidate("approve"),
            request_doc,
            dispatch.manifest_document(),
            trusted_now + timedelta(minutes=6),
        )
    assert error.value.code == FailureCode.EXPIRY_FAILURE


def test_model_cannot_declare_expiry_before_trusted_deadline(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    with pytest.raises(TechnicalFailure) as error:
        post(load_candidate("expired"), request_doc, dispatch.manifest_document(), trusted_now)
    assert error.value.code == FailureCode.EXPIRY_FAILURE


def test_trusted_fields_replace_model_verdict_id_and_timestamp(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    verdict, _ = post(load_candidate("approve"), request_doc, dispatch.manifest_document(), trusted_now)
    assert verdict["verdict_id"] == "verdict_trusted_candidate_0001"
    assert verdict["generated_at"] == "2026-07-16T00:00:03.000Z"
