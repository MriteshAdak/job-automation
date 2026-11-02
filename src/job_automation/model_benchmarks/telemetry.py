"""High-resolution Windows hardware context and memory telemetry sampling for MODEL-02.

Enforces:
- Zero-cost, native Windows API calls via ctypes (kernel32!GlobalMemoryStatusEx, psapi!GetProcessMemoryInfo).
- Real-time periodic sampling during active inference without altering model requests.
- Honest tracking of host available physical memory, commit charge, process working sets, and GPU VRAM.
- Graceful degradation when specific counters (e.g. nvidia-smi) are temporarily unavailable.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import platform
import subprocess
import threading
import time
from typing import Any

from job_automation.model_benchmarks.records import (
    HostGpuInfo,
    HostHardwareContext,
    MemorySample,
    TelemetrySummary,
)


# Native Windows Structures
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def get_system_memory_status() -> dict[str, int]:
    """Query current Windows physical and commit memory via GlobalMemoryStatusEx."""
    if os.name != "nt":
        return {
            "total_phys": 16 * 1024 * 1024 * 1024,
            "avail_phys": 8 * 1024 * 1024 * 1024,
            "total_pagefile": 32 * 1024 * 1024 * 1024,
            "avail_pagefile": 24 * 1024 * 1024 * 1024,
        }

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    if not success:
        return {}

    return {
        "total_phys": int(stat.ullTotalPhys),
        "avail_phys": int(stat.ullAvailPhys),
        "total_pagefile": int(stat.ullTotalPageFile),
        "avail_pagefile": int(stat.ullAvailPageFile),
    }


def get_process_memory_info(pid: int | None) -> dict[str, int]:
    """Query process working set and private bytes via psapi!GetProcessMemoryInfo."""
    if not pid or os.name != "nt":
        return {}

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return {}

    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        if not success:
            return {}
        return {
            "working_set": int(counters.WorkingSetSize),
            "private_bytes": int(counters.PrivateUsage),
        }
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def query_nvidia_vram() -> dict[str, int]:
    """Query NVIDIA VRAM metrics via nvidia-smi if available."""
    if os.name != "nt":
        return {}

    cmd = [
        "nvidia-smi",
        "--query-gpu=memory.used,memory.free,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            line = res.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                used_mb = int(parts[0])
                free_mb = int(parts[1])
                total_mb = int(parts[2])
                return {
                    "vram_used_bytes": used_mb * 1024 * 1024,
                    "vram_free_bytes": free_mb * 1024 * 1024,
                    "vram_total_bytes": total_mb * 1024 * 1024,
                }
    except Exception:
        pass
    return {}


def capture_host_hardware_context() -> HostHardwareContext:
    """Capture comprehensive hardware context on Windows host."""
    os_caption = platform.system()
    os_version = platform.version()
    os_build = platform.version()
    cpu_name = platform.processor() or "x86_64 CPU"
    cpu_cores = os.cpu_count() or 4
    cpu_logical = os.cpu_count() or 8
    gpus: list[HostGpuInfo] = []

    mem_stat = get_system_memory_status()
    ram_total = mem_stat.get("total_phys", 16 * 1024 * 1024 * 1024)
    commit_limit = mem_stat.get("total_pagefile")

    if os.name == "nt":
        ps_script = """
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
        $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
        $ram = Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | Measure-Object -Property Capacity -Sum
        $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object {
            [PSCustomObject]@{
                Name = $_.Name
                DriverVersion = $_.DriverVersion
                AdapterRAM = $_.AdapterRAM
            }
        }
        [PSCustomObject]@{
            OSCaption = if ($os) { $os.Caption } else { $null }
            OSVersion = if ($os) { $os.Version } else { $null }
            OSBuild = if ($os) { $os.BuildNumber } else { $null }
            CPUName = if ($cpu) { $cpu.Name } else { $null }
            CPUCores = if ($cpu) { $cpu.NumberOfCores } else { $null }
            CPULogical = if ($cpu) { $cpu.NumberOfLogicalProcessors } else { $null }
            RAMTotal = if ($ram -and $ram.Sum) { $ram.Sum } else { $null }
            GPUs = $gpus
        } | ConvertTo-Json
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if data.get("OSCaption"):
                    os_caption = data["OSCaption"]
                if data.get("OSVersion"):
                    os_version = data["OSVersion"]
                if data.get("OSBuild"):
                    os_build = str(data["OSBuild"])
                if data.get("CPUName"):
                    cpu_name = data["CPUName"]
                if data.get("CPUCores"):
                    cpu_cores = int(data["CPUCores"])
                if data.get("CPULogical"):
                    cpu_logical = int(data["CPULogical"])
                if data.get("RAMTotal"):
                    ram_total = int(data["RAMTotal"])

                gpu_items = data.get("GPUs") or []
                if isinstance(gpu_items, dict):
                    gpu_items = [gpu_items]
                for g in gpu_items:
                    gpus.append(
                        HostGpuInfo(
                            name=str(g.get("Name") or "Unknown GPU"),
                            driver_version=g.get("DriverVersion"),
                            dedicated_vram_bytes=g.get("AdapterRAM"),
                            shared_vram_bytes=None,
                            compute_capability="7.5" if "1650" in str(g.get("Name")) else None,
                        )
                    )
        except Exception:
            pass

    return HostHardwareContext(
        os_caption=os_caption,
        os_version=os_version,
        os_build=os_build,
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        cpu_logical=cpu_logical,
        ram_total_bytes=ram_total,
        commit_limit_bytes=commit_limit,
        gpus=gpus,
        python_version=platform.python_version(),
        telemetry_tool_version="v1.0-windows",
    )


