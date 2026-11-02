"""Tests for option validation, strict boolean override, and options digest calculation."""

from __future__ import annotations

import uuid

import pytest

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.input_availability import AvailabilityRechecker
from job_automation.generation.input_records import FrozenGenerationOptions
from job_automation.generation.request_mapping import compute_options_digest
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import create_job_with_posting, make_request


class TestOptionsValidation:
    def test_strict_boolean_override_behavior(self, engine: StorageEngine) -> None:
        """Verify that strings ('true', 'false'), ints, and null never grant override."""
        job, _, _ = create_job_with_posting(engine)
        rechecker = AvailabilityRechecker(engine=engine)

        # 1. Exact boolean True grants override
        check_true, _ = rechecker.recheck_availability(job.canonical_job_id, allow_unavailable_job=True)
        assert check_true is not None
        assert check_true.allow_unavailable_job is True

        # 2. String "true" does NOT grant override
        check_str_true, _ = rechecker.recheck_availability(job.canonical_job_id, allow_unavailable_job="true")
        assert check_str_true is not None
        assert check_str_true.allow_unavailable_job is False

        # 3. String "false" does NOT grant override
        check_str_false, _ = rechecker.recheck_availability(job.canonical_job_id, allow_unavailable_job="false")
        assert check_str_false is not None
        assert check_str_false.allow_unavailable_job is False

        # 4. Integer 1 does NOT grant override
        check_int, _ = rechecker.recheck_availability(job.canonical_job_id, allow_unavailable_job=1)
        assert check_int is not None
        assert check_int.allow_unavailable_job is False

        # 5. None does NOT grant override
        check_none, _ = rechecker.recheck_availability(job.canonical_job_id, allow_unavailable_job=None)
        assert check_none is not None
        assert check_none.allow_unavailable_job is False

    def test_options_digest_stability_and_invariance(self) -> None:
        job_id = uuid.uuid4()
        base = {
            "canonical_job_id": str(job_id),
            "document_type": "cv",
            "target_language": "de",
            "template_id": "tmpl-1",
            "context_strategy": "json",
            "allow_unavailable_job": False,
        }
        digest1 = compute_options_digest(base)

        # Shuffled keys must yield identical digest
        shuffled = {
            "allow_unavailable_job": False,
            "target_language": "de",
            "document_type": "cv",
            "template_id": "tmpl-1",
            "canonical_job_id": str(job_id),
            "context_strategy": "json",
        }
        digest2 = compute_options_digest(shuffled)
        assert digest1 == digest2

        # Altering allow_unavailable_job changes digest
        modified = dict(base)
        modified["allow_unavailable_job"] = True
        digest3 = compute_options_digest(modified)
        assert digest1 != digest3

