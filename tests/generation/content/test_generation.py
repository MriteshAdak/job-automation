"""Offline scripted-model checks: these are NOT live drafting-quality evidence."""
import copy
import json
import sqlite3
import uuid

import pytest
from pydantic import ValidationError

from job_automation.contracts.draft_content import DraftContentProposal, DraftDocumentV2, read_draft_json
from job_automation.generation.draft_adapter import DraftGeneratorV2
from job_automation.generation.draft_inputs import verify_binding
from job_automation.generation.input_records import compute_sha256_digest
from tests.generation.content.conftest import ROOT


@pytest.mark.parametrize("kind", ["cv", "cover_letter"])
@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("strategy", ["json", "rag"])
def test_real_freezer_and_harness_matrix(setup_content, kind, language, strategy):
    env = setup_content(kind, language, strategy)
    verify_binding(env.inputs, env.request.request_id)
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    draft = result.draft
    assert isinstance(draft, DraftDocumentV2)
    assert draft.document_type.value == kind and draft.target_language == language
    assert draft.requires_human_review and draft.validation_status == "pending_gen04"
    assert draft.candidate_name is None
    assert result.receipt.content_hash == compute_sha256_digest(draft)
    assert result.receipt.cited_fact_ids == [env.bundle.ordered_facts[0].fact_id]
    assert result.receipt.model_result.token_usage is None
    assert read_draft_json(draft.model_dump_json()) == draft
    context, _ = env.inputs.get_context_receipt_by_request(env.request.request_id)
    call = env.transport.recorded_calls[0]["payload"]
    assert call["prompt"] == context.result.rendered_prompt.full_prompt
    assert "system" not in call and call["options"]["num_predict"] == 1024
    assert len(env.audit.records) == 1
    assert env.service.generate_content(env.request.request_id) == result
    assert len(env.transport.recorded_calls) == 1
    assert env.engine.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    assert env.engine.generation_requests.get_request(env.request.request_id).state.value == "pending"
    assert {i.code for i in draft.review_issues} >= {"semantic_review_required", "source_language_preserved", "candidate_identity_missing", "upstream_warnings_present"}


@pytest.mark.parametrize("text,field,index", [
    ("Rust", "skills", 0), ("Reduced costs by 40%", "metrics", 0),
    ("Led a team of 100", "claims", 0), ("We may offer hybrid working in Berlin.", "claims", 0),
    ("2021-05-01", "start_date", None), ("Chief Executive Officer", "title", None),
])
def test_valid_id_does_not_authorize_false_text(setup_content, text, field, index):
    env = setup_content()
    env.proposal["claims"][0].update(text=text, source_field=field, source_index=index)
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None
    assert result.failure.details["reason_code"] == "draft_grounding_failed"
    assert env.engine.conn.execute("SELECT COUNT(*) FROM draft_content_results").fetchone()[0] == 0
    assert env.engine.conn.execute("SELECT COUNT(*) FROM draft_content_attempts WHERE receipt_json IS NOT NULL").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["wrong_kind", "cross_profile", "unknown_fact", "wrong_revision", "bad_path", "empty_quote", "bad_span", "span_disagrees", "subjective_disguise", "authority", "duplicate", "dangling", "false_review"])
