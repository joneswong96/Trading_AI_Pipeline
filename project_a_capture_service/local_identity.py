"""Fail-closed identity pin for the local capture-service listener."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def attest_capture_listener(*, port: int, expected_pid: int) -> dict[str, object]:
    if os.name != "nt" or expected_pid <= 0:
        raise ValueError("PROJECT_A_CAPTURE_SERVER_PID must pin the Windows listener process")
    script = (
        f"$r=@(Get-NetTCPConnection -State Listen -LocalPort {port} "
        "-ErrorAction SilentlyContinue);"
        "if($r.Count -gt 0){$p=Get-CimInstance Win32_Process -Filter "
        "('ProcessId='+$r[0].OwningProcess);[pscustomobject]@{addresses=@($r.LocalAddress);"
        "pids=@($r.OwningProcess);pid=$r[0].OwningProcess;name=$p.Name;"
        "executable=$p.ExecutablePath;command=$p.CommandLine}|ConvertTo-Json -Compress}"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True,
            text=True, timeout=8, check=False,
        )
        identity = json.loads(completed.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError) as exc:
        raise ValueError("capture service listener attestation failed") from exc
    addresses = set(identity.get("addresses") or [])
    pids = {int(value) for value in (identity.get("pids") or [])}
    command = str(identity.get("command") or "")
    executable = Path(str(identity.get("executable") or ""))
    if (
        addresses != {"127.0.0.1"} or pids != {expected_pid}
        or int(identity.get("pid") or 0) != expected_pid
        or str(identity.get("name") or "").lower() != "python.exe"
        or executable.name.lower() != "python.exe" or not executable.is_file()
        or not re.search(r"(?:^|\s)-m\s+project_a_capture_service\s+serve(?:\s|$)", command)
    ):
        raise ValueError("capture service listener identity mismatch")
    return {"pid": expected_pid, "address": "127.0.0.1", "port": port}
