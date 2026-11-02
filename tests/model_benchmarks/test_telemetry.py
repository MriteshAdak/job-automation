"""Tests for hardware context capture and memory telemetry sampling."""

from __future__ import annotations

import time

from job_automation.model_benchmarks.telemetry import (
    HostTelemetrySampler,
    capture_host_hardware_context,
    get_process_memory_info,
    get_system_memory_status,
)


class TestHostTelemetry:
    def test_capture_hardware_context(self) -> None:
        hw = capture_host_hardware_context()
        assert hw.cpu_cores > 0
        assert hw.ram_total_bytes > 0
        assert hw.python_version != ""

    def test_system_memory_status(self) -> None:
        mem = get_system_memory_status()
        assert "total_phys" in mem
        assert "avail_phys" in mem
        assert mem["total_phys"] > 0
        assert mem["avail_phys"] > 0

    def test_telemetry_sampler_lifecycle(self) -> None:
        sampler = HostTelemetrySampler(sample_interval_seconds=0.05)
        sampler.start()
        time.sleep(0.15)
        samples, summary = sampler.stop()

        assert len(samples) >= 1
        assert summary.sample_count == len(samples)
        assert summary.min_available_phys_bytes > 0
        assert summary.sample_interval_ms == 50.0

