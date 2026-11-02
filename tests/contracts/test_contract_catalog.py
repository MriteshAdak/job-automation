"""Comprehensive contract catalog test.

Audits C01–C15 contracts against synthetic fixtures and exported JSON schemas.
Validates round-trip serialization and expected negative failure behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type

import pytest
from pydantic import BaseModel, ValidationError

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.models import ModelCall
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import (
    FetchManifest,
    NormalizedPosting,
    RawPosting,
)
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.runs import RunSummary
from job_automation.contracts.sources import SourceConfig
from job_automation.contracts.sync import SyncOperation

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"

# Map of contract directory name to primary validating Pydantic model
CATALOG_MODELS: dict[str, Type[BaseModel]] = {
    "C01": ProfileSnapshot,
    "C02": SearchPolicy,
    "C03": SourceConfig,
    "C04": FetchManifest,
    "C05": RawPosting,
    "C06": NormalizedPosting,
    "C07": CanonicalJob,
    "C08": CandidateEvidenceReference,
    "C09": ContextBundle,
    "C10": ModelCall,
    "C11": Assessment,
    "C12": SyncOperation,
    "C13": GenerationRequest,
    "C14": Artifact,
    "C15": RunSummary,
}


class TestContractCatalog:
    def test_catalog_completeness(self) -> None:
        """Verify all 15 contract IDs (C01–C15) are mapped in the catalog."""
        expected_ids = {f"C{i:02d}" for i in range(1, 16)}
        assert set(CATALOG_MODELS.keys()) == expected_ids

    @pytest.mark.parametrize("contract_id,model_cls", CATALOG_MODELS.items())
    def test_positive_fixtures_validate_and_round_trip(
        self, contract_id: str, model_cls: Type[BaseModel]
    ) -> None:
        fixture_path = FIXTURES_DIR / contract_id / "valid.json"
        assert fixture_path.is_file(), f"Missing positive fixture for {contract_id}"

        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        instance = model_cls.model_validate(data)
        assert instance is not None

        # Verify round-trip serialization
        dumped = instance.model_dump(mode="json")
        reloaded = model_cls.model_validate(dumped)
        assert reloaded == instance

    @pytest.mark.parametrize("contract_id,model_cls", CATALOG_MODELS.items())
    def test_negative_fixtures_fail_validation(
        self, contract_id: str, model_cls: Type[BaseModel]
    ) -> None:
        fixture_path = FIXTURES_DIR / contract_id / "invalid.json"
        assert fixture_path.is_file(), f"Missing negative fixture for {contract_id}"

        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        with pytest.raises(ValidationError):
            model_cls.model_validate(data)

    def test_all_schemas_exist_and_are_valid_json(self) -> None:
        """Verify all 21 exported JSON schemas exist in schemas/v1/ and parse as JSON."""
        schema_files = list(SCHEMAS_DIR.glob("*.schema.json"))
        assert len(schema_files) >= 21, f"Expected at least 21 schemas, found {len(schema_files)}"

        for schema_file in schema_files:
            with open(schema_file, "r", encoding="utf-8") as f:
                schema_json = json.load(f)
            assert "$schema" in schema_json or "$defs" in schema_json or "properties" in schema_json

