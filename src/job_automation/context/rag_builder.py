"""RAG context builder: retrieval orchestration, mandatory-first packing, and whole-prompt budgeting."""

from __future__ import annotations

import json
import uuid
from typing import Sequence

from job_automation.context.budget import BudgetEvaluator
from job_automation.context.errors import (
    ContextBudgetOverflowError,
    ContextError,
    ContextPermissionError,
    ContextUnsupportedError,
    map_context_exception_to_classified_error,
)
from job_automation.context.fusion import ReciprocalRankFuser
from job_automation.context.index_identity import (
    compute_embedding_space_fingerprint,
)
from job_automation.context.index_ports import IndexHandlePort
from job_automation.context.keyword_retrieval import KeywordRetriever
from job_automation.context.measurement import ConservativeCharRatioEstimator
from job_automation.context.ports import PromptRendererPort, TokenCounterPort
from job_automation.context.queries import DefaultQueryBuilder
from job_automation.context.query_embeddings import QueryEmbeddingCoordinator
from job_automation.context.records import PreparedProfileContext, RenderedPrompt
from job_automation.context.rendering import DefaultPromptRenderer
from job_automation.context.retrieval_settings import (
    DEFAULT_RETRIEVAL_SETTINGS,
    RetrievalSettings,
)
from job_automation.context.semantic_retrieval import SemanticRetriever
from job_automation.context.serialization import (
    build_mandatory_context_strings,
    compute_content_fingerprint,
    serialize_candidate_fact,
)
from job_automation.contracts.context import (
    ContextBundle,
    MandatoryFactReason,
    StructuredMandatoryContext,
)
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.profile import CandidateFact
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
    FusedCandidate,
    RequirementQuerySet,
    RetrievalHit,
    RetrievalTrace,
)


def _serialize_rag_candidate_projection(
    prepared: PreparedProfileContext,
    facts: list[CandidateFact],
) -> str:
    """Serialize admitted candidate facts into deterministic model projection JSON."""
    projection = {
        "candidate_id": str(prepared.candidate_id),
        "profile_version": prepared.profile_version,
        "purpose": prepared.purpose,
        "inclusion_rule_version": prepared.inclusion_rule_version,
        "mandatory_policy_version": prepared.mandatory_policy_version,
        "explicit_eligibility": prepared.explicit_eligibility.model_dump(mode="json"),
        "eligibility_source": prepared.eligibility_source,
        "chronology_anchors": [
            anchor.model_dump(mode="json") for anchor in prepared.chronology
        ],
        "facts": [serialize_candidate_fact(f) for f in facts],
    }
    return json.dumps(projection, indent=2, sort_keys=True, ensure_ascii=False)


