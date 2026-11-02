"""Local model execution client and harness (LLM-01).

Implements Boundary 6 (ModelProvider):
- Structured generation with strict schema enforcement
- Ordered embeddings with dimension and provenance validation
- Bounded retries, timeouts, and classified error handling
- Zero cloud fallback, zero secret echo, and serialized inference gating
"""

from __future__ import annotations

from job_automation.models.audit import (
    AuditManager,
    AuditRecordError,
    InMemoryAuditRecorder,
)
from job_automation.models.budget import (
    CharacterRatioTokenizer,
    ContextBudgetManager,
    ExactTokenCounter,
)
from job_automation.models.configuration import (
    ModelCapabilities,
    ModelProviderSettings,
    validate_loopback_url,
)
from job_automation.models.diagnostics import (
    redact_url_credentials,
    safe_result_summary,
    sanitize_log_text,
)
from job_automation.models.fingerprints import (
    FINGERPRINT_ALGORITHM,
    FINGERPRINT_VERSION,
    compute_embedding_fingerprint,
    compute_generation_fingerprint,
)
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
from job_automation.models.provider import LocalModelProvider
from job_automation.models.records import (
    AttemptAuditRecord,
    BoundEmbeddingInput,
    BoundGenerationInput,
    LogicalCallAuditRecord,
)
from job_automation.models.schemas import (
    LocalSchemaRegistry,
    RegisteredSchema,
    build_default_schema_registry,
    parse_strict_json,
    validate_against_schema,
)
from job_automation.models.settings import (
    ALLOWED_GENERATION_SETTINGS,
    validate_generation_settings,
)
from job_automation.models.transport import LoopbackHttpTransport

__all__ = [
    "ALLOWED_GENERATION_SETTINGS",
    "AttemptAuditRecord",
    "AuditManager",
    "AuditRecordError",
    "AuditRecorder",
    "BoundEmbeddingInput",
    "BoundGenerationInput",
    "CharacterRatioTokenizer",
    "Clock",
    "ContextBudgetManager",
    "DefaultClock",
    "DefaultSleeper",
    "ExactTokenCounter",
    "FINGERPRINT_ALGORITHM",
    "FINGERPRINT_VERSION",
    "InMemoryAuditRecorder",
    "InMemoryInputResolver",
    "InputResolver",
    "LocalModelProvider",
    "LocalSchemaRegistry",
    "LogicalCallAuditRecord",
    "LoopbackHttpTransport",
    "ModelCapabilities",
    "ModelProviderSettings",
    "ModelTransport",
    "RegisteredSchema",
    "Sleeper",
    "Tokenizer",
    "build_default_schema_registry",
    "compute_embedding_fingerprint",
    "compute_generation_fingerprint",
    "parse_strict_json",
    "redact_url_credentials",
    "safe_result_summary",
    "sanitize_log_text",
    "validate_against_schema",
    "validate_generation_settings",
    "validate_loopback_url",
]

