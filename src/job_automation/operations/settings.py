"""Operations configuration loading, validation, and policy fingerprinting (OPS-01-S02)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from job_automation.operations.records import OperationsSettings


def load_operations_settings(
    settings_path: Path | str | None = None,
    base_dir: Path | None = None,
) -> OperationsSettings:
    """Load and validate operations settings from a JSON file, or return safe defaults."""
    if settings_path is None:
        return OperationsSettings()

    path = Path(settings_path)
    if not path.is_absolute() and base_dir is not None:
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        raise FileNotFoundError(f"Operations settings file not found: {path}")

    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    data.pop("$schema", None)
    return OperationsSettings.model_validate(data)


def compute_policy_fingerprint(settings: OperationsSettings) -> str:
    """Compute a deterministic hash of the active retention and capacity policy."""
    raw_dict: dict[str, Any] = {
        "retention_enabled": settings.retention.enabled,
        "raw_payloads_days": settings.retention.raw_payloads_days,
        "logs_days": settings.retention.logs_days,
        "staging_days": settings.retention.staging_days,
        "backups_days": settings.retention.backups_days,
        "source_overrides": sorted(settings.retention.source_overrides.items()),
        "reserve_bytes": settings.capacity.reserve_bytes,
        "reserve_percent": settings.capacity.reserve_percent,
        "keep_generations": settings.backup.keep_generations,
    }
    canonical = json.dumps(raw_dict, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
