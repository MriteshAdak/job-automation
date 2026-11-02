"""Tests for error classification and safe diagnostics (CONTEXT-02-S06)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_errors import (
    ChunkBindingError,
    ChunkCapacityError,
    ChunkConfigurationError,
    ChunkPermissionError,
    ChunkUnsupportedError,
    ChunkValidationError,
    map_chunk_exception_to_classified_error,
)
from job_automation.contracts.errors import ErrorCategory


class TestChunkErrors:
    def test_chunk_capacity_error_maps_to_context_budget(self) -> None:
        exc = ChunkCapacityError(
            "Chunk size 500 exceeds max_chunk_chars 400",
            field_path="max_chunk_chars",
            details={"actual_chars": 500, "max_chunk_chars": 400},
        )
        classified = map_chunk_exception_to_classified_error(exc)
        assert classified.category == ErrorCategory.CONTEXT_BUDGET
        assert classified.field_path == "max_chunk_chars"
        assert classified.details["actual_chars"] == 500

    def test_chunk_permission_error_maps_to_permission(self) -> None:
        fid = uuid.uuid4()
        exc = ChunkPermissionError(
            f"Fact '{fid}' is restricted from purpose 'cv'",
            field_path=f"facts[{fid}].allowed_uses",
            details={"fact_id": str(fid), "purpose": "cv"},
        )
        classified = map_chunk_exception_to_classified_error(exc)
        assert classified.category == ErrorCategory.PERMISSION
        assert classified.details["purpose"] == "cv"

    def test_chunk_validation_and_binding_error_maps_to_validation(self) -> None:
        exc_val = ChunkValidationError("Invalid snapshot schema", field_path="schema_version")
        cl_val = map_chunk_exception_to_classified_error(exc_val)
        assert cl_val.category == ErrorCategory.VALIDATION

        exc_bind = ChunkBindingError("Profile version mismatch", field_path="profile_version")
        cl_bind = map_chunk_exception_to_classified_error(exc_bind)
        assert cl_bind.category == ErrorCategory.VALIDATION

    def test_chunk_configuration_error_maps_to_missing_configuration(self) -> None:
        exc = ChunkConfigurationError("Missing settings configuration", field_path="settings")
        classified = map_chunk_exception_to_classified_error(exc)
        assert classified.category == ErrorCategory.MISSING_CONFIGURATION

    def test_chunk_unsupported_error_maps_to_unsupported_input(self) -> None:
        exc = ChunkUnsupportedError("Unsupported granularity", field_path="granularity")
        classified = map_chunk_exception_to_classified_error(exc)
        assert classified.category == ErrorCategory.UNSUPPORTED_INPUT

    def test_safe_diagnostics_omits_sensitive_claims_and_raw_secrets(self) -> None:
        secret_claim = "SUPER_SECRET_PATENT_CLAIM_VALUE"
        exc = ChunkValidationError(
            "Invalid fact schema",
            field_path="claims[0]",
            details={"fact_id": str(uuid.uuid4())},
        )
        classified = map_chunk_exception_to_classified_error(exc)
        assert secret_claim not in classified.message
        assert secret_claim not in str(classified.details)

