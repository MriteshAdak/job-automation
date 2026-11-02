"""Conservative company entity identity resolution and alias management."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from job_automation.storage.repositories.identity import IdentityRepository

# Legal entity suffixes to strip for normalized matching
_LEGAL_SUFFIXES = [
    r"\bgmbh\s*&\s*co\.?\s*kg\b",
    r"\bco\.?\s*kg\b",
    r"\bhaftungsbeschr[äa]nkt\b",
    r"\bug\b",
    r"\bgmbh\b",
    r"\bag\b",
    r"\bkgaa\b",
    r"\bgbr\b",
    r"\bohg\b",
    r"\be\.?\s*k\.?\b",
    r"\bllc\b",
    r"\binc\.?\b",
    r"\bltd\.?\b",
    r"\bcorp\.?\b",
    r"\bplc\b",
    r"\bse\b",
    r"\bsa\b",
]

_SUFFIX_REGEX = re.compile(
    r"\s*(?:,|–|-)?\s*(?:" + "|".join(_LEGAL_SUFFIXES) + r")\.?\s*$",
    re.IGNORECASE,
)


def normalize_company_name(name: str) -> str:
    """Normalize employer name for conservative identity indexing.

    Strips legal form suffixes, punctuation, and extra whitespace, and lowercases.
    Preserves German umlauts and distinct substantive tokens.
    """
    if not name:
        return ""

    cleaned = name.strip()
    # Strip trailing legal forms iteratively
    for _ in range(2):
        cleaned = _SUFFIX_REGEX.sub("", cleaned).strip()

    # Remove non-alphanumeric except spaces, ampersands, and hyphens
    cleaned = re.sub(r"[^\w\s&\-äöüÄÖÜß]", "", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def resolve_company_identity(
    company_name_hint: str,
    company_id_hint: str | None,
    provider: str,
    board_id: str,
    identity_repo: IdentityRepository | None = None,
) -> tuple[uuid.UUID, str]:
    """Conservatively resolve or register a company identity.

    Returns (canonical_company_id, display_name).
    """
    clean_name = company_name_hint.strip()
    norm_name = normalize_company_name(clean_name)

    if identity_repo is None:
        # In-memory fallback
        return uuid.uuid4(), clean_name

    # 1. Check provider-scoped company ID if present
    if company_id_hint:
        namespace = f"{provider}:{board_id}"
        alias_key = str(company_id_hint).strip()
        existing_id = identity_repo.find_company_by_alias(namespace, alias_key)
        if existing_id:
            return existing_id, clean_name

    # 2. Check exact normalized name
    if norm_name:
        existing_company = identity_repo.find_company_by_name(norm_name)
        if existing_company:
            comp_id = uuid.UUID(existing_company["company_id"])
            # If provider company ID is present, associate it as an alias
            if company_id_hint:
                namespace = f"{provider}:{board_id}"
                alias_key = str(company_id_hint).strip()
                identity_repo.save_company_alias(comp_id, namespace, alias_key)
            return comp_id, clean_name

    # 3. Register new company entity
    comp_id = uuid.uuid4()
    identity_repo.save_company(comp_id, canonical_name=clean_name, normalized_name=norm_name)

    if company_id_hint:
        namespace = f"{provider}:{board_id}"
        alias_key = str(company_id_hint).strip()
        identity_repo.save_company_alias(comp_id, namespace, alias_key)

    return comp_id, clean_name

