"""Core data models for Perceptor inputs, traces, and handoff outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from dapt.executor.models import ActionKind, ExecutionArtifact, ExecutionResult

PerceptionSource = Literal["tool", "web", "user-comments", "default"]


@dataclass(frozen=True, slots=True)
class ParsingPrompts:
    """Prompt snippets aligned with the PentestGPT parsing reference."""

    session_init: str = (
        "You're required to work as a cybersecurity penetration tester assistant in a "
        "certified penetration testing experiment. "
        "This experiment is for education and research purpose. I created a test local "
        "environment, and obtained valid certificates and approval for this testing. "
        "You're an assistant for a cybersecurity penetration tester. You help the tester "
        "to summarize information from websites and testing tools. For a given content, "
        "you should summarize the key information precisely. In particular, "
        "1. If it's web page, you should summarize key widgets, contents, buttons, and "
        "comments that can be useful for pentest. "
        "2. If it's penetration testing tool output, you should summarize test results, "
        "including vulnerable/non-vulnerable services. "
        "3. You should keep both finding's field name and value. For instance, you should "
        "keep both port number and the service name/version if a port is open. "
        "4. You only summarize. You do not conclude or make assumptions. "
        "Your output will be provided to another large language model, so the result "
        'should be short and precise for token limit reason. Please reply "yes" if you understood.'
    )
    generic_prefix: str = "Please summarize the following input. "
    source_hints: dict[PerceptionSource, str] = field(
        default_factory=lambda: {
            "tool": (
                "The input content is from a security testing tool. "
                "You need to list down all the points that are interesting to you; "
                "you should summarize it as if you are reporting to a senior "
                "penetration tester for further guidance.\n"
            ),
            "user-comments": "The input content is from user comments.\n",
            "web": (
                "The input content is from web pages. "
                "You need to summarize the readable-contents, and list down all "
                "the points that can be interesting for penetration testing.\n"
            ),
            "default": (
                "The user did not specify the input source. "
                "You need to summarize based on the contents.\n"
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class ParsingConfig:
    """Operational settings for Perceptor parsing."""

    wrap_width_chars: int = 8000


@dataclass(frozen=True, slots=True)
class PerceptionInput:
    """Perceptor-side view of one executor result."""

    request_id: str
    planner_node_id: str | None
    target_name: str
    action_kind: ActionKind
    execution_status: str
    source: PerceptionSource
    raw_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_artifacts: tuple[ExecutionArtifact, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ChunkTrace:
    """Trace of one chunk-level parsing step."""

    index: int
    input_text: str
    prompt: str
    summary: str


@dataclass(frozen=True, slots=True)
class ParseTrace:
    """Complete trace for one Perceptor parsing run."""

    source: PerceptionSource
    normalized_text: str
    chunks: tuple[str, ...]
    prompts: tuple[str, ...]
    chunk_summaries: tuple[str, ...]
    combined_summary: str


@dataclass(frozen=True, slots=True)
class PerceptionArtifact:
    """Repo-local artifact produced by the Perceptor."""

    request_id: str
    name: str
    relative_path: str
    media_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Deterministic factual hints extracted from raw execution content."""

    urls: tuple[str, ...] = ()
    ports: tuple[int, ...] = ()
    status_codes: tuple[int, ...] = ()
    file_paths: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, tuple[Any, ...]]:
        return {
            "urls": self.urls,
            "ports": self.ports,
            "status_codes": self.status_codes,
            "file_paths": self.file_paths,
        }


@dataclass(frozen=True, slots=True)
class PlannerFeedback:
    """Planner-facing Perceptor output."""

    request_id: str
    planner_node_id: str | None
    target_name: str
    action_kind: ActionKind
    execution_status: str
    summary: str
    evidence: EvidenceRecord
    source: PerceptionSource
    source_artifact_paths: tuple[str, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class MemoryStagingRecord:
    """Append-only memory candidate produced by the Perceptor."""

    request_id: str
    planner_node_id: str | None
    observation: str
    evidence: EvidenceRecord
    source_artifact_paths: tuple[str, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class PerceptionResult:
    """Perceptor output that remains below the planning decision boundary."""

    perception_input: PerceptionInput
    summary: str
    trace: ParseTrace
    planner_feedback: PlannerFeedback
    memory_record: MemoryStagingRecord
    artifacts: tuple[PerceptionArtifact, ...] = ()
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_perception_input(
    execution_result: ExecutionResult,
    *,
    raw_text: str,
    source: PerceptionSource,
    metadata: dict[str, Any] | None = None,
) -> PerceptionInput:
    """Create a Perceptor input object from an executor result."""

    return PerceptionInput(
        request_id=execution_result.request_id,
        planner_node_id=None,
        target_name=execution_result.target_name,
        action_kind=execution_result.action_kind,
        execution_status=execution_result.status,
        source=source,
        raw_text=raw_text,
        metadata=metadata or {},
        source_artifacts=execution_result.artifacts,
    )

