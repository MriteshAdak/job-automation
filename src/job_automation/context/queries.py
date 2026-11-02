"""Deterministic requirement query construction for CONTEXT-04 retrieval."""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from job_automation.context.errors import ContextValidationError
from job_automation.context.keyword_index import KeywordAnalyzer
from job_automation.context.selector_ports import QueryBuilderPort
from job_automation.context.selector_records import (
    RequirementQuery,
    RequirementQuerySet,
)


class DefaultQueryBuilder(QueryBuilderPort):
    """Constructs versioned, deterministic requirement queries with bounded work limits."""

    def __init__(
        self,
        analyzer: KeywordAnalyzer | None = None,
        recipe_version: str = "v1",
        max_queries: int = 20,
        max_query_chars: int = 500,
    ) -> None:
        self.analyzer = analyzer or KeywordAnalyzer(version="v1")
        self.recipe_version = recipe_version
        self.max_queries = max_queries
        self.max_query_chars = max_query_chars

    def build_queries(
        self,
        requirements: Sequence[str],
        fallback_job_text: str | None = None,
    ) -> RequirementQuerySet:
        """Construct deterministic queries from explicit requirements or job text fallback."""
        cleaned_requirements = [req.strip() for req in requirements if req and req.strip()]

        if not cleaned_requirements and fallback_job_text:
            text = fallback_job_text.strip()
            if text and self.analyzer.analyze(text):
                # Use bounded snippet of fallback job text as single query
                snippet = text[: self.max_query_chars]
                cleaned_requirements = [snippet]

        if len(cleaned_requirements) > self.max_queries:
            raise ContextValidationError(
                f"Requirements count ({len(cleaned_requirements)}) exceeds maximum query limit ({self.max_queries})",
                field_path="requirements",
                details={
                    "count": len(cleaned_requirements),
                    "max_queries": self.max_queries,
                },
            )

        queries: list[RequirementQuery] = []
        for idx, req_text in enumerate(cleaned_requirements):
            if len(req_text) > self.max_query_chars:
                raise ContextValidationError(
                    f"Requirement at index {idx} exceeds maximum length ({len(req_text)} > {self.max_query_chars} chars)",
                    field_path=f"requirements[{idx}]",
                    details={
                        "index": idx,
                        "length": len(req_text),
                        "max_chars": self.max_query_chars,
                    },
                )

            # Analyze terms using KeywordAnalyzer
            token_pairs = self.analyzer.analyze(req_text)
            terms = [term for term, _ in token_pairs]
            # Deduplicate terms while preserving order of appearance
            seen_terms: set[str] = set()
            unique_terms: list[str] = []
            for t in terms:
                if t not in seen_terms:
                    seen_terms.add(t)
                    unique_terms.append(t)

            query_id = f"q_{idx}"
            provenance = "requirement" if requirements else "job_fallback"
            queries.append(
                RequirementQuery(
                    query_id=query_id,
                    original_text=req_text,
                    query_text=req_text,
                    terms=unique_terms,
                    source_span=None,
                    provenance=provenance,
                )
            )

        # Compute deterministic fingerprint of all queries
        query_payload = [
            {
                "query_id": q.query_id,
                "original_text": q.original_text,
                "query_text": q.query_text,
                "terms": q.terms,
                "provenance": q.provenance,
            }
            for q in queries
        ]
        canonical = json.dumps(
            {"recipe_version": self.recipe_version, "queries": query_payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        query_set_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return RequirementQuerySet(
            recipe_version=self.recipe_version,
            queries=queries,
            query_set_fingerprint=query_set_fingerprint,
        )
