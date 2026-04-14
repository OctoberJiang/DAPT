"""Typed contracts for tool and skill specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .models import ExecutionRequest, ExecutionResult, OutputEnvelope

Validator = Callable[[ExecutionRequest], None]
ToolExecutor = Callable[[ExecutionRequest], OutputEnvelope]
OutputParser = Callable[[OutputEnvelope], dict[str, Any]]
ResultValidator = Callable[[ExecutionResult], None]
ParameterBuilder = Callable[[ExecutionRequest], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Schema entry for a tool or skill parameter."""

    name: str
    type_name: str
    description: str
    required: bool = True
    default: Any | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Typed interface for a single executable tool action."""

    name: str
    description: str
    input_schema: tuple[FieldSpec, ...]
    validators: tuple[Validator, ...] = ()
    preconditions: tuple[Validator, ...] = ()
    executor: ToolExecutor | None = None
    output_parser: OutputParser | None = None
    postconditions: tuple[ResultValidator, ...] = ()
    default_parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillStepSpec:
    """One step inside a higher-level skill procedure."""

    name: str
    tool_name: str
    parameter_builder: ParameterBuilder
    preconditions: tuple[Validator, ...] = ()
    success_hint: str | None = None
    on_failure: str = "stop"


@dataclass(frozen=True, slots=True)
class SkillSpec:
    """Reusable multi-step procedure built on top of tool contracts."""

    name: str
    goal: str
    required_state: tuple[str, ...]
    preferred_tools: tuple[str, ...]
    fallback_tools: tuple[str, ...] = ()
    input_schema: tuple[FieldSpec, ...] = ()
    validators: tuple[Validator, ...] = ()
    step_sequence: tuple[SkillStepSpec, ...] = ()
    result_aggregator: OutputParser | None = None
    success_conditions: tuple[str, ...] = ()
    produced_effects: tuple[str, ...] = ()
