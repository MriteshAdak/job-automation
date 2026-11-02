"""Tests for embedding benchmark execution harness with scripted transport."""

from __future__ import annotations

import math

from job_automation.model_benchmarks.embedding_runs import (
    compute_cosine_similarity,
    compute_vector_conformance,
    execute_embedding_cell,
)
from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    CapabilityType,
    CellStatus,
    ExecutionPlacement,
    ResidencyMode,
)
from job_automation.model_benchmarks.telemetry import HostTelemetrySampler
from job_automation.model_benchmarks.transport_observer import TransportObserver
from tests.fakes.model_transport import ScriptedModelTransport


class TestEmbeddingRuns:
    def test_compute_vector_conformance_valid(self) -> None:
        vectors = [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ]
        conf = compute_vector_conformance(vectors)
        assert conf.vector_count == 2
        assert conf.dimension == 3
        assert conf.is_finite is True
        assert conf.l2_norm_mean is not None

    def test_compute_vector_conformance_nan_inf(self) -> None:
        vectors = [
            [0.1, float("nan"), 0.3],
        ]
        conf = compute_vector_conformance(vectors)
        assert conf.is_finite is False

    def test_compute_cosine_similarity(self) -> None:
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0]
        sim = compute_cosine_similarity(vec_a, vec_b)
        assert math.isclose(sim, 1.0)

        vec_c = [0.0, 1.0, 0.0]
        sim_ortho = compute_cosine_similarity(vec_a, vec_c)
        assert math.isclose(sim_ortho, 0.0)

    def test_execute_embedding_cell_success(self) -> None:
        transport = ScriptedModelTransport()
        # Mock initial embed response
        transport.queue_response(
            "/api/embed",
            200,
            body={
                "model": "all-minilm:22m",
                "embeddings": [[0.1, 0.2, 0.3]],
                "total_duration": 50_000_000,
            },
        )
        # Mock residency check
        transport.queue_response(
            "/api/ps",
            200,
            body={"models": [{"name": "all-minilm:22m", "size_vram": 30000000}]},
        )
        # Mock repeat call for cosine similarity check
        transport.queue_response(
            "/api/embed",
            200,
            body={
                "model": "all-minilm:22m",
                "embeddings": [[0.1, 0.2, 0.3]],
            },
        )

        observer = TransportObserver(transport=transport)
        sampler = HostTelemetrySampler(sample_interval_seconds=0.05)

        cell = BenchmarkCell(
            cell_id="embed_test_01",
            capability=CapabilityType.EMBEDDING,
            model_name="all-minilm:22m",
            context_length=512,
            batch_size=1,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=1,
            input_case_id="case_embed_short",
        )

        obs = execute_embedding_cell(
            cell=cell,
            repetition_index=0,
            transport=transport,
            observer=observer,
            sampler=sampler,
        )

        assert obs.status == CellStatus.MEASURED
        assert obs.placement_observed == ExecutionPlacement.GPU
        assert obs.vector_conformance is not None
        assert obs.vector_conformance.is_finite is True
        assert obs.vector_conformance.dimension == 3
        assert obs.vector_conformance.repeatability_cosine_similarity is not None
        assert math.isclose(obs.vector_conformance.repeatability_cosine_similarity, 1.0)

