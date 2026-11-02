"""Source-backed job requirement preparation and query derivation (MATCH-02-S02).

Prepares structured and passage-based job requirements before context selection,
ensuring queries have traceable job source citations and preserving:
- Original obligation (required, preferred, unclear)
- Negation ("no degree required" -> not mandatory)
- Alternatives ("degree or equivalent experience")
- Units and thresholds ("5 years")
- Advert language does not synthesize a language proficiency requirement.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Literal

from job_automation.assessment.llm_records import (
    RequirementCategory,
    RequirementItem,
    RequirementIssue,
    RequirementObligation,
    RequirementSet,
)
from job_automation.assessment.requirement_prompts import (
    EXTRACTION_SYSTEM_INSTRUCTION,
    ExtractedRequirementPayload,
    render_extraction_prompt,
)
from job_automation.assessment.requirement_validation import validate_requirement_item
from job_automation.context.keyword_index import KeywordAnalyzer
from job_automation.context.selector_records import RequirementQuery, RequirementQuerySet
from job_automation.contracts.evidence import JobEvidenceReference, SourceSpan
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.models import ModelCall
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.models.fingerprints import compute_generation_fingerprint
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.records import BoundGenerationInput

_KEYWORD_ANALYZER = KeywordAnalyzer()

# Section header patterns
_PERKS_HEADERS = re.compile(
    r"(?i)^(?:\s*[-*•]?\s*)(?:was wir bieten|wir bieten|what we offer|benefits|perks|unser angebot|das bieten wir)[:\s]*$"
)
_REQUIREMENTS_HEADERS = re.compile(
    r"(?i)^(?:\s*[-*•]?\s*)(?:anforderungen|qualifikationen|ihr profil|dein profil|das bringst du mit|das bringen sie mit|what you bring|your profile|requirements|qualifications|must-haves?)[:\s]*$"
)
_PREFERRED_HEADERS = re.compile(
    r"(?i)^(?:\s*[-*•]?\s*)(?:wünschenswert|von vorteil|nice to have|nice-to-have|idealerweise|optional|preferred qualifications?)[:\s]*$"
)

# Negation patterns
_NEGATION_PATTERNS = re.compile(
    r"(?i)\b(?:keine?\s+\w+\s+erforderlich|nicht\s+erforderlich|nicht\s+zwingend|kein\s+muss|no\s+\w+\s+required|not\s+required|not\s+mandatory|neither\b.*?\bnor)\b"
)

# Obligation patterns
_PREFERRED_PATTERNS = re.compile(
    r"(?i)\b(?:wünschenswert|von vorteil|vorteilhaft|idealerweise|plus|optional|nice to have|nice-to-have|preferred|desirable|advantage)\b"
)
_REQUIRED_PATTERNS = re.compile(
    r"(?i)\b(?:erforderlich|voraussetzung|muss|zwingend|mindestens|notwendig|required|must|essential|mandatory|at least|minimum)\b"
)

# Threshold and units
_THRESHOLD_PATTERN = re.compile(r"(\d+)\+?\s*(?:jahre|jahren|years|year)", re.IGNORECASE)

# Alternatives
_ALTERNATIVE_PATTERN = re.compile(r"\b(?:oder|or|bzw\.)\b", re.IGNORECASE)

# Category patterns
_EDUCATION_PATTERN = re.compile(
    r"(?i)\b(?:abschluss|studium|bachelor|master|diplom|phd|doktor|ausbildung|degree|university)\b"
)
_EXPERIENCE_PATTERN = re.compile(
    r"(?i)\b(?:berufserfahrung|erfahrung|experience|senior|junior|lead|jahre|years)\b"
)
_LANGUAGE_PATTERN = re.compile(
    r"(?i)\b(?:deutsch|englisch|german|english|französisch|french|spanisch|spanish|c1|c2|b1|b2|fließend|fluent|sprachkenntnisse)\b"
)
_CERTIFICATION_PATTERN = re.compile(
    r"(?i)\b(?:zertifikat|zertifizierung|certified|certification|aws|azure|gcp|pmp|scrum)\b"
)


def _compute_requirement_set_fingerprint(
    requirements: list[RequirementItem],
    canonical_job_id: uuid.UUID,
    job_revision: str,
) -> str:
    """Compute deterministic SHA-256 fingerprint over an ordered requirement set."""
    items_data = []
    for r in requirements:
        span_data = None
        if r.job_evidence.source_span is not None:
            span_data = {
                "start": r.job_evidence.source_span.start,
                "end": r.job_evidence.source_span.end,
            }
        items_data.append(
            {
                "requirement_id": r.requirement_id,
                "text": r.text,
                "obligation": str(r.obligation),
                "category": str(r.category),
                "field_path": r.job_evidence.field_path,
                "quotation": r.job_evidence.quotation,
                "source_span": span_data,
                "qualifiers": sorted(r.qualifiers),
                "alternatives": sorted(r.alternatives),
                "threshold": r.threshold,
                "unit": r.unit,
            }
        )

    payload = {
        "canonical_job_id": str(canonical_job_id),
        "job_revision": job_revision,
        "requirements": items_data,
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"


def _detect_obligation(
    passage: str,
    section: str,
) -> RequirementObligation:
    """Determine requirement obligation level preserving negation and section context."""
    # Check negation first: "no degree required" -> PREFERRED / not required
    if _NEGATION_PATTERNS.search(passage):
        return RequirementObligation.PREFERRED

    # Check explicit preferred keywords
    if _PREFERRED_PATTERNS.search(passage):
        return RequirementObligation.PREFERRED

    # Check explicit required keywords
    if _REQUIRED_PATTERNS.search(passage):
        return RequirementObligation.REQUIRED

    # Check section context
    if section == "preferred":
        return RequirementObligation.PREFERRED
    if section == "requirements":
        return RequirementObligation.REQUIRED

    return RequirementObligation.REQUIRED


def _detect_category(passage: str) -> RequirementCategory:
    """Categorize requirement based on semantic tokens."""
    if _EDUCATION_PATTERN.search(passage):
        return RequirementCategory.EDUCATION
    if _EXPERIENCE_PATTERN.search(passage):
        return RequirementCategory.EXPERIENCE
    if _LANGUAGE_PATTERN.search(passage):
        return RequirementCategory.LANGUAGE
    if _CERTIFICATION_PATTERN.search(passage):
        return RequirementCategory.CERTIFICATION
    return RequirementCategory.SKILL


def _extract_alternatives(passage: str) -> list[str]:
    """Extract alternative options from a requirement if present."""
    parts = _ALTERNATIVE_PATTERN.split(passage)
    if len(parts) > 1:
        cleaned = [p.strip() for p in parts if len(p.strip()) > 3]
        if len(cleaned) > 1:
            return cleaned
    return []


def _extract_threshold_and_unit(passage: str) -> tuple[str | None, str | None]:
    """Extract numeric threshold and unit (e.g. 5 years) if present."""
    m = _THRESHOLD_PATTERN.search(passage)
    if m:
        return m.group(1), "years"
    return None, None


def prepare_deterministic_requirements(
    posting: NormalizedPosting,
    posting_revision: str,
    canonical_job_id: uuid.UUID,
    policy: SearchPolicy | None = None,
    max_requirements: int = 20,
) -> RequirementSet:
    """Deterministically extract source-backed job requirements from posting fields.

    Extracts:
    1. Title as primary role qualification
    2. Description passages and bullet points with exact Unicode character offsets
    3. Proper obligation, negation, alternatives, thresholds, and categories
    """
    desc = posting.description_clean or ""
    issues: list[RequirementIssue] = []

    if not desc.strip() and not posting.title.strip():
        issues.append(
            RequirementIssue(
                code="empty_job_source",
                stage="requirement_preparation",
                message="Posting has empty title and description; zero requirements extracted",
                severity="warning",
            )
        )
        return RequirementSet(
            recipe_version="v1",
            canonical_job_id=canonical_job_id,
            job_revision=posting_revision,
            requirements=[],
            issues=issues,
            fingerprint=f"sha256:{hashlib.sha256(b'empty').hexdigest()}",
            extractor_version="v1-deterministic",
        )

    requirements: list[RequirementItem] = []
    req_index = 0

    # 1. Title requirement
    if posting.title and posting.title.strip():
        title_text = posting.title.strip()
        job_ev = JobEvidenceReference(
            posting_revision=posting_revision,
            field_path="title",
            quotation=title_text,
            source_span=SourceSpan(start=0, end=len(posting.title)),
        )
        requirements.append(
            RequirementItem(
                requirement_id=f"req_{req_index}",
                text=f"Role: {title_text}",
                obligation=RequirementObligation.REQUIRED,
                category=RequirementCategory.EXPERIENCE,
                job_evidence=job_ev,
            )
        )
        req_index += 1

    # 2. Description passage extraction
    current_section = "general"  # 'general', 'requirements', 'preferred', 'benefits'

    for match in re.finditer(r"[^\r\n]+", desc):
        if len(requirements) >= max_requirements:
            break

        raw_line = match.group(0)
        start = match.start()
        end = match.end()

        stripped = raw_line.strip()
        if not stripped:
            continue

        # Check for section headers
        if _PERKS_HEADERS.match(stripped):
            current_section = "benefits"
            continue
        if _REQUIREMENTS_HEADERS.match(stripped):
            current_section = "requirements"
            continue
        if _PREFERRED_HEADERS.match(stripped):
            current_section = "preferred"
            continue

        # Skip perks and benefits section
        if current_section == "benefits":
            continue

        # Strip bullet points and adjust start/end to exact substring in description
        bullet_match = re.match(r"^(\s*[-*•]\s*|\s*\d+\.\s*)", raw_line)
        if bullet_match:
            bullet_len = len(bullet_match.group(0))
            start += bullet_len
            raw_line = raw_line[bullet_len:]

        # Strip trailing whitespace
        trailing_ws = len(raw_line) - len(raw_line.rstrip())
        end -= trailing_ws
        quote = desc[start:end]

        if len(quote) < 8:
            continue

        # Detect properties
        obligation = _detect_obligation(quote, current_section)
        category = _detect_category(quote)
        alternatives = _extract_alternatives(quote)
        threshold, unit = _extract_threshold_and_unit(quote)

        job_ev = JobEvidenceReference(
            posting_revision=posting_revision,
            field_path="description_clean",
            quotation=quote,
            source_span=SourceSpan(start=start, end=end),
        )

        requirements.append(
            RequirementItem(
                requirement_id=f"req_{req_index}",
                text=quote,
                obligation=obligation,
                category=category,
                job_evidence=job_ev,
                alternatives=alternatives,
                threshold=threshold,
                unit=unit,
            )
        )
        req_index += 1

    fingerprint = _compute_requirement_set_fingerprint(
        requirements=requirements,
        canonical_job_id=canonical_job_id,
        job_revision=posting_revision,
    )

    req_set = RequirementSet(
        recipe_version="v1",
        canonical_job_id=canonical_job_id,
        job_revision=posting_revision,
        requirements=requirements,
        issues=issues,
        fingerprint=fingerprint,
        extractor_version="v1-deterministic",
    )

    return req_set


def prepare_llm_requirements(
    posting: NormalizedPosting,
    posting_revision: str,
    canonical_job_id: uuid.UUID,
    model_provider: ModelProvider,
    input_resolver: InMemoryInputResolver,
    model_identifier: str = "local-assessor",
    max_requirements: int = 20,
) -> RequirementSet:
    """Prepare requirements using LLM extraction on job text only (no candidate context)."""
    desc = posting.description_clean or ""
    if not desc.strip():
        return prepare_deterministic_requirements(
            posting=posting,
            posting_revision=posting_revision,
            canonical_job_id=canonical_job_id,
            max_requirements=max_requirements,
        )

    call_id = uuid.uuid4()
    prompt = render_extraction_prompt(desc)
    system_instruction = EXTRACTION_SYSTEM_INSTRUCTION

    # Register/bind generation input
    bound_input = input_resolver.bind_generation(
        call_id=call_id,
        prompt=prompt,
        system_prompt=system_instruction,
        metadata={"schema_name": "requirement_extraction"},
    )

    call = ModelCall(
        call_id=call_id,
        operation_type="requirement_extraction",
        model_identifier=model_identifier,
        prompt_version="v1",
        requested_schema="requirement_extraction",
        input_fingerprint=bound_input.input_fingerprint,
        context_limit=4096,
    )

    result = model_provider.generate(call)
    issues: list[RequirementIssue] = []

    if result.error is not None or result.parsed_output is None:
        issues.append(
            RequirementIssue(
                code="extraction_call_failed",
                stage="requirement_extraction",
                message=result.error.message if result.error else "Model failed to produce parsed output",
                severity="warning",
            )
        )
        # Fallback to deterministic extraction
        fallback_set = prepare_deterministic_requirements(
            posting=posting,
            posting_revision=posting_revision,
            canonical_job_id=canonical_job_id,
            max_requirements=max_requirements,
        )
        return RequirementSet(
            recipe_version=fallback_set.recipe_version,
            canonical_job_id=fallback_set.canonical_job_id,
            job_revision=fallback_set.job_revision,
            requirements=fallback_set.requirements,
            issues=issues + fallback_set.issues,
            fingerprint=fallback_set.fingerprint,
            extractor_version="v1-llm-fallback",
        )

    # Parse extracted items
    parsed = result.parsed_output
    raw_reqs = parsed.get("requirements", [])
    requirements: list[RequirementItem] = []

    for i, item_data in enumerate(raw_reqs[:max_requirements]):
        req_id = f"req_{i}"
        quote = item_data.get("quotation", "")
        start = item_data.get("start", 0)
        end = item_data.get("end", len(quote))
        text = item_data.get("text", quote)
        ob_str = item_data.get("obligation", "required")
        cat_str = item_data.get("category", "other")

        try:
            ob = RequirementObligation(ob_str)
        except ValueError:
            ob = RequirementObligation.REQUIRED

        try:
            cat = RequirementCategory(cat_str)
        except ValueError:
            cat = RequirementCategory.OTHER

        span = None
        if end > start and start >= 0:
            span = SourceSpan(start=start, end=end)

        job_ev = JobEvidenceReference(
            posting_revision=posting_revision,
            field_path="description_clean",
            quotation=quote,
            source_span=span,
        )

        item = RequirementItem(
            requirement_id=req_id,
            text=text,
            obligation=ob,
            category=cat,
            job_evidence=job_ev,
            qualifiers=item_data.get("qualifiers", []),
            alternatives=item_data.get("alternatives", []),
            threshold=item_data.get("threshold"),
            unit=item_data.get("unit"),
        )

        # Validate item citations against source posting
        item_issues = validate_requirement_item(item, posting, posting_revision)
        issues.extend(item_issues)
        requirements.append(item)

    fingerprint = _compute_requirement_set_fingerprint(
        requirements=requirements,
        canonical_job_id=canonical_job_id,
        job_revision=posting_revision,
    )

    return RequirementSet(
        recipe_version="v1",
        canonical_job_id=canonical_job_id,
        job_revision=posting_revision,
        requirements=requirements,
        issues=issues,
        fingerprint=fingerprint,
        extractor_version="v1-llm",
    )


def prepare_requirements(
    posting: NormalizedPosting,
    posting_revision: str,
    canonical_job_id: uuid.UUID,
    policy: SearchPolicy | None = None,
    max_requirements: int = 20,
    mode: Literal["deterministic", "llm"] = "deterministic",
    model_provider: ModelProvider | None = None,
    input_resolver: InMemoryInputResolver | None = None,
    model_identifier: str = "local-assessor",
) -> RequirementSet:
    """Unified entry point for preparing job requirements before context selection."""
    if mode == "llm" and model_provider is not None and input_resolver is not None:
        return prepare_llm_requirements(
            posting=posting,
            posting_revision=posting_revision,
            canonical_job_id=canonical_job_id,
            model_provider=model_provider,
            input_resolver=input_resolver,
            model_identifier=model_identifier,
            max_requirements=max_requirements,
        )
    return prepare_deterministic_requirements(
        posting=posting,
        posting_revision=posting_revision,
        canonical_job_id=canonical_job_id,
        policy=policy,
        max_requirements=max_requirements,
    )


def to_requirement_query_set(req_set: RequirementSet) -> RequirementQuerySet:
    """Convert a RequirementSet into CONTEXT-04's RequirementQuerySet."""
    queries: list[RequirementQuery] = []

    for r in req_set.requirements:
        terms = [term for term, _ in _KEYWORD_ANALYZER.analyze(r.text)]
        span_str = None
        if r.job_evidence.source_span is not None:
            span_str = f"{r.job_evidence.source_span.start}:{r.job_evidence.source_span.end}"

        queries.append(
            RequirementQuery(
                query_id=f"q_{r.requirement_id}",
                original_text=r.text,
                query_text=r.text,
                terms=terms,
                source_span=span_str,
                provenance="requirement",
            )
        )

    canonical_data = [
        {"id": q.query_id, "text": q.query_text, "terms": sorted(q.terms)}
        for q in queries
    ]
    canonical_bytes = json.dumps(canonical_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    query_fp = f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"

    return RequirementQuerySet(
        recipe_version=req_set.recipe_version,
        queries=queries,
        query_set_fingerprint=query_fp,
    )
