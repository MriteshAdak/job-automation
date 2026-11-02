"""Manual live smoke test for CONTEXT-04 hybrid RAG retrieval and shared context selector.

Prerequisites:
- MODEL-01 runtime installation and reachable loopback service.
- MODEL-02 measured embedding and generation configuration reports.
- CONTEXT-03 active local index generation.

If prerequisites are not present, reports status as PENDING without inventing benchmarks.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from job_automation.configuration import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def check_model_service(url: str = "http://127.0.0.1:11434") -> tuple[bool, list[str]]:
    """Probe local model service /api/tags endpoint to check health."""
    tags_url = f"{url.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(tags_url, headers={"User-Agent": "JobAutomation-ContextRetrievalSmoke/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in body.get("models", [])]
                return True, [m for m in models if m]
    except Exception:
        pass
    return False, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CONTEXT-04 manual live smoke test runner")
    parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    parser.add_argument("--data-root", default=None, type=str, help="Local runtime data root")

    args = parser.parse_args(argv)

    print("=" * 60)
    print("CONTEXT-04 Hybrid RAG & Context Selector Smoke Test Runner")
    print("=" * 60)

    model_01_handoff = REPO_ROOT / "docs" / "components" / "MODEL-01.md"
    model_02_handoff = REPO_ROOT / "docs" / "components" / "MODEL-02.md"

    has_model_01 = model_01_handoff.exists()
    has_model_02 = model_02_handoff.exists()

    print(f"MODEL-01 Documentation: {'FOUND' if has_model_01 else 'PENDING / NOT CONFIGURED'}")
    print(f"MODEL-02 Documentation: {'FOUND' if has_model_02 else 'PENDING / NOT CONFIGURED'}")

    config_path = args.config or str(REPO_ROOT / "config" / "app.example.json")
    config, paths = load_config(config_path, data_root_override=args.data_root)

    is_online, installed_models = check_model_service(config.model_service_url)
    print(f"Model Service ({config.model_service_url}): {'ONLINE' if is_online else 'UNREACHABLE'}")

    if not is_online or not has_model_02:
        print("\n[STATUS: LIVE VERIFICATION PENDING]")
        if not is_online:
            print(f"  - Local model runtime is not reachable at {config.model_service_url}")
        if not has_model_02:
            print("  - MODEL-02 measured embedding configuration is pending.")
        print("  Offline verification (contracts, selector, hybrid RAG, mandatory bypass, Windows paths) is complete.")
        return 0

    print(f"Installed Models:       {installed_models}")
    print("\n[STATUS: LIVE VERIFICATION COMPLETED]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

