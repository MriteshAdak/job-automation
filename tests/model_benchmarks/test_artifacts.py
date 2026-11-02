"""Tests for benchmark artifact storage and path isolation."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.model_benchmarks.artifacts import (
    BenchmarkArtifactStore,
    BenchmarkPathError,
)
from job_automation.model_benchmarks.records import (
    CellObservation,
    CellStatus,
    DigestProvenance,
    ExecutionPlacement,
    ResidencyMode,
    TelemetrySummary,
    TransportTimings,
)


class TestBenchmarkArtifacts:
    def test_store_creates_isolated_directories(self, tmp_path: Path) -> None:
        root = tmp_path / "benchmarks"
        store = BenchmarkArtifactStore(root_dir=root)
        store.initialize_directories()

        assert store.observations_dir.is_dir()
        assert store.telemetry_dir.is_dir()
        assert store.reports_dir.is_dir()
        assert store.indices_dir.is_dir()

    def test_production_root_aliasing_rejected(self, tmp_path: Path) -> None:
        prod_dir = tmp_path / "Production"
        prod_dir.mkdir()

        # Exact match
        with pytest.raises(BenchmarkPathError, match="matches production data root"):
            BenchmarkArtifactStore(root_dir=prod_dir, production_data_root=prod_dir)

        # Nested in production
        nested = prod_dir / "benchmarks"
        with pytest.raises(BenchmarkPathError, match="nested inside production data root"):
            BenchmarkArtifactStore(root_dir=nested, production_data_root=prod_dir)

    def test_atomic_observation_save_and_load(self, tmp_path: Path) -> None:
        root = tmp_path / "benchmarks"
        store = BenchmarkArtifactStore(root_dir=root)

        obs = CellObservation(
            cell_id="gen_cell_1",
            repetition_index=0,
            attempt_index=0,
            cold_warm=ResidencyMode.COLD,
            requested_model="qwen2.5:1.5b",
            effective_model_tag="qwen2.5:1.5b",
            inventory_digest="sha256:1111",
            digest_provenance=DigestProvenance.INVENTORY_DIGEST,
            status=CellStatus.MEASURED,
            placement_requested=ExecutionPlacement.GPU,
            placement_observed=ExecutionPlacement.GPU,
            timings=TransportTimings(wall_duration_ms=1234.5),
            telemetry=TelemetrySummary(
                baseline_available_phys_bytes=8000000000,
                min_available_phys_bytes=7800000000,
                sample_count=5,
                sample_interval_ms=200.0,
            ),
        )

        saved_path = store.save_observation(obs)
        assert saved_path.is_file()
        assert store.has_observation("gen_cell_1", 0) is True

        loaded = store.load_observation("gen_cell_1", 0)
        assert loaded is not None
        assert loaded.cell_id == "gen_cell_1"
        assert loaded.timings.wall_duration_ms == 1234.5

        all_obs = store.list_observations()
        assert len(all_obs) == 1

