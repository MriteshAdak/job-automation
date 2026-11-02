"""Opt-in live smoke verification helper for ArbeitnowAdapter (SOURCE-03-S07).

Usage:
    python tests/manual/arbeitnow_smoke.py --registry-path config/sources.local.json --data-dir local_data/smoke

NOT run by automated pytest suites. Requires explicit local configuration with
enabled=true. Maximum 2 pages, bounded timeout, at least 60s spacing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.postings import SourceJobDraft
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.arbeitnow import (
    ATTRIBUTION_LINK,
    ATTRIBUTION_NOTICE,
    ArbeitnowAdapter,
)
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash
from job_automation.sources.loader import load_source_registry
from job_automation.sources.service import SourceRegistryService


class LocalDirectoryCaptureSink(RawCaptureSink):
    """File-backed capture sink for manual smoke tests."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, Path] = {}

    def capture(self, content_bytes: bytes, identifier_hint: str = "") -> tuple[str, str]:
        c_hash = compute_content_hash(content_bytes)
        hex_prefix = c_hash.split(":")[-1][:12]
        safe_hint = "".join(c if c.isalnum() else "_" for c in identifier_hint)
        filename = f"{safe_hint}_{hex_prefix}.dat"
        file_path = self.data_dir / filename
        file_path.write_bytes(content_bytes)
        ref = f"file://{file_path.as_posix()}"
        self._index[ref] = file_path
        return ref, c_hash

    def get(self, raw_payload_ref: str) -> bytes | None:
        p = self._index.get(raw_payload_ref)
        if p and p.is_file():
            return p.read_bytes()
        return None


def run_smoke(registry_path: Path, data_dir: Path, max_pages: int = 1) -> int:
    """Execute bounded smoke verification against live Arbeitnow API."""
    print("=" * 70)
    print("Arbeitnow API Adapter — Opt-in Live Smoke Verification")
    print(f"Timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
    print(f"Registry:        {registry_path}")
    print(f"Data directory:  {data_dir}")
    print(f"Max pages cap:   {max_pages} (enforced upper bound: 2)")
    print("=" * 70)

    if not registry_path.is_file():
        print(f"[ERROR] Registry file not found: {registry_path}")
        print("To run live verification, create a local registry with arbeitnow_de enabled.")
        return 1

    service = SourceRegistryService.load_from_path(registry_path)
    selection = service.select_sources(["arbeitnow_de"])

    if not selection.is_valid or not selection.selected_sources:
        print("[BLOCKED] Source 'arbeitnow_de' is not runnable in the provided registry:")
        for blocker in selection.blockers:
            print(f"  - {blocker}")
        print("\nLive verification marked PENDING (no enabled local configuration).")
        return 2

    eff_source = selection.selected_sources[0]
    sink = LocalDirectoryCaptureSink(data_dir)
    # Uses real default _UrllibTransport and _SystemClock
    adapter = ArbeitnowAdapter(effective_source=eff_source, capture_sink=sink)

    cap_pages = min(max_pages, 2)
    continuation: Continuation | None = None
    all_drafts: list[SourceJobDraft] = []

    for page_idx in range(1, cap_pages + 1):
        print(f"\n--- Fetching Page {page_idx} (continuation: {continuation.value if continuation else 'initial'}) ---")
        page = adapter.fetch_page(eff_source.config, continuation=continuation)

        if page.page_error:
            print(f"[PAGE ERROR] {page.page_error.category.value}: {page.page_error.message}")
            if page.page_error.details:
                print(f"  Details: {page.page_error.details}")
            break

        print(f"Raw items on page:   {page.record_count}")
        print(f"Record issues:       {page.issue_count}")
        print(f"Exhausted:           {page.exhausted}")
        print(f"Raw response refs:   {page.raw_response_refs}")

        for raw_item in page.items:
            res = adapter.draft_posting(raw_item)
            if res.draft is not None:
                all_drafts.append(res.draft)
            else:
                print(f"  [DRAFT FAILED] {raw_item.source_key.source_posting_id}:")
                for iss in res.issues:
                    print(f"    - {iss.severity}: {iss.code}: {iss.message}")

        if page.exhausted or page.continuation_out is None:
            print("\nTraversal completed / exhausted.")
            break

        continuation = page.continuation_out

    print("\n" + "=" * 70)
    print("Smoke Summary:")
    print(f"  Total valid drafts created: {len(all_drafts)}")
    if all_drafts:
        sample = all_drafts[0]
        print(f"  Sample draft:")
        print(f"    Title:        {sample.source_mapped_fields.get('title')}")
        print(f"    Company hint: {sample.source_mapped_fields.get('company_name_hint')}")
        print(f"    Workplace:    {sample.source_mapped_fields.get('workplace_type_raw')}")
        print(f"    Locations:    {sample.source_mapped_fields.get('locations_raw')}")
        print(f"    Mapping ver:  {sample.source_mapped_fields.get('mapping_version')}")
        print(f"    Attribution:  {sample.source_mapped_fields.get('attribution')}")

    print(f"\nRequired Attribution Notice:")
    print(f"  {ATTRIBUTION_NOTICE} ({ATTRIBUTION_LINK})")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arbeitnow API live smoke verification")
    parser.add_argument("--registry-path", type=Path, default=_REPO_ROOT / "config" / "sources.arbeitnow.example.json")
    parser.add_argument("--data-dir", type=Path, default=_REPO_ROOT / "local_data" / "smoke")
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args()

    sys.exit(run_smoke(args.registry_path, args.data_dir, args.max_pages))
