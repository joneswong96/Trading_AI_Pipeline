"""Secret-free OpenClaw template rendering and security validation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from .errors import FailureCode, TechnicalFailure

_PLACEHOLDER = re.compile(r"^\$\{([A-Z0-9_]+)\}$")
REQUIRED_ENV = {
    "PROJECT_A_REVIEWER_WORKSPACE",
    "PROJECT_A_REVIEWER_AGENT_DIR",
    "PROJECT_A_REVIEWER_MODEL",
    "PROJECT_A_TELEGRAM_USER_ID",
}


def _substitute(value, environment: Mapping[str, str]):
    if isinstance(value, dict):
        return {key: _substitute(child, environment) for key, child in value.items()}
    if isinstance(value, list):
        return [_substitute(child, environment) for child in value]
    if isinstance(value, str):
        match = _PLACEHOLDER.fullmatch(value)
        if match:
            name = match.group(1)
            replacement = environment.get(name, "")
            if not replacement:
                raise TechnicalFailure(FailureCode.CONFIG_INVALID, f"missing required value {name}")
            return replacement
    return value


def load_and_render_template(path: Path, environment: Mapping[str, str]) -> dict:
    missing = sorted(name for name in REQUIRED_ENV if not environment.get(name))
    if missing:
        raise TechnicalFailure(
            FailureCode.CONFIG_INVALID,
            "missing required values: " + ", ".join(missing),
        )
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    rendered = _substitute(document, environment)
    validate_security_posture(rendered)
    return rendered


def validate_security_posture(config: dict) -> None:
    try:
        agent = next(item for item in config["agents"]["list"] if item["id"] == "project-a-reviewer")
        sandbox = agent["sandbox"]
        tools = agent["tools"]
        telegram = config["channels"]["telegram"]
    except (KeyError, StopIteration, TypeError) as exc:
        raise TechnicalFailure(FailureCode.CONFIG_INVALID, "required reviewer config is absent") from exc
    failures: list[str] = []
    if sandbox.get("mode") != "all" or sandbox.get("scope") != "session":
        failures.append("sandbox must be all/session")
    if sandbox.get("workspaceAccess") not in {"none", "ro"}:
        failures.append("workspace access must be none or ro")
    docker = sandbox.get("docker", {})
    if docker.get("network") != "none" or docker.get("readOnlyRoot") is not True:
        failures.append("sandbox network/root must be none/read-only")
    if docker.get("capDrop") != ["ALL"]:
        failures.append("all Linux capabilities must be dropped")
    if sandbox.get("browser", {}).get("enabled") is not False:
        failures.append("sandbox browser must be disabled")
    denied = set(tools.get("deny", []))
    required_denies = {
        "group:runtime",
        "group:fs",
        "group:web",
        "group:ui",
        "group:automation",
        "group:messaging",
        "group:nodes",
        "group:sessions",
        "group:plugins",
        "group:agents",
        "group:media",
        "group:openclaw",
        "browser",
        "exec",
        "process",
        "read",
        "write",
        "edit",
        "apply_patch",
    }
    if not required_denies <= denied:
        failures.append("required tool denies are missing")
    if tools.get("elevated", {}).get("enabled") is not False:
        failures.append("elevated tools must be disabled")
    model = agent.get("model", {})
    if not isinstance(model, dict) or model.get("fallbacks") != [] or not model.get("primary"):
        failures.append("one explicit primary model and no fallbacks are required")
    image_model = agent.get("imageModel", {})
    if not isinstance(image_model, dict) or image_model.get("fallbacks") != [] or image_model.get("primary") != model.get("primary"):
        failures.append("image review must use the same explicit model without fallbacks")
    allow_from = telegram.get("allowFrom", [])
    if telegram.get("dmPolicy") != "pairing" or telegram.get("groupPolicy") != "disabled":
        failures.append("Telegram must use pairing and disabled groups")
    if len(allow_from) != 1 or allow_from[0] == "*" or not str(allow_from[0]).isdigit():
        failures.append("Telegram requires exactly one numeric user ID")
    if telegram.get("configWrites") is not False:
        failures.append("Telegram config writes must be disabled")
    if config.get("session", {}).get("dmScope") != "per-account-channel-peer":
        failures.append("DM session isolation is required")
    gateway = config.get("gateway", {})
    if gateway.get("bind") != "loopback" or gateway.get("controlUi", {}).get("enabled") is not False:
        failures.append("Gateway must be loopback-only with Control UI disabled")
    if config.get("logging", {}).get("redactSensitive") != "tools":
        failures.append("sensitive tool logging must be redacted")
    if failures:
        raise TechnicalFailure(FailureCode.CONFIG_INVALID, "; ".join(failures))
