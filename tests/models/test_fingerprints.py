"""Tests for canonical input fingerprinting algorithms (LLM-01-S03)."""

from __future__ import annotations

from job_automation.models.fingerprints import (
    compute_embedding_fingerprint,
    compute_generation_fingerprint,
)


class TestFingerprints:
    def test_generation_fingerprint_deterministic(self) -> None:
        """Identical inputs produce exact identical fingerprint."""
        h1 = compute_generation_fingerprint("Evaluate applicant", "You are an evaluator")
        h2 = compute_generation_fingerprint("Evaluate applicant", "You are an evaluator")
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_generation_fingerprint_sensitive_to_whitespace_and_unicode(self) -> None:
        """Changes in whitespace or unicode characters alter fingerprint."""
        base = compute_generation_fingerprint("Job: Developer", "System instructions")
        space_diff = compute_generation_fingerprint("Job:  Developer", "System instructions")
        unicode_diff = compute_generation_fingerprint("Job: Entwickler Prüfung ä", "System instructions")

        assert base != space_diff
        assert base != unicode_diff

    def test_generation_fingerprint_sensitive_to_system_prompt(self) -> None:
        """Altering system prompt alters fingerprint."""
        h1 = compute_generation_fingerprint("Prompt", "Sys 1")
        h2 = compute_generation_fingerprint("Prompt", "Sys 2")
        h3 = compute_generation_fingerprint("Prompt", None)

        assert h1 != h2
        assert h1 != h3

    def test_embedding_fingerprint_sensitive_to_ordering(self) -> None:
        """Reordering texts produces a distinct fingerprint."""
        texts_1 = ["first text", "second text", "third text"]
        texts_2 = ["second text", "first text", "third text"]

        h1 = compute_embedding_fingerprint(texts_1)
        h2 = compute_embedding_fingerprint(texts_2)

        assert h1 != h2

