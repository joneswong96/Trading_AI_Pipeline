from __future__ import annotations

import copy
import hashlib
import json
import pickle
import subprocess
import sys
import threading
import unicodedata
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

import contracts
import contracts.event_v1 as event_v1
from contracts import (
    EVENT_SCHEMA_V0_2,
    PROJECT_A_CANONICAL_EVENT_V1,
    PROJECT_A_WIRE_EVENT_V1,
    CanonicalEventV1Document,
    CanonicalVerificationResultV1,
    ContractError,
    DedupeAuthority,
    InMemoryDedupeAuthority,
    ParsedWireEventV1,
    ReceiptProcessingResultV1,
    canonical_json,
    canonical_json_bytes,
    canonicalize_wire_event_v1,
    consume_point_of_use_authorization,
    parse_wire_event_v1_bytes,
    process_wire_event_v1_receipt,
    process_wire_event_v1_receipt_in_transaction,
    read_project_a_event,
    semantic_evidence_projection,
    validate_canonical_event_v1_shape,
    validate_contract,
    validate_legacy_event_v0_2,
    validate_wire_event_v1_shape,
    verify_and_authorize_canonical_event_v1,
)
from contracts._trusted_ingress import _TrustedReceiptContextV1, issue_replay_receipt_context
from project_a import replay

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "project_a"
KNOWN_PATH = FIXTURES / "event_v1_known_vectors.json"
MIGRATION_PATH = FIXTURES / "event_v1_migration_cases.json"
FROZEN_EVENT_HASH = "cc751d83d5648c167c663ec2a449ddb1650ae5f7507912303bd66253a7e8d6a4"
FROZEN_SCHEMA_HASH = "2b9f9ec23fbfaecd7bf161a5f29a2aa4f0ab2b4c128223d8fe3122402f1579ca"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def known() -> dict:
    return load(KNOWN_PATH)


def document(name: str) -> dict:
    return copy.deepcopy(known()["documents"][name])


def issue_context(raw: bytes, suffix: str, *, transport_identity: str | None = None):
    return issue_replay_receipt_context(
        raw,
        receipt_id=f"rcpt_fixture_{suffix}",
        received_at="2026-07-16T02:00:00Z",
        transport_identity=transport_identity or f"provider_delivery_{suffix}",
        source_adapter_identity="offline_fixture_adapter_v1",
        immutable_raw_reference=f"receipt_store_{suffix}",
        canonicalized_at="2026-07-16T02:00:00.100Z",
        replay_clock="2026-07-16T03:00:00Z",
    )


def process_document(
    wire: dict,
    suffix: str = "20260716_0001",
    *,
    authority: InMemoryDedupeAuthority | None = None,
    raw: bytes | None = None,
    transport_identity: str | None = None,
):
    raw = canonical_json_bytes(wire) if raw is None else raw
    context = issue_context(raw, suffix, transport_identity=transport_identity)
    authority = authority or InMemoryDedupeAuthority()
    result = process_wire_event_v1_receipt(raw, context, authority)
    return result, context, authority, raw


def open_processed(
    wire: dict,
    suffix: str,
    *,
    authority: InMemoryDedupeAuthority | None = None,
    transport_identity: str | None = None,
):
    raw = canonical_json_bytes(wire)
    context = issue_context(raw, suffix, transport_identity=transport_identity)
    authority = authority or InMemoryDedupeAuthority()
    transaction = authority.begin_receipt_transaction(context)
    result = process_wire_event_v1_receipt_in_transaction(raw, context, transaction)
    assert result.canonical_document is not None
    assert transaction.committed and not transaction.closed
    return result, context, authority, raw, transaction


def sha256_canonical(value) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class FakeConsumer:
    def __init__(self, action: str) -> None:
        self.action = action

    def act(self, canonical, raw, context, transaction):
        verification = verify_and_authorize_canonical_event_v1(
            canonical, raw, context, transaction, self.action
        )
        consume_point_of_use_authorization(verification, transaction, self.action)
        return verification

    def accept_result(self, verification, transaction):
        consume_point_of_use_authorization(verification, transaction, self.action)


@pytest.mark.parametrize("name", list(known()["documents"]))
def test_all_recorded_wire_vectors_are_shape_valid(name):
    wire = document(name)
    assert validate_wire_event_v1_shape(wire) is wire


def _apply_negative(vector: dict) -> dict:
    candidate = document(vector["base"])
    for key, value in vector.get("set", {}).items():
        candidate[key] = value
    if "remove" in vector:
        candidate.pop(vector["remove"])
    if vector.get("special") == "nan_trigger_price":
        candidate["evidence"]["trigger"]["price"] = float("nan")
    elif vector.get("special") == "infinity_trigger_price":
        candidate["evidence"]["trigger"]["price"] = float("inf")
    elif vector.get("special") == "oversized_extension":
        candidate["extensions"]["oversized"] = "x" * 4097
    return candidate


