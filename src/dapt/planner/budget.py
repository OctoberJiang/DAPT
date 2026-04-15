"""Planner-session usage tracking and hard budget evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from dapt.executor import ExecutionResult

BudgetLimitName = Literal["runtime_seconds", "tool_calls", "llm_cost_cny"]


@dataclass(frozen=True, slots=True)
class PlannerBudgetLimits:
    """Optional hard caps for one planner session."""

    max_runtime_seconds: float | None = None
    max_tool_calls: int | None = None
    max_llm_cost_cny: float | None = None


@dataclass(frozen=True, slots=True)
class BudgetLimitHit:
    """The first budget limit that was reached for a session."""

    limit_name: BudgetLimitName
    limit_value: float
    observed_value: float

    def as_payload(self) -> dict[str, float | str]:
        return {
            "limit_name": self.limit_name,
            "limit_value": self.limit_value,
            "observed_value": self.observed_value,
        }


@dataclass(slots=True)
class PlannerBudgetTracker:
    """Mutable usage tracker for one planner session."""

    limits: PlannerBudgetLimits = field(default_factory=PlannerBudgetLimits)
    runtime_seconds: float = 0.0
    tool_calls: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    llm_cost_cny: float = 0.0
    limit_hit: BudgetLimitHit | None = None

    def record_llm_usage(
        self,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cost_cny: float | None = None,
        latency_seconds: float | None = None,
    ) -> None:
        self.llm_prompt_tokens += max(prompt_tokens or 0, 0)
        self.llm_completion_tokens += max(completion_tokens or 0, 0)
        resolved_total = total_tokens
        if resolved_total is None:
            resolved_total = max(prompt_tokens or 0, 0) + max(completion_tokens or 0, 0)
        self.llm_total_tokens += max(resolved_total, 0)
        self.llm_cost_cny = round(self.llm_cost_cny + max(cost_cny or 0.0, 0.0), 6)
        self.runtime_seconds = round(self.runtime_seconds + max(latency_seconds or 0.0, 0.0), 6)
        self.evaluate()

    def record_execution(
        self,
        *,
        result: ExecutionResult,
        fallback_tool_invocations: int = 0,
        fallback_elapsed_seconds: float = 0.0,
    ) -> None:
        usage = result.usage
        tool_invocations = fallback_tool_invocations
        elapsed_seconds = fallback_elapsed_seconds
        if usage is not None:
            tool_invocations = usage.tool_invocations
            elapsed_seconds = usage.elapsed_seconds
        self.tool_calls += max(tool_invocations, 0)
        self.runtime_seconds = round(self.runtime_seconds + max(elapsed_seconds, 0.0), 6)
        self.evaluate()

    def evaluate(self) -> BudgetLimitHit | None:
        if self.limit_hit is not None:
            return self.limit_hit

        if self.limits.max_runtime_seconds is not None and self.runtime_seconds >= self.limits.max_runtime_seconds:
            self.limit_hit = BudgetLimitHit(
                limit_name="runtime_seconds",
                limit_value=float(self.limits.max_runtime_seconds),
                observed_value=float(self.runtime_seconds),
            )
            return self.limit_hit

        if self.limits.max_tool_calls is not None and self.tool_calls >= self.limits.max_tool_calls:
            self.limit_hit = BudgetLimitHit(
                limit_name="tool_calls",
                limit_value=float(self.limits.max_tool_calls),
                observed_value=float(self.tool_calls),
            )
            return self.limit_hit

        if self.limits.max_llm_cost_cny is not None and self.llm_cost_cny >= self.limits.max_llm_cost_cny:
            self.limit_hit = BudgetLimitHit(
                limit_name="llm_cost_cny",
                limit_value=float(self.limits.max_llm_cost_cny),
                observed_value=float(self.llm_cost_cny),
            )
            return self.limit_hit

        return None

    def snapshot(self) -> dict[str, object]:
        return {
            "limits": {
                "max_runtime_seconds": self.limits.max_runtime_seconds,
                "max_tool_calls": self.limits.max_tool_calls,
                "max_llm_cost_cny": self.limits.max_llm_cost_cny,
            },
            "usage": {
                "runtime_seconds": self.runtime_seconds,
                "tool_calls": self.tool_calls,
                "llm_prompt_tokens": self.llm_prompt_tokens,
                "llm_completion_tokens": self.llm_completion_tokens,
                "llm_total_tokens": self.llm_total_tokens,
                "llm_cost_cny": self.llm_cost_cny,
                "currency": "CNY",
            },
            "limit_hit": None if self.limit_hit is None else self.limit_hit.as_payload(),
        }
