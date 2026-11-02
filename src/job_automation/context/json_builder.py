"""Public builder for CONTEXT-01 full-profile JSON context bundles.

Guarantees:
- Exactly one of (ContextBundle | None, ClassifiedError | None) is non-null.
- Never returns a partial bundle, truncated facts, or silent fallback.
- Enforces strict purpose-based inclusion and mandatory context policy.
- Complete request budget evaluation against effective model window.
"""

from __future__ import annotations

import uuid

from job_automation.context.binding import DefaultJobBindingValidator
from job_automation.context.budget import BudgetEvaluator
from job_automation.context.errors import (
    ContextError,
    ContextUnsupportedError,
    ContextValidationError,
    map_context_exception_to_classified_error,
)
from job_automation.context.measurement import ConservativeCharRatioEstimator
from job_automation.context.ports import (
    JobBindingPort,
    JsonContextBuilderPort,
    PromptRendererPort,
    TokenCounterPort,
)
from job_automation.context.preparation import ProfileContextPreparer
from job_automation.context.records import JsonContextRequest, PreparedProfileContext
from job_automation.context.rendering import DefaultPromptRenderer
from job_automation.context.serialization import (
    build_mandatory_context_strings,
    compute_content_fingerprint,
    serialize_candidate_model_projection,
)
from job_automation.contracts.context import (
    ContextBundle,
    MandatoryFactReason,
    StructuredMandatoryContext,
)
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ClassifiedError
from job_automation.profile.models import SUPPORTED_PURPOSES


class JsonContextBuilder(JsonContextBuilderPort):
    """Synchronous builder for full-profile JSON ContextBundle records."""

    def __init__(
        self,
        preparer: ProfileContextPreparer | None = None,
        renderer: PromptRendererPort | None = None,
        counter: TokenCounterPort | None = None,
        job_binding_validator: JobBindingPort | None = None,
        budget_evaluator: BudgetEvaluator | None = None,
    ) -> None:
        self.preparer = preparer or ProfileContextPreparer()
        self.renderer = renderer or DefaultPromptRenderer()
        self.counter = counter or ConservativeCharRatioEstimator()
        self.job_binding_validator = job_binding_validator or DefaultJobBindingValidator()
        self.budget_evaluator = budget_evaluator or BudgetEvaluator()

    def build(
        self,
        request: JsonContextRequest,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Build C09 ContextBundle from request or return ClassifiedError.

        Invariant: Exactly one returned value is non-null.
        """
        try:
            # 1. Validate request invariants
            if request.purpose not in SUPPORTED_PURPOSES:
                raise ContextValidationError(
                    f"Unsupported inclusion purpose '{request.purpose}'. Must be one of {sorted(SUPPORTED_PURPOSES)}",
                    field_path="purpose",
                    code="UNSUPPORTED_PURPOSE",
                )

            # 2. Check exact measurement requirement
            probe_result = self.counter.count_tokens("test")
            if request.require_exact_measurement and not probe_result.is_exact:
                raise ContextUnsupportedError(
                    f"Exact token measurement is required but configured counter "
                    f"'{probe_result.method}' is a heuristic estimate",
                    field_path="require_exact_measurement",
                )

            # 3. Validate job binding
            self.job_binding_validator.validate_binding(
                canonical_job_id=request.canonical_job_id,
                posting_revision=request.posting_revision,
                posting=request.job_content,
            )

            # 4. Prepare profile context (purpose filtering, chronology anchors, mandatory context)
            prepared: PreparedProfileContext = self.preparer.prepare_context(
                snapshot=request.snapshot,
                purpose=request.purpose,
                explicit_mandatory_ids=request.explicit_mandatory_fact_ids,
            )

            # 5. Serialize lossless candidate model projection
            candidate_json = serialize_candidate_model_projection(prepared)

            # 6. Render complete structured prompt
            rendered = self.renderer.render(request, candidate_json)

            # 7. Measure whole prompt token consumption P
            measurement = self.counter.count_rendered_prompt(rendered)

            # 8. Evaluate whole-prompt budget: P + O + M <= L
            budget_report = self.budget_evaluator.evaluate(
                measurement=measurement,
                context_limit=request.context_limit,
                output_reserve=request.output_reserve,
                safety_allowance=request.safety_allowance,
            )

            # 9. Build structured mandatory context
            structured_reasons: list[MandatoryFactReason] = []
            for fid_str, reasons in prepared.mandatory_reasons.items():
                fid_uuid = uuid.UUID(fid_str)
                for r in reasons:
                    structured_reasons.append(MandatoryFactReason(fact_id=fid_uuid, reason=r))

            structured_mandatory = StructuredMandatoryContext(
                mandatory_fact_ids=prepared.mandatory_fact_ids,
                fact_reasons=structured_reasons,
                chronology=prepared.chronology,
                explicit_eligibility=prepared.explicit_eligibility,
                eligibility_source=prepared.eligibility_source,
            )

            # 10. Compute reproducible content fingerprint
            fingerprint = compute_content_fingerprint(
                candidate_projection_json=candidate_json,
                canonical_job_id=request.canonical_job_id,
                posting_revision=request.posting_revision,
                purpose=request.purpose,
                builder_version=request.builder_version,
                serialization_version=request.serialization_version,
                instruction_text=request.instruction_text,
                requirements=request.requirements,
            )

            # 11. Assemble final C09 ContextBundle
            bundle = ContextBundle(
                strategy=ContextStrategy.JSON,
                profile_version=request.snapshot.profile_version,
                posting_revision=request.posting_revision,
                ordered_facts=prepared.eligible_facts,
                mandatory_context=build_mandatory_context_strings(prepared),
                selected_fact_ids=prepared.eligible_fact_ids,
                query_version=None,
                index_version=None,
                retrieval_settings=None,
                token_budget=max(1, budget_report.candidate_allowance),
                estimated_tokens=budget_report.candidate_tokens,
                warnings=prepared.warnings,
                candidate_id=prepared.candidate_id,
                purpose=request.purpose,
                inclusion_rule_version=prepared.inclusion_rule_version,
                mandatory_policy_version=prepared.mandatory_policy_version,
                builder_version=request.builder_version,
                serialization_version=request.serialization_version,
                mandatory_fact_ids=prepared.mandatory_fact_ids,
                structured_mandatory=structured_mandatory,
                content_fingerprint=fingerprint,
                budget_report=budget_report,
            )

            return bundle, None

        except Exception as exc:
            classified_error = map_context_exception_to_classified_error(exc)
            return None, classified_error

