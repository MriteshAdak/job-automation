#!/usr/bin/env python3
"""Manual diagnostic entry point for MODEL-01 local runtime health checks.

Usage:
    python scripts/model_runtime_health.py --config config/local.model-runtime.json --runtime-config config/local.model-runtime-manifest.json
    python scripts/model_runtime_health.py --config config/app.example.json --runtime-config config/model-runtime.example.json --metadata-only --json

Exit codes:
    0: All checks passed (ready or ready_cpu)
    2: Configuration, manifest, or unsafe binding error
    3: Runtime unavailable, not running, or incompatible
    4: Model missing, capability mismatch, or digest mismatch
    5: Active execution, memory, or capacity failure
    6: Metadata-only check completed successfully or active checks incomplete
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from job_automation.models.runtime_health import (
    ModelRuntimeManifest,
    RuntimeHealthChecker,
    normalize_digest,
)


def format_human_report(report_dict: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("JOB SEARCH AUTOMATION — MODEL RUNTIME HEALTH DIAGNOSTICS (MODEL-01)")
    lines.append("=" * 70)
    lines.append(f"Timestamp (UTC):     {report_dict.get('timestamp_utc')}")
    lines.append(f"Check Mode:          {report_dict.get('check_mode')}")
    lines.append(f"Effective URL:       {report_dict.get('effective_url')}")
    lines.append(f"Overall Status:      {report_dict.get('overall_status')}")
    lines.append(f"Exit Code:           {report_dict.get('exit_code')}")

    hw = report_dict.get("hardware_info", {})
    if hw.get("os_caption"):
        lines.append("-" * 70)
        lines.append("Host Hardware Context (Windows):")
        lines.append(f"  OS:                {hw.get('os_caption')} (Build {hw.get('os_build')})")
        lines.append(f"  CPU:               {hw.get('cpu_name')} ({hw.get('cpu_cores')} cores, {hw.get('cpu_logical')} logical)")
        lines.append(f"  Total RAM:         {hw.get('ram_total_gb')} GB")
        for idx, gpu in enumerate(hw.get("gpus", []), 1):
            lines.append(f"  GPU #{idx}:          {gpu.get('Name')} (Driver: {gpu.get('DriverVersion')})")

    lines.append("-" * 70)
    lines.append("Layer Diagnostic Results:")
    layers = report_dict.get("layers", {})
    for layer_name, layer_info in layers.items():
        status = layer_info.get("status", "").upper()
        reason = f" [{layer_info.get('reason')}]" if layer_info.get("reason") else ""
        lines.append(f"  • {layer_name:<20}: {status}{reason}")
        for k, v in layer_info.get("details", {}).items():
            if isinstance(v, (str, int, float, bool)):
                lines.append(f"      - {k}: {v}")

    if report_dict.get("reasons"):
        lines.append("-" * 70)
        lines.append("Identified Diagnostic Reasons:")
        for r in report_dict["reasons"]:
            lines.append(f"  [!] {r}")

    if report_dict.get("remediations"):
        lines.append("-" * 70)
        lines.append("Recommended Remediation Steps:")
        for rem in report_dict["remediations"]:
            lines.append(f"  -> {rem}")

    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify local model runtime installation, loopback listener, model inventory, and inference capabilities."
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to application configuration JSON (e.g. config/app.example.json).",
    )
    parser.add_argument(
        "--runtime-config",
        required=True,
        type=Path,
        help="Path to model runtime setup manifest JSON (e.g. config/model-runtime.example.json).",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Perform only non-intrusive metadata checks (executable, listener, tags, show) without active inference.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output structured JSON report to standard output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write report JSON. Must reside outside repository source root.",
    )

    args = parser.parse_args()

    checker = RuntimeHealthChecker(
        app_config_path=args.config,
        manifest_path=args.runtime_config,
        metadata_only=args.metadata_only,
        output_path=args.output,
        repo_root=REPO_ROOT,
    )

    report = checker.run_check()
    report_dict = report.model_dump()

    if args.json_output:
        print(json.dumps(report_dict, indent=2, ensure_ascii=False))
    else:
        print(format_human_report(report_dict))

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())

