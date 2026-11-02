"""Tests for context budget accounting and token limit enforcement (LLM-01-S03)."""

from __future__ import annotations

import uuid

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.models import ModelCall
from job_automation.models.budget import (
    CharacterRatioTokenizer,
    ContextBudgetManager,
    ExactTokenCounter,
)
from job_automation.models.configuration import (
    ModelCapabilities,
    ModelProviderSettings,
)
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class TestContextBudget:
    def test_acceptance_criteria_896_fits_897_overflows(self) -> None:
        """With synthetic 1,024-token ceiling and 128 reserved output tokens, 896 fits; 897 returns context_budget."""
        settings = ModelProviderSettings(
            default_context_ceiling=1024,
            reserved_output_tokens=128,
            safety_margin_tokens=0,
            models={
                "synthetic-model": ModelCapabilities(
                    model_identifier="synthetic-model",
                    max_context_tokens=1024,
                    default_output_reserve=128,
                )
            },
        )

        # Injected exact token counter: counts length of prompt string as tokens
        exact_counter = ExactTokenCounter(count_fn=lambda text: len(text))
        budget_mgr = ContextBudgetManager(settings, tokenizer=exact_counter)

        # 896 tokens input: 896 + 128 reserve = 1024 <= 1024 (FITS)
        prompt_896 = "x" * 896
        input_tokens, ceiling, err = budget_mgr.check_generation_budget(
            prompt=prompt_896,
            system_prompt=None,
            requested_context_limit=1024,
            model_identifier="synthetic-model",
        )
        assert err is None
        assert input_tokens == 896
        assert ceiling == 1024

        # 897 tokens input: 897 + 128 reserve = 1025 > 1024 (OVERFLOWS)
        prompt_897 = "x" * 897
        input_tokens, ceiling, err = budget_mgr.check_generation_budget(
            prompt=prompt_897,
            system_prompt=None,
            requested_context_limit=1024,
            model_identifier="synthetic-model",
        )
        assert err is not None
        assert err.category == ErrorCategory.CONTEXT_BUDGET
        assert "Context budget exceeded" in err.message

    def test_context_budget_preflight_blocks_inference(self) -> None:
        """Context overflow returns ClassifiedError without any transport calls."""
        settings = ModelProviderSettings(
            default_context_ceiling=500,
            reserved_output_tokens=100,
            safety_margin_tokens=0,
        )
        exact_counter = ExactTokenCounter(count_fn=lambda text: len(text))
        transport = ScriptedModelTransport()
        resolver = InMemoryInputResolver()

        provider = LocalModelProvider(
            settings=settings,
            transport=transport,
            input_resolver=resolver,
            tokenizer=exact_counter,
        )

        call_id = uuid.uuid4()
        # Input 450 tokens + 100 reserve = 550 > 500 ceiling
        oversized_prompt = "x" * 450
        bound = resolver.bind_generation(call_id, oversized_prompt)

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="test-model",
            prompt_version="v1",
            context_limit=500,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.CONTEXT_BUDGET
        assert result.output_text is None
        assert result.parsed_output is None
        assert len(transport.recorded_calls) == 0

    def test_requested_context_limit_exceeding_ceiling_fails(self) -> None:
        """Call specifying context_limit greater than model ceiling fails with VALIDATION."""
        settings = ModelProviderSettings(
            models={
                "small-model": ModelCapabilities(
                    model_identifier="small-model",
                    max_context_tokens=2048,
                )
            }
        )
        budget_mgr = ContextBudgetManager(settings)
        _, _, err = budget_mgr.check_generation_budget(
            prompt="short prompt",
            system_prompt=None,
            requested_context_limit=8192,  # Conflict: 8192 > 2048
            model_identifier="small-model",
        )
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "exceeds model ceiling" in err.message

    def test_embedding_text_oversize_fails_context_budget(self) -> None:
        """Individual embedding text exceeding max context window fails with CONTEXT_BUDGET."""
        settings = ModelProviderSettings(
            models={
                "embed-model": ModelCapabilities(
                    model_identifier="embed-model",
                    max_context_tokens=100,
                )
            }
        )
        exact_counter = ExactTokenCounter(count_fn=lambda text: len(text))
        budget_mgr = ContextBudgetManager(settings, tokenizer=exact_counter)

        texts = ["short text", "x" * 150]
        _, err = budget_mgr.check_embedding_budget(texts, "embed-model")
        assert err is not None
        assert err.category == ErrorCategory.CONTEXT_BUDGET
        assert "texts[1]" in (err.field_path or "")

