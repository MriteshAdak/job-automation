"""Tests for requirement query set construction (S03, RET-04, RET-06, RET-07)."""

from __future__ import annotations

import pytest

from job_automation.context.errors import ContextValidationError
from job_automation.context.queries import DefaultQueryBuilder


def test_query_builder_extracts_tokens_and_preserves_special_skills() -> None:
    builder = DefaultQueryBuilder()
    reqs = [
        "Experience in C++ and C# with .NET microservices",
        "CI/CD deployment with Docker in München",
        "Frontend with Node.js and TypeScript",
    ]

    qset = builder.build_queries(reqs)
    assert len(qset.queries) == 3

    q0 = qset.queries[0]
    assert q0.query_id == "q_0"
    assert "c++" in q0.terms
    assert "c#" in q0.terms
    assert ".net" in q0.terms

    q1 = qset.queries[1]
    assert "ci/cd" in q1.terms
    assert "docker" in q1.terms
    assert "münchen" in q1.terms

    q2 = qset.queries[2]
    assert "node.js" in q2.terms

    assert len(qset.query_set_fingerprint) == 64


def test_query_builder_fallback_to_job_description() -> None:
    builder = DefaultQueryBuilder()
    qset = builder.build_queries(
        requirements=[],
        fallback_job_text="Softwareentwickler für C++ Hochleistungssysteme in München gesucht.",
    )

    assert len(qset.queries) == 1
    assert qset.queries[0].provenance == "job_fallback"
    assert "c++" in qset.queries[0].terms
    assert "münchen" in qset.queries[0].terms


def test_query_builder_empty_inputs_returns_empty_set() -> None:
    builder = DefaultQueryBuilder()
    qset = builder.build_queries(requirements=[], fallback_job_text=None)
    assert len(qset.queries) == 0
    assert len(qset.query_set_fingerprint) == 64


def test_query_builder_oversized_requirements_count_fails() -> None:
    builder = DefaultQueryBuilder(max_queries=3)
    with pytest.raises(ContextValidationError, match="Requirements count .* exceeds maximum query limit"):
        builder.build_queries(["Req 1", "Req 2", "Req 3", "Req 4"])


def test_query_builder_oversized_query_length_fails() -> None:
    builder = DefaultQueryBuilder(max_query_chars=20)
    with pytest.raises(ContextValidationError, match="exceeds maximum length"):
        builder.build_queries(["This requirement is definitely longer than 20 characters"])


def test_query_builder_deterministic_fingerprint() -> None:
    builder = DefaultQueryBuilder()
    reqs = ["Python backend developer", "PostgreSQL database optimization"]

    qset1 = builder.build_queries(reqs)
    qset2 = builder.build_queries(reqs)
    qset3 = builder.build_queries(["Different requirement"])

    assert qset1.query_set_fingerprint == qset2.query_set_fingerprint
    assert qset1.query_set_fingerprint != qset3.query_set_fingerprint

