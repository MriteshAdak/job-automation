"""Passive transport observer and timing extractor for MODEL-02.

Enforces:
- Passive collection of nanosecond durations from runtime API responses.
- Safe conversions to milliseconds and token rates (tokens/second) without inventing throughput when durations are missing or non-positive.
- Queries /api/ps to verify model residency and observed hardware offload (CPU vs GPU).
- Zero mutation of request payloads and zero prompt leakage into ordinary diagnostics.
"""

from __future__ import annotations

import json
import time
from typing import Any

from job_automation.model_benchmarks.records import (
    ExecutionPlacement,
    TransportTimings,
)
from job_automation.models.runtime_health import LoopbackHttpClient
from job_automation.models.transport import LoopbackHttpTransport


class TransportObserver:
    """Interprets raw API timing fields and checks runtime residency."""

    def __init__(self, transport: LoopbackHttpTransport) -> None:
        self.transport = transport

    def extract_timings(
        self,
        wall_start_monotonic: float,
        wall_end_monotonic: float,
        response_data: dict[str, Any],
    ) -> TransportTimings:
        """Convert response duration nanoseconds to milliseconds and compute token throughput."""
        wall_ms = max(0.0, (wall_end_monotonic - wall_start_monotonic) * 1000.0)

        total_ns = response_data.get("total_duration")
        load_ns = response_data.get("load_duration")
        prompt_ns = response_data.get("prompt_eval_duration")
        eval_ns = response_data.get("eval_duration")

        server_total_ms = (total_ns / 1_000_000.0) if isinstance(total_ns, (int, float)) and total_ns >= 0 else None
        server_load_ms = (load_ns / 1_000_000.0) if isinstance(load_ns, (int, float)) and load_ns >= 0 else None
        server_prompt_ms = (prompt_ns / 1_000_000.0) if isinstance(prompt_ns, (int, float)) and prompt_ns >= 0 else None
        server_eval_ms = (eval_ns / 1_000_000.0) if isinstance(eval_ns, (int, float)) and eval_ns >= 0 else None

        prompt_tokens = response_data.get("prompt_eval_count")
        completion_tokens = response_data.get("eval_count")

        prompt_rate: float | None = None
        if isinstance(prompt_tokens, int) and isinstance(prompt_ns, (int, float)) and prompt_ns > 0:
            prompt_rate = round(prompt_tokens / (prompt_ns / 1_000_000_000.0), 2)

        eval_rate: float | None = None
        if isinstance(completion_tokens, int) and isinstance(eval_ns, (int, float)) and eval_ns > 0:
            eval_rate = round(completion_tokens / (eval_ns / 1_000_000_000.0), 2)

        return TransportTimings(
            wall_duration_ms=round(wall_ms, 2),
            server_total_duration_ms=round(server_total_ms, 2) if server_total_ms is not None else None,
            server_load_duration_ms=round(server_load_ms, 2) if server_load_ms is not None else None,
            server_prompt_eval_duration_ms=round(server_prompt_ms, 2) if server_prompt_ms is not None else None,
            server_eval_duration_ms=round(server_eval_ms, 2) if server_eval_ms is not None else None,
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens=completion_tokens if isinstance(completion_tokens, int) else None,
            prompt_eval_rate_tok_s=prompt_rate,
            eval_rate_tok_s=eval_rate,
        )

    def check_residency(self, model_name: str | None = None) -> tuple[bool, int, ExecutionPlacement]:
        """Query /api/ps to inspect active model residency and GPU offload.

        Returns (is_loaded, size_vram_bytes, observed_placement).
        """
        try:
            status, body = 0, b""
            if hasattr(self.transport, "base_url") and isinstance(getattr(self.transport, "base_url", None), str):
                client = LoopbackHttpClient(base_url=self.transport.base_url)
                status, _, body = client.request("GET", "/api/ps", timeout_seconds=5.0)
            else:
                status, _, body = self.transport.post("/api/ps", {}, timeout_seconds=5.0)

            if status == 200:
                data = json.loads(body.decode("utf-8"))
                models = data.get("models", [])
                if not models:
                    return False, 0, ExecutionPlacement.UNKNOWN

                target_models = models
                if model_name:
                    target_models = [
                        m for m in models
                        if m.get("name") == model_name or m.get("model") == model_name
                    ]

                if not target_models:
                    return False, 0, ExecutionPlacement.UNKNOWN

                total_vram = 0
                has_gpu = False
                has_cpu = False
                for m in target_models:
                    vram = m.get("size_vram", 0)
                    total_vram += vram
                    if vram > 0:
                        has_gpu = True
                    else:
                        has_cpu = True

                if has_gpu and not has_cpu:
                    placement = ExecutionPlacement.GPU
                elif has_cpu and not has_gpu:
                    placement = ExecutionPlacement.CPU
                elif has_gpu and has_cpu:
                    placement = ExecutionPlacement.MIXED
                else:
                    placement = ExecutionPlacement.UNKNOWN

                return True, total_vram, placement
        except Exception:
            pass

        return False, 0, ExecutionPlacement.UNKNOWN

    def unload_model(self, model_name: str) -> bool:
        """Instruct Ollama to unload model immediately by issuing keep_alive: 0."""
        try:
            # Issue dummy generate with keep_alive=0 to trigger unload
            status, _, _ = self.transport.post(
                "/api/generate",
                {"model": model_name, "prompt": "", "keep_alive": 0},
                timeout_seconds=5.0,
            )
            # Give Ollama a short window to release process handles
            time.sleep(0.3)
            is_loaded, _, _ = self.check_residency(model_name)
            return not is_loaded
        except Exception:
            return False
