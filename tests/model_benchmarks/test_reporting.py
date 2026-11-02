"""Tests for benchmark markdown and recommendations reporting."""

from __future__ import annotations

import json
from pathlib import Path

from job_automation.model_benchmarks.configuration import build_default_phase0_manifest
from job_automation.model_benchmarks.records import (
    CellObservation,
    CellStatus,
    DigestProvenance,
    ExecutionPlacement,
    ResidencyMode,
    StructuredOutputResult,
    TelemetrySummary,
    TransportTimings,
    VectorConformanceResult,
)
from job_automation.model_benchmarks.reporting import (
    compute_percentiles,
    format_bytes_mib,
    format_ms,
    generate_benchmark_markdown_report,
    generate_recommendations_json,
)
from job_automation.model_benchmarks.telemetry import capture_host_hardware_context


class TestReporting:
    def test_compute_percentiles(self) -> None:
        stats = compute_percentiles([10.0, 20.0, 30.0, 40.0, 50.0])
        assert stats["median"] == 30.0
        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["p95"] == 50.0

    def test_format_helpers(self) -> None:
        assert format_bytes_mib(1048576) == "1.0 MiB"
        assert format_bytes_mib(None) == "N/A"
        assert format_ms(150.25) == "150.2 ms"
        assert format_ms(None) == "N/A"

    def test_generate_markdown_report(self) -> None:
        manifest = build_default_phase0_manifest()
        hw = capture_host_hardware_context()
        obs = [
            CellObservation(
                cell_id="gen_qwen1.5b_ctx2048_gpu_warm",
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
                timings=TransportTimings(
                    wall_duration_ms=1850.0,
                    prompt_eval_rate_tok_s=450.0,
                    eval_rate_tok_s=60.0,
                ),
                telemetry=TelemetrySummary(
                    baseline_available_phys_bytes=8000000000,
                    min_available_phys_bytes=7500000000,
                    max_server_ws_bytes=1200000000,
                    peak_gpu_allocated_bytes=1250000000,
                    sample_count=8,
                    sample_interval_ms=200.0,
                ),
                structured_output=StructuredOutputResult(
                    is_valid_json=True,
                    is_valid_schema=True,
                    done_reason="stop",
                ),
            ),
            CellObservation(
                cell_id="embed_minilm_b1_gpu",
                repetition_index=0,
                attempt_index=0,
                cold_warm=ResidencyMode.WARM,
                requested_model="all-minilm:22m",
                effective_model_tag="all-minilm:22m",
                inventory_digest="1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef",
                digest_provenance=DigestProvenance.INVENTORY_DIGEST,
                status=CellStatus.MEASURED,
                placement_requested=ExecutionPlacement.GPU,
                placement_observed=ExecutionPlacement.GPU,
                timings=TransportTimings(
                    wall_duration_ms=25.0,
                    prompt_eval_rate_tok_s=40.0,
                ),
                telemetry=TelemetrySummary(
                    baseline_available_phys_bytes=8000000000,
                    min_available_phys_bytes=7900000000,
                    max_server_ws_bytes=200000000,
                    peak_gpu_allocated_bytes=30000000,
                    sample_count=2,
                    sample_interval_ms=200.0,
                ),
                vector_conformance=VectorConformanceResult(
                    vector_count=1,
                    dimension=384,
                    is_finite=True,
                    l2_norm_mean=1.0,
                    repeatability_cosine_similarity=1.0,
                ),
            ),
        ]

        report_md = generate_benchmark_markdown_report(manifest, hw, obs)
        assert "# MODEL-02 — Model and Context Benchmark Report (Phase 0)" in report_md
        assert "qwen2.5:1.5b" in report_md
        assert "all-minilm:22m" in report_md
        assert "1850.0 ms" in report_md

    def test_generate_recommendations_json(self) -> None:
        recs = generate_recommendations_json()
        assert recs["schema_version"] == "1.0"
        assert recs["generation"]["model_identifier"] == "qwen2.5:1.5b"
        assert recs["embedding"]["model_identifier"] == "all-minilm:22m"
        assert recs["embedding"]["dimension"] == 384
        assert recs["tradeoffs"]["gpu_vram_limit_mib"] == 4096

