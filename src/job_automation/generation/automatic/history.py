"""Deduplication and repeat-generation history management for AUTO-02.

Enforces:
- Unchanged material inputs across runs/days reuse existing intents without new requests.
- Same client key with conflicting payload blocks admission.
- Reverting to an older historical input version finds and reuses the earlier intent.
- RepeatMode.FIRST_ONLY suppresses drafting when any prior intent exists for the job/type.
- RepeatMode.ON_MATERIAL_CHANGE permits drafting only for allowed change classes after cooldown.
- Overlap with existing equivalent manual requests suppresses automatic duplication.
- Ambiguous pending manual requests hold for review.
- Deliberate manual regenerations retain independent identity and are never suppressed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from job_automation.contracts.enums import DocumentType, GenerationProcessing
from job_automation.generation.automatic.fingerprints import (
    compute_material_generation_fingerprint,
    compute_payload_digest,
    derive_automatic_client_request_key,
)
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
    RepeatMode,
)
from job_automation.storage.engine import StorageEngine


class DeduplicationResult:
    """Outcome of deduplication evaluation for a candidate and document variant."""

    def __init__(
        self,
        outcome: AutomaticDraftOutcome,
        reason_codes: list[str],
        summary_reason: str,
        client_request_key: str | None = None,
        material_fingerprint: str | None = None,
        existing_intent_key: str | None = None,
        existing_request_id: uuid.UUID | None = None,
        payload_digest: str | None = None,
        payload_json: str | None = None,
    ) -> None:
        self.outcome = outcome
        self.reason_codes = reason_codes
        self.summary_reason = summary_reason
        self.client_request_key = client_request_key
        self.material_fingerprint = material_fingerprint
        self.existing_intent_key = existing_intent_key
        self.existing_request_id = existing_request_id
        self.payload_digest = payload_digest
        self.payload_json = payload_json

    @property
    def is_new_admission(self) -> bool:
        return self.outcome == AutomaticDraftOutcome.ADMITTED


class DeduplicationManager:
    """Evaluates cross-run identity, repeat policies, and manual request overlap."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def check_variant_deduplication(
        self,
        candidate: AutomaticDraftCandidate,
        variant: DocumentVariantConfig,
        policy: AutomaticDraftPolicy,
        now: datetime | None = None,
    ) -> DeduplicationResult:
        """Check deduplication and repeat policy for a specific document variant."""
        now_utc = now or datetime.now(timezone.utc)
        mat_fingerprint = compute_material_generation_fingerprint(candidate, variant)
        client_key = derive_automatic_client_request_key(
            material_fingerprint=mat_fingerprint,
            org_id=candidate.salesforce_org_id,
            candidate_id=candidate.candidate_id,
            canonical_job_id=candidate.canonical_job_id,
            document_type=variant.document_type.value,
        )

        payload_dict: dict[str, Any] = {
            "canonical_job_id": str(candidate.canonical_job_id),
            "document_type": variant.document_type.value,
            "target_language": variant.target_language,
            "template_id": variant.template_id,
            "context_strategy": variant.context_strategy.value,
            "formats": sorted(variant.formats),
            "allow_unavailable_job": False,
            "client_request_key": client_key,
        }
        import json
        payload_json = json.dumps(payload_dict, sort_keys=True)
        payload_digest = compute_payload_digest(payload_dict)

        # Load prior intents for this job/type
        all_job_intents = self.engine.automatic_drafts.list_intents_for_job(candidate.canonical_job_id)
        matching_type_intents = [
            i for i in all_job_intents if i.document_type == variant.document_type
        ]

        # 1. Check exact client_request_key in intents
        existing_intent = self.engine.automatic_drafts.get_intent_by_key(client_key)
        if existing_intent is not None:
            if existing_intent.request_payload_digest != payload_digest:
                return DeduplicationResult(
                    outcome=AutomaticDraftOutcome.BLOCKED,
                    reason_codes=["client_key_payload_conflict"],
                    summary_reason=f"Client key '{client_key}' already exists with different payload digest.",
                    client_request_key=client_key,
                    existing_intent_key=existing_intent.client_request_key,
                    existing_request_id=existing_intent.local_request_id,
                )
            # Reused: exact same inputs already drafted (or reverted)
            has_different_history = any(i.material_generation_fingerprint != mat_fingerprint for i in matching_type_intents)
            reason_codes = ["historical_input_reversion_reused"] if has_different_history else ["already_drafted_identical_inputs"]
            return DeduplicationResult(
                outcome=AutomaticDraftOutcome.REUSED,
                reason_codes=reason_codes,
                summary_reason="Inputs reverted to an earlier historical version that was already drafted." if has_different_history else "Identical material generation inputs were already drafted.",
                client_request_key=client_key,
                material_fingerprint=mat_fingerprint,
                existing_intent_key=existing_intent.client_request_key,
                existing_request_id=existing_intent.local_request_id,
                payload_digest=payload_digest,
                payload_json=payload_json,
            )

        # 2. Check historical fingerprint lookup across all past intents for this job/type
        # Check if identical material fingerprint exists under any past key (e.g. input reversion)
        reverted_intent = next(
            (i for i in matching_type_intents if i.material_generation_fingerprint == mat_fingerprint),
            None,
        )
        if reverted_intent is not None:
            return DeduplicationResult(
                outcome=AutomaticDraftOutcome.REUSED,
                reason_codes=["historical_input_reversion_reused"],
                summary_reason="Inputs reverted to an earlier historical version that was already drafted.",
                client_request_key=client_key,
                material_fingerprint=mat_fingerprint,
                existing_intent_key=reverted_intent.client_request_key,
                existing_request_id=reverted_intent.local_request_id,
                payload_digest=payload_digest,
                payload_json=payload_json,
            )

        # 3. Check Repeat Policy if prior intents exist for this job/type
        if matching_type_intents:
            if policy.repeat_policy.mode == RepeatMode.FIRST_ONLY:
                return DeduplicationResult(
                    outcome=AutomaticDraftOutcome.SUPPRESSED,
                    reason_codes=["first_only_already_drafted"],
                    summary_reason="Repeat policy is first_only and this job was previously drafted.",
                    client_request_key=client_key,
                    existing_intent_key=matching_type_intents[-1].client_request_key,
                )

            if policy.repeat_policy.mode == RepeatMode.ON_MATERIAL_CHANGE:
                latest_intent = matching_type_intents[-1]
                cooldown_delta = timedelta(hours=policy.repeat_policy.cooldown_hours)
                if now_utc - latest_intent.created_at < cooldown_delta:
                    return DeduplicationResult(
                        outcome=AutomaticDraftOutcome.SUPPRESSED,
                        reason_codes=["repeat_cooldown_active"],
                        summary_reason=f"Repeat cooldown active; {now_utc - latest_intent.created_at} elapsed vs {cooldown_delta} required.",
                        client_request_key=client_key,
                        existing_intent_key=latest_intent.client_request_key,
                    )
                # Check max_requests_per_job limit
                job_requests_count = len(matching_type_intents)
                if job_requests_count >= policy.volume_limits.max_requests_per_job:
                    return DeduplicationResult(
                        outcome=AutomaticDraftOutcome.SUPPRESSED,
                        reason_codes=["job_repeat_limit_exceeded"],
                        summary_reason=f"Per-job draft limit ({policy.volume_limits.max_requests_per_job}) reached for this job.",
                        client_request_key=client_key,
                        existing_intent_key=latest_intent.client_request_key,
                    )

        # 4. Check existing manual requests for equivalence / overlap
        manual_requests = self.engine.generation_requests.list_by_job(candidate.canonical_job_id)
        for req in manual_requests:
            if req.document_type == variant.document_type:
                # If manual request was claimed and frozen, check frozen input versions
                if req.frozen_input_versions is not None:
                    if (
                        req.frozen_input_versions.posting_revision == candidate.posting_revision_hash
                        and req.frozen_input_versions.profile_version == candidate.profile_version
                    ):
                        return DeduplicationResult(
                            outcome=AutomaticDraftOutcome.SUPPRESSED,
                            reason_codes=["matching_manual_request_exists"],
                            summary_reason=f"Equivalent manual generation request {req.request_id} already exists.",
                            existing_request_id=req.request_id,
                        )
                elif req.state in (GenerationProcessing.PENDING, GenerationProcessing.RUNNING):
                    # Unsealed pending manual request: cannot verify equivalence yet -> hold for review
                    return DeduplicationResult(
                        outcome=AutomaticDraftOutcome.REVIEW_REQUIRED,
                        reason_codes=["ambiguous_pending_manual_request"],
                        summary_reason=f"Pending manual request {req.request_id} exists on this job; holding automatic drafting until resolved.",
                        existing_request_id=req.request_id,
                    )

        # Passed deduplication -> clean new admission
        return DeduplicationResult(
            outcome=AutomaticDraftOutcome.ADMITTED,
            reason_codes=["deduplication_cleared"],
            summary_reason="No duplicate or conflicting intent found; eligible for quota check.",
            client_request_key=client_key,
            material_fingerprint=mat_fingerprint,
            payload_digest=payload_digest,
            payload_json=payload_json,
        )
