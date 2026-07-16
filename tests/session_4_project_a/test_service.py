from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta

import pytest

from project_a_ai_review.audit import ShadowAuditStore
from project_a_ai_review.clients import OpenClawCliClient
from project_a_ai_review.errors import FailureCode, TechnicalFailure
from project_a_ai_review.models import RuntimePolicy
from project_a_ai_review.service import ReviewService

from .conftest import MutableClock, candidate_raw, make_dispatch, make_service


def test_valid_bundle_reaches_mocked_reviewer(request_doc, artifact_root, trusted_now, tmp_path):
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now)
    result = service.review(make_dispatch(request_doc, artifact_root))
    assert result.status == "VERDICT"
    assert result.verdict["verdict"] == "APPROVE"
    assert client.calls == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(instrument={**x["instrument"], "symbol": "USTEC"}),
        lambda x: x.update(base_timeframe="5m"),
        lambda x: x.update(spread_points=11),
        lambda x: x.update(tp_candidate=2419.0),
    ],
)
def test_invalid_bundle_never_reaches_model(request_doc, artifact_root, trusted_now, tmp_path, mutate):
    request = deepcopy(request_doc)
    mutate(request)
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now)
    result = service.review(make_dispatch(request_doc, artifact_root, request_override=request))
    assert result.status == "INPUT_REJECTION"
    assert client.calls == 0


def test_missing_artifact_never_reaches_model(request_doc, artifact_root, trusted_now, tmp_path):
    dispatch = make_dispatch(request_doc, artifact_root)
    (artifact_root / "xauusd_1m.txt").unlink()
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now)
    assert service.review(dispatch).status == "INPUT_REJECTION"
    assert client.calls == 0


def test_expired_approve_after_model_is_technical_failure(request_doc, artifact_root, trusted_now, tmp_path):
    clock = MutableClock(trusted_now)
    service, client = make_service(
        tmp_path,
        candidate_raw(),
        clock,
        delay_hook=lambda: setattr(clock, "value", trusted_now + timedelta(minutes=5)),
    )
    result = service.review(make_dispatch(request_doc, artifact_root))
    assert result.status == "TECHNICAL_FAILURE"
    assert result.failure["code"] == FailureCode.EXPIRY_FAILURE.value
    assert result.verdict is None


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TechnicalFailure(FailureCode.MODEL_TIMEOUT, "timeout", True), FailureCode.MODEL_TIMEOUT),
        (TechnicalFailure(FailureCode.AUTHENTICATION_UNAVAILABLE, "oauth expired"), FailureCode.AUTHENTICATION_UNAVAILABLE),
        (TechnicalFailure(FailureCode.RATE_LIMITED, "rate limit", True), FailureCode.RATE_LIMITED),
        (TechnicalFailure(FailureCode.MODEL_UNAVAILABLE, "unavailable", True), FailureCode.MODEL_UNAVAILABLE),
        (TechnicalFailure(FailureCode.OPENCLAW_UNAVAILABLE, "missing", True), FailureCode.OPENCLAW_UNAVAILABLE),
    ],
)
def test_provider_failures_are_not_trade_verdicts(request_doc, artifact_root, trusted_now, tmp_path, failure, code):
    service, client = make_service(tmp_path, None, lambda: trusted_now, failure=failure)
    result = service.review(make_dispatch(request_doc, artifact_root))
    assert result.status == "TECHNICAL_FAILURE"
    assert result.failure["code"] == code.value
    assert result.verdict is None


def test_malformed_model_output_is_technical_failure(request_doc, artifact_root, trusted_now, tmp_path):
    service, _ = make_service(tmp_path, "prose {\"verdict\":\"APPROVE\"}", lambda: trusted_now)
    result = service.review(make_dispatch(request_doc, artifact_root))
    assert result.failure["code"] == FailureCode.MALFORMED_MODEL_OUTPUT.value
    assert result.verdict is None


def test_duplicate_request_is_idempotent(request_doc, artifact_root, trusted_now, tmp_path):
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now)
    dispatch = make_dispatch(request_doc, artifact_root)
    first = service.review(dispatch)
    second = service.review(dispatch)
    assert first.status == second.status == "VERDICT"
    assert second.cached is True
    assert first.verdict == second.verdict
    assert client.calls == 1


def test_conflicting_duplicate_fails_closed(request_doc, artifact_root, trusted_now, tmp_path):
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now)
    first = make_dispatch(request_doc, artifact_root)
    assert service.review(first).status == "VERDICT"
    changed = deepcopy(request_doc)
    changed["hpa"].append("M30_DISCOUNT")
    conflict = make_dispatch(request_doc, artifact_root, request_override=changed)
    result = service.review(conflict)
    assert result.status == "INPUT_REJECTION"
    assert result.failure["code"] == FailureCode.DUPLICATE_CONFLICT.value
    assert client.calls == 1