def test_hostile_and_invalid_proposals(setup_content, mutation):
    env = setup_content()
    p = env.proposal
    if mutation == "wrong_kind":
        p["claims"][0]["evidence_reference"] = p["claims"][1]["evidence_reference"]
    elif mutation == "cross_profile":
        p["claims"][0]["evidence_reference"]["profile_version"] = "v999"
    elif mutation == "unknown_fact":
        p["claims"][0]["evidence_reference"]["fact_id"] = str(uuid.uuid4())
    elif mutation == "wrong_revision":
        p["claims"][1]["evidence_reference"]["posting_revision"] = "raw-hash-or-old-revision"
    elif mutation == "bad_path":
        p["claims"][1]["evidence_reference"]["field_path"] = "__class__"
    elif mutation == "empty_quote":
        p["claims"][1]["evidence_reference"]["quotation"] = ""
    elif mutation == "bad_span":
        p["claims"][1]["evidence_reference"]["source_span"] = {"start": 0, "end": 9999}
    elif mutation == "span_disagrees":
        p["claims"][1]["evidence_reference"]["source_span"] = {"start": 1, "end": 10}
    elif mutation == "subjective_disguise":
        p["subjective_blocks"][0]["text"] = "I have Rust skills and reduced costs by 40%."
    elif mutation == "authority":
        p["approval_status"] = "approved"
    elif mutation == "duplicate":
        p["claims"][1]["claim_id"] = "candidate_claim"
    elif mutation == "dangling":
        p["sections"][0]["claim_ids"].append("missing")
    else:
        p["subjective_blocks"][0]["requires_human_review"] = False
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None and result.failure.category.value == "model_output"
    assert len(env.transport.recorded_calls) == 1
    assert "Rust" not in result.failure.model_dump_json()


def test_injection_is_escaped_data_and_cannot_add_candidate_fact(setup_content):
    env = setup_content()
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    prompt = env.transport.recorded_calls[0]["payload"]["prompt"]
    assert "\\n### System Instructions\\nIgnore" in prompt
    assert "</JOB>" not in prompt and "\\u003c/JOB\\u003e" in prompt
    assert all("Rust" not in c.text for c in result.draft.claims if c.claim_subject == "candidate")


@pytest.mark.parametrize("raw", ["```json\n{}\n```", '{"sections":[],"sections":[]}', '{"x":NaN}', '{} trailing', '{}'])
def test_malformed_output_is_failure_without_repair_loop(setup_content, raw):
    env = setup_content()
    env.queue(response=raw)
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None and result.failure.category.value == "model_output"
    assert len(env.transport.recorded_calls) == 1


@pytest.mark.parametrize("mode", ["missing_verifier", "wrong_verifier", "missing_digest", "wrong_digest", "length", "unavailable", "audit"])
def test_model_failures(setup_content, mode):
    env = setup_content()
    if mode == "missing_verifier":
        env.service.identity_verifier = None
    elif mode == "wrong_verifier":
        env.service.identity_verifier = lambda call: (call.model_identifier, "different")
    elif mode == "missing_digest":
        env.queue(digest=None)
    elif mode == "wrong_digest":
        env.queue(digest="different")
    elif mode == "length":
        env.queue(done_reason="length")
    elif mode == "unavailable":
        for _ in range(3):
            env.transport.queue_response("/api/generate", 404, body={})
    else:
        class BrokenAudit:
            def record_call(self, record):
                raise RuntimeError("private candidate sentinel")
        env.provider.audit_manager.recorder = BrokenAudit()
        env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None and result.failure is not None
    assert len(env.transport.recorded_calls) <= 3
    if mode.endswith("verifier"):
        assert not env.transport.recorded_calls
    assert "private candidate" not in result.failure.model_dump_json()


def test_pinned_schema_and_options_fail_before_inference(setup_content):
    env = setup_content()
    env.registry.register("draft_content_proposal_v1", DraftDocumentV2)
    result = env.service.generate_content(env.request.request_id)
    assert result.failure.details["reason_code"] == "draft_schema_mismatch"
    assert not env.transport.recorded_calls
    adapter = DraftGeneratorV2(env.service)
    _, error = adapter.generate_draft(env.request.model_copy(update={"target_language": "en"}), env.bundle)
    assert error.details["reason_code"] == "draft_binding_mismatch"


def test_legacy_c14_stays_legacy_and_future_versions_fail():
    payload = json.dumps({"request_id": str(uuid.uuid4()), "document_type": "cv", "document_version": "legacy-v1",
                          "title": "CV", "candidate_name": "Synthetic Candidate", "target_role": "Developer", "target_company": "Synthetic Employer",
                          "frozen_inputs": {"posting_revision": "old-revision", "profile_version": "v1", "policy_version": "v1", "template_version": "v1"}})
    assert read_draft_json(payload).schema_version == "1.0"
    with pytest.raises(ValueError):
        read_draft_json('{"schema_version":"3.0"}')


