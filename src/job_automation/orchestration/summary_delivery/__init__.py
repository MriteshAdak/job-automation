"""AUTO-03 per-run summary delivery and notification component."""

from __future__ import annotations

from job_automation.orchestration.summary_delivery.adapter import (
    FakeSalesforceSummaryTargetAdapter,
    SalesforceSummaryTargetAdapter,
    SummaryTargetPort,
)
from job_automation.orchestration.summary_delivery.projection import (
    build_sanitized_headline,
    build_sanitized_summary_text,
    build_summary_projection,
    sanitize_diagnostic_text,
)
from job_automation.orchestration.summary_delivery.records import (
    DeliveryAttemptRecord,
    DeliveryReport,
    DeliveryState,
    NotificationState,
    RunCompletionReceipt,
    RunSummaryProjection,
    SummaryDelivery,
    TargetAcknowledgment,
)
from job_automation.orchestration.summary_delivery.service import SummaryDeliveryService
from job_automation.orchestration.summary_delivery.settings import (
    SummaryDeliverySettings,
    load_summary_delivery_settings,
)

__all__ = [
    "DeliveryAttemptRecord",
    "DeliveryReport",
    "DeliveryState",
    "FakeSalesforceSummaryTargetAdapter",
    "NotificationState",
    "RunCompletionReceipt",
    "RunSummaryProjection",
    "SalesforceSummaryTargetAdapter",
    "SummaryDelivery",
    "SummaryDeliveryService",
    "SummaryDeliverySettings",
    "SummaryTargetPort",
    "TargetAcknowledgment",
    "build_sanitized_headline",
    "build_sanitized_summary_text",
    "build_summary_projection",
    "load_summary_delivery_settings",
    "sanitize_diagnostic_text",
]

