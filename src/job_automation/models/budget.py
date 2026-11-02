"""Context budget management and token estimation (LLM-01-S03).

Provides preflight validation of prompt length, completion reserve, and safety allowances
against declared context window limits.
"""

from __future__ import annotations

import math
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.models.configuration import ModelCapabilities, ModelProviderSettings
from job_automation.models.ports import Tokenizer


class CharacterRatioTokenizer:
    """Conservative token estimator using character-to-token ratio.

    Uses conservative ratio ~3.5 chars per token with ceiling to prevent underestimation.
    """

    def __init__(self, chars_per_token: float = 3.5) -> None:
        self.chars_per_token = max(1.0, chars_per_token)

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.chars_per_token))


class ExactTokenCounter:
    """Exact token counter using word/whitespace or injected map (primarily for testing)."""

    def __init__(self, count_fn: Any = None) -> None:
        self._count_fn = count_fn

    def count_tokens(self, text: str) -> int:
        if self._count_fn:
            return int(self._count_fn(text))
        # Default whitespace splitting
        return len(text.split()) if text else 0


class ContextBudgetManager:
    """Manages preflight context budget checks for generation and embeddings."""

    def __init__(
        self,
        settings: ModelProviderSettings,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self.settings = settings
        self.tokenizer: Tokenizer = tokenizer if tokenizer is not None else CharacterRatioTokenizer()

    def check_generation_budget(
        self,
        prompt: str,
        system_prompt: str | None,
        requested_context_limit: int,
        model_identifier: str,
    ) -> tuple[int, int, ClassifiedError | None]:
        """Validate that input, reserved output, and safety margin fit within context window.

        Returns (input_tokens, effective_context_ceiling, error).
        """
        model_caps: ModelCapabilities | None = self.settings.models.get(model_identifier)
        max_model_context = (
            model_caps.max_context_tokens
            if model_caps is not None
            else self.settings.default_context_ceiling
        )

        # Reject conflict if requested context limit exceeds model ceiling
        if requested_context_limit > max_model_context:
            err = ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Requested context limit {requested_context_limit} exceeds model ceiling {max_model_context} for '{model_identifier}'",
                details={
                    "requested_limit": requested_context_limit,
                    "model_ceiling": max_model_context,
                    "model": model_identifier,
                },
            )
            return 0, max_model_context, err

        effective_limit = min(requested_context_limit, max_model_context)

        # Calculate input tokens
        prompt_tokens = self.tokenizer.count_tokens(prompt)
        sys_tokens = self.tokenizer.count_tokens(system_prompt) if system_prompt else 0
        input_tokens = prompt_tokens + sys_tokens

        # Reserve completion tokens and safety margin
        reserved_output = (
            model_caps.default_output_reserve
            if model_caps is not None
            else self.settings.reserved_output_tokens
        )
        safety_margin = self.settings.safety_margin_tokens

        total_required = input_tokens + reserved_output + safety_margin

        if total_required > effective_limit:
            err = ClassifiedError.from_category(
                ErrorCategory.CONTEXT_BUDGET,
                f"Context budget exceeded: input ({input_tokens}) + reserve ({reserved_output}) + margin ({safety_margin}) = {total_required} > limit ({effective_limit})",
                details={
                    "input_tokens": input_tokens,
                    "reserved_output": reserved_output,
                    "safety_margin": safety_margin,
                    "total_required": total_required,
                    "effective_limit": effective_limit,
                },
            )
            return input_tokens, effective_limit, err

        return input_tokens, effective_limit, None

    def check_embedding_budget(
        self,
        texts: list[str],
        model_identifier: str,
    ) -> tuple[int, ClassifiedError | None]:
        """Validate embedding batch and per-text context lengths without completion reserve."""
        if not texts:
            return 0, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                "Embedding texts batch cannot be empty",
            )

        if len(texts) > self.settings.max_batch_size:
            return 0, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Embedding batch size {len(texts)} exceeds configured maximum {self.settings.max_batch_size}",
                details={"batch_size": len(texts), "max_batch_size": self.settings.max_batch_size},
            )

        model_caps = self.settings.models.get(model_identifier)
        max_context = (
            model_caps.max_context_tokens
            if model_caps is not None
            else self.settings.default_context_ceiling
        )

        total_tokens = 0
        for i, text in enumerate(texts):
            if not text or not text.strip():
                return 0, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    f"Embedding text at index {i} is empty or whitespace-only",
                    field_path=f"texts[{i}]",
                )
            text_tokens = self.tokenizer.count_tokens(text)
            total_tokens += text_tokens
            if text_tokens > max_context:
                return total_tokens, ClassifiedError.from_category(
                    ErrorCategory.CONTEXT_BUDGET,
                    f"Embedding text at index {i} ({text_tokens} tokens) exceeds context limit {max_context}",
                    field_path=f"texts[{i}]",
                    details={"index": i, "tokens": text_tokens, "limit": max_context},
                )

        return total_tokens, None

