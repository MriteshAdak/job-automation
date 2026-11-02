"""Native Windows path, encoding, timezone, and file-handle verification for Arbeitnow (SOURCE-03-S07)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure repository root is on sys.path regardless of process working directory
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from job_automation.contracts.adapter_results import DraftResult
from job_automation.contracts.postings import RawPosting
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter, build_page_url
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash
from tests.sources.arbeitnow_helpers import (
    FakeClock,
    FakeTransport,
    build_adapter,
    build_arbeitnow_config,
    build_arbeitnow_source,
    load_fixture,
)


class FileSystemTestSink(RawCaptureSink):
    """File-backed capture sink inside a directory with umlauts and spaces to test handle release."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, Path] = {}

    def capture(self, content_bytes: bytes, identifier_hint: str = "") -> tuple[str, str]:
        c_hash = compute_content_hash(content_bytes)
        hex_prefix = c_hash.split(":")[-1][:12]
        safe_hint = "".join(c if c.isalnum() else "_" for c in identifier_hint)
        filename = f"{safe_hint}_{hex_prefix}.dat"
        file_path = self.root_dir / filename
        file_path.write_bytes(content_bytes)
        ref = f"file://{file_path.as_posix()}"
        self._index[ref] = file_path
        return ref, c_hash

    def get(self, raw_payload_ref: str) -> bytes | None:
        p = self._index.get(raw_payload_ref)
        if p and p.is_file():
            return p.read_bytes()
        return None


def test_windows_unicode_spaces_path_and_handle_release(tmp_path: Path) -> None:
    # Directory with spaces and umlauts:
    work_dir = tmp_path / "Job Prüfung Arbeitnow ä ö ü ß"
    sink_dir = work_dir / "Rohdaten Speichergröße"
    sink = FileSystemTestSink(sink_dir)

    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)

    adapter = ArbeitnowAdapter(
        effective_source=build_arbeitnow_source(),
        capture_sink=sink,
        transport=transport,
        clock=FakeClock(),
    )

    page = adapter.fetch_page(build_arbeitnow_config())
    assert len(page.items) == 2
    assert len(page.raw_response_refs) == 1

    # Verify captured parent and envelope files exist on disk
    parent_file = sink._index[page.raw_response_refs[0]]
    assert parent_file.is_file()

    # Verify German characters in the parsed items
    res0 = adapter.draft_posting(page.items[0])
    assert res0.draft is not None
    assert "Küche & Co GmbH" in res0.draft.source_mapped_fields["company_name_hint"]
    assert "Vertriebsinnendienst" in res0.draft.source_mapped_fields["title"]

    # Demonstrate handle release on native Windows:
    # We can rename and delete all captured files immediately with no leaked open handles!
    renamed_parent = parent_file.parent / "umbenannt_parent.dat"
    parent_file.rename(renamed_parent)
    assert renamed_parent.is_file()
    assert not parent_file.exists()

    for item in page.items:
        env_file = sink._index[item.raw_payload_ref]
        assert env_file.is_file()
        renamed_env = env_file.parent / f"renamed_{env_file.name}"
        env_file.rename(renamed_env)
        assert renamed_env.is_file()
        renamed_env.unlink()
        assert not renamed_env.exists()

    renamed_parent.unlink()
    assert not renamed_parent.exists()


def test_windows_independent_of_process_working_directory(tmp_path: Path) -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport)

    other_dir = tmp_path / "Anderes Verzeichnis"
    other_dir.mkdir()
    old_cwd = os.getcwd()
    try:
        os.chdir(other_dir)
        page = adapter.fetch_page(build_arbeitnow_config())
        assert len(page.items) == 2
        res = adapter.draft_posting(page.items[0])
        assert res.draft is not None
    finally:
        os.chdir(old_cwd)


class BerlinClock:
    """Clock returning Europe/Berlin local time with timezone offset."""

    def __init__(self) -> None:
        self.tz = ZoneInfo("Europe/Berlin")

    def now_utc(self) -> datetime:
        # Returns current time converted to aware UTC
        berlin_time = datetime(2026, 10, 28, 11, 0, 0, tzinfo=self.tz)
        return berlin_time.astimezone(timezone.utc)


def test_berlin_timezone_clock_converted_to_utc() -> None:
    clock = BerlinClock()
    utc_dt = clock.now_utc()
    # Must be aware with offset 0
    assert utc_dt.tzinfo is not None
    assert utc_dt.utcoffset() == timezone.utc.utcoffset(None)
    # 11:00 in Berlin (CET / +01:00) is 10:00 UTC
    assert utc_dt.hour == 10
    assert utc_dt.isoformat().endswith("+00:00") or utc_dt.isoformat().endswith("Z")

    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport, clock=clock)

    page = adapter.fetch_page(build_arbeitnow_config())
    assert len(page.items) == 2
    for item in page.items:
        assert item.fetch_time.utcoffset() == timezone.utc.utcoffset(None)


def test_deterministic_content_hashing_for_fixtures() -> None:
    p1 = load_fixture("page_1.json")
    hash_1 = compute_content_hash(p1)
    hash_2 = compute_content_hash(p1)
    assert hash_1 == hash_2
    assert hash_1.startswith("sha256:")
    assert len(hash_1) == len("sha256:") + 64
