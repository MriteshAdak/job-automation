"""Scheduling package for native Windows startup and scheduling (AUTO-01)."""

from __future__ import annotations

from job_automation.operations.scheduling.records import (
    BootstrapCategory,
    DispatchReport,
    IdentityResourceManifest,
    LaunchAttemptRecord,
    OccurrenceOutcome,
    ReadinessProbeResult,
    ScheduleDefinition,
    ScheduleKind,
    ScheduleOccurrence,
    SchedulingSettings,
)
from job_automation.operations.scheduling.calendar import CalendarCalculator
from job_automation.operations.scheduling.dispatcher import SchedulingDispatcher
from job_automation.operations.scheduling.launcher import SubprocessLauncher
from job_automation.operations.scheduling.readiness import (
    is_loopback_url,
    probe_model_readiness,
    wait_for_model_readiness,
)
from job_automation.operations.scheduling.service import SchedulingService

__all__ = [
    "BootstrapCategory",
    "CalendarCalculator",
    "DispatchReport",
    "IdentityResourceManifest",
    "LaunchAttemptRecord",
    "OccurrenceOutcome",
    "ReadinessProbeResult",
    "ScheduleDefinition",
    "ScheduleKind",
    "ScheduleOccurrence",
    "SchedulingDispatcher",
    "SchedulingService",
    "SchedulingSettings",
    "SubprocessLauncher",
    "is_loopback_url",
    "probe_model_readiness",
    "wait_for_model_readiness",
]

