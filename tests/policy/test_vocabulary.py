"""Tests for POLICY-01-S03 German/English vocabulary normalization and alias validation."""

from __future__ import annotations

import pytest

from job_automation.policy.vocabulary import (
    normalize_display,
    normalize_lookup,
    validate_vocabulary,
)


class TestVocabularyNormalization:
    def test_unicode_nfc_and_whitespace_collapsing(self) -> None:
        raw = "  Senior   Software\tEngineer   "
        disp = normalize_display(raw)
        assert disp == "Senior Software Engineer"

        lk = normalize_lookup(raw)
        assert lk == "senior software engineer"

    def test_german_umlauts_composed_and_decomposed(self) -> None:
        composed = "München"
        decomposed = "Mu\u0308nchen"
        assert normalize_display(composed) == normalize_display(decomposed)
        assert normalize_lookup(composed) == normalize_lookup(decomposed)

    def test_german_eszett_casefold_and_display(self) -> None:
        term = "Großkundenbetreuer"
        assert normalize_display(term) == "Großkundenbetreuer"
        # In Python str.casefold(), 'ß' becomes 'ss'
        assert normalize_lookup(term) == "grosskundenbetreuer"

    def test_distinctive_punctuation_preserved(self) -> None:
        # C, C++, C#, .NET must remain completely distinct
        assert normalize_display("C++") == "C++"
        assert normalize_display("C#") == "C#"
        assert normalize_display(".NET") == ".NET"
        assert normalize_lookup("C++") != normalize_lookup("C")
        assert normalize_lookup("C#") != normalize_lookup("C")
        assert normalize_lookup(".NET") != normalize_lookup("NET")

    def test_canonical_term_resolves_to_itself(self) -> None:
        roles = {
            "Projektmanager": ["Project Manager", "Projektleiter"]
        }
        skills = {
            "Python": ["Python 3", "Python3"]
        }
        vocab, issues = validate_vocabulary(roles, skills)
        assert len([i for i in issues if i.severity == "error"]) == 0

        # Resolves canonical term directly
        assert vocab.resolve_role("Projektmanager") == "Projektmanager"
        assert vocab.resolve_role("projektmanager") == "Projektmanager"
        assert vocab.resolve_role("PROJECT MANAGER") == "Projektmanager"

        # Resolves skill
        assert vocab.resolve_skill("Python") == "Python"
        assert vocab.resolve_skill("python3") == "Python"
        assert vocab.resolve_skill("PYTHON 3") == "Python"
        assert vocab.resolve_skill("Java") is None

    def test_reject_empty_canonical_and_empty_alias(self) -> None:
        roles = {
            "": ["Developer"],
            "Manager": ["  "]
        }
        vocab, issues = validate_vocabulary(roles, {})
        assert any(i.code == "empty_canonical_term" for i in issues)
        assert any(i.code == "empty_alias" for i in issues)

    def test_reject_duplicate_canonical_term(self) -> None:
        roles = {
            "Software Developer": ["Dev"],
            "software developer": ["Programmer"],
        }
        vocab, issues = validate_vocabulary(roles, {})
        assert any(i.code == "duplicate_canonical_term" for i in issues)

    def test_warn_and_deduplicate_in_group_duplicates(self) -> None:
        roles = {
            "Developer": ["Dev", "dev", "DEV"]
        }
        vocab, issues = validate_vocabulary(roles, {})
        # Should have warnings for duplicate aliases in group
        warnings = [i for i in issues if i.severity == "warning" and i.code == "duplicate_alias_in_group"]
        assert len(warnings) == 2
        # Lookup table should still resolve Dev to Developer
        assert vocab.resolve_role("dev") == "Developer"

    def test_warn_and_deduplicate_redundant_self_alias(self) -> None:
        roles = {
            "Developer": ["Developer", "Dev"]
        }
        vocab, issues = validate_vocabulary(roles, {})
        warnings = [i for i in issues if i.code == "redundant_self_alias"]
        assert len(warnings) == 1
        assert vocab.resolve_role("Developer") == "Developer"
        assert vocab.resolve_role("Dev") == "Developer"

    def test_reject_ambiguous_alias_across_groups(self) -> None:
        roles = {
            "Software Engineer": ["Developer"],
            "DevOps Engineer": ["Developer"]
        }
        vocab, issues = validate_vocabulary(roles, {})
        errors = [i for i in issues if i.code == "ambiguous_alias"]
        assert len(errors) == 1
        assert "Developer" in errors[0].message
        assert "Software Engineer" in errors[0].message
        assert "DevOps Engineer" in errors[0].message

    def test_reject_alias_chains(self) -> None:
        # A is alias of B, but B is declared as canonical in another group
        roles = {
            "Engineer": ["Coder"],
            "Software Engineer": ["Engineer"]
        }
        vocab, issues = validate_vocabulary(roles, {})
        errors = [i for i in issues if i.code == "alias_chain"]
        assert len(errors) >= 1

    def test_role_and_skill_namespace_isolation(self) -> None:
        # Same term in role and skill namespaces is permitted and does not collide
        roles = {
            "Python Developer": ["Python"]
        }
        skills = {
            "Python Programming": ["Python"]
        }
        vocab, issues = validate_vocabulary(roles, skills)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

        assert vocab.resolve_role("Python") == "Python Developer"
        assert vocab.resolve_skill("Python") == "Python Programming"

