"""Deterministic Jones-only Telegram ingress policy (no network calls)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping

from .errors import FailureCode, TechnicalFailure

_REQUEST_ID = r"req_[A-Za-z0-9._:-]{8,120}"
_COMMANDS = {
    "review": re.compile(rf"^/review\s+({_REQUEST_ID})$"),
    "status": re.compile(rf"^/status\s+({_REQUEST_ID})$"),
    "retry": re.compile(rf"^/retry\s+({_REQUEST_ID})$"),
    "cancel": re.compile(rf"^/cancel\s+({_REQUEST_ID})$"),
    "health": re.compile(r"^/health$"),
}


@dataclass(frozen=True)
class AuthorizedCommand:
    name: str
    request_id: str | None
    sender_id: int


class TelegramPolicy:
    def __init__(
        self,
        jones_numeric_user_id: str | int,
        *,
        denial_audit: Callable[[dict], None] | None = None,
    ):
        raw = str(jones_numeric_user_id)
        if not raw.isdigit() or int(raw) <= 0:
            raise TechnicalFailure(
                FailureCode.CONFIG_INVALID,
                "PROJECT_A_TELEGRAM_USER_ID must be a positive numeric ID",
            )
        self.jones_user_id = int(raw)
        self.denial_audit = denial_audit

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "TelegramPolicy":
        value = environment.get("PROJECT_A_TELEGRAM_USER_ID", "")
        if not value:
            raise TechnicalFailure(
                FailureCode.CONFIG_INVALID,
                "PROJECT_A_TELEGRAM_USER_ID is required; Telegram remains disabled",
            )
        return cls(value)

    def _deny(self, update: dict, message: str) -> None:
        raw_message = update.get("message")
        raw_message = raw_message if isinstance(raw_message, dict) else {}
        sender = raw_message.get("from")
        sender = sender.get("id") if isinstance(sender, dict) else None
        chat = raw_message.get("chat")
        chat_type = chat.get("type") if isinstance(chat, dict) else None
        if self.denial_audit is not None:
            self.denial_audit(
                {
                    "event": "TELEGRAM_DENIED",
                    "sender_id": sender if isinstance(sender, int) else None,
                    "chat_type": chat_type if isinstance(chat_type, str) else None,
                    "reason": message,
                }
            )
        raise TechnicalFailure(FailureCode.CONFIG_INVALID, message)

    def authorize(self, update: dict) -> AuthorizedCommand:
        message = update.get("message")
        if not isinstance(message, dict):
            self._deny(update, "channel/non-message update denied")
        if message.get("chat", {}).get("type") != "private":
            self._deny(update, "group/channel Telegram input denied")
        sender = message.get("from", {}).get("id")
        if sender != self.jones_user_id:
            self._deny(update, "unknown Telegram user denied")
        text = message.get("text")
        if not isinstance(text, str) or len(text.encode("utf-8")) > 512:
            self._deny(update, "Telegram command text denied")
        for name, pattern in _COMMANDS.items():
            match = pattern.fullmatch(text.strip())
            if match:
                request_id = match.group(1) if match.lastindex else None
                return AuthorizedCommand(name, request_id, sender)
        self._deny(
            update,
            "free text, paths, pasted bundles, and unsupported commands are denied",
        )
