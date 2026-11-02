"""Tests for generation benchmark execution harness with scripted transport."""

from __future__ import annotations

import json
from pathlib import Path

from job_automation.model_benchmarks.generation_runs import execute_generation_cell
from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    CapabilityType,
    CellStatus,
    ExecutionPlacement,
    ResidencyMode,
)
from job_automation.model_benchmarks.telemetry import HostTelemetrySampler
from job_automation.model_benchmarks.transport_observer import TransportObserver
from job_automation.models.schemas import build_default_schema_registry
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestGenerationRuns:
    def test_execute_generation_cell_success(self) -> None:
        transport = ScriptedModelTransport()
        # Mock residency check
        transport.queue_response(
            "/api/ps",
            200,
            body={"models": [{"name": "qwen2.5:1.5b", "size_vram": 1100000000}]},
        )
        # Mock successful generation
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            gen_resp = json.load(f)
        transport.queue_response("/api/generate", 200, body=gen_resp)

        # Mock residency query in finally block
        transport.queue_response(
            "/api/ps",
            200,
            body={"models": [{"name": "qwen2.5:1.5b", "size_vram": 1100000000}]},
        )

        observer = TransportObserver(transport=transport)
        sampler = HostTelemetrySampler(sample_interval_seconds=0.05)
        schema_reg = build_default_schema_registry()

        cell = BenchmarkCell(
            cell_id="gen_test_01",
            capability=CapabilityType.GENERATION,
            model_name="qwen2.5:1.5b",
            context_length=2048,
            num_predict=256,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=1,
            input_case_id="case_gen_short",
        )

        obs = execute_generation_cell(
            cell=cell,
            repetition_index=0,
            transport=transport,
            observer=observer,
            sampler=sampler,
            schema_registry=schema_reg,
        )

        assert obs.status == CellStatus.MEASURED
        assert obs.placement_observed == ExecutionPlacement.GPU
        assert obs.structured_output is not None
        assert obs.structured_output.is_valid_json is True
        assert obs.structured_output.is_valid_schema is True

    def test_execute_generation_cell_malformed_json(self) -> None:
        transport = ScriptedModelTransport()
        transport.queue_response(
            "/api/ps", 200, body={"models": [{"name": "qwen2.5:1.5b", "size_vram": 0}]}
        )
        transport.queue_response(
            "/api/generate",
            200,
            body={"model": "qwen2.5:1.5b", "response": "Not valid JSON at all!"},
        )
        transport.queue_response(
            "/api/ps", 200, body={"models": [{"name": "qwen2.5:1.5b", "size_vram": 0}]}
        )

        observer = TransportObserver(transport=transport)
        sampler = HostTelemetrySampler(sample_interval_seconds=0.05)
        schema_reg = build_default_schema_registry()

        cell = BenchmarkCell(
            cell_id="gen_test_fail",
            capability=CapabilityType.GENERATION,
            model_name="qwen2.5:1.5b",
            context_length=2048,
            num_predict=256,
            placement_requested=ExecutionPlacement.CPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=1,
            input_case_id="case_gen_short",
        )

        obs = execute_generation_cell(
            cell=cell,
            repetition_index=0,
            transport=transport,
            observer=observer,
            sampler=sampler,
            schema_registry=schema_reg,
        )

        assert obs.status == CellStatus.FAILED
        assert obs.error_category == "MODEL_OUTPUT"
        assert obs.structured_output is not None
        assert obs.structured_output.is_valid_json is False
