"""Dependency-aware candidate selection and planner-to-executor request emission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dapt.executor import ExecutionRequest, SpecRegistry

from .models import PlannerSelection, PlannerTerminationReason

if TYPE_CHECKING:
    from .service import PlannerSession


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    """Selection result or deterministic stop reason."""

    selection: PlannerSelection | None
    termination_reason: PlannerTerminationReason | None = None


class PlannerDecisionEngine:
    """Select the next candidate and materialize an executor request."""

    def __init__(self, registry: SpecRegistry) -> None:
        self.registry = registry

    def choose(self, session: PlannerSession) -> SelectionOutcome:
        """Return the next executable selection or a stop reason."""

        ranked = session.graph.rank_candidates()
        actionable: list[tuple[Any, Any]] = []
        blocked_present = False
        for evaluation in ranked:
            candidate = session.graph.candidates[evaluation.candidate_id]
            if candidate.status == "blocked":
                blocked_present = True
            if candidate.status != "available":
                continue
            hypothesis = session.tree.nodes[candidate.hypothesis_node_id]
            action_kind = hypothesis.metadata.get("action_kind")
            target_name = hypothesis.metadata.get("action_target_name")
            if not isinstance(action_kind, str) or not isinstance(target_name, str):
                continue
            if not self._target_exists(action_kind=action_kind, target_name=target_name):
                continue
            actionable.append((evaluation, candidate))

        if not actionable:
            return SelectionOutcome(
                selection=None,
                termination_reason="frontier-blocked" if blocked_present else "no-actionable-candidates",
            )

        actionable.sort(
            key=lambda item: (
                -item[0].final_score,
                -int(session.tree.nodes[item[1].hypothesis_node_id].metadata.get("priority", 0)),
                -item[0].prerequisite_satisfaction,
                -item[0].downstream_unlock_count,
                -item[0].dependency_centrality,
                item[0].contradiction_penalty,
                item[0].candidate_id,
            )
        )
        evaluation, candidate = actionable[0]
        hypothesis = session.tree.nodes[candidate.hypothesis_node_id]
        request_id = session.next_request_id()
        action_title = f"Execute {hypothesis.metadata['action_target_name']}"
        action_description = hypothesis.content
        action_node = session.tree.add_action(
            parent_id=hypothesis.node_id,
            title=action_title,
            action=action_description,
            request_id=request_id,
            metadata={
                "candidate_id": candidate.candidate_id,
                "action_kind": hypothesis.metadata["action_kind"],
                "action_target_name": hypothesis.metadata["action_target_name"],
                "effects": tuple(hypothesis.metadata.get("effects", ())),
                "knowledge_doc_ids": hypothesis.metadata.get("knowledge_doc_ids", ()),
            },
        )
        selection = PlannerSelection(
            candidate_id=candidate.candidate_id,
            hypothesis_node_id=hypothesis.node_id,
            action_node_id=action_node.node_id,
            request_id=request_id,
            action_kind=hypothesis.metadata["action_kind"],
            target_name=hypothesis.metadata["action_target_name"],
            goal=str(hypothesis.metadata.get("goal", hypothesis.content)),
            request_parameters=_compact_mapping(hypothesis.metadata.get("request_parameters", {})),
            request_context={**session.current_state, **hypothesis.metadata.get("request_context", {})},
            score=evaluation.final_score,
            effects=tuple(hypothesis.metadata.get("effects", ())),
            knowledge_doc_ids=tuple(hypothesis.metadata.get("knowledge_doc_ids", ())),
        )
        session.tree.update_metadata(hypothesis.node_id, selected_request_id=request_id)
        return SelectionOutcome(selection=selection)

    def build_execution_request(self, selection: PlannerSelection) -> ExecutionRequest:
        """Convert a committed planner selection into an executor request."""

        return ExecutionRequest(
            request_id=selection.request_id,
            target_name=selection.target_name,
            action_kind=selection.action_kind,
            parameters=selection.request_parameters,
            planner_node_id=selection.action_node_id,
            goal=selection.goal,
            context=selection.request_context,
        )

    def _target_exists(self, *, action_kind: str, target_name: str) -> bool:
        if action_kind == "tool":
            return self.registry.get_tool(target_name) is not None
        if action_kind == "skill":
            return self.registry.get_skill(target_name) is not None
        return False


def _compact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None}
