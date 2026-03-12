"""Shared types for TMB — token tracking, structured signals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenAccumulator:
    """Type-safe accumulator for LLM token usage across tool loops."""

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage: dict) -> None:
        """Merge a usage dict (from extract_token_usage) into running totals."""
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
