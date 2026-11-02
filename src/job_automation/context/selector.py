"""Shared ContextSelector implementation dispatching to CONTEXT-01 JSON or CONTEXT-04 RAG."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.binding import DefaultJobBindingValidator
from job_automation.context.errors import (
    ContextConfigurationError,
    ContextError,
    map_context_exception_to_classified_error,
)
from job_automation.context.index_ports import IndexStorePort
from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.ports import JobBindingPort, PromptRendererPort
from job_automation.context.preparation import ProfileContextPreparer
from job_automation.context.rag_builder import RAGContextBuilder
from job_automation.context.rendering import DefaultPromptRenderer
from job_automation.context.selector_ports import ContextSelectorV2Port
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
)
from job_automation.context.selector_validation import (
    validate_context_selection_request,
)
from job_automation.context.serialization import (
    serialize_candidate_model_projection,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import ContextSelector, ContextSelectorV2
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.retrieval_index import IndexReadRequest
from job_automation.contracts.interfaces import ModelProvider


class ContextSelectorV2Service(ContextSelectorV2Port, ContextSelectorV2):
    """Shared context selector implementing ContextSelectorV2 for both JSON and RAG strategies."""

    def __init__(
        self,
        preparer: ProfileContextPreparer | None = None,
        json_builder: JsonContextBuilder | None = None,
        rag_builder: RAGContextBuilder | None = None,
        index_store: IndexStorePort | None = None,
        model_provider: ModelProvider | None = None,
        job_binding_validator: JobBindingPort | None = None,
        renderer: PromptRendererPort | None = None,
    ) -> None:
        self.preparer = preparer or ProfileContextPreparer()
        self.json_builder = json_builder or JsonContextBuilder(preparer=self.preparer)
        self.rag_builder = rag_builder or RAGContextBuilder(renderer=renderer)
        self.index_store = index_store
        self.model_provider = model_provider
        self.job_binding_validator = job_binding_validator or DefaultJobBindingValidator()
        self.renderer = renderer or DefaultPromptRenderer()

    def select_context(
        self,
        request: ContextSelectionRequest,
    ) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
        """Dispatch context construction to JSON builder or RAG retriever according to request.strategy."""
        try:
            # 1. Validate request, snapshot approval, purpose, versions, and job binding
            validate_context_selection_request(
                request=request,
                job_binding_validator=self.job_binding_validator,
            )

            # 2. Shared preparation: prepare permitted fact universe, chronology anchors, and eligibility
            prepared = self.preparer.prepare_context(
                snapshot=request.snapshot,
                purpose=request.purpose,
                explicit_mandatory_ids=request.explicit_mandatory_fact_ids,
            )

            # 3. Strategy dispatch
            if request.strategy == ContextStrategy.JSON:
                # Delegate directly to CONTEXT-01 JsonContextBuilder
                json_req = request.to_json_context_request()
                bundle, err = self.json_builder.build(json_req)
                if err is not None or bundle is None:
                    return None, err

                cand_json = serialize_candidate_model_projection(prepared)
                rendered_prompt = self.renderer.render(json_req, cand_json)

                result = ContextSelectionResult(
                    bundle=bundle,
                    rendered_prompt=rendered_prompt,
                    trace=None,
                    construction_fingerprint=bundle.content_fingerprint or "",
                )
                return result, None

            elif request.strategy == ContextStrategy.RAG:
                # Open index handle via IndexStorePort
                if self.index_store is None:
                    return None, ClassifiedError.from_category(
                        ErrorCategory.MISSING_CONFIGURATION,
                        "IndexStore is not configured on ContextSelector for RAG retrieval",
                        field_path="index_store",
                    )

                read_req = request.index_read_request or IndexReadRequest(
                    candidate_id=request.snapshot.candidate_id,
                    purpose=request.purpose,
                    expected_profile_version=request.snapshot.profile_version,
                )

                handle, open_err = self.index_store.open(read_req)
                if open_err is not None or handle is None:
                    return None, open_err

                try:
                    return self.rag_builder.build_rag_context(
                        request=request,
                        prepared=prepared,
                        index_handle=handle,
                        model_provider=self.model_provider,
                    )
                finally:
                    handle.close()

            else:
                return None, ClassifiedError.from_category(
                    ErrorCategory.UNSUPPORTED_INPUT,
                    f"Unsupported context strategy '{request.strategy}'",
                    field_path="strategy",
                )

        except Exception as exc:
            return None, map_context_exception_to_classified_error(exc)


class LegacyContextSelectorAdapter(ContextSelector):
    """Adapter exposing the legacy 4-argument ContextSelector interface."""

    def __init__(self, selector_v2: ContextSelectorV2Port) -> None:
        self.selector_v2 = selector_v2

    def select_context(
        self,
        requirements: list[str],
        profile: ProfileSnapshot,
        strategy: ContextStrategy,
        token_budget: int,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Legacy adapter method: returns unsupported_input if full context request cannot be constructed."""
        return None, ClassifiedError.from_category(
            ErrorCategory.UNSUPPORTED_INPUT,
            "Legacy select_context interface is deprecated and requires complete ContextSelectionRequest binding via ContextSelectorV2",
            field_path="request",
        )

