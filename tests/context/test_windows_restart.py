"""Tests verifying context construction reproducibility across simulated process restarts and database reopenings."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.records import JsonContextRequest
from job_automation.contracts.enums import EvidenceFactKind, WorkplaceType
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.storage.engine import StorageEngine


class TestWindowsRestart:
    def test_reproducible_construction_across_storage_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "restart_test.db"
        cid = uuid.uuid4()
        fid1 = uuid.uuid4()
        fid2 = uuid.uuid4()
        now = datetime.now(timezone.utc)
        rev_hash = "sha256:" + "7" * 64
        job_id = uuid.uuid4()

        snapshot = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1.0",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(
                work_authorization_countries=["DE"],
                remote_eligible=True,
                min_salary=MoneyAmount(amount=Decimal("80000"), currency="EUR"),
            ),
            evidence_records=[
                CandidateFact(
                    fact_id=fid1,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Software Engineer",
                    start_date=PrecisionDate(value="2020", precision="year"),
                    end_date=PrecisionDate(value="2022", precision="year"),
                    provenance="contract_1",
                    allowed_uses=["assessment", "cv"],
                ),
                CandidateFact(
                    fact_id=fid2,
                    kind=EvidenceFactKind.EDUCATION,
                    title="B.Sc. Informatics",
                    start_date=PrecisionDate(value="2016", precision="year"),
                    end_date=PrecisionDate(value="2019", precision="year"),
                    provenance="cert_1",
                    allowed_uses=["assessment", "cv"],
                ),
            ],
        )

        posting = NormalizedPosting(
            source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="200"),
            normalizer_version="1.0",
            raw_reference="ref_200",
            raw_content_hash=rev_hash,
            company_name_hint="FinTech Inc",
            title="Senior Developer",
            description_clean="Job description text here.",
            workplace_type=WorkplaceType.REMOTE,
            source_url="https://example.com/job/200",
            observed_at=now,
        )

        # Session 1: Migrate and store snapshot
        with StorageEngine(db_path=db_path) as engine1:
            engine1.migrate()
            engine1.profiles.publish_snapshot(
                snapshot=snapshot,
                version_sequence=1,
                predecessor_version=None,
                content_hash="sha256:dummy",
                approved_by="candidate",
                approved_at=now,
            )

        # Session 2: Reopen storage engine in a new context (simulated restart)
        with StorageEngine(db_path=db_path) as engine2:
            reloaded_snapshot = engine2.profiles.get_snapshot("v1.0")
            assert reloaded_snapshot is not None

            builder = JsonContextBuilder()
            req = JsonContextRequest(
                snapshot=reloaded_snapshot,
                purpose="assessment",
                canonical_job_id=job_id,
                posting_revision=rev_hash,
                job_content=posting,
                model_identifier="llama3:8b-instruct-q4_K_M",
                context_limit=4096,
            )

            bundle1, err1 = builder.build(req)
            bundle2, err2 = builder.build(req)

            assert bundle1 is not None and err1 is None
            assert bundle2 is not None and err2 is None
            assert bundle1.content_fingerprint == bundle2.content_fingerprint
            assert bundle1.selected_fact_ids == [fid1, fid2]
            assert bundle1.budget_report.fits is True
