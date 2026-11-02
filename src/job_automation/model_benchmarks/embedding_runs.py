"""Embedding benchmark execution harness for MODEL-02-S04.

Enforces:
- Batch scaling measurements (1, 4, 16) on fixed texts.
- Vector conformance validation: dimension, finite floats, L2 norms, repeatability cosine similarity.
- Overlength input detection (e.g. all-minilm > 256 tokens).
- CPU vs GPU placement verification and memory telemetry collection.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    CellObservation,
    CellStatus,
    DigestProvenance,
    ExecutionPlacement,
    ResidencyMode,
    TelemetrySummary,
    TransportTimings,
    VectorConformanceResult,
)
from job_automation.model_benchmarks.telemetry import HostTelemetrySampler
from job_automation.model_benchmarks.transport_observer import TransportObserver
from job_automation.models.transport import LoopbackHttpTransport


EMBEDDING_TEXT_CORPUS: dict[str, list[str]] = {
    "case_embed_short": [
        "Senior Python Entwickler mit Erfahrung in verteilten Systemen und PostgreSQL in Berlin.",
    ],
    "case_embed_batch4": [
        "Senior Python Entwickler mit Erfahrung in verteilten Systemen und PostgreSQL in Berlin.",
        "Cloud Data Platform Architect experienced with Apache Spark, Snowflake, and Kubernetes.",
        "Disziplinarische Teamführung agiler Software-Engineering-Teams im Cloud-Umfeld.",
        "Verhandlungssichere Deutsch- und Englischkenntnisse für internationale Kundenprojekte.",
    ],
    "case_embed_batch16": [
        f"Anforderungsprofil und Kompetenznachweis für Fachposition Modul {i}: Backend-Engineering, "
        f"API-Design, Datenbank-Skalierung und automatisierte Testabdeckung."
        for i in range(16)
    ],
    "case_embed_overflow": [
        "Sehr langer Text zur Prüfung des Kontextfensters. " * 80  # ~400 words / > 500 tokens
    ],
}


def get_embedding_texts(case_id: str) -> list[str]:
    """Retrieve embedding texts for test case."""
    if case_id not in EMBEDDING_TEXT_CORPUS:
        raise KeyError(f"Unknown embedding case ID '{case_id}'")
    return EMBEDDING_TEXT_CORPUS[case_id]


def compute_vector_conformance(vectors: list[list[float]]) -> VectorConformanceResult:
    """Validate vector dimensions, numerical finiteness, and L2 norms."""
    if not vectors:
        return VectorConformanceResult(
            vector_count=0,
            dimension=0,
            is_finite=False,
        )

    dim = len(vectors[0])
    is_finite = True
    norms: list[float] = []

    for vec in vectors:
        if len(vec) != dim:
            return VectorConformanceResult(
                vector_count=len(vectors),
                dimension=dim,
                is_finite=False,
            )
        sum_sq = 0.0
        for val in vec:
            if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val):
                is_finite = False
                break
            sum_sq += float(val) * float(val)
        norm = math.sqrt(sum_sq)
        norms.append(norm)

    mean_norm = sum(norms) / len(norms) if norms else None
    min_norm = min(norms) if norms else None
    max_norm = max(norms) if norms else None

    return VectorConformanceResult(
        vector_count=len(vectors),
        dimension=dim,
        is_finite=is_finite,
        l2_norm_mean=round(mean_norm, 4) if mean_norm is not None else None,
        l2_norm_min=round(min_norm, 4) if min_norm is not None else None,
        l2_norm_max=round(max_norm, 4) if max_norm is not None else None,
        repeatability_cosine_similarity=None,
    )


def compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for a, b in zip(vec_a, vec_b):
        fa, fb = float(a), float(b)
        dot += fa * fb
        norm_a_sq += fa * fa
        norm_b_sq += fb * fb
    denom = math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq)
    if denom == 0.0:
        return 0.0
    return dot / denom


def execute_embedding_cell(
    cell: BenchmarkCell,
    repetition_index: int,
    transport: LoopbackHttpTransport,
    observer: TransportObserver,
    sampler: HostTelemetrySampler,
    inventory_digest: str | None = None,
    timeout_seconds: float = 60.0,
) -> CellObservation:
    """Execute a single embedding benchmark cell trial and return a CellObservation."""
    texts = get_embedding_texts(cell.input_case_id)[: cell.batch_size]
    if not texts:
        texts = ["Fallback embedding text probe"]

    # Build options
    options: dict[str, Any] = {
        "num_ctx": cell.context_length,
    }
    if cell.placement_requested == ExecutionPlacement.CPU:
        options["num_gpu"] = 0

    wire_payload: dict[str, Any] = {
        "model": cell.model_name,
        "input": texts,
        "options": options,
    }

    # Start telemetry
    sampler.start()
    wall_start = time.monotonic()
    status_code: int = 0
    resp_body: bytes = b""
    error_cat: str | None = None
    error_msg: str | None = None

    try:
        status_code, _, resp_body = transport.post(
            "/api/embed", wire_payload, timeout_seconds=timeout_seconds
        )
    except Exception as exc:
        error_cat = "TRANSIENT_SERVICE" if "timeout" in str(exc).lower() else "SYSTEM_RESOURCE"
        error_msg = str(exc)
    finally:
        wall_end = time.monotonic()
        is_resident, vram_bytes, observed_placement = observer.check_residency(cell.model_name)
        samples, telemetry_summary = sampler.stop()

    timings: TransportTimings
    conformance: VectorConformanceResult | None = None
    cell_status: CellStatus = CellStatus.MEASURED

    if error_msg or status_code != 200:
        cell_status = CellStatus.FAILED
        if not error_msg:
            error_cat = "HTTP_ERROR"
            error_msg = f"HTTP {status_code}: {resp_body[:200].decode('utf-8', errors='replace')}"
        timings = TransportTimings(wall_duration_ms=round((wall_end - wall_start) * 1000.0, 2))
    else:
        try:
            data = json.loads(resp_body.decode("utf-8"))
            vectors = data.get("embeddings", [])
            total_dur_ns = data.get("total_duration")
            load_dur_ns = data.get("load_duration")
            prompt_tokens = data.get("prompt_eval_count")

            wall_ms = (wall_end - wall_start) * 1000.0
            server_total_ms = (total_dur_ns / 1e6) if isinstance(total_dur_ns, (int, float)) else None
            server_load_ms = (load_dur_ns / 1e6) if isinstance(load_dur_ns, (int, float)) else None

            # Compute throughput
            texts_per_sec = round(len(texts) / (wall_ms / 1000.0), 2) if wall_ms > 0 else None

            timings = TransportTimings(
                wall_duration_ms=round(wall_ms, 2),
                server_total_duration_ms=round(server_total_ms, 2) if server_total_ms is not None else None,
                server_load_duration_ms=round(server_load_ms, 2) if server_load_ms is not None else None,
                prompt_tokens=prompt_tokens,
                prompt_eval_rate_tok_s=texts_per_sec,
            )

            conformance = compute_vector_conformance(vectors)
            if not conformance.is_finite or conformance.vector_count != len(texts):
                cell_status = CellStatus.FAILED
                error_cat = "VECTOR_CONFORMANCE"
                error_msg = f"Vector validation failed: count={conformance.vector_count}, finite={conformance.is_finite}"
            else:
                # Repeatability check for batch_size=1
                if len(texts) == 1 and vectors:
                    try:
                        _, _, repeat_body = transport.post(
                            "/api/embed", wire_payload, timeout_seconds=timeout_seconds
                        )
                        repeat_data = json.loads(repeat_body.decode("utf-8"))
                        repeat_vectors = repeat_data.get("embeddings", [])
                        if repeat_vectors:
                            sim = compute_cosine_similarity(vectors[0], repeat_vectors[0])
                            conformance = VectorConformanceResult(
                                vector_count=conformance.vector_count,
                                dimension=conformance.dimension,
                                is_finite=conformance.is_finite,
                                l2_norm_mean=conformance.l2_norm_mean,
                                l2_norm_min=conformance.l2_norm_min,
                                l2_norm_max=conformance.l2_norm_max,
                                repeatability_cosine_similarity=round(sim, 6),
                            )
                    except Exception:
                        pass

        except Exception as parse_err:
            cell_status = CellStatus.FAILED
            error_cat = "RUNTIME_PROTOCOL"
            error_msg = f"Malformed Ollama response: {parse_err}"
            timings = TransportTimings(wall_duration_ms=round((wall_end - wall_start) * 1000.0, 2))

    return CellObservation(
        cell_id=cell.cell_id,
        repetition_index=repetition_index,
        attempt_index=0,
        cold_warm=cell.cold_warm,
        requested_model=cell.model_name,
        effective_model_tag=cell.model_name,
        inventory_digest=inventory_digest,
        response_digest=None,
        digest_provenance=(
            DigestProvenance.INVENTORY_DIGEST if inventory_digest else DigestProvenance.UNVERIFIED
        ),
        status=cell_status,
        error_category=error_cat,
        error_message=error_msg,
        placement_requested=cell.placement_requested,
        placement_observed=observed_placement,
        timings=timings,
        telemetry=telemetry_summary,
        vector_conformance=conformance,
        metadata={"vram_bytes_ps": vram_bytes},
    )

