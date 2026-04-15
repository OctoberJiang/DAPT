"""Repo-local storage layout for planner state artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import PlannerArtifact, PlannerTurnRecord
from .runtime import AttackDependencyGraph, SearchTreeState


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "planner"


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    return value


class PlannerArtifactStore:
    """Persistence helper for planner tree and dependency graph snapshots."""

    def __init__(self, repo_root: Path, root_dir_name: str = "artifacts/planner") -> None:
        self.repo_root = repo_root
        self.root_dir_name = root_dir_name

    @property
    def base_dir(self) -> Path:
        return self.repo_root / self.root_dir_name

    def initialize(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def session_dir(self, session_id: str, target_name: str) -> Path:
        return self.base_dir / f"{session_id}-{_slugify(target_name)}"

    def persist_search_tree(self, tree: SearchTreeState) -> PlannerArtifact:
        """Persist a search-tree snapshot."""

        return self._write_json(
            session_id=tree.session_id,
            target_name=tree.target_name,
            artifact_name="search-tree",
            payload=tree.snapshot(),
        )

    def persist_dependency_graph(self, graph: AttackDependencyGraph) -> PlannerArtifact:
        """Persist a dependency-graph snapshot."""

        return self._write_json(
            session_id=graph.session_id,
            target_name=graph.target_name,
            artifact_name="dependency-graph",
            payload=graph.snapshot(),
        )

    def persist_candidate_rankings(self, graph: AttackDependencyGraph) -> PlannerArtifact:
        """Persist the current candidate ranking view."""

        payload = {
            "session_id": graph.session_id,
            "target_name": graph.target_name,
            "rankings": [asdict(evaluation) for evaluation in graph.rank_candidates()],
        }
        return self._write_json(
            session_id=graph.session_id,
            target_name=graph.target_name,
            artifact_name="candidate-rankings",
            payload=payload,
        )

    def persist_session_snapshot(self, session) -> PlannerArtifact:
        """Persist the top-level planner session snapshot."""

        return self._write_json(
            session_id=session.session_id,
            target_name=session.target_name,
            artifact_name="session",
            payload=session.snapshot(),
        )

    def persist_hypothesis_trace(
        self,
        *,
        session_id: str,
        target_name: str,
        observation_node_id: str,
        payload: dict[str, Any],
    ) -> PlannerArtifact:
        """Persist one auditable hypothesis-generation trace."""

        return self._write_json(
            session_id=session_id,
            target_name=target_name,
            artifact_name=f"hypothesis-trace-{observation_node_id}",
            payload=payload,
        )

    def persist_bootstrap_analysis(
        self,
        *,
        session_id: str,
        target_name: str,
        analysis_name: str,
        payload: dict[str, Any],
    ) -> PlannerArtifact:
        """Persist one bootstrap-state analysis snapshot."""

        return self._write_json(
            session_id=session_id,
            target_name=target_name,
            artifact_name=f"bootstrap-{analysis_name}",
            payload=payload,
        )

    def persist_objective_progress(
        self,
        *,
        session_id: str,
        target_name: str,
        payload: dict[str, Any],
    ) -> PlannerArtifact:
        """Persist the current objective-progress view."""

        return self._write_json(
            session_id=session_id,
            target_name=target_name,
            artifact_name="objective-progress",
            payload=payload,
        )

    def persist_budget_snapshot(
        self,
        *,
        session_id: str,
        target_name: str,
        payload: dict[str, Any],
    ) -> PlannerArtifact:
        """Persist the current budget and usage tracker snapshot."""

        return self._write_json(
            session_id=session_id,
            target_name=target_name,
            artifact_name="budget",
            payload=payload,
        )

    def persist_turn_record(
        self,
        *,
        session_id: str,
        target_name: str,
        turn_record: PlannerTurnRecord,
    ) -> PlannerArtifact:
        """Persist one planner turn record."""

        return self._write_json(
            session_id=session_id,
            target_name=target_name,
            artifact_name=f"turn-{turn_record.turn_index:04d}",
            payload=asdict(turn_record),
        )

    def _write_json(
        self,
        *,
        session_id: str,
        target_name: str,
        artifact_name: str,
        payload: dict[str, Any],
    ) -> PlannerArtifact:
        self.initialize()
        session_dir = self.session_dir(session_id, target_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{_slugify(artifact_name)}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
        return PlannerArtifact(
            session_id=session_id,
            name=artifact_name,
            relative_path=path.relative_to(self.repo_root).as_posix(),
            media_type="application/json",
        )
