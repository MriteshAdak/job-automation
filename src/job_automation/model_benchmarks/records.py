"""Benchmark records, schemas, candidate register, and dependency gates for MODEL-02.

Enforces:
- Attributable, versioned benchmark cells and observations.
- Explicit status values: planned, measured, failed, skipped, unsupported, pending.
- Clear separation between requested identities, inventory digests, and response digests.
- Pinned candidate licenses, provenances, and dependency gates (B1–B5, EVAL EG5).
- Precise units: milliseconds (ms), nanoseconds (ns), bytes, MiB/GiB.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from job_automation.contracts.primitives import UtcDatetime


class CellStatus(str, Enum):
    """Execution status of a benchmark cell or trial."""

    PLANNED = "planned"
    MEASURED = "measured"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"
    PENDING = "pending"


class CapabilityType(str, Enum):
    """Model capability role."""

    GENERATION = "generation"
    EMBEDDING = "embedding"


class ExecutionPlacement(str, Enum):
    """Inference placement mode."""

    CPU = "cpu"
    GPU = "gpu"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ResidencyMode(str, Enum):
    """Memory residency state for model execution."""

    COLD = "cold"
    WARM = "warm"


class DigestProvenance(str, Enum):
    """Source of verification for a model digest."""

    RESPONSE_DIGEST = "response_digest"
    INVENTORY_DIGEST = "inventory_digest"
    UNVERIFIED = "unverified"


class DependencyGateStatus(str, Enum):
    """Readiness status of an upstream or downstream dependency gate."""

    SATISFIED = "satisfied"
    PENDING = "pending"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


class DependencyGate(BaseModel):
    """Attributable dependency gate record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str = Field(description="Gate identifier: B1, B2, B3, B4, B5, EVAL_EG5")
    name: str = Field(description="Descriptive name of the gate")
    owner: str = Field(description="Component owner responsible for satisfying the gate")
    status: DependencyGateStatus = Field(description="Current status of the gate")
    evidence: str = Field(description="Observed verification evidence or blocking reason")
    next_action: str = Field(description="Next actionable step to satisfy or maintain the gate")


class CandidateLicenseRecord(BaseModel):
    """License, provenance, and quantization metadata for a model candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = Field(description="Local model identifier / tag (e.g. qwen2.5:1.5b)")
    parameter_size: str = Field(description="Parameter count specification (e.g. 1.5B, 23M)")
    format_quant: str = Field(description="Container and quantization format (e.g. GGUF / Q4_K_M, GGUF / F16)")
    source_url: str = Field(description="Upstream model card or repository URL")
    license_id: str = Field(description="SPDX license identifier (e.g. Apache-2.0, MIT)")
    copyright_notice: str = Field(description="Copyright attribution statement")
    notice_required: bool = Field(default=False, description="Whether NOTICE distribution is required")
    commercial_use_allowed: bool = Field(default=True, description="Whether commercial use is permitted")
    verified_digest: str | None = Field(default=None, description="SHA-256 digest of weights or manifest")
    provenance_notes: str = Field(default="", description="Quantizer, conversion method, or lineage notes")


class HostGpuInfo(BaseModel):
    """Hardware metadata for a single graphics controller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Device name (e.g. NVIDIA GeForce GTX 1650)")
    driver_version: str | None = Field(default=None, description="Installed display driver version")
    dedicated_vram_bytes: int | None = Field(default=None, description="Dedicated video memory in bytes")
    shared_vram_bytes: int | None = Field(default=None, description="Shared system video memory in bytes")
    compute_capability: str | None = Field(default=None, description="Compute capability (e.g. 7.5)")


