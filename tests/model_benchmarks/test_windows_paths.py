"""Tests for native Windows path resilience with spaces and German umlauts."""

from __future__ import annotations

import json
from pathlib import Path

from job_automation.model_benchmarks.artifacts import BenchmarkArtifactStore
from job_automation.model_benchmarks.configuration import build_default_phase0_manifest
from job_automation.model_benchmarks.records import (
    CellObservation,
    CellStatus,
    DigestProvenance,
    ExecutionPlacement,
    ResidencyMode,
    TelemetrySummary,
    TransportTimings,
)


class TestWindowsPaths:
    def test_artifact_store_with_umlauts_and_spaces(self, tmp_path: Path) -> None:
        special_dir = tmp_path / "JobAutomation Benchmarks Prüfung äöü ß"
        store = BenchmarkArtifactStore(root_dir=special_dir)
        store.initialize_directories()

        assert special_dir.is_dir()
        assert (special_dir / "observations").is_dir()

        obs = CellObservation(
            cell_id="gen_cell_äöü_1",
            repetition_index=0,
            attempt_index=0,
            cold_warm=ResidencyMode.WARM,
            requested_model="qwen2.5:1.5b",
            effective_model_tag="qwen2.5:1.5b",
            digest_provenance=DigestProvenance.UNVERIFIED,
            status=CellStatus.MEASURED,
            placement_requested=ExecutionPlacement.GPU,
            placement_observed=ExecutionPlacement.GPU,
            timings=TransportTimings(wall_duration_ms=100.0),
            telemetry=TelemetrySummary(
                baseline_available_phys_bytes=1000000,
                min_available_phys_bytes=1000000,
                sample_count=1,
                sample_interval_ms=200.0,
            ),
        )

        saved = store.save_observation(obs)
        assert saved.is_file()

        loaded = store.load_observation("gen_cell_äöü_1", 0)
        assert loaded is not None
        assert loaded.cell_id == "gen_cell_äöü_1"

