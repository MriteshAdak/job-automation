"""ContextService facade for CONTEXT-01 full JSON and CONTEXT-04 hybrid RAG context generation."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.index_ports import IndexStorePort
from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.ports import JobBindingPort, PromptRendererPort, TokenCounterPort
from job_automation.context.preparation import ProfileContextPreparer
from job_automation.context.rag_builder import RAGContextBuilder
from job_automation.context.records import JsonContextRequest, PreparedProfileContext
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.profile import ProfileSnapshot


class ContextService:
    """Facade for candidate context preparation, full JSON construction, and hybrid RAG retrieval."""

    def __init__(
        self,
        builder: JsonContextBuilder | None = None,
        preparer: ProfileContextPreparer | None = None,
        rag_builder: RAGContextBuilder | None = None,
        selector: ContextSelectorV2Service | None = None,
        index_store: IndexStorePort | None = None,
        model_provider: ModelProvider | None = None,
        job_binding_validator: JobBindingPort | None = None,
        counter: TokenCounterPort | None = None,
        renderer: PromptRendererPort | None = None,
    ) -> None:
        self.preparer = preparer or ProfileContextPreparer()
        self.builder = builder or JsonContextBuilder(
            preparer=self.preparer,
            counter=counter,
            renderer=renderer,
            job_binding_validator=job_binding_validator,
        )
        self.rag_builder = rag_builder or RAGContextBuilder(
            counter=counter,
            renderer=renderer,
        )
        self.selector = selector or ContextSelectorV2Service(
            preparer=self.preparer,
            json_builder=self.builder,
            rag_builder=self.rag_builder,
            index_store=index_store,
            model_provider=model_provider,
            job_binding_validator=job_binding_validator,
            renderer=renderer,
        )

    def select_context(
        self,
        request: ContextSelectionRequest,
    ) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
        """Execute shared selector dispatching to JSON or RAG according to request.strategy."""
        return self.selector.select_context(request)

    def build_json_context(
        self,
        request: JsonContextRequest,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Construct full JSON ContextBundle or return ClassifiedError (CONTEXT-01)."""
        return self.builder.build(request)

    def prepare_profile_context(
        self,
        snapshot: ProfileSnapshot,
        purpose: str,
        explicit_mandatory_ids: Sequence[uuid.UUID] | None = None,
    ) -> PreparedProfileContext:
        """Prepare shared purpose-aware evidence universe and mandatory context."""
        return self.preparer.prepare_context(
            snapshot=snapshot,
            purpose=purpose,
            explicit_mandatory_ids=explicit_mandatory_ids,
        )
