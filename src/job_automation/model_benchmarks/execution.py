"""Master benchmark orchestration engine for MODEL-02 (S02, S03, S04).

Enforces:
- Orderly, isolated execution of planned benchmark cells.
- Atomic checkpointing of each finished observation to disk.
- Safe resume capability: skips already-committed cells without re-running inference.
- Strict hardware guardrails: aborts before cell start if available physical RAM < threshold.
- Full cleanup: unloads models on completion or failure.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from job_automation.model_benchmarks.artifacts import BenchmarkArtifactStore
from job_automation.model_benchmarks.embedding_runs import execute_embedding_cell
from job_automation.model_benchmarks.evaluation_adapter import (
    EvaluationComparisonSummary,
    run_paired_model_evaluation,
)
from job_automation.model_benchmarks.generation_runs import execute_generation_cell
from job_automation.model_benchmarks.index_measurements import (
    IndexBenchmarkMetrics,
    measure_isolated_index,
)
from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    BenchmarkManifest,
    CapabilityType,
    CellObservation,
    CellStatus,
    HostHardwareContext,
)
from job_automation.model_benchmarks.telemetry import (
    HostTelemetrySampler,
    capture_host_hardware_context,
    get_system_memory_status,
)
from job_automation.model_benchmarks.transport_observer import TransportObserver
from job_automation.models.runtime_health import LoopbackHttpClient
from job_automation.models.schemas import (
    LocalSchemaRegistry,
    build_default_schema_registry,
)
from job_automation.models.transport import LoopbackHttpTransport


class BenchmarkExecutionResult(BaseModel):
    """Overall outcome of a benchmark execution run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: str
    total_planned_trials: int
    executed_trials: int
    skipped_trials: int
    failed_trials: int
    overall_status: str  # "completed", "incomplete", "failed"
    index_metrics: IndexBenchmarkMetrics | None = None
    eval_summary: EvaluationComparisonSummary | None = None
    observations: list[CellObservation] = Field(default_factory=list)


class BenchmarkEngine:
    """Orchestrates benchmark measurement matrix across generation and embedding cells."""

    def __init__(
        self,
        manifest: BenchmarkManifest,
        output_root: Path | str,
        production_data_root: Path | str | None = None,
        schema_registry: LocalSchemaRegistry | None = None,
    ) -> None:
        self.manifest = manifest
        self.store = BenchmarkArtifactStore(
            root_dir=output_root, production_data_root=production_data_root
        )
        self.schema_registry = (
            schema_registry if schema_registry is not None else build_default_schema_registry()
        )
        self.transport = LoopbackHttpTransport(base_url=manifest.server_url)
        self.observer = TransportObserver(transport=self.transport)
        self.sampler = HostTelemetrySampler(sample_interval_seconds=0.2)
        self.hardware = capture_host_hardware_context()

    def run(
        self,
        target_cell_id: str | None = None,
        include_eval: bool = True,
        include_index: bool = True,
    ) -> BenchmarkExecutionResult:
        """Execute benchmark cells with atomic checkpointing and resumption."""
        self.store.initialize_directories()
        self.store.save_manifest(self.manifest)

        # 1. Fetch runtime inventory digests
        inventory_digests: dict[str, str] = {}
        try:
            client = LoopbackHttpClient(base_url=self.manifest.server_url)
            status, _, body = client.request("GET", "/api/tags", timeout_seconds=5.0)
            if status == 200:
                tag_data = json.loads(body.decode("utf-8"))
                for m in tag_data.get("models", []):
                    name = m.get("name") or m.get("model")
                    digest = m.get("digest")
                    if name and digest:
                        inventory_digests[name] = digest
        except Exception:
            pass

        # 2. Select target cells
        planned_cells = self.manifest.cells
        if target_cell_id:
            planned_cells = [c for c in planned_cells if c.cell_id == target_cell_id]
            if not planned_cells:
                raise ValueError(f"Cell ID '{target_cell_id}' not found in manifest")

        total_trials = sum(c.repetitions for c in planned_cells)
        executed_count = 0
        skipped_count = 0
        failed_count = 0
        collected_observations: list[CellObservation] = []

        # 3. Execute cells
        try:
            for cell in planned_cells:
                for rep in range(cell.repetitions):
                    # Check for existing checkpoint
                    if self.store.has_observation(cell.cell_id, rep):
                        existing = self.store.load_observation(cell.cell_id, rep)
                        if existing is not None:
                            collected_observations.append(existing)
                            skipped_count += 1
                            continue

                    # Preflight Guardrail Check
                    mem = get_system_memory_status()
                    avail_phys = mem.get("avail_phys", 0)
                    if avail_phys < self.manifest.guardrails.min_available_ram_bytes:
                        raise RuntimeError(
                            f"Host available physical RAM ({round(avail_phys / 1024**2, 1)} MiB) is below "
                            f"guardrail threshold ({round(self.manifest.guardrails.min_available_ram_bytes / 1024**2, 1)} MiB). "
                            "Aborting benchmark safely to prevent system instability."
                        )

                    digest = inventory_digests.get(cell.model_name)

                    if cell.capability == CapabilityType.GENERATION:
                        obs = execute_generation_cell(
                            cell=cell,
                            repetition_index=rep,
                            transport=self.transport,
                            observer=self.observer,
                            sampler=self.sampler,
                            schema_registry=self.schema_registry,
                            inventory_digest=digest,
                            timeout_seconds=self.manifest.guardrails.watchdog_timeout_seconds,
                        )
                    else:
                        obs = execute_embedding_cell(
                            cell=cell,
                            repetition_index=rep,
                            transport=self.transport,
                            observer=self.observer,
                            sampler=self.sampler,
                            inventory_digest=digest,
                            timeout_seconds=self.manifest.guardrails.watchdog_timeout_seconds,
                        )

                    # Atomically save observation
                    self.store.save_observation(obs)
                    collected_observations.append(obs)
                    executed_count += 1
                    if obs.status == CellStatus.FAILED:
                        failed_count += 1

            # 4. Optional Isolated Index Benchmark (CONTEXT-03 binding)
            index_metrics: IndexBenchmarkMetrics | None = None
            if include_index:
                try:
                    index_dir = self.store.indices_dir / "isolated_benchmark_index"
                    index_metrics = measure_isolated_index(
                        transport=self.transport,
                        model_identifier="all-minilm:22m",
                        dimension=384,
                        output_dir=index_dir,
                    )
                except Exception:
                    pass

            # 5. Optional EVAL-01 Paired Evaluation (B3 gate)
            eval_summary: EvaluationComparisonSummary | None = None
            if include_eval:
                try:
                    eval_summary = run_paired_model_evaluation(
                        output_dir=self.store.root_dir,
                        model_name="qwen2.5:1.5b",
                        transport=self.transport,
                        model_digest=inventory_digests.get("qwen2.5:1.5b"),
                        max_cases=4,
                    )
                except Exception:
                    pass

        finally:
            # Full unload cleanup
            for c in planned_cells:
                self.observer.unload_model(c.model_name)

        overall_status = "completed" if failed_count == 0 else "incomplete"

        return BenchmarkExecutionResult(
            manifest_id=self.manifest.manifest_id,
            total_planned_trials=total_trials,
            executed_trials=executed_count,
            skipped_trials=skipped_count,
            failed_trials=failed_count,
            overall_status=overall_status,
            index_metrics=index_metrics,
            eval_summary=eval_summary,
            observations=collected_observations,
        )
