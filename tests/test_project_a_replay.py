from __future__ import annotations

import json

import pytest

from project_a import replay


def test_one_command_replays_all_paths_without_live_dependencies():
    result = replay.run_all()
    assert result["ok"] is True
    assert result["mode"] == "SHADOW"
    assert result["environment"] == "MT5_DEMO"
    assert result["live_execution"] is False
    observed = {case.get("outcome") or case.get("error_code") for case in result["event_cases"]}
    assert {"ACCEPTED", "REJECTED", "STRUCTURAL_BREAK", "EXPIRED", "DUPLICATE"} <= observed
    assert result["accepted_pipeline"]["outputs"]["mt5"]["order_placed"] is False


def test_cli_writes_inspectable_output(tmp_path):
    output = tmp_path / "replay.json"
    assert replay.main(["--all", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True


@pytest.mark.parametrize(
    ("key", "unsafe"),
    [("live_execution", True), ("execution_environment", "MT5_LIVE"), ("mode", "LIVE")],
)
def test_replay_fails_closed_for_unsafe_environment(key, unsafe):
    config = replay._config()
    config[key] = unsafe
    with pytest.raises(replay.ReplayFailure, match="unsafe config"):
        replay._enforce_shadow(config)
