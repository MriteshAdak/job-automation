"""Document generation request worker package (GEN-01)."""

from job_automation.generation.admission import GenerationAdmitter
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.errors import (
    DependencyBlockedError,
    FreezeConflictError,
    GenerationError,
    InvalidRequestStateError,
    MissingComponentError,
    OptionMismatchError,
    PreflightFailureError,
    ProjectionUncertainError,
    StaleWorkerError,
)
from job_automation.generation.ports import (
    ArtifactDeliverer,
    DocumentRenderer,
    DraftValidator,
    GenerationInputService,
    GenerationRequestSource,
    RequestStateProjector,
)
from job_automation.generation.polling import SalesforceGenerationRequestSource
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import (
    ArtifactDeliveryRecord,
    FreezeManifest,
    GenerationRequestObservation,
    GenerationStage,
    GenerationWorkerReport,
    ObservationIssueCategory,
    ProjectionIntent,
    ProjectionStatus,
    RemoteRequestState,
    StageAttempt,
    StageCheckpoint,
    StageStatus,
    ValidationReport,
)
from job_automation.generation.recovery import GenerationRecoveryManager
from job_automation.generation.request_mapping import (
    RequestFieldMapping,
    canonicalize_salesforce_id,
    compute_options_digest,
    derive_local_request_id,
)
from job_automation.generation.settings import GenerationSettings, load_generation_settings
from job_automation.generation.worker import GenerationWorker
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.generation.input_ports import StandaloneGenerationInputService
from job_automation.generation.input_records import (
    AvailabilityCheck,
    FrozenContextReceipt,
    FrozenContextRecipe,
    FrozenGenerationOptions,
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
    FrozenSeal,
    GenerationInputSettings,
    PreflightReceipt,
)
from job_automation.generation.input_binding import FrozenJobBindingValidator
from job_automation.generation.input_availability import AvailabilityRechecker

from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliverySetReceipt,
    RemoteArtifactMapping,
    ReviewProjection,
    ReadinessTransitionRecord,
    build_reconciliation_marker,
    parse_reconciliation_marker,
)
from job_automation.generation.delivery_ports import (
    ArtifactDeliveryServicePort,
    SalesforceFilesGatewayPort,
)
from job_automation.generation.delivery_settings import DeliverySettings
from job_automation.generation.delivery_service import DeliveryService
from job_automation.generation.delivery_adapter import ArtifactDeliveryAdapter

__all__ = [
    "AccessibilityReceipt",
    "ArtifactDeliverer",
    "ArtifactDeliveryAdapter",
    "ArtifactDeliveryRecord",
    "ArtifactDeliveryServicePort",
    "AvailabilityCheck",
    "AvailabilityRechecker",
    "DefaultGenerationInputService",
    "DeliveryAttempt",
    "DeliveryIntent",
    "DeliveryService",
    "DeliverySetReceipt",
    "DeliverySettings",
    "DependencyBlockedError",
    "DocumentRenderer",
    "DraftValidator",
    "FreezeConflictError",
    "FreezeManifest",
    "FrozenContextReceipt",
    "FrozenContextRecipe",
    "FrozenGenerationOptions",
    "FrozenJobBindingValidator",
    "FrozenJobSnapshot",
    "FrozenProfileSnapshot",
    "FrozenSeal",
    "GenerationAdmitter",
    "GenerationCoordinator",
    "GenerationError",
    "GenerationInputService",
    "GenerationInputSettings",
    "GenerationRecoveryManager",
    "GenerationRequestObservation",
    "GenerationRequestSource",
    "GenerationSettings",
    "GenerationStage",
    "GenerationWorker",
    "GenerationWorkerReport",
    "InvalidRequestStateError",
    "MissingComponentError",
    "ObservationIssueCategory",
    "OptionMismatchError",
    "PreflightFailureError",
    "PreflightReceipt",
    "ProjectionIntent",
    "ProjectionStatus",
    "ProjectionUncertainError",
    "ReadinessTransitionRecord",
    "RemoteArtifactMapping",
    "RemoteRequestState",
    "RequestFieldMapping",
    "RequestStateProjector",
    "ReviewProjection",
    "SalesforceFilesGatewayPort",
    "SalesforceGenerationRequestSource",
    "SalesforceRequestStateProjector",
    "StageAttempt",
    "StageCheckpoint",
    "StageStatus",
    "StaleWorkerError",
    "StandaloneGenerationInputService",
    "ValidationReport",
    "build_reconciliation_marker",
    "canonicalize_salesforce_id",
    "compute_options_digest",
    "derive_local_request_id",
    "load_generation_settings",
    "parse_reconciliation_marker",
]

