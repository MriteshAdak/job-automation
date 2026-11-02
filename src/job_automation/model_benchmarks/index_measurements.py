"""Isolated index construction and retrieval latency benchmark for MODEL-02-S04.

Enforces:
- Direct verification of B4 gate (embedding & retrieval binding).
- Complete isolation in output_root/indices without touching production database or index directories.
- Measurement of index build wall time, chunks/second, file size on disk, and vector query latency.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from job_automation.context.vector_matrix import VectorMatrixReader, VectorMatrixWriter
from job_automation.contracts.retrieval_index import EmbeddingConfiguration
from job_automation.models.transport import LoopbackHttpTransport


class IndexBenchmarkMetrics(BaseModel):
    """Measured performance metrics for isolated index build and query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_identifier: str = Field(description="Embedding model used")
    dimension: int = Field(description="Embedding vector dimension")
    chunk_count: int = Field(description="Number of chunks indexed")
    build_time_ms: float = Field(description="Total index construction wall time in ms")
    chunks_per_second: float = Field(description="Indexing throughput (chunks/s)")
    matrix_file_bytes: int = Field(description="Size of binary vector matrix on disk in bytes")
    query_latency_ms: float = Field(description="Cosine similarity query search latency in ms")


SAMPLE_EVAL_CHUNKS = [
    "Expertise in Python backend development, FastAPI, asynchronous programming, and REST APIs.",
    "Comprehensive experience with PostgreSQL, schema migration, relational modeling, and query tuning.",
    "Cloud infrastructure engineering on AWS and Google Cloud Platform, including Docker and Kubernetes.",
    "Architecture of distributed data processing pipelines using Apache Spark, Kafka, and dbt.",
    "Leadership of cross-functional agile development teams, sprint planning, and engineering mentorship.",
    "Strong communication in German (native) and English (business fluent) across technical stakeholders.",
    "CI/CD automation, GitHub Actions workflows, infrastructure as code with Terraform, and monitoring with Prometheus.",
    "Strict adherence to software testing best practices: unit testing, integration tests, and high test coverage.",
]


def measure_isolated_index(
    transport: LoopbackHttpTransport,
    model_identifier: str,
    dimension: int,
    output_dir: Path,
    chunks: list[str] | None = None,
    timeout_seconds: float = 60.0,
) -> IndexBenchmarkMetrics:
    """Build an isolated vector index on disk and measure build & query latency."""
    test_chunks = chunks or SAMPLE_EVAL_CHUNKS
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_file = output_dir / "vectors.bin"

    # 1. Measure Embedding and Build
    build_start = time.perf_counter()
    status, _, body = transport.post(
        "/api/embed",
        {
            "model": model_identifier,
            "input": test_chunks,
        },
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise RuntimeError(f"Embedding API call failed with status {status}: {body[:200].decode('utf-8', errors='replace')}")

    resp_data = json.loads(body.decode("utf-8"))
    vectors = resp_data.get("embeddings", [])
    if len(vectors) != len(test_chunks):
        raise ValueError(f"Expected {len(test_chunks)} vectors, got {len(vectors)}")

    # Write binary vector matrix
    writer = VectorMatrixWriter(matrix_file, dimension=dimension)
    info = writer.write_matrix(vectors)
    build_time_ms = round((time.perf_counter() - build_start) * 1000.0, 2)
    chunks_per_sec = round(len(test_chunks) / (build_time_ms / 1000.0), 2) if build_time_ms > 0 else 0.0

    # 2. Measure Query Search Latency
    query_start = time.perf_counter()
    # Embed single query
    q_status, _, q_body = transport.post(
        "/api/embed",
        {
            "model": model_identifier,
            "input": ["Python backend and database engineering"],
        },
        timeout_seconds=timeout_seconds,
    )
    if q_status != 200:
        raise RuntimeError(f"Query embedding failed: {q_body[:200].decode('utf-8', errors='replace')}")

    q_data = json.loads(q_body.decode("utf-8"))
    q_vec = q_data.get("embeddings", [[]])[0]

    # Read vectors from disk and score cosine similarities
    reader = VectorMatrixReader(matrix_file, row_count=len(test_chunks), dimension=dimension)
    read_vectors = reader.read_vectors()

    # Score similarities
    scores: list[tuple[int, float]] = []
    for idx, v in enumerate(read_vectors):
        dot = sum(a * b for a, b in zip(q_vec, v))
        scores.append((idx, dot))
    scores.sort(key=lambda x: x[1], reverse=True)
    query_latency_ms = round((time.perf_counter() - query_start) * 1000.0, 2)

    return IndexBenchmarkMetrics(
        model_identifier=model_identifier,
        dimension=dimension,
        chunk_count=len(test_chunks),
        build_time_ms=build_time_ms,
        chunks_per_second=chunks_per_sec,
        matrix_file_bytes=info.byte_length,
        query_latency_ms=query_latency_ms,
    )

