"""Objective-mode contracts and evidence-aware objective tracking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CampaignMode = Literal["ctf", "real-world"]

_CTF_FLAG_PATTERN = re.compile(r"(?i)\b(?:flag|ctf)\{[^}\n]+\}")
_ROOT_PATTERNS = (
    re.compile(r"(?i)\buid=0\b"),
    re.compile(r"(?i)\beuid=0\b"),
    re.compile(r"(?i)\bwhoami:\s*root\b"),
    re.compile(r"(?i)\broot shell\b"),
    re.compile(r"(?i)\bnt authority\\\\system\b"),
    re.compile(r"(?i)\badministrator shell\b"),
)


@dataclass(frozen=True, slots=True)
class CampaignObjective:
    """Declared planner objective for a campaign mode."""

    mode: CampaignMode
    objective_summary: str
    success_indicators: tuple[str, ...]
    partial_progress_markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObjectiveProgress:
    """Current progress toward the campaign objective."""

    mode: CampaignMode
    objective_summary: str
    succeeded: bool
    success_indicator: str | None = None
    matched_observation_ids: tuple[str, ...] = ()
    partial_progress_markers: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "objective_summary": self.objective_summary,
            "succeeded": self.succeeded,
            "success_indicator": self.success_indicator,
            "matched_observation_ids": list(self.matched_observation_ids),
            "partial_progress_markers": list(self.partial_progress_markers),
            "notes": list(self.notes),
        }


def build_campaign_objective(mode: CampaignMode, *, objective_summary: str | None = None) -> CampaignObjective:
    """Return the default objective contract for the selected campaign mode."""

    if mode == "ctf":
        return CampaignObjective(
            mode=mode,
            objective_summary=objective_summary or "Capture the target flag.",
            success_indicators=("flag{...}", "ctf{...}"),
            partial_progress_markers=("content-discovery", "credential-access", "shell-access"),
        )
    return CampaignObjective(
        mode=mode,
        objective_summary=objective_summary or "Obtain root or administrator-equivalent access.",
        success_indicators=("uid=0", "root shell", "NT AUTHORITY\\SYSTEM"),
        partial_progress_markers=("credential-access", "shell-access", "privesc-enumerated"),
    )


class ObjectiveTracker:
    """Evaluate objective completion from explicit planner evidence."""

    def evaluate(self, session) -> ObjectiveProgress | None:
        objective = getattr(session, "objective", None)
        if objective is None:
            return None
        observations = [
            node
            for node in session.tree.nodes.values()
            if node.kind == "observation"
        ]
        observations.sort(key=lambda node: node.node_id)
        if objective.mode == "ctf":
            matched_ids: list[str] = []
            indicator: str | None = None
            for observation in observations:
                match = _CTF_FLAG_PATTERN.search(observation.content)
                if match:
                    matched_ids.append(observation.node_id)
                    indicator = match.group(0)
            partials = _partial_progress_markers(session)
            return ObjectiveProgress(
                mode=objective.mode,
                objective_summary=objective.objective_summary,
                succeeded=indicator is not None,
                success_indicator=indicator,
                matched_observation_ids=tuple(matched_ids),
                partial_progress_markers=partials,
                notes=("Objective is satisfied only by explicit flag evidence.",),
            )

        matched_ids = []
        indicator = None
        for observation in observations:
            for pattern in _ROOT_PATTERNS:
                match = pattern.search(observation.content)
                if match:
                    matched_ids.append(observation.node_id)
                    indicator = match.group(0)
                    break
        partials = _partial_progress_markers(session)
        return ObjectiveProgress(
            mode=objective.mode,
            objective_summary=objective.objective_summary,
            succeeded=indicator is not None,
            success_indicator=indicator,
            matched_observation_ids=tuple(matched_ids),
            partial_progress_markers=partials,
            notes=("Objective is satisfied only by explicit root or administrator-equivalent evidence.",),
        )


def _partial_progress_markers(session) -> tuple[str, ...]:
    markers: set[str] = set()
    if "effect:content-discovered" in session.graph.satisfied_conditions:
        markers.add("content-discovery")
    if "effect:credential-reuse-validated" in session.graph.satisfied_conditions:
        markers.add("credential-access")
    if "effect:local-privesc-enumerated" in session.graph.satisfied_conditions:
        markers.add("privesc-enumerated")
    if session.current_state.get("local_shell"):
        markers.add("shell-access")
    return tuple(sorted(markers))
