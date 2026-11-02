"""Model runtime health and diagnostics service (MODEL-01).

Implements layered verification for local Ollama runtime:
- Layer 1: App config & runtime manifest validation, safe loopback binding, listener inspection.
- Layer 2: Runtime availability and version verification (/api/version).
- Layer 3: Model inventory and capability checks (/api/tags, /api/show).
- Layer 4: Active structured generation and embedding smoke probes (/api/generate, /api/embed).
- Layer 5: Placement & hardware acceleration evaluation (/api/ps, CPU fallback).
- Layer 6: Precise diagnostic exit codes and safe remediation reporting.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from job_automation.configuration import AppConfig, load_config
from job_automation.models.configuration import validate_loopback_url
from job_automation.models.diagnostics import redact_url_credentials, sanitize_log_text


# Standard Diagnostic Exit Codes (MODEL-01-S04)
EXIT_SUCCESS = 0
EXIT_CONFIG_OR_BINDING_ERROR = 2
EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE = 3
EXIT_MODEL_MISSING_OR_MISMATCH = 4
EXIT_EXECUTION_OR_CAPACITY_FAILURE = 5
EXIT_METADATA_ONLY_OR_INCOMPLETE = 6

# Precedence map: smaller index = higher precedence
EXIT_PRECEDENCE = [
    EXIT_CONFIG_OR_BINDING_ERROR,           # 2
    EXIT_RUNTIME_UNAVAILABLE_OR_INCOMPATIBLE,  # 3
    EXIT_MODEL_MISSING_OR_MISMATCH,         # 4
    EXIT_EXECUTION_OR_CAPACITY_FAILURE,     # 5
    EXIT_METADATA_ONLY_OR_INCOMPLETE,       # 6
    EXIT_SUCCESS,                           # 0
]


class ModelRuntimeManifest(BaseModel):
    """Specification manifest for local model runtime setup and health validation."""

    schema_version: Literal["1.0"] = "1.0"
    runtime_executable: str = Field(description="Absolute path to runtime executable")
    model_storage_path: str = Field(description="Absolute path to model storage directory outside source")
    expected_runtime_version: str | None = Field(default=None, description="Expected runtime version string")
    generation_model: str = Field(min_length=1, description="Model identifier/tag for text generation")
    embedding_model: str = Field(min_length=1, description="Model identifier/tag for embeddings")
    generation_digest: str | None = Field(default=None, description="Optional expected SHA-256 digest")
    embedding_digest: str | None = Field(default=None, description="Optional expected SHA-256 digest")
    smoke_context_tokens: int = Field(default=2048, gt=0, description="Smoke context length token limit")
    embedding_dimension: int | None = Field(default=None, gt=0, description="Optional expected vector dimension")
    acceleration_mode: Literal["auto", "cpu"] = Field(default="auto", description="Acceleration mode requirement")
    expected_environment: dict[str, str] = Field(default_factory=dict, description="Expected environment values")

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }

    @field_validator("runtime_executable", "model_storage_path")
    @classmethod
    def _validate_absolute_path(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            raise ValueError(f"Path must be absolute, got: '{v}'")
        return v


class SocketListener(BaseModel):
    """Inspected TCP socket listener."""

    local_address: str
    local_port: int
    owning_process_id: int | None = None
    process_name: str | None = None
    process_path: str | None = None
    state: str | None = None


class ListenerInspector(Protocol):
    """Protocol for inspecting active TCP socket listeners on the local system."""

    def inspect_listeners(self, port: int) -> list[SocketListener]:
        ...


class WindowsPowerShellListenerInspector:
    """Default Windows listener inspector using Get-NetTCPConnection."""

    def inspect_listeners(self, port: int) -> list[SocketListener]:
        listeners: list[SocketListener] = []
        if os.name != "nt":
            return listeners

        ps_script = f"""
        Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue |
            ForEach-Object {{
                $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
                [PSCustomObject]@{{
                    LocalAddress = $_.LocalAddress
                    LocalPort = $_.LocalPort
                    RemoteAddress = $_.RemoteAddress
                    RemotePort = $_.RemotePort
                    OwningProcess = $_.OwningProcess
                    ProcessName = if ($proc) {{ $proc.ProcessName }} else {{ $null }}
                    ProcessPath = if ($proc) {{ $proc.Path }} else {{ $null }}
                    State = $_.State
                }}
            }} | ConvertTo-Json
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    remote_port = item.get("RemotePort")
                    remote_addr = str(item.get("RemoteAddress") or "")
                    # In Windows CIM, listening sockets have RemotePort 0 or remote address 0.0.0.0 / ::
                    if remote_port == 0 or remote_addr in ("0.0.0.0", "::"):
                        listeners.append(
                            SocketListener(
                                local_address=str(item.get("LocalAddress") or ""),
                                local_port=int(item.get("LocalPort") or port),
                                owning_process_id=item.get("OwningProcess"),
                                process_name=item.get("ProcessName"),
                                process_path=item.get("ProcessPath"),
                                state=item.get("State"),
                            )
                        )
        except Exception:
            pass

        return listeners


class LayerResult(BaseModel):
    """Result of a single diagnostic layer."""

    layer: str
    status: Literal["pass", "fail", "warning", "skipped", "not_tested"]
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    remediation: str | None = None


