"""Model runtime readiness probing, cold-start deadlines, and supervisor health checks (AUTO-01-S02).

Enforces:
- Strict loopback URL policy (rejects non-loopback bindings).
- Bounded HTTP probes against /api/tags without shell commands.
- Explicit classification of missing runtime, missing model weights, access denial, and timeouts.
- Monotonic elapsed deadline for cold-start wait (proposed default 180s).
- Zero automatic downloading of model weights at runtime.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from job_automation.operations.scheduling.records import (
    BootstrapCategory,
    ReadinessProbeResult,
)

logger = logging.getLogger(__name__)


def is_loopback_url(url: str) -> bool:
    """Validate that the given URL binds strictly to IPv4 or IPv6 loopback."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return host in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


def probe_model_readiness(
    url: str = "http://127.0.0.1:11434",
    required_model: str | None = None,
    timeout_seconds: float = 3.0,
) -> ReadinessProbeResult:
    """Execute a single bounded health check against the local model runtime."""
    # 1. Enforce loopback policy
    if not is_loopback_url(url):
        return ReadinessProbeResult(
            is_ready=False,
            category=BootstrapCategory.ACCESS_DENIED,
            details=f"Loopback security violation: service URL '{url}' is not on localhost/127.0.0.1",
            installed_models=[],
        )

    clean_url = url.rstrip("/")
    tags_url = f"{clean_url}/api/tags"

    start_mono = time.monotonic()
    try:
        req = urllib.request.Request(
            tags_url,
            headers={"User-Agent": "JobAutomation-Scheduler/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            elapsed_ms = (time.monotonic() - start_mono) * 1000.0
            if resp.status == 200:
                raw_body = resp.read().decode("utf-8")
                body = json.loads(raw_body)
                raw_models = body.get("models", [])
                installed: list[str] = []
                for m in raw_models:
                    if isinstance(m, dict) and "name" in m:
                        installed.append(m["name"])
                    elif isinstance(m, str):
                        installed.append(m)

                # Check if required model is present
                if required_model:
                    req_clean = required_model.lower().strip()
                    # Match exact name or name:latest or prefix
                    matched = False
                    for inst in installed:
                        inst_clean = inst.lower().strip()
                        if inst_clean == req_clean or inst_clean == f"{req_clean}:latest" or req_clean == f"{inst_clean}:latest":
                            matched = True
                            break
                        if inst_clean.split(":")[0] == req_clean.split(":")[0]:
                            matched = True
                            break

                    if not matched:
                        return ReadinessProbeResult(
                            is_ready=False,
                            category=BootstrapCategory.MODEL_MISSING,
                            details=f"Runtime is online, but required model '{required_model}' is not installed. Found: {installed}",
                            installed_models=installed,
                            latency_ms=elapsed_ms,
                        )

                return ReadinessProbeResult(
                    is_ready=True,
                    category=BootstrapCategory.OK,
                    details="Model runtime is healthy and responsive",
                    installed_models=installed,
                    latency_ms=elapsed_ms,
                )
            else:
                return ReadinessProbeResult(
                    is_ready=False,
                    category=BootstrapCategory.RUNTIME_OFFLINE,
                    details=f"Runtime returned HTTP {resp.status}",
                    installed_models=[],
                    latency_ms=elapsed_ms,
                )

    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.monotonic() - start_mono) * 1000.0
        cat = BootstrapCategory.ACCESS_DENIED if exc.code in (401, 403) else BootstrapCategory.RUNTIME_OFFLINE
        if exc.code >= 500:
            cat = BootstrapCategory.RESOURCE_EXHAUSTED
        return ReadinessProbeResult(
            is_ready=False,
            category=cat,
            details=f"HTTP error from model runtime: {exc}",
            installed_models=[],
            latency_ms=elapsed_ms,
        )

    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed_ms = (time.monotonic() - start_mono) * 1000.0
        return ReadinessProbeResult(
            is_ready=False,
            category=BootstrapCategory.RUNTIME_OFFLINE,
            details=f"Model runtime is offline or unreachable at '{url}': {exc}",
            installed_models=[],
            latency_ms=elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start_mono) * 1000.0
        return ReadinessProbeResult(
            is_ready=False,
            category=BootstrapCategory.RUNTIME_OFFLINE,
            details=f"Unexpected error probing model runtime: {exc}",
            installed_models=[],
            latency_ms=elapsed_ms,
        )


def wait_for_model_readiness(
    url: str = "http://127.0.0.1:11434",
    required_model: str | None = None,
    deadline_seconds: float = 180.0,
    poll_interval: float = 2.0,
) -> ReadinessProbeResult:
    """Poll model runtime until healthy or monotonic cold-start deadline expires."""
    start_mono = time.monotonic()
    last_res: ReadinessProbeResult | None = None

    while True:
        res = probe_model_readiness(url=url, required_model=required_model, timeout_seconds=min(3.0, poll_interval))
        if res.is_ready:
            return res

        last_res = res
        elapsed = time.monotonic() - start_mono
        if elapsed >= deadline_seconds:
            # Deadline expired
            return ReadinessProbeResult(
                is_ready=False,
                category=BootstrapCategory.TIMEOUT,
                details=f"Cold-start deadline of {deadline_seconds:.1f}s exceeded. Last status: {res.category.value} ({res.details})",
                installed_models=res.installed_models,
                latency_ms=res.latency_ms,
            )

        time.sleep(poll_interval)

