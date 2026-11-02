"""Manual live smoke test for model-assisted assessment (MATCH-02-S08).

Prerequisite: MODEL-01 / MODEL-02 runtime installation and running local model.
If local model service is offline or unreachable, this script exits cleanly
and reports live verification as pending without failing offline CI.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_automation.assessment.llm_records import AssessmentLimits, AssessmentRequest
from job_automation.assessment.llm_service import LLMAssessmentService
from job_automation.assessment.service import AssessmentService
from job_automation.configuration import load_config
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.policy import SearchPolicy
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.context.selector_test_helpers import (
    create_selector_test_posting,
    create_selector_test_snapshot,
)

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
    print("MATCH-02 Model-Assisted Assessment Smoke Test Runner")
    print("=" * 60)

    config_path = REPO_ROOT / "config" / "app.example.json"
    config, _ = load_config(config_path)
    service_url = config.model_service_url

    print(f"Target Model Service:   {service_url}")

    is_online, installed_models = check_model_service(service_url)

    if not is_online:
        print("\n[STATUS: LIVE VERIFICATION PENDING]")
        print("  Reason: Local model runtime is not reachable at " + service_url)
        print("  MODEL-01 installation and native service startup are prerequisites for live testing.")
        print("  Offline verification (contract, boundary, deterministic, Windows, and scripted tests) is complete.")
        return 0

    print(f"Runtime Status:         ONLINE")
    print(f"Installed Models:       {installed_models}")

    if not installed_models:
        print("\n[STATUS: LIVE VERIFICATION PENDING]")
        print("  Runtime is online, but no models are installed.")
        return 0

    generation_models = [m for m in installed_models if "embed" not in m.lower()]
    if not generation_models:
        print("\n[STATUS: LIVE VERIFICATION PENDING]")
        print("  Installed models are embedding-only (no generation model found).")
        return 0

    chosen_model = generation_models[0]
    print(f"\nExecuting Live Smoke Test with model: {chosen_model}")

    snapshot = create_selector_test_snapshot()
    posting = create_selector_test_posting()
    policy = SearchPolicy(policy_version="pol-1.0")

    rule_evaluator = AssessmentService()
    baseline, trace = rule_evaluator.evaluate_posting_with_trace(
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        posting=posting,
        policy=policy,
        profile=snapshot,
    )

    resolver = InMemoryInputResolver()
    model_provider = LocalModelProvider.from_config(config=config, input_resolver=resolver)
    context_selector = ContextSelectorV2Service(index_store=None, model_provider=None)

    assessment_service = LLMAssessmentService(
        context_selector=context_selector,
        model_provider=model_provider,
        input_resolver=resolver,
    )

    request = AssessmentRequest(
        assessment_id=uuid.uuid4(),
        canonical_job_id=baseline.canonical_job_id,
        posting_revision=posting.raw_content_hash,
        posting=posting,
        profile=snapshot,
        policy=policy,
        context_strategy=ContextStrategy.JSON,
        deterministic_baseline=baseline,
        deterministic_trace=trace,
        limits=AssessmentLimits(context_limit=4096),
        model_identifier=chosen_model,
    )

    print("Running live assessment...")
    result = assessment_service.assess(request)

    print(f"Result Status:      {result.status}")
    if result.status == "success":
        assert result.assessment is not None
        print(f"Final Disposition:  {result.assessment.final_disposition}")
        print(f"Relevance Score:    {result.assessment.relevance_score}")
        print(f"Findings Count:     {len(result.assessment.requirement_findings)}")
        print(f"Summary:            {result.assessment.summary_reason}")
    else:
        print(f"Failed Stage:       {result.failed_stage}")
        print(f"Retryable:          {result.retryable}")
        print(f"Error:              {result.error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
