"""Typed contracts for structured campaign reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

ReportSeverity = Literal["critical", "high", "medium", "low", "info", "unknown"]
FindingStatus = Literal["confirmed", "attempted", "unsupported"]
ReportFormat = Literal["json", "markdown"]


@dataclass(frozen=True, slots=True)
class ReportFinding:
    """One reportable finding grounded in repo-local artifacts."""

    finding_id: str
    title: str
    description: str
    severity: ReportSeverity
    status: FindingStatus
    category: str
    target_name: str | None = None
    candidate_id: str | None = None
    turn_index: int | None = None
    evidence_refs: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "category": self.category,
            "target_name": self.target_name,
            "candidate_id": self.candidate_id,
            "turn_index": self.turn_index,
            "evidence_refs": list(self.evidence_refs),
            "artifact_paths": list(self.artifact_paths),
        }


@dataclass(frozen=True, slots=True)
class AttackChainStep:
    """One ordered step in the completed or attempted attack chain."""

    step_index: int
    turn_index: int
    title: str
    action_kind: str | None
    target_name: str | None
    candidate_id: str | None
    summary: str
    observation: str | None = None
    evidence_refs: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "step_index": self.step_index,
            "turn_index": self.turn_index,
            "title": self.title,
            "action_kind": self.action_kind,
            "target_name": self.target_name,
            "candidate_id": self.candidate_id,
            "summary": self.summary,
            "observation": self.observation,
            "evidence_refs": list(self.evidence_refs),
            "artifact_paths": list(self.artifact_paths),
        }


@dataclass(frozen=True, slots=True)
class CampaignReport:
    """Normalized structured report assembled from repo-local artifacts."""

    session_id: str
    target_name: str
    session_dir: str
    target_url: str | None
    objective_summary: str | None
    objective_met: bool
    termination_reason: str | None
    turn_count: int
    findings: tuple[ReportFinding, ...]
    attack_chain: tuple[AttackChainStep, ...]
    summary_notes: tuple[str, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "session_dir": self.session_dir,
            "target_url": self.target_url,
            "objective_summary": self.objective_summary,
            "objective_met": self.objective_met,
            "termination_reason": self.termination_reason,
            "turn_count": self.turn_count,
            "findings": [finding.as_payload() for finding in self.findings],
            "attack_chain": [step.as_payload() for step in self.attack_chain],
            "summary_notes": list(self.summary_notes),
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class RenderedReport:
    """Rendered report output plus persistence metadata."""

    report_format: ReportFormat
    content: str
    output_path: str

    def as_payload(self) -> dict[str, object]:
        return {
            "report_format": self.report_format,
            "output_path": self.output_path,
        }
