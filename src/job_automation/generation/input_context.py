"""Exact context assembly and receipt persistence strictly from frozen inputs (GEN-02-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from job_automation.context.selector import ContextSelectorV2Service
from job_automation.context.chunk_identity import compute_snapshot_fingerprint
from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.retrieval_index import IndexReadRequest
from job_automation.generation.input_binding import FrozenJobBindingValidator
from job_automation.generation.input_indexes import FrozenIndexStoreAdapter
from job_automation.generation.input_records import (
    FrozenContextReceipt,
    FrozenSeal,
    compute_sha256_digest,
)

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class ContextAssembler:
    """Assembles context bundle (JSON or RAG) strictly from sealed snapshots."""

    def __init__(
        self,
        engine: StorageEngine,
        model_provider: ModelProvider | None = None,
    ) -> None:
        self.engine = engine
        self.model_provider = model_provider

    def assemble_context(
        self,
        seal: FrozenSeal,
        context_op_id: str,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Assemble or reopen context bundle strictly from frozen snapshots.

        Guarantees:
        - Never queries current profile facts or current canonical job revisions.
        - Idempotent: repeated calls return the saved receipt byte-for-byte with zero model/selector calls.
        - JSON uses purpose-eligible facts and mandatory context without opening an index.
        - RAG uses the request-owned pinned index handle with frozen reader validation.
        - Persists complete ContextSelectionResult in T3.
        """
        # 1. Check if context receipt already exists for this exact seal and recipe
        existing_receipt = self.engine.generation_inputs.get_context_receipt_by_manifest_and_recipe(
            manifest_hash=seal.manifest.manifest_hash,
            recipe_hash=seal.recipe.recipe_digest,
        )
        if existing_receipt is not None:
            return existing_receipt.result.bundle, None

        # Also check by request_id
        req_receipt = self.engine.generation_inputs.get_context_receipt_by_request_id(seal.request_id)
        if req_receipt is not None and req_receipt.manifest_hash == seal.manifest.manifest_hash:
            return req_receipt.result.bundle, None

        # 2. Build ContextSelectionRequest strictly from frozen seal components
        index_read_req: IndexReadRequest | None = None
        index_store_adapter = None

        if seal.options.context_strategy == ContextStrategy.RAG:
            if seal.pinned_index_generation_id is None or seal.index_pin_id is None:
                return None, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    f"RAG context strategy requested but seal {seal.seal_id} has no pinned index generation",
                    details={"reason_code": "frozen_index_mismatch"},
                )

            index_store_adapter = FrozenIndexStoreAdapter(
                indexes_dir=self.engine.indexes_dir,
                repository=self.engine.context_indexes,
                request_id=seal.request_id,
                expected_candidate_id=seal.candidate_id,
                expected_purpose=seal.options.purpose,
                expected_profile_version=seal.profile_snapshot.profile_version,
                expected_snapshot_fingerprint=compute_snapshot_fingerprint(seal.profile_snapshot.snapshot),
                pinned_generation_id=seal.pinned_index_generation_id,
                pin_id=seal.index_pin_id,
            )

            index_read_req = IndexReadRequest(
                candidate_id=seal.candidate_id,
                purpose=seal.options.purpose,
                authorization_mode="frozen_use",
                frozen_generation_id=seal.pinned_index_generation_id,
            )

        selection_req = ContextSelectionRequest(
            strategy=seal.options.context_strategy,
            snapshot=seal.profile_snapshot.snapshot,
            purpose=seal.options.purpose,
            canonical_job_id=seal.canonical_job_id,
            posting_revision=seal.manifest.posting_revision_hash,
            job_content=seal.job_snapshot.normalized_posting,
            requirements=list(seal.recipe.requirements),
            instruction_text=seal.recipe.instruction_text,
            output_schema_text=seal.recipe.output_schema_text,
            model_identifier=seal.recipe.model_identifier,
            context_limit=seal.recipe.context_limit,
            output_reserve=seal.recipe.output_reserve,
            safety_allowance=seal.recipe.safety_allowance,
            builder_version=seal.recipe.builder_version,
            serialization_version=seal.recipe.serialization_version,
            inclusion_rule_version=seal.recipe.inclusion_rule_version,
            mandatory_policy_version=seal.recipe.mandatory_policy_version,
            explicit_mandatory_fact_ids=list(seal.profile_snapshot.explicit_mandatory_fact_ids),
            template_name=seal.recipe.template_name,
            chat_template_version=seal.recipe.chat_template_version,
            require_exact_measurement=seal.recipe.require_exact_measurement,
            retrieval_settings=seal.recipe.retrieval_settings,
            index_read_request=index_read_req,
            embedding_config=seal.recipe.embedding_config,
        )

        binding_validator = FrozenJobBindingValidator()
        selector = ContextSelectorV2Service(
            job_binding_validator=binding_validator,
            json_builder=JsonContextBuilder(job_binding_validator=binding_validator),
            index_store=index_store_adapter,
            model_provider=self.model_provider,
        )

        # 3. Execute selector
        result, err = selector.select_context(selection_req)
        if err or result is None:
            return None, err

        # 4. Merge preflight warnings into context result
        merged_warnings = sorted(list(set(
            seal.manifest.warnings +
            (result.trace.warnings if result.trace else [])
        )))

        # Also merge into C09 bundle warnings
        bundle = result.bundle.model_copy(update={"warnings": merged_warnings})
        updated_result = result.model_copy(update={"bundle": bundle})

        # 5. Compute result hash
        result_digest_payload = {
            "construction_fingerprint": result.construction_fingerprint,
            "manifest_hash": seal.manifest.manifest_hash,
            "recipe_hash": seal.recipe.recipe_digest,
            "prompt_text": result.rendered_prompt.full_prompt,
        }
        result_hash = compute_sha256_digest(result_digest_payload)

        # 6. Persist FrozenContextReceipt in T3
        now_utc = datetime.now(timezone.utc)
        context_receipt = FrozenContextReceipt(
            request_id=seal.request_id,
            manifest_id=seal.manifest.manifest_id,
            manifest_hash=seal.manifest.manifest_hash,
            recipe_hash=seal.recipe.recipe_digest,
            context_op_id=context_op_id,
            result=updated_result,
            warnings=merged_warnings,
            result_hash=result_hash,
            created_at=now_utc,
        )

        self.engine.generation_inputs.save_context_receipt(context_receipt)

        return bundle, None

