"""Concrete LocalModelProvider implementation of the ModelProvider protocol (LLM-01).

Implements Boundary 6:
- generate(call: ModelCall) -> ModelResult
- embed(texts: list[str], model: str) -> tuple[EmbeddingResponse | None, ClassifiedError | None]

Enforces:
- Shared serialization gate across generation and embeddings.
- Bounded lock acquisition against total deadline.
- Full contract compliance with classified error returns.
"""

from __future__ import annotations

import threading
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from job_automation.configuration import AppConfig
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import EmbeddingResponse, ModelProvider
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.models.audit import AuditManager
from job_automation.models.budget import ContextBudgetManager
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.embeddings import EmbeddingHarness
from job_automation.models.generation import GenerationHarness
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.ports import (
    AuditRecorder,
    Clock,
    DefaultClock,
    DefaultSleeper,
    InputResolver,
    ModelTransport,
    Sleeper,
    Tokenizer,
)
from job_automation.models.schemas import (
    LocalSchemaRegistry,
    build_default_schema_registry,
)
from job_automation.models.transport import LoopbackHttpTransport


class LocalModelProvider(ModelProvider):
    """Production provider for structured local generation and embeddings."""

    def __init__(
        self,
        settings: ModelProviderSettings,
        transport: ModelTransport,
        input_resolver: InputResolver,
        schema_registry: LocalSchemaRegistry | None = None,
        audit_recorder: AuditRecorder | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.input_resolver = input_resolver
        self.schema_registry = (
            schema_registry if schema_registry is not None else build_default_schema_registry()
        )
        self.clock = clock if clock is not None else DefaultClock()
        self.sleeper = sleeper if sleeper is not None else DefaultSleeper()
        self.audit_manager = AuditManager(audit_recorder)
        self.budget_manager = ContextBudgetManager(settings, tokenizer=tokenizer)

        self._gate = threading.Lock()

        self._generation_harness = GenerationHarness(
            settings=self.settings,
            transport=self.transport,
            input_resolver=self.input_resolver,
            schema_registry=self.schema_registry,
            budget_manager=self.budget_manager,
            audit_manager=self.audit_manager,
            clock=self.clock,
            sleeper=self.sleeper,
        )

        self._embedding_harness = EmbeddingHarness(
            settings=self.settings,
            transport=self.transport,
            budget_manager=self.budget_manager,
            audit_manager=self.audit_manager,
            clock=self.clock,
            sleeper=self.sleeper,
        )

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        input_resolver: InputResolver | None = None,
        schema_registry: LocalSchemaRegistry | None = None,
        audit_recorder: AuditRecorder | None = None,
        transport: ModelTransport | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        tokenizer: Tokenizer | None = None,
    ) -> LocalModelProvider:
        """Construct a LocalModelProvider from application configuration."""
        settings = (
            config.model_provider
            if config.model_provider is not None
            else ModelProviderSettings()
        )
        endpoint_url = settings.service_url or config.model_service_url
        effective_transport = (
            transport
            if transport is not None
            else LoopbackHttpTransport(
                base_url=endpoint_url,
                max_response_bytes=settings.max_response_bytes,
            )
        )
        effective_resolver = (
            input_resolver if input_resolver is not None else InMemoryInputResolver()
        )

        return cls(
            settings=settings,
            transport=effective_transport,
            input_resolver=effective_resolver,
            schema_registry=schema_registry,
            audit_recorder=audit_recorder,
            clock=clock,
            sleeper=sleeper,
            tokenizer=tokenizer,
        )

    def generate(self, call: ModelCall) -> ModelResult:
        """Execute structured generation call under serialized inference gate."""
        start_mono = self.clock.monotonic()
        acquired = self._gate.acquire(timeout=self.settings.total_deadline_seconds)
        if not acquired:
            elapsed = (self.clock.monotonic() - start_mono) * 1000.0
            return ModelResult(
                call_id=call.call_id,
                model_identifier=call.model_identifier,
                output_text=None,
                parsed_output=None,
                error=ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_SERVICE,
                    "Timed out waiting for serialized model inference gate",
                    details={"deadline_seconds": self.settings.total_deadline_seconds},
                ),
                latency_ms=elapsed,
            )

        try:
            return self._generation_harness.execute(call)
        finally:
            self._gate.release()

    def embed(
        self,
        texts: list[str],
        model: str,
    ) -> tuple[EmbeddingResponse | None, ClassifiedError | None]:
        """Execute text embeddings under serialized inference gate."""
        start_mono = self.clock.monotonic()
        acquired = self._gate.acquire(timeout=self.settings.total_deadline_seconds)
        if not acquired:
            call_id = uuid.uuid4()
            err = ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                "Timed out waiting for serialized model inference gate",
                details={
                    "call_id": str(call_id),
                    "deadline_seconds": self.settings.total_deadline_seconds,
                },
            )
            return None, err

        try:
            return self._embedding_harness.execute(texts, model)
        finally:
            self._gate.release()
