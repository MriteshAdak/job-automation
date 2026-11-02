"""Unit tests for row alignment across vector matrix, keyword postings, and source chunks."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_reader import IndexHandle
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_row_alignment_across_representations(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(indexes_dir=indexes_dir, provider=provider)

    req = create_test_build_request(dimension=8)
    res, err = builder.build(req)
    assert err is None
    assert res is not None

    final_dir = indexes_dir / str(req.candidate_id) / req.purpose / str(res.generation_id)
    handle = IndexHandle(manifest=res.manifest, generation_dir=final_dir)

    try:
        assert handle.row_count == len(req.chunk_set.chunks)

        for i, chunk in enumerate(req.chunk_set.chunks):
            # Row mapping in manifest
            row_map = res.manifest.rows[i]
            assert row_map.row_ordinal == i
            assert row_map.chunk_id == chunk.chunk_id
            assert row_map.primary_fact_id == chunk.primary_fact_id

            # Source chunk retrieval
            retrieved_chunk = handle.get_chunk(i)
            assert retrieved_chunk.chunk_id == chunk.chunk_id
            assert retrieved_chunk.retrieval_text == chunk.retrieval_text

            # Chunk lookup by chunk_id
            by_id = handle.get_chunk_by_id(chunk.chunk_id)
            assert by_id is not None
            assert by_id.chunk_id == chunk.chunk_id

            # Vector retrieval
            vec = handle.get_vector(i)
            assert len(vec) == 8
    finally:
        handle.close()

