"""Integration tests covering multi-version profile snapshots, purposes, and bound jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.records import JsonContextRequest
from job_automation.context.service import ContextService
from job_automation.contracts.enums import EvidenceFactKind, WorkplaceType
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine


def create_job_posting(rev_hash: str) -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="int-1"),
        normalizer_version="1.0",
        raw_reference="raw_int_1",
        raw_content_hash=rev_hash,
        company_name_hint="FinTech Cloud AG",
        title="Senior Python Platform Engineer",
        description_clean="We build high throughput event-driven microservices on AWS and Kubernetes.",
        workplace_type=WorkplaceType.HYBRID,
        source_url="https://example.com/job/int-1",
        observed_at=datetime.now(timezone.utc),
    )


class TestContextIntegration:
    def test_multi_version_lifecycle_and_purpose_matrix(self, tmp_path: Path) -> None:
        db_path = tmp_path / "integration_test.db"
        cid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        job_id = uuid.uuid4()
        rev_hash = "sha256:" + "8" * 64
        posting = create_job_posting(rev_hash)

        f_role = uuid.uuid4()
        f_proj = uuid.uuid4()
        f_v2_new = uuid.uuid4()

        # v1 Snapshot: f_role (assessment, cv), f_proj (assessment, cv)
        snapshot_v1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1.0",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(
                    fact_id=f_role,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Backend Software Engineer",
                    organization="Scale Corp",
                    start_date=PrecisionDate(value="2020", precision="year"),
                    end_date=PrecisionDate(value="2022", precision="year"),
                    skills=["Python", "FastAPI"],
                    provenance="contract_v1.pdf",
                    allowed_uses=["assessment", "cv", "cover_letter"],
                ),
                CandidateFact(
                    fact_id=f_proj,
                    parent_id=f_role,
                    kind=EvidenceFactKind.PROJECT,
                    title="Payment Gateway Integration",
                    skills=["Stripe", "PostgreSQL"],
                    provenance="project_note.md",
                    allowed_uses=["assessment", "cv"],
                ),
            ],
        )

        # v2 Snapshot: f_role restricted to cv only, f_v2_new added for assessment only
        snapshot_v2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2.0",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(
                work_authorization_countries=["DE", "AT"],
                remote_eligible=True,
                min_salary=MoneyAmount(amount=Decimal("90000"), currency="EUR"),
            ),
            evidence_records=[
                CandidateFact(
                    fact_id=f_role,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Lead Backend Engineer (Promoted)",
                    organization="Scale Corp",
                    start_date=PrecisionDate(value="2020", precision="year"),
                    end_date=PrecisionDate(value="2022", precision="year"),
                    skills=["Python", "FastAPI", "Leadership"],
                    provenance="contract_v2.pdf",
                    allowed_uses=["cv"],  # Restricted from assessment in v2
                ),
                CandidateFact(
                    fact_id=f_proj,
                    parent_id=f_role,
                    kind=EvidenceFactKind.PROJECT,
                    title="Payment Gateway Integration",
                    skills=["Stripe", "PostgreSQL"],
                    provenance="project_note.md",
                    allowed_uses=["assessment", "cv"],
                ),
                CandidateFact(
                    fact_id=f_v2_new,
                    kind=EvidenceFactKind.SKILL,
                    title="Kubernetes Administrator",
                    skills=["Kubernetes", "CKA"],
                    provenance="cka_cert.pdf",
                    allowed_uses=["assessment"],
                ),
            ],
        )

        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            profile_svc = ProfileService.from_engine(engine)

            # Publish v1 and v2
            engine.profiles.publish_snapshot(
                snapshot=snapshot_v1,
                version_sequence=1,
                predecessor_version=None,
                content_hash="sha256:hash_v1",
                approved_by="candidate",
                approved_at=now,
            )
            engine.profiles.publish_snapshot(
                snapshot=snapshot_v2,
                version_sequence=2,
                predecessor_version="v1.0",
                content_hash="sha256:hash_v2",
                approved_by="candidate",
                approved_at=now,
            )

            context_svc = ContextService()

            # 1. Build assessment context for v1
            req_v1_assess = JsonContextRequest(
                snapshot=snapshot_v1,
                purpose="assessment",
                canonical_job_id=job_id,
                posting_revision=rev_hash,
                job_content=posting,
                model_identifier="llama3:8b-instruct-q4_K_M",
                context_limit=4096,
            )
            bundle_v1, err_v1 = context_svc.build_json_context(req_v1_assess)
            assert bundle_v1 is not None and err_v1 is None
            assert set(bundle_v1.selected_fact_ids) == {f_role, f_proj}
            assert bundle_v1.profile_version == "v1.0"

            # 2. Build assessment context for v2
            req_v2_assess = JsonContextRequest(
                snapshot=snapshot_v2,
                purpose="assessment",
                canonical_job_id=job_id,
                posting_revision=rev_hash,
                job_content=posting,
                model_identifier="llama3:8b-instruct-q4_K_M",
                context_limit=4096,
            )
            bundle_v2, err_v2 = context_svc.build_json_context(req_v2_assess)
            assert bundle_v2 is not None and err_v2 is None
            assert bundle_v2.profile_version == "v2.0"
            # In v2: f_role is restricted from assessment! f_proj and f_v2_new are included
            assert f_role not in bundle_v2.selected_fact_ids
            assert f_proj in bundle_v2.selected_fact_ids
            assert f_v2_new in bundle_v2.selected_fact_ids

            # 3. Build CV context for v2
            req_v2_cv = JsonContextRequest(
                snapshot=snapshot_v2,
                purpose="cv",
                canonical_job_id=job_id,
                posting_revision=rev_hash,
                job_content=posting,
                model_identifier="llama3:8b-instruct-q4_K_M",
                context_limit=4096,
            )
            bundle_v2_cv, err_v2_cv = context_svc.build_json_context(req_v2_cv)
            assert bundle_v2_cv is not None and err_v2_cv is None
            # In CV view: f_role and f_proj have 'cv' allowed; f_v2_new is assessment only
            assert f_role in bundle_v2_cv.selected_fact_ids
            assert f_proj in bundle_v2_cv.selected_fact_ids
            assert f_v2_new not in bundle_v2_cv.selected_fact_ids

            # 4. Historical resolution of v1 citation via ProfileService still resolves correctly
            resolved_v1 = profile_svc.resolve_candidate_reference(("v1.0", f_role))
            assert resolved_v1 is not None
            assert resolved_v1.title == "Backend Software Engineer"