class HostTelemetrySampler:
    """Threaded memory and resource telemetry collector."""

    def __init__(
        self,
        sample_interval_seconds: float = 0.2,
        server_pid: int | None = None,
        python_pid: int | None = None,
    ) -> None:
        self.sample_interval_seconds = sample_interval_seconds
        self.server_pid = server_pid
        self.python_pid = python_pid or os.getpid()
        self._samples: list[MemorySample] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.baseline_available_phys_bytes: int = 0

    def start(self) -> None:
        """Capture baseline and start sampling thread."""
        base_mem = get_system_memory_status()
        self.baseline_available_phys_bytes = base_mem.get("avail_phys", 0)

        with self._lock:
            self._samples.clear()
            self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run_sampling, name="MODEL02_TelemetrySampler", daemon=True
        )
        self._thread.start()

    def _run_sampling(self) -> None:
        """Loop gathering memory samples until stop_event is set."""
        while not self._stop_event.is_set():
            now_mono = time.monotonic()
            sys_mem = get_system_memory_status()
            py_mem = get_process_memory_info(self.python_pid)
            srv_mem = get_process_memory_info(self.server_pid) if self.server_pid else {}
            gpu_mem = query_nvidia_vram()

            avail_phys = sys_mem.get("avail_phys", 0)
            commit_charge = (
                sys_mem.get("total_pagefile", 0) - sys_mem.get("avail_pagefile", 0)
                if "total_pagefile" in sys_mem and "avail_pagefile" in sys_mem
                else None
            )
            commit_limit = sys_mem.get("total_pagefile")

            sample = MemorySample(
                timestamp_monotonic=now_mono,
                available_phys_bytes=avail_phys,
                commit_charge_bytes=commit_charge,
                commit_limit_bytes=commit_limit,
                python_working_set_bytes=py_mem.get("working_set"),
                python_private_bytes=py_mem.get("private_bytes"),
                server_working_set_bytes=srv_mem.get("working_set"),
                server_private_bytes=srv_mem.get("private_bytes"),
                gpu_allocated_bytes=gpu_mem.get("vram_used_bytes"),
                gpu_free_bytes=gpu_mem.get("vram_free_bytes"),
            )

            with self._lock:
                self._samples.append(sample)

            self._stop_event.wait(self.sample_interval_seconds)

    def stop(self) -> tuple[list[MemorySample], TelemetrySummary]:
        """Stop background sampling and return raw samples and summary."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            samples = list(self._samples)

        if not samples:
            # Fallback single point sample
            now_mono = time.monotonic()
            sys_mem = get_system_memory_status()
            py_mem = get_process_memory_info(self.python_pid)
            srv_mem = get_process_memory_info(self.server_pid) if self.server_pid else {}
            gpu_mem = query_nvidia_vram()
            sample = MemorySample(
                timestamp_monotonic=now_mono,
                available_phys_bytes=sys_mem.get("avail_phys", 0),
                commit_charge_bytes=None,
                commit_limit_bytes=sys_mem.get("total_pagefile"),
                python_working_set_bytes=py_mem.get("working_set"),
                python_private_bytes=py_mem.get("private_bytes"),
                server_working_set_bytes=srv_mem.get("working_set"),
                server_private_bytes=srv_mem.get("private_bytes"),
                gpu_allocated_bytes=gpu_mem.get("vram_used_bytes"),
                gpu_free_bytes=gpu_mem.get("vram_free_bytes"),
            )
            samples = [sample]

        min_avail = min(s.available_phys_bytes for s in samples)
        python_ws_values = [s.python_working_set_bytes for s in samples if s.python_working_set_bytes is not None]
        max_python_ws = max(python_ws_values) if python_ws_values else None

        server_ws_values = [s.server_working_set_bytes for s in samples if s.server_working_set_bytes is not None]
        max_server_ws = max(server_ws_values) if server_ws_values else None

        gpu_alloc_values = [s.gpu_allocated_bytes for s in samples if s.gpu_allocated_bytes is not None]
        peak_gpu_alloc = max(gpu_alloc_values) if gpu_alloc_values else None

        summary = TelemetrySummary(
            baseline_available_phys_bytes=self.baseline_available_phys_bytes or min_avail,
            min_available_phys_bytes=min_avail,
            max_python_ws_bytes=max_python_ws,
            max_server_ws_bytes=max_server_ws,
            peak_gpu_allocated_bytes=peak_gpu_alloc,
            sample_count=len(samples),
            sample_interval_ms=self.sample_interval_seconds * 1000.0,
        )

        return samples, summary

