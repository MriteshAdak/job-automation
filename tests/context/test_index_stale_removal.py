"""Unit tests verifying stale-evidence removal upon rebuilding in CONTEXT-03."""

from __future__ import annotations

import uuid
from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_reader import IndexStore
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.profile import CandidateFact
from job_automation.contracts.retrieval_index import (
    IndexBuildRequest,
    IndexReadRequest,
)
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import (
    create_test_chunk_set,
    create_test_embedding_config,
    create_test_index_settings,
    create_test_profile_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_stale_evidence_removal_between_profile_versions(tmp_path: Path) -> None:
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
    store = IndexStore(indexes_dir=indexes_dir, repository=engine.context_indexes)

    cand_id = uuid.uuid4()
    fact_a_id = uuid.uuid4()
    fact_b_id = uuid.uuid4()

    # Profile v1 with facts A and B
    fact_a = CandidateFact(
        fact_id=fact_a_id,
        kind=EvidenceFactKind.SKILL,
        title="Rust Specialist",
        skills=["Rust"],
        claims=["Built memory-safe microservices"],
        provenance="v1.pdf",
        allowed_uses=["assessment"],
    )
    fact_b = CandidateFact(
        fact_id=fact_b_id,
        kind=EvidenceFactKind.SKILL,
        title="Legacy Cobol Maintainer",
        skills=["Cobol"],
        claims=["Maintained mainframe transactions"],
        provenance="v1.pdf",
        allowed_uses=["assessment"],
    )
    snap_v1 = create_test_profile_snapshot(
        candidate_id=cand_id, profile_version="v1", facts=[fact_a, fact_b]
    )
    cs_v1 = create_test_chunk_set(snap_v1, purpose="assessment")

    # Build and activate v1
    req_v1 = IndexBuildRequest(
        candidate_id=cand_id,
        profile_version="v1",
        purpose="assessment",
        chunk_set=cs_v1,
        embedding_config=create_test_embedding_config(dimension=8),
        settings=create_test_index_settings(),
    )
    res_v1, _ = builder.build(req_v1)
    assert res_v1 is not None
    token_v1 = lifecycle.activate(
        cand_id, "assessment", res_v1.generation_id, expected_profile_version="v1"
    )

    # Verify v1 contains "cobol"
    read_req_v1 = IndexReadRequest(
        candidate_id=cand_id,
        purpose="assessment",
        expected_profile_version="v1",
    )
    handle_v1, err_v1 = store.open(read_req_v1)
    assert err_v1 is None
    assert handle_v1 is not None
    assert len(handle_v1.lookup_term("cobol")) > 0
    handle_v1.close()

    # Profile v2 removes fact B (Cobol), retaining only fact A (Rust)
    snap_v2 = create_test_profile_snapshot(
        candidate_id=cand_id, profile_version="v2", facts=[fact_a]
    )
    cs_v2 = create_test_chunk_set(snap_v2, purpose="assessment")

    req_v2 = IndexBuildRequest(
        candidate_id=cand_id,
        profile_version="v2",
        purpose="assessment",
        chunk_set=cs_v2,
        embedding_config=create_test_embedding_config(dimension=8),
        settings=create_test_index_settings(),
        expected_prior_token=token_v1,
    )
    res_v2, _ = builder.build(req_v2)
    assert res_v2 is not None
    token_v2 = lifecycle.activate(
        cand_id,
        "assessment",
        res_v2.generation_id,
        expected_prior_token=token_v1,
        expected_profile_version="v2",
    )

    # Open active v2 index
    read_req_v2 = IndexReadRequest(
        candidate_id=cand_id,
        purpose="assessment",
        expected_profile_version="v2",
    )
    handle_v2, err_v2 = store.open(read_req_v2)
    assert err_v2 is None
    assert handle_v2 is not None

    try:
        # Row count is exactly 1 (only fact A)
        assert handle_v2.row_count == 1
        assert handle_v2.get_chunk(0).primary_fact_id == fact_a_id

        # "cobol" must NOT be in v2 active index!
        assert handle_v2.lookup_term("cobol") == []

        # "rust" IS present in v2
        assert len(handle_v2.lookup_term("rust")) > 0
    finally:
        handle_v2.close()

