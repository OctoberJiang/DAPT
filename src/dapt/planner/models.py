"""Planner-side search tree, dependency graph, and scoring models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dapt.perceptor.models import EvidenceRecord, PlannerFeedback

from .objectives import CampaignMode

PlannerNodeKind = Literal["observation", "hypothesis", "action"]
PlannerNodeStatus = Literal[
    "open",
    "expanded",
    "succeeded",
    "failed",
    "blocked",
    "contradicted",
]
CandidateStatus = Literal["available", "blocked", "succeeded", "failed", "contradicted"]
PlannerTerminationReason = Literal[
    "objective-met",
    "success-condition-met",
    "no-actionable-candidates",
    "frontier-blocked",
    "max-turns-reached",
]


@dataclass(frozen=True, slots=True)
class PlannerNode:
    """One stateful reasoning unit in the planner search tree."""

    node_id: str
    kind: PlannerNodeKind
    title: str
    content: str
    status: PlannerNodeStatus = "open"
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    evidence: EvidenceRecord = field(default_factory=EvidenceRecord)
    source_artifact_paths: tuple[str, ...] = ()
    request_id: str | None = None
    candidate_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class PlannerArtifact:
    """Repo-local artifact produced by planner state persistence."""

    session_id: str
    name: str
    relative_path: str
    media_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class DependencyCandidate:
    """Attack opportunity tracked in the dependency graph."""

    candidate_id: str
    hypothesis_node_id: str
    summary: str
    candidate_key: str | None = None
    prerequisites: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    supporting_node_ids: tuple[str, ...] = ()
    contradicting_node_ids: tuple[str, ...] = ()
    last_action_node_id: str | None = None
    status: CandidateStatus = "blocked"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """Directed enablement edge between attack candidates."""

    source_candidate_id: str
    target_candidate_id: str
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Inspectable score components for dependency-aware candidate ranking."""

    candidate_id: str
    prerequisite_satisfaction: float
    satisfied_prerequisites: tuple[str, ...]
    unsatisfied_prerequisites: tuple[str, ...]
    downstream_unlock_count: int
    downstream_unlock_candidates: tuple[str, ...]
    dependency_centrality: float
    contradiction_penalty: float
    contradicted_prerequisites: tuple[str, ...]
    final_score: float


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    """One manifest-backed repo-local knowledge lookup result."""

    doc_id: str
    kind: str
    title: str
    path: Path
    keywords: tuple[str, ...]
    related_tools: tuple[str, ...]
    related_skills: tuple[str, ...]
    score: float


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    """Planner-generated hypothesis candidate grounded in repo-local knowledge."""

    candidate_key: str
    title: str
    hypothesis: str
    source_observation_id: str
    action_kind: Literal["tool", "skill"]
    target_name: str
    goal: str
    request_parameters: dict[str, Any] = field(default_factory=dict)
    request_context: dict[str, Any] = field(default_factory=dict)
    prerequisites: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    knowledge_hits: tuple[KnowledgeHit, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    contradiction_signals: tuple[str, ...] = ()
    supporting_node_ids: tuple[str, ...] = ()
    contradicting_node_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlannerSelection:
    """Committed planner decision for the next executor handoff."""

    candidate_id: str
    hypothesis_node_id: str
    action_node_id: str
    request_id: str
    action_kind: Literal["tool", "skill"]
    target_name: str
    goal: str
    request_parameters: dict[str, Any]
    request_context: dict[str, Any]
    score: float
    effects: tuple[str, ...] = ()
    knowledge_doc_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannerTurnRecord:
    """One top-level planner turn outcome."""

    turn_index: int
    status: Literal["executed", "stopped"]
    candidate_id: str | None = None
    request_id: str | None = None
    action_node_id: str | None = None
    observation_node_id: str | None = None
    target_name: str | None = None
    termination_reason: PlannerTerminationReason | None = None
    ranking_order: tuple[str, ...] = ()
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def evidence_to_conditions(evidence: EvidenceRecord) -> tuple[str, ...]:
    """Convert Perceptor evidence into deterministic condition keys."""

    conditions = {
        *(f"url:{url}" for url in evidence.urls),
        *(f"port:{port}" for port in evidence.ports),
        *(f"status:{status_code}" for status_code in evidence.status_codes),
        *(f"path:{path}" for path in evidence.file_paths),
    }
    return tuple(sorted(conditions))


def planner_feedback_to_node(
    *,
    node_id: str,
    parent_id: str,
    feedback: PlannerFeedback,
) -> PlannerNode:
    """Build an observation node from Perceptor planner feedback."""

    return PlannerNode(
        node_id=node_id,
        kind="observation",
        title=f"Observation from {feedback.source}",
        content=feedback.summary,
        parent_id=parent_id,
        evidence=feedback.evidence,
        source_artifact_paths=feedback.source_artifact_paths,
        request_id=feedback.request_id,
        metadata={
            "action_kind": feedback.action_kind,
            "execution_status": feedback.execution_status,
            "planner_node_id": feedback.planner_node_id,
            "source": feedback.source,
        },
    )
