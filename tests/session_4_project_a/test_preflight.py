from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from project_a_ai_review.errors import FailureCode, InputRejected
from project_a_ai_review.gates import preflight, recompute_rr
from project_a_ai_review.hashing import bundle_hash, manifest_hash
from project_a_ai_review.models import RuntimePolicy

from .conftest import make_dispatch


def failure_code(dispatch, now):
    with pytest.raises(InputRejected) as error:
        preflight(dispatch, now, RuntimePolicy())
    return error.value.code


def test_valid_bundle_passes_preflight(request_doc, artifact_root, trusted_now):
    gates = preflight(make_dispatch(request_doc, artifact_root), trusted_now, RuntimePolicy())
    assert all(gates[key] for key in ("schema_valid", "symbol_valid", "timeframe_valid", "artifact_integrity_valid", "spread_valid", "rr_valid", "environment_valid"))


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda x: x.update(instrument={**x["instrument"], "symbol": "USTEC"}), FailureCode.INPUT_SCHEMA_REJECTED),
        (lambda x: x.update(base_timeframe="5m"), FailureCode.INPUT_SCHEMA_REJECTED),
        (lambda x: x.update(spread_points=11), FailureCode.INPUT_SCHEMA_REJECTED),
        (lambda x: x["risk"].update(live_execution=True), FailureCode.INPUT_SCHEMA_REJECTED),
        (lambda x: x.update(tp_candidate=2419.0), FailureCode.INPUT_SCHEMA_REJECTED),
    ],
)
def test_contract_hard_gate_failures(request_doc, artifact_root, trusted_now, mutator, expected):
    request = deepcopy(request_doc)
    mutator(request)
    assert failure_code(make_dispatch(request_doc, artifact_root, request_override=request), trusted_now) == expected


def test_stale_request_rejected(request_doc, artifact_root, trusted_now):
    now = trusted_now + timedelta(seconds=61)
    with pytest.raises(InputRejected) as error:
        preflight(
            make_dispatch(request_doc, artifact_root),
            now,
            RuntimePolicy(max_request_age_seconds=60),
        )
    assert error.value.code == FailureCode.INPUT_STALE


def test_expired_request_rejected(request_doc, artifact_root, trusted_now):
    now = trusted_now + timedelta(minutes=6)
    assert failure_code(make_dispatch(request_doc, artifact_root), now) == FailureCode.INPUT_EXPIRED


def test_future_request_rejected(request_doc, artifact_root, trusted_now):
    now = trusted_now - timedelta(seconds=10)
    assert failure_code(make_dispatch(request_doc, artifact_root), now) == FailureCode.INPUT_FUTURE_DATED


def test_missing_artifact_rejected(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    (artifact_root / "xauusd_1m.txt").unlink()
    assert failure_code(dispatch, trusted_now) == FailureCode.ARTIFACT_MISSING


def test_artifact_hash_mismatch_rejected(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root)
    (artifact_root / "xauusd_1m.txt").write_text("tampered", encoding="utf-8")
    assert failure_code(dispatch, trusted_now) in {FailureCode.ARTIFACT_SIZE_MISMATCH, FailureCode.ARTIFACT_HASH_MISMATCH}


def test_manifest_hash_mismatch_rejected(request_doc, artifact_root, trusted_now):
    dispatch = replace(make_dispatch(request_doc, artifact_root), artifact_manifest_hash="0" * 64)
    assert failure_code(dispatch, trusted_now) == FailureCode.MANIFEST_HASH_MISMATCH


def test_bundle_hash_mismatch_rejected(request_doc, artifact_root, trusted_now):
    dispatch = replace(make_dispatch(request_doc, artifact_root), bundle_hash="0" * 64)
    assert failure_code(dispatch, trusted_now) == FailureCode.BUNDLE_HASH_MISMATCH


def test_path_traversal_rejected(request_doc, artifact_root, trusted_now):
    def mutate(items):
        items[0] = replace(items[0], relative_path="../outside.txt")
        return items
    dispatch = make_dispatch(request_doc, artifact_root, artifact_mutator=mutate)
    assert failure_code(dispatch, trusted_now) == FailureCode.ARTIFACT_PATH_REJECTED


def test_missing_required_evidence_rejected(request_doc, artifact_root, trusted_now):
    dispatch = make_dispatch(request_doc, artifact_root, artifact_mutator=lambda items: items[:-1])
    assert failure_code(dispatch, trusted_now) == FailureCode.REQUIRED_EVIDENCE_MISSING


def test_decimal_rr_long_and_short():
    assert recompute_rr("LONG", 100.0, 99.0, 101.0, 0.01)["ratio"] == "1:1"
    assert recompute_rr("SHORT", 100.0, 101.0, 99.0, 0.01)["ratio"] == "1:1"


@pytest.mark.parametrize(
    "values",
    [
        ("LONG", 100.0, 99.0, 102.0, 0.01),
        ("LONG", 100.0, 101.0, 99.0, 0.01),
        ("SHORT", 100.0, 99.0, 101.0, 0.01),
        ("LONG", 100.001, 99.0, 101.002, 0.01),
        ("LONG", float("nan"), 99.0, 101.0, 0.01),
    ],
)
def test_invalid_rr_geometry_rejected(values):
    with pytest.raises(Exception):
        recompute_rr(*values)
