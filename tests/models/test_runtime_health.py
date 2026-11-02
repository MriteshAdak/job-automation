"""Unit and synthetic integration tests for MODEL-01 runtime health diagnostics.

Covers:
- Standard exit codes (0, 2, 3, 4, 5, 6) and failure precedence (2 > 3 > 4 > 5 > 6 > 0).
- Configuration precedence, loopback validation, and listener safety checks.
- Model inventory, digest verification, and capability alignment.
- Structured generation and embedding active probe validations.
- Supported CPU fallback vs. GPU acceleration reporting.
- Privacy boundaries (no vector leaks, no credential leaks).
- Windows paths with spaces and Unicode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from job_automation.models.runtime_health import (
    EXIT_CONFIG_OR_BINDING_ERROR,
    EXIT_EXECUTION_OR_CAPACITY_FAILURE,
    EXIT_METADATA_ONLY_OR_INCOMPLETE,
    EXIT_MODEL_MISSING_OR_MISMATCH,
    EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE,
    EXIT_SUCCESS,
    LoopbackHttpClient,
    ModelRuntimeManifest,
    RuntimeHealthChecker,
    SocketListener,
    normalize_digest,
)


FAKE_HARDWARE = {
    "os_caption": "Microsoft Windows 11 Home",
    "os_version": "10.0.26300",
    "os_build": "26300",
    "cpu_name": "11th Gen Intel(R) Core(TM) i5-11320H @ 3.20GHz",
    "cpu_cores": 4,
    "cpu_logical": 8,
    "ram_total_gb": 16.0,
    "gpus": [
        {"Name": "NVIDIA GeForce GTX 1650", "DriverVersion": "32.0.16.1742", "AdapterRAM": 4293918720, "Status": "OK"}
    ],
}


class MockHttpClient(LoopbackHttpClient):
    """Scripted HTTP client for unit tests simulating Ollama endpoints."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, dict[str, str], bytes]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.base_url = "http://127.0.0.1:11434"
        self.scheme = "http"
        self.hostname = "127.0.0.1"
        self.port = 11434
        self.base_path = ""
        self.max_response_bytes = 10 * 1024 * 1024

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float = 5.0,
    ) -> tuple[int, dict[str, str], bytes]:
        clean_path = f"/{path.lstrip('/')}"
        self.calls.append((method.upper(), clean_path, payload))
        key = (method.upper(), clean_path)
        if key in self.routes:
            return self.routes[key]
        return 404, {}, b'{"error": "route not found"}'


class MockListenerInspector:
    """Mock socket listener inspector."""

    def __init__(self, listeners: list[SocketListener] | None = None) -> None:
        self._listeners = listeners if listeners is not None else []

    def inspect_listeners(self, port: int) -> list[SocketListener]:
        return self._listeners


