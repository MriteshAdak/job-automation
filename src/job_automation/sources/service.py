"""High-level SourceRegistryService facade for registry inspection and checked selection (SOURCE-01-S06).

Enforces:
- Checked source selection: only configured, valid, enabled, permitted sources can be selected.
- Atomic selection: if any requested key is missing or blocked, no executable selection is returned.
- Exact key matching and duplicate request rejection.
- Detached immutable snapshots: mutations by caller cannot alter registered configuration.
- Read-only inspection of configured sources with readiness status.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from job_automation.configuration import AppConfig, load_config
from job_automation.contracts.errors import ValidationIssue
from job_automation.sources.errors import (
    ERR_DUPLICATE_SELECTION,
    ERR_SOURCE_DISABLED,
    ERR_SOURCE_NOT_CONFIGURED,
    make_issue,
)
from job_automation.sources.loader import load_source_registry
from job_automation.sources.models import (
    AccessReviewStatus,
    AttributionStatus,
    EffectiveSource,
    SourceRegistryEnvelope,
    SourceSelectionResult,
)
from job_automation.sources.validation import validate_source_config


class SourceRegistryService:
    """Service providing source registry loading, semantic validation, and checked selection."""

    def __init__(
        self,
        envelope: SourceRegistryEnvelope,
        sources: dict[str, EffectiveSource],
        registry_path: Path | None = None,
        load_issues: list[ValidationIssue] | None = None,
    ) -> None:
        self.envelope = envelope
        self.sources = sources
        self.registry_path = registry_path
        self.load_issues = load_issues or []

    @classmethod
    def from_envelope(
        cls,
        envelope: SourceRegistryEnvelope,
        registry_path: Path | None = None,
        load_issues: list[ValidationIssue] | None = None,
    ) -> SourceRegistryService:
        """Construct service from a validated SourceRegistryEnvelope."""
        sources: dict[str, EffectiveSource] = {}
        for cfg in envelope.sources:
            effective = validate_source_config(cfg)
            sources[cfg.source_key] = effective

        return cls(
            envelope=envelope,
            sources=sources,
            registry_path=registry_path,
            load_issues=load_issues,
        )

    @classmethod
    def load_from_path(cls, registry_path: Path | str) -> SourceRegistryService:
        """Load and validate a source registry from a filesystem path."""
        p = Path(registry_path).resolve()
        envelope, issues = load_source_registry(p)
        return cls.from_envelope(envelope, registry_path=p, load_issues=issues)

    @classmethod
    def load_from_config(
        cls,
        config_path: Path | str | None = None,
        data_root_override: str | None = None,
        registry_override: Path | str | None = None,
    ) -> tuple[SourceRegistryService, AppConfig, list[str]]:
        """Load application configuration and resolve its source registry.

        Precedence for source registry:
        1. Explicit registry_override path
        2. Resolved source_registry_path from AppConfig
        """
        app_config, paths = load_config(
            config_path=config_path,
            data_root_override=data_root_override,
        )

        target_registry: Path | None = None
        if registry_override is not None:
            target_registry = Path(registry_override).resolve()
        elif paths.source_registry_path is not None:
            target_registry = paths.source_registry_path

        if target_registry is None:
            raise FileNotFoundError(
                "No source registry configured. Specify --registry <path> or set "
                "'source_registry_ref' in application configuration."
            )

        service = cls.load_from_path(target_registry)
        return service, app_config, app_config.active_sources

    def get_source(self, source_key: str) -> EffectiveSource | None:
        """Look up a single configured source by key, returning a detached copy."""
        source = self.sources.get(source_key)
        if source is None:
            return None
        return source.model_copy(deep=True)

    def list_sources(self) -> list[EffectiveSource]:
        """Return detached copies of all configured sources in the registry."""
        return [s.model_copy(deep=True) for s in self.sources.values()]

    def select_sources(
        self,
        requested_keys: Sequence[str],
    ) -> SourceSelectionResult:
        """Select requested sources through the strict preflight validation gate.

        Invariants enforced:
        - Duplicate requested keys produce a visible error and fail selection.
        - Empty requested keys returns a valid empty selection (nothing runs).
        - If ANY requested source is unconfigured, disabled, unreviewed, or invalid,
          the selection fails atomically and NO executable sources are returned.
        - Returns detached deep copies so caller mutation cannot bypass validation.
        """
        requested_list = list(requested_keys)
        blockers: list[str] = []
        issues: list[ValidationIssue] = []

        # 1. Check duplicate keys in requested selection
        seen_keys: set[str] = set()
        duplicate_keys: list[str] = []
        for k in requested_list:
            if k in seen_keys:
                if k not in duplicate_keys:
                    duplicate_keys.append(k)
            seen_keys.add(k)

        if duplicate_keys:
            msg = f"Duplicate source keys requested in selection: {duplicate_keys}"
            blockers.append(msg)
            issues.append(
                make_issue(
                    code=ERR_DUPLICATE_SELECTION,
                    message=msg,
                    field_path="active_sources",
                )
            )

        # 2. Check each requested key
        selected: list[EffectiveSource] = []
        for key in requested_list:
            if key not in self.sources:
                msg = f"Source '{key}' is not configured in source registry"
                blockers.append(msg)
                issues.append(
                    make_issue(
                        code=ERR_SOURCE_NOT_CONFIGURED,
                        message=msg,
                        field_path=f"sources.{key}",
                    )
                )
                continue

            source = self.sources[key]

            # Check disabled
            if not source.config.enabled:
                msg = f"Source '{key}' is disabled (enabled=false)"
                blockers.append(msg)
                issues.append(
                    make_issue(
                        code=ERR_SOURCE_DISABLED,
                        message=msg,
                        field_path=f"sources.{key}.enabled",
                    )
                )

            # Check access review
            if source.access_review.status != AccessReviewStatus.PERMITTED:
                msg = (
                    f"Source '{key}' lacks approved access authorization review "
                    f"(status: '{source.access_review.status.value}')"
                )
                blockers.append(msg)

            # Check attribution
            if source.attribution_review.status == AttributionStatus.UNKNOWN:
                msg = f"Source '{key}' has unknown attribution requirements"
                blockers.append(msg)

            # Check config errors
            if not source.is_valid:
                error_msgs = [
                    f"[{i.code}] {i.message}"
                    for i in source.issues
                    if i.severity == "error"
                ]
                msg = f"Source '{key}' has configuration validation errors: {'; '.join(error_msgs)}"
                blockers.append(msg)

            # Accumulate issues
            issues.extend(source.issues)

            if source.is_runnable and source.is_valid:
                selected.append(source.model_copy(deep=True))

        # Atomic failure rule: if any requested key is blocked, return no executable sources
        if blockers:
            return SourceSelectionResult(
                selected_sources=[],
                all_sources={k: s.model_copy(deep=True) for k, s in self.sources.items()},
                requested_keys=requested_list,
                is_valid=False,
                blockers=blockers,
                issues=issues,
            )

        return SourceSelectionResult(
            selected_sources=selected,
            all_sources={k: s.model_copy(deep=True) for k, s in self.sources.items()},
            requested_keys=requested_list,
            is_valid=True,
            blockers=[],
            issues=issues,
        )
