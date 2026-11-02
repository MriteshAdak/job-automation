"""Base model classes and schema version conventions for all contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base class for all versioned contract models.

    Frozen (immutable), forbids extra fields, validates defaults.
    All contract records carry a schema_version.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        use_enum_values=False,
        ser_json_bytes="base64",
    )

    schema_version: str = "1.0"

