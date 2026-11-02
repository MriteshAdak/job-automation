"""Tests for MODEL-02 benchmark records and data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    BenchmarkManifest,
    CandidateLicenseRecord,
    CapabilityType,
    CellObservation,
    CellStatus,
    DependencyGate,
    DependencyGateStatus,
    DigestProvenance,
    ExecutionPlacement,
    HardwareGuardrails,
    HostHardwareContext,
    MemorySample,
    ResidencyMode,
    StructuredOutputResult,
    TelemetrySummary,
    TransportTimings,
    VectorConformanceResult,
)


class TestBenchmarkRecords:
    def test_candidate_license_record(self) -> None:
        rec = CandidateLicenseRecord(
            model_name="qwen2.5:1.5b",
            parameter_size="1.5B",
            format_quant="GGUF / Q4_K_M",
            source_url="https://huggingface.co/Qwen/Qwen2.5-1.5B",
            license_id="Apache-2.0",
            copyright_notice="Copyright 2024 Alibaba Cloud",
            verified_digest="sha256:testdigest",
        )
        assert rec.model_name == "qwen2.5:1.5b"
        assert rec.commercial_use_allowed is True
        assert rec.notice_required is False

    def test_dependency_gate_record(self) -> None:
        gate = DependencyGate(
            gate_id="B1",
            name="Runtime Health",
            owner="MODEL-01",
            status=DependencyGateStatus.SATISFIED,
            evidence="Ollama verified",
            next_action="Maintain loopback",
        )
        assert gate.status == DependencyGateStatus.SATISFIED
        with pytest.raises(ValidationError):
            gate.status = "invalid"  # Frozen / type validated

    def test_transport_timings_rates(self) -> None:
        timings = TransportTimings(
            wall_duration_ms=1500.0,
            server_total_duration_ms=1450.0,
            server_prompt_eval_duration_ms=300.0,
            server_eval_duration_ms=1150.0,
            prompt_tokens=150,
            completion_tokens=65,
            prompt_eval_rate_tok_s=500.0,
            eval_rate_tok_s=56.5,
        )
        assert timings.wall_duration_ms == 1500.0
        assert timings.eval_rate_tok_s == 56.5

    def test_cell_observation_serialization(self) -> None:
        obs = CellObservation(
            cell_id="cell_test_01",
            repetition_index=0,
            attempt_index=0,
            cold_warm=ResidencyMode.WARM,
            requested_model="qwen2.5:1.5b",
            effective_model_tag="qwen2.5:1.5b",
            inventory_digest="65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b",
            digest_provenance=DigestProvenance.INVENTORY_DIGEST,
            status=CellStatus.MEASURED,
            placement_requested=ExecutionPlacement.GPU,
            placement_observed=ExecutionPlacement.GPU,
            timings=TransportTimings(wall_duration_ms=1200.0),
            telemetry=TelemetrySummary(
                baseline_available_phys_bytes=8000000000,
                min_available_phys_bytes=7500000000,
                sample_count=10,
                sample_interval_ms=200.0,
            ),
        )
        dumped = obs.model_dump(mode="json")
        loaded = CellObservation.model_validate(dumped)
        assert loaded.cell_id == "cell_test_01"
        assert loaded.status == CellStatus.MEASURED
        assert loaded.placement_observed == ExecutionPlacement.GPU

