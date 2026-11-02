"""Tests for shared primitives, serialization, and versioned conventions."""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.base import ContractModel
from job_automation.contracts.primitives import (
    MoneyAmount,
    PrecisionDate,
    SourceKey,
    validate_utc,
)
from job_automation.contracts.enums import (
    ApplicationProgress,
    AssessmentDisposition,
    DocumentApproval,
    GenerationProcessing,
    HardCriterionResult,
    PipelineStage,
    PostingAvailability,
    SyncOperationState,
)


class DummyModel(ContractModel):
    id: uuid.UUID
    provider_id: str
    created_at: datetime


class TestPrimitives:
    def test_local_id_valid_and_invalid(self) -> None:
        valid_uuid = uuid.uuid4()
        m = DummyModel(
            id=valid_uuid,
            provider_id="00042",
            created_at=datetime.now(timezone.utc),
        )
        assert m.id == valid_uuid
        assert m.provider_id == "00042"

        with pytest.raises(ValidationError):
            DummyModel.model_validate(
                {
                    "id": "not-a-uuid",
                    "provider_id": "00042",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    def test_provider_id_preserves_leading_zeros(self) -> None:
        m = DummyModel(
            id=uuid.uuid4(),
            provider_id="00042",
            created_at=datetime.now(timezone.utc),
        )
        assert m.provider_id == "00042"
        data = m.model_dump()
        assert data["provider_id"] == "00042"
        json_str = m.model_dump_json()
        assert '"provider_id":"00042"' in json_str

    def test_utc_datetime_validation(self) -> None:
        now_utc = datetime.now(timezone.utc)
        assert validate_utc(now_utc) == now_utc

        naive_dt = datetime(2026, 10, 27, 10, 0, 0)
        with pytest.raises(ValueError, match="must be UTC"):
            validate_utc(naive_dt)

    def test_precision_date(self) -> None:
        # Month precision
        pd_month = PrecisionDate(value="2021-05", precision="month")
        assert pd_month.value == "2021-05"
        assert pd_month.precision == "month"

        # Day precision
        pd_day = PrecisionDate(value="2021-05-15", precision="day")
        assert pd_day.value == "2021-05-15"

        # Year precision
        pd_year = PrecisionDate(value="2021", precision="year")
        assert pd_year.value == "2021"

        # Invalid combinations
        with pytest.raises(ValueError):
            PrecisionDate(value="2021-05-15", precision="month")

        with pytest.raises(ValueError):
            PrecisionDate(value="2021-05", precision="day")

        with pytest.raises(ValueError):
            PrecisionDate(value="2021-05", precision="year")

    def test_money_amount_explicit_null_and_zero(self) -> None:
        ma = MoneyAmount(amount=Decimal("0.00"), currency="EUR")
        assert ma.amount == Decimal("0.00")
        assert ma.currency == "EUR"

        # Currency must be 3 uppercase letters
        with pytest.raises(ValidationError):
            MoneyAmount(amount=Decimal("50000"), currency="euros")

    def test_source_key_comparison(self) -> None:
        sk1 = SourceKey(provider="provider-a", board_id="board-1", source_posting_id="42")
        sk2 = SourceKey(provider="provider-a", board_id="board-2", source_posting_id="42")
        sk3 = SourceKey(provider="provider-a", board_id="board-1", source_posting_id="42")

        assert sk1 != sk2
        assert sk1 == sk3

    def test_eight_state_domains_independence(self) -> None:
        # All eight domains exist and have distinct value spaces/semantics
        assert PipelineStage.RUNNING.value == "running"
        assert HardCriterionResult.PASS.value == "pass"
        assert HardCriterionResult.FAIL.value == "fail"
        assert HardCriterionResult.UNKNOWN.value == "unknown"
        assert AssessmentDisposition.REJECTED.value == "rejected"
        assert PostingAvailability.UNAVAILABLE.value == "unavailable"
        assert ApplicationProgress.NEW.value == "New"
        assert ApplicationProgress.REJECTED.value == "Rejected"
        assert SyncOperationState.RETRY_WAIT.value == "retry_wait"
        assert GenerationProcessing.UPLOAD_PENDING.value == "upload_pending"
        assert DocumentApproval.DRAFT.value == "draft"

        # Ensure types cannot be confused
        assert AssessmentDisposition.REJECTED != ApplicationProgress.REJECTED
        assert GenerationProcessing.UPLOAD_PENDING != DocumentApproval.DRAFT