class HostHardwareContext(BaseModel):
    """Complete hardware and OS snapshot captured on Windows host."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    os_caption: str = Field(description="Operating system name and edition")
    os_version: str = Field(description="Operating system release version")
    os_build: str = Field(description="Operating system build number")
    cpu_name: str = Field(description="Processor model name")
    cpu_cores: int = Field(gt=0, description="Physical CPU cores")
    cpu_logical: int = Field(gt=0, description="Logical CPU processors")
    ram_total_bytes: int = Field(gt=0, description="Total physical system RAM in bytes")
    commit_limit_bytes: int | None = Field(default=None, description="System commit limit (RAM + pagefile) in bytes")
    gpus: list[HostGpuInfo] = Field(default_factory=list, description="Detected graphics devices")
    python_version: str = Field(description="Python interpreter version")
    telemetry_tool_version: str = Field(default="v1.0", description="Instrumentation version")


class HardwareGuardrails(BaseModel):
    """Safety boundaries and abort thresholds for benchmark execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_available_ram_bytes: int = Field(
        default=512 * 1024 * 1024,
        gt=0,
        description="Minimum available physical host RAM required to start a cell (default 512 MiB)",
    )
    min_free_vram_bytes: int = Field(
        default=256 * 1024 * 1024,
        gt=0,
        description="Minimum free dedicated VRAM required for GPU acceleration cell (default 256 MiB)",
    )
    watchdog_timeout_seconds: float = Field(
        default=180.0,
        gt=0.0,
        description="Maximum wall-clock execution deadline per physical attempt",
    )


class MemorySample(BaseModel):
    """Point-in-time memory telemetry sample."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp_monotonic: float = Field(description="Monotonic timestamp in seconds")
    available_phys_bytes: int = Field(description="Available physical system RAM in bytes")
    commit_charge_bytes: int | None = Field(default=None, description="Total system commit charge in bytes")
    commit_limit_bytes: int | None = Field(default=None, description="Total system commit limit in bytes")
    python_working_set_bytes: int | None = Field(default=None, description="Python process working set in bytes")
    python_private_bytes: int | None = Field(default=None, description="Python process private bytes")
    server_working_set_bytes: int | None = Field(default=None, description="Ollama server process working set in bytes")
    server_private_bytes: int | None = Field(default=None, description="Ollama server process private bytes")
    gpu_allocated_bytes: int | None = Field(default=None, description="Allocated VRAM in bytes (from /api/ps or nvidia-smi)")
    gpu_free_bytes: int | None = Field(default=None, description="Free VRAM in bytes (from nvidia-smi if available)")


class TelemetrySummary(BaseModel):
    """Aggregated memory profile over an execution interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_available_phys_bytes: int = Field(description="Available physical RAM before execution")
    min_available_phys_bytes: int = Field(description="Minimum observed available physical RAM")
    max_python_ws_bytes: int | None = Field(default=None, description="Peak Python working set in bytes")
    max_server_ws_bytes: int | None = Field(default=None, description="Peak Ollama server working set in bytes")
    peak_gpu_allocated_bytes: int | None = Field(default=None, description="Peak GPU memory allocation in bytes")
    sample_count: int = Field(ge=0, description="Total samples gathered")
    sample_interval_ms: float = Field(gt=0, description="Target telemetry sample interval in milliseconds")


class TransportTimings(BaseModel):
    """High-precision execution and runtime phase durations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wall_duration_ms: float = Field(description="Total wall-clock duration of logical call in milliseconds")
    server_total_duration_ms: float | None = Field(default=None, description="Server total duration in milliseconds")
    server_load_duration_ms: float | None = Field(default=None, description="Server model load duration in milliseconds")
    server_prompt_eval_duration_ms: float | None = Field(default=None, description="Server prompt evaluation in ms")
    server_eval_duration_ms: float | None = Field(default=None, description="Server generation decode duration in ms")
    prompt_tokens: int | None = Field(default=None, description="Evaluated prompt token count")
    completion_tokens: int | None = Field(default=None, description="Generated completion token count")
    prompt_eval_rate_tok_s: float | None = Field(default=None, description="Prompt processing throughput (tokens/second)")
    eval_rate_tok_s: float | None = Field(default=None, description="Decoding generation throughput (tokens/second)")


class StructuredOutputResult(BaseModel):
    """Diagnostic outcome for structured generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid_json: bool = Field(description="Whether output parsed strictly as JSON without extra text")
    is_valid_schema: bool = Field(description="Whether parsed JSON conformed strictly to registered schema")
    done_reason: str | None = Field(default=None, description="Ollama completion done_reason: stop, length")
    refused: bool = Field(default=False, description="Whether the model refused to answer")
    parse_error: str | None = Field(default=None, description="JSON parse error message if any")
    validation_error: str | None = Field(default=None, description="Schema validation error message if any")
    raw_output_snippet: str | None = Field(default=None, description="Sanitized short excerpt of malformed response")


