"""Unit tests for CONTEXT-03 retrieval index contract models."""

from __future__ import annotations

import uuid
from pydantic import ValidationError
import pytest

from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRecord,
    IndexBuildRequest,
    IndexBuildResult,
    IndexManifest,
    IndexReadRequest,
    IndexRowMapping,
    IndexSettings,
    PayloadFileInfo,
    TermPosting,
)
from tests.context.index_test_helpers import (
    create_test_build_request,
    create_test_chunk_set,
    create_test_embedding_config,
    create_test_index_settings,
)


def test_index_settings_defaults_and_validation() -> None:
    settings = IndexSettings()
    assert settings.dtype == "float32"
    assert settings.byte_order == "little_endian"
    assert settings.metric == "cosine"
    assert settings.normalization == "l2"

    # Unsupported dtype
    with pytest.raises(ValidationError):
        IndexSettings(dtype="float64")

    # Unsupported byte_order
    with pytest.raises(ValidationError):
        IndexSettings(byte_order="big_endian")


def test_embedding_configuration_validation() -> None:
    config = create_test_embedding_config(dimension=16)
    assert config.dimension == 16
    assert config.model_identifier == "fake-embedder"

    # Dimension must be > 0
    with pytest.raises(ValidationError):
        EmbeddingConfiguration(
            model_identifier="test",
            dimension=0,
        )


def test_index_build_request_chunk_set_alignment() -> None:
    cs = create_test_chunk_set()
    emb_config = create_test_embedding_config()
    settings = create_test_index_settings()

    # Valid request
    req = IndexBuildRequest(
        candidate_id=cs.candidate_id,
        profile_version=cs.profile_version,
        purpose=cs.purpose,
        chunk_set=cs,
        embedding_config=emb_config,
        settings=settings,
    )
    assert req.candidate_id == cs.candidate_id

    # Candidate mismatch raises ValueError
    with pytest.raises(ValidationError) as exc:
        IndexBuildRequest(
            candidate_id=uuid.uuid4(),
            profile_version=cs.profile_version,
            purpose=cs.purpose,
            chunk_set=cs,
            embedding_config=emb_config,
            settings=settings,
        )
    assert "Candidate mismatch" in str(exc.value)

    # Profile version mismatch raises ValueError
    with pytest.raises(ValidationError) as exc:
        IndexBuildRequest(
            candidate_id=cs.candidate_id,
            profile_version="v999",
            purpose=cs.purpose,
            chunk_set=cs,
            embedding_config=emb_config,
            settings=settings,
        )
    assert "Profile version mismatch" in str(exc.value)

    # Purpose mismatch raises ValueError
    with pytest.raises(ValidationError) as exc:
        IndexBuildRequest(
            candidate_id=cs.candidate_id,
            profile_version=cs.profile_version,
            purpose="cover_letter",
            chunk_set=cs,
            embedding_config=emb_config,
            settings=settings,
        )
    assert "Purpose mismatch" in str(exc.value)


def test_term_posting_validation() -> None:
    posting = TermPosting(
        term="engineer",
        row_ordinal=0,
        term_frequency=2,
        positions=[1, 5],
    )
    assert posting.term == "engineer"
    assert posting.term_frequency == 2
    assert posting.positions == [1, 5]

    # Negative row_ordinal invalid
    with pytest.raises(ValidationError):
        TermPosting(
            term="test",
            row_ordinal=-1,
            term_frequency=1,
            positions=[0],
        )


def test_index_read_request_modes() -> None:
    cand_id = uuid.uuid4()

    # current_use valid without frozen_generation_id
    req1 = IndexReadRequest(
        candidate_id=cand_id,
        purpose="assessment",
        authorization_mode="current_use",
    )
    assert req1.authorization_mode == "current_use"

    # frozen_use
    gen_id = uuid.uuid4()
    req2 = IndexReadRequest(
        candidate_id=cand_id,
        purpose="assessment",
        authorization_mode="frozen_use",
        frozen_generation_id=gen_id,
    )
    assert req2.frozen_generation_id == gen_id

