"""Core data models for execution requests, raw outputs, and stored artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ActionKind = Literal["tool", "skill"]
ExecutionStatus = Literal["pending", "running", "succeeded", "failed"]
SkillStepStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """Planner-issued request for a single execution action."""

    request_id: str
    target_name: str
    action_kind: ActionKind
    parameters: dict[str, Any]
    planner_node_id: str | None = None
    goal: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class OutputEnvelope:
    """Raw execution output captured from a tool or a skill step."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionArtifact:
    """Repo-local artifact produced by an execution attempt."""

    request_id: str
    name: str
    relative_path: str
    media_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Execution-layer result passed forward without summarizing attack meaning."""

    request_id: str
    target_name: str
    action_kind: ActionKind
    status: ExecutionStatus
    output: OutputEnvelope | None = None
    artifacts: tuple[ExecutionArtifact, ...] = ()
    effects: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    error_message: str | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SkillStepRecord:
    """Structured record of one skill step execution outcome."""

    name: str
    tool_name: str
    status: SkillStepStatus
    effects: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
