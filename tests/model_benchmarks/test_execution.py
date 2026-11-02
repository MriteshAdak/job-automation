"""Tests for BenchmarkEngine execution, resumption, and guardrails."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from job_automation.model_benchmarks.configuration import build_default_phase0_manifest
from job_automation.model_benchmarks.execution import BenchmarkEngine
from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    CapabilityType,
    CellStatus,
    ExecutionPlacement,
    ResidencyMode,
)
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestExecutionEngine:
    def test_engine_resume_skips_committed_cells(self, tmp_path: Path) -> None:
        manifest = build_default_phase0_manifest()
        # Restrict to 1 small cell
        cell = BenchmarkCell(
            cell_id="test_cell_resume",
            capability=CapabilityType.EMBEDDING,
            model_name="all-minilm:22m",
            context_length=512,
            batch_size=1,
            placement_requested=ExecutionPlacement.CPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=1,
            input_case_id="case_embed_short",
        )
        manifest = manifest.model_copy(update={"cells": [cell]})

        output_root = tmp_path / "benchmarks"
        engine = BenchmarkEngine(manifest=manifest, output_root=output_root)

        # Inject fake transport
        fake_transport = ScriptedModelTransport()
        fake_transport.queue_response(
            "/api/embed",
            200,
            body={"model": "all-minilm:22m", "embeddings": [[0.1, 0.2, 0.3]]},
        )
        fake_transport.queue_response("/api/ps", 200, body={"models": []})
        fake_transport.queue_response(
            "/api/embed",
            200,
            body={"model": "all-minilm:22m", "embeddings": [[0.1, 0.2, 0.3]]},
        )
        fake_transport.queue_response("/api/generate", 200, body={})
        fake_transport.queue_response("/api/ps", 200, body={"models": []})

        engine.transport = fake_transport
        engine.observer.transport = fake_transport

        # First run executes
        res1 = engine.run(include_eval=False, include_index=False)
        assert res1.executed_trials == 1
        assert res1.skipped_trials == 0

        # Second run skips without calling transport
        res2 = engine.run(include_eval=False, include_index=False)
        assert res2.executed_trials == 0
        assert res2.skipped_trials == 1

