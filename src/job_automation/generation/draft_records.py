"""GEN-03 durable result and attempt contracts."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.contracts.primitives import UtcDatetime


class DraftGenerationReceipt(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    receipt_id: uuid.UUID
    request_id: uuid.UUID
    logical_key: str
    binding_hash: str
    recipe_hash: str
    seal_id: str
    context_receipt_id: uuid.UUID
    started_at: UtcDatetime
    completed_at: UtcDatetime
    call: ModelCall | None = None
    model_result: ModelResult | None = None
    draft: DraftDocumentV2 | None = None
    content_hash: str | None = None
    error: ClassifiedError | None = None
    selected_fact_ids: list[uuid.UUID] = Field(default_factory=list)
    cited_fact_ids: list[uuid.UUID] = Field(default_factory=list)
    validation_status: Literal["pending_gen04"] = "pending_gen04"

    @model_validator(mode="after")
    def exclusive(self):
        if (self.draft is None) == (self.error is None):
            raise ValueError("Exactly one draft or classified failure required")
        if (self.draft is None) != (self.content_hash is None):
            raise ValueError("Content hash must accompany a draft")
        return self


class DraftGenerationResult(ContractModel):
    receipt: DraftGenerationReceipt | None = None
    error: ClassifiedError | None = None

    @model_validator(mode="after")
    def exclusive(self):
        if (self.receipt is None) == (self.error is None):
            raise ValueError("Exactly one receipt or boundary failure required")
        return self

    @property
    def draft(self):
        return self.receipt.draft if self.receipt else None

    @property
    def failure(self):
        return self.error or (self.receipt.error if self.receipt else None)
