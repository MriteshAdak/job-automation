"""GEN-01 adapter verifies caller C09/options; durable receipts remain authoritative."""
from job_automation.generation.draft_service import draft_error
from job_automation.contracts.generation import FrozenInputVersions


class DraftGeneratorV2:
    content_schema_version = "2.0"

    def __init__(self, service):
        self.service = service

    def generate_draft(self, request, context):
        seal, error = self.service.inputs.get_seal(request.request_id)
        receipt, context_error = self.service.inputs.get_context_receipt_by_request(request.request_id)
        if error or context_error or seal is None or receipt is None:
            return None, draft_error("draft_dependency_missing")
        opts = seal.options
        expected_versions = FrozenInputVersions(posting_revision=seal.job_snapshot.posting_revision_hash,
                                               profile_version=seal.profile_snapshot.profile_version,
                                               policy_version=seal.manifest.policy_version,
                                               template_version=opts.template_version)
        if (context != receipt.result.bundle or request.canonical_job_id != seal.canonical_job_id
                or request.document_type != opts.document_type or request.target_language != opts.target_language
                or request.template_id != opts.template_id or request.context_strategy != opts.context_strategy
                or request.allow_unavailable_job != opts.allow_unavailable_job
                or (request.frozen_input_versions is not None and request.frozen_input_versions != expected_versions)):
            return None, draft_error("draft_binding_mismatch")
        result = self.service.generate_content(request.request_id)
        return result.draft, result.failure

    def reopen_draft(self, receipt_id, request=None, context=None):
        result = self.service.reopen_draft(receipt_id)
        if result.draft is not None and request is not None:
            if result.draft.request_id != request.request_id:
                return None, draft_error("draft_binding_mismatch")
            return self.generate_draft(request, context)
        return result.draft, result.failure
