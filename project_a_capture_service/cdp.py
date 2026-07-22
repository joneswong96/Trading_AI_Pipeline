"""Minimal fixed-method Chrome DevTools reader for the approved 9333 profile."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import websocket

from .plans import CapturePlan, ViewPlan
from .schemas import CDP_ENDPOINT, EXPECTED_ACCOUNT


SCRIPT_ID = "tradingview_read_state"
SCRIPT_VERSION = "1.0"
SCRIPT_SHA256 = "b2ab345bd8ed987a1ef17e17087126a4ddcbcbcacad71e68ab28600eb19390a6"
SCRIPT_PATH = Path(__file__).with_name("scripts") / "tradingview_read_state_v1.js"
ALLOWED_CDP_METHODS = frozenset({"Runtime.evaluate", "Page.captureScreenshot"})
MAX_METADATA_BYTES = 1_048_576
MAX_SCREENSHOT_BYTES = 4_194_304
MAX_SCREENSHOT_PIXELS = 24_000_000


class CaptureFailure(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool = True):
        self.code = code
        self.detail = str(detail)[:400]
        self.retryable = retryable
        super().__init__(f"{code}: {self.detail}")


@dataclass(frozen=True)
class Target:
    target_id: str
    url: str
    title: str
    web_socket_url: str
    layout_id: str


@dataclass(frozen=True)
class ViewSnapshot:
    plan: ViewPlan
    target: Target
    account: str
    observed_at: datetime
    last_bar_at: datetime
    charts: tuple[dict[str, Any], ...]
    indicator_names: tuple[str, ...]
    alert_inventory_count: int | None
    raw: dict[str, Any]


class ReadOnlyBackend(Protocol):
    def discover(self) -> list[Target]: ...
    def read(self, target: Target) -> dict[str, Any]: ...
    def screenshot(self, target: Target) -> bytes: ...


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch(value: Any) -> datetime:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise CaptureFailure("SOURCE_STALE", "bar timestamp is absent or non-finite")
    seconds = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _read_json(path: str) -> Any:
    request = urllib.request.Request(CDP_ENDPOINT + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", f"CDP metadata status {response.status}")
        raw = response.read(MAX_METADATA_BYTES + 1)
    if len(raw) > MAX_METADATA_BYTES:
        raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "CDP metadata exceeded size limit")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "CDP metadata is not JSON") from exc


def _layout_id(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https" or parts.hostname not in {"www.tradingview.com", "tradingview.com"}
        or parts.username is not None or parts.password is not None or parts.port not in {None, 443}
    ):
        raise CaptureFailure("LAYOUT_MISMATCH", "target origin is not TradingView")
    match = re.fullmatch(r"/chart/([A-Za-z0-9]+)/?", parts.path)
    if not match or parts.query or parts.fragment:
        raise CaptureFailure("LAYOUT_MISMATCH", "target is not an exact saved-layout URL")
    return match.group(1)


def _script() -> str:
    raw = SCRIPT_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCRIPT_SHA256:
        raise CaptureFailure("SCRIPT_INTEGRITY_FAILURE", "fixed read script hash mismatch", retryable=False)
    return raw.decode("utf-8")


class _TargetSession:
    def __init__(self, target: Target, *, timeout: float = 12.0):
        parsed = urlsplit(target.web_socket_url)
        if (
            parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port != 9333
            or parsed.path != f"/devtools/page/{target.target_id}" or parsed.query or parsed.fragment
        ):
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "target websocket is outside fixed 9333 authority")
        self._connection = websocket.create_connection(
            target.web_socket_url, timeout=timeout, suppress_origin=True, enable_multithread=False,
        )
        self._next_id = 0

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in ALLOWED_CDP_METHODS:
            raise CaptureFailure("CDP_METHOD_FORBIDDEN", f"method {method!r} is not read-only allowlisted", retryable=False)
        self._next_id += 1
        message_id = self._next_id
        self._connection.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            raw = self._connection.recv()
            message = json.loads(raw)
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise CaptureFailure("CDP_READ_FAILURE", str(message["error"]))
            result = message.get("result")
            if not isinstance(result, dict):
                raise CaptureFailure("CDP_READ_FAILURE", "CDP response omitted result")
            return result

    def evaluate_fixed(self) -> dict[str, Any]:
        result = self._send("Runtime.evaluate", {
            "expression": _script(),
            "returnByValue": True,
            "awaitPromise": False,
            "includeCommandLineAPI": False,
            "silent": False,
            "userGesture": False,
        })
        exception = result.get("exceptionDetails")
        value = (result.get("result") or {}).get("value")
        if exception or not isinstance(value, dict):
            raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "fixed TradingView read script failed")
        return value

    def capture_png(self) -> bytes:
        result = self._send("Page.captureScreenshot", {
            "format": "png", "fromSurface": True,
            "captureBeyondViewport": False, "optimizeForSpeed": False,
        })
        encoded = result.get("data")
        if not isinstance(encoded, str) or len(encoded) > (MAX_SCREENSHOT_BYTES * 4 // 3 + 16):
            raise CaptureFailure("SCREENSHOT_INVALID", "screenshot payload is absent or oversized")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise CaptureFailure("SCREENSHOT_INVALID", "screenshot base64 is invalid") from exc
        validate_png(data)
        return data


class ProductionCdpBackend:
    """Attests and reads only the already-running approved production Chrome."""

    def _attest_listener(self) -> None:
        if os.name != "nt":
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "production listener attestation is Windows-only")
        script = (
            "Import-Module -Name 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\Modules\\"
            "Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1';"
            "$r=@(Get-NetTCPConnection -State Listen -LocalPort 9333 -ErrorAction SilentlyContinue);"
            "if($r.Count -gt 0){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$r[0].OwningProcess);"
            "$s=Get-AuthenticodeSignature -LiteralPath $p.ExecutablePath;"
            "[pscustomobject]@{addresses=@($r.LocalAddress);pids=@($r.OwningProcess);pid=$r[0].OwningProcess;"
            "name=$p.Name;executable=$p.ExecutablePath;signature=$s.Status.ToString();"
            "signer=$s.SignerCertificate.Subject;command=$p.CommandLine}|ConvertTo-Json -Compress}"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script], capture_output=True,
                text=True, timeout=8, check=False,
            )
            attestation = json.loads(completed.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError) as exc:
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "9333 listener attestation failed") from exc
        addresses = set(attestation.get("addresses") or [])
        pids = {int(value) for value in (attestation.get("pids") or [])}
        command = str(attestation.get("command") or "").lower()
        executable = str(attestation.get("executable") or "").lower()
        signer = str(attestation.get("signer") or "").lower()
        if (
            addresses != {"127.0.0.1"} or len(pids) != 1
            or str(attestation.get("name") or "").lower() != "chrome.exe"
            or executable != r"c:\program files\google\chrome\application\chrome.exe"
            or str(attestation.get("signature") or "") != "Valid" or "google llc" not in signer
            or not re.search(r"(?:^|\s)--remote-debugging-port=9333(?:\s|$)", command)
            or not re.search(
                r"(?:^|\s)--user-data-dir=(?:\"?)c:\\users\\jones\.w\\chromecdp9333(?:\"?)(?:\s|$)",
                command,
            )
        ):
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "9333 is not the approved loopback Chrome profile")

    def discover(self) -> list[Target]:
        self._attest_listener()
        version = _read_json("/json/version")
        targets = _read_json("/json/list")
        if not isinstance(version, dict) or not str(version.get("Browser", "")).startswith("Chrome/"):
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "9333 browser identity is incomplete")
        if not isinstance(targets, list):
            raise CaptureFailure("CDP_ENDPOINT_IDENTITY_MISMATCH", "9333 target inventory is invalid")
        result = []
        for item in targets:
            if not isinstance(item, dict) or item.get("type") != "page":
                continue
            try:
                layout = _layout_id(str(item.get("url", "")))
            except CaptureFailure:
                continue
            target_id = str(item.get("id", ""))
            ws = str(item.get("webSocketDebuggerUrl", ""))
            if not target_id or len(target_id) > 128:
                continue
            result.append(Target(target_id, str(item["url"]), str(item.get("title", "")), ws, layout))
        return result

    def read(self, target: Target) -> dict[str, Any]:
        with _TargetSession(target) as session:
            return session.evaluate_fixed()

    def screenshot(self, target: Target) -> bytes:
        with _TargetSession(target) as session:
            return session.capture_png()


def select_targets(plan: CapturePlan, targets: list[Target]) -> dict[str, Target]:
    selected: dict[str, Target] = {}
    for view in plan.views:
        matches = [target for target in targets if target.layout_id == view.layout_id]
        if not matches:
            raise CaptureFailure("TARGET_MISSING", f"approved layout {view.layout_id} is not open")
        if len(matches) != 1:
            raise CaptureFailure("TARGET_AMBIGUOUS", f"approved layout {view.layout_id} has {len(matches)} targets")
        selected[view.role] = matches[0]
    return selected


def _normalize_timeframe(value: Any) -> str:
    normalized = str(value or "").upper()
    return {
        "5S": "5s", "1": "1m", "1M": "1m", "5": "5m", "5M": "5m",
        "15": "15m", "15M": "15m", "30": "30m", "30M": "30m",
        "240": "4H", "4H": "4H", "1D": "D", "D": "D", "1W": "W", "W": "W",
    }.get(normalized, "")


def _resolve_account(markers: Any) -> str:
    if not isinstance(markers, list):
        raise CaptureFailure("ACCOUNT_MISMATCH", "account markers are missing")
    found = set()
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        username = str(marker.get("username") or "").strip()
        href = str(marker.get("href") or "")
        if username:
            found.add(username)
        match = re.search(r"/u/([^/?#]+)/?", href, re.IGNORECASE)
        if match:
            found.add(match.group(1))
        for key in ("aria_label", "title", "text"):
            value = str(marker.get(key) or "")
            if EXPECTED_ACCOUNT.lower() in value.lower():
                found.add(EXPECTED_ACCOUNT)
    exact = {value for value in found if value.lower() == EXPECTED_ACCOUNT.lower()}
    others = {value for value in found if value.lower() != EXPECTED_ACCOUNT.lower()}
    if exact != {EXPECTED_ACCOUNT} or others:
        raise CaptureFailure("ACCOUNT_MISMATCH", f"account identity is not uniquely {EXPECTED_ACCOUNT}")
    return EXPECTED_ACCOUNT


def validate_view(view: ViewPlan, target: Target, raw: dict[str, Any], *, now: datetime) -> ViewSnapshot:
    if raw.get("script_id") != SCRIPT_ID or raw.get("script_version") != SCRIPT_VERSION:
        raise CaptureFailure("SCRIPT_INTEGRITY_FAILURE", "fixed script identity was not returned")
    if raw.get("page_ready") is not True or raw.get("read_error"):
        raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "TradingView structured state is not ready")
    if _layout_id(str(raw.get("location_url", ""))) != view.layout_id or target.layout_id != view.layout_id:
        raise CaptureFailure("LAYOUT_MISMATCH", f"live page does not match layout {view.layout_id}")
    account = _resolve_account(raw.get("account_markers"))
    charts = raw.get("charts")
    if not isinstance(charts, list) or len(charts) != len(view.timeframes):
        raise CaptureFailure("TIMEFRAME_MISMATCH", f"layout {view.layout_id} chart count mismatch")
    normalized: list[dict[str, Any]] = []
    for chart in charts:
        if not isinstance(chart, dict):
            raise CaptureFailure("STRUCTURED_READ_INCOMPLETE", "chart record is invalid")
        symbol = str(chart.get("symbol") or "").upper()
        expected = f"{view.feed}:{view.symbol}"
        if symbol != expected:
            raise CaptureFailure("SYMBOL_MISMATCH", f"layout {view.layout_id} observed {symbol!r}")
        timeframe = _normalize_timeframe(chart.get("interval"))
        if not timeframe:
            raise CaptureFailure("TIMEFRAME_MISMATCH", "unrecognized TradingView interval")
        if chart.get("chart_type") != 1:
            raise CaptureFailure("CHART_TYPE_MISMATCH", f"{view.layout_id}/{timeframe} is not standard candles")
        current = chart.get("current_bar")
        closed = chart.get("closed_bar")
        if not isinstance(current, dict) or not isinstance(closed, dict):
            raise CaptureFailure("SOURCE_STALE", f"{view.layout_id}/{timeframe} bars are incomplete")
        last_at = _epoch(current.get("time"))
        seconds = {"5s": 5, "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                   "4H": 14400, "D": 86400, "W": 604800}[timeframe]
        if now - last_at > timedelta(seconds=seconds * 2 + 120) or last_at > now + timedelta(seconds=5):
            raise CaptureFailure("SOURCE_STALE", f"{view.layout_id}/{timeframe} bar is stale")
        item = dict(chart)
        item["timeframe"] = timeframe
        normalized.append(item)
    if {item["timeframe"] for item in normalized} != set(view.timeframes):
        raise CaptureFailure("TIMEFRAME_MISMATCH", f"layout {view.layout_id} timeframe set mismatch")
    indicators = sorted({
        str(study.get("description")) for chart in normalized for study in chart.get("studies", [])
        if isinstance(study, dict) and study.get("description")
    })
    last_bar_at = max(_epoch(chart["current_bar"]["time"]) for chart in normalized)
    return ViewSnapshot(
        view, target, account, now, last_bar_at, tuple(normalized), tuple(indicators),
        raw.get("alert_inventory_count") if isinstance(raw.get("alert_inventory_count"), int) else None,
        raw,
    )


def validate_png(data: bytes) -> tuple[int, int]:
    if len(data) > MAX_SCREENSHOT_BYTES or len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CaptureFailure("SCREENSHOT_INVALID", "PNG signature or size is invalid")
    width, height = struct.unpack(">II", data[16:24])
    if width < 320 or height < 200 or width > 16384 or height > 16384 or width * height > MAX_SCREENSHOT_PIXELS:
        raise CaptureFailure("SCREENSHOT_INVALID", f"PNG dimensions {width}x{height} are outside policy")
    return width, height
