"""Text, title, company, URL, and HTML cleaning (INGEST-02).

Normalizes untrusted markup into deterministic, inert plain text:
- Decodes HTML entities once without re-parsing unescaped markup.
- Discards non-content script, style, and comments completely.
- Preserves paragraph/list/table-cell structure and readable whitespace.
- Normalizes CRLF/CR to LF and collapses multiple blank lines.
- Leaves plain-text characters (C++, C#, x < 5, SQL) intact without alteration.
- Validates URL syntax and allowed schemes (http, https) safely.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any

from job_automation.contracts.errors import ValidationIssue

# Block-level HTML elements that produce vertical whitespace
BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ul",
        "ol",
        "blockquote",
        "section",
        "article",
        "header",
        "footer",
        "table",
        "tr",
        "pre",
        "hr",
    }
)

# Inline elements where tags are stripped without adding whitespace
INLINE_TAGS = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "span",
        "a",
        "code",
        "small",
        "sub",
        "sup",
        "mark",
    }
)

# Elements whose entire subtree should be discarded
IGNORE_TAGS = frozenset({"script", "style", "noscript", "svg"})


class _TextExtractingParser(HTMLParser):
    """HTML parser extracting readable plain text and discarding scripts/styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.pieces: list[str] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low_tag = tag.lower()
        if low_tag in IGNORE_TAGS:
            self._ignore_depth += 1
            return
        if self._ignore_depth > 0:
            return

        if low_tag in BLOCK_TAGS:
            self._ensure_newline()
        elif low_tag == "br":
            self.pieces.append("\n")
        elif low_tag in ("td", "th"):
            if self.pieces and not self.pieces[-1].endswith((" ", "\t", "\n")):
                self.pieces.append("\t")

    def handle_endtag(self, tag: str) -> None:
        low_tag = tag.lower()
        if low_tag in IGNORE_TAGS:
            if self._ignore_depth > 0:
                self._ignore_depth -= 1
            return
        if self._ignore_depth > 0:
            return

        if low_tag in BLOCK_TAGS:
            self._ensure_newline()

    def handle_data(self, data: str) -> None:
        if self._ignore_depth > 0:
            return
        self.pieces.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._ignore_depth > 0:
            return
        # Decode named entity once
        char = html.unescape(f"&{name};")
        self.pieces.append(char)

    def handle_charref(self, name: str) -> None:
        if self._ignore_depth > 0:
            return
        # Decode numeric charref once
        char = html.unescape(f"&#{name};")
        self.pieces.append(char)

    def handle_comment(self, data: str) -> None:
        # Ignore comments
        pass

    def _ensure_newline(self) -> None:
        if self.pieces and not self.pieces[-1].endswith("\n"):
            self.pieces.append("\n")


def clean_html_to_text(html_content: str) -> str:
    """Convert HTML markup or plain text into clean, deterministic plain text.

    Decodes entities once, preserves block and list structures, strips script/style
    elements, and normalizes line endings and whitespace.
    """
    if not html_content:
        return ""

    # Normalize CRLF and CR to LF first
    text = html_content.replace("\r\n", "\n").replace("\r", "\n")

    parser = _TextExtractingParser()
    try:
        parser.feed(text)
        parser.close()
        extracted = "".join(parser.pieces)
    except Exception:
        # Fallback to regex-based tag strip if malformed markup crashes parser
        no_scripts = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
        no_tags = re.sub(r"<[^>]+>", " ", no_scripts)
        extracted = html.unescape(no_tags)

    # Post-process lines: strip trailing whitespace and collapse consecutive empty lines
    lines = [line.rstrip() for line in extracted.split("\n")]

    # Collapse consecutive blank lines (max 1 blank line between text)
    collapsed: list[str] = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 1 and collapsed:
                collapsed.append("")
        else:
            blank_count = 0
            collapsed.append(line.strip())

    result = "\n".join(collapsed).strip()
    return result


