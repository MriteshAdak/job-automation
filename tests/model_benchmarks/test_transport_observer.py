"""Tests for transport timing observer and residency checking."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from job_automation.model_benchmarks.records import ExecutionPlacement
from job_automation.model_benchmarks.transport_observer import TransportObserver
from tests.fakes.model_transport import ScriptedModelTransport


class TestTransportObserver:
    def test_extract_timings_complete(self) -> None:
        observer = TransportObserver(transport=MagicMock())
        resp_data = {
            "total_duration": 1_500_000_000,
            "load_duration": 50_000_000,
            "prompt_eval_duration": 400_000_000,
            "eval_duration": 1_000_000_000,
            "prompt_eval_count": 200,
            "eval_count": 50,
        }

        timings = observer.extract_timings(100.0, 101.6, resp_data)
        assert timings.wall_duration_ms == 1600.0
        assert timings.server_total_duration_ms == 1500.0
        assert timings.server_load_duration_ms == 50.0
        assert timings.server_prompt_eval_duration_ms == 400.0
        assert timings.server_eval_duration_ms == 1000.0
        assert timings.prompt_tokens == 200
        assert timings.completion_tokens == 50
        assert timings.prompt_eval_rate_tok_s == 500.0
        assert timings.eval_rate_tok_s == 50.0

    def test_extract_timings_missing_fields_safe(self) -> None:
        observer = TransportObserver(transport=MagicMock())
        timings = observer.extract_timings(10.0, 10.5, {})
        assert timings.wall_duration_ms == 500.0
        assert timings.server_total_duration_ms is None
        assert timings.eval_rate_tok_s is None

    def test_check_residency_gpu(self) -> None:
        fake_transport = ScriptedModelTransport()
        fake_transport.queue_response(
            "/api/ps",
            200,
            body={
                "models": [
                    {
                        "name": "qwen2.5:1.5b",
                        "size_vram": 1200000000,
                    }
                ]
            },
        )
        observer = TransportObserver(transport=fake_transport)
        is_loaded, vram_bytes, placement = observer.check_residency("qwen2.5:1.5b")
        assert is_loaded is True
        assert vram_bytes == 1200000000
        assert placement == ExecutionPlacement.GPU

    def test_check_residency_cpu(self) -> None:
        fake_transport = ScriptedModelTransport()
        fake_transport.queue_response(
            "/api/ps",
            200,
            body={
                "models": [
                    {
                        "name": "qwen2.5:1.5b",
                        "size_vram": 0,
                    }
                ]
            },
        )
        observer = TransportObserver(transport=fake_transport)
        is_loaded, vram_bytes, placement = observer.check_residency("qwen2.5:1.5b")
        assert is_loaded is True
        assert vram_bytes == 0
        assert placement == ExecutionPlacement.CPU

