"""Deterministic keyword indexing with normalized term postings in per-generation SQLite."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from job_automation.contracts.retrieval_index import PayloadFileInfo, TermPosting

# Match specific programming skills / compound tokens before general words
SKILL_TOKEN_PATTERN = re.compile(
    r"(?i)\.net\b|\bc\+\+|\bc\#|\bci/cd\b|\bnode\.js\b"
)
WORD_TOKEN_PATTERN = re.compile(
    r"[^\W_]+(?:[-'][^\W_]+)*"
)
COMBINED_TOKEN_PATTERN = re.compile(
    r"(?i)\.net\b|\bc\+\+|\bc\#|\bci/cd\b|\bnode\.js\b|[^\W_]+(?:[-'][^\W_]+)*"
)


class KeywordAnalyzer:
    """Deterministic token analyzer preserving skills, German/English words, and Unicode."""

    def __init__(self, version: str = "v1") -> None:
        self.version = version

    def analyze(self, text: str) -> list[tuple[str, int]]:
        """Tokenize text into ordered pairs of (normalized_term, 0-based position)."""
        tokens: list[tuple[str, int]] = []
        pos = 0
        for match in COMBINED_TOKEN_PATTERN.finditer(text):
            raw_token = match.group(0)
            term = raw_token.casefold()
            tokens.append((term, pos))
            pos += 1
        return tokens

    def extract_document_postings(
        self,
        row_ordinal: int,
        text: str,
    ) -> list[TermPosting]:
        """Extract term postings for a single document / row ordinal."""
        tokens = self.analyze(text)
        term_positions: dict[str, list[int]] = defaultdict(list)

        for term, pos in tokens:
            term_positions[term].append(pos)

        postings: list[TermPosting] = []
        for term, positions in sorted(term_positions.items()):
            postings.append(
                TermPosting(
                    term=term,
                    row_ordinal=row_ordinal,
                    term_frequency=len(positions),
                    positions=positions,
                )
            )
        return postings


class KeywordIndexWriter:
    """Builds an isolated, finalized SQLite keywords.db for an index generation."""

    def __init__(self, db_path: Path, analyzer: KeywordAnalyzer | None = None) -> None:
        self.db_path = db_path
        self.analyzer = analyzer or KeywordAnalyzer()

    def build_index(
        self,
        row_texts: Sequence[str],
        metadata: dict[str, str] | None = None,
        relative_to: Path | None = None,
    ) -> PayloadFileInfo:
        """Construct keywords database, populate postings and terms, and checkpoint."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode = DELETE;")
            conn.execute("PRAGMA synchronous = FULL;")

            conn.execute(
                """
                CREATE TABLE meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE postings (
                    term TEXT NOT NULL,
                    row_ordinal INTEGER NOT NULL,
                    term_frequency INTEGER NOT NULL,
                    positions_json TEXT NOT NULL,
                    PRIMARY KEY (term, row_ordinal)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX idx_postings_term ON postings(term);
                """
            )
            conn.execute(
                """
                CREATE INDEX idx_postings_row ON postings(row_ordinal);
                """
            )
            conn.execute(
                """
                CREATE TABLE terms (
                    term TEXT PRIMARY KEY,
                    document_frequency INTEGER NOT NULL
                );
                """
            )

            # Insert metadata
            meta = metadata or {}
            for k, v in meta.items():
                conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (k, v))

            # Populate postings
            term_doc_counts: dict[str, int] = defaultdict(int)
            postings_rows: list[tuple[str, int, int, str]] = []

            for row_ordinal, text in enumerate(row_texts):
                doc_postings = self.analyzer.extract_document_postings(row_ordinal, text)
                for p in doc_postings:
                    term_doc_counts[p.term] += 1
                    postings_rows.append(
                        (p.term, p.row_ordinal, p.term_frequency, json.dumps(p.positions))
                    )

            if postings_rows:
                conn.executemany(
                    "INSERT INTO postings (term, row_ordinal, term_frequency, positions_json) VALUES (?, ?, ?, ?)",
                    postings_rows,
                )

            term_rows = [(term, count) for term, count in term_doc_counts.items()]
            if term_rows:
                conn.executemany(
                    "INSERT INTO terms (term, document_frequency) VALUES (?, ?)",
                    term_rows,
                )

            conn.commit()
        finally:
            conn.close()

        # Compute digest
        h = hashlib.sha256()
        size = 0
        with open(self.db_path, "rb") as f:
            while chunk := f.read(65536):
                size += len(chunk)
                h.update(chunk)

        rel_path = (
            self.db_path.relative_to(relative_to).as_posix()
            if relative_to is not None
            else self.db_path.name
        )
        return PayloadFileInfo(
            relative_path=rel_path,
            byte_length=size,
            sha256_hash=h.hexdigest(),
        )


class KeywordIndexReader:
    """Read-only query access to a generation's keywords.db."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only = ON;")

    def lookup_term(self, term: str) -> list[TermPosting]:
        """Lookup all postings for a normalized term."""
        normalized = term.casefold()
        cursor = self.conn.execute(
            """
            SELECT term, row_ordinal, term_frequency, positions_json
            FROM postings
            WHERE term = ?
            ORDER BY row_ordinal ASC
            """,
            (normalized,),
        )
        results: list[TermPosting] = []
        for row in cursor.fetchall():
            results.append(
                TermPosting(
                    term=row["term"],
                    row_ordinal=row["row_ordinal"],
                    term_frequency=row["term_frequency"],
                    positions=json.loads(row["positions_json"]),
                )
            )
        return results

    def lookup_terms(self, terms: Sequence[str]) -> dict[str, list[TermPosting]]:
        """Lookup postings for multiple terms."""
        return {term: self.lookup_term(term) for term in terms}

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
