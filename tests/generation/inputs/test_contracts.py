"""Tests for GEN-02 companion contracts, canonical hashing, and serialization invariants."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    PostingAvailability,
)
from job_automation.contracts.primitives import SourceKey
from job_automation.generation.input_records import (
    AvailabilityCheck,
    FrozenGenerationOptions,
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
    FrozenSeal,
    PreflightReceipt,
    canonical_json_dumps,
    compute_manifest_hash,
    compute_sha256_digest,
)
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_posting,
    publish_approved_profile,
)


class TestCompanionContracts:
    def test_canonical_json_deterministic_ordering(self) -> None:
        dict_a = {"b": 2, "a": 1, "nested": {"z": 9, "m": 5}}
        dict_b = {"nested": {"m": 5, "z": 9}, "a": 1, "b": 2}
        assert canonical_json_dumps(dict_a) == canonical_json_dumps(dict_b)
        assert compute_sha256_digest(dict_a) == compute_sha256_digest(dict_b)

    def test_manifest_hash_excludes_manifest_hash_itself(self) -> None:
        base = {
            "manifest_id": "man-1",
            "canonical_job_id": str(uuid.uuid4()),
            "profile_version": "v1",
        }
        hash_1 = compute_manifest_hash(base)
        with_self = dict(base)
        with_self["manifest_hash"] = "any_hash_value"
        hash_2 = compute_manifest_hash(with_self)
        assert hash_1 == hash_2
        assert hash_1.startswith("sha256:")

    def test_frozen_options_extra_forbid(self) -> None:
        valid_args = {
            "document_type": DocumentType.CV,
            "purpose": "cv",
            "target_language": "de",
            "template_id": "tmpl-1",
            "template_version": "v1",
            "context_strategy": ContextStrategy.JSON,
            "allow_unavailable_job": False,
            "options_digest": "sha256:" + "0" * 64,
        }
        opts = FrozenGenerationOptions(**valid_args)
        assert opts.purpose == "cv"

        invalid_args = dict(valid_args)
        invalid_args["unexpected_field"] = "bad"
        with pytest.raises(ValidationError):
            FrozenGenerationOptions(**invalid_args)

    def test_preflight_receipt_contract_roundtrip(self) -> None:
        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        receipt = PreflightReceipt(
            request_id=req_id,
            accepted_options_digest="sha256:" + "1" * 64,
            freeze_op_id=f"freeze:{req_id}",
            started_at=now_utc,
            completed_at=now_utc,
            result="failed",
            warnings=["job_not_seen"],
            reason_code="job_unavailable",
        )
        json_str = receipt.model_dump_json()
        reloaded = PreflightReceipt.model_validate_json(json_str)
        assert reloaded.request_id == req_id
        assert reloaded.result == "failed"
        assert reloaded.warnings == ["job_not_seen"]
        assert reloaded.reason_code == "job_unavailable"

