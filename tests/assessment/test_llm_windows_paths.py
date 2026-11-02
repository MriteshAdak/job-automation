"""Native Windows path and handle release verification for LLM assessment (M02-14)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import uuid
from datetime import datetime, timezone

from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentRequest,
)
from job_automation.assessment.llm_service import LLMAssessmentService
from job_automation.assessment.service import AssessmentService
from job_automation.configuration import AppConfig
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.policy import SearchPolicy
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    create_selector_test_posting,
    create_selector_test_snapshot,
)
from tests.fakes.model_transport import ScriptedModelTransport


def test_llm_assessment_windows_paths_spaces_and_umlauts():
    """M02-14: LLM assessment and SQLite persistence in native Windows path with spaces and umlauts."""
    base_temp = Path(os.environ.get("TEMP", "C:/Temp"))
    test_dir = base_temp / f"job_search_prï¿½fung ï¿½ï¿½ï¿½_{uuid.uuid4().hex[:8]}"
    # Using explicit German umlauts: 'Job Suche Prüfung äöü'
    test_dir = base_temp / f"Job Suche Prüfung äöü_{uuid.uuid4().hex[:8]}"
    test_dir.mkdir(parents=True, exist_ok=True)

    try:
        db_path = test_dir / "prüfung_datenbank.sqlite"
        raw_dir = test_dir / "roh daten"
        art_dir = test_dir / "artefäkte"

        storage_engine = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=art_dir)
        storage_engine.initialize_schema()

        cfg = AppConfig(
            data_root=str(test_dir / "daten ordner"),
            model_service_url="http://127.0.0.1:11434",
        )
        transport = ScriptedModelTransport()
        recorder = InMemoryAuditRecorder()
        resolver = InMemoryInputResolver()

        model_provider = LocalModelProvider.from_config(
            config=cfg,
            input_resolver=resolver,
            audit_recorder=recorder,
            transport=transport,
        )

        context_selector = ContextSelectorV2Service(
            index_store=None,
            model_provider=None,
        )

        service = LLMAssessmentService(
            context_selector=context_selector,
            model_provider=model_provider,
            input_resolver=resolver,
        )

        snapshot = create_selector_test_snapshot()
        fact1 = snapshot.evidence_records[0]
        posting = create_selector_test_posting()
        job_id = uuid.uuid4()

        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            company_name=posting.company_name_hint or "Test GmbH",
            current_revision_id=uuid.uuid4(),
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        storage_engine.canonical_jobs.save_canonical_job(canonical_job)

        policy = SearchPolicy(policy_version="pol-1.0")

        rule_evaluator = AssessmentService()
        baseline, trace = rule_evaluator.evaluate_posting_with_trace(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=snapshot,
        )

        model_proposal = {
            "findings": [
                {
                    "requirement_id": "req_0",
                    "status": "match",
                    "reason": "Matches position",
                    "score": 90.0,
                    "candidate_evidence": [
                        {
                            "source_kind": "candidate",
                            "profile_version": snapshot.profile_version,
                            "fact_id": str(fact1.fact_id),
                        }
                    ],
                }
            ],
            "relevance_score": 90.0,
            "score_scale": "0-100",
            "summary_reason": "Matches candidate background",
        }
        transport.queue_response(
            "/api/generate",
            200,
            body={
                "response": json.dumps(model_proposal),
                "done": True,
                "done_reason": "stop",
                "total_duration": 100000000,
                "prompt_eval_count": 100,
                "eval_count": 50,
            },
        )

        request = AssessmentRequest(
            assessment_id=uuid.uuid4(),
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            profile=snapshot,
            policy=policy,
            context_strategy=ContextStrategy.JSON,
            deterministic_baseline=baseline,
            deterministic_trace=trace,
            limits=AssessmentLimits(context_limit=4096),
        )

        result = service.assess(request)
        assert result.status == "success"
        assert result.assessment is not None

        # Save and verify load
        storage_engine.assessments.save_assessment(result.assessment)
        loaded = storage_engine.assessments.get_assessment(result.assessment.assessment_id)
        assert loaded is not None
        assert loaded.assessment_id == result.assessment.assessment_id

        # Crucial Windows check: close connections and verify directory can be deleted
        storage_engine.close()

        shutil.rmtree(test_dir)
        assert not test_dir.exists()

    finally:
        if test_dir.exists():
            try:
                shutil.rmtree(test_dir)
            except Exception:
                pass

