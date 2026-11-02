"""Unit tests for KeywordAnalyzer, KeywordIndexWriter, and KeywordIndexReader."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.keyword_index import (
    KeywordAnalyzer,
    KeywordIndexReader,
    KeywordIndexWriter,
)


def test_keyword_analyzer_tokenization() -> None:
    analyzer = KeywordAnalyzer()
    text = "Senior C++ and C# developer (.NET 8) in München, Germany! Skills: Docker, CI/CD."
    tokens = analyzer.analyze(text)

    terms = [term for term, pos in tokens]

    assert "c++" in terms
    assert "c#" in terms
    assert ".net" in terms
    assert "ci/cd" in terms
    assert "münchen" in terms  # German umlauts preserved
    assert "docker" in terms


def test_keyword_analyzer_positions_and_frequencies() -> None:
    analyzer = KeywordAnalyzer()
    text = "Python developer building Python apps with Python."
    postings = analyzer.extract_document_postings(row_ordinal=0, text=text)

    postings_by_term = {p.term: p for p in postings}
    assert "python" in postings_by_term
    py_posting = postings_by_term["python"]

    assert py_posting.term_frequency == 3
    assert py_posting.positions == [0, 3, 6]  # 0-based token positions


def test_keyword_index_writer_and_reader_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "keywords.db"
    writer = KeywordIndexWriter(db_path=db_path)

    documents = [
        "Senior C++ Engineer in München",
        "Frontend React and TypeScript developer",
        "Full-stack engineer with C++ and React",
    ]

    info = writer.build_index(documents, metadata={"generation_id": "test_gen"})
    assert info.byte_length > 0
    assert len(info.sha256_hash) == 64

    reader = KeywordIndexReader(db_path=db_path)
    try:
        # Lookup term occurring in docs 0 and 2
        hits_cpp = reader.lookup_term("C++")
        assert len(hits_cpp) == 2
        assert [h.row_ordinal for h in hits_cpp] == [0, 2]

        # Lookup term occurring only in doc 1
        hits_react = reader.lookup_term("react")
        assert [h.row_ordinal for h in hits_react] == [1, 2]

        # Lookup non-existent term
        hits_none = reader.lookup_term("cobol")
        assert hits_none == []
    finally:
        reader.close()

