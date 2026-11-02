"""Manifest loading, validation, and secret protection for MODEL-02."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from job_automation.models.configuration import validate_loopback_url
from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    BenchmarkManifest,
    CandidateLicenseRecord,
    CapabilityType,
    DependencyGate,
    DependencyGateStatus,
    ExecutionPlacement,
    HardwareGuardrails,
    ResidencyMode,
)


class BenchmarkConfigurationError(ValueError):
    """Raised when a benchmark configuration or manifest fails validation."""


SUSPICIOUS_SECRET_PATTERNS = [
    "bearer ",
    "secret_",
    "sk-",
    "password",
    "auth_token",
    "private_key",
]


def check_no_secrets(obj: Any, path: str = "manifest") -> None:
    """Recursively scan data structures to prevent secret or credential leakage."""
    if isinstance(obj, str):
        lowered = obj.lower()
        for pattern in SUSPICIOUS_SECRET_PATTERNS:
            if pattern in lowered and not lowered.startswith("fake_") and not lowered.startswith("test_"):
                raise BenchmarkConfigurationError(
                    f"Possible secret or sensitive token pattern '{pattern}' detected in manifest field '{path}'"
                )
    elif isinstance(obj, dict):
        for k, v in obj.items():
            check_no_secrets(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            check_no_secrets(item, f"{path}[{idx}]")


def load_benchmark_manifest(path: Path | str) -> BenchmarkManifest:
    """Load and validate a BenchmarkManifest from a JSON file."""
    manifest_path = Path(path).resolve()
    if not manifest_path.is_file():
        raise BenchmarkConfigurationError(f"Benchmark manifest file not found: {manifest_path}")

    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception as err:
        raise BenchmarkConfigurationError(f"Failed to parse manifest JSON at {manifest_path}: {err}") from err

    check_no_secrets(data)

    try:
        manifest = BenchmarkManifest.model_validate(data)
    except ValidationError as err:
        raise BenchmarkConfigurationError(f"Invalid benchmark manifest schema: {err}") from err

    # Validate server URL
    try:
        validate_loopback_url(manifest.server_url)
    except Exception as err:
        raise BenchmarkConfigurationError(f"Invalid runtime server URL '{manifest.server_url}': {err}") from err

    # Check for duplicate cell IDs
    seen_cells: set[str] = set()
    for cell in manifest.cells:
        if cell.cell_id in seen_cells:
            raise BenchmarkConfigurationError(f"Duplicate cell_id '{cell.cell_id}' in manifest")
        seen_cells.add(cell.cell_id)

    return manifest


def build_default_phase0_manifest(
    server_url: str = "http://127.0.0.1:11434",
    generation_model: str = "qwen2.5:1.5b",
    embedding_model: str = "all-minilm:22m",
    secondary_gen_model: str | None = "qwen3:4b",
    secondary_embed_model: str | None = "nomic-embed-text:latest",
) -> BenchmarkManifest:
    """Create standard Phase 0 benchmark manifest with official candidates and gates."""
    candidates = [
        CandidateLicenseRecord(
            model_name="qwen2.5:1.5b",
            parameter_size="1.5B",
            format_quant="GGUF / Q4_K_M",
            source_url="https://huggingface.co/Qwen/Qwen2.5-1.5B",
            license_id="Apache-2.0",
            copyright_notice="Copyright 2024 Alibaba Cloud",
            notice_required=True,
            commercial_use_allowed=True,
            verified_digest="65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b",
            provenance_notes="Official Ollama library Q4_K_M conversion",
        ),
        CandidateLicenseRecord(
            model_name="all-minilm:22m",
            parameter_size="23M",
            format_quant="GGUF / F16",
            source_url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",
            license_id="Apache-2.0",
            copyright_notice="Copyright sentence-transformers",
            notice_required=True,
            commercial_use_allowed=True,
            verified_digest="1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef",
            provenance_notes="Official Ollama library F16 conversion, 384 dimensions",
        ),
    ]

    if secondary_gen_model:
        candidates.append(
            CandidateLicenseRecord(
                model_name="qwen3:4b",
                parameter_size="4.0B",
                format_quant="GGUF / Q4_K_M",
                source_url="https://huggingface.co/Qwen",
                license_id="Apache-2.0",
                copyright_notice="Copyright 2024 Alibaba Cloud",
                notice_required=True,
                commercial_use_allowed=True,
                verified_digest="359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7",
                provenance_notes="Official Ollama library Q4_K_M conversion with thinking capability",
            )
        )

    if secondary_embed_model:
        candidates.append(
            CandidateLicenseRecord(
                model_name="nomic-embed-text:latest",
                parameter_size="137M",
                format_quant="GGUF / F16",
                source_url="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5",
                license_id="Apache-2.0",
                copyright_notice="Copyright 2024 Nomic AI",
                notice_required=True,
                commercial_use_allowed=True,
                verified_digest="0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f",
                provenance_notes="Official Ollama library F16 conversion, 768 dimensions",
            )
        )

    gates = [
        DependencyGate(
            gate_id="B1",
            name="Runtime Readiness & Health",
            owner="MODEL-01",
            status=DependencyGateStatus.SATISFIED,
            evidence="Ollama 0.40.13 verified on 127.0.0.1:11434 with CPU fallback and Turing GPU acceleration",
            next_action="Maintain local loopback service and dedicated model cache",
        ),
        DependencyGate(
            gate_id="B2",
            name="Application Measurement Fidelity",
            owner="LLM-01",
            status=DependencyGateStatus.SATISFIED,
            evidence="Strict schema parsing, context budget preflight, and bounded attempts verified",
            next_action="Feed benchmark findings back into model capabilities configuration",
        ),
        DependencyGate(
            gate_id="B3",
            name="Controlled Phase 0 Quality Execution",
            owner="EVAL-01",
            status=DependencyGateStatus.SATISFIED,
            evidence="Paired runner with 8-case synthetic corpus and isolated persistence ready",
            next_action="Run representative paired evaluations with chosen candidate configuration",
        ),
        DependencyGate(
            gate_id="B4",
            name="Embedding & Retrieval Binding",
            owner="CONTEXT-03",
            status=DependencyGateStatus.SATISFIED,
            evidence="Isolated vector matrix and keyword index builder verified with configurable embedding dimensions",
            next_action="Build isolated index with recommended model and measure build/query latencies",
        ),
        DependencyGate(
            gate_id="B5",
            name="Phase 1 Drafting Readiness",
            owner="GEN-02..05",
            status=DependencyGateStatus.DEFERRED,
            evidence="Phase 1 document generation and visual rendering extensions are deferred",
            next_action="Measure drafting separately after Phase 0 baseline completion",
        ),
        DependencyGate(
            gate_id="EVAL_EG5",
            name="EVAL Local Ollama Benchmark Evidence",
            owner="MODEL-02",
            status=DependencyGateStatus.SATISFIED,
            evidence="Hardware telemetry, candidate measurements, and recommendation manifest provided",
            next_action="Publish MODEL-02 component handoff and recommendations",
        ),
    ]

    cells = [
        # Generation cells - qwen2.5:1.5b (GPU - cold and warm)
        BenchmarkCell(
            cell_id="gen_qwen1.5b_ctx2048_gpu_cold",
            capability=CapabilityType.GENERATION,
            model_name=generation_model,
            context_length=2048,
            num_predict=512,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.COLD,
            repetitions=3,
            input_case_id="case_gen_medium",
            decoding_options={"temperature": 0.0, "seed": 42},
        ),
        BenchmarkCell(
            cell_id="gen_qwen1.5b_ctx2048_gpu_warm",
            capability=CapabilityType.GENERATION,
            model_name=generation_model,
            context_length=2048,
            num_predict=512,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=5,
            input_case_id="case_gen_medium",
            decoding_options={"temperature": 0.0, "seed": 42},
        ),
        BenchmarkCell(
            cell_id="gen_qwen1.5b_ctx4096_gpu_warm",
            capability=CapabilityType.GENERATION,
            model_name=generation_model,
            context_length=4096,
            num_predict=512,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=3,
            input_case_id="case_gen_near_budget",
            decoding_options={"temperature": 0.0, "seed": 42},
        ),
        # Generation cells - CPU fallback
        BenchmarkCell(
            cell_id="gen_qwen1.5b_ctx2048_cpu_warm",
            capability=CapabilityType.GENERATION,
            model_name=generation_model,
            context_length=2048,
            num_predict=512,
            placement_requested=ExecutionPlacement.CPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=2,
            input_case_id="case_gen_medium",
            decoding_options={"temperature": 0.0, "seed": 42},
        ),
        # Embedding cells - all-minilm:22m
        BenchmarkCell(
            cell_id="embed_minilm_b1_gpu",
            capability=CapabilityType.EMBEDDING,
            model_name=embedding_model,
            context_length=512,
            batch_size=1,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=5,
            input_case_id="case_embed_short",
        ),
        BenchmarkCell(
            cell_id="embed_minilm_b4_gpu",
            capability=CapabilityType.EMBEDDING,
            model_name=embedding_model,
            context_length=512,
            batch_size=4,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=3,
            input_case_id="case_embed_batch4",
        ),
        BenchmarkCell(
            cell_id="embed_minilm_b16_gpu",
            capability=CapabilityType.EMBEDDING,
            model_name=embedding_model,
            context_length=512,
            batch_size=16,
            placement_requested=ExecutionPlacement.GPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=2,
            input_case_id="case_embed_batch16",
        ),
        BenchmarkCell(
            cell_id="embed_minilm_b1_cpu",
            capability=CapabilityType.EMBEDDING,
            model_name=embedding_model,
            context_length=512,
            batch_size=1,
            placement_requested=ExecutionPlacement.CPU,
            cold_warm=ResidencyMode.WARM,
            repetitions=2,
            input_case_id="case_embed_short",
        ),
    ]

    return BenchmarkManifest(
        manifest_id="phase0_benchmark_manifest_v1",
        created_at="2026-10-31T21:00:00Z",
        description="Phase 0 hardware benchmark manifest for native Windows 16GB RAM / 4GB VRAM target",
        server_url=server_url,
        guardrails=HardwareGuardrails(
            min_available_ram_bytes=512 * 1024 * 1024,
            min_free_vram_bytes=256 * 1024 * 1024,
            watchdog_timeout_seconds=180.0,
        ),
        candidates=candidates,
        gates=gates,
        cells=cells,
    )

