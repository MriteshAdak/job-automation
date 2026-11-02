"""Opt-in live smoke verification helper for INGEST-01 FetchController with ArbeitnowAdapter.

Usage:
    python tests/manual/ingest_smoke.py --data-dir <temp-dir> [--max-pages 1]

NOT run by automated pytest suites.
Runs FetchController with ArbeitnowAdapter against https://www.arbeitnow.com/api/job-board-api
under strict bounded limits (max 2 pages, 1 attempt per page, 60s spacing, 30s timeout, 10 MiB max body).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.ports import AdapterRegistry
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter
from job_automation.sources.models import EffectiveSource, SourceRegistryEnvelope
from job_automation.sources.service import SourceRegistryService
from job_automation.storage.engine import StorageEngine


def run_ingest_smoke(data_dir: Path, max_pages: int = 1) -> int:
    print("=" * 72)
    print("INGEST-01 FetchController Live Verification with ArbeitnowAdapter")
    print(f"Timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
    print(f"Data directory:  {data_dir}")
    print(f"Max pages cap:   {max_pages} (bounded upper limit: 2)")
    print("=" * 72)

    db_path = data_dir / "sqlite" / "ingest_smoke.db"
    raw_dir = data_dir / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize StorageEngine
    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    # 2. Configure Arbeitnow SourceConfig
    source_cfg = SourceConfig(
        source_key="arbeitnow_de",
        provider="arbeitnow",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://www.arbeitnow.com/api/job-board-api",
        enabled=True,
        inventory_semantics=InventorySemantics.FILTERED_FEED,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    envelope = SourceRegistryEnvelope(sources=[source_cfg])
    registry_service = SourceRegistryService.from_envelope(envelope)

    # 3. Setup AdapterRegistry with real ArbeitnowAdapter factory
    sink = DurableRawCaptureSink(raw_dir)
    adapter_registry = AdapterRegistry()
    adapter_registry.register_for_key(
        "arbeitnow_de",
        lambda eff, s, opts: ArbeitnowAdapter(effective_source=eff, capture_sink=s),
    )

    # 4. ControllerOptions enforcing bounds
    bounded_max_pages = min(max_pages, 2)
    options = ControllerOptions(
        max_pages=bounded_max_pages,
        max_requests=bounded_max_pages * 2,
        max_attempts_per_page=1,
        request_spacing_seconds=60.0,
        timeout_seconds=30.0,
        source_deadline_seconds=120.0,
    )

    controller = FetchController(
        storage=storage,
        options=options,
        adapter_registry=adapter_registry,
        registry_service=registry_service,
    )

    # 5. Run fetch
    print("\nExecuting FetchController.run_fetch ...")
    stage_res = controller.run_fetch(run_id=run_id, source_keys=["arbeitnow_de"])

    print("\nFetch execution finished.")
    print(f"Sources attempted: {stage_res.sources_attempted}")
    print(f"Sources completed: {stage_res.sources_completed}")
    print(f"Sources partial:   {stage_res.sources_partial}")
    print(f"Sources failed:    {stage_res.sources_failed}")
    print(f"Total requests:    {stage_res.total_requests}")
    print(f"Total pages:       {stage_res.total_pages}")
    print(f"Total raw records: {stage_res.total_raw_observations}")
    print(f"Unique identities: {stage_res.total_unique_identities}")

    src_res = stage_res.source_results["arbeitnow_de"]
    manifest = src_res.manifest
    print("\nAuthoritative C04 Manifest:")
    print(f"  Run ID:        {manifest.run_id}")
    print(f"  Source key:    {manifest.source_key}")
    print(f"  Scope ID:      {manifest.scope_id}")
    print(f"  Outcome:       {manifest.outcome.value}")
    print(f"  Page count:    {manifest.page_count}")
    print(f"  Identities:    {len(manifest.observed_posting_identities)}")
    print(f"  Raw refs:      {len(manifest.raw_response_refs)}")
    print(f"  Cursor in:     {manifest.cursor_in}")
    print(f"  Cursor out:    {manifest.cursor_out}")
    print(f"  Error:         {manifest.error}")

    # 6. Verify evidence in SQLite
    persisted_manifests = storage.raw_postings.get_manifests_for_run(run_id)
    assert len(persisted_manifests) == 1, "Manifest must be persisted in SQLite"
    print(f"\n[OK] Manifest verified in SQLite fetch_manifests table.")

    # Verify captured raw files exist on disk
    for ref in manifest.raw_response_refs:
        raw_bytes = sink.get(ref)
        assert raw_bytes is not None, f"Captured file {ref} must be readable"
        print(f"[OK] Raw capture file verified on disk: {ref} ({len(raw_bytes)} bytes)")

    storage.close()
    print("\n[SUCCESS] INGEST-01 Live Smoke Verification completed successfully.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="INGEST-01 Live Smoke Verification")
    parser.add_argument("--data-dir", type=Path, default=Path("temp_smoke_data"), help="Temporary data directory")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum pages to fetch (max 2)")
    args = parser.parse_args()

    sys.exit(run_ingest_smoke(data_dir=args.data_dir, max_pages=args.max_pages))
