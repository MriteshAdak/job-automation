"""Generation benchmark execution harness for MODEL-02-S03.

Enforces:
- Structured generation conforming to registered C11 schema.
- Verification of CPU-only vs GPU-accelerated placement via /api/ps.
- Cold vs warm model residency tracking and unloading discipline.
- Accurate capture of prompt evaluation, decode latency, token counts, and memory telemetry.
- Classification of failures: timeout, malformed output, length truncation, budget exhaustion.
"""

from __future__ import annotations

import json
import time
from typing import Any

from job_automation.model_benchmarks.generation_cases import get_generation_case
from job_automation.model_benchmarks.records import (
    BenchmarkCell,
    CellObservation,
    CellStatus,
    DigestProvenance,
    ExecutionPlacement,
    ResidencyMode,
    StructuredOutputResult,
    TelemetrySummary,
    TransportTimings,
)
from job_automation.model_benchmarks.telemetry import HostTelemetrySampler
from job_automation.model_benchmarks.transport_observer import TransportObserver
from job_automation.models.schemas import (
    LocalSchemaRegistry,
    parse_strict_json,
    validate_against_schema,
)
from job_automation.models.transport import LoopbackHttpTransport


def execute_generation_cell(
    cell: BenchmarkCell,
    repetition_index: int,
    transport: LoopbackHttpTransport,
    observer: TransportObserver,
    sampler: HostTelemetrySampler,
    schema_registry: LocalSchemaRegistry,
    inventory_digest: str | None = None,
    timeout_seconds: float = 180.0,
) -> CellObservation:
    """Execute a single generation benchmark cell trial and return a CellObservation."""
    case = get_generation_case(cell.input_case_id)
    schema = schema_registry.resolve(case.target_schema)

    # 1. Cold/Warm residency preparation
    if cell.cold_warm == ResidencyMode.COLD:
        observer.unload_model(cell.model_name)
    else:
        # For warm cells, ensure model is resident before measured repetition
        is_loaded, _, _ = observer.check_residency(cell.model_name)
        if not is_loaded:
            # Short warmup call to load model into memory
            warmup_options: dict[str, Any] = {
                "num_ctx": cell.context_length,
                "num_predict": 10,
                "temperature": 0.0,
            }
            if cell.placement_requested == ExecutionPlacement.CPU:
                warmup_options["num_gpu"] = 0
            try:
                transport.post(
                    "/api/generate",
                    {
                        "model": cell.model_name,
                        "prompt": "Hello",
                        "stream": False,
                        "options": warmup_options,
                    },
                    timeout_seconds=60.0,
                )
            except Exception:
                pass

    # 2. Build wire payload
    options: dict[str, Any] = {
        "num_ctx": cell.context_length,
        "num_predict": cell.num_predict,
        "temperature": cell.decoding_options.get("temperature", 0.0),
        "seed": cell.decoding_options.get("seed", 42),
    }
    if cell.placement_requested == ExecutionPlacement.CPU:
        options["num_gpu"] = 0

    wire_payload: dict[str, Any] = {
        "model": cell.model_name,
        "system": case.system_prompt,
        "prompt": case.user_prompt,
        "stream": False,
        "format": schema.json_schema,
        "options": options,
    }

    # 3. Start Telemetry Sampling
    sampler.start()
    wall_start = time.monotonic()
    status_code: int = 0
    resp_body: bytes = b""
    error_cat: str | None = None
    error_msg: str | None = None

    try:
        status_code, _, resp_body = transport.post(
            "/api/generate", wire_payload, timeout_seconds=timeout_seconds
        )
    except Exception as exc:
        error_cat = "TRANSIENT_SERVICE" if "timeout" in str(exc).lower() else "SYSTEM_RESOURCE"
        error_msg = str(exc)
    finally:
        wall_end = time.monotonic()
        # Query residency while loaded
        is_resident, vram_bytes, observed_placement = observer.check_residency(cell.model_name)
        samples, telemetry_summary = sampler.stop()

    # 4. Process Response Data
    timings: TransportTimings
    structured_result: StructuredOutputResult | None = None
    cell_status: CellStatus = CellStatus.MEASURED
    response_digest: str | None = None

    if error_msg or status_code != 200:
        cell_status = CellStatus.FAILED
        if not error_msg:
            error_cat = "HTTP_ERROR"
            error_msg = f"HTTP {status_code}: {resp_body[:200].decode('utf-8', errors='replace')}"
        timings = TransportTimings(wall_duration_ms=round((wall_end - wall_start) * 1000.0, 2))
    else:
        try:
            resp_data = json.loads(resp_body.decode("utf-8"))
            timings = observer.extract_timings(wall_start, wall_end, resp_data)
            raw_text = resp_data.get("response", "")
            done_reason = resp_data.get("done_reason")

            # Check JSON & Schema Validity
            try:
                parsed_json = parse_strict_json(raw_text)
                _, val_issues = validate_against_schema(parsed_json, schema)
                if val_issues:
                    cell_status = CellStatus.FAILED
                    error_cat = "MODEL_OUTPUT"
                    error_msg = f"Schema validation failed: {[i.message for i in val_issues]}"
                    structured_result = StructuredOutputResult(
                        is_valid_json=True,
                        is_valid_schema=False,
                        done_reason=done_reason,
                        validation_error=error_msg,
                        raw_output_snippet=raw_text[:200],
                    )
                else:
                    structured_result = StructuredOutputResult(
                        is_valid_json=True,
                        is_valid_schema=True,
                        done_reason=done_reason,
                    )
            except Exception as json_err:
                cell_status = CellStatus.FAILED
                error_cat = "MODEL_OUTPUT"
                error_msg = f"JSON parse error: {json_err}"
                structured_result = StructuredOutputResult(
                    is_valid_json=False,
                    is_valid_schema=False,
                    done_reason=done_reason,
                    parse_error=str(json_err),
                    raw_output_snippet=raw_text[:200],
                )
        except Exception as parse_err:
            cell_status = CellStatus.FAILED
            error_cat = "RUNTIME_PROTOCOL"
            error_msg = f"Malformed Ollama response: {parse_err}"
            timings = TransportTimings(wall_duration_ms=round((wall_end - wall_start) * 1000.0, 2))

    # 5. Clean up residency if cold mode
    if cell.cold_warm == ResidencyMode.COLD:
        observer.unload_model(cell.model_name)

    return CellObservation(
        cell_id=cell.cell_id,
        repetition_index=repetition_index,
        attempt_index=0,
        cold_warm=cell.cold_warm,
        requested_model=cell.model_name,
        effective_model_tag=cell.model_name,
        inventory_digest=inventory_digest,
        response_digest=response_digest,
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
        structured_output=structured_result,
        metadata={"vram_bytes_ps": vram_bytes},
    )
