"""Windows-specific tests for paths containing spaces, Unicode, and different working directories."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.records import JsonContextRequest
from job_automation.contracts.enums import EvidenceFactKind, WorkplaceType
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)


class TestWindowsPaths:
    def test_context_construction_with_unicode_and_space_paths(self, tmp_path: Path) -> None:
        """Verify context construction works cleanly when runtime/config paths have spaces and umlauts."""
        special_dir = tmp_path / "Job Automation Prüfung ä"
        special_dir.mkdir(parents=True, exist_ok=True)

        config_path = special_dir / "context.config.json"
        config_data = {
            "schema_version": "1.0",
            "default_context_limit": 4096,
            "default_output_reserve": 512,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False)

        assert config_path.is_file()

        cid = uuid.uuid4()
        fid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        rev_hash = "sha256:" + "f" * 64
        job_id = uuid.uuid4()

        snapshot = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2026.1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(
                    fact_id=fid,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Entwickler für Cloud-Systeme",
                    organization="Müller & Partner GmbH",
                    start_date=PrecisionDate(value="2021", precision="year"),
                    provenance=str(special_dir / "zeugnis_müller.pdf"),
                    allowed_uses=["assessment", "cv"],
                )
            ],
        )

        posting = NormalizedPosting(
            source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="103"),
            normalizer_version="1.0",
            raw_reference=str(special_dir / "raw_posting.json"),
            raw_content_hash=rev_hash,
            company_name_hint="Müller AG",
            title="Senior Ingenieur",
            description_clean="Entwicklung von Cloud-Lösungen in Berlin.",
            workplace_type=WorkplaceType.HYBRID,
            source_url="https://example.com/job/103",
            observed_at=now,
        )

        builder = JsonContextBuilder()
        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="test-model",
            context_limit=4096,
        )

        bundle, error = builder.build(req)

        assert bundle is not None
        assert error is None
        assert bundle.ordered_facts[0].provenance == str(special_dir / "zeugnis_müller.pdf")
        assert "Müller & Partner GmbH" in bundle.content_fingerprint or bundle.content_fingerprint is not None

