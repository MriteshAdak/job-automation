"""Retrieval settings configuration and validation for CONTEXT-04 hybrid RAG."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel


class RetrievalSettings(ContractModel):
    """Validated settings governing keyword/semantic retrieval and reciprocal rank fusion."""

    schema_version: str = "1.0"
    algorithm_version: str = "v1"
    query_format_version: str = "v1"

    # Candidate selection limits
    top_k: int = Field(
        default=8,
        ge=0,
        description="Maximum number of optional primary facts admitted (0 is allowed)",
    )
    per_channel_limit: int = Field(
        default=20,
        gt=0,
        description="Per-query candidate pool limit for each channel (keyword and semantic)",
    )

    # Retrieval metrics & fusion
    keyword_metric: Literal["distinct_terms", "bm25"] = Field(
        default="distinct_terms",
        description="Keyword scoring metric",
    )
    semantic_metric: Literal["cosine", "dot_product"] = Field(
        default="cosine",
        description="Semantic similarity metric",
    )
    fusion_method: Literal["rrf"] = Field(
        default="rrf",
        description="Rank fusion method (Reciprocal Rank Fusion)",
    )
    rrf_k: int = Field(
        default=60,
        gt=0,
        description="RRF smoothing constant k in sum(1 / (k + rank))",
    )
    multi_query_aggregation: Literal["max", "sum"] = Field(
        default="max",
        description="Aggregation method across multiple requirement queries",
    )
    tie_break_order: list[str] = Field(
        default_factory=lambda: ["query_count", "best_channel_rank", "fact_id"],
        description="Ordered tie-break criteria for equal fused scores",
    )

    # Hierarchy and safety
    strict_parents: bool = Field(
        default=False,
        description="If True, missing/restricted optional parent raises permission error",
    )
    semantic_threshold: float | None = Field(
        default=None,
        description="Optional minimum semantic similarity cutoff; None initially",
    )

    # Work bounds
    max_queries: int = Field(
        default=20,
        gt=0,
        description="Maximum number of requirement queries processed",
    )
    max_query_chars: int = Field(
        default=500,
        gt=0,
        description="Maximum character length per requirement query",
    )

    @model_validator(mode="after")
    def validate_limits(self) -> RetrievalSettings:
        if self.top_k > self.per_channel_limit:
            raise ValueError(
                f"top_k ({self.top_k}) cannot exceed per_channel_limit ({self.per_channel_limit})"
            )
        return self

    def compute_settings_fingerprint(self) -> str:
        """Derive deterministic SHA-256 fingerprint of effective retrieval settings."""
        payload = {
            "schema_version": self.schema_version,
            "algorithm_version": self.algorithm_version,
            "query_format_version": self.query_format_version,
            "top_k": self.top_k,
            "per_channel_limit": self.per_channel_limit,
            "keyword_metric": self.keyword_metric,
            "semantic_metric": self.semantic_metric,
            "fusion_method": self.fusion_method,
            "rrf_k": self.rrf_k,
            "multi_query_aggregation": self.multi_query_aggregation,
            "tie_break_order": self.tie_break_order,
            "strict_parents": self.strict_parents,
            "semantic_threshold": self.semantic_threshold,
            "max_queries": self.max_queries,
            "max_query_chars": self.max_query_chars,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFAULT_RETRIEVAL_SETTINGS = RetrievalSettings()

