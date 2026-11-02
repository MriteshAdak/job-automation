"""Local schema registry and strict JSON parser (LLM-01-S01, S04).

Enforces:
- Structured generation requires an object-shaped registered schema.
- Rejection of duplicate keys, non-finite numbers, markdown fences, and trailing prose.
- Strict Pydantic validation forbidding extra or missing fields without value coercion.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ValidationIssue


class RegisteredSchema(ContractModel):
    """Pinned metadata and schema specification for structured generation."""

    schema_id: str
    version: str
    digest: str
    json_schema: dict[str, Any]
    model_cls: Any = None  # type[BaseModel] | None


def _check_depth(val: Any, current_depth: int, max_depth: int) -> None:
    if current_depth > max_depth:
        raise ValueError(f"JSON nesting depth exceeds maximum allowed {max_depth}")
    if isinstance(val, dict):
        for v in val.values():
            _check_depth(v, current_depth + 1, max_depth)
    elif isinstance(val, list):
        for v in val:
            _check_depth(v, current_depth + 1, max_depth)


def _strict_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"Duplicate key in JSON object: '{k}'")
        out[k] = v
    return out


def _forbid_constant(constant: str) -> None:
    raise ValueError(f"Non-finite numbers (NaN, Infinity) are forbidden: '{constant}'")


def parse_strict_json(raw_text: str, max_depth: int = 20) -> dict[str, Any]:
    """Parse strict JSON object.

    Rejects:
    - Markdown code fences (e.g. ```json ... ```)
    - Surrounding prose or trailing text
    - Non-dict top level (lists, primitives)
    - Duplicate dictionary keys
    - NaN, Infinity, -Infinity
    - Excessive nesting depth
    """
    if not isinstance(raw_text, str):
        raise ValueError("raw_text must be a string")

    stripped = raw_text.strip()
    if not stripped:
        raise ValueError("Raw text is empty")

    if stripped.startswith("```") or stripped.endswith("```"):
        raise ValueError("Markdown code fences (```) are not allowed in strict JSON output")

    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError("Strict JSON output must be a single object enclosed in '{ ... }'")

    # Decode strict JSON
    decoder = json.JSONDecoder(
        object_pairs_hook=_strict_pairs_hook,
        parse_constant=_forbid_constant,
    )

    parsed, end_idx = decoder.raw_decode(stripped)
    if end_idx != len(stripped):
        raise ValueError("Trailing data after JSON object is forbidden")

    if not isinstance(parsed, dict):
        raise ValueError("Top-level JSON value must be an object (dictionary)")

    _check_depth(parsed, 1, max_depth)
    return parsed


def validate_against_schema(
    parsed_dict: dict[str, Any],
    schema: RegisteredSchema,
) -> tuple[dict[str, Any] | None, list[ValidationIssue]]:
    """Validate a parsed JSON dict against the registered schema.

    Returns (validated_data_dict, issues_list).
    """
    if schema.model_cls is None:
        return parsed_dict, []

    model_cls: Type[BaseModel] = schema.model_cls
    try:
        instance = model_cls.model_validate(parsed_dict)
        return instance.model_dump(mode="json"), []
    except ValidationError as exc:
        issues: list[ValidationIssue] = []
        for err in exc.errors():
            loc_str = ".".join(str(loc) for loc in err.get("loc", []))
            code = str(err.get("type", "validation_error"))
            msg = str(err.get("msg", "Invalid field"))
            issues.append(
                ValidationIssue(
                    field_path=loc_str or "root",
                    code=code,
                    message=f"Schema validation error at {loc_str or 'root'}: {msg}",
                    severity="error",
                )
            )
        return None, issues


class LocalSchemaRegistry:
    """Registry of approved output schemas for structured generation."""

    def __init__(self) -> None:
        self._schemas: dict[str, RegisteredSchema] = {}

    def register(
        self,
        schema_id: str,
        model_cls: Type[BaseModel],
        version: str = "1.0",
    ) -> RegisteredSchema:
        """Register a contract model class under schema_id."""
        json_schema = model_cls.model_json_schema()
        canonical_bytes = json.dumps(
            json_schema,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"

        registered = RegisteredSchema(
            schema_id=schema_id,
            version=version,
            digest=digest,
            json_schema=json_schema,
            model_cls=model_cls,
        )
        self._schemas[schema_id] = registered
        return registered

    def get(self, schema_id: str) -> RegisteredSchema | None:
        """Retrieve registered schema by ID."""
        return self._schemas.get(schema_id)

    def resolve(self, schema_id: str) -> RegisteredSchema:
        """Resolve schema or raise ValueError."""
        schema = self.get(schema_id)
        if schema is None:
            raise ValueError(f"Unknown or unregistered output schema '{schema_id}'")
        return schema


def build_default_schema_registry() -> LocalSchemaRegistry:
    """Construct registry pre-populated with standard C-contract output schemas."""
    from job_automation.assessment.llm_records import AssessmentProposal
    from job_automation.assessment.requirement_prompts import ExtractedRequirementPayload
    from job_automation.contracts.draft_content import DraftContentProposal, DraftDocumentV2

    registry = LocalSchemaRegistry()
    registry.register("C11_assessment", Assessment, version="1.0")
    registry.register("assessment_proposal", AssessmentProposal, version="1.0")
    registry.register("requirement_extraction", ExtractedRequirementPayload, version="1.0")
    registry.register("C14_draft_document", DraftDocument, version="1.0")
    registry.register("C14_artifact", Artifact, version="1.0")
    registry.register("draft_content_proposal_v1", DraftContentProposal, version="1.0")
    registry.register("C14_draft_document_v2", DraftDocumentV2, version="2.0")
    return registry
