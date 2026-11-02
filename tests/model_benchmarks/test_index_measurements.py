"""Tests for isolated index benchmarking (CONTEXT-03 binding)."""

from __future__ import annotations

from pathlib import Path

from job_automation.model_benchmarks.index_measurements import measure_isolated_index
from tests.fakes.model_transport import ScriptedModelTransport


class TestIndexMeasurements:
    def test_measure_isolated_index_scripted(self, tmp_path: Path) -> None:
        transport = ScriptedModelTransport()
        test_chunks = ["Chunk 1", "Chunk 2"]

        # 1. Chunks embed response (dimension 3)
        transport.queue_response(
            "/api/embed",
            200,
            body={
                "model": "all-minilm:22m",
                "embeddings": [
                    [0.1, 0.2, 0.3],
                    [0.4, 0.5, 0.6],
                ],
            },
        )
        # 2. Query embed response (dimension 3)
        transport.queue_response(
            "/api/embed",
            200,
            body={
                "model": "all-minilm:22m",
                "embeddings": [
                    [0.1, 0.2, 0.3],
                ],
            },
        )

        index_dir = tmp_path / "isolated_index"
        metrics = measure_isolated_index(
            transport=transport,
            model_identifier="all-minilm:22m",
            dimension=3,
            output_dir=index_dir,
            chunks=test_chunks,
        )

        assert metrics.chunk_count == 2
        assert metrics.dimension == 3
        assert metrics.matrix_file_bytes == 2 * 3 * 4  # 24 bytes
        assert (index_dir / "vectors.bin").is_file()
        assert metrics.build_time_ms >= 0.0
        assert metrics.query_latency_ms >= 0.0