class RAGContextBuilder:
    """Orchestrates hybrid retrieval, reciprocal rank fusion, parent preservation, and RAG budgeting."""

    def __init__(
        self,
        counter: TokenCounterPort | None = None,
        renderer: PromptRendererPort | None = None,
        budget_evaluator: BudgetEvaluator | None = None,
        keyword_retriever: KeywordRetriever | None = None,
        semantic_retriever: SemanticRetriever | None = None,
        fuser: ReciprocalRankFuser | None = None,
        query_builder: DefaultQueryBuilder | None = None,
    ) -> None:
        self.counter = counter or ConservativeCharRatioEstimator()
        self.renderer = renderer or DefaultPromptRenderer()
        self.budget_evaluator = budget_evaluator or BudgetEvaluator()
        self.keyword_retriever = keyword_retriever or KeywordRetriever()
        self.semantic_retriever = semantic_retriever or SemanticRetriever()
        self.fuser = fuser or ReciprocalRankFuser()
        self.query_builder = query_builder or DefaultQueryBuilder()

    def build_rag_context(
        self,
        request: ContextSelectionRequest,
        prepared: PreparedProfileContext,
        index_handle: IndexHandlePort,
        model_provider: ModelProvider | None = None,
    ) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
        """Execute hybrid retrieval over active index, pack within budget, and assemble C09 bundle."""
        try:
            # 1. Exact measurement check
            if request.require_exact_measurement:
                probe = self.counter.count_tokens("probe")
                if not probe.is_exact:
                    raise ContextUnsupportedError(
                        f"Exact token measurement is required but configured counter '{probe.method}' is a heuristic estimate",
                        field_path="require_exact_measurement",
                    )

            settings = request.retrieval_settings or DEFAULT_RETRIEVAL_SETTINGS
            warnings: list[str] = list(prepared.warnings)
            channel_statuses: dict[str, str] = {}

            # 2. Build deterministic requirement queries
            query_set: RequirementQuerySet = self.query_builder.build_queries(
                requirements=request.requirements,
                fallback_job_text=request.job_content.description_clean,
            )
            has_usable_queries = any(len(q.terms) > 0 for q in query_set.queries)
            if not query_set.queries or not has_usable_queries:
                warnings.append("NO_OPTIONAL_QUERY")

            # 3. Query embedding compatibility check & execution (semantic channel)
            query_vectors: dict[str, list[float]] = {}
            if query_set.queries and request.embedding_config is not None:
                # Validate query embedding space matches index manifest
                query_space_fp = compute_embedding_space_fingerprint(
                    request.embedding_config,
                    index_handle.manifest.index_settings,
                )
                index_handle.validate_query_embedding_space(query_space_fp)

                if model_provider is not None:
                    coordinator = QueryEmbeddingCoordinator(model_provider)
                    query_vectors, _ = coordinator.embed_queries(
                        query_set=query_set,
                        embedding_config=request.embedding_config,
                        normalize=(index_handle.manifest.index_settings.normalization == "l2"),
                    )
                    channel_statuses["semantic"] = "ok"
                else:
                    channel_statuses["semantic"] = "skipped_no_provider"
            else:
                channel_statuses["semantic"] = "no_queries_or_config"

            # 4. Keyword channel execution
            kw_hits: list[RetrievalHit] = []
            if query_set.queries:
                kw_retriever = KeywordRetriever(settings=settings)
                kw_hits = kw_retriever.retrieve(query_set, index_handle)
                channel_statuses["keyword"] = "ok"
            else:
                channel_statuses["keyword"] = "no_queries"

            # 5. Semantic channel execution
            sem_hits: list[RetrievalHit] = []
            if query_vectors:
                sem_retriever = SemanticRetriever(settings=settings)
                sem_hits = sem_retriever.retrieve(query_set, query_vectors, index_handle)

            all_hits = kw_hits + sem_hits
            if not all_hits and query_set.queries:
                warnings.append("NO_RETRIEVAL_HITS")

            # 6. Reciprocal Rank Fusion & multi-query aggregation
            fuser = ReciprocalRankFuser(settings=settings)
            fused_candidates: list[FusedCandidate] = fuser.fuse(all_hits)

            # 7. Mandatory Context First: reserve mandatory context
            mandatory_facts = list(prepared.mandatory_facts)
            mandatory_fact_ids = set(prepared.mandatory_fact_ids)

            # Check that mandatory context alone fits the whole prompt window
            mand_json = _serialize_rag_candidate_projection(prepared, mandatory_facts)
            mand_rendered = self.renderer.render(request.to_json_context_request(), mand_json)
            mand_meas = self.counter.count_rendered_prompt(mand_rendered)

            fixed_overhead = (
                mand_meas.instruction_tokens
                + mand_meas.job_tokens
                + mand_meas.framing_tokens
                + request.output_reserve
                + request.safety_allowance
            )
            candidate_allowance = request.context_limit - fixed_overhead
            if candidate_allowance <= 0 or (mand_meas.total_input_tokens + request.output_reserve + request.safety_allowance) > request.context_limit:
                total_demand = mand_meas.total_input_tokens + request.output_reserve + request.safety_allowance
                deficit = max(1, total_demand - request.context_limit)
                raise ContextBudgetOverflowError(
                    f"Mandatory context alone exceeds configured context window by {deficit} token{'s' if deficit != 1 else ''}; "
                    f"complete RAG context was not produced",
                    field_path="context_budget",
                    details={
                        "overflow": deficit,
                        "total_input_tokens": mand_meas.total_input_tokens,
                        "candidate_tokens": mand_meas.candidate_tokens,
                        "candidate_allowance": candidate_allowance,
                        "effective_window": request.context_limit,
                    },
                )

            # 8. Optional Candidate Packing & Ancestor Resolution
            all_facts_by_id = {f.fact_id: f for f in request.snapshot.evidence_records}
            permitted_fact_ids = set(prepared.eligible_fact_ids)

            admitted_facts: list[CandidateFact] = list(mandatory_facts)
            admitted_fact_ids: set[uuid.UUID] = set(f.fact_id for f in mandatory_facts)
            admitted_optional_count = 0
            budget_omitted_ids: list[uuid.UUID] = []
            updated_fused_candidates: list[FusedCandidate] = []

            for candidate in fused_candidates:
                if candidate.fact_id in admitted_fact_ids:
                    # Already included as mandatory or prior ancestor
                    updated_fused_candidates.append(
                        candidate.model_copy(update={"is_admitted": True})
                    )
                    continue

                if admitted_optional_count >= settings.top_k:
                    # Optional top-k slot limit reached
                    updated_fused_candidates.append(
                        candidate.model_copy(
                            update={
                                "is_admitted": False,
                                "omission_reason": "top_k_limit_reached",
                            }
                        )
                    )
                    continue

                if candidate.fact_id not in permitted_fact_ids:
                    # Fact is restricted from target purpose
                    updated_fused_candidates.append(
                        candidate.model_copy(
                            update={
                                "is_admitted": False,
                                "omission_reason": "purpose_restricted",
                            }
                        )
                    )
                    continue

                primary_fact = all_facts_by_id[candidate.fact_id]

                # Resolve ancestor chain root-to-leaf
                ancestors: list[CandidateFact] = []
                curr_id = primary_fact.parent_id
                parent_restricted = False

                while curr_id is not None:
                    curr_fact = all_facts_by_id.get(curr_id)
                    if curr_fact is None:
                        break

                    if curr_id not in permitted_fact_ids:
                        # Restricted parent
                        if settings.strict_parents or curr_id in request.explicit_mandatory_fact_ids:
                            raise ContextPermissionError(
                                f"Parent fact '{curr_id}' of fact '{primary_fact.fact_id}' is restricted from purpose '{request.purpose}'",
                                field_path="snapshot.evidence_records",
                                details={"parent_id": str(curr_id), "fact_id": str(primary_fact.fact_id)},
                            )
                        else:
                            warnings.append(
                                f"Parent fact '{curr_id}' of fact '{primary_fact.fact_id}' is restricted and omitted from '{request.purpose}' view"
                            )
                            parent_restricted = True
                            break
                    else:
                        ancestors.append(curr_fact)

                    curr_id = curr_fact.parent_id

                ancestors.reverse()  # root to leaf order

                # Group to add: unadmitted permitted ancestors + primary fact
                group_to_add: list[CandidateFact] = []
                for anc in ancestors:
                    if anc.fact_id not in admitted_fact_ids and anc not in group_to_add:
                        group_to_add.append(anc)
                if primary_fact.fact_id not in admitted_fact_ids and primary_fact not in group_to_add:
                    group_to_add.append(primary_fact)

                # Test whole-prompt budget fit for adding this group
                tentative_facts = admitted_facts + group_to_add
                tentative_json = _serialize_rag_candidate_projection(prepared, tentative_facts)
                tentative_rendered = self.renderer.render(request.to_json_context_request(), tentative_json)
                tentative_meas = self.counter.count_rendered_prompt(tentative_rendered)
                tentative_demand = (
                    tentative_meas.total_input_tokens
                    + request.output_reserve
                    + request.safety_allowance
                )

                if tentative_demand <= request.context_limit:
                    # Fits! Admit group
                    admitted_facts.extend(group_to_add)
                    for f in group_to_add:
                        admitted_fact_ids.add(f.fact_id)
                    admitted_optional_count += 1
                    updated_fused_candidates.append(
                        candidate.model_copy(update={"is_admitted": True})
                    )
                else:
                    # Omit whole group due to budget constraint
                    budget_omitted_ids.append(candidate.fact_id)
                    warnings.append(f"OPTIONAL_BUDGET_OMISSION:{candidate.fact_id}")
                    updated_fused_candidates.append(
                        candidate.model_copy(
                            update={
                                "is_admitted": False,
                                "omission_reason": "budget_omitted",
                            }
                        )
                    )

            # 9. Final prompt render and whole-prompt measurement
            final_json = _serialize_rag_candidate_projection(prepared, admitted_facts)
            final_rendered = self.renderer.render(request.to_json_context_request(), final_json)
            final_meas = self.counter.count_rendered_prompt(final_rendered)

            if not final_meas.is_exact:
                warnings.append("TOKEN_COUNT_ESTIMATED")

            budget_report = self.budget_evaluator.evaluate(
                measurement=final_meas,
                context_limit=request.context_limit,
                output_reserve=request.output_reserve,
                safety_allowance=request.safety_allowance,
            )

            # 10. Build structured mandatory context
            structured_reasons: list[MandatoryFactReason] = []
            for fid_str, r_list in prepared.mandatory_reasons.items():
                fid_uuid = uuid.UUID(fid_str)
                for r in r_list:
                    structured_reasons.append(MandatoryFactReason(fact_id=fid_uuid, reason=r))

            structured_mandatory = StructuredMandatoryContext(
                mandatory_fact_ids=prepared.mandatory_fact_ids,
                fact_reasons=structured_reasons,
                chronology=prepared.chronology,
                explicit_eligibility=prepared.explicit_eligibility,
                eligibility_source=prepared.eligibility_source,
            )

            # 11. Compute construction fingerprint
            query_version = f"{query_set.recipe_version}:{query_set.query_set_fingerprint}"
            index_version = index_handle.manifest.artifact_fingerprint
            settings_fp = settings.compute_settings_fingerprint()

            fingerprint = compute_content_fingerprint(
                candidate_projection_json=final_json,
                canonical_job_id=request.canonical_job_id,
                posting_revision=request.posting_revision,
                purpose=request.purpose,
                builder_version=request.builder_version,
                serialization_version=request.serialization_version,
                instruction_text=request.instruction_text,
                requirements=request.requirements,
            )

            # 12. Build RetrievalTrace
            trace = RetrievalTrace(
                query_version=query_version,
                index_version=index_version,
                channel_statuses=channel_statuses,
                retrieved_hits=all_hits,
                fused_candidates=updated_fused_candidates,
                selected_fact_ids=[f.fact_id for f in admitted_facts],
                retrieved_fact_ids=sorted(list(set(h.fact_id for h in all_hits)), key=str),
                mandatory_fact_ids=prepared.mandatory_fact_ids,
                budget_omitted_fact_ids=budget_omitted_ids,
                warnings=sorted(list(set(warnings))),
            )

            # 13. Assemble final C09 ContextBundle
            bundle = ContextBundle(
                strategy=ContextStrategy.RAG,
                profile_version=request.snapshot.profile_version,
                posting_revision=request.posting_revision,
                ordered_facts=admitted_facts,
                mandatory_context=build_mandatory_context_strings(prepared),
                selected_fact_ids=[f.fact_id for f in admitted_facts],
                query_version=query_version,
                index_version=index_version,
                retrieval_settings=settings.model_dump(mode="json"),
                token_budget=max(1, budget_report.candidate_allowance),
                estimated_tokens=budget_report.candidate_tokens,
                warnings=sorted(list(set(warnings))),
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
                retrieval_audit=trace.model_dump(mode="json"),
            )

            result = ContextSelectionResult(
                bundle=bundle,
                rendered_prompt=final_rendered,
                trace=trace,
                construction_fingerprint=fingerprint,
            )
            return result, None

        except Exception as exc:
            return None, map_context_exception_to_classified_error(exc)