def test_concurrent_duplicate_creates_one_model_call(request_doc, artifact_root, trusted_now, tmp_path):
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now, delay_hook=lambda: time.sleep(0.2))
    dispatch = make_dispatch(request_doc, artifact_root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.review(dispatch), range(2)))
    assert [item.status for item in results] == ["VERDICT", "VERDICT"]
    assert client.calls == 1
    assert sum(item.cached for item in results) == 1


def test_retry_rechecks_expiry_before_model(request_doc, artifact_root, trusted_now, tmp_path):
    clock = MutableClock(trusted_now)
    timeout = TechnicalFailure(FailureCode.MODEL_TIMEOUT, "timeout", True)
    service, client = make_service(tmp_path, candidate_raw(), clock, failure=timeout)
    dispatch = make_dispatch(request_doc, artifact_root)
    first = service.review(dispatch)
    assert first.failure["code"] == FailureCode.MODEL_TIMEOUT.value
    client.failure = None
    clock.value = trusted_now + timedelta(minutes=4, seconds=59)
    second = service.review(dispatch, retry_of=first.attempt_id)
    assert second.status == "INPUT_REJECTION"
    assert second.failure["code"] == FailureCode.INPUT_EXPIRED.value
    assert client.calls == 1


def test_retry_limit_is_bounded(request_doc, artifact_root, trusted_now, tmp_path):
    failure = TechnicalFailure(FailureCode.MODEL_TIMEOUT, "timeout", True)
    service, client = make_service(tmp_path, None, lambda: trusted_now, failure=failure)
    dispatch = make_dispatch(request_doc, artifact_root)
    one = service.review(dispatch)
    two = service.review(dispatch, retry_of=one.attempt_id)
    three = service.review(dispatch, retry_of=two.attempt_id)
    assert client.calls == 2
    assert three.failure["code"] == FailureCode.SESSION_FAILURE.value
    assert three.failure["retryable"] is False


def test_cross_request_sessions_do_not_match(request_doc, artifact_root, trusted_now, tmp_path):
    service, client = make_service(tmp_path, candidate_raw(), lambda: trusted_now)
    assert service.review(make_dispatch(request_doc, artifact_root)).status == "VERDICT"
    request2 = deepcopy(request_doc)
    request2.update(
        request_id="req_xau_20260716_0002",
        setup_id="setup_xau_20260716_0002",
        correlation_id="corr_xau_20260716_0002",
    )
    client.raw_response = candidate_raw(
        mutate=lambda x: x.update(
            request_id=request2["request_id"],
            setup_id=request2["setup_id"],
            correlation_id=request2["correlation_id"],
            causation_id=request2["request_id"],
        )
    )
    assert service.review(make_dispatch(request2, artifact_root)).status == "VERDICT"
    assert len(set(client.sessions)) == 2


class BrokenAuditStore(ShadowAuditStore):
    def append_attempt(self, request_id, record):
        raise OSError("disk failure")


def test_audit_persistence_failure_withholds_verdict(request_doc, artifact_root, trusted_now, tmp_path):
    store = BrokenAuditStore(tmp_path / "audit")
    service, _ = make_service(tmp_path, candidate_raw(), lambda: trusted_now, store=store)
    result = service.review(make_dispatch(request_doc, artifact_root))
    assert result.status == "TECHNICAL_FAILURE"
    assert result.failure["code"] == FailureCode.AUDIT_PERSISTENCE_FAILURE.value
    assert result.verdict is None


def test_audit_chain_detects_tampering(request_doc, artifact_root, trusted_now, tmp_path):
    store = ShadowAuditStore(tmp_path / "audit")
    service, _ = make_service(tmp_path, candidate_raw(), lambda: trusted_now, store=store)
    dispatch = make_dispatch(request_doc, artifact_root)
    assert service.review(dispatch).status == "VERDICT"
    assert store.verify_chain(request_doc["request_id"])
    path = store.request_dir(request_doc["request_id"]) / "attempts.jsonl"
    text = path.read_text(encoding="utf-8").replace("VERDICT", "REJECTED", 1)
    path.write_text(text, encoding="utf-8")
    assert not store.verify_chain(request_doc["request_id"])


def test_openclaw_absence_is_classified(tmp_path):
    client = OpenClawCliClient(
        executable=str(tmp_path / "missing-openclaw"),
        model="openai/example",
        staging_root=tmp_path / "stage",
    )
    with pytest.raises(TechnicalFailure) as error:
        client.version()
    assert error.value.code == FailureCode.OPENCLAW_UNAVAILABLE


def test_review_service_imports_no_session5_or_mt5_module():
    import project_a_ai_review.service as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "output.mt5" not in source
    assert "session_5" not in source