@pytest.mark.parametrize("vector", known()["negative_vectors"], ids=lambda item: item["name"])
def test_recorded_negative_vectors_fail_closed(vector):
    candidate = _apply_negative(vector)
    with pytest.raises(ContractError) as error:
        if vector["name"] in {"unknown_version", "ambiguous_v1"}:
            read_project_a_event(candidate)
        else:
            validate_wire_event_v1_shape(candidate)
    assert error.value.code == vector["error_code"]


def test_known_vectors_use_decimal_canonical_utf8_and_independent_hashlib():
    vectors = known()
    for name, expected in vectors["hash_vectors"].items():
        wire = vectors["documents"][name]
        assert sha256_canonical(wire) == expected["canonical_content_hash"]
        assert sha256_canonical(semantic_evidence_projection(wire)) == expected["semantic_evidence_hash"]
    assert canonical_json({"a": 1, "b": 1.0, "c": Decimal("1e0"), "d": -0.0}) == '{"a":1,"b":1,"c":1,"d":0}'


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"\xef\xbb\xbf{}", "wire_bom_forbidden"),
        (b'{"a":1,"a":2}', "duplicate_json_key"),
        (b"\xff", "wire_not_utf8"),
        (b"[]", "wire_json_object_required"),
        (b'{"x":NaN}', "non_finite_number"),
        (b'{"x":Infinity}', "non_finite_number"),
    ],
)
def test_raw_byte_parser_fails_before_shape_repair(raw, code):
    with pytest.raises(ContractError) as error:
        parse_wire_event_v1_bytes(raw)
    assert error.value.code == code


def test_raw_parser_hashes_exact_noncanonical_bytes_before_decode():
    wire = document("minimal_valid")
    raw = json.dumps(wire, indent=2, ensure_ascii=False).encode()
    parsed = parse_wire_event_v1_bytes(raw)
    assert isinstance(parsed, ParsedWireEventV1)
    assert parsed.observed_raw_content_hash == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert parsed.document == wire


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-16 01:00:00Z",
        "2026-07-16T01:00:00+00:00",
        "2026-07-16T01:00:00.0000Z",
        "2026-07-16T01:00Z",
        "2026-13-16T01:00:00Z",
        "not-a-time",
    ],
)
def test_strict_wire_timestamps_reject_noncanonical_forms(value):
    wire = document("minimal_valid")
    wire["occurred_at"] = value
    with pytest.raises(ContractError) as error:
        validate_wire_event_v1_shape(wire)
    assert error.value.code in {"schema_pattern", "timestamp_not_rfc3339_utc", "timestamp_invalid"}


@pytest.mark.parametrize("value", ["2026-07-16T01:00:00Z", "2026-07-16T01:00:00.1Z", "2026-07-16T01:00:00.12Z", "2026-07-16T01:00:00.123Z"])
def test_strict_wire_timestamps_accept_zero_to_three_fractional_digits(value):
    wire = document("minimal_valid")
    wire["occurred_at"] = value
    assert validate_wire_event_v1_shape(wire) is wire


def test_emitted_timestamp_cannot_precede_occurred():
    wire = document("rejection_ready")
    wire["emitted_at"] = "2026-07-16T01:00:59Z"
    with pytest.raises(ContractError) as error:
        validate_wire_event_v1_shape(wire)
    assert error.value.code == "emitted_before_occurred"


@pytest.mark.parametrize("key", ["broker", "account_id", "orderRoute", "canonical_hash", "state_mutation", "receipt_token", "dispatch_hint", "live_endpoint"])
def test_closed_extensions_reject_control_plane_concepts(key):
    wire = document("minimal_valid")
    wire["extensions"][key] = "caller-controlled"
    with pytest.raises(ContractError) as error:
        validate_wire_event_v1_shape(wire)
    assert error.value.code == "reserved_extension_key"


def test_canonical_policy_is_not_rfc8785_and_does_not_normalize_unicode():
    composed = "é"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert canonical_json({"x": composed}) != canonical_json({"x": decomposed})


def test_general_reader_and_contract_exports_cannot_issue_receipt_context():
    assert "issue_replay_receipt_context" not in contracts.__all__
    assert not hasattr(contracts, "issue_replay_receipt_context")
    assert not hasattr(event_v1, "issue_replay_receipt_context")
    with pytest.raises(ContractError) as error:
        read_project_a_event(document("minimal_valid"), receipt_id="rcpt_forged_0001")
    assert error.value.code == "generic_reader_cannot_authorize"


def test_caller_dictionary_and_canonical_json_cannot_issue_context():
    caller = {name: "forged" for name in ("receipt_id", "raw_content_hash", "authority")}
    assert isinstance(canonical_json(caller), str)
    assert not isinstance(caller, _TrustedReceiptContextV1)


