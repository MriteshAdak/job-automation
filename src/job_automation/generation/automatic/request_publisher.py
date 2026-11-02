"""Request publisher and admission adapter for AUTO-02.

Turns reserved intents into executable GenerationRequest (C13) records through GEN-01 admission.
Enforces:
- Scoped uniqueness and idempotent adoption of existing remote/local records.
- Creating durable AutomaticRequestBinding before request can execute.
- Bundle atomicity at reservation, but resilient sibling handling at submission:
  successful sibling requests are retained while failed/uncertain siblings are retried
  under their original keys without duplicating the successful sibling.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.admission import GenerationAdmitter
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftIntent,
    AutomaticDraftPolicy,
    AutomaticRequestBinding,
    SubmissionState,
)
from job_automation.generation.records import GenerationRequestObservation
from job_automation.generation.request_mapping import (
    RequestFieldMapping,
    canonicalize_salesforce_id,
    derive_local_request_id,
)
from job_automation.storage.connection import transaction
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class AutomaticRequestPublisher:
    """Dispatches reserved intents to GEN-01 admission and establishes durable request bindings."""

    def __init__(
        self,
        engine: StorageEngine,
        mapping: RequestFieldMapping | None = None,
    ) -> None:
        self.engine = engine
        self.mapping = mapping or RequestFieldMapping()
        self.admitter = GenerationAdmitter(engine=self.engine, mapping=self.mapping)

    def publish_intent(
        self,
        intent: AutomaticDraftIntent,
        candidate: AutomaticDraftCandidate,
        policy: AutomaticDraftPolicy,
    ) -> tuple[GenerationRequest | None, ClassifiedError | None]:
        """Publish a single intent, admitting it to durable C13 storage and creating its binding."""
        # 1. Update intent to SENDING
        intent.submission_state = SubmissionState.SENDING
        intent.attempt_count += 1
        self.engine.automatic_drafts.save_intent(intent)

        # 2. Build remote observation
        # Generate safe 15/18-character synthetic salesforce ID if none assigned yet
        sf_req_id = intent.salesforce_request_id
        if not sf_req_id:
            sf_req_id = f"a00{intent.intent_id.hex[:12]}"

        canonical_sf_id = canonicalize_salesforce_id(sf_req_id)
        local_uuid = derive_local_request_id(intent.salesforce_org_id, canonical_sf_id)

        # Build raw record matching RequestFieldMapping
        raw_options: dict[str, Any] = {
            self.mapping.job_lookup_field: str(intent.canonical_job_id),
            self.mapping.document_type_field: intent.document_type.value,
            self.mapping.target_language_field: intent.target_language,
            self.mapping.template_id_field: intent.template_id,
            self.mapping.context_strategy_field: intent.context_strategy.value,
            self.mapping.allow_unavailable_field: False,
            self.mapping.client_key_field: intent.client_request_key,
        }

        obs = GenerationRequestObservation(
            org_id=intent.salesforce_org_id,
            salesforce_request_id=sf_req_id,
            canonical_salesforce_id=canonical_sf_id,
            canonical_job_id=intent.canonical_job_id,
            client_request_key=intent.client_request_key,
            local_request_id=local_uuid,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record=raw_options,
        )

        # 3. Admit via GEN-01 admitter
        req, err = self.admitter.admit_observation(obs)
        if err is not None or req is None:
            intent.submission_state = SubmissionState.FAILED
            self.engine.automatic_drafts.save_intent(intent)
            return None, err

        # 4. Atomically persist binding and update intent to ACKNOWLEDGED
        binding = AutomaticRequestBinding(
            local_request_id=req.request_id,
            intent_id=intent.intent_id,
            client_request_key=intent.client_request_key,
            candidate_id=candidate.candidate_id,
            salesforce_org_id=candidate.salesforce_org_id,
            canonical_job_id=candidate.canonical_job_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_content_hash=policy.policy_content_hash or "unhashed",
            expected_assessment_id=candidate.assessment_id,
            expected_assessment_fingerprint=candidate.assessment_input_fingerprint,
            expected_material_fingerprint=intent.material_generation_fingerprint,
            expected_posting_revision_hash=candidate.posting_revision_hash,
            expected_profile_version=candidate.profile_version,
            expected_profile_digest=candidate.profile_digest,
            expected_search_policy_version=candidate.search_policy_version,
            expected_search_policy_hash=candidate.search_policy_hash,
            created_at=datetime.now(timezone.utc),
        )

        with transaction(self.engine.conn):
            self.engine.automatic_drafts.save_binding(binding)
            intent.submission_state = SubmissionState.ACKNOWLEDGED
            intent.local_request_id = req.request_id
            intent.salesforce_request_id = canonical_sf_id
            self.engine.automatic_drafts.save_intent(intent)

        return req, None

    def publish_bundle(
        self,
        intents: list[AutomaticDraftIntent],
        candidate: AutomaticDraftCandidate,
        policy: AutomaticDraftPolicy,
    ) -> list[tuple[AutomaticDraftIntent, GenerationRequest | None, ClassifiedError | None]]:
        """Publish a bundle of reserved intents for a single candidate.

        Retains successful siblings while returning errors for failed siblings.
        """
        results: list[tuple[AutomaticDraftIntent, GenerationRequest | None, ClassifiedError | None]] = []
        for intent in intents:
            req, err = self.publish_intent(intent, candidate, policy)
            results.append((intent, req, err))
        return results

