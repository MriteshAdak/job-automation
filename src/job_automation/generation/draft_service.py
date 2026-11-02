"""Standalone GEN-03 content generation through sealed GEN-02 and LLM-01 ports."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from job_automation.contracts.draft_content import DraftContentProposal, DraftDocumentV2, DraftProvenance
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions
from job_automation.contracts.models import ModelCall
from job_automation.generation.draft_grounding import admit
from job_automation.generation.draft_inputs import verify_binding
from job_automation.generation.draft_prompts import HEADINGS, SCHEMA_ID
from job_automation.generation.draft_records import DraftGenerationReceipt, DraftGenerationResult
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.models.schemas import parse_strict_json
from job_automation.models.audit import AuditRecordError
from job_automation.storage.exceptions import StorageError
from job_automation.generation.draft_ports import DraftIdentityVerifier
from job_automation.generation.input_ports import StandaloneGenerationInputService
from job_automation.storage.repositories.draft_content import DraftContentRepository
from job_automation.contracts.interfaces import ModelProvider
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.schemas import LocalSchemaRegistry


def draft_error(code, category=ErrorCategory.VALIDATION):
    return ClassifiedError.from_category(category, "Draft generation could not complete", details={"reason_code": code})


class DraftContentService:
    """No worker/Salesforce dependency, no selector rerun, no independent retry loop.

    identity_verifier(call) is a REQUIRED trusted deployment port, bound to the
    invocation, returning verified (identifier, digest). MODEL-01 owns its actual
    runtime implementation. A mutable tag or missing observed digest fails closed.
    """
    def __init__(self, inputs: StandaloneGenerationInputService, repository: DraftContentRepository,
                 provider: ModelProvider, input_resolver: InMemoryInputResolver,
                 schema_registry: LocalSchemaRegistry, identity_verifier: DraftIdentityVerifier | None = None):
        self.inputs, self.repository, self.provider = inputs, repository, provider
        self.input_resolver, self.schema_registry = input_resolver, schema_registry
        self.identity_verifier = identity_verifier

    def generate_content(self, request_id: uuid.UUID) -> DraftGenerationResult:
        try:
            seal, context, recipe, binding_hash = verify_binding(self.inputs, request_id)
            key = compute_sha256_digest({"request_id": str(request_id), "binding_hash": binding_hash, "recipe_hash": recipe.recipe_hash})
            saved = self.repository.get_by_request(request_id)
            if saved is not None:
                return self._verified_saved(saved, binding_hash, key)
            schema = self.schema_registry.resolve(SCHEMA_ID)
            if schema.version != "1.0" or schema.digest != recipe.proposal_schema_digest or schema.model_cls is not DraftContentProposal or compute_sha256_digest(schema.json_schema) != schema.digest:
                raise ValueError("draft_schema_mismatch")
            call_id, receipt_id = uuid.uuid4(), uuid.uuid4()
            bound = self.input_resolver.bind_generation(call_id, context.result.rendered_prompt.full_prompt)
            call = ModelCall(
                call_id=call_id, operation_type=f"draft_{recipe.document_type}",
                model_identifier=recipe.model_identifier, model_digest=recipe.model_digest,
                prompt_version=recipe.prompt_version, generation_settings=recipe.generation_settings,
                context_limit=recipe.context_limit, input_fingerprint=bound.input_fingerprint,
                requested_schema=SCHEMA_ID,
            )
            started = datetime.now(timezone.utc)
            self.repository.start_attempt(receipt_id, request_id, key, binding_hash, seal.seal_id, context.receipt_id, started, call)
            model_result, draft, error = None, None, None
            try:
                if self.identity_verifier is None or self.identity_verifier(call) != (recipe.model_identifier, recipe.model_digest):
                    raise ValueError("model_identity_unverified")
                model_result = self.provider.generate(call)
                if model_result.call_id != call_id or model_result.model_identifier != recipe.model_identifier:
                    raise ValueError("draft_model_identity_mismatch")
                if model_result.error:
                    # Provider diagnostics may contain output validation details; retain
                    # only its category and bounded safe reason at this public boundary.
                    error = draft_error("draft_model_failed", model_result.error.category)
                else:
                    if model_result.model_digest != recipe.model_digest:
                        raise ValueError("model_identity_unverified")
                    audit = self.repository.get_call_audit(call_id)
                    if (audit.outcome != "success" or audit.input_fingerprint != call.input_fingerprint
                            or audit.schema_id != SCHEMA_ID or audit.schema_version != "1.0"
                            or audit.observed_model != recipe.model_identifier or audit.observed_digest != recipe.model_digest
                            or audit.effective_settings.get("num_predict") != recipe.output_reserve
                            or audit.effective_settings.get("num_ctx") != recipe.context_limit):
                        raise ValueError("draft_audit_corrupt")
                    if model_result.output_text is None or len(model_result.output_text) > 200_000:
                        raise ValueError("draft_output_invalid")
                    parsed = parse_strict_json(model_result.output_text)
                    proposal = DraftContentProposal.model_validate_json(json.dumps(parsed))
                    if model_result.parsed_output != proposal.model_dump(mode="json"):
                        raise ValueError("draft_output_invalid")
                    protected, issues = admit(proposal, seal, context, recipe)
                    provenance = DraftProvenance(
                        seal_id=seal.seal_id, seal_hash=seal.seal_hash, binding_hash=binding_hash,
                        context_receipt_id=context.receipt_id, context_hash=compute_sha256_digest(context),
                        recipe_hash=recipe.recipe_hash, prompt_version=recipe.prompt_version,
                        schema_id=SCHEMA_ID, schema_digest=recipe.proposal_schema_digest,
                        input_fingerprint=call.input_fingerprint, model_identifier=recipe.model_identifier,
                        model_digest=recipe.model_digest, model_call_ref=call_id, receipt_id=receipt_id,
                    )
                    draft = DraftDocumentV2(
                        sections=proposal.sections, claims=proposal.claims, subjective_blocks=proposal.subjective_blocks,
                        draft_id=uuid.uuid4(), request_id=request_id, document_type=seal.options.document_type,
                        document_version=f"draft:{receipt_id}", target_language=recipe.target_language,
                        template_id=recipe.template_id, template_version=recipe.template_version,
                        template_content_digest=recipe.template_content_digest,
                        headings={s.section_id: HEADINGS[recipe.target_language][s.heading_key] for s in proposal.sections},
                        protected_values=protected, review_issues=issues, provenance=provenance,
                        frozen_inputs=FrozenInputVersions(
                            posting_revision=seal.job_snapshot.posting_revision_hash,
                            profile_version=seal.profile_snapshot.profile_version,
                            policy_version=seal.manifest.policy_version, template_version=recipe.template_version,
                        ),
                    )
            except ValidationError:
                error = draft_error("draft_output_invalid", ErrorCategory.MODEL_OUTPUT)
            except (ValueError, TypeError, KeyError) as exc:
                code = str(exc)
                if code not in {"model_identity_unverified", "draft_model_identity_mismatch", "draft_grounding_failed", "draft_output_invalid", "draft_audit_missing", "draft_audit_corrupt"}:
                    code = "draft_output_invalid"
                error = draft_error(code, ErrorCategory.MODEL_OUTPUT)
            except AuditRecordError:
                error = draft_error("draft_audit_failed")
            except Exception:
                # Runtime/audit exceptions must never complete a successful receipt.
                error = draft_error("draft_provider_failed", ErrorCategory.TRANSIENT_SERVICE)
            receipt = DraftGenerationReceipt(
                receipt_id=receipt_id, request_id=request_id, logical_key=key, binding_hash=binding_hash,
                recipe_hash=recipe.recipe_hash, seal_id=seal.seal_id, context_receipt_id=context.receipt_id,
                started_at=started, completed_at=datetime.now(timezone.utc), call=call, model_result=model_result,
                draft=draft, content_hash=compute_sha256_digest(draft) if draft else None, error=error,
                selected_fact_ids=context.result.bundle.selected_fact_ids,
                cited_fact_ids=sorted({c.evidence_reference.fact_id for c in draft.claims if c.claim_subject == "candidate"}) if draft else [],
            )
            saved = self.repository.finish_attempt(receipt)
            return self._verified_saved(saved, binding_hash, key)
        except sqlite3.Error as exc:
            category = ErrorCategory.CAPACITY if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL else ErrorCategory.VALIDATION
            return DraftGenerationResult(error=draft_error("draft_storage_failed", category))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, StorageError) as exc:
            code = str(exc)
            if code not in {"draft_dependency_missing", "recipe_unavailable", "frozen_input_corrupt", "draft_binding_mismatch", "draft_context_budget", "draft_schema_mismatch", "draft_receipt_missing", "draft_receipt_corrupt", "draft_content_corrupt"}:
                code = "draft_binding_mismatch"
            category = ErrorCategory.CONTEXT_BUDGET if code == "draft_context_budget" else ErrorCategory.VALIDATION
            if code in {"draft_dependency_missing", "recipe_unavailable", "draft_schema_mismatch"}:
                category = ErrorCategory.MISSING_CONFIGURATION
            return DraftGenerationResult(error=draft_error(code, category))

    def _verified_saved(self, receipt, binding_hash, key):
        if receipt.binding_hash != binding_hash or receipt.logical_key != key:
            raise ValueError("draft_binding_mismatch")
        return DraftGenerationResult(receipt=receipt)

    def reopen_draft(self, receipt_id: uuid.UUID) -> DraftGenerationResult:
        try:
            receipt = self.repository.reopen(receipt_id)
            _, _, recipe, binding_hash = verify_binding(self.inputs, receipt.request_id)
            key = compute_sha256_digest({"request_id": str(receipt.request_id), "binding_hash": binding_hash, "recipe_hash": recipe.recipe_hash})
            return self._verified_saved(receipt, binding_hash, key)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, sqlite3.Error, StorageError):
            return DraftGenerationResult(error=draft_error("draft_receipt_corrupt"))
