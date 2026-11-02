"""Port interfaces, protocols, and standard adapter factory registry (INGEST-01-S01).

Defines:
- ClockProtocol and SystemClock for deterministic UTC/monotonic time
- SleeperProtocol and SystemSleeper for bounded delays and unit-test fakes
- AdapterFactory protocol and default registry binding checked sources to adapters
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.interfaces import Adapter
from job_automation.ingestion.models import ControllerOptions
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter
from job_automation.sources.adapters.manual_csv import ManualCsvAdapter
from job_automation.sources.adapters.manual_text import ManualTextAdapter
from job_automation.sources.adapters.raw import RawCaptureSink
from job_automation.sources.models import EffectiveSource


@runtime_checkable
class ClockProtocol(Protocol):
    """Injected clock protocol for monotonic and UTC wall-clock time."""

    def now_utc(self) -> datetime:
        """Return current time with timezone.utc."""
        ...

    def monotonic(self) -> float:
        """Return monotonic time in fractional seconds."""
        ...


class SystemClock:
    """Standard system clock implementation."""

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


@runtime_checkable
class SleeperProtocol(Protocol):
    """Injected sleeper protocol for pacing and backoff delays."""

    def sleep(self, seconds: float) -> None:
        """Sleep for the specified number of seconds."""
        ...


class SystemSleeper:
    """Standard system sleeper using time.sleep."""

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


AdapterFactory = Callable[[EffectiveSource, RawCaptureSink, ControllerOptions], Adapter]


class AdapterRegistry:
    """Registry mapping sources or acquisition methods to adapter factories.

    Ensures no dynamic untrusted imports occur; all factories must be
    explicitly registered.
    """

    def __init__(self) -> None:
        self._factories_by_key: dict[str, AdapterFactory] = {}
        self._factories_by_provider: dict[str, AdapterFactory] = {}
        self._register_defaults()

    def register_for_key(self, source_key: str, factory: AdapterFactory) -> None:
        """Register factory for a specific source_key (highest precedence)."""
        self._factories_by_key[source_key] = factory

    def register_for_provider(self, provider: str, factory: AdapterFactory) -> None:
        """Register factory for a provider identifier."""
        self._factories_by_provider[provider] = factory

    def create_adapter(
        self,
        effective_source: EffectiveSource,
        capture_sink: RawCaptureSink,
        options: ControllerOptions,
    ) -> Adapter:
        """Create and bind an adapter for the given effective source."""
        key = effective_source.config.source_key
        provider = effective_source.config.provider

        if key in self._factories_by_key:
            return self._factories_by_key[key](effective_source, capture_sink, options)

        if provider in self._factories_by_provider:
            return self._factories_by_provider[provider](effective_source, capture_sink, options)

        # Check acquisition method fallback
        if effective_source.config.acquisition_method == AcquisitionMethod.MANUAL_IMPORT:
            return self._create_manual_adapter(effective_source, capture_sink, options)

        raise ValueError(
            f"No registered adapter factory for source_key='{key}' or provider='{provider}'"
        )

    def _register_defaults(self) -> None:
        # Default registration for Arbeitnow provider
        self.register_for_provider("arbeitnow", _create_arbeitnow_adapter)

    def _create_manual_adapter(
        self,
        effective_source: EffectiveSource,
        capture_sink: RawCaptureSink,
        options: ControllerOptions,
    ) -> Adapter:
        key = effective_source.config.source_key
        descriptor = options.manual_inputs.get(key, {})
        base_path = options.input_base_path or Path.cwd()

        # Determine if CSV or Text
        is_csv = False
        csv_path: str | Path | None = None
        if "csv_path" in descriptor or descriptor.get("format") == "csv":
            is_csv = True
            csv_path = descriptor.get("csv_path")
        elif "input_file" in descriptor:
            file_name = str(descriptor["input_file"]).lower()
            if file_name.endswith(".csv"):
                is_csv = True
                csv_path = descriptor["input_file"]

        if is_csv:
            if not csv_path:
                raise ValueError(f"Manual CSV source '{key}' missing 'csv_path' or 'input_file'")
            page_size = descriptor.get("page_size", 50)
            delimiter = descriptor.get("delimiter", ",")
            return ManualCsvAdapter(
                effective_source=effective_source,
                capture_sink=capture_sink,
                csv_path=csv_path,
                input_base_path=base_path,
                page_size=page_size,
                delimiter=delimiter,
            )

        # Default to ManualTextAdapter
        source_url = descriptor.get("source_url") or descriptor.get("input_url") or "https://example.invalid/manual"
        return ManualTextAdapter(
            effective_source=effective_source,
            capture_sink=capture_sink,
            source_url=source_url,
            text=descriptor.get("text") or descriptor.get("input_text"),
            text_path=descriptor.get("text_path") or descriptor.get("input_file"),
            input_base_path=base_path,
        )


def _create_arbeitnow_adapter(
    effective_source: EffectiveSource,
    capture_sink: RawCaptureSink,
    options: ControllerOptions,
) -> Adapter:
    return ArbeitnowAdapter(
        effective_source=effective_source,
        capture_sink=capture_sink,
    )