class HealthReport(BaseModel):
    """Versioned health diagnostic report v1.0."""

    schema_version: Literal["1.0"] = "1.0"
    timestamp_utc: str
    check_mode: Literal["full", "metadata_only"]
    effective_url: str
    overall_status: Literal["ready", "ready_cpu", "metadata_healthy", "failed", "incomplete"]
    exit_code: int
    reasons: list[str] = Field(default_factory=list)
    remediations: list[str] = Field(default_factory=list)
    layers: dict[str, LayerResult] = Field(default_factory=dict)
    runtime_info: dict[str, Any] = Field(default_factory=dict)
    hardware_info: dict[str, Any] = Field(default_factory=dict)


class LoopbackHttpClient:
    """Direct, proxy-bypassing HTTP client for local health probes."""

    def __init__(
        self,
        base_url: str,
        max_response_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.base_url = validate_loopback_url(base_url)
        self.max_response_bytes = max_response_bytes
        parsed = urlparse(self.base_url)
        self.scheme = parsed.scheme
        self.hostname = (parsed.hostname or "127.0.0.1").lower()
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.base_path = parsed.path.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float = 5.0,
    ) -> tuple[int, dict[str, str], bytes]:
        if ".." in path:
            raise ValueError("Path must not contain directory traversal")

        full_path = f"{self.base_path}/{path.lstrip('/')}"
        body_bytes: bytes | None = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "JobAutomation-RuntimeHealth/1.0",
        }

        if payload is not None:
            body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body_bytes))

        conn: http.client.HTTPConnection | None = None
        try:
            if self.scheme == "https":
                conn = http.client.HTTPSConnection(
                    self.hostname,
                    self.port,
                    timeout=timeout_seconds,
                )
            else:
                conn = http.client.HTTPConnection(
                    self.hostname,
                    self.port,
                    timeout=timeout_seconds,
                )

            conn.request(method.upper(), full_path, body=body_bytes, headers=headers)
            response = conn.getresponse()

            status = response.status
            resp_headers = {k.lower(): v for k, v in response.getheaders()}

            # Content length check
            cl_header = resp_headers.get("content-length")
            if cl_header:
                try:
                    decl_len = int(cl_header)
                    if decl_len > self.max_response_bytes:
                        raise ValueError(f"Response Content-Length {decl_len} exceeds maximum allowed")
                except ValueError as err:
                    if "exceeds maximum allowed" in str(err):
                        raise

            # Read incrementally
            chunks: list[bytes] = []
            total = 0
            chunk_size = 64 * 1024
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise ValueError(f"Response body exceeded maximum allowed {self.max_response_bytes} bytes")
                chunks.append(chunk)

            return status, resp_headers, b"".join(chunks)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def normalize_digest(digest: str | None) -> str | None:
    """Normalize a digest string by stripping 'sha256:' prefix if present."""
    if not digest:
        return None
    val = digest.strip().lower()
    if val.startswith("sha256:"):
        return val[len("sha256:"):]
    return val


def get_hardware_inventory() -> dict[str, Any]:
    """Capture sanitized host hardware context on Windows without assuming GPU support."""
    info: dict[str, Any] = {
        "os_caption": None,
        "os_version": None,
        "os_build": None,
        "cpu_name": None,
        "cpu_cores": None,
        "cpu_logical": None,
        "ram_total_gb": None,
        "gpus": [],
    }

    if os.name != "nt":
        return info

    ps_script = """
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
    $ram = Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | Measure-Object -Property Capacity -Sum
    $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object {
        [PSCustomObject]@{
            Name = $_.Name
            DriverVersion = $_.DriverVersion
            AdapterRAM = $_.AdapterRAM
            Status = $_.Status
        }
    }
    [PSCustomObject]@{
        OSCaption = if ($os) { $os.Caption } else { $null }
        OSVersion = if ($os) { $os.Version } else { $null }
        OSBuild = if ($os) { $os.BuildNumber } else { $null }
        CPUName = if ($cpu) { $cpu.Name } else { $null }
        CPUCores = if ($cpu) { $cpu.NumberOfCores } else { $null }
        CPULogical = if ($cpu) { $cpu.NumberOfLogicalProcessors } else { $null }
        RAMTotalGB = if ($ram -and $ram.Sum) { [math]::Round($ram.Sum / 1GB, 2) } else { $null }
        GPUs = $gpus
    } | ConvertTo-Json
    """
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            info["os_caption"] = data.get("OSCaption")
            info["os_version"] = data.get("OSVersion")
            info["os_build"] = data.get("OSBuild")
            info["cpu_name"] = data.get("CPUName")
            info["cpu_cores"] = data.get("CPUCores")
            info["cpu_logical"] = data.get("CPULogical")
            info["ram_total_gb"] = data.get("RAMTotalGB")
            gpus = data.get("GPUs")
            if isinstance(gpus, list):
                info["gpus"] = gpus
            elif isinstance(gpus, dict):
                info["gpus"] = [gpus]
    except Exception:
        pass

    return info


