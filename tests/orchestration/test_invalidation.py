"""Tests for input-version invalidation and cache reuse decisions (RUN-01-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.enums import AssessmentDisposition, AssessmentMethod, PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.primitives import SourceKey
from job_automation.orchestration.fingerprints import compute_assessment_composite_fingerprint
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.records import AssessmentSelection
from job_automation.storage.engine import StorageEngine


class TestInvalidation:
    def test_invalidation_matrix(self, tmp_path: Path) -> None:
        db_path = tmp_path / "inval.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        evaluator = InvalidationEvaluator(engine)
        can_id = uuid.uuid4()
        cand_id = uuid.uuid4()
        asmt_id = uuid.uuid4()

        # 1. Initially no selection exists -> requires assessment
        req1, fp1, sel1, a1 = evaluator.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="rev_hash_1",
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_fp_1",
            assessment_mode="rules",
        )
        assert req1 is True
        assert sel1 is None

        # Persist assessment and selection
        now = datetime.now(timezone.utc)
        rev_id = uuid.uuid4()
        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Tech Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
            revisions=[
                PostingRevision(
                    revision_id=rev_id,
                    canonical_job_id=can_id,
                    source_key=SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="1"),
                    content_hash=f"sha256:{'1'*64}",
                    title="Senior Python Developer",
                    first_seen_at=now,
                    last_seen_at=now,
                )
            ],
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        asmt = Assessment(
            assessment_id=asmt_id,
            canonical_job_id=can_id,
            posting_revision="rev_hash_1",
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="All rules passed",
            rule_outcomes=[],
        )
        engine.assessments.save_assessment(asmt)

        selection = AssessmentSelection(
            canonical_job_id=can_id,
            candidate_id=cand_id,
            purpose="assessment",
            input_fingerprint=fp1,
            assessment_id=asmt_id,
            evaluated_at=now,
            generation_token="gen_1",
            is_selected_final=True,
            disposition=AssessmentDisposition.ELIGIBLE,
        )
        engine.pipeline_work.save_assessment_selection(selection)

        # 2. Check identical inputs -> requires_reassessment is FALSE!
        req2, fp2, sel2, a2 = evaluator.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="rev_hash_1",
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_fp_1",
            assessment_mode="rules",
        )
        assert req2 is False
        assert fp2 == fp1
        assert sel2 is not None
        assert a2 is not None
        assert a2.assessment_id == asmt_id

        # 3. Change posting revision hash -> invalidated!
        req3, fp3, sel3, a3 = evaluator.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="rev_hash_2",  # Changed!
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_fp_1",
            assessment_mode="rules",
        )
        assert req3 is True
        assert fp3 != fp1

        # 4. Change profile snapshot hash -> invalidated!
        req4, fp4, sel4, a4 = evaluator.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="rev_hash_1",
            profile_snapshot_hash="prof_hash_2",  # Changed!
            policy_fingerprint="pol_fp_1",
            assessment_mode="rules",
        )
        assert req4 is True

        # 5. Change policy fingerprint -> invalidated!
        req5, fp5, sel5, a5 = evaluator.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="rev_hash_1",
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_fp_2",  # Changed!
            assessment_mode="rules",
        )
        assert req5 is True

        # 6. Change mode to LLM -> invalidated!
        req6, fp6, sel6, a6 = evaluator.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="rev_hash_1",
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_fp_1",
            assessment_mode="llm",  # Changed!
            strategy="json",
        )
        assert req6 is True

        engine.close()
