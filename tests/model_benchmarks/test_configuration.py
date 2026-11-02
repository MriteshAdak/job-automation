"""Tests for benchmark manifest configuration and validation."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.model_benchmarks.configuration import (
    BenchmarkConfigurationError,
    build_default_phase0_manifest,
    check_no_secrets,
    load_benchmark_manifest,
)


class TestBenchmarkConfiguration:
    def test_build_default_phase0_manifest(self) -> None:
        manifest = build_default_phase0_manifest()
        assert manifest.manifest_id == "phase0_benchmark_manifest_v1"
        assert len(manifest.candidates) >= 2
        assert len(manifest.gates) == 6
        assert len(manifest.cells) >= 6

    def test_load_manifest_valid(self, tmp_path: Path) -> None:
        manifest = build_default_phase0_manifest()
        m_path = tmp_path / "manifest.json"
        m_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")

        loaded = load_benchmark_manifest(m_path)
        assert loaded.manifest_id == manifest.manifest_id
        assert len(loaded.cells) == len(manifest.cells)

    def test_secret_detection_raises(self) -> None:
        with pytest.raises(BenchmarkConfigurationError, match="secret"):
            check_no_secrets({"api_key": "bearer secret_123456789"})

    def test_duplicate_cell_id_raises(self, tmp_path: Path) -> None:
        manifest = build_default_phase0_manifest()
        data = manifest.model_dump(mode="json")
        # Duplicate first cell
        data["cells"].append(data["cells"][0])
        m_path = tmp_path / "dup_manifest.json"
        m_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(BenchmarkConfigurationError, match="Duplicate cell_id"):
            load_benchmark_manifest(m_path)

    def test_invalid_loopback_url_raises(self, tmp_path: Path) -> None:
        manifest = build_default_phase0_manifest()
        data = manifest.model_dump(mode="json")
        data["server_url"] = "http://remote-host.com:11434"
        m_path = tmp_path / "remote_manifest.json"
        m_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(BenchmarkConfigurationError, match="Invalid runtime server URL"):
            load_benchmark_manifest(m_path)

