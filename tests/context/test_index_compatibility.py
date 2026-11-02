"""Unit tests for embedding space compatibility rules in CONTEXT-03."""

from __future__ import annotations

from job_automation.context.index_identity import (
    validate_embedding_space_compatibility,
)
from tests.context.index_test_helpers import (
    create_test_embedding_config,
    create_test_index_settings,
)


def test_same_dimension_different_model_is_incompatible() -> None:
    settings = create_test_index_settings()
    # Same dimension 768, different model identifier
    cfg_a = create_test_embedding_config(dimension=768, model_identifier="nomic-embed-text")
    cfg_b = create_test_embedding_config(dimension=768, model_identifier="bge-base-en-v1.5")

    assert not validate_embedding_space_compatibility(cfg_a, cfg_b, settings)


def test_same_model_different_digest_is_incompatible() -> None:
    settings = create_test_index_settings()
    cfg_a = create_test_embedding_config(
        dimension=384, model_identifier="all-minilm", model_digest="sha256_weights_v1"
    )
    cfg_b = create_test_embedding_config(
        dimension=384, model_identifier="all-minilm", model_digest="sha256_weights_v2"
    )

    assert not validate_embedding_space_compatibility(cfg_a, cfg_b, settings)


def test_changed_document_prefix_is_incompatible() -> None:
    settings = create_test_index_settings()
    cfg_a = create_test_embedding_config(dimension=768, model_identifier="nomic-embed-text")
    cfg_b = cfg_a.model_copy(update={"document_prefix": "search_document: "})

    assert not validate_embedding_space_compatibility(cfg_a, cfg_b, settings)


def test_changed_metric_is_incompatible() -> None:
    cfg = create_test_embedding_config(dimension=768, model_identifier="nomic-embed-text")
    settings_cosine = create_test_index_settings()
    settings_dot = settings_cosine.model_copy(update={"metric": "dot_product"})

    assert not validate_embedding_space_compatibility(cfg, cfg, settings_cosine) is False  # identical settings pass
    # Comparing cross-settings
    from job_automation.context.index_identity import compute_embedding_space_fingerprint
    fp1 = compute_embedding_space_fingerprint(cfg, settings_cosine)
    fp2 = compute_embedding_space_fingerprint(cfg, settings_dot)
    assert fp1 != fp2

