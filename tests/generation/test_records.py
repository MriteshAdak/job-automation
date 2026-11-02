"""Tests for GEN-01 contract records, ID canonicalization, and option digests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.generation.records import (
    FreezeManifest,
    GenerationRequestObservation,
    ObservationIssueCategory,
    ProjectionIntent,
    ProjectionStatus,
    StageCheckpoint,
    StageStatus,
)
from job_automation.generation.request_mapping import (
    canonicalize_salesforce_id,
    compute_options_digest,
    derive_local_request_id,
)


class TestRecordsAndMapping:
    def test_canonicalize_15_char_salesforce_id_preserves_case(self) -> None:
        # Standard 15-character test ID
        sf_15 = "00D000000000001"
        sf_18 = canonicalize_salesforce_id(sf_15)
        assert len(sf_18) == 18
        assert sf_18.startswith(sf_15)
        assert sf_18 == "00D000000000001EAA"
        # Case is strictly preserved
        assert "00d" not in sf_18

    def test_canonicalize_15_char_mixed_case(self) -> None:
        sf_15 = "a00123456789ABC"
        sf_18 = canonicalize_salesforce_id(sf_15)
        assert len(sf_18) == 18
        assert sf_18 == "a00123456789ABCAA2"

    def test_canonicalize_18_char_id_returned_unchanged(self) -> None:
        sf_18 = "00D000000000001EAA"
        assert canonicalize_salesforce_id(sf_18) == sf_18

    def test_canonicalize_invalid_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid Salesforce ID"):
            canonicalize_salesforce_id("invalid-id")
        with pytest.raises(ValueError, match="Invalid Salesforce ID"):
            canonicalize_salesforce_id("12345")

    def test_derive_local_request_id_is_deterministic(self) -> None:
        org_id = "00D000000000001"
        sf_id = "a00123456789ABC"
        uuid1 = derive_local_request_id(org_id, sf_id)
        uuid2 = derive_local_request_id(org_id, sf_id)
        assert uuid1 == uuid2
        assert isinstance(uuid1, uuid.UUID)

        # Different SF ID yields different UUID
        uuid3 = derive_local_request_id(org_id, "a00123456789ABD")
        assert uuid1 != uuid3

        # 15 and 18-char canonical representations converge
        sf_18 = canonicalize_salesforce_id(sf_id)
        assert derive_local_request_id(org_id, sf_18) == uuid1

    def test_compute_options_digest_is_deterministic(self) -> None:
        job_id = uuid.uuid4()
        opts1 = {
            "canonical_job_id": job_id,
            "document_type": DocumentType.CV,
            "target_language": "de",
            "template_id": "template_1",
            "context_strategy": ContextStrategy.JSON,
            "allow_unavailable_job": False,
        }
        opts2 = {
            "template_id": "template_1",
            "context_strategy": ContextStrategy.JSON,
            "allow_unavailable_job": False,
            "canonical_job_id": str(job_id),
            "target_language": "de",
            "document_type": "cv",
        }
        digest1 = compute_options_digest(opts1)
        digest2 = compute_options_digest(opts2)
        assert digest1 == digest2
        assert len(digest1) == 64

    def test_freeze_manifest_roundtrip(self) -> None:
        manifest = FreezeManifest(
            manifest_id="manifest-001",
            manifest_hash="sha256:" + "a" * 64,
            canonical_job_id=uuid.uuid4(),
            posting_revision_id="rev-001",
            posting_revision_hash="hash-001",
            profile_version="prof-v1",
            policy_version="pol-v1",
            template_id="tmpl-1",
            template_version="tmpl-v1",
            context_strategy=ContextStrategy.JSON,
            target_language="de",
            options_digest="sha256:" + "b" * 64,
            availability_status="active",
            allow_unavailable_job=False,
            frozen_at=datetime.now(timezone.utc),
            snapshot_refs={"profile": "snapshots/prof.json"},
            warnings=["unknown_field"],
        )
        json_str = manifest.model_dump_json()
        restored = FreezeManifest.model_validate_json(json_str)
        assert restored.manifest_id == manifest.manifest_id
        assert restored.manifest_hash == manifest.manifest_hash
        assert restored.warnings == ["unknown_field"]

