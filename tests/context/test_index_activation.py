"""Unit tests for IndexLifecycleManager activation semantics."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_errors import (
    IndexBindingError,
    IndexStaleError,
    IndexValidationError,
)
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import StorageError
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_activation_checks(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(
        indexes_dir=indexes_dir,
        provider=provider,
        repository=engine.context_indexes,
    )
    lifecycle = IndexLifecycleManager(repository=engine.context_indexes)

    req = create_test_build_request(dimension=8)
    res, _ = builder.build(req)
    assert res is not None

    # Unknown generation ID raises IndexValidationError
    with pytest.raises(IndexValidationError):
        lifecycle.activate(req.candidate_id, req.purpose, uuid.uuid4())

    # Profile version mismatch raises IndexStaleError
    with pytest.raises(IndexStaleError):
        lifecycle.activate(
            req.candidate_id,
            req.purpose,
            res.generation_id,
            expected_profile_version="v99",
        )

    # Valid activation succeeds
    token = lifecycle.activate(
        req.candidate_id,
        req.purpose,
        res.generation_id,
        expected_profile_version=req.profile_version,
    )
    assert token is not None

    # Activating an already active generation raises IndexBindingError
    with pytest.raises(IndexBindingError):
        lifecycle.activate(
            req.candidate_id,
            req.purpose,
            res.generation_id,
        )