class VectorConformanceResult(BaseModel):
    """Validation outcome for embedding vector responses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector_count: int = Field(ge=0, description="Number of vectors returned")
    dimension: int = Field(ge=0, description="Observed dimension of vectors")
    is_finite: bool = Field(description="Whether all vector elements are finite float32 (no NaN/Inf)")
    l2_norm_mean: float | None = Field(default=None, description="Mean L2 norm across vectors")
    l2_norm_min: float | None = Field(default=None, description="Minimum L2 norm observed")
    l2_norm_max: float | None = Field(default=None, description="Maximum L2 norm observed")
    repeatability_cosine_similarity: float | None = Field(
        default=None, description="Cosine similarity across repeat embedding of identical input"
    )


class BenchmarkCell(BaseModel):
    """Specification of an individual benchmark measurement cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell_id: str = Field(description="Unique identifier for the benchmark cell")
    capability: CapabilityType = Field(description="Generation or embedding capability")
    model_name: str = Field(description="Model tag (e.g. qwen2.5:1.5b, all-minilm:22m)")
    context_length: int = Field(gt=0, description="Configured context token budget (e.g. 2048, 4096)")
    num_predict: int = Field(default=256, gt=0, description="Max generation output reserve in tokens")
    batch_size: int = Field(default=1, gt=0, description="Batch size for embedding calls")
    placement_requested: ExecutionPlacement = Field(description="Requested placement: cpu or gpu")
    cold_warm: ResidencyMode = Field(description="Target residency: cold (unloaded) or warm (loaded)")
    repetitions: int = Field(default=1, gt=0, description="Number of measured repetitions")
    input_case_id: str = Field(description="Test case identifier")
    prompt_template_hash: str | None = Field(default=None, description="SHA-256 fingerprint of input prompt/text")
    decoding_options: dict[str, Any] = Field(default_factory=dict, description="Decoding parameters (temperature, seed)")


class CellObservation(BaseModel):
    """Attributable result record for an individual benchmark repetition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cell_id: str = Field(description="Foreign key linking to BenchmarkCell.cell_id")
    repetition_index: int = Field(ge=0, description="0-based repetition index")
    attempt_index: int = Field(default=0, ge=0, description="0-based physical attempt index")
    cold_warm: ResidencyMode = Field(description="Observed residency state: cold or warm")
    requested_model: str = Field(description="Model identifier requested by caller")
    effective_model_tag: str = Field(description="Model identifier resolved by runtime")
    inventory_digest: str | None = Field(default=None, description="Model SHA-256 digest from /api/tags")
    response_digest: str | None = Field(default=None, description="Model SHA-256 digest from response if present")
    digest_provenance: DigestProvenance = Field(description="Source of the recorded digest")
    status: CellStatus = Field(description="Outcome status of the cell")
    error_category: str | None = Field(default=None, description="Classified error category if failed")
    error_message: str | None = Field(default=None, description="Sanitized error description if failed")
    placement_requested: ExecutionPlacement = Field(description="Requested placement mode")
    placement_observed: ExecutionPlacement = Field(description="Observed placement mode from /api/ps")
    timings: TransportTimings = Field(description="Latency and throughput timings")
    telemetry: TelemetrySummary = Field(description="Memory and resource telemetry summary")
    structured_output: StructuredOutputResult | None = Field(default=None, description="Generation structured output validation")
    vector_conformance: VectorConformanceResult | None = Field(default=None, description="Embedding vector conformance result")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional context or notes")


class BenchmarkManifest(BaseModel):
    """Complete versioned benchmark plan describing candidates, gates, and planned cells."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    manifest_id: str = Field(description="Unique manifest identifier")
    created_at: str = Field(description="ISO-8601 UTC timestamp of creation")
    description: str = Field(description="Human-readable benchmark plan description")
    target_os: str = Field(default="Windows", description="Target operating system")
    server_url: str = Field(default="http://127.0.0.1:11434", description="Loopback URL of runtime")
    guardrails: HardwareGuardrails = Field(default_factory=HardwareGuardrails)
    candidates: list[CandidateLicenseRecord] = Field(default_factory=list, description="Model candidate register")
    gates: list[DependencyGate] = Field(default_factory=list, description="Dependency gate tracking")
    cells: list[BenchmarkCell] = Field(default_factory=list, description="Planned benchmark measurement cells")

