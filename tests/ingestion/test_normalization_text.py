"""Tests for text, HTML, title, company, and URL cleaning (INGEST-02-S03)."""

from __future__ import annotations

import pytest

from job_automation.ingestion.normalization.text import (
    clean_company,
    clean_description,
    clean_html_to_text,
    clean_title,
    clean_url,
)


def test_clean_html_to_text_paragraphs_and_entities() -> None:
    """Paragraphs, lists, and HTML entities are cleaned into deterministic readable text."""
    raw_html = "<p>Planung &amp; Einkauf</p><ul><li>SAP</li><li>Excel</li></ul>"
    expected = "Planung & Einkauf\nSAP\nExcel"
    assert clean_html_to_text(raw_html) == expected


def test_clean_html_to_text_german_umlauts_and_gender_markers() -> None:
    """German letters, umlauts, and gender markers are preserved intact."""
    raw_html = (
        "<h3>Sachbearbeiter (m/w/d) für Vertrieb &amp; Einkauf</h3>\n"
        "<p>Standort: Köln / München. Größe: Großes Team.</p>"
    )
    cleaned = clean_html_to_text(raw_html)
    assert "Sachbearbeiter (m/w/d) für Vertrieb & Einkauf" in cleaned
    assert "Köln / München" in cleaned
    assert "Größe: Großes Team." in cleaned


def test_clean_html_discards_script_style_and_comments() -> None:
    """Non-content script, style, and comments are completely removed."""
    raw_html = (
        "<div>Header text</div>"
        "<script>alert('malicious');</script>"
        "<style>body { color: red; }</style>"
        "<!-- This is a comment -->"
        "<p>Footer content</p>"
    )
    cleaned = clean_html_to_text(raw_html)
    assert "alert" not in cleaned
    assert "color: red" not in cleaned
    assert "comment" not in cleaned
    assert "Header text" in cleaned
    assert "Footer content" in cleaned


def test_clean_html_inert_plain_text() -> None:
    """Plain-text symbols such as C++, C#, x < 5, and code snippets remain intact."""
    plain = "Experience with C++, C#, and conditions like x < 5 or SELECT * FROM jobs."
    cleaned = clean_html_to_text(plain)
    assert cleaned == plain


def test_clean_html_tolerates_malformed_unclosed_tags() -> None:
    """Unclosed or broken markup is recovered gracefully."""
    malformed = "<p>Unclosed paragraph<div>Nested <b>bold item without end"
    cleaned = clean_html_to_text(malformed)
    assert "Unclosed paragraph" in cleaned
    assert "Nested bold item without end" in cleaned


def test_clean_title_validation() -> None:
    """Title validates string type, trims whitespace, and flags empty or missing values."""
    # Valid
    title, issues = clean_title("  Senior Backend Engineer (m/w/d)  ")
    assert title == "Senior Backend Engineer (m/w/d)"
    assert not issues

    # Missing (None)
    title_none, issues_none = clean_title(None)
    assert title_none is None
    assert any(iss.code == "missing_required_field" for iss in issues_none)

    # Empty after cleaning
    title_empty, issues_empty = clean_title("   \n\t  ")
    assert title_empty is None
    assert any(iss.code == "empty_after_cleaning" for iss in issues_empty)

    # Wrong type (int/bool)
    title_int, issues_int = clean_title(12345)
    assert title_int is None
    assert any(iss.code == "invalid_field_type" for iss in issues_int)

    title_bool, issues_bool = clean_title(True)
    assert title_bool is None
    assert any(iss.code == "invalid_field_type" for iss in issues_bool)


def test_clean_company_validation() -> None:
    """Company hint validates string type and non-blank content."""
    # Valid
    comp, issues = clean_company("  Küche & Co GmbH  ")
    assert comp == "Küche & Co GmbH"
    assert not issues

    # Missing
    comp_none, issues_none = clean_company(None)
    assert comp_none is None
    assert any(iss.code == "missing_required_field" for iss in issues_none)

    # Empty
    comp_empty, issues_empty = clean_company("   ")
    assert comp_empty is None
    assert any(iss.code == "empty_after_cleaning" for iss in issues_empty)

    # Invalid type
    comp_type, issues_type = clean_company(["Invalid", "List"])
    assert comp_type is None
    assert any(iss.code == "invalid_field_type" for iss in issues_type)


def test_clean_description_validation() -> None:
    """Description verifies presence, cleans markup, and detects script-only emptiness."""
    # Valid
    desc, issues = clean_description("<p>Solid experience in Python.</p>")
    assert desc == "Solid experience in Python."
    assert not issues

    # Missing
    desc_none, issues_none = clean_description(None)
    assert desc_none is None
    assert any(iss.code == "missing_required_field" for iss in issues_none)

    # Script-only content -> empty after cleaning
    desc_script, issues_script = clean_description("<script>console.log('empty');</script>")
    assert desc_script is None
    assert any(iss.code == "empty_after_cleaning" for iss in issues_script)


def test_clean_url_validation() -> None:
    """URLs validate allowed schemes, reject unsafe schemes, and protect secrets in errors."""
    # Valid
    url, issues = clean_url("https://example.com/job/123?utm=tracking#apply")
    assert url == "https://example.com/job/123?utm=tracking#apply"
    assert not issues

    # Allowed optional URL missing
    app_url, app_issues = clean_url(None, field_name="application_url", required=False)
    assert app_url is None
    assert not app_issues

    # Required URL missing
    src_url, src_issues = clean_url(None, field_name="source_url", required=True)
    assert src_url is None
    assert any(iss.code == "missing_required_field" for iss in src_issues)

    # Invalid scheme (javascript:)
    js_url, js_issues = clean_url("javascript:alert(1)", field_name="source_url")
    assert js_url is None
    assert any(iss.code == "invalid_value" for iss in js_issues)

    # Secret in URL query is not echoed in issue message
    secret_url = "https://example.invalid/apply?token=SECRET_API_KEY_12345"
    bad_syntax = "not_a_valid_url?secret=SUPER_SECRET_TOKEN"
    bad_res, bad_issues = clean_url(bad_syntax, field_name="source_url")
    assert bad_res is None
    for iss in bad_issues:
        assert "SUPER_SECRET_TOKEN" not in iss.message