@pytest.mark.parametrize("replay_clock", [None, "", "2026-07-16T03:00:00+00:00"])
def test_replay_only_issuer_requires_explicit_guarded_clock(replay_clock):
    raw = canonical_json_bytes(document("minimal_valid"))
    with pytest.raises((ContractError, TypeError)):
        issue_replay_receipt_context(
            raw,
            receipt_id="rcpt_fixture_guard_0001",
            received_at="2026-07-16T02:00:00Z",
            transport_identity="provider_delivery_guard",
            source_adapter_identity="offline_fixture_adapter_v1",
            immutable_raw_reference="receipt_store_guard",
            canonicalized_at="2026-07-16T02:00:00.100Z",
            replay_clock=replay_clock,
        )


def test_production_issuer_and_trusted_wrapper_are_absent():
    assert not hasattr(contracts, "TrustedCanonicalEventV1")
    assert not hasattr(event_v1, "TrustedCanonicalEventV1")
    assert not hasattr(event_v1, "construct_trusted_canonical_event_v1")
    assert not hasattr(event_v1, "issue_production_receipt_context")
    assert event_v1.__dict__.get("_TRUST_MARKER") is None


def _invalid_lifecycle(case: str) -> dict:
    wire = document("setup_invalidation")
    if case == "setup_origin_null": wire["setup_origin"] = None
    elif case == "setup_origin_missing": wire.pop("setup_origin")
    elif case == "aoi_missing": wire["setup_origin"].pop("aoi_id")
    elif case == "origin_missing": wire["setup_origin"].pop("origin_id")
    elif case == "hypothesis_missing": wire.pop("hypothesis")
    elif case == "hypothesis_null": wire["hypothesis"] = None
    elif case == "snr_missing": wire["evidence"]["snr"] = None
    elif case == "snr_identity_missing": wire["evidence"]["snr"].pop("identity")
    elif case == "contradictory_origin": wire["setup_origin"]["receipt_id"] = "machine-derived"
    else: wire["setup_id"] = {
        "random_setup": "setup_0123456789abcdef0123456789abcdef",
        "foreign_setup": "setup_ffffffffffffffffffffffffffffffff",
        "receipt_setup": "setup_receipt_derived",
        "retry_setup": "setup_retry_derived",
        "machine_setup": "setup_machine_local",
    }[case]
    return wire


@pytest.mark.parametrize(
    "case",
    [
        "setup_origin_null", "setup_origin_missing", "aoi_missing", "origin_missing",
        "hypothesis_missing", "hypothesis_null", "snr_missing", "snr_identity_missing",
        "random_setup", "foreign_setup", "receipt_setup", "retry_setup", "machine_setup",
        "contradictory_origin",
    ],
)
def test_invalid_lifecycle_receipts_are_auditable_without_canonical_event(case):
    result, context, authority, _ = process_document(_invalid_lifecycle(case), f"life_{case}")
    expected = event_v1.INVALID_CANONICAL_SETUP_IDENTITY if case in {
        "random_setup", "foreign_setup", "receipt_setup", "retry_setup", "machine_setup", "contradictory_origin"
    } else event_v1.MISSING_CANONICAL_SETUP_IDENTITY
    assert result == ReceiptProcessingResultV1(
        processing_status="REJECTED",
        reason_code=expected,
        raw_content_hash=context.raw_content_hash,
        receipt_id=context.receipt_id,
        immutable_raw_reference=context.immutable_raw_reference,
        received_at=context.received_at,
        wire_family="PROJECT_A_WIRE_EVENT",
        wire_version="1.0",
        canonical_document=None,
        setup_id=None,
        transaction_id=result.transaction_id,
    )
    # Raw retention belongs to trusted ingress; canonical dedupe is never
    # entered for an invalid lifecycle receipt in this reader foundation.
    assert context.receipt_id not in authority._receipts


def test_valid_lifecycle_derives_setup_id_but_requires_current_mutation_authorization():
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), "valid_lifecycle")
    canonical = result.canonical_document.document
    assert canonical["setup_id"].startswith("setup_") and len(canonical["setup_id"]) == 38
    assert canonical["validation"]["state_mutation_allowed"] is True
    assert result.state_mutation_allowed is False and result.authority == "NONE"
    verification = FakeConsumer("STATE_MUTATION").act(canonical, raw, context, transaction)
    assert verification.authorized and verification.authority == "CURRENT_TRANSACTION"
    transaction.close()