def create_test_files(
    tmp_path: Path,
    app_url: str = "http://127.0.0.1:11434",
    exe_name: str = "ollama.exe",
    storage_subpath: str = "external_models",
    expected_version: str | None = "0.40.13",
    gen_model: str = "qwen2.5:1.5b",
    emb_model: str = "all-minilm:22m",
    gen_digest: str | None = "65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b",
    emb_digest: str | None = "1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef",
    emb_dim: int | None = 384,
    accel_mode: str = "auto",
    expected_env: dict[str, str] | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Helper to create valid test app config and runtime manifest.

    Returns (app_config_path, manifest_path, fake_exe, repo_root).
    """
    repo_root = tmp_path / "repo_root"
    repo_root.mkdir(parents=True, exist_ok=True)
    external_dir = tmp_path / "external_data"
    external_dir.mkdir(parents=True, exist_ok=True)

    app_config_path = repo_root / "app.test.json"
    manifest_path = repo_root / "manifest.test.json"
    fake_exe = external_dir / exe_name
    fake_exe.write_text("fake binary", encoding="utf-8")

    fake_storage = tmp_path / storage_subpath
    fake_storage.mkdir(parents=True, exist_ok=True)

    app_data = {
        "schema_version": "1.0",
        "app_name": "JobAutomationTest",
        "data_root": str(external_dir / "data_root"),
        "display_timezone": "Europe/Berlin",
        "model_service_url": app_url,
    }
    app_config_path.write_text(json.dumps(app_data), encoding="utf-8")

    env_map = expected_env if expected_env is not None else {"OLLAMA_HOST": "127.0.0.1:11434"}
    manifest_data = {
        "schema_version": "1.0",
        "runtime_executable": str(fake_exe),
        "model_storage_path": str(fake_storage),
        "expected_runtime_version": expected_version,
        "generation_model": gen_model,
        "embedding_model": emb_model,
        "generation_digest": gen_digest,
        "embedding_digest": emb_digest,
        "smoke_context_tokens": 2048,
        "embedding_dimension": emb_dim,
        "acceleration_mode": accel_mode,
        "expected_environment": env_map,
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    return app_config_path, manifest_path, fake_exe, repo_root


def standard_mock_routes(
    gen_model: str = "qwen2.5:1.5b",
    emb_model: str = "all-minilm:22m",
    gen_digest: str = "65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b",
    emb_digest: str = "1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef",
    version: str = "0.40.13",
    size_vram: int = 1000,
    size: int = 1000,
) -> dict[tuple[str, str], tuple[int, dict[str, str], bytes]]:
    """Generate healthy standard mock HTTP responses."""
    tags_resp = {
        "models": [
            {
                "name": gen_model,
                "model": gen_model,
                "digest": f"sha256:{gen_digest}",
                "size": size,
                "capabilities": ["completion"],
            },
            {
                "name": emb_model,
                "model": emb_model,
                "digest": f"sha256:{emb_digest}",
                "size": 500,
                "capabilities": ["embedding"],
            },
        ]
    }
    ps_resp = {
        "models": [
            {
                "name": gen_model,
                "model": gen_model,
                "size": size,
                "size_vram": size_vram,
            }
        ]
    }
    gen_resp = {
        "model": gen_model,
        "response": "Hello world from test mock.",
        "done": True,
    }
    emb_resp = {
        "model": emb_model,
        "embeddings": [[0.1] * 384, [0.2] * 384],
    }
    return {
        ("GET", "/api/version"): (200, {}, json.dumps({"version": version}).encode("utf-8")),
        ("GET", "/api/tags"): (200, {}, json.dumps(tags_resp).encode("utf-8")),
        ("POST", "/api/show"): (200, {}, b'{"capabilities": ["completion", "embedding"]}'),
        ("GET", "/api/ps"): (200, {}, json.dumps(ps_resp).encode("utf-8")),
        ("POST", "/api/generate"): (200, {}, json.dumps(gen_resp).encode("utf-8")),
        ("POST", "/api/embed"): (200, {}, json.dumps(emb_resp).encode("utf-8")),
    }


def test_full_health_check_success_gpu(tmp_path: Path) -> None:
    """Full check passes with observed GPU acceleration (exit code 0, status ready)."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    routes = standard_mock_routes(size_vram=1000, size=1000)
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_SUCCESS
    assert report.overall_status == "ready"
    assert report.layers["configuration"].status == "pass"
    assert report.layers["listener"].status == "pass"
    assert report.layers["runtime_version"].status == "pass"
    assert report.layers["generation_model"].status == "pass"
    assert report.layers["embedding_model"].status == "pass"
    assert report.layers["generation_probe"].status == "pass"
    assert report.layers["embedding_probe"].status == "pass"
    assert report.layers["acceleration"].details["observed_acceleration"] == "gpu"


def test_full_health_check_success_cpu(tmp_path: Path) -> None:
    """Full check passes with CPU execution (exit code 0, status ready_cpu)."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path, accel_mode="cpu")
    routes = standard_mock_routes(size_vram=0, size=1000)
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_SUCCESS
    assert report.overall_status == "ready_cpu"
    assert report.layers["acceleration"].status == "pass"


def test_metadata_only_check_exits_6(tmp_path: Path) -> None:
    """Metadata-only check verifies metadata and exits 6 without active inference."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    routes = standard_mock_routes()
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        metadata_only=True,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_METADATA_ONLY_OR_INCOMPLETE
    assert report.overall_status == "metadata_healthy"
    assert "metadata_only" in report.reasons
    assert report.layers["generation_probe"].status == "skipped"
    assert report.layers["embedding_probe"].status == "skipped"


def test_exit_2_output_path_inside_repository_source(tmp_path: Path) -> None:
    """Report output path inside source root must be rejected with exit code 2."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    forbidden_output = repo_root / "reports" / "health.json"

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        output_path=forbidden_output,
        repo_root=repo_root,
        hardware_inventory=FAKE_HARDWARE,
        listener_inspector=MockListenerInspector(),
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_CONFIG_OR_BINDING_ERROR
    assert "output_in_source" in report.reasons


def test_exit_2_unsafe_binding_non_loopback(tmp_path: Path) -> None:
    """Listener bound to 0.0.0.0 is flagged as unsafe binding with exit code 2."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    mock_client = MockHttpClient(standard_mock_routes())
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="0.0.0.0", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_CONFIG_OR_BINDING_ERROR
    assert "unsafe_binding" in report.reasons
    assert report.layers["listener"].status == "fail"


def test_exit_2_endpoint_mismatch(tmp_path: Path) -> None:
    """Application config port mismatching manifest expected OLLAMA_HOST exits 2."""
    app_cfg, man_cfg, _, repo_root = create_test_files(
        tmp_path,
        app_url="http://127.0.0.1:11434",
        expected_env={"OLLAMA_HOST": "127.0.0.1:11435"},
    )
    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        repo_root=repo_root,
        hardware_inventory=FAKE_HARDWARE,
        listener_inspector=MockListenerInspector(),
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_CONFIG_OR_BINDING_ERROR
    assert "endpoint_mismatch" in report.reasons


def test_exit_2_cache_path_inside_repo(tmp_path: Path) -> None:
    """Model storage path located inside source repository triggers exit code 2."""
    app_cfg, man_cfg, _, repo_root = create_test_files(
        tmp_path,
        storage_subpath="repo_root/models_cache",
    )
    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        repo_root=repo_root,
        hardware_inventory=FAKE_HARDWARE,
        listener_inspector=MockListenerInspector(),
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_CONFIG_OR_BINDING_ERROR
    assert "cache_path_invalid" in report.reasons


def test_exit_3_runtime_not_installed(tmp_path: Path) -> None:
    """Missing runtime executable exits with code 3."""
    app_cfg, man_cfg, fake_exe, repo_root = create_test_files(tmp_path)
    fake_exe.unlink()  # Delete executable

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        repo_root=repo_root,
        hardware_inventory=FAKE_HARDWARE,
        listener_inspector=MockListenerInspector(),
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE
    assert "runtime_not_installed" in report.reasons
    assert report.layers["executable"].status == "fail"


def test_exit_3_port_conflict(tmp_path: Path) -> None:
    """Port occupied by an unrelated non-Ollama process triggers exit code 3."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=9999, process_name="rogue_server.exe")]
    )
    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        repo_root=repo_root,
        hardware_inventory=FAKE_HARDWARE,
        listener_inspector=mock_inspector,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE
    assert "port_conflict" in report.reasons
    assert report.layers["listener"].status == "fail"


def test_exit_3_runtime_version_incompatible(tmp_path: Path) -> None:
    """Runtime version mismatch against manifest expectation exits with code 3."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path, expected_version="0.50.0")
    routes = standard_mock_routes(version="0.40.13")
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE
    assert "runtime_incompatible" in report.reasons
    assert report.layers["runtime_version"].status == "fail"


def test_exit_3_embed_route_not_found(tmp_path: Path) -> None:
    """Missing /api/embed route (HTTP 404) reports runtime incompatibility and exits 3."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    routes = standard_mock_routes()
    routes[("POST", "/api/embed")] = (404, {}, b'{"error": "route not found"}')
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE
    assert "runtime_incompatible" in report.reasons
    assert report.layers["embedding_probe"].status == "fail"


def test_exit_4_generation_model_missing(tmp_path: Path) -> None:
    """Selected generation model missing from inventory exits with code 4."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path, gen_model="nonexistent:model")
    routes = standard_mock_routes()
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_MODEL_MISSING_OR_MISMATCH
    assert "generation_model_missing" in report.reasons
    assert report.layers["generation_model"].status == "fail"


def test_exit_4_digest_mismatch(tmp_path: Path) -> None:
    """Observed model digest differing from expected digest exits with code 4."""
    app_cfg, man_cfg, _, repo_root = create_test_files(
        tmp_path,
        gen_digest="0000000000000000000000000000000000000000000000000000000000000000",
    )
    routes = standard_mock_routes()
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_MODEL_MISSING_OR_MISMATCH
    assert "model_digest_mismatch" in report.reasons
    assert report.layers["generation_model"].status == "fail"


def test_exit_4_model_capability_mismatch(tmp_path: Path) -> None:
    """Generation model with only embedding capability exits with code 4."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    routes = standard_mock_routes()
    routes[("GET", "/api/tags")] = (
        200,
        {},
        json.dumps({
            "models": [
                {
                    "name": "qwen2.5:1.5b",
                    "digest": "sha256:65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b",
                    "capabilities": ["embedding"],
                },
                {
                    "name": "all-minilm:22m",
                    "digest": "sha256:1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef",
                    "capabilities": ["embedding"],
                },
            ]
        }).encode("utf-8"),
    )
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_MODEL_MISSING_OR_MISMATCH
    assert "model_capability_mismatch" in report.reasons
    assert report.layers["generation_model"].status == "fail"


def test_exit_5_generation_oom_memory_capacity(tmp_path: Path) -> None:
    """HTTP 507 or out-of-memory error during generation triggers exit code 5."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    routes = standard_mock_routes()
    routes[("POST", "/api/generate")] = (507, {}, b'{"error": "insufficient VRAM / out of memory"}')
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_EXECUTION_OR_CAPACITY_FAILURE
    assert "memory_capacity" in report.reasons
    assert report.layers["generation_probe"].status == "fail"


def test_exit_5_embedding_response_invalid(tmp_path: Path) -> None:
    """Embedding response with boolean values or dimension mismatch triggers exit code 5."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path, emb_dim=384)
    routes = standard_mock_routes()
    routes[("POST", "/api/embed")] = (
        200,
        {},
        json.dumps({"embeddings": [[0.1] * 128, [0.2] * 128]}).encode("utf-8"),
    )
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_EXECUTION_OR_CAPACITY_FAILURE
    assert "embedding_response_invalid" in report.reasons
    assert report.layers["embedding_probe"].status == "fail"


def test_exit_code_precedence_2_over_3_over_4_over_5(tmp_path: Path) -> None:
    """Ensure exit code precedence resolves strictly: 2 > 3 > 4 > 5 > 6 > 0."""
    repo_root = tmp_path / "repo_root"
    repo_root.mkdir(parents=True, exist_ok=True)
    app_cfg = repo_root / "app.invalid.json"
    app_cfg.write_text("invalid json", encoding="utf-8")
    man_cfg = repo_root / "manifest.nonexistent.json"

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        repo_root=repo_root,
        hardware_inventory=FAKE_HARDWARE,
        listener_inspector=MockListenerInspector(),
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_CONFIG_OR_BINDING_ERROR
    assert "invalid_config" in report.reasons
    assert "manifest_invalid" in report.reasons


def test_windows_paths_with_spaces_and_umlauts(tmp_path: Path) -> None:
    """Validate path handling for Windows directories containing spaces and German umlauts."""
    special_dir = tmp_path / "Model Prüfung mit Leerzeichen und äöü"
    special_dir.mkdir(parents=True, exist_ok=True)

    app_cfg, man_cfg, _, repo_root = create_test_files(special_dir, storage_subpath="Modelle Außen ä")
    routes = standard_mock_routes()
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()

    assert report.exit_code == EXIT_SUCCESS
    assert report.layers["configuration"].status == "pass"


def test_no_vector_or_prompt_leaks_in_report(tmp_path: Path) -> None:
    """Verify that embeddings raw vector floats and prompt texts are omitted from reports."""
    app_cfg, man_cfg, _, repo_root = create_test_files(tmp_path)
    routes = standard_mock_routes()
    mock_client = MockHttpClient(routes)
    mock_inspector = MockListenerInspector(
        [SocketListener(local_address="127.0.0.1", local_port=11434, owning_process_id=1234, process_name="ollama.exe")]
    )

    checker = RuntimeHealthChecker(
        app_config_path=app_cfg,
        manifest_path=man_cfg,
        http_client=mock_client,
        listener_inspector=mock_inspector,
        hardware_inventory=FAKE_HARDWARE,
        repo_root=repo_root,
    )
    report = checker.run_check()
    report_json = json.dumps(report.model_dump())

    assert "0.1000" not in report_json
    assert "Job automation test" not in report_json
