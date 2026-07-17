"""Durable Session 2 authority adapter for the accepted Event V1 readers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from typing import Any

from contracts import (
    CanonicalVerificationResultV1,
    ContractError,
    DedupeAuthority,
    DedupeDecision,
    DedupeReceiptTransaction,
    consume_point_of_use_authorization,
    parse_wire_event_v1_bytes,
    verify_and_authorize_canonical_event_v1,
)
from contracts._trusted_ingress import _TrustedReceiptContextV1
from contracts.event_v1 import DedupeAuthorityUnavailable, DedupeCommitUnknown, _build_canonical
from contracts.validation import canonical_json

from .config import ProjectAConfig
from .database import ProjectADatabase
from .state import transition

DESTINATION = "SESSION_3_PHASE_1_8"
PURPOSE = "COMPILE_ANALYSIS_REQUEST"


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _bounded(value: str | None, limit: int = 500) -> str:
    return (value or "").replace("\x00", "")[:limit]


class SQLiteDedupeAuthority(DedupeAuthority):
    """One production authority instance per durably stored raw receipt."""

    def __init__(
        self,
        db: ProjectADatabase,
        config: ProjectAConfig,
        *,
        ingest_id: str,
        raw_bytes: bytes,
        recorded_at: str,
        replay_operation_id: str | None = None,
        fail_at: str | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.ingest_id = ingest_id
        self.raw_bytes = raw_bytes
        self.recorded_at = recorded_at
        self.replay_operation_id = replay_operation_id
        self.fail_at = fail_at

    @property
    def durable(self) -> bool:
        return True

    def begin_receipt_transaction(
        self, context: _TrustedReceiptContextV1
    ) -> DedupeReceiptTransaction:
        if self.fail_at == "begin":
            raise DedupeAuthorityUnavailable("injected durable authority unavailability")
        if (
            not isinstance(context, _TrustedReceiptContextV1)
            or context.context_kind != "PRODUCTION"
            or context.receipt_id != self.ingest_id
        ):
            raise ContractError(
                "trusted_receipt_context_required",
                "Session 2 authority requires its production receipt context",
            )
        transaction_id = "tx_" + uuid.uuid4().hex
        with self.db.transaction(immediate=True) as conn:
            receipt = conn.execute(
                "SELECT body_hash,raw_complete FROM project_a_raw_receipts WHERE ingest_id=?",
                (self.ingest_id,),
            ).fetchone()
            if (
                receipt is None
                or receipt["body_hash"] != context.raw_content_hash
                or receipt["raw_complete"] != 1
            ):
                raise ContractError(
                    "trusted_raw_receipt_mismatch",
                    "durable raw receipt does not match the production context",
                )
            conn.execute(
                "INSERT INTO project_a_receipt_transactions("
                "transaction_id,ingest_id,receipt_id,generation,status,claimed_at"
                ") VALUES(?,?,?,1,'CLAIMED',?)",
                (transaction_id, self.ingest_id, context.receipt_id, self.recorded_at),
            )
        return SQLiteReceiptTransaction(self, context, transaction_id)


class SQLiteReceiptTransaction(DedupeReceiptTransaction):
    def __init__(
        self,
        authority: SQLiteDedupeAuthority,
        context: _TrustedReceiptContextV1,
        transaction_id: str,
    ) -> None:
        self.authority = authority
        self._context = context
        self._transaction_id = transaction_id
        self._generation = 1
        self._committed = False
        self._closed = False
        self._rolled_back = False
        self._receipt_recorded = False
        self._exact_key: tuple[str, str] | None = None
        self._semantic_hash: str | None = None
        self._exact_duplicate: bool | None = None
        self._semantic_duplicate: bool | None = None
        self._prior_ids: tuple[str, ...] = ()
        self._decision: DedupeDecision | None = None
        self._canonical: dict[str, Any] | None = None
        self._state_mutation_performed = False
        self._outbox_created = False
        self._authorization_lock = threading.RLock()
        self._authorization_states: dict[tuple[int, str], dict[str, Any]] = {}
        self._conn = self.authority.db.connect()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except Exception:
            self._conn.close()
            self._set_claim_status("ABANDONED", "begin transaction failed")
            raise

    @property
    def transaction_id(self) -> str:
        return self._transaction_id

    @property
    def generation(self) -> int:
        with self._authorization_lock:
            return self._generation

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def receipt_context(self) -> _TrustedReceiptContextV1:
        return self._context

    @property
    def decision(self) -> DedupeDecision | None:
        return self._decision

    @property
    def prior_canonical_event_ids(self) -> tuple[str, ...]:
        return self._prior_ids

    @property
    def canonical_document(self) -> dict[str, Any] | None:
        return json.loads(canonical_json(self._canonical)) if self._canonical is not None else None

    def _active(self) -> None:
        if self._closed:
            raise ContractError("dedupe_transaction_closed", "transaction is closed")
        if self._rolled_back:
            raise ContractError("dedupe_transaction_rolled_back", "transaction was rolled back")

    def assert_current_context(self, context: _TrustedReceiptContextV1) -> None:
        self._active()
        if context is not self._context:
            raise ContractError(
                "dedupe_transaction_context_mismatch",
                "transaction is bound to another receipt context",
            )

    def record_receipt(self, raw_content_hash: str) -> None:
        self._active()
        if self._receipt_recorded:
            raise ContractError("dedupe_receipt_already_recorded", "record_receipt called twice")
        row = self._conn.execute(
            "SELECT body_hash,raw_body,raw_complete FROM project_a_raw_receipts WHERE ingest_id=?",
            (self.authority.ingest_id,),
        ).fetchone()
        if (
            row is None
            or row["body_hash"] != raw_content_hash
            or bytes(row["raw_body"]) != self.authority.raw_bytes
            or row["raw_complete"] != 1
        ):
            raise ContractError(
                "trusted_raw_receipt_mismatch", "recorded raw bytes differ from receipt context"
            )
        self._receipt_recorded = True

    def reserve_exact(self, transport_identity: str, canonical_content_hash: str) -> bool:
        self._active()
        if not self._receipt_recorded or self._exact_key is not None:
            raise ContractError(
                "dedupe_transaction_order", "exact reserve requires one receipt record"
            )
        self._exact_key = (transport_identity, canonical_content_hash)
        row = self._conn.execute(
            "SELECT d.canonical_event_id FROM project_a_exact_dedupe d "
            "JOIN project_a_receipt_transactions t ON t.transaction_id=d.transaction_id "
            "WHERE d.transport_identity=? AND d.canonical_content_hash=? "
            "AND t.status IN ('CONFIRMED','COMMITTED_UNCONFIRMED','COMMIT_UNKNOWN')",
            self._exact_key,
        ).fetchone()
        self._exact_duplicate = row is not None
        if row:
            self._prior_ids = (row["canonical_event_id"],)
        return self._exact_duplicate

    def reserve_semantic(self, semantic_evidence_hash: str) -> bool:
        self._active()
        if self._exact_key is None or self._semantic_hash is not None:
            raise ContractError(
                "dedupe_transaction_order", "semantic reserve follows exact reserve"
            )
        self._semantic_hash = semantic_evidence_hash
        rows = self._conn.execute(
            "SELECT d.canonical_event_id FROM project_a_semantic_dedupe d "
            "JOIN project_a_receipt_transactions t ON t.transaction_id=d.transaction_id "
            "WHERE d.semantic_evidence_hash=? "
            "AND t.status IN ('CONFIRMED','COMMITTED_UNCONFIRMED','COMMIT_UNKNOWN') "
            "ORDER BY d.created_at,d.canonical_event_id LIMIT 16",
            (semantic_evidence_hash,),
        ).fetchall()
        ids = list(self._prior_ids)
        ids.extend(row["canonical_event_id"] for row in rows)
        self._prior_ids = tuple(dict.fromkeys(ids))
        self._semantic_duplicate = bool(rows)
        return self._semantic_duplicate

    def persist_decision(
        self,
        *,
        decision: DedupeDecision | None,
        canonical_event_id: str | None,
        processing_status: str,
        reason_code: str,
        state_mutation_allowed: bool,
        dispatch_allowed: bool,
    ) -> None:
        self._active()
        if (
            not self._receipt_recorded
            or self._exact_duplicate is None
            or self._semantic_duplicate is None
            or self._decision is not None
            or decision
            != DedupeDecision(
                self._exact_duplicate, self._semantic_duplicate, self._prior_ids
            )
            or canonical_event_id is None
        ):
            raise ContractError(
                "dedupe_authority_invalid_result", "decision differs from durable reservations"
            )
        if self.authority.fail_at == "persist":
            raise sqlite3.OperationalError("injected durable persist failure")
        self._decision = decision
        self._canonical = _build_canonical(
            parse_wire_event_v1_bytes(self.authority.raw_bytes).document,
            self._context,
            decision,
        )
        if self._canonical["canonical_event_id"] != canonical_event_id:
            raise ContractError(
                "dedupe_authority_invalid_result", "canonical event identity mismatch"
            )
        validation = self._canonical["validation"]
        if (
            validation["status"] != processing_status
            or validation["reason_codes"][0] != reason_code
            or validation["state_mutation_allowed"] != state_mutation_allowed
            or validation["dispatch_allowed"] != dispatch_allowed
        ):
            raise ContractError(
                "dedupe_authority_invalid_result", "canonical eligibility mismatch"
            )
        self._persist_unit()

    def _persist_unit(self) -> None:
        assert self._canonical is not None
        assert self._decision is not None
        assert self._exact_key is not None
        assert self._semantic_hash is not None
        canonical = self._canonical
        wire = canonical["wire_event"]
        canonical_id = canonical["canonical_event_id"]
        setup_id = canonical["setup_id"]
        now_text = self.authority.recorded_at

        if not self._decision.exact_receipt_duplicate:
            self._conn.execute(
                "INSERT INTO project_a_exact_dedupe("
                "transport_identity,canonical_content_hash,canonical_event_id,ingest_id,"
                "transaction_id,created_at) VALUES(?,?,?,?,?,?)",
                (
                    self._exact_key[0],
                    self._exact_key[1],
                    canonical_id,
                    self.authority.ingest_id,
                    self._transaction_id,
                    now_text,
                ),
            )
        if not self._decision.semantic_evidence_duplicate:
            self._conn.execute(
                "INSERT INTO project_a_semantic_dedupe("
                "semantic_evidence_hash,canonical_event_id,ingest_id,transaction_id,created_at"
                ") VALUES(?,?,?,?,?)",
                (
                    self._semantic_hash,
                    canonical_id,
                    self.authority.ingest_id,
                    self._transaction_id,
                    now_text,
                ),
            )
        if not self._decision.exact_receipt_duplicate:
            self._conn.execute(
                "INSERT INTO project_a_canonical_events("
                "event_id,ingest_id,setup_id,correlation_id,causation_id,event_class,event_type,"
                "occurred_at,canonical_hash,evidence_fingerprint,canonical_json,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    canonical_id,
                    self.authority.ingest_id,
                    setup_id,
                    canonical["correlation_id"],
                    canonical["causation_id"],
                    wire["event_class"],
                    wire["event_type"],
                    wire["occurred_at"],
                    canonical["canonical_content_hash"],
                    canonical["semantic_evidence_hash"],
                    canonical_json(canonical),
                    now_text,
                ),
            )

        runtime_status = canonical["validation"]["status"]
        runtime_reason = canonical["validation"]["reason_codes"][0]
        transition_code = runtime_reason
        dispatch_key = None
        if runtime_status == "ACCEPTED":
            current = self._current_setup(setup_id)
            if (
                current is not None
                and wire["occurred_at"] < current["occurred_at"]
            ):
                runtime_status = "REJECTED"
                runtime_reason = "OUT_OF_ORDER_EVENT"
            else:
                state_decision = transition(
                    current["lifecycle_state"] if current else None,
                    wire["event_class"],
                    wire["event_type"],
                )
                if (
                    wire["event_class"] == "LIFECYCLE"
                    and current is None
                    and wire["event_type"] in {"SETUP_INVALIDATED", "SETUP_EXPIRED"}
                ):
                    state_decision = type(state_decision)(
                        True,
                        wire["event_type"],
                        True,
                        False,
                        wire["event_type"],
                    )
                transition_code = state_decision.reason_code
                if not state_decision.allowed:
                    runtime_status = "REJECTED"
                    runtime_reason = "ILLEGAL_LIFECYCLE_TRANSITION"
                elif (
                    state_decision.persist_state
                    and setup_id
                    and canonical["validation"]["state_mutation_allowed"]
                ):
                    version = int(current["version"]) + 1 if current else 1
                    self._conn.execute(
                        "INSERT INTO project_a_setup_state_v1("
                        "setup_id,transaction_id,symbol,lifecycle_state,hypothesis,path,"
                        "canonical_event_id,occurred_at,semantic_evidence_hash,version,recorded_at"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            setup_id,
                            self._transaction_id,
                            wire["symbol"],
                            state_decision.next_state,
                            wire["hypothesis"],
                            wire["path"],
                            canonical_id,
                            wire["occurred_at"],
                            canonical["semantic_evidence_hash"],
                            version,
                            now_text,
                        ),
                    )
                    self._state_mutation_performed = True
                if (
                    runtime_status == "ACCEPTED"
                    and state_decision.create_outbox
                    and canonical["validation"]["dispatch_allowed"]
                ):
                    dispatch_key = _digest(
                        canonical_json(
                            {
                                "destination": DESTINATION,
                                "purpose": PURPOSE,
                                "setup_id": setup_id,
                                "semantic_evidence_hash": canonical[
                                    "semantic_evidence_hash"
                                ],
                            }
                        ).encode("utf-8")
                    )
                    payload = canonical_json(
                        {
                            "outbox_schema_version": "1.0",
                            "destination": DESTINATION,
                            "purpose": PURPOSE,
                            "dispatch_key": dispatch_key,
                            "canonical_event": canonical,
                        }
                    )
                    self._conn.execute(
                        "INSERT INTO project_a_outbox("
                        "outbox_id,dispatch_key,destination,purpose,event_id,setup_id,payload_json,"
                        "status,available_at,created_at,updated_at,transaction_id,"
                        "release_authorized"
                        ") VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?,?,0)",
                        (
                            "out_" + uuid.uuid4().hex,
                            dispatch_key,
                            DESTINATION,
                            PURPOSE,
                            canonical_id,
                            setup_id,
                            payload,
                            now_text,
                            now_text,
                            now_text,
                            self._transaction_id,
                        ),
                    )
                    self._outbox_created = True

        duplicate_of = None
        if self._prior_ids:
            row = self._conn.execute(
                "SELECT ingest_id FROM project_a_canonical_events WHERE event_id=?",
                (self._prior_ids[0],),
            ).fetchone()
            duplicate_of = row["ingest_id"] if row else None
        outcome_reason = (
            transition_code if runtime_status == "ACCEPTED" else runtime_reason
        )
        self._conn.execute(
            "INSERT INTO project_a_receipt_processing("
            "ingest_id,recorded_at,status,schema_version,event_id,setup_id,error_code,detail,"
            "duplicate_of_ingest_id,replay_operation_id"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                self.authority.ingest_id,
                now_text,
                runtime_status,
                "1.0",
                canonical_id,
                setup_id,
                outcome_reason,
                _bounded(
                    "trusted Event V1 decision"
                    if dispatch_key is None
                    else f"trusted Event V1 decision; dispatch_key={dispatch_key}"
                ),
                duplicate_of,
                self.authority.replay_operation_id,
            ),
        )
        self._conn.execute(
            "UPDATE project_a_receipt_transactions SET canonical_event_id=?,"
            "processing_status=?,reason_code=?,state_mutation_allowed=?,dispatch_allowed=? "
            "WHERE transaction_id=?",
            (
                canonical_id,
                runtime_status,
                outcome_reason,
                int(self._state_mutation_performed),
                int(self._outbox_created),
                self._transaction_id,
            ),
        )

    def _current_setup(self, setup_id: str | None):
        if setup_id is None:
            return None
        return self._conn.execute(
            "SELECT s.* FROM project_a_setup_state_v1 s "
            "JOIN project_a_receipt_transactions t "
            "ON t.transaction_id=s.transaction_id "
            "WHERE s.setup_id=? AND t.status='CONFIRMED' "
            "ORDER BY s.version DESC,s.recorded_at DESC LIMIT 1",
            (setup_id,),
        ).fetchone()

    def commit(self) -> None:
        self._active()
        if self._decision is None or self._canonical is None or self._committed:
            raise ContractError(
                "dedupe_transaction_order", "persist_decision precedes one commit"
            )
        if self.authority.fail_at == "commit":
            raise sqlite3.OperationalError("injected durable commit failure")
        self._conn.execute(
            "UPDATE project_a_receipt_transactions SET status='COMMITTED_UNCONFIRMED',"
            "committed_at=? WHERE transaction_id=?",
            (self.authority.recorded_at, self._transaction_id),
        )
        self._conn.execute("COMMIT")
        self._conn.close()
        self._committed = True
        if self.authority.fail_at == "commit_unknown":
            self._set_claim_status("COMMIT_UNKNOWN", "injected commit outcome unknown")
            raise DedupeCommitUnknown("durable commit outcome intentionally treated as unknown")

    def confirm_point_of_use(self) -> None:
        self._active()
        if not self._committed:
            raise ContractError(
                "dedupe_transaction_not_committed", "confirmation requires durable commit"
            )
        if self.authority.fail_at == "confirm":
            self._set_claim_status("COMMIT_UNKNOWN", "confirmation failed")
            raise DedupeCommitUnknown("post-commit confirmation failed")
        with self.authority.db.transaction(immediate=True) as conn:
            updated = conn.execute(
                "UPDATE project_a_receipt_transactions SET status='CONFIRMED',confirmed_at=?,"
                "last_error=NULL WHERE transaction_id=? AND status='COMMITTED_UNCONFIRMED'",
                (
                    self.authority.recorded_at,
                    self._transaction_id,
                ),
            ).rowcount
            if updated != 1:
                raise DedupeCommitUnknown("transaction is not confirmable")
            conn.execute(
                "UPDATE project_a_outbox SET release_authorized=1,updated_at=? "
                "WHERE transaction_id=? AND release_authorized=0",
                (self.authority.recorded_at, self._transaction_id),
            )

    def mark_commit_unknown(self, detail: str) -> None:
        self._set_claim_status("COMMIT_UNKNOWN", detail)

    def rollback(self) -> None:
        with self._authorization_lock:
            if self._closed:
                raise ContractError("dedupe_transaction_closed", "transaction is closed")
            if self._committed:
                raise ContractError(
                    "dedupe_committed_no_rollback", "committed transaction cannot roll back"
                )
            if not self._rolled_back:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                self._conn.close()
                self._rolled_back = True
                self._invalidate_pending_authorizations_locked()
                self._set_claim_status("ROLLED_BACK", "transaction rolled back")

    def close(self) -> None:
        with self._authorization_lock:
            if self._closed:
                raise ContractError("dedupe_transaction_closed", "transaction is already closed")
            if not self._committed and not self._rolled_back:
                self.rollback()
            self._invalidate_pending_authorizations_locked()
            self._closed = True

    def issue_authorization(
        self, *, action: str, canonical_content_hash: str, raw_content_hash: str
    ) -> CanonicalVerificationResultV1:
        with self._authorization_lock:
            self._active()
            if not self._committed:
                raise ContractError(
                    "dedupe_transaction_not_committed", "authorization requires commit"
                )
            key = (self._generation, action)
            existing = self._authorization_states.get(key)
            if existing is not None:
                code = (
                    "authorization_already_consumed"
                    if existing["state"] == "CONSUMED"
                    else "authorization_already_issued"
                )
                raise ContractError(code, "authorization already exists for generation/action")
            result = CanonicalVerificationResultV1(
                True,
                action,
                "POINT_OF_USE_VERIFIED",
                self._context.receipt_id,
                raw_content_hash,
                canonical_content_hash,
                self._transaction_id,
                self._generation,
                "auth_" + uuid.uuid4().hex,
                "CURRENT_TRANSACTION",
            )
            self._authorization_states[key] = {
                "state": "PENDING",
                "result": result,
            }
            return result

    def consume_authorization(
        self, result: CanonicalVerificationResultV1, intended_action: str
    ) -> None:
        with self._authorization_lock:
            self._active()
            if not self._committed:
                raise ContractError(
                    "dedupe_transaction_not_committed", "consumer requires commit"
                )
            if result.transaction_generation != self._generation:
                raise ContractError(
                    "authorization_generation_stale", "authorization generation is stale"
                )
            key = (self._generation, intended_action)
            existing = self._authorization_states.get(key)
            if existing is None or existing["result"] != result:
                raise ContractError(
                    "authorization_invalidated", "authorization is not current"
                )
            if existing["state"] == "CONSUMED":
                raise ContractError(
                    "authorization_already_consumed", "authorization was already consumed"
                )
            if (
                not result.authorized
                or result.intended_action != intended_action
                or result.transaction_id != self._transaction_id
                or result.receipt_id != self._context.receipt_id
                or result.raw_content_hash != self._context.raw_content_hash
            ):
                raise ContractError(
                    "authorization_invalidated", "authorization binding mismatch"
                )
            existing["state"] = "CONSUMED"

    def advance_generation(self) -> int:
        with self._authorization_lock:
            self._active()
            if not self._committed:
                raise ContractError(
                    "dedupe_transaction_not_committed", "generation advance requires commit"
                )
            if any(
                key[0] == self._generation and value["state"] == "CONSUMED"
                for key, value in self._authorization_states.items()
            ):
                raise ContractError(
                    "authorization_already_consumed",
                    "generation cannot advance after consumption",
                )
            self._invalidate_pending_authorizations_locked()
            self._generation += 1
            return self._generation

    def _invalidate_pending_authorizations_locked(self) -> None:
        for value in self._authorization_states.values():
            if value["state"] == "PENDING":
                value["state"] = "INVALIDATED"

    def _set_claim_status(self, status: str, detail: str) -> None:
        try:
            with self.authority.db.transaction(immediate=True) as conn:
                fields = "status=?,last_error=?"
                values: list[Any] = [status, _bounded(detail)]
                if status == "ABANDONED":
                    fields += ",abandoned_at=?"
                    values.append(self.authority.recorded_at)
                values.append(self._transaction_id)
                conn.execute(
                    f"UPDATE project_a_receipt_transactions SET {fields} "
                    "WHERE transaction_id=? AND status<>'CONFIRMED'",
                    values,
                )
        except sqlite3.Error:
            pass


def authorize_and_confirm(
    transaction: SQLiteReceiptTransaction,
    raw_bytes: bytes,
    canonical_document,
) -> None:
    """Bind the committed canonical result before any outbox becomes claimable."""
    canonical = canonical_document.document
    actions = ["AUDIT_ACCEPTANCE"]
    if transaction._state_mutation_performed:
        actions.append("STATE_MUTATION")
    if transaction._outbox_created:
        actions.append("OUTBOX_CREATE")
    for action in actions:
        authorization = verify_and_authorize_canonical_event_v1(
            canonical_document,
            raw_bytes,
            transaction.receipt_context,
            transaction,
            action,
        )
        if not authorization.authorized:
            transaction.mark_commit_unknown(authorization.reason_code)
            raise DedupeCommitUnknown(
                f"point-of-use authorization failed: {authorization.reason_code}"
            )
        consume_point_of_use_authorization(authorization, transaction, action)
    transaction.confirm_point_of_use()


def recover_abandoned_transactions(
    db: ProjectADatabase, cutoff: str, now_text: str
) -> int:
    """Mark stale ingress claims fail-closed; their outboxes remain unreleasable."""
    with db.transaction(immediate=True) as conn:
        rows = conn.execute(
            "SELECT transaction_id FROM project_a_receipt_transactions "
            "WHERE status IN ('CLAIMED','COMMITTED_UNCONFIRMED') AND claimed_at<?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE project_a_receipt_transactions SET status='ABANDONED',"
                "abandoned_at=?,last_error='ABANDONED_INGRESS_CLAIM' "
                "WHERE transaction_id=?",
                (now_text, row["transaction_id"]),
            )
        return len(rows)


__all__ = [
    "SQLiteDedupeAuthority",
    "SQLiteReceiptTransaction",
    "authorize_and_confirm",
    "recover_abandoned_transactions",
]
