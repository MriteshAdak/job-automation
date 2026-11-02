"""Durable observation reader for committed ingestion drafts (RUN-01-S04).

Reads mapped SourceJobDrafts and raw provenance from committed page receipts
or filestore snapshots, ensuring durable replay across process restarts.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from job_automation.contracts.postings import SourceJobDraft
from job_automation.ingestion.models import FetchStageResult, PageReceipt
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class ObservationReader:
    """Reads committed observation drafts from fetch results or storage."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def extract_drafts_from_fetch_result(
        self,
        fetch_stage_result: FetchStageResult,
    ) -> list[tuple[SourceJobDraft, str, int]]:
        """Extract drafts and raw reference metadata from committed page receipts.

        Returns list of (draft, raw_reference, record_index).
        """
        extracted: list[tuple[SourceJobDraft, str, int]] = []
        for src_key, src_res in fetch_stage_result.source_results.items():
            for receipt in src_res.receipts:
                raw_ref = receipt.raw_response_refs[0] if receipt.raw_response_refs else ""
                for idx, dr in enumerate(receipt.draft_results):
                    if dr.draft is not None:
                        ref = dr.raw_reference or raw_ref
                        extracted.append((dr.draft, ref, idx))

        return extracted
