"""Structured report assembly and rendering helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AttackChainStep, CampaignReport, RenderedReport, ReportFinding, ReportFormat, ReportSeverity
from .storage import ReportArtifactStore


_SEVERITY_BY_TARGET: dict[str, ReportSeverity] = {
    "service-enumeration": "info",
    "web-surface-mapping": "info",
    "content-discovery": "low",
    "sqli-verification": "high",
    "credential-reuse-check": "high",
    "password-spray-validation": "high",
    "asrep-roast-collection": "medium",
    "kerberoast-collection": "medium",
    "local-privesc-enum": "high",
}

_CATEGORY_BY_TARGET: dict[str, str] = {
    "service-enumeration": "reconnaissance",
    "web-surface-mapping": "reconnaissance",
    "content-discovery": "surface-exposure",
    "sqli-verification": "injection",
    "credential-reuse-check": "credential-access",
    "password-spray-validation": "credential-access",
    "asrep-roast-collection": "kerberos",
    "kerberoast-collection": "kerberos",
    "local-privesc-enum": "privilege-escalation",
}


def assemble_report(*, repo_root: Path, session_dir: Path) -> CampaignReport:
    """Assemble a normalized report from one persisted planner session directory."""

    resolved_session_dir = _resolve_session_dir(repo_root=repo_root, session_dir=session_dir)
    session_payload = _read_json(resolved_session_dir / "session.json")
    tree_payload = _read_json(resolved_session_dir / "search-tree.json")
    graph_payload = _read_json(resolved_session_dir / "dependency-graph.json")
    objective_payload = _read_optional_json(resolved_session_dir / "objective-progress.json")
    nodes = tree_payload.get("nodes", {})
    candidates = graph_payload.get("candidates", {})
    turns = list(session_payload.get("turns", []))
    attack_chain: list[AttackChainStep] = []
    findings: list[ReportFinding] = []
    executed_turns = [turn for turn in turns if turn.get("status") == "executed"]
    final_executed_turn = executed_turns[-1]["turn_index"] if executed_turns else None
    for index, turn in enumerate(executed_turns, start=1):
        action_node = nodes.get(turn.get("action_node_id"))
        observation_node = nodes.get(turn.get("observation_node_id"))
        candidate = candidates.get(turn.get("candidate_id"), {})
        target_name = turn.get("target_name") or _node_metadata(action_node).get("action_target_name")
        title = (action_node or {}).get("title") or candidate.get("summary") or f"Step {index}"
        observation_text = None if observation_node is None else observation_node.get("content")
        summary = observation_text or candidate.get("summary") or (action_node or {}).get("content") or title
        evidence_refs = _node_evidence_refs(observation_node)
        artifact_paths = tuple(sorted(set((observation_node or {}).get("source_artifact_paths", ()))))
        attack_chain.append(
            AttackChainStep(
                step_index=index,
                turn_index=int(turn["turn_index"]),
                title=str(title),
                action_kind=_node_metadata(action_node).get("action_kind"),
                target_name=target_name,
                candidate_id=turn.get("candidate_id"),
                summary=str(summary),
                observation=observation_text,
                evidence_refs=evidence_refs,
                artifact_paths=artifact_paths,
            )
        )
        findings.append(
            ReportFinding(
                finding_id=f"finding-{index:04d}",
                title=str(title),
                description=str(summary),
                severity=_finding_severity(
                    target_name=target_name,
                    objective_payload=objective_payload,
                    turn_index=int(turn["turn_index"]),
                    final_turn_index=final_executed_turn,
                ),
                status="confirmed" if candidate.get("status") == "succeeded" else "attempted",
                category=_CATEGORY_BY_TARGET.get(str(target_name), "general"),
                target_name=None if target_name is None else str(target_name),
                candidate_id=turn.get("candidate_id"),
                turn_index=int(turn["turn_index"]),
                evidence_refs=evidence_refs,
                artifact_paths=artifact_paths,
            )
        )
    session_objective = session_payload.get("objective") or {}
    objective_summary = (
        None
        if objective_payload is None
        else objective_payload.get("objective_summary")
    ) or session_objective.get("objective_summary")
    objective_met = bool(objective_payload and objective_payload.get("succeeded"))
    summary_notes = _summary_notes(
        objective_met=objective_met,
        termination_reason=session_payload.get("termination_reason"),
        findings=findings,
    )
    return CampaignReport(
        session_id=str(session_payload["session_id"]),
        target_name=str(session_payload["target_name"]),
        session_dir=resolved_session_dir.relative_to(repo_root).as_posix(),
        target_url=session_payload.get("current_state", {}).get("target_url"),
        objective_summary=None if objective_summary in (None, "") else str(objective_summary),
        objective_met=objective_met,
        termination_reason=session_payload.get("termination_reason"),
        turn_count=len(turns),
        findings=tuple(findings),
        attack_chain=tuple(attack_chain),
        summary_notes=summary_notes,
    )


def render_report(report: CampaignReport, *, report_format: ReportFormat) -> str:
    """Render the normalized report to the selected format."""

    if report_format == "json":
        return json.dumps(report.as_payload(), indent=2, sort_keys=True)
    if report_format == "markdown":
        return _render_markdown(report)
    raise ValueError(f"Unsupported report format: {report_format}")


def write_report(
    *,
    repo_root: Path,
    report: CampaignReport,
    report_format: ReportFormat,
    output_path: Path | None = None,
) -> RenderedReport:
    """Render and persist a report."""

    store = ReportArtifactStore(repo_root=repo_root)
    resolved_output_path = output_path or store.default_output_path(
        session_id=report.session_id,
        target_name=report.target_name,
        report_format=report_format,
    )
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_report(report, report_format=report_format)
    resolved_output_path.write_text(content, encoding="utf-8")
    return RenderedReport(
        report_format=report_format,
        content=content,
        output_path=resolved_output_path.as_posix(),
    )


def _resolve_session_dir(*, repo_root: Path, session_dir: Path) -> Path:
    candidate = session_dir if session_dir.is_absolute() else repo_root / session_dir
    if not candidate.exists():
        raise FileNotFoundError(f"Session directory does not exist: {candidate}")
    if not candidate.is_dir():
        raise NotADirectoryError(f"Session directory is not a directory: {candidate}")
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json(path)


def _node_metadata(node: dict[str, Any] | None) -> dict[str, Any]:
    if not node:
        return {}
    metadata = node.get("metadata", {})
    if isinstance(metadata, dict):
        return metadata
    return {}


def _node_evidence_refs(node: dict[str, Any] | None) -> tuple[str, ...]:
    if not node:
        return ()
    evidence = node.get("evidence", {})
    refs = {
        *(f"url:{value}" for value in evidence.get("urls", []) or []),
        *(f"port:{value}" for value in evidence.get("ports", []) or []),
        *(f"status:{value}" for value in evidence.get("status_codes", []) or []),
        *(f"path:{value}" for value in evidence.get("file_paths", []) or []),
    }
    return tuple(sorted(refs))


def _finding_severity(
    *,
    target_name: str | None,
    objective_payload: dict[str, Any] | None,
    turn_index: int,
    final_turn_index: int | None,
) -> ReportSeverity:
    if (
        objective_payload is not None
        and objective_payload.get("succeeded")
        and final_turn_index is not None
        and turn_index == final_turn_index
    ):
        mode = objective_payload.get("mode")
        if mode == "real-world":
            return "critical"
        if mode == "ctf":
            return "high"
    if target_name is None:
        return "unknown"
    return _SEVERITY_BY_TARGET.get(str(target_name), "unknown")


def _summary_notes(
    *,
    objective_met: bool,
    termination_reason: str | None,
    findings: list[ReportFinding],
) -> tuple[str, ...]:
    notes: list[str] = []
    if objective_met:
        notes.append("Campaign objective was met with explicit evidence.")
    elif termination_reason:
        notes.append(f"Campaign terminated with reason: {termination_reason}.")
    else:
        notes.append("Campaign did not record an explicit objective outcome.")
    notes.append(f"Structured findings extracted: {len(findings)}.")
    return tuple(notes)


def _render_markdown(report: CampaignReport) -> str:
    lines = [
        f"# DAPT Report: {report.target_name}",
        "",
        "## Summary",
        "",
        f"- Session ID: `{report.session_id}`",
        f"- Target URL: `{report.target_url or 'unknown'}`",
        f"- Objective: {report.objective_summary or 'not specified'}",
        f"- Objective met: `{'yes' if report.objective_met else 'no'}`",
        f"- Termination reason: `{report.termination_reason or 'unknown'}`",
        f"- Turns recorded: `{report.turn_count}`",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("- No structured findings were assembled from the persisted artifacts.")
    else:
        for finding in report.findings:
            lines.extend(
                [
                    f"### {finding.finding_id}: {finding.title}",
                    "",
                    f"- Category: `{finding.category}`",
                    f"- Severity: `{finding.severity}`",
                    f"- Status: `{finding.status}`",
                    f"- Target: `{finding.target_name or 'unknown'}`",
                    f"- Description: {finding.description}",
                    f"- Evidence refs: {', '.join(finding.evidence_refs) if finding.evidence_refs else 'none'}",
                    f"- Artifact paths: {', '.join(finding.artifact_paths) if finding.artifact_paths else 'none'}",
                    "",
                ]
            )
    lines.extend(["## Attack Chain", ""])
    if not report.attack_chain:
        lines.append("No executed attack-chain steps were recorded.")
    else:
        for step in report.attack_chain:
            lines.extend(
                [
                    f"{step.step_index}. `{step.target_name or 'unknown'}`: {step.summary}",
                    f"   - Turn: `{step.turn_index}`",
                    f"   - Evidence refs: {', '.join(step.evidence_refs) if step.evidence_refs else 'none'}",
                    f"   - Artifact paths: {', '.join(step.artifact_paths) if step.artifact_paths else 'none'}",
                ]
            )
    lines.extend(["", "## Notes", ""])
    for note in report.summary_notes:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