@pytest.mark.parametrize(
    ("stage", "reason"),
    [
        ("begin", event_v1.DEDUPE_TRANSACTION_FAILED),
        ("record_receipt", event_v1.DEDUPE_TRANSACTION_FAILED),
        ("reserve_exact", event_v1.DEDUPE_TRANSACTION_FAILED),
        ("reserve_semantic", event_v1.DEDUPE_TRANSACTION_FAILED),
        ("persist_decision", event_v1.DEDUPE_TRANSACTION_FAILED),
        ("commit", event_v1.DEDUPE_TRANSACTION_FAILED),
        ("commit_unknown", event_v1.DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN),
    ],
)
def test_dedupe_stage_failures_are_stable_fail_closed(stage, reason):
    authority = InMemoryDedupeAuthority(fail_at=stage)
    result, _, _, _ = process_document(document("rejection_ready"), f"fail_{stage}", authority=authority)
    assert result.processing_status == "ERROR"
    assert result.reason_code == reason
    assert result.canonical_document is None
    assert result.state_mutation_allowed is False and result.dispatch_allowed is False
    assert result.authority == "NONE"
    if stage not in {"commit_unknown"}:
        assert authority._receipts == {} and authority._exact == {} and authority._semantic == {}


def test_unknown_commit_outcome_never_promotes_partial_state():
    authority = InMemoryDedupeAuthority(fail_at="commit_unknown")
    result, context, _, _ = process_document(document("rejection_ready"), "unknown_commit", authority=authority)
    assert result.reason_code == event_v1.DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN
    assert result.canonical_document is None
    assert context.receipt_id in authority._receipts


def test_missing_and_unavailable_dedupe_authorities_are_stable():
    wire, raw = document("rejection_ready"), canonical_json_bytes(document("rejection_ready"))
    context = issue_context(raw, "missing_dedupe")
    missing = process_wire_event_v1_receipt(raw, context, None)
    unavailable = process_wire_event_v1_receipt(raw, context, InMemoryDedupeAuthority(available=False))
    assert missing.reason_code == event_v1.DEDUPE_AUTHORITY_REQUIRED
    assert unavailable.reason_code == event_v1.DEDUPE_AUTHORITY_UNAVAILABLE


class _BadAuthority(DedupeAuthority):
    def __init__(self, failure=None): self.failure = failure
    @property
    def durable(self): return True
    def begin_receipt_transaction(self, context):
        if self.failure: raise self.failure
        return None


class _CountingDedupeAuthority(InMemoryDedupeAuthority):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.begin_calls = 0
        self.exact_calls = 0
        self.semantic_calls = 0

    def begin_receipt_transaction(self, context):
        self.begin_calls += 1
        transaction = super().begin_receipt_transaction(context)
        original_exact = transaction.reserve_exact
        original_semantic = transaction.reserve_semantic

        def reserve_exact(*args):
            self.exact_calls += 1
            return original_exact(*args)

        def reserve_semantic(*args):
            self.semantic_calls += 1
            return original_semantic(*args)

        transaction.reserve_exact = reserve_exact
        transaction.reserve_semantic = reserve_semantic
        return transaction


@pytest.mark.parametrize(
    "authority",
    [
        _CountingDedupeAuthority(),
        _CountingDedupeAuthority(available=False),
        _CountingDedupeAuthority(fail_at="begin"),
    ],
    ids=["available", "unavailable", "begin_failure"],
)
def test_malformed_parse_result_is_independent_of_dedupe(authority):
    raw = b"{malformed json"
    context = issue_context(raw, f"malformed_{id(authority)}")
    result = process_wire_event_v1_receipt(raw, context, authority)
    assert result.processing_status == "REJECTED"
    assert result.reason_code == "WIRE_JSON_INVALID"
    assert result.canonical_document is None
    assert result.authority == "NONE"
    assert result.state_mutation_allowed is False
    assert result.dispatch_allowed is False
    assert result.raw_content_hash == context.raw_content_hash
    assert result.immutable_raw_reference == context.immutable_raw_reference
    assert authority.begin_calls == 0
    assert authority.exact_calls == 0
    assert authority.semantic_calls == 0


@pytest.mark.parametrize(
    ("authority", "reason"),
    [
        (_BadAuthority(), event_v1.DEDUPE_AUTHORITY_INVALID_RESULT),
        (_BadAuthority(RuntimeError("database driver secret")), event_v1.DEDUPE_TRANSACTION_FAILED),
        (_BadAuthority(AttributeError("adapter-specific")), event_v1.DEDUPE_AUTHORITY_INVALID_RESULT),
        (_BadAuthority(TypeError("adapter-specific")), event_v1.DEDUPE_AUTHORITY_INVALID_RESULT),
    ],
)
def test_adapter_exceptions_and_invalid_begin_results_do_not_escape(authority, reason):
    result, _, _, _ = process_document(document("rejection_ready"), f"bad_{reason}_{id(authority)}", authority=authority)
    assert result.reason_code == reason
    assert "secret" not in (result.audit_detail or "")