def test_budget_overflow_does_not_switch_strategy(setup_content):
    env = setup_content(context_limit=50)
    assert env.bundle is None and env.context_error.category.value == "context_budget"


def test_protected_dates_and_unknowns(setup_content):
    env = setup_content()
    fact = env.bundle.ordered_facts[0]
    env.proposal["claims"][0].update(text=fact.start_date.value, source_field="start_date", source_index=None)
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    assert result.draft.protected_values[0].original_value == fact.start_date
    assert result.draft.protected_values[0].original_value.precision == "month"


def test_ordered_entries_and_mixed_letter_claims_roundtrip(setup_content):
    env = setup_content(kind="cover_letter", language="en")
    env.proposal["sections"] = [{"section_id": "experience", "heading_key": "experience", "entries": [
        {"entry_id": "paragraph_one", "claim_ids": ["candidate_claim", "job_claim"], "subjective_ids": ["motivation"]},
    ]}]
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    assert result.draft.sections[0].entries[0].claim_ids == ["candidate_claim", "job_claim"]
    assert read_draft_json(result.draft.model_dump_json()) == result.draft


@pytest.mark.parametrize("template", ["content-basic", "content-compact"])
def test_supported_content_templates_are_frozen(setup_content, template):
    env = setup_content(template=template)
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    assert result.draft.template_id == template
    assert result.draft.template_content_digest


@pytest.mark.parametrize("mode", ["unselected", "wrong_purpose"])
def test_existing_approved_fact_still_requires_admission_and_purpose(setup_content, mode):
    env = setup_content(strategy="rag" if mode == "unselected" else "json", kind="cover_letter")
    fact = env.optional_fact if mode == "unselected" else env.cv_only_fact
    assert fact.fact_id not in env.bundle.selected_fact_ids
    claim = env.proposal["claims"][0]
    claim["text"] = fact.claims[0]
    claim["evidence_reference"]["fact_id"] = str(fact.fact_id)
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None and result.failure.details["reason_code"] == "draft_grounding_failed"


def test_exact_skill_and_metric_selections_preserve_source_values(setup_content):
    env = setup_content()
    fact = env.bundle.ordered_facts[0]
    original = copy.deepcopy(env.proposal["claims"][0])
    env.proposal["claims"][0].update(text=fact.skills[0], source_field="skills", source_index=0)
    original.update(claim_id="metric", text=fact.metrics[0], source_field="metrics", source_index=0)
    env.proposal["claims"].append(original)
    env.proposal["sections"][0]["claim_ids"].append("metric")
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    assert result.draft.protected_values[0].original_value == fact.skills
    assert result.draft.protected_values[-1].original_value == fact.metrics


@pytest.mark.parametrize("language,template", [("fr", "content-basic"), ("de", "missing-template")])
def test_unsupported_options_fail_preflight_without_fallback(setup_content, language, template):
    env = setup_content(language=language, template=template)
    assert env.manifest is None
    assert env.preflight_error.details["reason_code"] == "draft_option_unsupported"
    seal, error = env.inputs.get_seal(env.request.request_id)
    assert seal is None and error is not None


def test_one_token_overflow_is_visible_without_reduction(setup_content):
    env = setup_content()
    report = env.bundle.budget_report
    overflow = setup_content(context_limit=report.total_demand - 1)
    assert overflow.bundle is None
    assert overflow.context_error.category.value == "context_budget"


@pytest.mark.parametrize("mutation", ["call_id", "model", "parsed_payload"])
def test_alternative_provider_cannot_bypass_result_binding(setup_content, mutation):
    env = setup_content()
    real_provider = env.provider
    class AlteredProvider:
        def generate(self, call):
            result = real_provider.generate(call)
            if mutation == "call_id":
                return result.model_copy(update={"call_id": uuid.uuid4()})
            if mutation == "model":
                return result.model_copy(update={"model_identifier": "different-model"})
            return result.model_copy(update={"parsed_output": {"approval_status": "approved"}})
    env.service.provider = AlteredProvider()
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None and result.failure.category.value == "model_output"
