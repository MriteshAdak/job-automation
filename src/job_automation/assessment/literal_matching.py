"""Unicode-aware literal token and phrase matching for keywords and aliases."""

from __future__ import annotations

import re
import unicodedata

from job_automation.policy.vocabulary import normalize_display, normalize_lookup


def build_safe_token_pattern(query: str) -> re.Pattern[str]:
    """Compile a regex pattern for query respecting word and punctuation boundaries.

    Ensures terms like 'Java' do not match inside 'JavaScript', 'Go' does not match
    inside 'ongoing', while safely matching terms with symbols like 'C++', 'C#', and '.NET'.
    """
    escaped = re.escape(query.strip())
    if not escaped:
        return re.compile(r"(?!)")  # Never matches empty pattern

    # Lookbehind: if query starts with a word character, require boundary or start
    first_char = query.strip()[0]
    if re.match(r"\w", first_char):
        prefix = r"(?<!\w)"
    else:
        prefix = r"(?<!\S)"

    # Lookahead: if query ends with a word character, require boundary or end
    last_char = query.strip()[-1]
    if re.match(r"\w", last_char):
        suffix = r"(?!\w)"
    elif last_char in {"+", "#"}:
        # Avoid matching 'C+' when searching for 'C' or 'C+++' when searching for 'C++'
        suffix = r"(?![+#\w])"
    else:
        suffix = r"(?!\S)"

    pattern_str = f"{prefix}{escaped}{suffix}"
    return re.compile(pattern_str, re.IGNORECASE)


def find_literal_matches(text: str, query: str) -> list[tuple[int, int, str]]:
    """Find all occurrences of query in text with boundary checks.

    Returns:
        list of (start, end, matched_text) spans in the original text.
    """
    if not text or not query or not query.strip():
        return []

    # Normalize unicode to NFC for reliable character indices
    nfc_text = unicodedata.normalize("NFC", text)
    pattern = build_safe_token_pattern(query)

    matches: list[tuple[int, int, str]] = []
    for m in pattern.finditer(nfc_text):
        matches.append((m.start(), m.end(), m.group(0)))

    return matches


def contains_literal_phrase(text: str, query: str) -> bool:
    """Check if query exists as a distinct token or phrase in text."""
    return bool(find_literal_matches(text, query))


def match_any_phrase(text: str, queries: list[str]) -> list[tuple[str, int, int, str]]:
    """Match any of the queries against text.

    Returns:
        list of (query, start, end, matched_text)
    """
    results: list[tuple[str, int, int, str]] = []
    for q in queries:
        for start, end, matched in find_literal_matches(text, q):
            results.append((q, start, end, matched))
    return results