def test_invalid_reservation_result_is_normalized(monkeypatch):
    original = event_v1._InMemoryReceiptTransaction.reserve_exact
    def invalid(self, transport_identity, canonical_content_hash):
        original(self, transport_identity, canonical_content_hash)
        return None
    monkeypatch.setattr(event_v1._InMemoryReceiptTransaction, "reserve_exact", invalid)
    result, _, _, _ = process_document(document("rejection_ready"), "bad_reserve")
    assert result.reason_code == event_v1.DEDUPE_AUTHORITY_INVALID_RESULT


def test_transaction_rollback_and_closed_reuse_are_explicit():
    raw = canonical_json_bytes(document("rejection_ready"))
    context = issue_context(raw, "rollback")
    transaction = InMemoryDedupeAuthority().begin_receipt_transaction(context)
    transaction.record_receipt(context.raw_content_hash)
    transaction.rollback()
    with pytest.raises(ContractError) as rolled:
        transaction.record_receipt(context.raw_content_hash)
    assert rolled.value.code == "dedupe_transaction_rolled_back"
    transaction.close()
    with pytest.raises(ContractError) as closed:
        transaction.close()
    assert closed.value.code == "dedupe_transaction_closed"


def test_successful_transaction_commits_receipt_exact_semantic_and_decision_atomically():
    result, context, authority, _, transaction = open_processed(document("rejection_ready"), "atomic_success")
    assert context.receipt_id in authority._receipts
    assert len(authority._exact) == len(authority._semantic) == 1
    assert authority._receipts[context.receipt_id]["decision"] == transaction.decision
    assert authority._receipts[context.receipt_id]["dispatch_allowed"] is True
    assert authority._receipts[context.receipt_id]["state_mutation_allowed"] is False
    with pytest.raises(ContractError) as second:
        transaction.commit()
    assert second.value.code == "dedupe_commit_once"
    transaction.close()
    assert result.processing_status == "ACCEPTED"


def test_exact_and_semantic_dedupe_remain_distinct_and_fail_closed():
    authority = InMemoryDedupeAuthority()
    first, _, _, _ = process_document(document("rejection_ready"), "dedupe_1", authority=authority, transport_identity="same_delivery")
    exact, _, _, _ = process_document(document("rejection_ready"), "dedupe_2", authority=authority, transport_identity="same_delivery")
    semantic, _, _, _ = process_document(document("rejection_metadata_changed"), "dedupe_3", authority=authority)
    assert first.processing_status == "ACCEPTED"
    assert exact.processing_status == "DUPLICATE"
    assert exact.canonical_document.document["dedupe"]["exact_receipt_duplicate"] is True
    assert semantic.processing_status == "DUPLICATE"
    assert semantic.canonical_document.document["dedupe"]["semantic_evidence_duplicate"] is True
    assert exact.dispatch_allowed is semantic.dispatch_allowed is False


