"""Top-level planner runtime and turn orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Mapping
from urllib.parse import urlparse

from dapt.executor import ExecutionRequest, Executor, SpecRegistry
from dapt.knowledge import KnowledgeManifest, load_knowledge_manifest
from dapt.memory import MemoryArtifactStore, MemoryQuery, MemoryStore
from dapt.perceptor import PerceptionResult, Perceptor

from .bootstrap import BootstrapPolicy
from .budget import PlannerBudgetLimits, PlannerBudgetTracker
from .llm import PlannerLLM, PlannerLLMConfig
from .models import PlannerTerminationReason, PlannerTurnRecord
from .objectives import (
    CampaignMode,
    CampaignObjective,
    ObjectiveProgress,
    ObjectiveTracker,
    build_campaign_objective,
)
from .runtime import AttackDependencyGraph, SearchTreeState, build_planner_state
from .selection import PlannerDecisionEngine
from .storage import PlannerArtifactStore
from .synthesis import CandidateSynthesizer, enrich_state_from_observation, state_to_conditions


@dataclass(slots=True)
class PlannerSession:
    """Mutable planner campaign state."""

    session_id: str
    target_name: str
    current_state: dict[str, Any]
    tree: SearchTreeState
    graph: AttackDependencyGraph
    memory_store: MemoryStore
    processed_observation_ids: set[str] = field(default_factory=set)
    turns: list[PlannerTurnRecord] = field(default_factory=list)
    request_counter: int = 0
    completed: bool = False
    termination_reason: PlannerTerminationReason | None = None
    success_conditions: tuple[str, ...] = ()
    objective: CampaignObjective | None = None
    budget_tracker: PlannerBudgetTracker = field(default_factory=PlannerBudgetTracker)

    def next_request_id(self) -> str:
        self.request_counter += 1
        return f"{self.session_id}-req-{self.request_counter:04d}"

    def next_turn_index(self) -> int:
        return len(self.turns) + 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "current_state": self.current_state,
            "processed_observation_ids": sorted(self.processed_observation_ids),
            "completed": self.completed,
            "termination_reason": self.termination_reason,
            "success_conditions": self.success_conditions,
            "objective": None
            if self.objective is None
            else {
                "mode": self.objective.mode,
                "objective_summary": self.objective.objective_summary,
                "success_indicators": self.objective.success_indicators,
                "partial_progress_markers": self.objective.partial_progress_markers,
            },
            "budget": self.budget_tracker.snapshot(),
            "request_counter": self.request_counter,
            "turns": [asdict(turn) for turn in self.turns],
        }


@dataclass(frozen=True, slots=True)
class _ObservationProxy:
    content: str
    evidence: Any


class Planner:
    """Coordinate the search tree, dependency graph, executor, and Perceptor."""

    def __init__(
        self,
        *,
        repo_root,
        registry: SpecRegistry,
        executor: Executor,
        perceptor: Perceptor,
        artifact_store: PlannerArtifactStore | None = None,
        knowledge_manifest: KnowledgeManifest | None = None,
        synthesizer: CandidateSynthesizer | None = None,
        hypothesis_llm: PlannerLLM | None = None,
        hypothesis_llm_config: PlannerLLMConfig | Mapping[str, Any] | None = None,
        bootstrap_policy: BootstrapPolicy | None = None,
        selector: PlannerDecisionEngine | None = None,
        budget_limits: PlannerBudgetLimits | None = None,
        max_turns: int = 10,
    ) -> None:
        self.repo_root = repo_root
        self.registry = registry
        self.executor = executor
        self.perceptor = perceptor
        self.artifact_store = artifact_store or PlannerArtifactStore(repo_root=repo_root)
        self.memory_artifact_store = MemoryArtifactStore(repo_root=repo_root)
        self.bootstrap_policy = bootstrap_policy or BootstrapPolicy(repo_root=repo_root)
        self.objective_tracker = ObjectiveTracker()
        manifest = knowledge_manifest or load_knowledge_manifest(repo_root)
        self.synthesizer = synthesizer or CandidateSynthesizer(
            manifest,
            llm=hypothesis_llm,
            llm_config=hypothesis_llm_config,
        )
        self.selector = selector or PlannerDecisionEngine(registry)
        self.budget_limits = budget_limits or PlannerBudgetLimits()
        self.max_turns = max_turns
        self.artifact_store.initialize()
        self.memory_artifact_store.initialize()

    def start_session(
        self,
        *,
        session_id: str,
        target_url: str,
        target_host: str | None = None,
        target_name: str | None = None,
        initial_context: dict[str, Any] | None = None,
        success_conditions: tuple[str, ...] = (),
        campaign_mode: CampaignMode | None = None,
        objective_summary: str | None = None,
    ) -> PlannerSession:
        """Initialize planner state for a new target."""

        resolved_state = dict(initial_context or {})
        resolved_state.setdefault("target_url", target_url)
        parsed = urlparse(target_url)
        if target_host is not None:
            resolved_state["target_host"] = target_host
        elif parsed.hostname:
            resolved_state.setdefault("target_host", parsed.hostname)
        resolved_state, bootstrap_analysis = self.bootstrap_policy.apply(resolved_state)
        resolved_target_name = target_name or resolved_state.get("target_host") or target_url
        tree, graph = build_planner_state(
            repo_root=self.repo_root,
            session_id=session_id,
            target_name=resolved_target_name,
            target_summary=target_url,
        )
        graph.ingest_observation(
            observation_node_id=tree.root_node_id,
            satisfied_conditions=state_to_conditions(resolved_state),
        )
        session = PlannerSession(
            session_id=session_id,
            target_name=resolved_target_name,
            current_state=resolved_state,
            tree=tree,
            graph=graph,
            memory_store=MemoryStore(session_id=session_id, target_name=resolved_target_name),
            success_conditions=success_conditions,
            objective=build_campaign_objective(campaign_mode, objective_summary=objective_summary)
            if campaign_mode is not None
            else None,
            budget_tracker=PlannerBudgetTracker(limits=self.budget_limits),
        )
        session.memory_store.add_record(
            kind="fact",
            summary="Target root",
            content=target_url,
            source_key=f"root:{session_id}",
            tags=("target",),
            planner_node_id=tree.root_node_id,
            evidence_refs=(f"url:{target_url}",),
        )
        bootstrap_artifact = self.artifact_store.persist_bootstrap_analysis(
            session_id=session.session_id,
            target_name=session.target_name,
            analysis_name="session-start",
            payload=bootstrap_analysis.as_payload(),
        )
        session.tree.update_metadata(
            session.tree.root_node_id,
            bootstrap_trace_artifact=bootstrap_artifact.relative_path,
            bootstrap_missing_state=bootstrap_analysis.missing_state_keys,
            bootstrap_defaults=bootstrap_analysis.defaulted_state,
        )
        self.persist_session_state(session)
        return session

    def synthesize_candidates(self, session: PlannerSession) -> int:
        """Process unsynthesized observations into hypothesis candidates."""

        created = 0
        processed_any = False
        for observation in self._unsynthesized_observations(session):
            session.current_state = enrich_state_from_observation(session.current_state, observation)
            session.current_state, bootstrap_analysis = self.bootstrap_policy.apply(session.current_state)
            session.graph.ingest_observation(
                observation_node_id=observation.node_id,
                evidence=observation.evidence,
                satisfied_conditions=state_to_conditions(session.current_state),
            )
            memory_hits = session.memory_store.search(
                MemoryQuery(
                    goal=observation.content,
                    keywords=tuple(
                        str(item)
                        for item in (
                            *observation.evidence.urls,
                            *observation.evidence.file_paths,
                            *observation.evidence.ports,
                        )
                    ),
                    limit=5,
                )
            )
            result = self.synthesizer.ingest(
                tree=session.tree,
                graph=session.graph,
                current_state=session.current_state,
                observation=observation,
                memory_hits=memory_hits,
            )
            session.budget_tracker.record_llm_usage(
                prompt_tokens=result.trace.llm_prompt_tokens,
                completion_tokens=result.trace.llm_completion_tokens,
                total_tokens=result.trace.llm_total_tokens,
                cost_cny=result.trace.llm_cost_cny,
                latency_seconds=result.trace.llm_latency_seconds,
            )
            session.memory_store.ingest_candidate_proposals(
                observation_node_id=observation.node_id,
                proposals=result.proposals,
            )
            trace_artifact = self.artifact_store.persist_hypothesis_trace(
                session_id=session.session_id,
                target_name=session.target_name,
                observation_node_id=observation.node_id,
                payload=result.trace.as_payload(),
            )
            bootstrap_artifact = self.artifact_store.persist_bootstrap_analysis(
                session_id=session.session_id,
                target_name=session.target_name,
                analysis_name=observation.node_id,
                payload=bootstrap_analysis.as_payload(),
            )
            session.tree.update_metadata(
                observation.node_id,
                hypothesis_trace_artifact=trace_artifact.relative_path,
                bootstrap_trace_artifact=bootstrap_artifact.relative_path,
                bootstrap_missing_state=bootstrap_analysis.missing_state_keys,
                bootstrap_defaults=bootstrap_analysis.defaulted_state,
            )
            session.processed_observation_ids.add(observation.node_id)
            processed_any = True
            created += len(result.proposals)
            if session.budget_tracker.limit_hit is not None:
                break
        if processed_any:
            self.persist_session_state(session)
        return created

    def plan_next_action(self, session: PlannerSession) -> tuple[ExecutionRequest | None, PlannerTurnRecord | None]:
        """Select and materialize the next execution request, if any."""

        outcome = self.selector.choose(session)
        ranking_order = tuple(evaluation.candidate_id for evaluation in session.graph.rank_candidates())
        turn_index = session.next_turn_index()
        if outcome.selection is None:
            record = PlannerTurnRecord(
                turn_index=turn_index,
                status="stopped",
                termination_reason=outcome.termination_reason,
                ranking_order=ranking_order,
                notes="Planner frontier has no executable candidate.",
            )
            session.turns.append(record)
            session.completed = True
            session.termination_reason = outcome.termination_reason
            self.persist_session_state(session)
            return None, record
        request = self.selector.build_execution_request(outcome.selection)
        record = PlannerTurnRecord(
            turn_index=turn_index,
            status="executed",
            candidate_id=outcome.selection.candidate_id,
            request_id=request.request_id,
            action_node_id=outcome.selection.action_node_id,
            target_name=outcome.selection.target_name,
            ranking_order=ranking_order,
        )
        return request, record

    def run_turn(self, session: PlannerSession) -> PlannerTurnRecord:
        """Run one full planner turn including execution and Perceptor feedback."""

        if session.completed:
            raise RuntimeError("Planner session already completed")
        if len(session.turns) >= self.max_turns:
            record = PlannerTurnRecord(
                turn_index=session.next_turn_index(),
                status="stopped",
                termination_reason="max-turns-reached",
                notes="Planner reached the configured turn limit.",
            )
            session.turns.append(record)
            session.completed = True
            session.termination_reason = "max-turns-reached"
            self.persist_session_state(session)
            return record

        budget_record = self._budget_stop_record(session)
        if budget_record is not None:
            session.turns.append(budget_record)
            session.completed = True
            session.termination_reason = "budget-limit-reached"
            self.persist_session_state(session, turn_record=budget_record)
            return budget_record

        self.synthesize_candidates(session)
        completion_reason, _objective_progress = self._completion_status(session)
        if completion_reason is not None:
            record = PlannerTurnRecord(
                turn_index=session.next_turn_index(),
                status="stopped",
                termination_reason=completion_reason,
                notes="Planner objective or success conditions are already satisfied.",
            )
            session.turns.append(record)
            session.completed = True
            session.termination_reason = completion_reason
            self.persist_session_state(session)
            return record

        budget_record = self._budget_stop_record(session)
        if budget_record is not None:
            session.turns.append(budget_record)
            session.completed = True
            session.termination_reason = "budget-limit-reached"
            self.persist_session_state(session, turn_record=budget_record)
            return budget_record

        request, planned_record = self.plan_next_action(session)
        if request is None or planned_record is None:
            return session.turns[-1]

        execution_started_at = perf_counter()
        execution_result = self.executor.execute(request)
        execution_elapsed = perf_counter() - execution_started_at
        session.budget_tracker.record_execution(
            result=execution_result,
            fallback_tool_invocations=1,
            fallback_elapsed_seconds=execution_elapsed,
        )
        perception = self.perceptor.perceive(
            execution_result,
            planner_node_id=request.planner_node_id,
        )
        observation = session.tree.ingest_planner_feedback(
            action_node_id=request.planner_node_id or "",
            feedback=perception.planner_feedback,
        )
        session.current_state = self._merge_state_from_perception(session.current_state, perception)
        session.graph.record_action_outcome(
            candidate_id=planned_record.candidate_id or "",
            action_node_id=planned_record.action_node_id or "",
            status="succeeded" if execution_result.status == "succeeded" else "failed",
            produced_effects=session.tree.nodes[planned_record.action_node_id or ""].metadata.get("effects", ()),
        )
        session.graph.ingest_observation(
            observation_node_id=observation.node_id,
            evidence=perception.planner_feedback.evidence,
            satisfied_conditions=state_to_conditions(session.current_state),
        )
        executed_record = PlannerTurnRecord(
            turn_index=planned_record.turn_index,
            status="executed",
            candidate_id=planned_record.candidate_id,
            request_id=planned_record.request_id,
            action_node_id=planned_record.action_node_id,
            observation_node_id=observation.node_id,
            target_name=planned_record.target_name,
            ranking_order=planned_record.ranking_order,
        )
        session.turns.append(executed_record)
        completion_reason, _objective_progress = self._completion_status(session)
        if completion_reason is not None:
            session.completed = True
            session.termination_reason = completion_reason
        elif session.budget_tracker.limit_hit is not None:
            session.completed = True
            session.termination_reason = "budget-limit-reached"
        session.memory_store.ingest_memory_staging(perception.memory_record)
        session.memory_store.ingest_turn_result(
            turn_record=executed_record,
            tree=session.tree,
            graph=session.graph,
        )
        session.memory_store.ingest_contradictions(graph=session.graph)
        session.memory_store.ingest_objective_progress(self._objective_progress(session))
        self.persist_session_state(session, turn_record=executed_record)
        return executed_record

    def run(self, session: PlannerSession) -> PlannerSession:
        """Run the planner until it reaches a deterministic stop condition."""

        while not session.completed:
            self.run_turn(session)
        return session

    def persist_session_state(
        self,
        session: PlannerSession,
        *,
        turn_record: PlannerTurnRecord | None = None,
    ) -> None:
        """Persist tree, graph, ranking, and session-level snapshots."""

        self.artifact_store.persist_search_tree(session.tree)
        self.artifact_store.persist_dependency_graph(session.graph)
        self.artifact_store.persist_candidate_rankings(session.graph)
        self.artifact_store.persist_session_snapshot(session)
        self.artifact_store.persist_budget_snapshot(
            session_id=session.session_id,
            target_name=session.target_name,
            payload=session.budget_tracker.snapshot(),
        )
        self.memory_artifact_store.persist_store(session.memory_store)
        self.memory_artifact_store.persist_retrieval_index(session.memory_store)
        objective_progress = self._objective_progress(session)
        if objective_progress is not None:
            self.artifact_store.persist_objective_progress(
                session_id=session.session_id,
                target_name=session.target_name,
                payload=objective_progress.as_payload(),
            )
        if turn_record is not None:
            self.artifact_store.persist_turn_record(
                session_id=session.session_id,
                target_name=session.target_name,
                turn_record=turn_record,
            )

    def _completion_status(
        self,
        session: PlannerSession,
    ) -> tuple[PlannerTerminationReason | None, ObjectiveProgress | None]:
        objective_progress = self._objective_progress(session)
        if objective_progress is not None and objective_progress.succeeded:
            return "objective-met", objective_progress
        if self._success_conditions_met(session):
            return "success-condition-met", objective_progress
        return None, objective_progress

    def _success_conditions_met(self, session: PlannerSession) -> bool:
        if not session.success_conditions:
            return False
        return all(condition in session.graph.satisfied_conditions for condition in session.success_conditions)

    def _objective_progress(self, session: PlannerSession) -> ObjectiveProgress | None:
        return self.objective_tracker.evaluate(session)

    def _budget_stop_record(self, session: PlannerSession) -> PlannerTurnRecord | None:
        limit_hit = session.budget_tracker.evaluate()
        if limit_hit is None:
            return None
        return PlannerTurnRecord(
            turn_index=session.next_turn_index(),
            status="stopped",
            termination_reason="budget-limit-reached",
            notes=(
                f"Planner budget limit reached: {limit_hit.limit_name} "
                f"{limit_hit.observed_value:.6f}/{limit_hit.limit_value:.6f}."
            ),
        )

    def _unsynthesized_observations(self, session: PlannerSession):
        observations = [
            node
            for node in session.tree.nodes.values()
            if node.kind == "observation" and node.node_id not in session.processed_observation_ids
        ]
        observations.sort(key=lambda node: node.node_id)
        return tuple(observations)

    def _merge_state_from_perception(
        self,
        current_state: dict[str, Any],
        perception: PerceptionResult,
    ) -> dict[str, Any]:
        return enrich_state_from_observation(
            current_state,
            _ObservationProxy(
                content=perception.summary,
                evidence=perception.planner_feedback.evidence,
            ),
        )
