from __future__ import annotations

import json

from output.project_a import acceptance, replay


def test_replay_defaults_to_no_side_effect_fake_mode(tmp_path):
    result = replay.replay(db_path=tmp_path / "replay.db")
    assert result["ok"] is True and result["dry_run"] is True
    assert result["external_side_effects"] is False
    assert result["clock_mode"] == "RECORDED_FIXTURE"


def test_replay_again_preserves_completed_deliveries(tmp_path):
    db = tmp_path / "replay.db"
    first = replay.replay(db_path=db)
    second = replay.replay(db_path=db)
    assert first["created"] is True and second["created"] is False
    assert second["results"] == []
    assert all(item["attempt_count"] == 1 for item in second["deliveries"])


def test_replay_one_selected_renderer_only(tmp_path):
    result = replay.replay(db_path=tmp_path / "replay.db", renderer_type="TELEGRAM")
    assert [item["status"] for item in result["results"]] == ["DRY_RUN_SUCCESS"]
    assert result["transport_counts"]["telegram_messages"] == 1
    assert result["transport_counts"]["tradingview_objects"] == 0


def test_replay_cli_writes_inspectable_json(tmp_path):
    output = tmp_path / "out.json"
    assert replay.main(["--db", str(tmp_path / "replay.db"), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["external_side_effects"] is False


def test_acceptance_harness_runs_28_recorded_fake_samples():
    report = acceptance.run_acceptance()
    assert report["sample_count"] == 28
    assert report["passed"] == 28 and report["failed"] == 0
    assert report["real_shadow_samples_completed"] == 0
    assert report["external_side_effects"] is False


def test_acceptance_template_contains_required_evidence_fields():
    report = acceptance.run_acceptance()
    required = {
        "sample_id", "setup_id", "source_fixture", "verdict", "expected_outputs",
        "actual_output_statuses", "idempotency_result", "safety_gate_result",
        "external_side_effects_used_or_mocked", "entry_sl_tp_consistency",
        "error_retry_evidence", "call_log_consistency", "pass", "reviewer_notes",
    }
    assert all(required <= set(sample) for sample in report["samples"])


def test_no_live_order_route_is_exposed():
    assert "live" not in replay.main.__doc__.lower() if replay.main.__doc__ else True
    source = (replay.Path(replay.__file__).read_text(encoding="utf-8")
              + replay.Path(acceptance.__file__).read_text(encoding="utf-8"))
    assert "order_send" not in source and "MetaTrader5" not in source
