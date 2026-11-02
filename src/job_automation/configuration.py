"""Application configuration and path resolution for native Windows deployment.

Enforces:
- Absolute runtime data root outside source repository.
- Loopback-only model service endpoint.
- Valid timezone resolution (Europe/Berlin default).
- Precedence: CLI args > Config file > Default environment path.
- Resolves config-relative references against configuration file parent directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.models.configuration import (
    ModelProviderSettings,
    validate_loopback_url,
)


class AppConfig(ContractModel):
    """Application configuration for local execution."""

    app_name: str = Field(default="JobAutomation", min_length=1)
    data_root: str = Field(description="Absolute path to runtime data root directory")
    display_timezone: str = Field(
        default="Europe/Berlin",
        description="IANA timezone for display and scheduling intent",
    )
    active_policy_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to active search policy JSON",
    )
    source_registry_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to source registry JSON",
    )
    availability_policy_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to availability policy JSON",
    )
    index_settings_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to index settings JSON",
    )
    salesforce_settings_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to Salesforce settings JSON",
    )
    sync_mapping_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to sync mapping JSON",
    )
    operations_settings_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to operations settings JSON",
    )
    scheduling_settings_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to scheduling settings JSON",
    )
    generation_settings_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to generation settings JSON",
    )
    request_mapping_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to generation request mapping JSON",
    )
    automatic_draft_policy_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to automatic drafting policy JSON",
    )
    summary_delivery_settings_ref: str | None = Field(
        default=None,
        description="Relative or absolute path to summary delivery settings JSON",
    )
    active_sources: list[str] = Field(
        default_factory=list,
        description="List of enabled source keys to fetch during discovery runs",
    )
    model_service_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Local model service URL; must bind to loopback",
    )
    model_provider: ModelProviderSettings | None = Field(
        default=None,
        description="Execution settings for local model provider",
    )

    @field_validator("display_timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"Invalid IANA timezone '{v}': {err}") from err
        return v

    @field_validator("model_service_url")
    @classmethod
    def _validate_loopback(cls, v: str) -> str:
        return validate_loopback_url(v)

    def resolve_paths(self, base_dir: Path | None = None) -> ResolvedPaths:
        """Resolve and validate all child directories beneath data_root."""
        raw_root = Path(self.data_root)
        if not raw_root.is_absolute():
            raise ValueError(f"Runtime data_root must be an absolute path, got '{self.data_root}'")

        # Resolve against repository root to ensure data_root is outside repository
        repo_root = Path(__file__).resolve().parent.parent.parent
        try:
            raw_root_resolved = raw_root.resolve()
            repo_root_resolved = repo_root.resolve()
            if repo_root_resolved == raw_root_resolved or repo_root_resolved in raw_root_resolved.parents:
                raise ValueError(
                    f"Runtime data_root ('{raw_root}') must be strictly outside repository ('{repo_root}')"
                )
        except (ValueError, RuntimeError) as e:
            if "must be strictly outside repository" in str(e):
                raise

        # Resolve policy reference against config parent if relative
        resolved_policy_path: Path | None = None
        if self.active_policy_ref:
            policy_path = Path(self.active_policy_ref)
            if not policy_path.is_absolute() and base_dir is not None:
                resolved_policy_path = (base_dir / policy_path).resolve()
            else:
                resolved_policy_path = policy_path.resolve()

        # Resolve source registry reference against config parent if relative
        resolved_registry_path: Path | None = None
        if self.source_registry_ref:
            reg_path = Path(self.source_registry_ref)
            if not reg_path.is_absolute() and base_dir is not None:
                resolved_registry_path = (base_dir / reg_path).resolve()
            else:
                resolved_registry_path = reg_path.resolve()

        # Resolve availability policy reference against config parent if relative
        resolved_availability_path: Path | None = None
        if self.availability_policy_ref:
            avail_path = Path(self.availability_policy_ref)
            if not avail_path.is_absolute() and base_dir is not None:
                resolved_availability_path = (base_dir / avail_path).resolve()
            else:
                resolved_availability_path = avail_path.resolve()

        # Resolve index settings reference against config parent if relative
        resolved_index_settings_path: Path | None = None
        if self.index_settings_ref:
            idx_path = Path(self.index_settings_ref)
            if not idx_path.is_absolute() and base_dir is not None:
                resolved_index_settings_path = (base_dir / idx_path).resolve()
            else:
                resolved_index_settings_path = idx_path.resolve()

        # Resolve salesforce settings reference against config parent if relative
        resolved_salesforce_settings_path: Path | None = None
        if self.salesforce_settings_ref:
            sf_path = Path(self.salesforce_settings_ref)
            if not sf_path.is_absolute() and base_dir is not None:
                resolved_salesforce_settings_path = (base_dir / sf_path).resolve()
            else:
                resolved_salesforce_settings_path = sf_path.resolve()

        # Resolve sync mapping reference against config parent if relative
        resolved_sync_mapping_path: Path | None = None
        if self.sync_mapping_ref:
            sync_map_path = Path(self.sync_mapping_ref)
            if not sync_map_path.is_absolute() and base_dir is not None:
                resolved_sync_mapping_path = (base_dir / sync_map_path).resolve()
            else:
                resolved_sync_mapping_path = sync_map_path.resolve()

        # Resolve operations settings reference against config parent if relative
        resolved_operations_settings_path: Path | None = None
        if self.operations_settings_ref:
            ops_path = Path(self.operations_settings_ref)
            if not ops_path.is_absolute() and base_dir is not None:
                resolved_operations_settings_path = (base_dir / ops_path).resolve()
            else:
                resolved_operations_settings_path = ops_path.resolve()

        # Resolve scheduling settings reference against config parent if relative
        resolved_scheduling_settings_path: Path | None = None
        if self.scheduling_settings_ref:
            sched_path = Path(self.scheduling_settings_ref)
            if not sched_path.is_absolute() and base_dir is not None:
                resolved_scheduling_settings_path = (base_dir / sched_path).resolve()
            else:
                resolved_scheduling_settings_path = sched_path.resolve()

        # Resolve generation settings reference against config parent if relative
        resolved_generation_settings_path: Path | None = None
        if self.generation_settings_ref:
            gen_path = Path(self.generation_settings_ref)
            if not gen_path.is_absolute() and base_dir is not None:
                resolved_generation_settings_path = (base_dir / gen_path).resolve()
            else:
                resolved_generation_settings_path = gen_path.resolve()

        # Resolve request mapping reference against config parent if relative
        resolved_request_mapping_path: Path | None = None
        if self.request_mapping_ref:
            map_path = Path(self.request_mapping_ref)
            if not map_path.is_absolute() and base_dir is not None:
                resolved_request_mapping_path = (base_dir / map_path).resolve()
            else:
                resolved_request_mapping_path = map_path.resolve()

        # Resolve automatic draft policy reference against config parent if relative
        resolved_auto_draft_path: Path | None = None
        if self.automatic_draft_policy_ref:
            ad_path = Path(self.automatic_draft_policy_ref)
            if not ad_path.is_absolute() and base_dir is not None:
                resolved_auto_draft_path = (base_dir / ad_path).resolve()
            else:
                resolved_auto_draft_path = ad_path.resolve()

        # Resolve summary delivery settings reference against config parent if relative
        resolved_summary_delivery_path: Path | None = None
        if self.summary_delivery_settings_ref:
            sd_path = Path(self.summary_delivery_settings_ref)
            if not sd_path.is_absolute() and base_dir is not None:
                resolved_summary_delivery_path = (base_dir / sd_path).resolve()
            else:
                resolved_summary_delivery_path = sd_path.resolve()

        return ResolvedPaths(
            data_root=raw_root,
            profiles_dir=raw_root / "profiles",
            raw_dir=raw_root / "raw",
            database_path=raw_root / "database" / "job_automation.db",
            indexes_dir=raw_root / "indexes",
            artifacts_dir=raw_root / "artifacts",
            logs_dir=raw_root / "logs",
            backups_dir=raw_root / "backups",
            generation_dir=raw_root / "generation",
            policy_path=resolved_policy_path,
            source_registry_path=resolved_registry_path,
            availability_policy_path=resolved_availability_path,
            index_settings_path=resolved_index_settings_path,
            salesforce_settings_path=resolved_salesforce_settings_path,
            sync_mapping_path=resolved_sync_mapping_path,
            operations_settings_path=resolved_operations_settings_path,
            scheduling_settings_path=resolved_scheduling_settings_path,
            generation_settings_path=resolved_generation_settings_path,
            request_mapping_path=resolved_request_mapping_path,
            automatic_draft_policy_path=resolved_auto_draft_path,
            summary_delivery_settings_path=resolved_summary_delivery_path,
        )


class ResolvedPaths(ContractModel):
    """Container for resolved application filesystem paths."""

    data_root: Path
    profiles_dir: Path
    raw_dir: Path
    database_path: Path
    indexes_dir: Path
    artifacts_dir: Path
    logs_dir: Path
    backups_dir: Path
    generation_dir: Path | None = None
    policy_path: Path | None = None
    source_registry_path: Path | None = None
    availability_policy_path: Path | None = None
    index_settings_path: Path | None = None
    salesforce_settings_path: Path | None = None
    sync_mapping_path: Path | None = None
    operations_settings_path: Path | None = None
    scheduling_settings_path: Path | None = None
    generation_settings_path: Path | None = None
    request_mapping_path: Path | None = None
    automatic_draft_policy_path: Path | None = None
    summary_delivery_settings_path: Path | None = None


def get_default_data_root() -> Path:
    """Derive standard default data root from LOCALAPPDATA or home directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JobAutomation"
    return Path.home() / "JobAutomation"


def load_config(
    config_path: str | Path | None = None,
    data_root_override: str | Path | None = None,
) -> tuple[AppConfig, ResolvedPaths]:
    """Load, validate, and resolve application configuration.

    Precedence:
    1. Explicit CLI data_root_override
    2. Explicit config_path JSON file
    3. Default data_root from %LOCALAPPDATA%
    """
    import json

    base_dir: Path | None = None
    config_data: dict = {}

    if config_path is not None:
        p = Path(config_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file not found: {p}")
        base_dir = p.parent
        try:
            with open(p, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(f"Malformed JSON in configuration file: {err}") from err

    # Apply data_root override if provided
    if data_root_override is not None:
        config_data["data_root"] = str(data_root_override)
    elif "data_root" not in config_data:
        config_data["data_root"] = str(get_default_data_root())

    config = AppConfig.model_validate(config_data)
    paths = config.resolve_paths(base_dir=base_dir)
    return config, paths