class RuntimeHealthChecker:
    """Executes layered diagnostics against local Ollama service."""

    def __init__(
        self,
        app_config_path: Path | str,
        manifest_path: Path | str,
        metadata_only: bool = False,
        output_path: Path | str | None = None,
        repo_root: Path | None = None,
        http_client: LoopbackHttpClient | None = None,
        listener_inspector: ListenerInspector | None = None,
        hardware_inventory: dict[str, Any] | None = None,
    ) -> None:
        self.app_config_path = Path(app_config_path)
        self.manifest_path = Path(manifest_path)
        self.metadata_only = metadata_only
        self.output_path = Path(output_path) if output_path else None
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent.parent
        self.custom_http_client = http_client
        self.listener_inspector = listener_inspector or WindowsPowerShellListenerInspector()
        self.hardware_inventory = hardware_inventory

    def run_check(self) -> HealthReport:
        now_utc = datetime.now(timezone.utc).isoformat()
        reasons: list[str] = []
        remediations: list[str] = []
        layers: dict[str, LayerResult] = {}
        runtime_info: dict[str, Any] = {}
        hardware_info = (
            self.hardware_inventory
            if self.hardware_inventory is not None
            else get_hardware_inventory()
        )

        effective_url = "http://127.0.0.1:11434"
        app_config: AppConfig | None = None
        manifest: ModelRuntimeManifest | None = None

        # -------------------------------------------------------------
        # Layer 1: App Config & Output Path Validation
        # -------------------------------------------------------------
        config_error: str | None = None
        if self.output_path is not None:
            resolved_output = self.output_path.resolve()
            if resolved_output.is_relative_to(self.repo_root):
                reasons.append("output_in_source")
                remediations.append(
                    f"Report output path '{self.output_path}' must be located outside repository source root."
                )

        try:
            app_config, _ = load_config(self.app_config_path)
            # Precedence: model_provider.service_url, then model_service_url
            if app_config.model_provider and app_config.model_provider.service_url:
                effective_url = app_config.model_provider.service_url
            else:
                effective_url = app_config.model_service_url

            # Strict loopback validation
            validate_loopback_url(effective_url)
        except Exception as err:
            config_error = str(err)
            reasons.append("invalid_config")
            remediations.append(f"Correct application config file at '{self.app_config_path}': {err}")

        # Manifest Validation
        manifest_error: str | None = None
        if not self.manifest_path.exists():
            manifest_error = f"Manifest file does not exist at '{self.manifest_path}'"
            reasons.append("manifest_invalid")
            remediations.append(f"Create or point to a valid runtime manifest JSON at '{self.manifest_path}'.")
        else:
            try:
                manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                manifest = ModelRuntimeManifest.model_validate(manifest_data)

                # Validate model storage path is outside repository
                storage_path = Path(manifest.model_storage_path).resolve()
                if storage_path.is_relative_to(self.repo_root):
                    reasons.append("cache_path_invalid")
                    remediations.append(
                        f"model_storage_path '{manifest.model_storage_path}' must be located outside repository source root."
                    )

                # Check expected endpoint / OLLAMA_HOST alignment
                expected_host = manifest.expected_environment.get("OLLAMA_HOST")
                if expected_host:
                    parsed_eff = urlparse(effective_url)
                    expected_netloc = expected_host.replace("http://", "").replace("https://", "").rstrip("/")
                    eff_netloc = parsed_eff.netloc
                    if expected_netloc != eff_netloc:
                        reasons.append("endpoint_mismatch")
                        remediations.append(
                            f"Application config URL ({effective_url}) netloc does not match expected OLLAMA_HOST ({expected_host})."
                        )
            except Exception as err:
                manifest_error = str(err)
                reasons.append("manifest_invalid")
                remediations.append(f"Fix manifest format at '{self.manifest_path}': {err}")

        if config_error or manifest_error:
            layers["configuration"] = LayerResult(
                layer="configuration",
                status="fail",
                reason="invalid_config" if config_error else "manifest_invalid",
                details={"config_error": config_error, "manifest_error": manifest_error},
                remediation=remediations[-1] if remediations else None,
            )
        else:
            layers["configuration"] = LayerResult(
                layer="configuration",
                status="pass",
                details={
                    "app_config_path": str(self.app_config_path),
                    "manifest_path": str(self.manifest_path),
                    "effective_url": redact_url_credentials(effective_url),
                },
            )

        # -------------------------------------------------------------
        # Layer 1b: Local Executable & Socket Listener
        # -------------------------------------------------------------
        parsed_url = urlparse(effective_url)
        port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)

        if manifest:
            exe_path = Path(manifest.runtime_executable)
            if not exe_path.exists():
                reasons.append("runtime_not_installed")
                remediations.append(
                    f"Ollama executable not found at '{manifest.runtime_executable}'. Install Ollama or update runtime_executable."
                )
                layers["executable"] = LayerResult(
                    layer="executable",
                    status="fail",
                    reason="runtime_not_installed",
                    details={"runtime_executable": manifest.runtime_executable},
                    remediation=remediations[-1],
                )
            else:
                layers["executable"] = LayerResult(
                    layer="executable",
                    status="pass",
                    details={"runtime_executable": manifest.runtime_executable},
                )

        # Listener inspection
        listeners = self.listener_inspector.inspect_listeners(port)
        if listeners:
            has_unsafe = False
            has_conflict = False
            verified_loopback = False

            for l in listeners:
                addr = l.local_address.lower()
                if addr in ("0.0.0.0", "::", "*") or (addr != "127.0.0.1" and addr != "::1" and addr != "localhost"):
                    has_unsafe = True
                else:
                    verified_loopback = True

                # Check process name if available
                if l.process_name and "ollama" not in l.process_name.lower():
                    has_conflict = True
                    reasons.append("port_conflict")
                    remediations.append(
                        f"Port {port} is occupied by non-Ollama process '{l.process_name}' (PID {l.owning_process_id})."
                    )

            if has_unsafe:
                reasons.append("unsafe_binding")
                remediations.append(
                    f"Listener on port {port} is bound to non-loopback address. Set OLLAMA_HOST=127.0.0.1:{port}."
                )

            layers["listener"] = LayerResult(
                layer="listener",
                status="fail" if (has_unsafe or has_conflict) else "pass",
                reason="unsafe_binding" if has_unsafe else ("port_conflict" if has_conflict else None),
                details={
                    "listeners": [l.model_dump() for l in listeners],
                    "verified_loopback": verified_loopback,
                },
                remediation=remediations[-1] if (has_unsafe or has_conflict) else None,
            )
        else:
            # If on Windows and listener inspection returned empty, verify if socket is connectable
            is_socket_connectable = False
            try:
                with socket.create_connection((parsed_url.hostname or "127.0.0.1", port), timeout=1.0):
                    is_socket_connectable = True
            except Exception:
                is_socket_connectable = False

            if not is_socket_connectable:
                reasons.append("runtime_not_running")
                remediations.append(
                    f"No active listener on port {port} and connection refused. Start Ollama with 'ollama serve' or launch the app."
                )
                layers["listener"] = LayerResult(
                    layer="listener",
                    status="fail",
                    reason="runtime_not_running",
                    details={"port": port},
                    remediation=remediations[-1],
                )
            else:
                layers["listener"] = LayerResult(
                    layer="listener",
                    status="pass",
                    details={"port": port, "verified_via_connect": True},
                )

        # Initialize HTTP client
        client = (
            self.custom_http_client
            if self.custom_http_client is not None
            else LoopbackHttpClient(base_url=effective_url)
        )

        # -------------------------------------------------------------
        # Layer 2: Runtime Version (/api/version)
        # -------------------------------------------------------------
        runtime_available = False
        try:
            status, _, body = client.request("GET", "/api/version", timeout_seconds=5.0)
            if status != 200:
                reasons.append("runtime_response_invalid")
                remediations.append(f"GET /api/version returned HTTP status {status}.")
                layers["runtime_version"] = LayerResult(
                    layer="runtime_version",
                    status="fail",
                    reason="runtime_response_invalid",
                    details={"http_status": status},
                    remediation=remediations[-1],
                )
            else:
                v_data = json.loads(body.decode("utf-8"))
                version_str = v_data.get("version")
                if not version_str:
                    reasons.append("runtime_response_invalid")
                    remediations.append("Response from /api/version lacked 'version' field.")
                    layers["runtime_version"] = LayerResult(
                        layer="runtime_version",
                        status="fail",
                        reason="runtime_response_invalid",
                        remediation=remediations[-1],
                    )
                else:
                    runtime_info["version"] = version_str
                    runtime_available = True

                    if manifest and manifest.expected_runtime_version:
                        if version_str != manifest.expected_runtime_version:
                            reasons.append("runtime_incompatible")
                            remediations.append(
                                f"Observed runtime version '{version_str}' does not match expected '{manifest.expected_runtime_version}'."
                            )
                            layers["runtime_version"] = LayerResult(
                                layer="runtime_version",
                                status="fail",
                                reason="runtime_incompatible",
                                details={"observed": version_str, "expected": manifest.expected_runtime_version},
                                remediation=remediations[-1],
                            )
                        else:
                            layers["runtime_version"] = LayerResult(
                                layer="runtime_version",
                                status="pass",
                                details={"version": version_str},
                            )
                    else:
                        layers["runtime_version"] = LayerResult(
                            layer="runtime_version",
                            status="pass",
                            details={"version": version_str},
                        )
        except Exception as err:
            err_str = str(err).lower()
            if "timed out" in err_str:
                reasons.append("request_timeout")
                remediations.append("GET /api/version timed out after 5.0 seconds.")
                layers["runtime_version"] = LayerResult(
                    layer="runtime_version",
                    status="fail",
                    reason="request_timeout",
                    details={"error": str(err)},
                    remediation=remediations[-1],
                )
            else:
                if "runtime_not_running" not in reasons:
                    reasons.append("runtime_not_running")
                    remediations.append(f"Cannot reach Ollama at {effective_url}: {err}")
                layers["runtime_version"] = LayerResult(
                    layer="runtime_version",
                    status="fail",
                    reason="runtime_not_running",
                    details={"error": str(err)},
                    remediation=remediations[-1],
                )

        # -------------------------------------------------------------
        # Layer 3: Inventory & Capabilities (/api/tags & /api/show)
        # -------------------------------------------------------------
        installed_models: dict[str, dict[str, Any]] = {}
        if runtime_available and manifest:
            try:
                status, _, body = client.request("GET", "/api/tags", timeout_seconds=5.0)
                if status != 200:
                    reasons.append("runtime_response_invalid")
                    remediations.append(f"GET /api/tags returned HTTP status {status}.")
                    layers["inventory"] = LayerResult(
                        layer="inventory",
                        status="fail",
                        reason="runtime_response_invalid",
                        details={"http_status": status},
                        remediation=remediations[-1],
                    )
                else:
                    tags_data = json.loads(body.decode("utf-8"))
                    raw_models = tags_data.get("models", [])
                    for m in raw_models:
                        name = m.get("name") or m.get("model")
                        if name:
                            installed_models[name] = m

                    runtime_info["installed_models"] = list(installed_models.keys())
                    layers["inventory"] = LayerResult(
                        layer="inventory",
                        status="pass",
                        details={"installed_count": len(installed_models), "models": list(installed_models.keys())},
                    )

                    # Check Generation Model
                    gen_tag = manifest.generation_model
                    gen_found = installed_models.get(gen_tag)
                    if not gen_found:
                        reasons.append("generation_model_missing")
                        remediations.append(
                            f"Generation model '{gen_tag}' not installed. Pull with: & '{manifest.runtime_executable}' pull {gen_tag}"
                        )
                        layers["generation_model"] = LayerResult(
                            layer="generation_model",
                            status="fail",
                            reason="generation_model_missing",
                            details={"requested_model": gen_tag},
                            remediation=remediations[-1],
                        )
                    else:
                        obs_gen_digest = normalize_digest(gen_found.get("digest"))
                        runtime_info["generation_digest"] = obs_gen_digest
                        exp_gen_digest = normalize_digest(manifest.generation_digest)

                        if exp_gen_digest and obs_gen_digest != exp_gen_digest:
                            reasons.append("model_digest_mismatch")
                            remediations.append(
                                f"Generation model '{gen_tag}' digest mismatch. Expected: {exp_gen_digest}, Observed: {obs_gen_digest}"
                            )
                            layers["generation_model"] = LayerResult(
                                layer="generation_model",
                                status="fail",
                                reason="model_digest_mismatch",
                                details={"expected": exp_gen_digest, "observed": obs_gen_digest},
                                remediation=remediations[-1],
                            )
                        else:
                            # Verify Capability via /api/show
                            caps = gen_found.get("capabilities", [])
                            if not caps:
                                try:
                                    s_st, _, s_body = client.request(
                                        "POST", "/api/show", {"model": gen_tag}, timeout_seconds=5.0
                                    )
                                    if s_st == 200:
                                        s_data = json.loads(s_body.decode("utf-8"))
                                        caps = s_data.get("capabilities", [])
                                except Exception:
                                    pass

                            # If model explicitly declares capabilities and lacks completion
                            if caps and "completion" not in caps and "tools" not in caps:
                                reasons.append("model_capability_mismatch")
                                remediations.append(
                                    f"Model '{gen_tag}' does not support text completion (capabilities: {caps})."
                                )
                                layers["generation_model"] = LayerResult(
                                    layer="generation_model",
                                    status="fail",
                                    reason="model_capability_mismatch",
                                    details={"capabilities": caps},
                                    remediation=remediations[-1],
                                )
                            else:
                                layers["generation_model"] = LayerResult(
                                    layer="generation_model",
                                    status="pass",
                                    details={
                                        "model": gen_tag,
                                        "digest": obs_gen_digest,
                                        "capabilities": caps,
                                        "details": gen_found.get("details"),
                                    },
                                )

                    # Check Embedding Model
                    emb_tag = manifest.embedding_model
                    emb_found = installed_models.get(emb_tag)
                    if not emb_found:
                        reasons.append("embedding_model_missing")
                        remediations.append(
                            f"Embedding model '{emb_tag}' not installed. Pull with: & '{manifest.runtime_executable}' pull {emb_tag}"
                        )
                        layers["embedding_model"] = LayerResult(
                            layer="embedding_model",
                            status="fail",
                            reason="embedding_model_missing",
                            details={"requested_model": emb_tag},
                            remediation=remediations[-1],
                        )
                    else:
                        obs_emb_digest = normalize_digest(emb_found.get("digest"))
                        runtime_info["embedding_digest"] = obs_emb_digest
                        exp_emb_digest = normalize_digest(manifest.embedding_digest)

                        if exp_emb_digest and obs_emb_digest != exp_emb_digest:
                            reasons.append("model_digest_mismatch")
                            remediations.append(
                                f"Embedding model '{emb_tag}' digest mismatch. Expected: {exp_emb_digest}, Observed: {obs_emb_digest}"
                            )
                            layers["embedding_model"] = LayerResult(
                                layer="embedding_model",
                                status="fail",
                                reason="model_digest_mismatch",
                                details={"expected": exp_emb_digest, "observed": obs_emb_digest},
                                remediation=remediations[-1],
                            )
                        else:
                            # Verify Capability via /api/show
                            caps = emb_found.get("capabilities", [])
                            if not caps:
                                try:
                                    s_st, _, s_body = client.request(
                                        "POST", "/api/show", {"model": emb_tag}, timeout_seconds=5.0
                                    )
                                    if s_st == 200:
                                        s_data = json.loads(s_body.decode("utf-8"))
                                        caps = s_data.get("capabilities", [])
                                except Exception:
                                    pass

                            # If capabilities present, must include 'embedding'
                            if caps and "embedding" not in caps:
                                reasons.append("model_capability_mismatch")
                                remediations.append(
                                    f"Model '{emb_tag}' does not support embeddings (capabilities: {caps})."
                                )
                                layers["embedding_model"] = LayerResult(
                                    layer="embedding_model",
                                    status="fail",
                                    reason="model_capability_mismatch",
                                    details={"capabilities": caps},
                                    remediation=remediations[-1],
                                )
                            else:
                                layers["embedding_model"] = LayerResult(
                                    layer="embedding_model",
                                    status="pass",
                                    details={
                                        "model": emb_tag,
                                        "digest": obs_emb_digest,
                                        "capabilities": caps,
                                        "details": emb_found.get("details"),
                                    },
                                )

            except Exception as err:
                reasons.append("runtime_response_invalid")
                remediations.append(f"Failed querying /api/tags: {err}")
                layers["inventory"] = LayerResult(
                    layer="inventory",
                    status="fail",
                    reason="runtime_response_invalid",
                    details={"error": str(err)},
                    remediation=remediations[-1],
                )
        else:
            if not runtime_available:
                layers["inventory"] = LayerResult(layer="inventory", status="not_tested", reason="runtime_not_running")
                layers["generation_model"] = LayerResult(layer="generation_model", status="not_tested", reason="runtime_not_running")
                layers["embedding_model"] = LayerResult(layer="embedding_model", status="not_tested", reason="runtime_not_running")

        # -------------------------------------------------------------
        # Layer 4: Active Smoke Probes (Generation & Embedding)
        # -------------------------------------------------------------
        observed_gen_placement: str | None = None
        observed_emb_placement: str | None = None

        has_upstream_failure = any(
            r in reasons for r in [
                "invalid_config", "manifest_invalid", "unsafe_binding", "output_in_source",
                "cache_path_invalid", "endpoint_mismatch", "runtime_not_installed",
                "runtime_path_invalid", "runtime_not_running", "port_conflict",
                "runtime_incompatible", "runtime_response_invalid",
                "generation_model_missing", "embedding_model_missing",
                "model_capability_mismatch", "model_digest_mismatch",
            ]
        )

        if self.metadata_only:
            reasons.append("metadata_only")
            layers["generation_probe"] = LayerResult(
                layer="generation_probe",
                status="skipped",
                details={"message": "Skipped due to --metadata-only mode"},
            )
            layers["embedding_probe"] = LayerResult(
                layer="embedding_probe",
                status="skipped",
                details={"message": "Skipped due to --metadata-only mode"},
            )
            layers["acceleration"] = LayerResult(
                layer="acceleration",
                status="skipped",
                details={"message": "Skipped due to --metadata-only mode"},
            )
        elif has_upstream_failure or not manifest:
            layers["generation_probe"] = LayerResult(
                layer="generation_probe",
                status="not_tested",
                reason="upstream_failure",
                details={"message": "Skipped due to earlier layer failures"},
            )
            layers["embedding_probe"] = LayerResult(
                layer="embedding_probe",
                status="not_tested",
                reason="upstream_failure",
                details={"message": "Skipped due to earlier layer failures"},
            )
            layers["acceleration"] = LayerResult(
                layer="acceleration",
                status="not_tested",
                reason="upstream_failure",
            )
        else:
            # Probe 1: Generation
            gen_model = manifest.generation_model
            t0 = time.time()
            try:
                # Send keep_alive 30s to allow placement inspection via /api/ps
                gen_payload = {
                    "model": gen_model,
                    "prompt": "Hello",
                    "stream": False,
                    "options": {
                        "num_predict": 16,
                        "num_ctx": manifest.smoke_context_tokens,
                    },
                    "keep_alive": "30s",
                }
                status, _, body = client.request("POST", "/api/generate", gen_payload, timeout_seconds=120.0)
                gen_latency_ms = round((time.time() - t0) * 1000, 2)

                if status == 507 or (status != 200 and "out of memory" in body.decode("utf-8", errors="ignore").lower()):
                    reasons.append("memory_capacity")
                    remediations.append("Generation failed due to insufficient memory (RAM/VRAM). Free resources.")
                    layers["generation_probe"] = LayerResult(
                        layer="generation_probe",
                        status="fail",
                        reason="memory_capacity",
                        details={"http_status": status, "latency_ms": gen_latency_ms},
                        remediation=remediations[-1],
                    )
                elif status != 200:
                    reasons.append("execution_failed")
                    remediations.append(f"Generation request returned HTTP {status}.")
                    layers["generation_probe"] = LayerResult(
                        layer="generation_probe",
                        status="fail",
                        reason="execution_failed",
                        details={"http_status": status, "latency_ms": gen_latency_ms},
                        remediation=remediations[-1],
                    )
                else:
                    gen_data = json.loads(body.decode("utf-8"))
                    if not gen_data.get("done") or not gen_data.get("response"):
                        reasons.append("execution_failed")
                        remediations.append("Generation response was incomplete or contained empty response text.")
                        layers["generation_probe"] = LayerResult(
                            layer="generation_probe",
                            status="fail",
                            reason="execution_failed",
                            details={"latency_ms": gen_latency_ms},
                            remediation=remediations[-1],
                        )
                    else:
                        # Check /api/ps for generation placement
                        try:
                            ps_st, _, ps_body = client.request("GET", "/api/ps", timeout_seconds=5.0)
                            if ps_st == 200:
                                ps_data = json.loads(ps_body.decode("utf-8"))
                                for m in ps_data.get("models", []):
                                    if m.get("name") == gen_model or m.get("model") == gen_model:
                                        sz = m.get("size", 0)
                                        vram = m.get("size_vram", 0)
                                        if sz > 0 and vram == sz:
                                            observed_gen_placement = "gpu"
                                        elif vram == 0:
                                            observed_gen_placement = "cpu"
                                        else:
                                            observed_gen_placement = "mixed"
                                        break
                        except Exception:
                            pass

                        layers["generation_probe"] = LayerResult(
                            layer="generation_probe",
                            status="pass",
                            details={
                                "model": gen_model,
                                "latency_ms": gen_latency_ms,
                                "done": True,
                                "observed_placement": observed_gen_placement or "unknown",
                            },
                        )
            except Exception as err:
                err_str = str(err).lower()
                if "timed out" in err_str:
                    reasons.append("request_timeout")
                    remediations.append("Generation probe timed out after 120.0 seconds.")
                    layers["generation_probe"] = LayerResult(
                        layer="generation_probe",
                        status="fail",
                        reason="request_timeout",
                        details={"error": str(err)},
                        remediation=remediations[-1],
                    )
                else:
                    reasons.append("execution_failed")
                    remediations.append(f"Generation probe failed: {err}")
                    layers["generation_probe"] = LayerResult(
                        layer="generation_probe",
                        status="fail",
                        reason="execution_failed",
                        details={"error": str(err)},
                        remediation=remediations[-1],
                    )
            finally:
                # Always unload generation model
                try:
                    client.request("POST", "/api/generate", {"model": gen_model, "keep_alive": 0}, timeout_seconds=5.0)
                except Exception:
                    pass

            # Probe 2: Embedding
            emb_model = manifest.embedding_model
            t0 = time.time()
            try:
                emb_payload = {
                    "model": emb_model,
                    "input": ["Hello world", "Job automation test"],
                    "truncate": False,
                    "keep_alive": "30s",
                }
                status, _, body = client.request("POST", "/api/embed", emb_payload, timeout_seconds=120.0)
                emb_latency_ms = round((time.time() - t0) * 1000, 2)

                if status == 404:
                    reasons.append("runtime_incompatible")
                    remediations.append(
                        "Route /api/embed returned HTTP 404. Ollama version is too old or does not support /api/embed."
                    )
                    layers["embedding_probe"] = LayerResult(
                        layer="embedding_probe",
                        status="fail",
                        reason="runtime_incompatible",
                        details={"http_status": 404},
                        remediation=remediations[-1],
                    )
                elif status == 507 or (status != 200 and "out of memory" in body.decode("utf-8", errors="ignore").lower()):
                    reasons.append("memory_capacity")
                    remediations.append("Embedding probe failed due to insufficient memory (RAM/VRAM).")
                    layers["embedding_probe"] = LayerResult(
                        layer="embedding_probe",
                        status="fail",
                        reason="memory_capacity",
                        details={"http_status": status, "latency_ms": emb_latency_ms},
                        remediation=remediations[-1],
                    )
                elif status != 200:
                    reasons.append("execution_failed")
                    remediations.append(f"Embedding probe returned HTTP {status}.")
                    layers["embedding_probe"] = LayerResult(
                        layer="embedding_probe",
                        status="fail",
                        reason="execution_failed",
                        details={"http_status": status, "latency_ms": emb_latency_ms},
                        remediation=remediations[-1],
                    )
                else:
                    emb_data = json.loads(body.decode("utf-8"))
                    vectors = emb_data.get("embeddings", [])
                    # Validate vector properties: exactly 2 vectors, equal length, finite floats (excluding booleans)
                    valid_shape = (
                        isinstance(vectors, list)
                        and len(vectors) == 2
                        and isinstance(vectors[0], list)
                        and isinstance(vectors[1], list)
                        and len(vectors[0]) > 0
                        and len(vectors[0]) == len(vectors[1])
                    )

                    valid_values = False
                    if valid_shape:
                        valid_values = all(
                            not isinstance(val, bool)
                            and isinstance(val, (int, float))
                            and math.isfinite(val)
                            for vec in vectors
                            for val in vec
                        )

                    observed_dim = len(vectors[0]) if (valid_shape and vectors) else None
                    runtime_info["observed_embedding_dimension"] = observed_dim

                    if not valid_shape or not valid_values:
                        reasons.append("embedding_response_invalid")
                        remediations.append(
                            "Embedding output did not match expected 2-vector shape with finite numeric values."
                        )
                        layers["embedding_probe"] = LayerResult(
                            layer="embedding_probe",
                            status="fail",
                            reason="embedding_response_invalid",
                            details={"latency_ms": emb_latency_ms, "valid_shape": valid_shape, "valid_values": valid_values},
                            remediation=remediations[-1],
                        )
                    elif manifest.embedding_dimension and observed_dim != manifest.embedding_dimension:
                        reasons.append("embedding_response_invalid")
                        remediations.append(
                            f"Embedding dimension {observed_dim} does not match expected {manifest.embedding_dimension}."
                        )
                        layers["embedding_probe"] = LayerResult(
                            layer="embedding_probe",
                            status="fail",
                            reason="embedding_response_invalid",
                            details={
                                "latency_ms": emb_latency_ms,
                                "observed_dimension": observed_dim,
                                "expected_dimension": manifest.embedding_dimension,
                            },
                            remediation=remediations[-1],
                        )
                    else:
                        # Check placement
                        try:
                            ps_st, _, ps_body = client.request("GET", "/api/ps", timeout_seconds=5.0)
                            if ps_st == 200:
                                ps_data = json.loads(ps_body.decode("utf-8"))
                                for m in ps_data.get("models", []):
                                    if m.get("name") == emb_model or m.get("model") == emb_model:
                                        sz = m.get("size", 0)
                                        vram = m.get("size_vram", 0)
                                        if sz > 0 and vram == sz:
                                            observed_emb_placement = "gpu"
                                        elif vram == 0:
                                            observed_emb_placement = "cpu"
                                        else:
                                            observed_emb_placement = "mixed"
                                        break
                        except Exception:
                            pass

                        layers["embedding_probe"] = LayerResult(
                            layer="embedding_probe",
                            status="pass",
                            details={
                                "model": emb_model,
                                "latency_ms": emb_latency_ms,
                                "vector_count": len(vectors),
                                "dimension": observed_dim,
                                "observed_placement": observed_emb_placement or "unknown",
                            },
                        )
            except Exception as err:
                err_str = str(err).lower()
                if "timed out" in err_str:
                    reasons.append("request_timeout")
                    remediations.append("Embedding probe timed out after 120.0 seconds.")
                    layers["embedding_probe"] = LayerResult(
                        layer="embedding_probe",
                        status="fail",
                        reason="request_timeout",
                        details={"error": str(err)},
                        remediation=remediations[-1],
                    )
                else:
                    reasons.append("execution_failed")
                    remediations.append(f"Embedding probe failed: {err}")
                    layers["embedding_probe"] = LayerResult(
                        layer="embedding_probe",
                        status="fail",
                        reason="execution_failed",
                        details={"error": str(err)},
                        remediation=remediations[-1],
                    )
            finally:
                # Always unload embedding model
                try:
                    client.request("POST", "/api/generate", {"model": emb_model, "keep_alive": 0}, timeout_seconds=5.0)
                except Exception:
                    pass

            # Acceleration evaluation (Story 05)
            observed_accel = "unknown"
            if observed_gen_placement == "gpu" or observed_emb_placement == "gpu":
                observed_accel = "gpu"
            elif observed_gen_placement == "cpu" and observed_emb_placement == "cpu":
                observed_accel = "cpu"
            elif observed_gen_placement == "mixed" or observed_emb_placement == "mixed":
                observed_accel = "mixed"

            layers["acceleration"] = LayerResult(
                layer="acceleration",
                status="pass",
                details={
                    "requested_mode": manifest.acceleration_mode,
                    "observed_acceleration": observed_accel,
                    "generation_placement": observed_gen_placement,
                    "embedding_placement": observed_emb_placement,
                },
            )

        # -------------------------------------------------------------
        # Layer 6: Status & Exit Code Resolution
        # -------------------------------------------------------------
        # Determine exit code based on precedence: 2 > 3 > 4 > 5 > 6 > 0
        resolved_exit = EXIT_SUCCESS
        for candidate_code in EXIT_PRECEDENCE:
            if candidate_code == EXIT_SUCCESS:
                break

            match candidate_code:
                case 2:
                    if any(r in reasons for r in [
                        "invalid_config", "manifest_invalid", "endpoint_mismatch",
                        "unsafe_binding", "output_in_source", "cache_path_invalid"
                    ]):
                        resolved_exit = 2
                        break
                case 3:
                    if any(r in reasons for r in [
                        "runtime_not_installed", "runtime_path_invalid",
                        "runtime_not_running", "port_conflict",
                        "runtime_incompatible", "runtime_response_invalid"
                    ]):
                        resolved_exit = 3
                        break
                case 4:
                    if any(r in reasons for r in [
                        "generation_model_missing", "embedding_model_missing",
                        "model_capability_mismatch", "model_digest_mismatch"
                    ]):
                        resolved_exit = 4
                        break
                case 5:
                    if any(r in reasons for r in [
                        "execution_failed", "memory_capacity", "storage_capacity",
                        "request_timeout", "runtime_busy", "embedding_response_invalid",
                        "acceleration_failed"
                    ]):
                        resolved_exit = 5
                        break
                case 6:
                    if any(r in reasons for r in [
                        "metadata_only", "active_tests_pending", "cpu_fallback_unverified"
                    ]):
                        resolved_exit = 6
                        break

        # Compute overall status
        if resolved_exit == EXIT_SUCCESS:
            accel_layer = layers.get("acceleration")
            obs = accel_layer.details.get("observed_acceleration") if accel_layer else None
            if obs == "cpu" or (manifest and manifest.acceleration_mode == "cpu"):
                overall_status = "ready_cpu"
            else:
                overall_status = "ready"
        elif resolved_exit == EXIT_METADATA_ONLY_OR_INCOMPLETE:
            overall_status = "metadata_healthy" if self.metadata_only else "incomplete"
        else:
            overall_status = "failed"

        report = HealthReport(
            schema_version="1.0",
            timestamp_utc=now_utc,
            check_mode="metadata_only" if self.metadata_only else "full",
            effective_url=redact_url_credentials(effective_url),
            overall_status=overall_status,
            exit_code=resolved_exit,
            reasons=reasons,
            remediations=remediations,
            layers=layers,
            runtime_info=runtime_info,
            hardware_info=hardware_info,
        )

        if self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(
                json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        return report
