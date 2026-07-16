"""Project A Event V1 reader, receipt processing, and point-of-use authority.

All public models in this module are data.  Python type identity, ``isinstance``,
private-looking attributes, copying, and serialization confer no authority.
An action is authorized only by fresh verification against exact bytes, a
receipt context, and an open committed dedupe transaction, immediately followed
by one-time consumption of that transaction-bound authorization.

No writer, endpoint, production ingress issuer, or Session 2 adapter exists.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from ._trusted_ingress import _TrustedReceiptContextV1
from .registry import EVENT_SCHEMA_V0_2, PROJECT_A_CANONICAL_EVENT_V1, PROJECT_A_WIRE_EVENT_V1
from .validation import MAX_DOCUMENT_BYTES, ContractError, canonical_json_bytes, validate_contract

VALIDATOR_VERSION = "project-a-event-v1/1.3"
PROJECTION_VERSION = "project-a-evidence/1.1"
UNSUPPORTED_LIFECYCLE_V02 = "UNSUPPORTED_LIFECYCLE_V02"
MISSING_CANONICAL_SETUP_IDENTITY = "MISSING_CANONICAL_SETUP_IDENTITY"
INVALID_CANONICAL_SETUP_IDENTITY = "INVALID_CANONICAL_SETUP_IDENTITY"
DEDUPE_AUTHORITY_REQUIRED = "DEDUPE_AUTHORITY_REQUIRED"
DEDUPE_AUTHORITY_UNAVAILABLE = "DEDUPE_AUTHORITY_UNAVAILABLE"
DEDUPE_AUTHORITY_INVALID_RESULT = "DEDUPE_AUTHORITY_INVALID_RESULT"
DEDUPE_TRANSACTION_FAILED = "DEDUPE_TRANSACTION_FAILED"
DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN = "DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN"
TRUSTED_RECEIPT_CONTEXT_MISMATCH = "TRUSTED_RECEIPT_CONTEXT_MISMATCH"
AUTHORIZATION_ALREADY_ISSUED = "AUTHORIZATION_ALREADY_ISSUED"
AUTHORIZATION_ALREADY_CONSUMED = "AUTHORIZATION_ALREADY_CONSUMED"
AUTHORIZATION_GENERATION_STALE = "AUTHORIZATION_GENERATION_STALE"
AUTHORIZATION_INVALIDATED = "AUTHORIZATION_INVALIDATED"

_UTC_V1 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$")
_LIFECYCLE_TYPES = {
    "SETUP_INVALIDATED", "SETUP_EXPIRED", "ENTRY_WINDOW_OPEN",
    "ENTRY_WINDOW_CLOSED", "THESIS_INVALIDATED",
}
_UNSUPPORTED_V02_LIFECYCLE = {"ENTRY_WINDOW_OPEN", "ENTRY_WINDOW_CLOSED", "THESIS_INVALIDATED"}
_TIMEFRAME_ORDER = {"1m": 0, "5m": 1, "15m": 2, "30m": 3}
_SEMANTIC_TIMESTAMP_KEYS = {"bar_close", "evidence_time", "started_at", "ended_at", "effective_at"}
_RESERVED_EXTENSION_CONCEPTS = {
    "broker", "account", "order", "trade", "execution", "live", "mt5live",
    "endpoint", "webhook", "route", "routing", "receipt", "receivedat",
    "canonical", "hash", "validation", "dedupe", "dispatch", "retry", "audit",
    "permission", "statemutation", "secret", "token", "credential",
}
_ACTIONS = {
    "STATE_MUTATION", "DISPATCH", "OUTBOX_CREATE", "AUDIT_ACCEPTANCE",
    "DOWNSTREAM_HANDOFF", "REPLAY_RELEASE",
}


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _strict_utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not _UTC_V1.fullmatch(value):
        raise ContractError("timestamp_not_rfc3339_utc", "expected UTC RFC 3339 with zero to three fractional digits", field_name)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ContractError("timestamp_invalid", str(exc), field_name) from exc


def _normalized_utc_millis(value: str, field_name: str) -> str:
    return _strict_utc(value, field_name).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bounded_raw_hash(raw_bytes: bytes) -> str:
    if not isinstance(raw_bytes, bytes):
        raise ContractError("raw_bytes_required", "receipt processing requires exact bytes")
    if len(raw_bytes) > MAX_DOCUMENT_BYTES:
        raise ContractError("raw_document_too_large", f"maximum is {MAX_DOCUMENT_BYTES} bytes")
    return _sha256(raw_bytes)


def _strict_json_object(raw_bytes: bytes) -> dict:
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raise ContractError("wire_bom_forbidden", "UTF-8 BOM is prohibited")

    def pairs(items: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ContractError("duplicate_json_key", f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError("wire_not_utf8", str(exc)) from exc
    try:
        value = json.loads(
            text, object_pairs_hook=pairs, parse_int=Decimal, parse_float=Decimal,
            parse_constant=lambda token: (_ for _ in ()).throw(ContractError("non_finite_number", token)),
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError("wire_json_invalid", str(exc)) from exc
    if not isinstance(value, dict):
        raise ContractError("wire_json_object_required", "Wire Event V1 must be one JSON object")
    return value


@dataclass(frozen=True, slots=True)
class ParsedWireEventV1:
    _document: dict = field(repr=False)
    observed_raw_content_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_document", deepcopy(self._document))

    @property
    def document(self) -> dict:
        return deepcopy(self._document)


@dataclass(frozen=True, slots=True)
class CanonicalEventV1Document:
    _document: dict = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_document", deepcopy(self._document))

    @property
    def document(self) -> dict:
        return deepcopy(self._document)


@dataclass(frozen=True, slots=True)
class ReceiptProcessingResultV1:
    processing_status: str
    reason_code: str
    raw_content_hash: str | None
    receipt_id: str | None
    immutable_raw_reference: str | None
    received_at: str | None
    wire_family: str | None
    wire_version: str | None
    canonical_document: CanonicalEventV1Document | None
    setup_id: str | None
    state_mutation_allowed: bool = False
    dispatch_allowed: bool = False
    authority: str = "NONE"
    transaction_id: str | None = None
    audit_detail: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalVerificationResultV1:
    authorized: bool
    intended_action: str
    reason_code: str
    receipt_id: str | None
    raw_content_hash: str | None
    canonical_content_hash: str | None
    transaction_id: str | None
    transaction_generation: int | None
    authorization_id: str | None
    authority: str = "NONE"


@dataclass(frozen=True, slots=True)
class DedupeDecision:
    exact_receipt_duplicate: bool
    semantic_evidence_duplicate: bool
    prior_canonical_event_ids: tuple[str, ...]


class DedupeAuthorityUnavailable(RuntimeError):
    pass


class DedupeCommitUnknown(RuntimeError):
    pass


class DedupeReceiptTransaction(ABC):
    @property
    @abstractmethod
    def transaction_id(self) -> str: ...

    @property
    @abstractmethod
    def generation(self) -> int: ...

    @property
    @abstractmethod
    def committed(self) -> bool: ...

    @property
    @abstractmethod
    def closed(self) -> bool: ...

    @property
    @abstractmethod
    def receipt_context(self) -> _TrustedReceiptContextV1: ...

    @property
    @abstractmethod
    def decision(self) -> DedupeDecision | None: ...

    @property
    @abstractmethod
    def prior_canonical_event_ids(self) -> tuple[str, ...]: ...

    @abstractmethod
    def record_receipt(self, raw_content_hash: str) -> None: ...

    @abstractmethod
    def reserve_exact(self, transport_identity: str, canonical_content_hash: str) -> bool: ...

    @abstractmethod
    def reserve_semantic(self, semantic_evidence_hash: str) -> bool: ...

    @abstractmethod
    def persist_decision(self, *, decision: DedupeDecision | None, canonical_event_id: str | None, processing_status: str, reason_code: str, state_mutation_allowed: bool, dispatch_allowed: bool) -> None: ...

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def assert_current_context(self, context: _TrustedReceiptContextV1) -> None: ...

    @abstractmethod
    def issue_authorization(self, *, action: str, canonical_content_hash: str, raw_content_hash: str) -> CanonicalVerificationResultV1: ...

    @abstractmethod
    def consume_authorization(self, result: CanonicalVerificationResultV1, intended_action: str) -> None: ...

    @abstractmethod
    def advance_generation(self) -> int: ...

    def __enter__(self) -> "DedupeReceiptTransaction":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if not self.committed:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()
        return False


class DedupeAuthority(ABC):
    @property
    @abstractmethod
    def durable(self) -> bool: ...

    @abstractmethod
    def begin_receipt_transaction(self, context: _TrustedReceiptContextV1) -> DedupeReceiptTransaction: ...


class InMemoryDedupeAuthority(DedupeAuthority):
    """Replay/test atomic model. Production use always fails the context guard."""

    def __init__(self, *, available: bool = True, fail_at: str | None = None) -> None:
        self.available = available
        self.fail_at = fail_at
        self._lock = threading.RLock()
        self._counter = 0
        self._exact: dict[tuple[str, str], list[str]] = {}
        self._semantic: dict[str, list[str]] = {}
        self._receipts: dict[str, dict] = {}

    @property
    def durable(self) -> bool:
        return False

    def begin_receipt_transaction(self, context: _TrustedReceiptContextV1) -> DedupeReceiptTransaction:
        if not self.available:
            raise DedupeAuthorityUnavailable("dedupe authority unavailable")
        if not isinstance(context, _TrustedReceiptContextV1) or context.context_kind != "REPLAY_ONLY" or not context.replay_clock:
            raise ContractError("durable_dedupe_authority_required", "in-memory authority is replay-only")
        if self.fail_at == "begin":
            raise RuntimeError("injected begin failure")
        with self._lock:
            self._counter += 1
            number = self._counter
        return _InMemoryReceiptTransaction(self, context, number)


class _InMemoryReceiptTransaction(DedupeReceiptTransaction):
    def __init__(self, authority: InMemoryDedupeAuthority, context: _TrustedReceiptContextV1, number: int) -> None:
        self._authority = authority
        # Serialize the replay unit of work so reservations and commit model
        # one atomic boundary even when tests exercise concurrent receipts.
        self._authority._lock.acquire()
        self._lock_held = True
        self._context = context
        self._transaction_id = "dtx_" + hashlib.sha256(f"{context.receipt_id}:{number}".encode()).hexdigest()[:32]
        self._authorization_lock = threading.RLock()
        self._generation = 1
        self._committed = False
        self._closed = False
        self._rolled_back = False
        self._commit_calls = 0
        self._recorded = False
        self._exact_key: tuple[str, str] | None = None
        self._semantic_hash: str | None = None
        self._exact_duplicate: bool | None = None
        self._semantic_duplicate: bool | None = None
        self._prior_ids: tuple[str, ...] = ()
        self._decision: DedupeDecision | None = None
        self._canonical_event_id: str | None = None
        self._processing_status: str | None = None
        self._reason_code: str | None = None
        self._state_mutation_allowed = False
        self._dispatch_allowed = False
        self._persisted = False
        self._authorizations: dict[str, tuple[tuple[Any, ...], CanonicalVerificationResultV1]] = {}
        self._authorization_states: dict[tuple[int, str], str] = {}
        self._auth_counter = 0

    @property
    def transaction_id(self) -> str: return self._transaction_id
    @property
    def generation(self) -> int:
        with self._authorization_lock:
            return self._generation
    @property
    def committed(self) -> bool: return self._committed
    @property
    def closed(self) -> bool: return self._closed
    @property
    def receipt_context(self) -> _TrustedReceiptContextV1: return self._context
    @property
    def decision(self) -> DedupeDecision | None: return self._decision
    @property
    def prior_canonical_event_ids(self) -> tuple[str, ...]: return self._prior_ids

    def _active(self) -> None:
        if self._closed:
            raise ContractError("dedupe_transaction_closed", "transaction is closed")
        if self._rolled_back:
            raise ContractError("dedupe_transaction_rolled_back", "transaction was rolled back")

    def _fail(self, stage: str) -> None:
        if self._authority.fail_at == stage:
            raise RuntimeError(f"injected {stage} failure")

    def _release_lock(self) -> None:
        if self._lock_held:
            self._lock_held = False
            self._authority._lock.release()

    def record_receipt(self, raw_content_hash: str) -> None:
        self._active(); self._fail("record_receipt")
        if self._recorded:
            raise ContractError("dedupe_receipt_already_recorded", "record_receipt called twice")
        if raw_content_hash != self._context.raw_content_hash:
            raise ContractError("trusted_raw_receipt_mismatch", "receipt hash differs from context")
        self._recorded = True

    def reserve_exact(self, transport_identity: str, canonical_content_hash: str) -> bool:
        self._active(); self._fail("reserve_exact")
        if not self._recorded or self._exact_key is not None:
            raise ContractError("dedupe_transaction_order", "exact reserve requires one receipt record")
        self._exact_key = (transport_identity, canonical_content_hash)
        with self._authority._lock:
            ids = list(self._authority._exact.get(self._exact_key, []))
        self._exact_duplicate = bool(ids)
        self._prior_ids = tuple(dict.fromkeys([*self._prior_ids, *ids]))[:16]
        return self._exact_duplicate

    def reserve_semantic(self, semantic_evidence_hash: str) -> bool:
        self._active(); self._fail("reserve_semantic")
        if self._exact_key is None or self._semantic_hash is not None:
            raise ContractError("dedupe_transaction_order", "semantic reserve follows exact reserve")
        self._semantic_hash = semantic_evidence_hash
        with self._authority._lock:
            ids = list(self._authority._semantic.get(semantic_evidence_hash, []))
        self._semantic_duplicate = bool(ids)
        self._prior_ids = tuple(dict.fromkeys([*self._prior_ids, *ids]))[:16]
        return self._semantic_duplicate

    def persist_decision(self, *, decision: DedupeDecision | None, canonical_event_id: str | None, processing_status: str, reason_code: str, state_mutation_allowed: bool, dispatch_allowed: bool) -> None:
        self._active(); self._fail("persist_decision")
        if not self._recorded or self._persisted:
            raise ContractError("dedupe_transaction_order", "one receipt and one decision are required")
        if decision is not None:
            if self._exact_duplicate is None or self._semantic_duplicate is None:
                raise ContractError("dedupe_transaction_order", "both reserves are required")
            if decision != DedupeDecision(self._exact_duplicate, self._semantic_duplicate, self._prior_ids):
                raise ContractError("dedupe_authority_invalid_result", "decision differs from reservations")
        self._decision = decision
        self._canonical_event_id = canonical_event_id
        self._processing_status = processing_status
        self._reason_code = reason_code
        if type(state_mutation_allowed) is not bool or type(dispatch_allowed) is not bool:
            raise ContractError("dedupe_authority_invalid_result", "eligibility values must be bool")
        self._state_mutation_allowed = state_mutation_allowed
        self._dispatch_allowed = dispatch_allowed
        self._persisted = True

    def _apply_commit(self) -> None:
        a = self._authority
        if self._context.receipt_id in a._receipts:
            raise ContractError("duplicate_receipt_id", "receipt_id already committed")
        a._receipts[self._context.receipt_id] = {
            "raw_content_hash": self._context.raw_content_hash,
            "transaction_id": self._transaction_id,
            "processing_status": self._processing_status,
            "reason_code": self._reason_code,
            "decision": self._decision,
            "state_mutation_allowed": self._state_mutation_allowed,
            "dispatch_allowed": self._dispatch_allowed,
        }
        if self._decision is not None and self._canonical_event_id is not None:
            a._exact.setdefault(self._exact_key, []).append(self._canonical_event_id)
            a._semantic.setdefault(self._semantic_hash, []).append(self._canonical_event_id)

    def commit(self) -> None:
        self._active()
        self._commit_calls += 1
        if self._commit_calls != 1 or self._committed:
            raise ContractError("dedupe_commit_once", "commit must be called exactly once")
        if not self._persisted:
            raise ContractError("dedupe_transaction_order", "persist_decision precedes commit")
        if self._authority.fail_at == "commit":
            raise RuntimeError("injected commit failure")
        with self._authority._lock:
            if self._authority.fail_at == "commit_unknown":
                self._apply_commit()
                raise DedupeCommitUnknown("commit outcome is partial or unknown")
            self._apply_commit()
            self._committed = True
            self._release_lock()

    def rollback(self) -> None:
        with self._authorization_lock:
            if self._closed:
                raise ContractError("dedupe_transaction_closed", "transaction is closed")
            if self._committed:
                raise ContractError("dedupe_committed_no_rollback", "committed transaction cannot roll back")
            self._invalidate_pending_authorizations_locked()
            self._rolled_back = True
            self._release_lock()

    def close(self) -> None:
        with self._authorization_lock:
            if self._closed:
                raise ContractError("dedupe_transaction_closed", "transaction is already closed")
            self._invalidate_pending_authorizations_locked()
            self._closed = True
            self._release_lock()

    def assert_current_context(self, context: _TrustedReceiptContextV1) -> None:
        self._active()
        if context is not self._context:
            raise ContractError("dedupe_transaction_context_mismatch", "transaction is bound to another receipt context")

    def issue_authorization(self, *, action: str, canonical_content_hash: str, raw_content_hash: str) -> CanonicalVerificationResultV1:
        with self._authorization_lock:
            self._active()
            if not self._committed:
                raise ContractError("dedupe_transaction_not_committed", "authorization requires commit")
            key = (self._generation, action)
            state = self._authorization_states.get(key)
            if state == "PENDING":
                raise ContractError("authorization_already_issued", "one authorization is already pending for this generation/action")
            if state == "CONSUMED":
                raise ContractError("authorization_already_consumed", "this generation/action was already consumed")
            if state == "INVALIDATED":
                raise ContractError("authorization_invalidated", "this generation/action was invalidated")
            self._auth_counter += 1
            auth_id = "auth_" + hashlib.sha256(
                f"{self._transaction_id}:{self._generation}:{self._auth_counter}:{action}:{canonical_content_hash}".encode()
            ).hexdigest()[:40]
            result = CanonicalVerificationResultV1(
                True, action, "POINT_OF_USE_VERIFIED", self._context.receipt_id,
                raw_content_hash, canonical_content_hash, self._transaction_id,
                self._generation, auth_id, "CURRENT_TRANSACTION",
            )
            self._authorizations[auth_id] = (self._authorization_snapshot(result), result)
            self._authorization_states[key] = "PENDING"
            return result

    @staticmethod
    def _authorization_snapshot(result: CanonicalVerificationResultV1) -> tuple[Any, ...]:
        return (
            result.authorized, result.intended_action, result.reason_code,
            result.receipt_id, result.raw_content_hash,
            result.canonical_content_hash, result.transaction_id,
            result.transaction_generation, result.authorization_id,
            result.authority,
        )

    def consume_authorization(self, result: CanonicalVerificationResultV1, intended_action: str) -> None:
        with self._authorization_lock:
            self._active()
            if not self._committed:
                raise ContractError("dedupe_transaction_not_committed", "consumer requires committed transaction")
            if not isinstance(result, CanonicalVerificationResultV1) or not result.authorized:
                raise ContractError("point_of_use_authorization_required", "fresh authorized result is required")
            result_generation = result.transaction_generation
            key = (result_generation, intended_action)
            state = self._authorization_states.get(key)
            if result_generation != self._generation:
                code = "authorization_invalidated" if state == "INVALIDATED" else "authorization_generation_stale"
                raise ContractError(code, "authorization does not belong to the current transaction generation")
            if state == "INVALIDATED":
                raise ContractError("authorization_invalidated", "authorization was invalidated")
            if state == "CONSUMED":
                raise ContractError("authorization_already_consumed", "this generation/action was already consumed")
            registered = self._authorizations.get(result.authorization_id or "")
            if (
                state != "PENDING"
                or registered is None
                or registered[0] != self._authorization_snapshot(result)
                or registered[1] is not result
                or result.intended_action != intended_action
                or result.transaction_id != self._transaction_id
            ):
                raise ContractError("point_of_use_authorization_stale", "authorization is stale, forged, or for another action")
            self._authorization_states[key] = "CONSUMED"
            del self._authorizations[result.authorization_id]

    def _invalidate_pending_authorizations_locked(self) -> None:
        for key, state in tuple(self._authorization_states.items()):
            if state == "PENDING":
                self._authorization_states[key] = "INVALIDATED"
        self._authorizations.clear()

    def advance_generation(self) -> int:
        """Atomically invalidate pending authority and advance an unused generation."""
        with self._authorization_lock:
            self._active()
            if not self._committed:
                raise ContractError("dedupe_transaction_not_committed", "generation advance requires commit")
            current_states = {
                state for (generation, _), state in self._authorization_states.items()
                if generation == self._generation
            }
            if "CONSUMED" in current_states:
                raise ContractError("authorization_already_consumed", "a consumed generation cannot be advanced")
            self._invalidate_pending_authorizations_locked()
            self._generation += 1
            return self._generation


def _validate_extension_safety(document: Mapping[str, Any]) -> None:
    source = document.get("source")
    bags = (("$.extensions", document.get("extensions")), ("$.source.diagnostics", source.get("diagnostics") if isinstance(source, Mapping) else None))
    for path, bag in bags:
        if not isinstance(bag, Mapping):
            continue
        for key, value in bag.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(concept in normalized_key for concept in _RESERVED_EXTENSION_CONCEPTS):
                raise ContractError("reserved_extension_key", "control-like extension key is prohibited", f"{path}.{key}")
            if isinstance(value, str):
                normalized_value = re.sub(r"[^a-z0-9]", "", value.lower())
                if any(concept in normalized_value for concept in _RESERVED_EXTENSION_CONCEPTS):
                    raise ContractError("reserved_extension_value", "control-like extension value is prohibited", f"{path}.{key}")


def _validate_unique_timeframes(items: list[dict], field_name: str) -> None:
    values = [item["timeframe"] for item in items]
    if len(values) != len(set(values)):
        raise ContractError("duplicate_timeframe_evidence", "timeframe entries must be unique", field_name)


def _validate_geometry(geometry: dict, hypothesis: str | None) -> None:
    direction = geometry["direction"]
    entry, sl, tp = geometry["entry"], geometry["sl"], geometry["tp"]
    if hypothesis is not None and direction != hypothesis:
        raise ContractError("geometry_hypothesis_mismatch", "geometry direction must match hypothesis")
    if direction == "LONG" and not (sl < entry < tp):
        raise ContractError("trade_geometry", "LONG requires sl < entry < tp")
    if direction == "SHORT" and not (tp < entry < sl):
        raise ContractError("trade_geometry", "SHORT requires tp < entry < sl")
    if Decimal(str(abs(tp - entry))) != Decimal(str(abs(entry - sl))):
        raise ContractError("rr_not_one_to_one", "geometry must be exactly 1:1")


def _validate_semantic_timestamps(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _SEMANTIC_TIMESTAMP_KEYS:
                _strict_utc(child, child_path)
            else:
                _validate_semantic_timestamps(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_semantic_timestamps(child, f"{path}[{index}]")


def validate_wire_event_v1_shape(document: dict) -> dict:
    if not isinstance(document, dict):
        raise ContractError("document_type", "document must be a JSON object")
    _validate_extension_safety(document)
    validate_contract(PROJECT_A_WIRE_EVENT_V1, document)
    _validate_semantic_timestamps(document["evidence"], "$.evidence")
    occurred = _strict_utc(document["occurred_at"], "$.occurred_at")
    if document.get("emitted_at") is not None:
        emitted = _strict_utc(document["emitted_at"], "$.emitted_at")
        if emitted < occurred:
            raise ContractError("emitted_before_occurred", "emitted_at precedes occurred_at")
    expected_types = {
        "TELEMETRY": {"SNR_UPDATE", "EXPANSION_UPDATE"},
        "SETUP_CANDIDATE": {"SETUP_CANDIDATE"},
        "ANALYSIS_READY": {"SNR_REJECTION_READY", "SNR_BREAK_READY"},
        "LIFECYCLE": _LIFECYCLE_TYPES,
    }
    if document["event_type"] not in expected_types[document["event_class"]]:
        raise ContractError("event_class_type_mismatch", "event type is invalid for event class")
    evidence = document["evidence"]
    _validate_unique_timeframes(evidence["hpa"], "$.evidence.hpa")
    _validate_unique_timeframes(evidence["momentum"], "$.evidence.momentum")
    snr = evidence["snr"]
    if snr is not None and snr["low"] > snr["high"]:
        raise ContractError("snr_bounds", "snr.low must be <= snr.high")
    if document["event_class"] != "TELEMETRY" and document["setup_origin"] is None:
        raise ContractError("setup_origin_required", "non-telemetry events require setup origin")
    if document["event_class"] == "ANALYSIS_READY":
        for name in ("hypothesis", "path"):
            if document[name] is None:
                raise ContractError(f"analysis_ready_{name}_required", f"{name} is required")
        if snr is None or evidence["trigger"] is None:
            raise ContractError("analysis_ready_evidence_required", "SNR and trigger are required")
        for group in ("hpa", "momentum"):
            for item in evidence[group]:
                if item["timeframe"] in {"5m", "15m", "30m"} and item["confirmation_state"] != "CONFIRMED":
                    raise ContractError("provisional_htf_not_analysis_ready", "developing HTF evidence is telemetry-only", f"$.evidence.{group}")
    required_evidence = {
        "SNR_REJECTION_READY": "rejection", "SNR_BREAK_READY": "break",
        "SETUP_INVALIDATED": "invalidation", "THESIS_INVALIDATED": "invalidation",
        "SETUP_EXPIRED": "expiry", "ENTRY_WINDOW_OPEN": "entry_window", "ENTRY_WINDOW_CLOSED": "entry_window",
    }
    required = required_evidence.get(document["event_type"])
    if required and evidence[required] is None:
        raise ContractError("event_evidence_required", f"{document['event_type']} requires {required}")
    if evidence["entry_window"] is not None and document["event_type"] in {"ENTRY_WINDOW_OPEN", "ENTRY_WINDOW_CLOSED"}:
        expected = "OPEN" if document["event_type"] == "ENTRY_WINDOW_OPEN" else "CLOSED"
        if evidence["entry_window"]["transition"] != expected:
            raise ContractError("entry_window_transition_mismatch", "transition does not match event type")
    if evidence["geometry"] is not None:
        _validate_geometry(evidence["geometry"], document["hypothesis"])
    return document


def parse_wire_event_v1_bytes(raw_bytes: bytes) -> ParsedWireEventV1:
    raw_hash = _bounded_raw_hash(raw_bytes)
    parsed = _strict_json_object(raw_bytes)
    validate_wire_event_v1_shape(parsed)
    return ParsedWireEventV1(parsed, raw_hash)


def _normalized_semantic(value: Any, key: str | None = None) -> Any:
    if isinstance(value, bool) or value is None: return value
    if isinstance(value, str): return _normalized_utc_millis(value, f"$.semantic.{key}") if key in _SEMANTIC_TIMESTAMP_KEYS else value
    if isinstance(value, (int, float, Decimal)): return canonical_json_bytes(value).decode("utf-8")
    if isinstance(value, list): return [_normalized_semantic(item) for item in value]
    if isinstance(value, Mapping): return {name: _normalized_semantic(value[name], name) for name in sorted(value)}
    raise ContractError("semantic_value_type", f"unsupported value: {type(value).__name__}")


def _stable_setup_id(document: dict) -> str | None:
    origin = document.get("setup_origin")
    evidence = document.get("evidence")
    snr = evidence.get("snr") if isinstance(evidence, Mapping) else None
    hypothesis = document.get("hypothesis")
    if not isinstance(origin, Mapping) or not isinstance(snr, Mapping) or hypothesis is None:
        return None
    if not origin.get("origin_id") or not origin.get("aoi_id") or not snr.get("identity"):
        return None
    inputs = {"symbol": document["symbol"], "aoi_id": origin["aoi_id"], "snr_identity": snr["identity"], "hypothesis": hypothesis, "setup_origin": origin["origin_id"]}
    return "setup_" + hashlib.sha256(canonical_json_bytes(inputs)).hexdigest()[:32]


def semantic_evidence_projection(document: dict, *, setup_id: str | None = None) -> dict:
    validate_wire_event_v1_shape(document)
    evidence = document["evidence"]
    projection = {
        "projection_version": PROJECTION_VERSION,
        "setup_id": _stable_setup_id(document) if setup_id is None else setup_id,
        "event_class": document["event_class"], "event_type": document["event_type"],
        "path": document["path"], "hypothesis": document["hypothesis"], "snr": evidence["snr"],
        "hpa": sorted(evidence["hpa"], key=lambda item: _TIMEFRAME_ORDER[item["timeframe"]]),
        "momentum": sorted(evidence["momentum"], key=lambda item: _TIMEFRAME_ORDER[item["timeframe"]]),
        "rejection": evidence["rejection"], "break": evidence["break"], "invalidation": evidence["invalidation"],
        "expiry": evidence["expiry"], "entry_window": evidence["entry_window"], "trigger": evidence["trigger"], "geometry": evidence["geometry"],
    }
    return _normalized_semantic(projection)


def validate_canonical_event_v1_shape(document: dict) -> CanonicalEventV1Document:
    validate_contract(PROJECT_A_CANONICAL_EVENT_V1, document)
    return CanonicalEventV1Document(document)


def _identity_values(wire: dict) -> tuple[str, str | None, str, str]:
    canonical_hash = _sha256(canonical_json_bytes(wire))
    setup_id = _stable_setup_id(wire)
    semantic_hash = _sha256(canonical_json_bytes(semantic_evidence_projection(wire, setup_id=setup_id)))
    return canonical_hash, setup_id, semantic_hash, "cevt_" + canonical_hash.removeprefix("sha256:")


def _derive_validation(wire: dict, setup_id: str | None, decision: DedupeDecision) -> dict:
    if wire["event_class"] == "LIFECYCLE" and setup_id is None:
        status, reasons = "REJECTED", [MISSING_CANONICAL_SETUP_IDENTITY]
    elif decision.exact_receipt_duplicate:
        status, reasons = "DUPLICATE", ["EXACT_RECEIPT_DUPLICATE"]
    elif decision.semantic_evidence_duplicate:
        status, reasons = "DUPLICATE", ["SEMANTIC_EVIDENCE_DUPLICATE"]
    else:
        status, reasons = "ACCEPTED", ["VALIDATED"]
    accepted = status == "ACCEPTED"
    return {"status": status, "reason_codes": reasons, "state_mutation_allowed": accepted and wire["event_class"] == "LIFECYCLE" and setup_id is not None, "dispatch_allowed": accepted and wire["event_class"] == "ANALYSIS_READY"}


def _build_canonical(wire: dict, context: _TrustedReceiptContextV1, decision: DedupeDecision) -> dict:
    canonical_hash, setup_id, semantic_hash, canonical_id = _identity_values(wire)
    document = {
        "contract_family": "PROJECT_A_CANONICAL_EVENT", "schema_version": "1.0", "source_wire_version": wire["schema_version"],
        "wire_event": deepcopy(wire),
        "receipt": {"receipt_id": context.receipt_id, "received_at": context.received_at, "transport_identity": context.transport_identity, "source_adapter_identity": context.source_adapter_identity, "raw_content_hash": context.raw_content_hash},
        "canonical_event_id": canonical_id, "canonical_content_hash": canonical_hash, "semantic_evidence_hash": semantic_hash, "setup_id": setup_id,
        "correlation_id": wire["correlation_id"], "causation_id": wire["causation_id"],
        "validation": _derive_validation(wire, setup_id, decision),
        "dedupe": {"exact_receipt_duplicate": decision.exact_receipt_duplicate, "semantic_evidence_duplicate": decision.semantic_evidence_duplicate, "prior_canonical_event_ids": list(decision.prior_canonical_event_ids)},
        "execution_profile": {"symbol": wire["symbol"], "base_tf": wire["base_tf"], "mode": wire["mode"], "execution_environment": wire["execution_environment"], "live_execution": wire["live_execution"], "rr": Decimal("1")},
        "audit": {"canonicalized_at": context.canonicalized_at, "validator_version": VALIDATOR_VERSION, "receipt_provenance": context.receipt_provenance, "immutable_raw_reference": context.immutable_raw_reference, "replay_clock": context.replay_clock, "migration": None},
    }
    validate_canonical_event_v1_shape(document)
    return document


def _lifecycle_identity_problem(document: Mapping[str, Any]) -> str | None:
    if document.get("event_class") != "LIFECYCLE" and document.get("event_type") not in _LIFECYCLE_TYPES:
        return None
    if "setup_id" in document:
        return INVALID_CANONICAL_SETUP_IDENTITY
    origin = document.get("setup_origin")
    if not isinstance(origin, Mapping) or not origin.get("origin_id") or not origin.get("aoi_id"):
        return MISSING_CANONICAL_SETUP_IDENTITY
    if set(origin) != {"origin_id", "aoi_id"}:
        return INVALID_CANONICAL_SETUP_IDENTITY
    if document.get("hypothesis") is None:
        return MISSING_CANONICAL_SETUP_IDENTITY
    evidence = document.get("evidence")
    snr = evidence.get("snr") if isinstance(evidence, Mapping) else None
    if not isinstance(snr, Mapping) or not snr.get("identity"):
        return MISSING_CANONICAL_SETUP_IDENTITY
    return None


def _processing_result(context: _TrustedReceiptContextV1 | None, *, status: str, reason: str, raw_hash: str | None, canonical: dict | None = None, wire: Mapping[str, Any] | None = None, transaction_id: str | None = None, detail: str | None = None) -> ReceiptProcessingResultV1:
    return ReceiptProcessingResultV1(
        processing_status=status, reason_code=reason, raw_content_hash=raw_hash,
        receipt_id=context.receipt_id if context else None,
        immutable_raw_reference=context.immutable_raw_reference if context else None,
        received_at=context.received_at if context else None,
        wire_family=wire.get("contract_family") if isinstance(wire, Mapping) else None,
        wire_version=wire.get("schema_version") if isinstance(wire, Mapping) else None,
        canonical_document=CanonicalEventV1Document(canonical) if canonical is not None else None,
        setup_id=canonical.get("setup_id") if canonical is not None else None,
        state_mutation_allowed=False, dispatch_allowed=False, authority="NONE",
        transaction_id=transaction_id, audit_detail=detail,
    )


def _dedupe_reason(exc: Exception) -> str:
    if isinstance(exc, DedupeAuthorityUnavailable): return DEDUPE_AUTHORITY_UNAVAILABLE
    if isinstance(exc, DedupeCommitUnknown): return DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN
    if isinstance(exc, ContractError):
        if exc.code in {"dedupe_authority_required", "durable_dedupe_authority_required"}: return DEDUPE_AUTHORITY_REQUIRED
        if exc.code in {"trusted_raw_receipt_mismatch", "dedupe_transaction_context_mismatch", "trusted_receipt_context_required"}: return TRUSTED_RECEIPT_CONTEXT_MISMATCH
        if exc.code == "dedupe_authority_invalid_result": return DEDUPE_AUTHORITY_INVALID_RESULT
        if exc.code in {"dedupe_transaction_closed", "dedupe_transaction_rolled_back"}: return DEDUPE_TRANSACTION_PARTIAL_OR_UNKNOWN
    if isinstance(exc, (AttributeError, TypeError)): return DEDUPE_AUTHORITY_INVALID_RESULT
    return DEDUPE_TRANSACTION_FAILED


def _preflight_wire_event_v1_receipt(raw_bytes: bytes, context: _TrustedReceiptContextV1) -> tuple[str | None, dict | None, ReceiptProcessingResultV1 | None]:
    """Complete the raw/shape boundary before canonical dedupe begins."""
    try:
        raw_hash = _bounded_raw_hash(raw_bytes)
    except ContractError as exc:
        return None, None, _processing_result(
            context if isinstance(context, _TrustedReceiptContextV1) else None,
            status="REJECTED", reason=exc.code.upper(), raw_hash=None,
            detail=exc.code,
        )
    if not isinstance(context, _TrustedReceiptContextV1) or raw_hash != context.raw_content_hash:
        return raw_hash, None, _processing_result(
            context if isinstance(context, _TrustedReceiptContextV1) else None,
            status="ERROR", reason=TRUSTED_RECEIPT_CONTEXT_MISMATCH,
            raw_hash=raw_hash, detail="trusted_raw_receipt_mismatch",
        )
    try:
        parsed = _strict_json_object(raw_bytes)
    except ContractError as exc:
        return raw_hash, None, _processing_result(
            context, status="REJECTED", reason=exc.code.upper(),
            raw_hash=raw_hash, detail=exc.code,
        )
    identity_problem = _lifecycle_identity_problem(parsed)
    if identity_problem:
        return raw_hash, parsed, _processing_result(
            context, status="REJECTED", reason=identity_problem,
            raw_hash=raw_hash, wire=parsed,
        )
    try:
        validate_wire_event_v1_shape(parsed)
    except ContractError as exc:
        return raw_hash, parsed, _processing_result(
            context, status="REJECTED", reason="WIRE_VALIDATION_REJECTED",
            raw_hash=raw_hash, wire=parsed, detail=exc.code,
        )
    return raw_hash, parsed, None


def _process_validated_wire_event_v1_receipt(
    raw_hash: str,
    parsed: dict,
    context: _TrustedReceiptContextV1,
    transaction: DedupeReceiptTransaction,
) -> ReceiptProcessingResultV1:
    transaction.assert_current_context(context)
    transaction.record_receipt(raw_hash)
    canonical_hash, _, semantic_hash, canonical_id = _identity_values(parsed)
    exact = transaction.reserve_exact(context.transport_identity, canonical_hash)
    semantic = transaction.reserve_semantic(semantic_hash)
    if type(exact) is not bool or type(semantic) is not bool:
        raise ContractError("dedupe_authority_invalid_result", "reserve methods must return bool")
    prior = transaction.prior_canonical_event_ids
    if not isinstance(prior, tuple):
        raise ContractError("dedupe_authority_invalid_result", "transaction did not expose deterministic prior IDs")
    decision = DedupeDecision(exact, semantic, prior)
    canonical = _build_canonical(parsed, context, decision)
    validation = canonical["validation"]
    transaction.persist_decision(
        decision=decision,
        canonical_event_id=canonical_id,
        processing_status=validation["status"],
        reason_code=validation["reason_codes"][0],
        state_mutation_allowed=validation["state_mutation_allowed"],
        dispatch_allowed=validation["dispatch_allowed"],
    )
    transaction.commit()
    return _processing_result(
        context, status=validation["status"],
        reason=validation["reason_codes"][0], raw_hash=raw_hash,
        canonical=canonical, wire=parsed, transaction_id=transaction.transaction_id,
    )


def process_wire_event_v1_receipt_in_transaction(raw_bytes: bytes, context: _TrustedReceiptContextV1, transaction: DedupeReceiptTransaction) -> ReceiptProcessingResultV1:
    raw_hash, parsed, rejection = _preflight_wire_event_v1_receipt(raw_bytes, context)
    if rejection is not None:
        return rejection
    assert raw_hash is not None and parsed is not None
    try:
        return _process_validated_wire_event_v1_receipt(raw_hash, parsed, context, transaction)
    except Exception as exc:
        try:
            if not transaction.committed and not transaction.closed:
                transaction.rollback()
        except Exception:
            pass
        return _processing_result(
            context, status="ERROR", reason=_dedupe_reason(exc),
            raw_hash=raw_hash, wire=parsed,
            transaction_id=getattr(transaction, "transaction_id", None),
            detail=type(exc).__name__,
        )


def process_wire_event_v1_receipt(raw_bytes: bytes, context: _TrustedReceiptContextV1, dedupe_authority: DedupeAuthority | None) -> ReceiptProcessingResultV1:
    raw_hash, parsed, rejection = _preflight_wire_event_v1_receipt(raw_bytes, context)
    if rejection is not None:
        return rejection
    assert raw_hash is not None and parsed is not None
    if not isinstance(dedupe_authority, DedupeAuthority):
        return _processing_result(context, status="ERROR", reason=DEDUPE_AUTHORITY_REQUIRED, raw_hash=raw_hash, wire=parsed)
    try:
        transaction = dedupe_authority.begin_receipt_transaction(context)
        if not isinstance(transaction, DedupeReceiptTransaction):
            raise ContractError("dedupe_authority_invalid_result", "begin must return DedupeReceiptTransaction")
        with transaction:
            return _process_validated_wire_event_v1_receipt(raw_hash, parsed, context, transaction)
    except Exception as exc:
        return _processing_result(
            context, status="ERROR", reason=_dedupe_reason(exc),
            raw_hash=raw_hash, wire=parsed, detail=type(exc).__name__,
        )


def _verification_failure(action: str, reason: str, context: _TrustedReceiptContextV1 | None = None, transaction: DedupeReceiptTransaction | None = None, canonical_hash: str | None = None) -> CanonicalVerificationResultV1:
    return CanonicalVerificationResultV1(False, action, reason, context.receipt_id if context else None, context.raw_content_hash if context else None, canonical_hash, transaction.transaction_id if transaction else None, transaction.generation if transaction else None, None, "NONE")


def verify_and_authorize_canonical_event_v1(canonical_document: dict | CanonicalEventV1Document, raw_bytes: bytes, context: _TrustedReceiptContextV1, transaction: DedupeReceiptTransaction, intended_action: str) -> CanonicalVerificationResultV1:
    if intended_action not in _ACTIONS:
        return _verification_failure(intended_action, "UNKNOWN_INTENDED_ACTION", context, transaction)
    try:
        if not isinstance(context, _TrustedReceiptContextV1):
            raise ContractError("trusted_receipt_context_required", "point-of-use verification requires receipt context")
        transaction.assert_current_context(context)
        if transaction.closed or not transaction.committed:
            raise ContractError("dedupe_transaction_not_current", "transaction must be open and committed")
        actual = canonical_document.document if isinstance(canonical_document, CanonicalEventV1Document) else deepcopy(canonical_document)
        validate_canonical_event_v1_shape(actual)
        raw_hash = _bounded_raw_hash(raw_bytes)
        if raw_hash != context.raw_content_hash:
            raise ContractError("trusted_raw_receipt_mismatch", "bytes differ from receipt context")
        wire = _strict_json_object(raw_bytes)
        validate_wire_event_v1_shape(wire)
        decision = transaction.decision
        if not isinstance(decision, DedupeDecision):
            raise ContractError("dedupe_authority_invalid_result", "committed transaction has no canonical decision")
        expected = _build_canonical(wire, context, decision)
        if canonical_json_bytes(actual) != canonical_json_bytes(expected):
            raise ContractError("trusted_document_mismatch", "document differs from point-of-use recomputation")
        validation = expected["validation"]
        eligible = {
            "STATE_MUTATION": validation["state_mutation_allowed"],
            "DISPATCH": validation["dispatch_allowed"],
            "OUTBOX_CREATE": validation["dispatch_allowed"],
            "DOWNSTREAM_HANDOFF": validation["dispatch_allowed"],
            "REPLAY_RELEASE": validation["dispatch_allowed"],
            "AUDIT_ACCEPTANCE": True,
        }[intended_action]
        canonical_hash = expected["canonical_content_hash"]
        if not eligible:
            return _verification_failure(intended_action, "ACTION_NOT_ELIGIBLE", context, transaction, canonical_hash)
        return transaction.issue_authorization(
            action=intended_action,
            canonical_content_hash=canonical_hash,
            raw_content_hash=raw_hash,
        )
    except Exception as exc:
        canonical_hash = None
        if isinstance(canonical_document, CanonicalEventV1Document):
            canonical_hash = canonical_document.document.get("canonical_content_hash")
        elif isinstance(canonical_document, Mapping):
            canonical_hash = canonical_document.get("canonical_content_hash")
        return _verification_failure(intended_action, exc.code.upper() if isinstance(exc, ContractError) else "POINT_OF_USE_VERIFICATION_FAILED", context if isinstance(context, _TrustedReceiptContextV1) else None, transaction, canonical_hash)


def consume_point_of_use_authorization(result: CanonicalVerificationResultV1, transaction: DedupeReceiptTransaction, intended_action: str) -> None:
    transaction.consume_authorization(result, intended_action)


def canonicalize_wire_event_v1(*args, **kwargs):
    raise ContractError("mapping_constructor_disabled", "use receipt processing with exact bytes")


def validate_wire_event_v1(document: dict) -> dict:
    return validate_wire_event_v1_shape(document)


def validate_canonical_event_v1(document: dict) -> CanonicalEventV1Document:
    return validate_canonical_event_v1_shape(document)


def validate_legacy_event_v0_2(document: dict) -> dict:
    return validate_contract(EVENT_SCHEMA_V0_2, document)


def read_project_a_event(document: dict, *, legacy_receipt_metadata: dict | None = None, **authority_arguments) -> dict:
    if not isinstance(document, dict):
        raise ContractError("document_type", "document must be a JSON object")
    if authority_arguments:
        raise ContractError("generic_reader_cannot_authorize", "use point-of-use verification service")
    if legacy_receipt_metadata is not None:
        raise ContractError("legacy_trusted_migration_disabled", "caller metadata cannot establish LEGACY_TRUSTED")
    version, family = document.get("schema_version"), document.get("contract_family")
    if version == "0.2" and family is None:
        validate_legacy_event_v0_2(document)
        unsupported = document["event_type"] in _UNSUPPORTED_V02_LIFECYCLE
        return {"contract": EVENT_SCHEMA_V0_2, "status": "UNSUPPORTED" if unsupported else "SHAPE_VALID", "reason_code": UNSUPPORTED_LIFECYCLE_V02 if unsupported else "LEGACY_V02_UNVERIFIED", "state_mutation_allowed": False, "dispatch_allowed": False, "receipt_provenance": "LEGACY_UNVERIFIED", "trusted_received_at": None, "legacy_declared_received_at": document["received_at"], "document": document}
    if version == "1.0" and family == "PROJECT_A_WIRE_EVENT":
        validate_wire_event_v1_shape(document)
        return {"contract": PROJECT_A_WIRE_EVENT_V1, "status": "SHAPE_VALID", "authority": "NONE", "document": ParsedWireEventV1(document)}
    if version == "1.0" and family == "PROJECT_A_CANONICAL_EVENT":
        shaped = validate_canonical_event_v1_shape(document)
        return {"contract": PROJECT_A_CANONICAL_EVENT_V1, "status": "SHAPE_VALID", "authority": "NONE", "document": shaped}
    raise ContractError("unknown_event_contract", "unknown or ambiguous event family/version")
