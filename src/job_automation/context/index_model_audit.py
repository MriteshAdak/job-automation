"""Audit recording and diagnostics for index embedding calls."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


class IndexAuditSink:
    """Collects embedding call execution records without private text."""

    def __init__(self) -> None:
        self.call_records: list[dict[str, Any]] = []

    def record_call(
        self,
        call_id: uuid.UUID,
        model_identifier: str,
        dimension: int,
        item_count: int,
        duration_ms: float,
        model_digest: str | None = None,
        token_usage: Any = None,
    ) -> None:
        self.call_records.append(
            {
                "call_id": str(call_id),
                "model_identifier": model_identifier,
                "model_digest": model_digest,
                "dimension": dimension,
                "item_count": item_count,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
