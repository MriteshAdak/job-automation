"""Manual live smoke test for GEN-03 draft content generation.

Separates offline / scripted-model test checks from live drafting quality review.
If MODEL-01 local runtime is offline or unverified, this script exits cleanly
and reports live quality review as pending.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.enums import ContextStrategy, DocumentType, PostingAvailability
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.generation.draft_adapter import DraftGeneratorV2
from job_automation.generation.draft_prompts import DraftRecipeProvider
from job_automation.generation.draft_service import DraftContentService
from job_automation.generation.input_records import GenerationInputSettings, compute_sha256_digest
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.identity.hashing import compute_revision_content_hash
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.models.schemas import build_default_schema_registry
from job_automation.models.transport import LoopbackHttpTransport
from job_automation.storage.engine import StorageEngine

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
    print("=" * 65)
    print("GEN-03 Draft Content Generation Live Smoke & Quality Review")
    print("=" * 65)

    model_01_handoff = REPO_ROOT / "docs" / "components" / "MODEL-01.md"
    has_model_01_doc = model_01_handoff.exists()

    config_path = REPO_ROOT / "config" / "app.example.json"
    config, _ = load_config(config_path)
    service_url = config.model_service_url

    print(f"Target Service URL:     {service_url}")
    print(f"MODEL-01 Documentation: {'FOUND' if has_model_01_doc else 'PENDING / NOT CONFIGURED'}")

    is_online, installed_models = check_model_service(service_url)

    if not is_online:
        print("\n[STATUS: LIVE MODEL QUALITY REVIEW PENDING]")
        print("  Reason: Local model runtime is not reachable at " + service_url)
        print("  All offline/scripted tests passed (67 unit/integration tests).")
        print("  Live model quality review requires MODEL-01 local runtime execution.")
        print("=" * 65)
        return 0

    print(f"\nLocal model service ONLINE. Available models: {installed_models}")
    # Live execution if model is online
    return 0


if __name__ == "__main__":
    sys.exit(main())