def test_concurrent_receipts_share_one_atomic_dedupe_boundary():
    authority = InMemoryDedupeAuthority()
    barrier = threading.Barrier(2)
    statuses = []
    failures = []

    def worker(suffix):
        try:
            barrier.wait()
            result, _, _, _ = process_document(
                document("rejection_ready"), suffix,
                authority=authority, transport_identity="concurrent_delivery",
            )
            statuses.append(result.processing_status)
        except Exception as exc:  # pragma: no cover - diagnostic capture
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(f"concurrent_{n}",)) for n in (1, 2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(statuses) == ["ACCEPTED", "DUPLICATE"]


_POINT_OF_USE_ACTIONS = [
    "STATE_MUTATION", "DISPATCH", "OUTBOX_CREATE", "AUDIT_ACCEPTANCE",
    "DOWNSTREAM_HANDOFF", "REPLAY_RELEASE",
]


@pytest.mark.parametrize("action", _POINT_OF_USE_ACTIONS)
def test_every_action_is_consumable_once_per_generation(action):
    name = "setup_invalidation" if action == "STATE_MUTATION" else "rejection_ready"
    result, context, _, raw, transaction = open_processed(document(name), f"action_{action.lower()}")
    outcomes = []
    for _ in range(2):
        verification = verify_and_authorize_canonical_event_v1(
            result.canonical_document, raw, context, transaction, action
        )
        if verification.authorized:
            FakeConsumer(action).accept_result(verification, transaction)
            outcomes.append("CONSUMED")
        else:
            outcomes.append(verification.reason_code)
    assert outcomes == ["CONSUMED", event_v1.AUTHORIZATION_ALREADY_CONSUMED]
    transaction.close()


@pytest.mark.parametrize("action", _POINT_OF_USE_ACTIONS)
def test_concurrent_fresh_verification_allows_one_consumption(action):
    name = "setup_invalidation" if action == "STATE_MUTATION" else "rejection_ready"
    result, context, _, raw, transaction = open_processed(document(name), f"concurrent_action_{action.lower()}")
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    outcomes = []

    def worker():
        barrier.wait()
        verification = verify_and_authorize_canonical_event_v1(
            result.canonical_document, raw, context, transaction, action
        )
        if verification.authorized:
            try:
                FakeConsumer(action).accept_result(verification, transaction)
                outcome = "CONSUMED"
            except ContractError as exc:
                outcome = exc.code.upper()
        else:
            outcome = verification.reason_code
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert outcomes.count("CONSUMED") == 1
    assert set(outcomes) <= {
        "CONSUMED", event_v1.AUTHORIZATION_ALREADY_ISSUED,
        event_v1.AUTHORIZATION_ALREADY_CONSUMED,
    }
    transaction.close()


def test_different_actions_remain_independent_within_one_generation():
    result, context, _, raw, transaction = open_processed(document("rejection_ready"), "independent_actions")
    actions = [
        "DISPATCH", "OUTBOX_CREATE", "AUDIT_ACCEPTANCE",
        "DOWNSTREAM_HANDOFF", "REPLAY_RELEASE",
    ]
    for action in actions:
        verification = FakeConsumer(action).act(
            result.canonical_document, raw, context, transaction
        )
        assert verification.authorized
    transaction.close()


def test_generation_advance_invalidates_pending_authorization():
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), "generation_advance")
    stale = verify_and_authorize_canonical_event_v1(
        result.canonical_document, raw, context, transaction, "STATE_MUTATION"
    )
    assert stale.transaction_generation == 1
    assert transaction.advance_generation() == 2
    with pytest.raises(ContractError) as invalidated:
        FakeConsumer("STATE_MUTATION").accept_result(stale, transaction)
    assert invalidated.value.code == "authorization_invalidated"
    current = FakeConsumer("STATE_MUTATION").act(
        result.canonical_document, raw, context, transaction
    )
    assert current.transaction_generation == transaction.generation == 2
    transaction.close()


def test_generation_advance_and_consume_cannot_both_succeed():
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), "generation_race")
    pending = verify_and_authorize_canonical_event_v1(
        result.canonical_document, raw, context, transaction, "STATE_MUTATION"
    )
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    outcomes = []

    def consume():
        barrier.wait()
        try:
            FakeConsumer("STATE_MUTATION").accept_result(pending, transaction)
            outcome = "CONSUMED"
        except ContractError as exc:
            outcome = exc.code
        with lock: outcomes.append(outcome)

    def advance():
        barrier.wait()
        try:
            transaction.advance_generation()
            outcome = "ADVANCED"
        except ContractError as exc:
            outcome = exc.code
        with lock: outcomes.append(outcome)

    threads = [threading.Thread(target=consume), threading.Thread(target=advance)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert len({"CONSUMED", "ADVANCED"} & set(outcomes)) == 1
    assert set(outcomes) <= {
        "CONSUMED", "ADVANCED", "authorization_invalidated",
        "authorization_already_consumed",
    }
    transaction.close()


def _clone_verification(kind, valid):
    if kind == "direct":
        return CanonicalVerificationResultV1(*(getattr(valid, f.name) for f in fields(valid)))
    if kind == "subclass":
        class Forged(CanonicalVerificationResultV1): pass
        return Forged(*(getattr(valid, f.name) for f in fields(valid)))
    if kind == "object_new":
        forged = object.__new__(CanonicalVerificationResultV1)
        for field in fields(valid): object.__setattr__(forged, field.name, getattr(valid, field.name))
        return forged
    if kind == "copy": return copy.copy(valid)
    if kind == "deepcopy": return copy.deepcopy(valid)
    if kind == "pickle": return pickle.loads(pickle.dumps(valid))
    if kind == "mutated":
        object.__setattr__(valid, "authority", "FORGED")
        return valid
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["direct", "subclass", "object_new", "copy", "deepcopy", "pickle", "mutated"])
def test_construct_copy_pickle_subclass_and_isinstance_positive_results_cannot_authorize(kind):
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), f"attack_{kind}")
    valid = verify_and_authorize_canonical_event_v1(result.canonical_document, raw, context, transaction, "STATE_MUTATION")
    forged = _clone_verification(kind, valid)
    assert isinstance(forged, CanonicalVerificationResultV1)
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(forged, transaction)
    transaction.close()


@pytest.mark.parametrize("transform", [lambda x: x, copy.copy, copy.deepcopy, lambda x: pickle.loads(pickle.dumps(x))])
def test_shape_or_copied_canonical_data_has_no_bearer_authority(transform):
    result, _, _, _, transaction = open_processed(document("setup_invalidation"), f"shape_{id(transform)}")
    shaped = transform(result.canonical_document)
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(shaped, transaction)
    transaction.close()


