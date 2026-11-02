"""Safe JSON loader and envelope parser for source registries (SOURCE-01-S02).

Enforces:
- UTF-8 encoding with BOM handling.
- Duplicate JSON key detection at parse time.
- Supported schema version checking.
- Unique source_key validation across entries.
- Validation of each entry against C03 SourceConfig.
- Immediate file handle release.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import (
    ERR_DUPLICATE_JSON_MEMBER,
    ERR_DUPLICATE_KEY,
    ERR_MALFORMED_REGISTRY,
    ERR_UNSUPPORTED_VERSION,
    make_issue,
)
from job_automation.sources.models import SourceRegistryEnvelope

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


def _check_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Object pairs hook for json.loads to detect duplicate keys in JSON objects."""
    d: dict[str, Any] = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"Duplicate JSON key '{k}' detected in source registry")
        d[k] = v
    return d


def load_source_registry(
    registry_path: Path | str,
) -> tuple[SourceRegistryEnvelope, list[ValidationIssue]]:
    """Load and parse source registry JSON file with strict envelope validation.

    Raises:
        FileNotFoundError: If registry file does not exist.
        ValueError: If JSON is malformed, has duplicate keys, unsupported version,
                    or duplicate source_keys.
    """
    path = Path(registry_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source registry file not found: {path}")

    # Read raw bytes to handle UTF-8 BOM if present
    raw_bytes = path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]

    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ValueError(f"Source registry is not valid UTF-8: {err}") from err

    try:
        raw_data = json.loads(raw_text, object_pairs_hook=_check_duplicate_pairs)
    except json.JSONDecodeError as err:
        raise ValueError(f"Malformed JSON in source registry: {err}") from err
    except ValueError as err:
        if "Duplicate JSON key" in str(err):
            raise
        raise ValueError(f"Malformed JSON in source registry: {err}") from err

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Source registry root must be a JSON object, got {type(raw_data).__name__}"
        )

    issues: list[ValidationIssue] = []

    # Validate envelope schema_version
    version = raw_data.get("schema_version")
    if not isinstance(version, str) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported source registry schema_version: '{version}'. Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    # Validate sources list
    sources_raw = raw_data.get("sources")
    if not isinstance(sources_raw, list):
        raise ValueError(
            f"Source registry 'sources' field must be a list, got {type(sources_raw).__name__}"
        )

    seen_keys: set[str] = set()
    validated_sources: list[SourceConfig] = []

    for idx, entry in enumerate(sources_raw):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Source entry at index {idx} must be a JSON object, got {type(entry).__name__}"
            )

        source_key = entry.get("source_key")
        if not isinstance(source_key, str) or not source_key.strip():
            raise ValueError(f"Source entry at index {idx} has invalid or empty 'source_key'")

        key_clean = source_key.strip()
        if key_clean in seen_keys:
            raise ValueError(
                f"Duplicate source_key '{key_clean}' detected in source registry at index {idx}"
            )
        seen_keys.add(key_clean)

        try:
            cfg = SourceConfig.model_validate(entry)
            validated_sources.append(cfg)
        except Exception as exc:
            raise ValueError(
                f"Source entry '{key_clean}' at index {idx} failed C03 validation: {exc}"
            ) from exc

    envelope = SourceRegistryEnvelope(
        schema_version=version,
        sources=validated_sources,
    )
    return envelope, issues

