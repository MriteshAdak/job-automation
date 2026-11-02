"""Tests for profile snapshot freezing, approval authorization, and purpose permissions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import DocumentType, EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestProfileAuthorization:
    def test_profile_freeze_preserves_fact_hierarchy_and_precision(
        self, engine: StorageEngine
    ) -> None:
        cand_id = uuid.uuid4()
        f1 = uuid.uuid4()
        f2 = uuid.uuid4()
        facts = [
            CandidateFact(
                fact_id=f1,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Principal Architect",
                organization="Berlin Cloud Tech",
                start_date=PrecisionDate(value="2022-06", precision="month"),
                skills=["Python", "GCP"],
                claims=["Architected mission-critical platform"],
                metrics=["100% test coverage"],
                provenance="cv_v2.pdf",
                allowed_uses=["cv"],  # only for CV, not for cover_letter!
            ),
            CandidateFact(
                fact_id=f2,
                kind=EvidenceFactKind.SKILL,
                parent_id=f1,
                title="Kubernetes Reliability",
                skills=["Kubernetes"],
                claims=["Multi-region failover"],
                provenance="cv_v2.pdf",
                allowed_uses=["cv", "cover_letter"],
            ),
        ]
        profile = publish_approved_profile(
            engine,
            candidate_id=cand_id,
            profile_version="v2",
            facts=facts,
            approved_by="test_reviewer",
        )

        job, _, _ = create_job_with_posting(engine)
        service = DefaultGenerationInputService(engine=engine)

        # 1. CV request includes f1 and f2
        req_cv = make_request(job_id=job.canonical_job_id, doc_type=DocumentType.CV)
        engine.generation_requests.create_request(req_cv)
        service.prepare_freeze(req_cv, f"freeze:{req_cv.request_id}")

        seal_cv, _ = service.get_seal(req_cv.request_id)
        assert seal_cv is not None
        assert f1 in seal_cv.profile_snapshot.eligible_fact_ids
        assert f2 in seal_cv.profile_snapshot.eligible_fact_ids
        assert seal_cv.profile_snapshot.approved_by == "test_reviewer"

        # 2. Cover letter request excludes f1 because f1 allowed_uses is only ['cv']
        req_cl = make_request(job_id=job.canonical_job_id, doc_type=DocumentType.COVER_LETTER)
        engine.generation_requests.create_request(req_cl)
        service.prepare_freeze(req_cl, f"freeze:{req_cl.request_id}")

        seal_cl, _ = service.get_seal(req_cl.request_id)
        assert seal_cl is not None
        assert f1 not in seal_cl.profile_snapshot.eligible_fact_ids
        assert f2 in seal_cl.profile_snapshot.eligible_fact_ids

