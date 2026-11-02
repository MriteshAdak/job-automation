"""German and English vocabulary normalization and alias validation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from job_automation.contracts.errors import ValidationIssue


def normalize_display(text: str) -> str:
    """Normalize display text: Unicode NFC, stripped, internal whitespace collapsed.
    
    Preserves case and distinctive punctuation like 'C++', 'C#', '.NET'.
    """
    nfc = unicodedata.normalize("NFC", text)
    stripped = nfc.strip()
    return re.sub(r"\s+", " ", stripped)


def normalize_lookup(text: str) -> str:
    """Normalize text for case-insensitive equivalence matching.
    
    Uses Unicode NFC, stripped, collapsed whitespace, and casefold.
    """
    disp = normalize_display(text)
    return disp.casefold()


@dataclass(frozen=True)
class VocabularyGroup:
    """A canonical term and its declared aliases with normalized lookups."""

    canonical_display: str
    canonical_lookup: str
    aliases_display: tuple[str, ...]
    aliases_lookup: tuple[str, ...]


@dataclass
class NormalizedVocabulary:
    """Two-namespace vocabulary index providing deterministic term resolution."""

    role_groups: dict[str, VocabularyGroup] = field(default_factory=dict)
    skill_groups: dict[str, VocabularyGroup] = field(default_factory=dict)
    role_lookup: dict[str, str] = field(default_factory=dict)
    skill_lookup: dict[str, str] = field(default_factory=dict)

    def resolve_role(self, term: str) -> str | None:
        """Resolve a role term or alias to its canonical display name, or None."""
        k = normalize_lookup(term)
        return self.role_lookup.get(k)

    def resolve_skill(self, term: str) -> str | None:
        """Resolve a skill term or alias to its canonical display name, or None."""
        k = normalize_lookup(term)
        return self.skill_lookup.get(k)

    def are_roles_equivalent(self, term1: str, term2: str) -> bool:
        """Return True if both role terms resolve to the same canonical role."""
        r1 = self.resolve_role(term1)
        r2 = self.resolve_role(term2)
        if r1 is not None and r2 is not None:
            return r1 == r2
        return normalize_lookup(term1) == normalize_lookup(term2)

    def are_skills_equivalent(self, term1: str, term2: str) -> bool:
        """Return True if both skill terms resolve to the same canonical skill."""
        s1 = self.resolve_skill(term1)
        s2 = self.resolve_skill(term2)
        if s1 is not None and s2 is not None:
            return s1 == s2
        return normalize_lookup(term1) == normalize_lookup(term2)


def validate_alias_mapping(
    alias_dict: dict[str, list[str]],
    namespace: str,
) -> tuple[dict[str, VocabularyGroup], dict[str, str], list[ValidationIssue]]:
    """Validate a single alias dictionary (roles or skills) and build lookup tables.
    
    Detects:
    - Blank canonical terms or aliases (errors)
    - Duplicate canonical terms after normalization (error)
    - Ambiguous aliases mapped across multiple canonical groups (error)
    - Alias chains (canonical term declared as alias elsewhere) (error)
    - Duplicate aliases within the same group (warning + deduplication)
    - Self-aliases identical to canonical term (warning + deduplication)
    """
    issues: list[ValidationIssue] = []
    groups: dict[str, VocabularyGroup] = {}
    lookup: dict[str, str] = {}
    # Track where each alias was first declared: normalized_alias -> (canonical_display, path)
    alias_declarations: dict[str, tuple[str, str]] = {}
    # Track canonical lookups to canonical display
    canonical_declarations: dict[str, str] = {}

    for raw_canonical, raw_aliases in alias_dict.items():
        canonical_disp = normalize_display(raw_canonical)
        if not canonical_disp:
            issues.append(
                ValidationIssue(
                    field_path=f"{namespace}['{raw_canonical}']",
                    code="empty_canonical_term",
                    message=f"Canonical {namespace[:-1]} name cannot be empty or whitespace only",
                    severity="error",
                )
            )
            continue

        canonical_lk = normalize_lookup(raw_canonical)
        if canonical_lk in canonical_declarations:
            existing = canonical_declarations[canonical_lk]
            issues.append(
                ValidationIssue(
                    field_path=f"{namespace}['{raw_canonical}']",
                    code="duplicate_canonical_term",
                    message=(
                        f"Canonical {namespace[:-1]} '{canonical_disp}' collides with "
                        f"existing canonical term '{existing}' under normalization"
                    ),
                    severity="error",
                )
            )
            continue
        canonical_declarations[canonical_lk] = canonical_disp

    # Second pass: validate aliases for each valid canonical group
    for raw_canonical, raw_aliases in alias_dict.items():
        canonical_disp = normalize_display(raw_canonical)
        canonical_lk = normalize_lookup(raw_canonical)
        if not canonical_disp or canonical_lk not in canonical_declarations:
            continue

        valid_aliases_disp: list[str] = []
        valid_aliases_lk: list[str] = []
        seen_in_group: set[str] = set()

        # Canonical term always maps to itself in lookup
        lookup[canonical_lk] = canonical_disp

        for idx, raw_alias in enumerate(raw_aliases):
            path = f"{namespace}['{raw_canonical}'][{idx}]"
            alias_disp = normalize_display(raw_alias)
            if not alias_disp:
                issues.append(
                    ValidationIssue(
                        field_path=path,
                        code="empty_alias",
                        message=f"Alias for '{canonical_disp}' cannot be empty or whitespace only",
                        severity="error",
                    )
                )
                continue

            alias_lk = normalize_lookup(raw_alias)

            # Redundant self-alias check
            if alias_lk == canonical_lk:
                issues.append(
                    ValidationIssue(
                        field_path=path,
                        code="redundant_self_alias",
                        message=(
                            f"Alias '{alias_disp}' in group '{canonical_disp}' is identical "
                            f"to the canonical term; canonical terms resolve to themselves by default"
                        ),
                        severity="warning",
                    )
                )
                continue

            # In-group duplicate check
            if alias_lk in seen_in_group:
                issues.append(
                    ValidationIssue(
                        field_path=path,
                        code="duplicate_alias_in_group",
                        message=(
                            f"Duplicate alias '{alias_disp}' in group '{canonical_disp}' "
                            f"will be deduplicated"
                        ),
                        severity="warning",
                    )
                )
                continue
            seen_in_group.add(alias_lk)

            # Cross-group ambiguity check
            if alias_lk in alias_declarations:
                other_canonical, other_path = alias_declarations[alias_lk]
                if other_canonical != canonical_disp:
                    issues.append(
                        ValidationIssue(
                            field_path=path,
                            code="ambiguous_alias",
                            message=(
                                f"Alias '{alias_disp}' is ambiguously assigned to both "
                                f"'{other_canonical}' (at {other_path}) and '{canonical_disp}'"
                            ),
                            severity="error",
                        )
                    )
                    continue

            # Alias chain check: alias is also a canonical term in another group
            if alias_lk in canonical_declarations and alias_lk != canonical_lk:
                other_canonical = canonical_declarations[alias_lk]
                issues.append(
                    ValidationIssue(
                        field_path=path,
                        code="alias_chain",
                        message=(
                            f"Alias '{alias_disp}' in '{canonical_disp}' is already declared as "
                            f"canonical term '{other_canonical}'; transitive alias chains are forbidden"
                        ),
                        severity="error",
                    )
                )
                continue

            alias_declarations[alias_lk] = (canonical_disp, path)
            valid_aliases_disp.append(alias_disp)
            valid_aliases_lk.append(alias_lk)
            lookup[alias_lk] = canonical_disp

        groups[canonical_disp] = VocabularyGroup(
            canonical_display=canonical_disp,
            canonical_lookup=canonical_lk,
            aliases_display=tuple(valid_aliases_disp),
            aliases_lookup=tuple(valid_aliases_lk),
        )

    # Check reverse alias chain: canonical term declared as an alias in another group
    for canonical_lk, canonical_disp in canonical_declarations.items():
        if canonical_lk in alias_declarations:
            other_canonical, other_path = alias_declarations[canonical_lk]
            issues.append(
                ValidationIssue(
                    field_path=f"{namespace}['{canonical_disp}']",
                    code="alias_chain",
                    message=(
                        f"Canonical term '{canonical_disp}' was also declared as an alias for "
                        f"'{other_canonical}' at {other_path}; transitive alias chains are forbidden"
                    ),
                    severity="error",
                )
            )

    return groups, lookup, issues


def validate_vocabulary(
    role_aliases: dict[str, list[str]],
    skill_aliases: dict[str, list[str]],
) -> tuple[NormalizedVocabulary, list[ValidationIssue]]:
    """Validate both role and skill alias namespaces and return NormalizedVocabulary."""
    role_groups, role_lookup, role_issues = validate_alias_mapping(role_aliases, "role_aliases")
    skill_groups, skill_lookup, skill_issues = validate_alias_mapping(skill_aliases, "skill_aliases")

    vocab = NormalizedVocabulary(
        role_groups=role_groups,
        skill_groups=skill_groups,
        role_lookup=role_lookup,
        skill_lookup=skill_lookup,
    )
    all_issues = role_issues + skill_issues
    return vocab, all_issues

