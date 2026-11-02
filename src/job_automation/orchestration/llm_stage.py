"""LLM stage adapter and service builder for MATCH-02 integration (RUN-01-S09).

Coordinates:
- Construction of LLMAssessmentService using real MATCH-02, CONTEXT-01-04, and LLM-01 services.
- Verification that MATCH-02 components are present and configured.
- Clean delegation of assessment requests through AssessorV2 boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from job_automation.assessment.llm_service import LLMAssessmentService
from job_automation.configuration import AppConfig
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.contracts.interfaces import ContextSelectorV2, ModelProvider
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.orchestration.errors import MissingComponentError

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


def build_llm_assessor(
    engine: StorageEngine,
    config: AppConfig,
    model_provider: ModelProvider | None = None,
    context_selector: ContextSelectorV2 | None = None,
    transport: Any | None = None,
) -> LLMAssessmentService:
    """Build and wire LLMAssessmentService from existing component boundaries.

    Raises MissingComponentError if required dependencies cannot be resolved.
    """
    try:
        resolver = InMemoryInputResolver()
        recorder = InMemoryAuditRecorder()

        if model_provider is None:
            model_provider = LocalModelProvider.from_config(
                config=config,
                input_resolver=resolver,
                audit_recorder=recorder,
                transport=transport,
            )

        if context_selector is None:
            context_selector = ContextSelectorV2Service(
                index_store=None,
                model_provider=model_provider,
            )

        return LLMAssessmentService(
            context_selector=context_selector,
            model_provider=model_provider,
            input_resolver=resolver,
        )
    except Exception as exc:
        raise MissingComponentError(
            f"Failed to initialize MATCH-02 LLMAssessmentService: {exc}",
            details={"error": str(exc)},
        ) from exc
