"""Tests for full standalone lifecycle of DefaultGenerationInputService."""

from __future__ import annotations

import uuid

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestStandaloneService:
    def test_full_standalone_lifecycle(self, engine: StorageEngine) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, doc_type=DocumentType.CV)
        engine.generation_requests.create_request(req)

        # 1. prepare_freeze
        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        # 2. inspect_preflight
        preflight = service.inspect_preflight(req.request_id)
        assert preflight is not None
        assert preflight.result == "prepared"
        assert preflight.seal_id == f"seal:{req.request_id}"

        # 3. get_seal
        seal, s_err = service.get_seal(req.request_id)
        assert s_err is None
        assert seal is not None
        assert seal.canonical_job_id == job.canonical_job_id
        assert seal.job_snapshot.normalized_posting.title == "Senior Python Engineer"

        # 4. reopen_freeze
        reopened_manifest, m_err = service.reopen_freeze(manifest.manifest_id)
        assert m_err is None
        assert reopened_manifest is not None
        assert reopened_manifest.manifest_hash == manifest.manifest_hash

        # 5. build_context
        bundle, c_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert c_err is None
        assert bundle is not None
        assert bundle.strategy == ContextStrategy.JSON

        # 6. get_context_receipt_by_request
        ctx_receipt, r_err = service.get_context_receipt_by_request(req.request_id)
        assert r_err is None
        assert ctx_receipt is not None
        assert ctx_receipt.manifest_hash == manifest.manifest_hash

        # 7. reopen_context
        reopened_ctx, ro_err = service.reopen_context(ctx_receipt.receipt_id)
        assert ro_err is None
        assert reopened_ctx is not None
        assert reopened_ctx.result_hash == ctx_receipt.result_hash
        assert reopened_ctx.result.bundle.posting_revision == job.revisions[0].content_hash

