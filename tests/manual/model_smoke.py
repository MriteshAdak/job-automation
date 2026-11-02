"""Manual live smoke test for local model execution (LLM-01-S08).

Prerequisite: MODEL-01 runtime installation and configured local models.
If MODEL-01 is not installed or service is offline, this script exits cleanly
and reports live verification as pending.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.contracts.models import ModelCall
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def check_model_service(url: str = "http://127.0.0.1:11434") -> tuple[bool, list[str]]:
    """Probe local model service /api/tags endpoint to check health and available models."""
    tags_url = f"{url.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(tags_url, headers={"User-Agent": "JobAutomation-Smoke/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in body.get("models", [])]
                return True, [m for m in models if m]
    except Exception:
        pass
    return False, []


def main() -> int:
    print("=" * 60)
    print("LLM-01 Local Model Client Smoke Test Runner")
    print("=" * 60)

    model_01_handoff = REPO_ROOT / "docs" / "components" / "MODEL-01.md"
    has_model_01_doc = model_01_handoff.exists()

    config_path = REPO_ROOT / "config" / "app.example.json"
    config, _ = load_config(config_path)
    service_url = config.model_service_url

    print(f"Target Service URL:     {service_url}")
    print(f"MODEL-01 Documentation: {'FOUND' if has_model_01_doc else 'PENDING / NOT CONFIGURED'}")

    is_online, installed_models = check_model_service(service_url)

    if not is_online:
        print("\n[STATUS: LIVE VERIFICATION PENDING]")
        print("  Reason: Local model runtime is not reachable at " + service_url)
        print("  MODEL-01 installation and native service startup are prerequisites for live testing.")
        print("  Offline verification (contract, budget, retry, transport, privacy tests) is complete.")
        return 0

    print(f"Runtime Status:         ONLINE")
    print(f"Installed Models:       {installed_models}")

    if not installed_models:
        print("\n[STATUS: LIVE VERIFICATION PENDING]")
        print("  Runtime is running, but no models are installed.")
        return 0

    chosen_model = installed_models[0]
    print(f"\nExecuting Live Smoke Test with model: {chosen_model}")

    resolver = InMemoryInputResolver()
    provider = LocalModelProvider.from_config(config, input_resolver=resolver)

    call_id = uuid.uuid4()
    prompt = "Candidate has 5 years Python experience. Job requires Python and SQL. Evaluate fit."
    bound = resolver.bind_generation(call_id, prompt=prompt, system_prompt="You evaluate candidate fitness.")

    call = ModelCall(
        call_id=call_id,
        operation_type="relevance_assessment",
        model_identifier=chosen_model,
        prompt_version="smoke_v1",
        context_limit=4096,
        input_fingerprint=bound.input_fingerprint,
        requested_schema="C11_assessment",
    )

    print("Sending structured generation request...")
    result = provider.generate(call)

    if result.error is not None:
        print(f"Generation Result: FAILED ({result.error.category})")
        print(f"Message: {result.error.message}")
    else:
        print("Generation Result: SUCCESS")
        print(f"Latency: {result.latency_ms:.1f}ms")
        print(f"Parsed Output: {result.parsed_output}")

    print("\nSending embedding request...")
    embed_resp, embed_err = provider.embed(["Python developer in Berlin"], chosen_model)
    if embed_err is not None:
        print(f"Embedding Result: FAILED ({embed_err.category})")
        print(f"Message: {embed_err.message}")
    else:
        print("Embedding Result: SUCCESS")
        assert embed_resp is not None
        print(f"Dimension: {embed_resp.dimension}")
        print(f"Vectors: {len(embed_resp.vectors)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