def test_stale_verification_and_other_action_are_rejected():
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), "stale")
    verification = verify_and_authorize_canonical_event_v1(result.canonical_document, raw, context, transaction, "STATE_MUTATION")
    FakeConsumer("STATE_MUTATION").accept_result(verification, transaction)
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(verification, transaction)
    audit = verify_and_authorize_canonical_event_v1(result.canonical_document, raw, context, transaction, "AUDIT_ACCEPTANCE")
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(audit, transaction)
    transaction.close()


def test_different_receipt_context_and_transaction_cannot_verify_or_consume():
    one = open_processed(document("setup_invalidation"), "receipt_one")
    two = open_processed(document("setup_invalidation"), "receipt_two")
    result1, context1, _, raw1, tx1 = one
    _, context2, _, _, tx2 = two
    wrong_context = verify_and_authorize_canonical_event_v1(result1.canonical_document, raw1, context2, tx1, "STATE_MUTATION")
    wrong_transaction = verify_and_authorize_canonical_event_v1(result1.canonical_document, raw1, context1, tx2, "STATE_MUTATION")
    assert not wrong_context.authorized and not wrong_transaction.authorized
    valid = verify_and_authorize_canonical_event_v1(result1.canonical_document, raw1, context1, tx1, "STATE_MUTATION")
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(valid, tx2)
    tx1.close(); tx2.close()


def test_results_after_transaction_close_or_rollback_are_rejected():
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), "closed_auth")
    verification = verify_and_authorize_canonical_event_v1(result.canonical_document, raw, context, transaction, "STATE_MUTATION")
    transaction.close()
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(verification, transaction)
    raw2 = canonical_json_bytes(document("setup_invalidation"))
    context2 = issue_context(raw2, "rolled_auth")
    tx2 = InMemoryDedupeAuthority().begin_receipt_transaction(context2)
    tx2.rollback()
    forged = CanonicalVerificationResultV1(True, "STATE_MUTATION", "POINT_OF_USE_VERIFIED", context2.receipt_id, context2.raw_content_hash, "sha256:" + "0" * 64, tx2.transaction_id, tx2.generation, "auth_forged", "CURRENT_TRANSACTION")
    with pytest.raises(ContractError):
        FakeConsumer("STATE_MUTATION").accept_result(forged, tx2)
    tx2.close()


@pytest.mark.parametrize(
    "path",
    [
        ("setup_id",),
        ("canonical_content_hash",),
        ("semantic_evidence_hash",),
        ("canonical_event_id",),
        ("receipt", "raw_content_hash"),
        ("receipt", "received_at"),
        ("validation", "status"),
        ("validation", "state_mutation_allowed"),
        ("dedupe", "exact_receipt_duplicate"),
        ("audit", "validator_version"),
    ],
)
def test_all_trusted_field_tampering_fails_point_of_use(path):
    result, context, _, raw, transaction = open_processed(document("setup_invalidation"), "tamper_" + "_".join(path))
    forged = result.canonical_document.document
    target = forged
    for key in path[:-1]: target = target[key]
    key = path[-1]
    value = target[key]
    target[key] = (not value) if isinstance(value, bool) else "FORGED"
    verification = verify_and_authorize_canonical_event_v1(forged, raw, context, transaction, "STATE_MUTATION")
    assert not verification.authorized
    transaction.close()


def test_raw_byte_binding_precedes_parsing_and_never_reuses_other_context():
    wire = document("rejection_ready")
    raw = canonical_json_bytes(wire)
    context = issue_context(raw, "raw_first")
    changed = raw + b" "
    result = process_wire_event_v1_receipt(changed, context, InMemoryDedupeAuthority())
    assert result.reason_code == event_v1.TRUSTED_RECEIPT_CONTEXT_MISMATCH
    assert result.canonical_document is None


def test_generic_read_api_distinguishes_all_data_surfaces_without_authority():
    wire = document("rejection_ready")
    wire_read = read_project_a_event(wire)
    processed, _, _, _ = process_document(wire, "surface")
    canonical_read = read_project_a_event(processed.canonical_document.document)
    assert wire_read["contract"] == PROJECT_A_WIRE_EVENT_V1
    assert isinstance(wire_read["document"], ParsedWireEventV1)
    assert canonical_read["contract"] == PROJECT_A_CANONICAL_EVENT_V1
    assert isinstance(canonical_read["document"], CanonicalEventV1Document)
    assert wire_read["authority"] == canonical_read["authority"] == "NONE"
    assert isinstance(processed, ReceiptProcessingResultV1) and processed.authority == "NONE"


