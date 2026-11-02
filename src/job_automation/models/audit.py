"""Audit record collection and dispatch (LLM-01-S07).

Assembles immutable logical call audit records with individual attempt metadata.
Guarantees that sensitive prompt bodies, raw generated text, and credentials
are excluded from ordinary audit logs.
"""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.models import TokenUsage
from job_automation.contracts.primitives import UtcDatetime
from job_automation.models.ports import AuditRecorder, Clock
from job_automation.models.records import (
    AttemptAuditRecord,
    LogicalCallAuditRecord,
)


class AuditRecordError(RuntimeError):
    """Raised when an injected audit recorder fails to persist or process a call record."""
    pass


class InMemoryAuditRecorder:
    """Thread-safe in-memory audit recorder for testing and inspection."""

    def __init__(self) -> None:
        self.records: list[LogicalCallAuditRecord] = []
        self._by_id: dict[uuid.UUID, LogicalCallAuditRecord] = {}

    def record_call(self, record: LogicalCallAuditRecord) -> None:
        self.records.append(record)
        self._by_id[record.call_id] = record

    def get_by_id(self, call_id: uuid.UUID) -> LogicalCallAuditRecord | None:
        return self._by_id.get(call_id)


class AuditManager:
    """Manages collection of attempt events and creation of logical call records."""

    def __init__(self, recorder: AuditRecorder | None = None) -> None:
        self.recorder = recorder

    def record(self, record: LogicalCallAuditRecord) -> None:
        """Deliver record to configured recorder if present."""
        if self.recorder is not None:
            try:
                self.recorder.record_call(record)
            except Exception as exc:
                raise AuditRecordError(f"Failed to record call audit event: {exc}") from exc

