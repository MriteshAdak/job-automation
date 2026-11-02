"""Consumer fakes for JSON and RAG context strategies verifying PROFILE-01 inclusion parity."""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.profile import ProfileSnapshot
from job_automation.profile.models import ProfileInclusionView
from job_automation.profile.service import ProfileService


class FakeJsonContextConsumer:
    """Simulates CONTEXT-01 full JSON context builder consuming ProfileSnapshot."""

    def __init__(self, profile_service: ProfileService) -> None:
        self.service = profile_service

    def build_context(
        self,
        snapshot: ProfileSnapshot,
        purpose: str = "assessment",
    ) -> dict[str, Any]:
        """Obtain inclusion view and construct simulated JSON context bundle."""
        view: ProfileInclusionView = self.service.get_inclusion_view(snapshot, purpose=purpose)
        return {
            "strategy": "json",
            "profile_version": view.profile_version,
            "candidate_id": view.candidate_id,
            "eligible_fact_ids": view.eligible_fact_ids,
            "facts": [
                {
                    "fact_id": f.fact_id,
                    "title": f.title,
                    "skills": f.skills,
                    "claims": f.claims,
                }
                for f in view.eligible_facts
            ],
            "eligibility": view.explicit_eligibility.model_dump(mode="json"),
            "excluded_count": view.excluded_fact_count,
            "warnings": view.warnings,
        }


class FakeRagContextConsumer:
    """Simulates CONTEXT-02/04 RAG context builder consuming ProfileSnapshot."""

    def __init__(self, profile_service: ProfileService) -> None:
        self.service = profile_service

    def build_index_and_retrieve(
        self,
        snapshot: ProfileSnapshot,
        purpose: str = "assessment",
    ) -> dict[str, Any]:
        """Obtain inclusion view and construct simulated RAG chunks/retrieval universe."""
        view: ProfileInclusionView = self.service.get_inclusion_view(snapshot, purpose=purpose)
        chunks = [
            {
                "chunk_id": f"chunk_{f.fact_id}",
                "fact_id": f.fact_id,
                "text": f"{f.title}: {' '.join(f.claims)}",
                "skills": f.skills,
            }
            for f in view.eligible_facts
        ]
        return {
            "strategy": "rag",
            "profile_version": view.profile_version,
            "candidate_id": view.candidate_id,
            "eligible_fact_ids": view.eligible_fact_ids,
            "chunks": chunks,
            "eligibility": view.explicit_eligibility.model_dump(mode="json"),
            "excluded_count": view.excluded_fact_count,
            "warnings": view.warnings,
        }

