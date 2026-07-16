from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from output.project_a.compiler import InputAttestation, ThesisCompiler
from output.project_a.models import parse_utc
from output.project_a.replay import FIXTURES, build_fake_runtime, load_json

NOW = parse_utc("2026-07-16T00:00:04Z")


@pytest.fixture
def request_doc():
    return deepcopy(load_json(FIXTURES / "analysis_request_accepted.json"))


@pytest.fixture
def verdict_doc():
    return deepcopy(load_json(FIXTURES / "ai_verdict_approved.json"))


@pytest.fixture
def runtime(tmp_path):
    config, store, transports, dispatcher, notion = build_fake_runtime(tmp_path / "outputs.db")
    return {
        "config": config, "store": store, "transports": transports,
        "dispatcher": dispatcher, "notion": notion,
    }


def compile_input(runtime, request, verdict, *, now=NOW, attestation=None):
    return ThesisCompiler(runtime["store"], runtime["config"]).compile(
        request, verdict,
        attestation or InputAttestation(True, True, "fixture://audit/verdict"),
        now=now,
    )


def non_actionable(verdict: dict, decision: str) -> dict:
    verdict = deepcopy(verdict)
    verdict.update({
        "verdict_id": f"verdict_xau_20260716_{decision.lower()}99",
        "verdict": decision, "entry": None, "sl": None, "tp": None,
        "valid_until": None, "reason_codes": ["SNR_INVALID"],
        "rationale": f"Deterministic {decision.lower()} fixture.",
    })
    return verdict


def delivery(store, setup_id, renderer_type):
    return next(item for item in store.deliveries_for_setup(setup_id)
                if item["renderer_type"] == renderer_type)
