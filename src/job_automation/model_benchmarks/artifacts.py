"""Isolated artifact storage and atomic persistence for MODEL-02.

Enforces:
- Strict path isolation preventing overlap or aliasing into production data or database directories.
- Atomic file writes using temporary file rename to prevent partial/corrupt observations.
- Proper handling of native Windows paths with spaces and international characters (umlauts).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from job_automation.model_benchmarks.records import (
    BenchmarkManifest,
    CellObservation,
)


class BenchmarkPathError(ValueError):
    """Raised when a benchmark path is invalid or aliases production storage."""


class BenchmarkArtifactStore:
    """Manages isolated disk storage for benchmark manifests, checkpoints, and reports."""

    def __init__(self, root_dir: Path | str, production_data_root: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.production_data_root = (
            Path(production_data_root).resolve() if production_data_root else None
        )
        self._validate_root_isolation()
        self.observations_dir = self.root_dir / "observations"
        self.telemetry_dir = self.root_dir / "telemetry"
        self.reports_dir = self.root_dir / "reports"
        self.indices_dir = self.root_dir / "indices"

    def _validate_root_isolation(self) -> None:
        """Ensure benchmark root does not alias production storage."""
        if not self.production_data_root:
            return

        try:
            prod_resolved = self.production_data_root.resolve()
            root_resolved = self.root_dir.resolve()
        except Exception as err:
            raise BenchmarkPathError(f"Failed to resolve path: {err}") from err

        # Windows case-folded comparison
        prod_norm = str(prod_resolved).lower()
        root_norm = str(root_resolved).lower()

        if root_norm == prod_norm:
            raise BenchmarkPathError(
                f"Benchmark root '{self.root_dir}' matches production data root '{self.production_data_root}'. "
                "Benchmark storage must be strictly isolated from production data."
            )

        if root_norm.startswith(prod_norm + os.sep.lower()):
            raise BenchmarkPathError(
                f"Benchmark root '{self.root_dir}' is nested inside production data root '{self.production_data_root}'."
            )

        if prod_norm.startswith(root_norm + os.sep.lower()):
            raise BenchmarkPathError(
                f"Production data root '{self.production_data_root}' is nested inside benchmark root '{self.root_dir}'."
            )

    def initialize_directories(self) -> None:
        """Create necessary subdirectories."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.observations_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.indices_dir.mkdir(parents=True, exist_ok=True)

    def get_observation_path(self, cell_id: str, repetition_index: int = 0) -> Path:
        """Generate safe file path for a cell observation."""
        safe_cell = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in cell_id)
        filename = f"{safe_cell}_rep{repetition_index}.json"
        return self.observations_dir / filename

    def has_observation(self, cell_id: str, repetition_index: int = 0) -> bool:
        """Check if an observation already exists and is valid."""
        path = self.get_observation_path(cell_id, repetition_index)
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("status") in ("measured", "skipped", "unsupported", "failed")
        except Exception:
            return False

    def save_observation(self, observation: CellObservation) -> Path:
        """Atomically persist a cell observation."""
        self.initialize_directories()
        path = self.get_observation_path(observation.cell_id, observation.repetition_index)
        temp_path = path.with_suffix(".tmp")

        payload = observation.model_dump(mode="json")
        json_str = json.dumps(payload, indent=2, ensure_ascii=False)

        temp_path.write_text(json_str, encoding="utf-8")
        temp_path.replace(path)
        return path

    def load_observation(self, cell_id: str, repetition_index: int = 0) -> CellObservation | None:
        """Load an observation if it exists."""
        path = self.get_observation_path(cell_id, repetition_index)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return CellObservation.model_validate(data)

    def list_observations(self) -> list[CellObservation]:
        """Load all committed observations."""
        if not self.observations_dir.is_dir():
            return []
        observations: list[CellObservation] = []
        for file in sorted(self.observations_dir.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                obs = CellObservation.model_validate(data)
                observations.append(obs)
            except Exception:
                continue
        return observations

    def save_manifest(self, manifest: BenchmarkManifest) -> Path:
        """Atomically persist a benchmark manifest."""
        self.initialize_directories()
        path = self.root_dir / "benchmark_manifest.json"
        temp_path = path.with_suffix(".tmp")

        payload = manifest.model_dump(mode="json")
        json_str = json.dumps(payload, indent=2, ensure_ascii=False)

        temp_path.write_text(json_str, encoding="utf-8")
        temp_path.replace(path)
        return path

    def load_manifest(self) -> BenchmarkManifest | None:
        """Load manifest from root directory."""
        path = self.root_dir / "benchmark_manifest.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return BenchmarkManifest.model_validate(data)