def clean_title(raw_title: Any) -> tuple[str | None, list[ValidationIssue]]:
    """Clean and validate a job title string.

    Returns:
        (clean_title, issues)
    """
    if raw_title is None:
        return None, [
            ValidationIssue(
                field_path="title",
                code="missing_required_field",
                message="Job title is required and cannot be null",
                severity="error",
            )
        ]

    if isinstance(raw_title, bool) or not isinstance(raw_title, str):
        return None, [
            ValidationIssue(
                field_path="title",
                code="invalid_field_type",
                message=f"Job title must be a string, got {type(raw_title).__name__}",
                severity="error",
            )
        ]

    cleaned = raw_title.strip()
    if not cleaned:
        return None, [
            ValidationIssue(
                field_path="title",
                code="empty_after_cleaning",
                message="Job title cannot be empty or blank whitespace",
                severity="error",
            )
        ]

    return cleaned, []


def clean_company(raw_company: Any) -> tuple[str | None, list[ValidationIssue]]:
    """Clean and validate a company name hint.

    Returns:
        (clean_company, issues)
    """
    if raw_company is None:
        return None, [
            ValidationIssue(
                field_path="company_name_hint",
                code="missing_required_field",
                message="Company name hint is required and cannot be null",
                severity="error",
            )
        ]

    if isinstance(raw_company, bool) or not isinstance(raw_company, str):
        return None, [
            ValidationIssue(
                field_path="company_name_hint",
                code="invalid_field_type",
                message=f"Company name must be a string, got {type(raw_company).__name__}",
                severity="error",
            )
        ]

    cleaned = raw_company.strip()
    if not cleaned:
        return None, [
            ValidationIssue(
                field_path="company_name_hint",
                code="empty_after_cleaning",
                message="Company name cannot be empty or blank whitespace",
                severity="error",
            )
        ]

    return cleaned, []


def clean_description(raw_desc: Any) -> tuple[str | None, list[ValidationIssue]]:
    """Clean and validate job description text/HTML.

    Returns:
        (description_clean, issues)
    """
    if raw_desc is None:
        return None, [
            ValidationIssue(
                field_path="description_clean",
                code="missing_required_field",
                message="Job description is required and cannot be null",
                severity="error",
            )
        ]

    if isinstance(raw_desc, bool) or not isinstance(raw_desc, str):
        return None, [
            ValidationIssue(
                field_path="description_clean",
                code="invalid_field_type",
                message=f"Job description must be a string, got {type(raw_desc).__name__}",
                severity="error",
            )
        ]

    cleaned = clean_html_to_text(raw_desc)
    if not cleaned:
        return None, [
            ValidationIssue(
                field_path="description_clean",
                code="empty_after_cleaning",
                message="Job description is empty after HTML/whitespace cleaning",
                severity="error",
            )
        ]

    return cleaned, []


def clean_url(
    raw_url: Any,
    field_name: str = "source_url",
    required: bool = True,
) -> tuple[str | None, list[ValidationIssue]]:
    """Validate and clean a source or application URL.

    Checks allowed schemes (http, https) and non-empty netloc while preserving
    valid query parameters and fragments. Does not echo secrets in error messages.
    """
    if raw_url is None:
        if required:
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="missing_required_field",
                    message=f"Required URL '{field_name}' is missing",
                    severity="error",
                )
            ]
        return None, []

    if isinstance(raw_url, bool) or not isinstance(raw_url, str):
        return None, [
            ValidationIssue(
                field_path=field_name,
                code="invalid_field_type",
                message=f"URL '{field_name}' must be a string, got {type(raw_url).__name__}",
                severity="error",
            )
        ]

    trimmed = raw_url.strip()
    if not trimmed:
        if required:
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="empty_after_cleaning",
                    message=f"URL '{field_name}' cannot be empty or whitespace",
                    severity="error",
                )
            ]
        return None, []

    try:
        parsed = urllib.parse.urlparse(trimmed)
        if parsed.scheme.lower() not in ("http", "https"):
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="invalid_value",
                    message=f"URL '{field_name}' must use http or https scheme",
                    severity="error",
                )
            ]
        if not parsed.netloc:
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="invalid_value",
                    message=f"URL '{field_name}' is missing a valid host / network location",
                    severity="error",
                )
            ]
    except Exception:
        return None, [
            ValidationIssue(
                field_path=field_name,
                code="invalid_value",
                message=f"URL '{field_name}' failed syntactic validation",
                severity="error",
            )
        ]

    return trimmed, []

