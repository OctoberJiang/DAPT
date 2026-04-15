"""Planner search-tree and dependency-graph state containers."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterable

from dapt.perceptor.models import EvidenceRecord, PlannerFeedback

from .models import (
    CandidateEvaluation,
    CandidateStatus,
    DependencyCandidate,
    DependencyEdge,
    PlannerNode,
    PlannerNodeKind,
    PlannerNodeStatus,
    evidence_to_conditions,
    planner_feedback_to_node,
)


class SearchTreeState:
    """Mutable planner-owned search tree with immutable node records."""

    def __init__(self, *, session_id: str, target_name: str, root_node: PlannerNode) -> None:
        self.session_id = session_id
        self.target_name = target_name
        self.root_node_id = root_node.node_id
        self.nodes: dict[str, PlannerNode] = {root_node.node_id: root_node}
        self._counters: dict[str, int] = defaultdict(int)
        self._record_existing_id(root_node.node_id)

    @classmethod
    def initialize(cls, *, session_id: str, target_name: str, target_summary: str) -> SearchTreeState:
        """Create a planner tree rooted at the initial target observation."""

        root_node = PlannerNode(
            node_id="obs-0001",
            kind="observation",
            title="Target root",
            content=target_summary,
            metadata={"target_name": target_name},
        )
        return cls(session_id=session_id, target_name=target_name, root_node=root_node)

    def add_hypothesis(
        self,
        *,
        parent_id: str,
        title: str,
        hypothesis: str,
        candidate_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlannerNode:
        """Add a hypothesis node beneath an observation."""

        self._require_parent_kind(parent_id, allowed_kinds={"observation"})
        node = PlannerNode(
            node_id=self._allocate_node_id("hypothesis"),
            kind="hypothesis",
            title=title,
            content=hypothesis,
            parent_id=parent_id,
            candidate_id=candidate_id,
            metadata=metadata or {},
        )
        self._insert_child(node)
        return node

    def add_action(
        self,
        *,
        parent_id: str,
        title: str,
        action: str,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlannerNode:
        """Add an action node beneath a hypothesis."""

        self._require_parent_kind(parent_id, allowed_kinds={"hypothesis"})
        node = PlannerNode(
            node_id=self._allocate_node_id("action"),
            kind="action",
            title=title,
            content=action,
            parent_id=parent_id,
            request_id=request_id,
            metadata=metadata or {},
        )
        self._insert_child(node)
        self.set_status(parent_id, "expanded")
        return node

    def add_observation(
        self,
        *,
        parent_id: str,
        title: str,
        observation: str,
        evidence: EvidenceRecord | None = None,
        source_artifact_paths: Iterable[str] = (),
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlannerNode:
        """Add an observation node beneath an action."""

        self._require_parent_kind(parent_id, allowed_kinds={"action"})
        node = PlannerNode(
            node_id=self._allocate_node_id("observation"),
            kind="observation",
            title=title,
            content=observation,
            parent_id=parent_id,
            evidence=evidence or EvidenceRecord(),
            source_artifact_paths=tuple(source_artifact_paths),
            request_id=request_id,
            metadata=metadata or {},
        )
        self._insert_child(node)
        return node

    def ingest_planner_feedback(self, *, action_node_id: str, feedback: PlannerFeedback) -> PlannerNode:
        """Create a follow-up observation node from Perceptor feedback."""

        self._require_parent_kind(action_node_id, allowed_kinds={"action"})
        observation = planner_feedback_to_node(
            node_id=self._allocate_node_id("observation"),
            parent_id=action_node_id,
            feedback=feedback,
        )
        self._insert_child(observation)
        if feedback.execution_status == "succeeded":
            self.set_status(action_node_id, "succeeded")
        else:
            self.set_status(action_node_id, "failed")
        return observation

    def set_status(self, node_id: str, status: PlannerNodeStatus) -> PlannerNode:
        """Update a node status."""

        node = self.nodes[node_id]
        updated = replace(node, status=status)
        self.nodes[node_id] = updated
        return updated

    def update_metadata(self, node_id: str, **metadata_updates: Any) -> PlannerNode:
        """Merge new metadata into an existing node."""

        node = self.nodes[node_id]
        updated = replace(node, metadata={**node.metadata, **metadata_updates})
        self.nodes[node_id] = updated
        return updated

    def children_of(self, node_id: str) -> tuple[PlannerNode, ...]:
        """Return child nodes for the given parent."""

        return tuple(self.nodes[child_id] for child_id in self.nodes[node_id].child_ids)

    def path_to_node(self, node_id: str) -> tuple[PlannerNode, ...]:
        """Return the ancestry path from root to the target node."""

        if node_id not in self.nodes:
            raise KeyError(node_id)
        path: list[PlannerNode] = []
        current_id: str | None = node_id
        while current_id is not None:
            node = self.nodes[current_id]
            path.append(node)
            current_id = node.parent_id
        path.reverse()
        return tuple(path)

    def snapshot(self) -> dict[str, Any]:
        """Serialize the tree into a deterministic JSON-ready snapshot."""

        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "root_node_id": self.root_node_id,
            "nodes": {
                node_id: asdict(node)
                for node_id, node in sorted(self.nodes.items())
            },
        }

    def _insert_child(self, node: PlannerNode) -> None:
        self.nodes[node.node_id] = node
        parent = self.nodes[node.parent_id or ""]
        updated_parent = replace(parent, child_ids=parent.child_ids + (node.node_id,))
        self.nodes[parent.node_id] = updated_parent

    def _allocate_node_id(self, kind: PlannerNodeKind) -> str:
        prefixes = {"observation": "obs", "hypothesis": "hyp", "action": "act"}
        prefix = prefixes[kind]
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]:04d}"

    def _record_existing_id(self, node_id: str) -> None:
        prefix, _, suffix = node_id.partition("-")
        if not suffix.isdigit():
            return
        self._counters[prefix] = max(self._counters[prefix], int(suffix))

    def _require_parent_kind(self, node_id: str, *, allowed_kinds: set[PlannerNodeKind]) -> None:
        if node_id not in self.nodes:
            raise KeyError(node_id)
        if self.nodes[node_id].kind not in allowed_kinds:
            allowed = ", ".join(sorted(allowed_kinds))
            raise ValueError(f"Node {node_id} must be one of: {allowed}")


class AttackDependencyGraph:
    """Planner-owned attack dependency graph with deterministic scoring."""

    def __init__(self, *, session_id: str, target_name: str) -> None:
        self.session_id = session_id
        self.target_name = target_name
        self.candidates: dict[str, DependencyCandidate] = {}
        self.satisfied_conditions: set[str] = set()
        self.contradicted_conditions: set[str] = set()
        self.observation_node_ids: set[str] = set()
        self._candidate_counter = 0

    def register_candidate(
        self,
        *,
        hypothesis_node_id: str,
        summary: str,
        candidate_key: str | None = None,
        prerequisites: Iterable[str] = (),
        effects: Iterable[str] = (),
        supporting_node_ids: Iterable[str] = (),
        contradicting_node_ids: Iterable[str] = (),
        candidate_id: str | None = None,
    ) -> DependencyCandidate:
        """Add a new attack candidate to the graph."""

        resolved_id = candidate_id or self._allocate_candidate_id()
        candidate = DependencyCandidate(
            candidate_id=resolved_id,
            hypothesis_node_id=hypothesis_node_id,
            summary=summary,
            candidate_key=candidate_key,
            prerequisites=tuple(sorted(set(prerequisites))),
            effects=tuple(sorted(set(effects))),
            supporting_node_ids=tuple(sorted(set(supporting_node_ids))),
            contradicting_node_ids=tuple(sorted(set(contradicting_node_ids))),
        )
        self.candidates[resolved_id] = self._refresh_candidate_status(candidate)
        self._recompute_statuses()
        return self.candidates[resolved_id]

    def get_candidate_by_key(self, candidate_key: str) -> DependencyCandidate | None:
        """Return the existing candidate with the given deterministic key, if any."""

        for candidate in self.candidates.values():
            if candidate.candidate_key == candidate_key:
                return candidate
        return None

    def ingest_observation(
        self,
        *,
        observation_node_id: str,
        evidence: EvidenceRecord | None = None,
        satisfied_conditions: Iterable[str] = (),
        contradicted_conditions: Iterable[str] = (),
    ) -> None:
        """Update graph conditions from a planner observation event."""

        self.observation_node_ids.add(observation_node_id)
        if evidence is not None:
            self.satisfied_conditions.update(evidence_to_conditions(evidence))
        self.satisfied_conditions.update(satisfied_conditions)
        self.contradicted_conditions.update(contradicted_conditions)
        self._recompute_statuses()

    def record_action_outcome(
        self,
        *,
        candidate_id: str,
        action_node_id: str,
        status: CandidateStatus,
        produced_effects: Iterable[str] = (),
        contradicted_conditions: Iterable[str] = (),
    ) -> DependencyCandidate:
        """Record a candidate execution outcome and refresh graph state."""

        if candidate_id not in self.candidates:
            raise KeyError(candidate_id)
        candidate = self.candidates[candidate_id]
        merged_effects = tuple(sorted(set(candidate.effects) | set(produced_effects)))
        updated = replace(
            candidate,
            effects=merged_effects,
            last_action_node_id=action_node_id,
            status=status,
        )
        self.candidates[candidate_id] = updated
        if status == "succeeded":
            self.satisfied_conditions.update(merged_effects)
        self.contradicted_conditions.update(contradicted_conditions)
        self._recompute_statuses()
        return self.candidates[candidate_id]

    def dependency_edges(self) -> tuple[DependencyEdge, ...]:
        """Return candidate enablement edges derived from effects and prerequisites."""

        edges: list[DependencyEdge] = []
        for source in self.candidates.values():
            for target in self.candidates.values():
                if source.candidate_id == target.candidate_id:
                    continue
                overlap = tuple(sorted(set(source.effects) & set(target.prerequisites)))
                if overlap:
                    edges.append(
                        DependencyEdge(
                            source_candidate_id=source.candidate_id,
                            target_candidate_id=target.candidate_id,
                            conditions=overlap,
                        )
                    )
        edges.sort(key=lambda edge: (edge.source_candidate_id, edge.target_candidate_id, edge.conditions))
        return tuple(edges)

    def evaluate_candidate(self, candidate_id: str) -> CandidateEvaluation:
        """Compute deterministic dependency-aware score components."""

        candidate = self.candidates[candidate_id]
        prerequisites = set(candidate.prerequisites)
        satisfied = tuple(sorted(prerequisites & self.satisfied_conditions))
        unsatisfied = tuple(sorted(prerequisites - self.satisfied_conditions))
        contradicted = tuple(sorted(prerequisites & self.contradicted_conditions))
        prerequisite_score = 1.0 if not prerequisites else len(satisfied) / len(prerequisites)
        unlock_candidates = self._downstream_unlock_candidates(candidate)
        centrality = self._dependency_centrality(candidate.candidate_id)
        contradiction_penalty = 0.0 if not prerequisites else len(contradicted) / len(prerequisites)
        denominator = max(len(self.candidates) - 1, 1)
        final_score = (
            prerequisite_score
            + (len(unlock_candidates) / denominator)
            + centrality
            - contradiction_penalty
        )
        return CandidateEvaluation(
            candidate_id=candidate_id,
            prerequisite_satisfaction=prerequisite_score,
            satisfied_prerequisites=satisfied,
            unsatisfied_prerequisites=unsatisfied,
            downstream_unlock_count=len(unlock_candidates),
            downstream_unlock_candidates=unlock_candidates,
            dependency_centrality=centrality,
            contradiction_penalty=contradiction_penalty,
            contradicted_prerequisites=contradicted,
            final_score=final_score,
        )

    def rank_candidates(self) -> tuple[CandidateEvaluation, ...]:
        """Return ranked candidate evaluations for non-terminal candidates."""

        evaluations = [
            self.evaluate_candidate(candidate_id)
            for candidate_id, candidate in self.candidates.items()
            if candidate.status not in {"succeeded", "failed"}
        ]
        evaluations.sort(key=lambda item: (-item.final_score, item.candidate_id))
        return tuple(evaluations)

    def snapshot(self) -> dict[str, Any]:
        """Serialize the graph into a deterministic JSON-ready snapshot."""

        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "satisfied_conditions": sorted(self.satisfied_conditions),
            "contradicted_conditions": sorted(self.contradicted_conditions),
            "observation_node_ids": sorted(self.observation_node_ids),
            "candidates": {
                candidate_id: asdict(candidate)
                for candidate_id, candidate in sorted(self.candidates.items())
            },
            "edges": [asdict(edge) for edge in self.dependency_edges()],
        }

    def _allocate_candidate_id(self) -> str:
        self._candidate_counter += 1
        return f"cand-{self._candidate_counter:04d}"

    def _refresh_candidate_status(self, candidate: DependencyCandidate) -> DependencyCandidate:
        if candidate.status in {"succeeded", "failed"}:
            return candidate
        prerequisites = set(candidate.prerequisites)
        if prerequisites & self.contradicted_conditions:
            return replace(candidate, status="contradicted")
        if prerequisites <= self.satisfied_conditions:
            return replace(candidate, status="available")
        return replace(candidate, status="blocked")

    def _recompute_statuses(self) -> None:
        for candidate_id, candidate in tuple(self.candidates.items()):
            self.candidates[candidate_id] = self._refresh_candidate_status(candidate)

    def _downstream_unlock_candidates(self, candidate: DependencyCandidate) -> tuple[str, ...]:
        simulated_conditions = self.satisfied_conditions | set(candidate.effects)
        unlocked: list[str] = []
        for other in self.candidates.values():
            if other.candidate_id == candidate.candidate_id:
                continue
            if other.status in {"succeeded", "failed", "contradicted"}:
                continue
            other_prereqs = set(other.prerequisites)
            if other_prereqs <= simulated_conditions and not other_prereqs <= self.satisfied_conditions:
                unlocked.append(other.candidate_id)
        unlocked.sort()
        return tuple(unlocked)

    def _dependency_centrality(self, candidate_id: str) -> float:
        edges = self.dependency_edges()
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge.source_candidate_id].add(edge.target_candidate_id)
        visited: set[str] = set()
        queue: deque[str] = deque(adjacency.get(candidate_id, ()))
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(adjacency.get(current, ()))
        denominator = max(len(self.candidates) - 1, 1)
        return len(visited) / denominator


def build_planner_state(
    *,
    repo_root: Path,
    session_id: str,
    target_name: str,
    target_summary: str,
) -> tuple[SearchTreeState, AttackDependencyGraph]:
    """Build the initial planner tree and dependency graph pair."""

    _ = repo_root
    return (
        SearchTreeState.initialize(
            session_id=session_id,
            target_name=target_name,
            target_summary=target_summary,
        ),
        AttackDependencyGraph(session_id=session_id, target_name=target_name),
    )
