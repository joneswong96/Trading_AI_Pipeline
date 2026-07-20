"""Deterministic, offline-only Project A Numeric Market State V1.

This module deliberately has no network, provider, database, writer, broker, or
runtime wiring.  Callers provide versioned producer JSON and, if persistence is
needed for an offline test/replay, an explicit path to :meth:`save_history`.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping


NUMERIC_STATE_SCHEMA = "project_a.numeric_market_state/1.0"
LIQUIDITY_EVENT_SCHEMA = "project_a.liquidity_event/1.0"
EXPANSION_EVENT_SCHEMA = "project_a.expansion_event/1.0"
RENKO_EVENT_SCHEMA = "project_a.renko_event/1.0"
LIQUIDITY_IDENTITY_SCHEMA = "project_a.liquidity_level_identity/1.0"
DERIVED_DECIMAL_PRECISION = 50

_SCHEMA_FAMILY = {
    LIQUIDITY_EVENT_SCHEMA: "LIQUIDITY",
    EXPANSION_EVENT_SCHEMA: "EXPANSION",
    RENKO_EVENT_SCHEMA: "RENKO",
}
RAW_PRODUCER_ALLOWLIST = {
    (LIQUIDITY_EVENT_SCHEMA, "LIQ_V2"): "9",
    (EXPANSION_EVENT_SCHEMA, "EXP_V3"): "5",
    (EXPANSION_EVENT_SCHEMA, "EXP_SCANNER"): "6",
    (RENKO_EVENT_SCHEMA, "RENKO_V3_SNIPER"): "1",
}
_EVENTS = {
    "LIQUIDITY": {
        "LIQ_APPROACH",
        "LIQ_TOUCH",
        "LIQ_REJECT",
        "LIQ_BREAK",
        "LIQ_INVALIDATED",
    },
    "EXPANSION": {"EXP_UP", "EXP_DOWN", "EXP_QUALITY_UPDATE", "EXP_TOO_EXTENDED"},
    "RENKO": {"RENKO_E1", "RENKO_E2", "RENKO_MAIN", "RENKO_FIRE", "RENKO_RESET", "RENKO_INVALIDATED"},
}
_FRESHNESS = {
    "FRESH",
    "AGING",
    "STALE",
    "MARKET_CLOSED",
    "MISSING",
    "CLOCK_INVALID",
    "SOURCE_UNAVAILABLE",
    "PROVISIONAL",
}
_LIQ_LIFECYCLE_FOR_EVENT = {
    "LIQ_APPROACH": "APPROACH",
    "LIQ_TOUCH": "HIT",
    "LIQ_REJECT": "REJECT",
    "LIQ_BREAK": "BREAK",
    "LIQ_INVALIDATED": "INVALIDATED",
}
_ACTIVE_LIFECYCLES = {"IDLE", "APPROACH", "HIT"}
_TERMINAL_LIFECYCLES = {"REJECT", "BREAK", "INVALIDATED", "EXPIRED", "REMOVED", "STALE", "SOURCE_UNAVAILABLE"}
_RENKO_STAGE = {
    "RENKO_E1": "E1",
    "RENKO_E2": "E2",
    "RENKO_MAIN": "MAIN",
    "RENKO_FIRE": "FIRE",
    "RENKO_RESET": "RESET",
    "RENKO_INVALIDATED": "INVALIDATED",
}
_RENKO_RANK = {"NONE": 0, "E1": 1, "E2": 2, "MAIN": 3, "FIRE": 4}
_ZONE_RANK = {"NEAR_TOUCH": 0, "APPROACH": 1, "FAR": 2}
_GRADE_RANK = {"PRIME": 0, "VALID": 1}
_FORBIDDEN_FIELDS = {"price", "dir", "trade_direction", "entry_price", "stop_loss", "take_profit", "order"}
_FAMILY_CONFLICTING_FIELDS = {
    "LIQUIDITY": {"direction", "signal_price", "stage"},
    "EXPANSION": {"side", "level_price", "signal_price", "stage", "lifecycle"},
    "RENKO": {"side", "level_price", "market_price", "lifecycle", "grade"},
}


class NumericStateError(ValueError):
    """Stable fail-closed validation error."""

    def __init__(self, code: str, field: str, message: str):
        super().__init__(f"{code}:{field}: {message}")
        self.code = code
        self.field = field


def _fail(code: str, field: str, message: str) -> None:
    raise NumericStateError(code, field, message)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        _fail("NON_FINITE_NUMBER", "number", "number must be finite")
    if value == 0:
        return "0"
    # ``normalize`` consults the ambient Decimal context and may round.  Fixed
    # point formatting preserves the exact coefficient independently of it.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _divide_decimal(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Pinned deterministic division for derived, non-identity measurements."""

    with localcontext() as context:
        context.prec = DERIVED_DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return numerator / denominator


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        return _format_timestamp(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float):
        _fail("BINARY_FLOAT_FORBIDDEN", "number", "use a JSON number, decimal string, or Decimal")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    _fail("UNSUPPORTED_VALUE", "payload", f"unsupported value type {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return pinned UTF-8 canonical JSON (sorted keys, compact, no ASCII escaping)."""

    return json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_JSON_KEY", key, "duplicate keys are ambiguous")
        result[key] = value
    return result


def _decode_payload(payload: bytes | str | Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, Mapping):
        obj = dict(payload)
        return obj, canonical_json_bytes(obj)
    else:
        _fail("INVALID_PAYLOAD", "payload", "expected UTF-8 JSON or a mapping")
    try:
        text = raw.decode("utf-8", errors="strict")
        obj = json.loads(
            text,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=lambda token: _fail("NON_FINITE_NUMBER", "payload", token),
            object_pairs_hook=_pairs_no_duplicates,
        )
    except NumericStateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("INVALID_JSON", "payload", str(exc))
    if not isinstance(obj, dict):
        _fail("INVALID_PAYLOAD", "payload", "top-level JSON must be an object")
    return obj, bytes(raw)


def _required(obj: Mapping[str, Any], field: str) -> Any:
    if field not in obj or obj[field] is None:
        _fail("MISSING_REQUIRED_FIELD", field, "field is required")
    return obj[field]


def _text(value: Any, field: str, *, upper: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("INVALID_TEXT", field, "must be a non-empty string")
    result = value.strip()
    return result.upper() if upper else result


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail("INVALID_BOOLEAN", field, "must be a JSON boolean")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INVALID_INTEGER", field, "must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        _fail("INTEGER_OUT_OF_RANGE", field, "value is outside the approved range")
    return value


def _decimal(value: Any, field: str, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        _fail("BINARY_FLOAT_FORBIDDEN", field, "use a JSON number, decimal string, or Decimal")
    if not isinstance(value, (str, int, Decimal)):
        _fail("INVALID_DECIMAL", field, "must be a decimal value")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        _fail("INVALID_DECIMAL", field, "invalid decimal value")
    if not result.is_finite():
        _fail("NON_FINITE_NUMBER", field, "must be finite")
    if positive and result <= 0:
        _fail("NUMBER_OUT_OF_RANGE", field, "must be greater than zero")
    if nonnegative and result < 0:
        _fail("NUMBER_OUT_OF_RANGE", field, "must be non-negative")
    return result


def _optional_decimal(
    obj: Mapping[str, Any],
    field: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal | None:
    value = obj.get(field)
    if value is None:
        return None
    return _decimal(value, field, positive=positive, nonnegative=nonnegative)


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            _fail("INVALID_TIMESTAMP", field, "epoch milliseconds must be non-negative")
        try:
            return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)
        except (OverflowError, ValueError):
            _fail("INVALID_TIMESTAMP", field, "epoch milliseconds are outside the supported range")
    text = _text(value, field)
    if not text.endswith("Z"):
        _fail("INVALID_TIMESTAMP", field, "must be UTC RFC 3339 ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        _fail("INVALID_TIMESTAMP", field, "must be UTC RFC 3339")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        _fail("INVALID_TIMESTAMP", field, "must identify UTC")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    text = value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return text.replace(".000000Z", "Z")


def _timeframe(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    aliases = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h", "1d": "1d", "1w": "1w"}
    return aliases.get(text, text)


def _freshness(value: Any, field: str = "freshness_status") -> str:
    result = _text(value, field, upper=True)
    if result not in _FRESHNESS:
        _fail("INVALID_FRESHNESS", field, "unrecognized freshness status")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _source_creation_identity(obj: Mapping[str, Any]) -> Any:
    direct = obj.get("source_creation_identity")
    if direct is not None:
        if isinstance(direct, str):
            return _text(direct, "source_creation_identity")
        if isinstance(direct, Mapping) and direct:
            return _json_value(direct)
        _fail("INVALID_IDENTITY", "source_creation_identity", "must be non-empty text or an object")
    derived: dict[str, Any] = {}
    for field in ("source_family", "source_timeframe", "source_pivot_time", "source_sequence"):
        if obj.get(field) is not None:
            derived[field] = obj[field]
    if not (derived.get("source_pivot_time") is not None or derived.get("source_sequence") is not None):
        _fail("MISSING_IDENTITY", "source_creation_identity", "producer-native creation identity is required")
    if "source_pivot_time" in derived:
        derived["source_pivot_time"] = _format_timestamp(_timestamp(derived["source_pivot_time"], "source_pivot_time"))
    if "source_sequence" in derived:
        derived["source_sequence"] = _integer(derived["source_sequence"], "source_sequence")
    if "source_timeframe" in derived:
        derived["source_timeframe"] = _timeframe(derived["source_timeframe"], "source_timeframe")
    if "source_family" in derived:
        derived["source_family"] = _text(derived["source_family"], "source_family")
    return derived


def liquidity_identity_preimage(
    *,
    producer_id: str,
    producer_revision: str | int,
    symbol: str,
    feed: str,
    anchor_timeframe: str,
    side: str,
    source_creation_identity: Any,
    level_price: str | int | Decimal,
    tick_size: str | int | Decimal,
) -> dict[str, Any]:
    """Build the exact stable V1 identity preimage.

    ``level_price_ticks`` is an integer produced by exact Decimal division.  A
    value not exactly aligned to the tick grid is rejected; no rounding occurs.
    """

    price = _decimal(level_price, "level_price", positive=True)
    tick = _decimal(tick_size, "tick_size", positive=True)
    # Decimal division is context-sensitive.  Convert the exact decimal
    # fractions to integers instead so identity never depends on precision or
    # rounding context.
    price_numerator, price_denominator = price.as_integer_ratio()
    tick_numerator, tick_denominator = tick.as_integer_ratio()
    numerator = price_numerator * tick_denominator
    denominator = price_denominator * tick_numerator
    integral, remainder = divmod(numerator, denominator)
    if remainder:
        _fail("PRICE_NOT_ON_TICK_GRID", "level_price", "exact Decimal-to-tick conversion is required")
    side_value = _text(side, "side", upper=True)
    if side_value not in {"ASK", "BID"}:
        _fail("INVALID_SIDE", "side", "must be ASK or BID")
    if source_creation_identity is None or source_creation_identity == "" or source_creation_identity == {}:
        _fail("MISSING_IDENTITY", "source_creation_identity", "identity is required")
    return {
        "schema": LIQUIDITY_IDENTITY_SCHEMA,
        "producer_id": _text(producer_id, "producer_id"),
        "producer_revision": _text(str(producer_revision), "producer_revision"),
        "symbol": _text(symbol, "symbol", upper=True),
        "feed": _text(feed, "feed", upper=True),
        "anchor_timeframe": _timeframe(anchor_timeframe, "anchor_timeframe"),
        "side": side_value,
        "source_creation_identity": _json_value(source_creation_identity),
        "tick_size": _canonical_decimal(tick),
        "level_price_ticks": integral,
    }


def liquidity_level_id(**components: Any) -> str:
    """Render ``liq1_<sha256>`` from the pinned canonical identity preimage."""

    digest = hashlib.sha256(canonical_json_bytes(liquidity_identity_preimage(**components))).hexdigest()
    return f"liq1_{digest}"


@dataclass(frozen=True)
class CanonicalEvent:
    family: str
    canonical_event_id: str
    producer_event_id: str
    source_bar_time: datetime
    confirmed: bool
    freshness_status: str
    data: Mapping[str, Any]
    raw_payload: bytes
    payload_sha256: str
    canonical_payload_sha256: str

    @property
    def event(self) -> str:
        return str(self.data["event"])

    @property
    def producer_key(self) -> tuple[str, str, str]:
        return (str(self.data["producer_id"]), str(self.data["producer_revision"]), self.producer_event_id)


def _common(obj: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    forbidden = sorted(_FORBIDDEN_FIELDS.intersection(obj))
    if forbidden:
        _fail("AMBIGUOUS_OR_ACTION_FIELD", forbidden[0], "field is forbidden at the numeric-state boundary")
    schema = _text(_required(obj, "schema"), "schema")
    family = _SCHEMA_FAMILY.get(schema)
    if family is None:
        _fail("UNSUPPORTED_SCHEMA", "schema", "unsupported or unversioned schema")
    producer_id = _text(_required(obj, "producer_id"), "producer_id")
    producer_revision = _text(str(_required(obj, "producer_revision")), "producer_revision")
    expected_revision = RAW_PRODUCER_ALLOWLIST.get((schema, producer_id))
    if expected_revision is None:
        _fail("UNSUPPORTED_PRODUCER", "producer_id", "schema and producer identity are not allowlisted")
    if producer_revision != expected_revision:
        _fail("UNSUPPORTED_PRODUCER_REVISION", "producer_revision", "producer revision is not allowlisted")
    event = _text(_required(obj, "event"), "event", upper=True)
    if event not in _EVENTS[family]:
        _fail("UNSUPPORTED_EVENT", "event", f"event is not valid for {family}")
    source_time = _timestamp(_required(obj, "source_bar_time"), "source_bar_time")
    conflicting = sorted(_FAMILY_CONFLICTING_FIELDS[family].intersection(obj))
    if conflicting:
        _fail("AMBIGUOUS_OR_ACTION_FIELD", conflicting[0], "field conflicts with the producer family")
    canonical = {
        "schema": schema,
        "producer_id": producer_id,
        "producer_revision": producer_revision,
        "event_id": _text(_required(obj, "event_id"), "event_id"),
        "event": event,
        "symbol": _text(_required(obj, "symbol"), "symbol", upper=True),
        "feed": _text(_required(obj, "feed"), "feed", upper=True),
        "source_bar_time": _format_timestamp(source_time),
        "confirmed": _boolean(_required(obj, "confirmed"), "confirmed"),
        "freshness_status": _freshness(_required(obj, "freshness_status")),
    }
    if obj.get("emitted_at") is not None:
        canonical["emitted_at"] = _format_timestamp(_timestamp(obj["emitted_at"], "emitted_at"))
    return family, canonical


def _canonicalize_liquidity(obj: Mapping[str, Any], data: dict[str, Any]) -> None:
    side = _text(_required(obj, "side"), "side", upper=True)
    if side not in {"ASK", "BID"}:
        _fail("INVALID_SIDE", "side", "must be ASK or BID")
    timeframe = _timeframe(obj.get("anchor_timeframe", obj.get("timeframe")), "anchor_timeframe")
    creation_identity = _source_creation_identity(obj)
    level_price = _decimal(_required(obj, "level_price"), "level_price", positive=True)
    market_price = _decimal(_required(obj, "market_price"), "market_price", positive=True)
    tick_size = _decimal(_required(obj, "tick_size"), "tick_size", positive=True)
    level_id = liquidity_level_id(
        producer_id=data["producer_id"],
        producer_revision=data["producer_revision"],
        symbol=data["symbol"],
        feed=data["feed"],
        anchor_timeframe=timeframe,
        side=side,
        source_creation_identity=creation_identity,
        level_price=level_price,
        tick_size=tick_size,
    )
    supplied_id = obj.get("level_id")
    if supplied_id is not None and _text(supplied_id, "level_id") != level_id:
        _fail("LEVEL_ID_MISMATCH", "level_id", "producer-supplied identity does not match canonical identity")
    grade = _text(_required(obj, "grade"), "grade", upper=True)
    if grade not in {"PRIME", "VALID", "WEAK"}:
        _fail("INVALID_GRADE", "grade", "must be PRIME, VALID, or WEAK")
    lifecycle = _text(_required(obj, "lifecycle"), "lifecycle", upper=True)
    expected_lifecycle = _LIQ_LIFECYCLE_FOR_EVENT[data["event"]]
    if lifecycle != expected_lifecycle:
        _fail("LIFECYCLE_EVENT_MISMATCH", "lifecycle", f"{data['event']} requires {expected_lifecycle}")
    created = _format_timestamp(_timestamp(_required(obj, "created_at_source"), "created_at_source"))
    data.update(
        {
            "anchor_timeframe": timeframe,
            "side": side,
            "source_creation_identity": creation_identity,
            "created_at_source": created,
            "level_id": level_id,
            "level_version": _text(str(_required(obj, "level_version")), "level_version"),
            "level_price": level_price,
            "market_price": market_price,
            "tick_size": tick_size,
            "grade": grade,
            "lifecycle": lifecycle,
            "mtf_confluence": _integer(_required(obj, "mtf_confluence"), "mtf_confluence", minimum=0),
            "touch_count": _integer(_required(obj, "touch_count"), "touch_count", minimum=0),
            "level_freshness_status": _freshness(obj.get("level_freshness_status", data["freshness_status"]), "level_freshness_status"),
            "market_price_freshness_status": _freshness(obj.get("market_price_freshness_status", data["freshness_status"]), "market_price_freshness_status"),
        }
    )
    if obj.get("confirmed_5m_atr14") is not None:
        data["confirmed_5m_atr14"] = _decimal(obj["confirmed_5m_atr14"], "confirmed_5m_atr14", positive=True)
        data["atr_confirmed"] = _boolean(_required(obj, "atr_confirmed"), "atr_confirmed")
        data["atr_freshness_status"] = _freshness(_required(obj, "atr_freshness_status"), "atr_freshness_status")
    else:
        data["confirmed_5m_atr14"] = None
        data["atr_confirmed"] = False
        data["atr_freshness_status"] = "MISSING"


def _canonicalize_expansion(obj: Mapping[str, Any], data: dict[str, Any]) -> None:
    direction = _text(_required(obj, "direction"), "direction", upper=True)
    if direction not in {"UP", "DOWN"}:
        _fail("INVALID_MOVEMENT_DIRECTION", "direction", "must be UP or DOWN; LONG/SHORT are forbidden")
    expected = "UP" if data["event"] == "EXP_UP" else "DOWN" if data["event"] == "EXP_DOWN" else None
    if expected and direction != expected:
        _fail("DIRECTION_EVENT_MISMATCH", "direction", f"{data['event']} requires {expected}")
    directional = data["event"] in {"EXP_UP", "EXP_DOWN"}
    quality = None if obj.get("quality") is None else _text(obj["quality"], "quality", upper=True)
    if quality is not None and quality not in {"CLEAN", "WEAK"}:
        _fail("INVALID_QUALITY", "quality", "must be CLEAN or WEAK when source evidence exists")
    path_efficiency = (
        _decimal(_required(obj, "path_efficiency"), "path_efficiency", nonnegative=True)
        if directional
        else _optional_decimal(obj, "path_efficiency", nonnegative=True)
    )
    body_quality = (
        _optional_decimal(obj, "body_quality", nonnegative=True)
        if directional
        else _decimal(_required(obj, "body_quality"), "body_quality", nonnegative=True)
    )
    if (path_efficiency is not None and path_efficiency > 1) or (
        body_quality is not None and body_quality > 1
    ):
        _fail("NUMBER_OUT_OF_RANGE", "quality_ratio", "quality ratios must be between zero and one")
    opposing_bars = (
        None if obj.get("opposing_bars") is None else _integer(obj["opposing_bars"], "opposing_bars")
    )
    if not directional and opposing_bars is None:
        _fail("MISSING_REQUIRED_FIELD", "opposing_bars", "scanner quality evidence requires opposing bars")
    too_extended = None if obj.get("too_extended") is None else _boolean(obj["too_extended"], "too_extended")
    if not directional and too_extended is None:
        _fail("MISSING_REQUIRED_FIELD", "too_extended", "scanner quality evidence requires extension status")
    data.update(
        {
            "timeframe": _timeframe(_required(obj, "timeframe"), "timeframe"),
            "direction": direction,
            "start_price": _decimal(_required(obj, "start_price"), "start_price", positive=True),
            "market_price": _decimal(_required(obj, "market_price"), "market_price", positive=True),
            "displacement": _decimal(_required(obj, "displacement"), "displacement", nonnegative=True),
            "atr": _decimal(_required(obj, "atr"), "atr", positive=True),
            "atr_multiple": _decimal(_required(obj, "atr_multiple"), "atr_multiple", nonnegative=True),
            "path_efficiency": path_efficiency,
            "body_quality": body_quality,
            "opposing_bars": opposing_bars,
            "age_bars": _integer(_required(obj, "age_bars"), "age_bars"),
            "quality": quality,
            "too_extended": too_extended,
        }
    )


def _canonicalize_renko(obj: Mapping[str, Any], data: dict[str, Any]) -> None:
    stage = _RENKO_STAGE[data["event"]]
    supplied_stage = _text(_required(obj, "stage"), "stage", upper=True)
    if supplied_stage == "SNIPER_FIRE":
        supplied_stage = "FIRE"
    if supplied_stage == "NONE" and stage in {"RESET", "INVALIDATED"}:
        supplied_stage = stage
    if supplied_stage != stage:
        _fail("STAGE_EVENT_MISMATCH", "stage", f"{data['event']} requires {stage}")
    direction = _text(_required(obj, "direction"), "direction", upper=True)
    allowed = {"NONE", "UP", "DOWN"} if stage in {"RESET", "INVALIDATED"} else {"UP", "DOWN"}
    if direction not in allowed:
        _fail("INVALID_MOVEMENT_DIRECTION", "direction", f"must be one of {sorted(allowed)}")
    cycle_id = obj.get("cycle_id", obj.get("cycle_identity"))
    data.update(
        {
            "timeframe": _timeframe(_required(obj, "timeframe"), "timeframe"),
            "stage": stage,
            "direction": direction,
            "event_sequence": _integer(_required(obj, "event_sequence"), "event_sequence"),
            "cycle_id": None if cycle_id is None else _text(cycle_id, "cycle_id"),
            "signal_price": (
                None
                if stage in {"RESET", "INVALIDATED"} and obj.get("signal_price") is None
                else _decimal(_required(obj, "signal_price"), "signal_price", positive=True)
            ),
        }
    )
    for age_field in ("e1_age_bars", "e2_age_bars", "main_age_bars"):
        data[age_field] = None if obj.get(age_field) is None else _integer(obj[age_field], age_field)
    if stage == "FIRE":
        score = _decimal(_required(obj, "score"), "score", nonnegative=True)
        if score > 100:
            _fail("NUMBER_OUT_OF_RANGE", "score", "score must be between zero and 100")
        power_value = _required(obj, "power")
        power = (
            _text(power_value, "power")
            if isinstance(power_value, str)
            else _decimal(power_value, "power", nonnegative=True)
        )
        data.update(
            {
                "score": score,
                "power": power,
                "mode": _text(_required(obj, "mode"), "mode"),
                "transfer": _text(_required(obj, "transfer"), "transfer"),
                "fire_reason_components": _freeze(_required(obj, "fire_reason_components")),
            }
        )


def parse_numeric_event(payload: bytes | str | Mapping[str, Any]) -> CanonicalEvent:
    """Parse one versioned producer event, failing closed on ambiguity."""

    obj, raw = _decode_payload(payload)
    family, data = _common(obj)
    if family == "LIQUIDITY":
        _canonicalize_liquidity(obj, data)
    elif family == "EXPANSION":
        _canonicalize_expansion(obj, data)
    else:
        _canonicalize_renko(obj, data)
    identity = {
        "schema": "project_a.producer_event_identity/1.0",
        "producer_id": data["producer_id"],
        "producer_revision": data["producer_revision"],
        "event_id": data["event_id"],
    }
    canonical_event_id = "evt1_" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return CanonicalEvent(
        family=family,
        canonical_event_id=canonical_event_id,
        producer_event_id=data["event_id"],
        source_bar_time=_timestamp(data["source_bar_time"], "source_bar_time"),
        confirmed=data["confirmed"],
        freshness_status=data["freshness_status"],
        data=_freeze(data),
        raw_payload=raw,
        payload_sha256=hashlib.sha256(raw).hexdigest(),
        # Hash the complete semantic source object (not its whitespace), so
        # producer extensions remain covered by event-id conflict detection.
        canonical_payload_sha256=hashlib.sha256(canonical_json_bytes(obj)).hexdigest(),
    )


@dataclass(frozen=True)
class LiquidityDistance:
    signed_distance_price: Decimal
    absolute_distance_price: Decimal
    distance_atr: Decimal | None
    distance_zone: str | None
    status: str
    expected_approach_direction: str


def liquidity_distance(
    *,
    side: str,
    level_price: Decimal,
    market_price: Decimal,
    confirmed_5m_atr14: Decimal | None,
    inputs_fresh: bool,
) -> LiquidityDistance:
    side = _text(side, "side", upper=True)
    if side not in {"ASK", "BID"}:
        _fail("INVALID_SIDE", "side", "must be ASK or BID")
    signed = level_price - market_price if side == "ASK" else market_price - level_price
    absolute = abs(signed)
    expected = "UP" if side == "ASK" else "DOWN"
    if not inputs_fresh or confirmed_5m_atr14 is None or confirmed_5m_atr14 <= 0:
        return LiquidityDistance(signed, absolute, None, None, "UNAVAILABLE", expected)
    ratio = _divide_decimal(absolute, confirmed_5m_atr14)
    if signed < 0:
        return LiquidityDistance(signed, absolute, ratio, None, "CROSSED_PENDING_CLASSIFICATION", expected)
    if signed == 0:
        return LiquidityDistance(signed, absolute, ratio, None, "HIT_INTERSECTION_EVALUATION_REQUIRED", expected)
    # Cross multiplication makes the approved 0.25/0.50 boundaries exact even
    # when the display ratio is a recurring decimal.
    zone = "NEAR_TOUCH" if absolute * 4 <= confirmed_5m_atr14 else "APPROACH" if absolute * 2 <= confirmed_5m_atr14 else "FAR"
    return LiquidityDistance(signed, absolute, ratio, zone, "AVAILABLE", expected)


@dataclass(frozen=True)
class PricePoint:
    event_id: str
    source_bar_time: datetime
    market_price: Decimal
    delta: Decimal | None
    delta_pct: Decimal | None
    movement_direction: str | None


@dataclass(frozen=True)
class LiquidityLevel:
    level_id: str
    level_version: str
    side: str
    level_price: Decimal
    created_at_source: datetime
    grade: str
    mtf_confluence: int
    touch_count: int
    lifecycle: str
    confirmed: bool
    freshness_status: str
    last_event_id: str
    last_observed_at: datetime
    distance: LiquidityDistance

    @property
    def key(self) -> tuple[str, str]:
        return self.level_id, self.level_version


@dataclass(frozen=True)
class RenkoState:
    cycle_id: str | None
    maturity: str
    confirmed_stages: tuple[str, ...]
    latest_stage: str
    latest_direction: str
    latest_confirmed: bool
    latest_freshness_status: str
    latest_event_id: str | None


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    duplicate: bool
    event: CanonicalEvent


def _time_key(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value - epoch
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _valid_lifecycle_transition(previous: str, current: str) -> bool:
    if previous == current:
        return True
    allowed = {
        "IDLE": {"APPROACH", "HIT", "BREAK", "INVALIDATED"},
        "APPROACH": {"HIT", "BREAK", "INVALIDATED"},
        "HIT": {"REJECT", "BREAK", "INVALIDATED"},
        "REJECT": set(),
        "BREAK": set(),
        "INVALIDATED": set(),
    }
    return current in allowed.get(previous, set())


class NumericMarketState:
    """Append-only, deterministically replayed offline numeric state."""

    schema_version = NUMERIC_STATE_SCHEMA

    def __init__(self, events: Iterable[bytes | str | Mapping[str, Any] | CanonicalEvent] = ()):
        self._events: dict[str, CanonicalEvent] = {}
        self._producer_keys: dict[tuple[str, str, str], str] = {}
        self._ordered: tuple[CanonicalEvent, ...] = ()
        self._levels: dict[tuple[str, str], LiquidityLevel] = {}
        self._price_path: tuple[PricePoint, ...] = ()
        self._expansion_history: tuple[CanonicalEvent, ...] = ()
        self._scanner_history: tuple[CanonicalEvent, ...] = ()
        self._scanner_quality: tuple[Mapping[str, Any], ...] = ()
        self._renko_history: tuple[CanonicalEvent, ...] = ()
        self._current: dict[str, CanonicalEvent] = {}
        self._previous: dict[str, CanonicalEvent] = {}
        self._tracked_key: tuple[str, str] | None = None
        self._tracked_selection: tuple[Any, ...] | None = None
        self._tracked_selected_at: datetime | None = None
        self._tracked_history: tuple[Mapping[str, Any], ...] = ()
        self._renko_state = RenkoState(None, "NONE", (), "NONE", "NONE", False, "MISSING", None)
        for event in events:
            self.ingest(event)

    @property
    def event_history(self) -> tuple[CanonicalEvent, ...]:
        return self._ordered

    @property
    def price_path(self) -> tuple[PricePoint, ...]:
        return self._price_path

    @property
    def liquidity_levels(self) -> Mapping[tuple[str, str], LiquidityLevel]:
        return MappingProxyType(dict(self._levels))

    @property
    def expansion_history(self) -> tuple[CanonicalEvent, ...]:
        return self._expansion_history

    @property
    def latest_expansion_story(self) -> CanonicalEvent | None:
        return self._expansion_history[-1] if self._expansion_history else None

    @property
    def scanner_quality_evidence(self) -> tuple[Mapping[str, Any], ...]:
        return self._scanner_quality

    @property
    def renko_state(self) -> RenkoState:
        return self._renko_state

    @property
    def tracked_level(self) -> LiquidityLevel | None:
        return None if self._tracked_key is None else self._levels.get(self._tracked_key)

    @property
    def tracked_level_history(self) -> tuple[Mapping[str, Any], ...]:
        return self._tracked_history

    @property
    def current_observations(self) -> Mapping[str, CanonicalEvent]:
        return MappingProxyType(dict(self._current))

    @property
    def previous_observations(self) -> Mapping[str, CanonicalEvent]:
        return MappingProxyType(dict(self._previous))

    def expansion_before(self, at: datetime | str, direction: str | None = None) -> CanonicalEvent | None:
        target = _timestamp(at, "at") if isinstance(at, str) else at.astimezone(timezone.utc)
        wanted = None if direction is None else _text(direction, "direction", upper=True)
        candidates = [
            event
            for event in self._expansion_history
            if event.source_bar_time <= target and (wanted is None or event.data["direction"] == wanted)
        ]
        return candidates[-1] if candidates else None

    def ingest(self, payload: bytes | str | Mapping[str, Any] | CanonicalEvent) -> IngestResult:
        event = payload if isinstance(payload, CanonicalEvent) else parse_numeric_event(payload)
        existing_digest = self._producer_keys.get(event.producer_key)
        if existing_digest is not None:
            existing = self._events[existing_digest]
            if existing.canonical_payload_sha256 != event.canonical_payload_sha256:
                _fail("EVENT_ID_CONFLICT", "event_id", "same producer event identity has different raw payload")
            return IngestResult(False, True, existing)
        self._events[event.canonical_event_id] = event
        self._producer_keys[event.producer_key] = event.canonical_event_id
        try:
            self._rebuild()
        except Exception:
            del self._events[event.canonical_event_id]
            del self._producer_keys[event.producer_key]
            self._rebuild()
            raise
        return IngestResult(True, False, event)

    def _rebuild(self) -> None:
        ordered = sorted(self._events.values(), key=lambda item: (_time_key(item.source_bar_time), item.canonical_event_id))
        levels: dict[tuple[str, str], LiquidityLevel] = {}
        prices: list[PricePoint] = []
        expansions: list[CanonicalEvent] = []
        scanners: list[CanonicalEvent] = []
        renko_events: list[CanonicalEvent] = []
        observations: dict[str, list[CanonicalEvent]] = {
            "LIQUIDITY": [], "EXPANSION": [], "EXPANSION_QUALITY": [], "RENKO": [],
        }
        tracked: tuple[str, str] | None = None
        tracked_tuple: tuple[Any, ...] | None = None
        tracked_at: datetime | None = None
        tracked_history: list[Mapping[str, Any]] = []
        renko_cycle: str | None = None
        renko_stages: set[str] = set()
        renko_latest: CanonicalEvent | None = None
        prior_expansion_direction: str | None = None

        for event in ordered:
            is_scanner = event.family == "EXPANSION" and event.data["producer_id"] == "EXP_SCANNER"
            observations["EXPANSION_QUALITY" if is_scanner else event.family].append(event)
            market_price = event.data.get("market_price") if event.family in {"LIQUIDITY", "EXPANSION"} else None
            if market_price is not None:
                previous = prices[-1] if prices else None
                delta = None if previous is None else market_price - previous.market_price
                delta_pct = None if previous is None else _divide_decimal(delta * Decimal(100), previous.market_price)
                direction = None if delta is None else "UP" if delta > 0 else "DOWN" if delta < 0 else "FLAT"
                prices.append(PricePoint(event.canonical_event_id, event.source_bar_time, market_price, delta, delta_pct, direction))

            if event.family == "EXPANSION":
                if is_scanner:
                    scanners.append(event)
                    continue
                expansions.append(event)
                if event.confirmed and event.freshness_status == "FRESH":
                    direction = str(event.data["direction"])
                    if prior_expansion_direction is not None and direction != prior_expansion_direction:
                        if tracked is not None:
                            tracked_history.append(
                                _freeze(
                                    {
                                        "event": "TRACKED_LEVEL_RELEASED",
                                        "level_id": tracked[0],
                                        "level_version": tracked[1],
                                        "reason": "DIRECTION_STORY_RESET",
                                        "source_event_id": event.canonical_event_id,
                                        "transition_time": _format_timestamp(event.source_bar_time),
                                    }
                                )
                            )
                        tracked = None
                        tracked_tuple = None
                        tracked_at = None
                    prior_expansion_direction = direction

            elif event.family == "LIQUIDITY":
                key = (str(event.data["level_id"]), str(event.data["level_version"]))
                previous_level = levels.get(key)
                if previous_level is not None and not _valid_lifecycle_transition(previous_level.lifecycle, str(event.data["lifecycle"])):
                    _fail("INVALID_LIFECYCLE_TRANSITION", "lifecycle", f"{previous_level.lifecycle} -> {event.data['lifecycle']}")
                inputs_fresh = (
                    event.confirmed
                    and event.data["level_freshness_status"] == "FRESH"
                    and event.data["market_price_freshness_status"] == "FRESH"
                    and event.data["atr_freshness_status"] == "FRESH"
                    and event.data["atr_confirmed"] is True
                )
                distance = liquidity_distance(
                    side=str(event.data["side"]),
                    level_price=event.data["level_price"],
                    market_price=event.data["market_price"],
                    confirmed_5m_atr14=event.data["confirmed_5m_atr14"],
                    inputs_fresh=inputs_fresh,
                )
                levels[key] = LiquidityLevel(
                    level_id=key[0],
                    level_version=key[1],
                    side=str(event.data["side"]),
                    level_price=event.data["level_price"],
                    created_at_source=_timestamp(event.data["created_at_source"], "created_at_source"),
                    grade=str(event.data["grade"]),
                    mtf_confluence=int(event.data["mtf_confluence"]),
                    touch_count=int(event.data["touch_count"]),
                    lifecycle=str(event.data["lifecycle"]),
                    confirmed=event.confirmed,
                    freshness_status=str(event.data["level_freshness_status"]),
                    last_event_id=event.canonical_event_id,
                    last_observed_at=event.source_bar_time,
                    distance=distance,
                )
                if tracked == key and levels[key].lifecycle in _TERMINAL_LIFECYCLES:
                    tracked_history.append(
                        _freeze(
                            {
                                "event": "TRACKED_LEVEL_RELEASED",
                                "level_id": tracked[0],
                                "level_version": tracked[1],
                                "reason": f"LEVEL_{levels[key].lifecycle}",
                                "source_event_id": event.canonical_event_id,
                                "transition_time": _format_timestamp(event.source_bar_time),
                            }
                        )
                    )
                    tracked = None
                    tracked_tuple = None
                    tracked_at = None

            else:
                renko_events.append(event)
                cycle = event.data.get("cycle_id")
                if cycle is not None and renko_cycle is not None and cycle != renko_cycle:
                    renko_stages.clear()
                if cycle is not None:
                    renko_cycle = str(cycle)
                if event.data["stage"] in {"RESET", "INVALIDATED"}:
                    renko_stages.clear()
                elif event.confirmed and event.freshness_status == "FRESH":
                    renko_stages.add(str(event.data["stage"]))
                renko_latest = event

            if tracked is None:
                story = next(
                    (
                        item
                        for item in reversed(expansions)
                        if item.confirmed and item.freshness_status == "FRESH"
                    ),
                    None,
                )
                if story is not None:
                    expected_side = "ASK" if story.data["direction"] == "UP" else "BID"
                    candidates = [
                        level
                        for level in levels.values()
                        if level.side == expected_side
                        and level.grade in _GRADE_RANK
                        and level.lifecycle in _ACTIVE_LIFECYCLES
                        and level.confirmed
                        and level.freshness_status == "FRESH"
                        and level.distance.status == "AVAILABLE"
                        and level.distance.distance_zone is not None
                    ]
                    candidates.sort(key=_selection_sort_key)
                    if candidates and candidates[0].distance.distance_zone != "FAR":
                        selected = candidates[0]
                        tracked = selected.key
                        tracked_tuple = _selection_audit_tuple(selected)
                        tracked_at = event.source_bar_time
                        tracked_history.append(
                            _freeze(
                                {
                                    "event": "TRACKED_LEVEL_SELECTED",
                                    "level_id": selected.level_id,
                                    "level_version": selected.level_version,
                                    "selection_tuple": tracked_tuple,
                                    "source_event_id": event.canonical_event_id,
                                    "transition_time": _format_timestamp(event.source_bar_time),
                                }
                            )
                        )

        directional_by_key: dict[tuple[Any, ...], list[CanonicalEvent]] = {}
        for expansion in expansions:
            key = (
                expansion.data["symbol"], expansion.data["feed"], expansion.data["timeframe"],
                expansion.data["source_bar_time"], expansion.data["direction"],
            )
            directional_by_key.setdefault(key, []).append(expansion)
        scanner_facts: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        scanner_quality: list[Mapping[str, Any]] = []
        for scanner in scanners:
            key = (
                scanner.data["symbol"], scanner.data["feed"], scanner.data["timeframe"],
                scanner.data["source_bar_time"], scanner.data["direction"],
            )
            conflict_key = key + (scanner.event,)
            facts = (
                scanner.data.get("quality"), scanner.data.get("too_extended"),
                scanner.data.get("body_quality"), scanner.data.get("opposing_bars"),
                scanner.data.get("age_bars"),
            )
            previous_facts = scanner_facts.get(conflict_key)
            if previous_facts is not None and previous_facts != facts:
                _fail(
                    "SCANNER_EVIDENCE_CONFLICT", "scanner_quality",
                    "same factual correlation key and event carry conflicting quality facts",
                )
            scanner_facts[conflict_key] = facts
            matches = directional_by_key.get(key, ())
            paired = matches[0] if len(matches) == 1 else None
            scanner_quality.append(_freeze({
                "scanner_event_id": scanner.canonical_event_id,
                "producer_event_id": scanner.producer_event_id,
                "status": (
                    "PAIRED_QUALITY_EVIDENCE"
                    if paired is not None else "UNPAIRED_QUALITY_EVIDENCE"
                ),
                "expansion_event_id": None if paired is None else paired.canonical_event_id,
                "correlation_key": {
                    "symbol": key[0], "feed": key[1], "timeframe": key[2],
                    "source_bar_time": key[3], "direction_context": key[4],
                },
                "event": scanner.event,
                "quality": scanner.data.get("quality"),
                "too_extended": scanner.data.get("too_extended"),
                "body_quality": scanner.data.get("body_quality"),
                "opposing_bars": scanner.data.get("opposing_bars"),
                "age_bars": scanner.data.get("age_bars"),
                "promoting": False,
                "trade_direction": None,
            }))

        self._ordered = tuple(ordered)
        self._levels = levels
        self._price_path = tuple(prices)
        self._expansion_history = tuple(expansions)
        self._scanner_history = tuple(scanners)
        self._scanner_quality = tuple(scanner_quality)
        self._renko_history = tuple(renko_events)
        self._current = {family: items[-1] for family, items in observations.items() if items}
        self._previous = {family: items[-2] for family, items in observations.items() if len(items) > 1}
        self._tracked_key = tracked
        self._tracked_selection = tracked_tuple
        self._tracked_selected_at = tracked_at
        self._tracked_history = tuple(tracked_history)
        maturity = max(renko_stages, key=lambda stage: _RENKO_RANK[stage], default="NONE")
        confirmed_stages = tuple(sorted(renko_stages, key=lambda stage: _RENKO_RANK[stage]))
        self._renko_state = RenkoState(
            renko_cycle,
            maturity,
            confirmed_stages,
            "NONE" if renko_latest is None else str(renko_latest.data["stage"]),
            "NONE" if renko_latest is None else str(renko_latest.data["direction"]),
            False if renko_latest is None else renko_latest.confirmed,
            "MISSING" if renko_latest is None else renko_latest.freshness_status,
            None if renko_latest is None else renko_latest.canonical_event_id,
        )

    def snapshot(self) -> dict[str, Any]:
        levels = sorted(self._levels.values(), key=lambda item: item.key)
        return {
            "schema_version": self.schema_version,
            "event_history": [event.canonical_event_id for event in self._ordered],
            "current_observations": {family: event.canonical_event_id for family, event in sorted(self._current.items())},
            "previous_observations": {family: event.canonical_event_id for family, event in sorted(self._previous.items())},
            "price_path": [
                {
                    "event_id": point.event_id,
                    "source_bar_time": point.source_bar_time,
                    "market_price": point.market_price,
                    "delta": point.delta,
                    "delta_pct": point.delta_pct,
                    "movement_direction": point.movement_direction,
                }
                for point in self._price_path
            ],
            "liquidity_levels": [
                {
                    "level_id": level.level_id,
                    "level_version": level.level_version,
                    "side": level.side,
                    "level_price": level.level_price,
                    "grade": level.grade,
                    "mtf_confluence": level.mtf_confluence,
                    "touch_count": level.touch_count,
                    "lifecycle": level.lifecycle,
                    "distance_atr": level.distance.distance_atr,
                    "distance_zone": level.distance.distance_zone,
                    "distance_status": level.distance.status,
                }
                for level in levels
            ],
            "tracked_level_id": None if self._tracked_key is None else self._tracked_key[0],
            "tracked_level_version": None if self._tracked_key is None else self._tracked_key[1],
            "tracked_selection_tuple": self._tracked_selection,
            "tracked_selected_at": self._tracked_selected_at,
            "tracked_level_history": list(self._tracked_history),
            "latest_expansion_story": None if self.latest_expansion_story is None else self.latest_expansion_story.canonical_event_id,
            "expansion_history": [event.canonical_event_id for event in self._expansion_history],
            "scanner_quality_evidence": list(self._scanner_quality),
            "renko": {
                "cycle_id": self._renko_state.cycle_id,
                "maturity": self._renko_state.maturity,
                "confirmed_stages": self._renko_state.confirmed_stages,
                "latest_stage": self._renko_state.latest_stage,
                "latest_direction": self._renko_state.latest_direction,
                "latest_confirmed": self._renko_state.latest_confirmed,
                "latest_freshness_status": self._renko_state.latest_freshness_status,
            },
            "trade_direction": None,
        }

    def canonical_snapshot(self) -> bytes:
        return canonical_json_bytes(self.snapshot())

    def save_history(self, path: str | Path) -> None:
        """Write an explicitly requested offline replay file; there is no default path."""

        destination = Path(path)
        lines = [base64.b64encode(event.raw_payload).decode("ascii") for event in self._ordered]
        destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="ascii", newline="\n")

    @classmethod
    def load_history(cls, path: str | Path) -> "NumericMarketState":
        state = cls()
        for line in Path(path).read_text(encoding="ascii").splitlines():
            if line:
                try:
                    payload = base64.b64decode(line, validate=True)
                except ValueError:
                    _fail("INVALID_HISTORY", "history", "invalid base64 replay record")
                state.ingest(payload)
        return state


def _selection_sort_key(level: LiquidityLevel) -> tuple[Any, ...]:
    if level.distance.distance_zone is None or level.distance.distance_atr is None:
        _fail("UNRANKABLE_LEVEL", "distance", "eligible level lacks distance")
    return (
        _ZONE_RANK[level.distance.distance_zone],
        _GRADE_RANK[level.grade],
        -level.mtf_confluence,
        level.distance.distance_atr,
        level.touch_count,
        -_time_key(level.created_at_source),
        level.level_id,
    )


def _selection_audit_tuple(level: LiquidityLevel) -> tuple[Any, ...]:
    return (
        level.distance.distance_zone,
        level.grade,
        level.mtf_confluence,
        level.distance.distance_atr,
        level.touch_count,
        _format_timestamp(level.created_at_source),
        level.level_id,
    )


# Explicit versioned alias for consumers that want the contract version in the name.
NumericMarketStateV1 = NumericMarketState
