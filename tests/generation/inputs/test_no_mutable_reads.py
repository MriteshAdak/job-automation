"""Tests proving frozen isolation against later mutable edits to profiles, jobs, and indexes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestNoMutableReads:
    def test_context_isolated_from_later_profile_and_job_edits(
        self, engine: StorageEngine
    ) -> None:
        """After sealing request on J1 and P1, mutating job text and publishing P2 does not alter frozen context."""
        f1_id = uuid.uuid4()
        cand_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)

        # 1. Setup P1
        facts_p1 = [
            CandidateFact(
                fact_id=f1_id,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="P1 Original Job Title",
                organization="Tech GmbH",
                skills=["Python"],
                claims=["Original P1 claim"],
                provenance="cv_v1.pdf",
                allowed_uses=["cv", "cover_letter"],
            )
        ]
        p1 = publish_approved_profile(engine, candidate_id=cand_id, profile_version="v1", facts=facts_p1, is_current=True)

        # 2. Setup J1
        job, rev, posting = create_job_with_posting(
            engine,
            title="J1 Original Posting Title",
            description="Original J1 Description with Python",
        )

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.JSON)
        engine.generation_requests.create_request(req)

        # 3. Seal the request on J1 and P1
        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None
        assert manifest.profile_version == "v1"

        # 4. Now perform mutable edits!
        # A. Publish P2 with modified text under the exact same fact ID
        facts_p2 = [
            CandidateFact(
                fact_id=f1_id,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="P2 Mutated Job Title",
                organization="Tech GmbH",
                skills=["Python", "Go"],
                claims=["Mutated P2 claim that did not exist at freeze"],
                provenance="cv_v2.pdf",
                allowed_uses=["cv", "cover_letter"],
            )
        ]
        p2 = publish_approved_profile(engine, candidate_id=cand_id, profile_version="v2", facts=facts_p2, is_current=True)
        assert engine.profiles.get_current_version(cand_id) == "v2"

        # B. Mutate normalized posting in storage
        engine.conn.execute(
            "UPDATE normalized_postings SET title = 'J2 Mutated Title' WHERE provider = ?",
            (rev.source_key.provider,),
        )

        # 5. Build context for the original sealed request
        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None

        # Verify context strictly reflects J1 and P1!
        assert bundle.posting_revision == rev.content_hash
        assert len(bundle.ordered_facts) == 1
        admitted_fact = bundle.ordered_facts[0]
        assert admitted_fact.title == "P1 Original Job Title"
        assert admitted_fact.claims == ["Original P1 claim"]
        assert "Mutated P2 claim" not in admitted_fact.claims