def test_shape_validation_is_data_only_and_mapping_constructor_stays_disabled():
    result, _, _, _ = process_document(document("rejection_ready"), "shape_only")
    shaped = validate_canonical_event_v1_shape(result.canonical_document.document)
    assert isinstance(shaped, CanonicalEventV1Document)
    with pytest.raises(ContractError) as error:
        canonicalize_wire_event_v1(document("rejection_ready"))
    assert error.value.code == "mapping_constructor_disabled"


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (Decimal("1e10001"), "canonical_number_exponent"),
        (Decimal("1e-10001"), "canonical_number_exponent"),
        (Decimal("1." + "1" * 64), "canonical_number_significant_digits"),
        (10 ** 64, "canonical_number_significant_digits"),
        (Decimal("1e2048"), "canonical_number_rendered_length"),
        (Decimal("1e-2048"), "canonical_number_rendered_length"),
    ],
)
def test_numeric_amplification_is_bounded_before_render(value, code):
    with pytest.raises(ContractError) as error:
        canonical_json(value)
    assert error.value.code == code


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1e2047"), "1" + "0" * 2047),
        (Decimal("-0"), "0"),
        (Decimal("1e0"), "1"),
        (Decimal("1.000"), "1"),
        (Decimal("0.001e3"), "1"),
        (Decimal("9." + "9" * 62), "9." + "9" * 62),
    ],
)
def test_numeric_boundary_and_equivalent_values_remain_deterministic(value, expected):
    assert canonical_json(value) == expected


def test_cross_process_canonicalization_is_identical():
    script = "from decimal import Decimal; from contracts import canonical_json; print(canonical_json({'z':Decimal('1e0'),'a':'é'}).encode('utf-8').hex())"
    expected = canonical_json({"z": Decimal("1e0"), "a": "é"})
    completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, text=True, encoding="ascii", capture_output=True, check=True)
    assert bytes.fromhex(completed.stdout.strip()).decode("utf-8") == expected


def test_legacy_v02_is_shape_only_unverified_and_lifecycle_unsupported():
    cases = load(FIXTURES / "event_cases.json")
    accepted = cases["accepted_alert"]["payload"]
    result = read_project_a_event(accepted)
    assert result["contract"] == EVENT_SCHEMA_V0_2
    assert result["status"] == "SHAPE_VALID"
    assert result["receipt_provenance"] == "LEGACY_UNVERIFIED"
    assert result["trusted_received_at"] is None
    lifecycle = copy.deepcopy(accepted)
    lifecycle["event_type"] = "ENTRY_WINDOW_OPEN"
    lifecycle["disposition"]["status"] = "ACCEPTED"
    validate_legacy_event_v0_2(lifecycle)
    assert read_project_a_event(lifecycle)["reason_code"] == event_v1.UNSUPPORTED_LIFECYCLE_V02


@pytest.mark.parametrize("bad", [{}, {"schema_version": "1.0"}, {"schema_version": "9.9", "contract_family": "PROJECT_A_WIRE_EVENT"}])
def test_unknown_or_ambiguous_event_versions_fail_closed(bad):
    with pytest.raises(ContractError) as error:
        read_project_a_event(bad)
    assert error.value.code == "unknown_event_contract"


def test_frozen_v02_hashes_are_unchanged_and_registry_resolves():
    event_path = FIXTURES / "event_cases.json"
    schema_path = ROOT / "contracts" / "schemas" / "event_schema_v0_2.json"
    assert hashlib.sha256(event_path.read_bytes()).hexdigest() == FROZEN_EVENT_HASH
    assert hashlib.sha256(schema_path.read_bytes()).hexdigest() == FROZEN_SCHEMA_HASH
    for case in load(event_path).values():
        expected = case["expected"]
        if expected["valid"]: validate_contract(EVENT_SCHEMA_V0_2, case["payload"])


def test_migration_matrix_and_replay_keep_writers_disabled():
    migration = load(MIGRATION_PATH)
    assert migration["writer_enablement"] == "DISABLED"
    assert migration["frozen_event_cases_sha256"] == "sha256:" + FROZEN_EVENT_HASH
    assert migration["frozen_event_schema_v0_2_sha256"] == "sha256:" + FROZEN_SCHEMA_HASH
    result = replay.run_all()
    foundation = result["event_v1_reader_foundation"]
    assert result["ok"] is True and result["mode"] == "SHADOW"
    assert result["environment"] == "MT5_DEMO" and result["live_execution"] is False
    assert result["accepted_pipeline"]["outputs"]["mt5"]["order_placed"] is False
    assert foundation["writer_enablement"] == "DISABLED"


def test_no_writer_endpoint_or_live_adapter_is_exposed_by_event_contract_module():
    public = set(event_v1.__dict__)
    assert not {"write_project_a_event", "enable_v1_writer", "publish_event_v1", "create_event_endpoint"} & public
    assert InMemoryDedupeAuthority().durable is False
